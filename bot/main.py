"""Точка входа: собирает зависимости, запускает polling и фоновый планировщик."""

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import load_settings
from bot.db import Database, UserRepository
from bot.handlers import build_router
from bot.middlewares import UserMiddleware
from bot.services.scheduler import Scheduler

COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="test", description="Пройти тест заново"),
    BotCommand(command="result", description="Мой результат"),
    BotCommand(command="product", description="О «Таблетке от прокрастинации»"),
    BotCommand(command="stop", description="Не присылать дополнительные сообщения"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    db = Database(settings.database_path)
    await db.connect()
    repo = UserRepository(db)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(repo=repo, settings=settings)
    middleware = UserMiddleware(repo)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    dp.include_router(build_router())

    scheduler_task = asyncio.create_task(Scheduler(bot, repo, settings).run(), name="scheduler")
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        await bot.session.close()
        await db.close()


def run() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


if __name__ == "__main__":
    run()
