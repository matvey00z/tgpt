from enum import IntEnum
import logging
import openai

MODEL = "gpt-3.5-turbo"

db = None


def set_token(token):
    openai.api_key = token


def set_db(new_db):
    global db
    db = new_db


async def request(user_id, content):
    response_message = "Error making request"
    try:
        conversation_id = await db.store_message(user_id, content, UserRole.USER.value)
        messages = await db.get_messages(conversation_id, drop_ids_callback)
        messages = [
            {"role": role2str(m["role"]), "content": m["content"]} for m in messages
        ]
        logging.debug(f"Conversation id {conversation_id} messages: {messages}")
        response = await openai.ChatCompletion.acreate(
            model=MODEL,
            messages=messages,
            temperature=0.3,
        )
        content = response.choices[0].message.content
        logging.debug(f"Conversation id {conversation_id} response: {content}")
        await db.store_message(user_id, content, int(UserRole.ASSISTANT))
        response_message = content
    except Exception as e:
        logging.exception("Error making request")
    return response_message


async def forget_conversation(user_id):
    await db.switch_conversation(user_id)


class UserRole(IntEnum):
    SYSTEM = 0
    ASSISTANT = 1
    USER = 2


def role2str(i):
    return UserRole(i).name.lower()


def drop_ids_callback(messages):
    return []
