from enum import IntEnum
import logging
import openai
import tiktoken
import time
import asyncio

import limiter

MODEL = "gpt-3.5-turbo"
MAX_TOKENS = 4096

LIMITS = {
    "requests": 60,
    "tokens": 60000,
}
LIMITS_INTERVAL_SEC = 60

db = None


async def get_limiter():
    if get_limiter.limiter is None:
        get_limiter.limiter = limiter.Limiter(LIMITS, LIMITS_INTERVAL_SEC)
    return get_limiter.limiter


get_limiter.limiter = None


def set_token(token):
    openai.api_key = token


def set_db(new_db):
    global db
    db = new_db


def set_limiter(new_limiter):
    global limiter
    limiter = new_limiter


async def limited(f, volume):
    try:
        limiter = await get_limiter()
        return await limiter.run(f, volume)
    except (
        openai.error.APIError,
        openai.error.Timeout,
        openai.error.TryAgain,
        openai.error.RateLimitError,
        openai.error.ServiceUnavailableError,
    ):
        logging.exception("Exception while making request, retry")
        await asyncio.sleep(1)
        return await limited(f, volume)
    except:
        logging.exception("Exception while making request, drop it")


async def adjust_limits(volume):
    limiter = await get_limiter()
    await limiter.alloc(volume)


async def request(user_id, content):
    response_message = "Error making request"
    try:
        conversation_id = await db.store_message(user_id, content, UserRole.USER.value)
        messages = await db.get_messages(conversation_id, drop_ids_callback)
        messages = [
            {"role": role2str(m["role"]), "content": m["content"]} for m in messages
        ]
        prompt_tokens = count_conversation_tokens(messages)
        timestamp = time.time_ns()
        request_id = await db.store_request(user_id, timestamp, prompt_tokens)
        logging.debug(f"Conversation id {conversation_id} messages: {messages}")
        volume = {
            "requests": 1,
            "tokens": prompt_tokens,
        }
        response = await limited(
            openai.ChatCompletion.acreate(
                model=MODEL,
                messages=messages,
                temperature=0.3,
            ),
            volume,
        )
        resp_timestamp = time.time_ns()
        resp_prompt_tokens = response["usage"]["prompt_tokens"]
        resp_completion_tokens = response["usage"]["completion_tokens"]
        await adjust_limits(
            {
                "tokens": max(
                    0, resp_prompt_tokens + resp_completion_tokens - prompt_tokens
                )
            }
        )
        content = response.choices[0].message.content
        request_info = {
            "conversation_id": conversation_id,
            "request_id": request_id,
            "duration_ms": (resp_timestamp - timestamp) / 1e6,
            "prompt_tokens": prompt_tokens,
            "resp_prompt_tokens": resp_prompt_tokens,
            "resp_completion_tokens": resp_completion_tokens,
            "content": content,
        }
        logging.debug(f"Request: {request_info}")
        await db.store_message(user_id, content, int(UserRole.ASSISTANT))
        await db.store_response(
            request_id, resp_timestamp, resp_prompt_tokens, resp_completion_tokens
        )
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
    max_tokens = int(
        MAX_TOKENS * 0.9
    )  # Set the max to 90% as our calculation is indicative
    droplist = []
    for message in messages[::-1]:
        tokens = count_message_tokens(message)
        max_tokens -= tokens
        if max_tokens >= 0:
            continue
        else:
            droplist.append(message["id"])
    if len(droplist) == len(messages):
        message_len = len(message["content"])
        tokens = count_message_tokens(message)
        logging.warn(
            f"Message too long! Message length: {message_len} tokens: {tokens}"
        )
    logging.debug(f"Dropping {len(droplist)} messages from conversation")
    return droplist


def get_encoding():
    try:
        encoding = tiktoken.encoding_for_model(MODEL)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return encoding


def count_message_tokens(message, encoding=get_encoding()):
    num_tokens = 0
    num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
    for key, value in message.items():
        if key not in ["role", "name", "content"]:
            continue
        if key == "role":
            num_tokens += 1
        else:
            num_tokens += len(encoding.encode(value))
        if key == "name":  # if there's a name, the role is omitted
            num_tokens += -1  # role is always required and always 1 token
    num_tokens += 2  # every reply is primed with <im_start>assistant
    return num_tokens


def count_conversation_tokens(messages, encoding=get_encoding()):
    num_tokens = 0
    for message in messages:
        num_tokens += count_message_tokens(message)
    return num_tokens
