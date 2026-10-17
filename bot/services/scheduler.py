"""Фоновый планировщик: цепочка прогрева (24ч / +48ч / +48ч) и напоминание о незавершённом тесте.

Работает как отдельная asyncio-задача рядом с polling. Всё состояние хранится в SQLite,
поэтому после перезапуска бота отправки продолжаются с того же места.
"""

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import FOLLOWUP_DELAYS, FOLLOWUP_STEPS, QUIZ_REMINDER_DELAY, SEND_PAUSE_SECONDS
from bot.db import User, UserRepository

logger = logging.getLogger(__name__)

def followup_text(step: int) -> str:
    # Читаем при каждой отправке, чтобы применялись тексты, изменённые через бота.
    return (texts.FOLLOWUP_1, texts.FOLLOWUP_2, texts.FOLLOWUP_3)[step]


class Scheduler:
    def __init__(self, bot: Bot, repo: UserRepository, settings: Settings) -> None:
        self._bot = bot
        self._repo = repo
        self._settings = settings

    def _delay(self, seconds: int) -> int:
        return int(seconds * self._settings.delay_scale)

    async def run(self) -> None:
        logger.info("Фоновый планировщик запущен (проверка раз в %s с)", self._settings.scheduler_tick)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка в фоновом планировщике")
            await asyncio.sleep(self._settings.scheduler_tick)

    async def tick(self) -> None:
        current = int(time.time())
        for user in await self._repo.due_followups(current):
            await self._send_followup(user, current)
            await asyncio.sleep(SEND_PAUSE_SECONDS)
        for user in await self._repo.due_quiz_reminders(current - self._delay(QUIZ_REMINDER_DELAY)):
            await self._send_quiz_reminder(user)
            await asyncio.sleep(SEND_PAUSE_SECONDS)

    async def _send_followup(self, user: User, current: int) -> None:
        step = user.followup_step  # сколько сообщений уже отправлено
        if step >= FOLLOWUP_STEPS:
            await self._repo.advance_followup(user.user_id, step, None)
            return

        sent = await self._safe_send(user.user_id, followup_text(step), keyboards.followup(step + 1))
        if sent is None:
            return  # временная ошибка — попробуем на следующем тике

        next_step = step + 1
        next_at = current + self._delay(FOLLOWUP_DELAYS[next_step]) if next_step < FOLLOWUP_STEPS else None
        await self._repo.advance_followup(user.user_id, next_step, next_at)
        logger.info("Прогрев %s/%s отправлен пользователю %s", next_step, FOLLOWUP_STEPS, user.user_id)

    async def _send_quiz_reminder(self, user: User) -> None:
        sent = await self._safe_send(user.user_id, texts.QUIZ_REMINDER, keyboards.continue_quiz())
        if sent is not None:
            await self._repo.mark_quiz_reminder_sent(user.user_id)

    async def _safe_send(self, chat_id: int, text: str, markup) -> bool | None:
        """True — отправлено; False — пользователь недоступен (отписан); None — повторить позже."""
        try:
            await self._bot.send_message(chat_id, text, reply_markup=markup)
            return True
        except TelegramRetryAfter as e:
            logger.warning("Flood control, ждём %s с", e.retry_after)
            await asyncio.sleep(e.retry_after)
            return None
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Бот заблокирован или чат недоступен — больше не пишем этому пользователю.
            logger.info("Пользователь %s недоступен (%s), отключаем рассылку", chat_id, e.message)
            await self._repo.set_followup_allowed(chat_id, False)
            await self._repo.advance_followup(chat_id, FOLLOWUP_STEPS, None)
            return False
        except Exception:
            logger.exception("Не удалось отправить сообщение %s", chat_id)
            return None
