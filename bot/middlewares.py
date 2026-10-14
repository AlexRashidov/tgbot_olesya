"""Middleware: регистрирует пользователя в БД и передаёт его в обработчик как `user`."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from bot.db import UserRepository


class UserMiddleware(BaseMiddleware):
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is not None and not tg_user.is_bot:
            data["user"] = await self._repo.upsert(tg_user.id, tg_user.username, tg_user.first_name)
        return await handler(event, data)
