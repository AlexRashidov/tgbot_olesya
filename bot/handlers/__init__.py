from aiogram import Router

from bot.handlers import admin, funnel, payment, quiz, start


def build_router() -> Router:
    root = Router(name="root")
    # admin первым: его команды (/paid, /stats) доступны только администраторам.
    root.include_routers(admin.router, start.router, quiz.router, funnel.router, payment.router)
    return root
