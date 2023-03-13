#!/usr/bin/env python

import argparse
import asyncio
import os

import db_handler


def add_user(args):
    async def wrapper(tg_id):
        db = await db_handler.DB.create(
            dbhost=os.environ["DBHOST"],
            dbname=os.environ["DBNAME"],
            dbuser=os.environ["DBUSER"],
            dbpass=os.environ["DBPASS"],
        )
        await db.add_user(tg_id)

    asyncio.run(wrapper(args.tg_id))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    add_user_parser = subparsers.add_parser("add_user")
    add_user_parser.add_argument("tg_id", type=int, help="Telegram id")
    add_user_parser.set_defaults(func=add_user)

    args = parser.parse_args()
    args.func(args)
