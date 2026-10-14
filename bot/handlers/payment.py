"""Оплата: кнопка «Купить», «Я оплатил(а)» и уведомление администраторов."""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import Cb
from bot.db import User, UserRepository
from bot.services import screens

logger = logging.getLogger(__name__)
router = Router(name="payment")


@router.callback_query(F.data == Cb.BUY)
async def buy(callback: CallbackQuery, user: User, repo: UserRepository, settings: Settings, bot: Bot) -> None:
    # Нажатие «Купить» — ещё не покупка: только статус pending и теги purchase_clicked / payment_pending.
    await callback.answer()
    await screens.send_payment(bot, repo, settings, user)


@router.callback_query(F.data == Cb.I_PAID)
async def i_paid(callback: CallbackQuery, user: User, settings: Settings, bot: Bot) -> None:
    await callback.answer()
    if user.is_customer:
        await screens.send_materials(bot, settings, user.user_id, texts.ALREADY_CUSTOMER)
        return

    await callback.message.answer(texts.PAYMENT_CHECKING)
    claim = texts.ADMIN_PAYMENT_CLAIM.format(
        user_id=user.user_id,
        name=html.escape(user.first_name or "—"),
        username=f"@{user.username}" if user.username else "—",
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, claim, reply_markup=keyboards.admin_payment(user.user_id))
        except Exception:
            logger.exception("Не удалось уведомить администратора %s", admin_id)
