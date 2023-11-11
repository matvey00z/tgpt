import asyncpg
import logging


class DB:
    @classmethod
    async def create(cls, dbhost, dbname, dbuser, dbpass):
        db = DB()
        db.pool = await asyncpg.create_pool(
            user=dbuser, password=dbpass, database=dbname, host=dbhost
        )
        await db.create_tables()
        return db

    async def execute(self, query, values=None):
        async with self.pool.acquire() as conn:
            if values is None:
                await conn.execute(query)
            else:
                await conn.execute(query, values)

    async def create_tables(self):
        async def create_table(name, query, add_columns = []):
            await self.execute(f"CREATE TABLE IF NOT EXISTS {name} ( {query} )")
            for column in add_columns:
                await self.execute(f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS {column}")
            logging.info(f"Created table {name}")

        await create_table(
            "users",
            """
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE
            """,
        )

        await create_table(
            "conversations",
            """
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id)
            """,
            [
                "title TEXT",
            ]
        )

        await create_table(
            "current_conversations",
            """
            id INTEGER PRIMARY KEY REFERENCES conversations(id) UNIQUE,
            user_id INTEGER REFERENCES users(id) UNIQUE
            """
        )

        await create_table(
            "messages",
            """
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id),
            role INTEGER CHECK (role IN (0, 1, 2)),
            content TEXT
            """,
        )

        await create_table(
            "requests",
            """
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            request_timestamp BIGINT,
            response_timestamp BIGINT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER
            """,
            [
                "dalle_3_hd_count INTEGER"
            ]
        )

    async def add_user(self, tg_id):
        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval(
                """
                INSERT INTO users (tg_id) VALUES ($1)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                tg_id,
            )

    async def get_user_id(self, tg_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT id FROM users WHERE tg_id = $1", tg_id)

    async def get_current_conversation(self, user_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await conn.fetchval(
                    "SELECT id FROM current_conversations WHERE user_id = $1", user_id
                )
                return conversation_id

    async def store_message(self, user_id: int, content: str, role: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await self.get_current_conversation(user_id)
                if conversation_id is None:
                    title = get_title(content)
                    logging.debug(f"User id {user_id} title {title}")
                    conversation_id = await self.add_conversation(user_id, title)
                    assert conversation_id is not None
                    await self.set_current_conversation(user_id, conversation_id)

                message_id = await conn.fetchval(
                    """
                    INSERT INTO messages (conversation_id, role, content)
                    VALUES ($1, $2, $3)
                    RETURNING id""",
                    conversation_id,
                    role,
                    content,
                )
                assert message_id is not None

                return conversation_id

    async def get_messages(self, conversation_id, drop_ids_callback):
        async with self.pool.acquire() as conn:
            messages = await conn.fetch(
                """
                SELECT id, role, content FROM messages
                WHERE conversation_id = $1
                ORDER BY id
                """,
                conversation_id,
            )
            messages = [dict(m) for m in messages]
            drop_ids = drop_ids_callback(messages)
            if len(drop_ids) > 0:
                await conn.execute("DELETE FROM messages WHERE id = ANY($1)", drop_ids)
                messages = [m for m in messages if m["id"] not in drop_ids]
            return messages

    async def get_conversation_title(self, user_id, conversation_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT title FROM conversations WHERE id = $1 AND user_id = $2",
                    conversation_id, user_id
                )
                if row is None:
                    return None
                title = row.get("title")
                if title is None:
                    return get_default_title(conversation_id)
                return title

    async def add_conversation(self, user_id: int, title: str | None):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                new_conversation_id = await conn.fetchval(
                    "INSERT INTO conversations (user_id, title) VALUES ($1, $2) RETURNING id",
                    user_id, title
                )
                assert new_conversation_id is not None
                return new_conversation_id

    async def set_current_conversation(self, user_id, conversation_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO current_conversations (id, user_id)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO
                        UPDATE SET id = EXCLUDED.id
                    """,
                    conversation_id, user_id
                )

    async def quit_conversation(self, user_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await conn.fetchval(
                    """
                    DELETE FROM current_conversations
                    WHERE user_id = $1
                    RETURNING id
                    """,
                    user_id
                )
                return conversation_id

    async def forget_conversation(self, user_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await self.quit_conversation(user_id)
                if conversation_id is None:
                    return
                await conn.execute(
                    "DELETE FROM messages WHERE conversation_id = $1", conversation_id
                )
                await conn.execute(
                    "DELETE FROM conversations WHERE id = $1", conversation_id
                )
                

    async def get_conversations_list(self, user_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversations = await conn.fetch(
                    """
                    SELECT id, title FROM conversations
                    WHERE user_id = $1
                    ORDER BY id
                    LIMIT 10
                    """,
                    user_id
                )
                conversations = [dict(c) for c in conversations]
                current_conversation_id = await self.get_current_conversation(user_id)
                for conversation in conversations:
                    id = conversation["id"]
                    if conversation["title"] is None:
                        conversation["title"] = get_default_title(id)
                    if id == current_conversation_id:
                        conversation["current"] = True
                
                return conversations


    async def store_request(self, user_id, timestamp, prompt_tokens=0, dalle_3_hd_count=0):
        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval(
                """
                INSERT INTO requests (user_id, request_timestamp, prompt_tokens, dalle_3_hd_count)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                timestamp,
                prompt_tokens,
                dalle_3_hd_count,
            )
            assert request_id is not None
            return request_id

    async def store_response(
        self, request_id, timestamp, prompt_tokens, completion_tokens
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE requests
                SET response_timestamp = $1, prompt_tokens = $2, completion_tokens = $3
                WHERE id = $4
                """,
                timestamp,
                prompt_tokens,
                completion_tokens,
                request_id,
            )

    async def store_response_timestamp(
        self, request_id, timestamp
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE requests
                SET response_timestamp = $1
                WHERE id = $2
                """,
                timestamp,
                request_id,
            )
    

def get_title(message: str):
    max_title_len = 50
    words = message.split()
    title = []
    for word in words:
        if len(title) + len(word) > max_title_len:
            break
        title.append(word)

    if len(title) == 0:
        return None
    else:
        return " ".join(title)

def get_default_title(conversation_id):
    return f"Conversation {conversation_id}"
