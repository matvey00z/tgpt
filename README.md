# Telegram bot talking to ChatGPT

## Disclaimer

This bot is on early development stage.

## Usage:

1. Obtain your [telegram token](https://core.telegram.org/bots/features#botfather)
1. Obtain your [openai API key](https://platform.openai.com/account/api-keys)
1. Create file with the name `.env` and set the values:
```
TG_TOKEN=<your-telegram-token>
GPT_TOKEN=<your-openai-api-key>
DB_PASSWORD=<some-random-password>
```
1. Run the service using docker compose file, for example: `docker compose up`. Now your bot should be up and running!

## Communication

While talking to the bot, just send text messages and get the replies from ChatGPT. Other than that, the following commands are supported:

1. `/forget`: forget previous messages

## References

- [OpenAI API overview](https://platform.openai.com/overview)
- [OpenAI python library](https://github.com/openai/openai-python)
- [Telegram bot python library](https://github.com/python-telegram-bot/python-telegram-bot)