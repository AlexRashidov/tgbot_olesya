"""Точка входа: собирает зависимости, запускает polling, веб-сервер оплаты и фоновый планировщик."""

import asyncio
import contextlib
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web

from bot.config import load_settings
from bot.db import Database, OrderRepository, TextRepository, UserRepository
from bot.handlers import build_router
from bot.middlewares import UserMiddleware
from bot.services import text_store
from bot.services.payments import PaymentService
from bot.services.scheduler import Scheduler
from bot.services.tbank import TBankClient
from bot.web import build_app

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="test", description="Пройти тест заново"),
    BotCommand(command="result", description="Мой результат"),
    BotCommand(command="product", description="О «Таблетке от прокрастинации»"),
    BotCommand(command="email", description="Изменить почту для чека"),
    BotCommand(command="stop", description="Не присылать дополнительные сообщения"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    db = Database(settings.database_path)
    await db.connect()
    repo = UserRepository(db)
    orders = OrderRepository(db)
    text_repo = TextRepository(db)
    await text_store.apply_overrides(await text_repo.all())

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    http = aiohttp.ClientSession()
    tbank = None
    if settings.tbank_enabled:
        tbank = TBankClient(http, settings.tbank_terminal_key, settings.tbank_password, settings.tbank_api_url,
                            settings.tbank_receipt, settings.tbank_taxation, settings.tbank_vat)
    me = await bot.get_me()
    payments = PaymentService(bot, settings, repo, orders, tbank, me.username or "")
    logger.info("Т-Банк: %s, Prodamus: %s",
                "автоподтверждение" if settings.tbank_enabled else "ручная проверка",
                "автоподтверждение" if settings.prodamus_enabled else "ручная проверка")

    dp = Dispatcher(repo=repo, settings=settings, payments=payments, text_repo=text_repo)
    middleware = UserMiddleware(repo)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    dp.include_router(build_router())

    runner = None
    if settings.web_enabled:
        runner = web.AppRunner(build_app(settings, payments), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, settings.web_host, settings.web_port).start()
        logger.info("Веб-сервер оплаты слушает %s:%s", settings.web_host, settings.web_port)

    scheduler_task = asyncio.create_task(Scheduler(bot, repo, settings).run(), name="scheduler")
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        if runner is not None:
            await runner.cleanup()
        await http.close()
        await bot.session.close()
        await db.close()


def run() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


if __name__ == "__main__":
    run()
