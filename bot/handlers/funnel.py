"""Прогрев и презентация продукта: метод → пример → продукт → содержание / «пока подумаю»."""

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import Cb, SalesStage
from bot.db import User, UserRepository
from bot.services import screens

router = Router(name="funnel")


@router.callback_query(F.data == Cb.WHAT_NEXT)
async def method(callback: CallbackQuery, user: User, repo: UserRepository) -> None:
    await callback.answer()
    await repo.set_stage(user.user_id, SalesStage.METHOD)
    await callback.message.answer(texts.METHOD, reply_markup=keyboards.method())


@router.callback_query(F.data == Cb.SHOW_EXAMPLE)
async def example(callback: CallbackQuery, user: User, repo: UserRepository) -> None:
    await callback.answer()
    await repo.set_stage(user.user_id, SalesStage.EXAMPLE)
    await callback.message.answer(texts.EXAMPLE, reply_markup=keyboards.example())


@router.callback_query(F.data.in_({Cb.ABOUT_SYSTEM, Cb.BACK_TO_PRODUCT}))
async def product(callback: CallbackQuery, user: User, repo: UserRepository, settings: Settings, bot: Bot) -> None:
    await callback.answer()
    await screens.send_product(bot, repo, settings, user.user_id)


@router.callback_query(F.data == Cb.CONTENTS)
async def contents(callback: CallbackQuery, user: User, repo: UserRepository, settings: Settings) -> None:
    await callback.answer()
    await repo.set_stage(user.user_id, SalesStage.CONTENTS)
    await callback.message.answer(
        texts.CONTENTS, reply_markup=keyboards.contents(screens.buy_url(settings, user.user_id))
    )


@router.callback_query(F.data == Cb.THINK)
async def think(callback: CallbackQuery, user: User, repo: UserRepository) -> None:
    await callback.answer()
    await repo.set_stage(user.user_id, SalesStage.THINKING)
    await callback.message.answer(texts.THINK, reply_markup=keyboards.think())
