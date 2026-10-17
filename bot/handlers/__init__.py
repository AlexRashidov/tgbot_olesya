from aiogram import Router

from bot.handlers import admin, funnel, payment, quiz, start, texts_admin


def build_router() -> Router:
    root = Router(name="root")
    # admin первыми: их команды (/paid, /stats, /texts) доступны только администраторам.
    root.include_routers(admin.router, texts_admin.router, start.router, quiz.router, funnel.router,
                         payment.router)
    return root
