"""Оплата: кнопка «Купить», почта для чека, «Я оплатил(а)» и уведомление администраторов."""

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import Cb
from bot.db import User, UserRepository
from bot.services import screens
from bot.services.payments import PaymentService

logger = logging.getLogger(__name__)
router = Router(name="payment")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class PaymentStates(StatesGroup):
    waiting_email = State()


async def _send_payment(bot: Bot, repo: UserRepository, payments: PaymentService, user: User) -> None:
    links = await payments.links_for_user(user.user_id, user.email)
    await screens.send_payment(bot, repo, user, [(l.method, l.url, l.automatic) for l in links])


@router.callback_query(F.data == Cb.BUY)
async def buy(callback: CallbackQuery, user: User, repo: UserRepository, settings: Settings,
              payments: PaymentService, state: FSMContext, bot: Bot) -> None:
    # Нажатие «Купить» — ещё не покупка: только статус pending и теги purchase_clicked / payment_pending.
    await callback.answer()
    if user.is_customer:
        await screens.send_materials(bot, settings, user.user_id, texts.ALREADY_CUSTOMER)
        return
    if not user.email:
        # Почта нужна для электронного чека.
        await state.set_state(PaymentStates.waiting_email)
        await bot.send_message(user.user_id, texts.ASK_EMAIL)
        return
    await _send_payment(bot, repo, payments, user)


@router.message(Command("email"))
async def cmd_email(message: Message, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_email)
    await message.answer(texts.ASK_EMAIL)


@router.message(StateFilter(PaymentStates.waiting_email), F.text, ~F.text.startswith("/"))
async def got_email(message: Message, user: User, repo: UserRepository, payments: PaymentService,
                    state: FSMContext, bot: Bot) -> None:
    email = message.text.strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        await message.answer(texts.EMAIL_INVALID)
        return
    await state.clear()
    await repo.set_email(user.user_id, email)
    fresh = await repo.get(user.user_id)
    assert fresh is not None
    if fresh.is_customer:
        await message.answer(texts.EMAIL_SAVED.format(email=html.escape(email)))
        return
    await _send_payment(bot, repo, payments, fresh)


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
        email=html.escape(user.email or "—"),
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, claim, reply_markup=keyboards.admin_payment(user.user_id))
        except Exception:
            logger.exception("Не удалось уведомить администратора %s", admin_id)
