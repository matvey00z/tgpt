from enum import IntEnum
import logging
import openai
from openai import AsyncOpenAI
import tiktoken
import time
import asyncio
import base64
from dataclasses import dataclass

import limiter

MODEL = "gpt-4o"
MODEL_DALLE = "dall-e-3"
MAX_TOKENS = 120000

LIMITS = {
    "requests": 10000,
    "tokens": 2000000,
    "dalle_3_hd": 15,
}
LIMITS_INTERVAL_SEC = 60

db = None


async def get_limiter():
    if get_limiter.limiter is None:
        get_limiter.limiter = limiter.Limiter(LIMITS, LIMITS_INTERVAL_SEC)
    return get_limiter.limiter


get_limiter.limiter = None


oai_client = None
def set_token(token):
    global oai_client
    oai_client = AsyncOpenAI(api_key = token)


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
        openai.APITimeoutError,
        openai.RateLimitError,
    ):
        logging.exception("Exception while making request, retry")
        await asyncio.sleep(1)
        return await limited(f, volume)
    except:
        logging.exception("Exception while making request, drop it")
        raise


async def adjust_limits(volume):
    limiter = await get_limiter()
    await limiter.alloc(volume)

@dataclass
class DalleResponse:
    revised_prompt: str
    image: str | None = None

async def dalle(user_id, content) -> DalleResponse | None:
    try:
        timestamp = time.time_ns()
        request_id = await db.store_request(user_id, timestamp, dalle_3_hd_count=1)
        logging.debug(f"User id {user_id} request dalle")
        volume = {
            "requests": 1,
            "dalle_3_hd": 1,
        }
        response = await limited(
            oai_client.images.generate(
                model=MODEL_DALLE,
                prompt=content,
                size="1024x1024",
                quality="hd",
                response_format="b64_json",
                n=1,
            ),
            volume
        )
        resp_timestamp = time.time_ns()
        await db.store_response_timestamp(request_id, resp_timestamp)
        image = response.data[0].b64_json
        image = base64.b64decode(image)
        revised_prompt = response.data[0].revised_prompt
        logging.debug(response.data[0])
        return DalleResponse(revised_prompt=revised_prompt, image=image)
    except openai.BadRequestError as e:
        logging.exception("Error making request: badrequest")
        return DalleResponse(revised_prompt=f"Bad request!\nCode: {e.code}")
    except Exception as e:
        logging.exception(f"Error making request: {e}")
    return None
        

async def get_models():
    response = await oai_client.models.list()
    logging.debug(response)
    models = [m for m in response.data]
    models = [m for m in models if m.owned_by != "openai-internal"]
    models = sorted(models, key=lambda m: m.created)
    return [{"model": m.id, "created": m.created} for m in models]


async def request(user_id, content):
    response_message = "Error making request"
    try:
        conversation_id = await db.store_message(user_id, content, UserRole.USER.value)
        model = await db.get_user_model(user_id)
        if model is None:
            model = MODEL
        messages = await db.get_messages(conversation_id, drop_ids_callback)
        messages = [
            {"role": role2str(m["role"]), "content": m["content"]} for m in messages
        ]
        prompt_tokens = count_conversation_tokens(messages)
        timestamp = time.time_ns()
        request_id = await db.store_request(user_id, timestamp, prompt_tokens=prompt_tokens)
        logging.debug(f"Conversation id {conversation_id} messages: {messages}")
        volume = {
            "requests": 1,
            "tokens": prompt_tokens,
        }
        response = await limited(
            oai_client.chat.completions.create(
                model=model,
                messages=messages,
            ),
            volume,
        )
        resp_timestamp = time.time_ns()
        resp_prompt_tokens = response.usage.prompt_tokens
        resp_completion_tokens = response.usage.completion_tokens
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
    await db.forget_conversation(user_id)

async def quit_conversation(user_id):
    await db.quit_conversation(user_id)

async def get_conversations_list(user_id):
    return await db.get_conversations_list(user_id)

async def select_conversation(user_id, conversation_id):
    title = await db.get_conversation_title(user_id, conversation_id)
    if title is not None:
        await db.set_current_conversation(user_id, conversation_id)
    return title


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


def get_encoding(model = MODEL):
    try:
        encoding = tiktoken.encoding_for_model(model)
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
