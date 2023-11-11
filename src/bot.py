#!/usr/bin/env python3

import logging
import os
import asyncio
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update
)
from telegram.ext import (
    filters,
    Application,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    AIORateLimiter,
)
import chatgpt
import db_handler


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

db = None


async def auth(update: Update):
    tg_user_id = update.effective_user.id
    user_id = await db.get_user_id(tg_user_id)
    if user_id is None:
        logging.warn(f"Message from unknown user: tg_id: {tg_user_id}")
    return user_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = await auth(update)
        if user_id is None:
            text = f"Your id is {update.effective_user.id}, please talk to the admin to get the access."
        else:
            text = "Hi there! Feel free to talk with ChatGPT here."
    except:
        logging.exception("Error handling /start")
        text = "Error making request"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = await auth(update)
        if user_id is None:
            return
        await chatgpt.forget_conversation(user_id)
        response = "All forgotten!"
    except Exception as e:
        logging.exception("Error handling /forget")
        response = "Error making request"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = await auth(update)
        if user_id is None:
            return
        await chatgpt.quit_conversation(user_id)
        response = "New conversation started"
    except Exception as e:
        logging.exception("Error handling /new")
        response = "Error making request"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)

async def list_conversations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def get_label(conversation):
        current = "* " if conversation.get("current", False) else "  "
        title = conversation["title"]
        return f"{current}{title}"

    try:
        user_id = await auth(update)
        if user_id is None:
            return
        conversations = await chatgpt.get_conversations_list(user_id)

        keyboard = [
            [InlineKeyboardButton(get_label(c), callback_data=f"choose:{c['id']}")]
            for c in conversations
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose a conversation:", reply_markup=reply_markup)
    except Exception as e:
        logging.exception("Error handling /choose")
        response = "Error making request"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=response)

async def choose_conversation(chat_id, user_id, query):
    conversation_id = int(query[1])
    title = await chatgpt.select_conversation(user_id, conversation_id)
    if title:
        response = f"You are in this conversation now: {title}"
    else:
        response = "Failed to select the conversation"
    return response

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = await auth(update)
    if user_id is None:
        return

    query = update.callback_query
    await query.answer()
    q = query.data.split(':')
    action = q[0]
    response = None
    if action == "choose":
        response = await choose_conversation(update.effective_chat.id, user_id, q)
    if response:
        await query.edit_message_text(text=response)


async def dalle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = await auth(update)
        if user_id is None:
            return
        text = update.message.text.replace("/dalle", "")
        resp = await chatgpt.dalle(user_id, text)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=resp.revised_prompt)
        if resp.image:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=resp.image)
    except Exception as e:
        logging.exception("Error handling /dalle")
        response = "Error making request"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = await auth(update)
        if user_id is None:
            return
        response = await chatgpt.request(user_id, update.message.text)
    except Exception as e:
        logging.exception("Error handling text update")
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
    builder.concurrent_updates(True)
    application = builder.build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("forget", forget))
    application.add_handler(CommandHandler("new", new))
    application.add_handler(CommandHandler("choose", list_conversations))
    application.add_handler(CommandHandler("dalle", dalle))
    application.add_handler(CallbackQueryHandler(button))

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), text_message)
    )

    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
