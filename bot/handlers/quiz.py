"""Прохождение теста: старт, ответы, подсчёт результата."""

import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import texts
from bot.config import Settings
from bot.constants import ANSWER_CATEGORIES, FOLLOWUP_DELAYS, QUESTIONS_COUNT, Category, Cb
from bot.db import User, UserRepository
from bot.services import quiz, screens

router = Router(name="quiz")


@router.callback_query(F.data.in_({Cb.START_TEST, Cb.RESTART_TEST}))
async def start_quiz(callback: CallbackQuery, user: User, repo: UserRepository, bot: Bot) -> None:
    await callback.answer()
    await repo.start_quiz(user.user_id)
    await screens.send_question(bot, user.user_id, 1)


@router.callback_query(F.data == Cb.CONTINUE_TEST)
async def continue_quiz(callback: CallbackQuery, user: User, bot: Bot) -> None:
    await callback.answer()
    if user.quiz_in_progress:
        await screens.send_question(bot, user.user_id, user.current_question)
    else:
        await screens.send_start(bot, user.user_id)


@router.callback_query(F.data.startswith(f"{Cb.ANSWER_PREFIX}:"))
async def answer(callback: CallbackQuery, user: User, repo: UserRepository, settings: Settings, bot: Bot) -> None:
    try:
        _, q_raw, opt_raw = callback.data.split(":")
        question, option = int(q_raw), int(opt_raw)
        category = ANSWER_CATEGORIES[option]
    except (ValueError, IndexError):
        await callback.answer()
        return

    if not await repo.save_answer(user.user_id, question, category):
        # Повторное нажатие на старый вопрос — игнорируем, чтобы не испортить подсчёт.
        await callback.answer(texts.QUESTION_OUTDATED)
        return
    await callback.answer()

    # Убираем кнопки у отвеченного вопроса, чтобы не было двойных нажатий.
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)

    if question < QUESTIONS_COUNT:
        await screens.send_question(bot, user.user_id, question + 1)
        return

    fresh = await repo.get(user.user_id)
    assert fresh is not None
    leaders = quiz.leading_categories(fresh.scores)
    first_followup_at = int(time.time() + FOLLOWUP_DELAYS[0] * settings.delay_scale)
    await repo.complete_quiz(user.user_id, quiz.encode_result(leaders), quiz.tags_for_result(leaders),
                             first_followup_at)
    await screens.send_result(bot, user.user_id, await repo.get(user.user_id))


@router.callback_query(F.data.startswith(f"{Cb.SHOW_CATEGORY_PREFIX}:"))
async def show_category(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    try:
        category = Category(callback.data.split(":", 1)[1])
    except ValueError:
        return
    await screens.send_category(bot, callback.from_user.id, category)


@router.callback_query(F.data == Cb.MY_RESULT)
async def my_result(callback: CallbackQuery, user: User, bot: Bot) -> None:
    await callback.answer()
    await screens.send_result(bot, user.user_id, user)
