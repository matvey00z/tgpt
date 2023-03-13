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
        async def create_table(name, query):
            await self.execute(f"CREATE TABLE IF NOT EXISTS {name} ( {query} )")
            logging.info(f"Created table {name}")

        await create_table(
            "users",
            """
            id SERIAL PRIMARY KEY,
            tg_id INTEGER UNIQUE
            """,
        )

        await create_table(
            "conversations",
            """
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id)
            """,
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
            timestamp INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER
            """,
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
            if user_id is not None:
                conversation_id = await conn.fetchval(
                    "INSERT INTO conversations (user_id) VALUES ($1) RETURNING id",
                    user_id,
                )
                assert conversation_id is not None

    async def get_user_id(self, tg_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT id FROM users WHERE tg_id = $1", tg_id)

    async def store_message(self, user_id: int, content: str, role: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await conn.fetchval(
                    "SELECT id FROM conversations WHERE user_id = $1", user_id
                )
                assert conversation_id is not None

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
                messages = [m for m in messages if m.id not in drop_ids]
            return messages

    async def switch_conversation(self, user_id: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                conversation_id = await conn.fetchval(
                    "SELECT id FROM conversations WHERE user_id = $1", user_id
                )
                assert conversation_id is not None
                new_conversation_id = await conn.fetchval(
                    "INSERT INTO conversations (user_id) VALUES ($1) RETURNING id",
                    user_id,
                )
                assert new_conversation_id is not None
                await conn.execute(
                    "DELETE FROM messages WHERE conversation_id = $1", conversation_id
                )
                await conn.execute(
                    "DELETE FROM conversations WHERE id = $1", conversation_id
                )
