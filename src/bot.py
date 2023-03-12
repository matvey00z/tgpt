#!/usr/bin/env python3

import logging
import os
import asyncio
from telegram import Update
from telegram.ext import (
    filters,
    Application,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    AIORateLimiter,
)
import chatgpt
import db_handler


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)

db = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!"
    )


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tg_user_id = update.effective_user.id
        user_id = await db.get_user_id(tg_user_id)
        await chatgpt.forget_conversation(user_id)
        response = "All forgotten!"
    except Exception as e:
        logging.exception("Error handling forget")
        response = "Error making request"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tg_user_id = update.effective_user.id
        user_id = await db.get_user_id(tg_user_id)
        response = await chatgpt.request(user_id, update.message.text)
    except Exception as e:
        logging.exception("Error handling update")
        response = "Error making request"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


async def post_init(application: Application) -> None:
    global db
    db = await db_handler.DB.create(
        dbhost=os.environ["DBHOST"],
        dbname=os.environ["DBNAME"],
        dbuser=os.environ["DBUSER"],
        dbpass=os.environ["DBPASS"],
    )
    chatgpt.set_db(db)


def main():
    TG_TOKEN = os.environ["TG_TOKEN"]
    GPT_TOKEN = os.environ["GPT_TOKEN"]

    chatgpt.set_token(GPT_TOKEN)

    builder = ApplicationBuilder()
    builder.token(TG_TOKEN)
    builder.rate_limiter(AIORateLimiter())
    builder.post_init(post_init)
    application = builder.build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("forget", forget))

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), text_message)
    )

    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
