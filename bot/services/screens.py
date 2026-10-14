"""Готовые «экраны» бота. Используются и обработчиками, и фоновым планировщиком."""

from aiogram import Bot

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import ANSWER_LETTERS, QUESTIONS_COUNT, Category, SalesStage, Tag
from bot.db import User, UserRepository
from bot.services import quiz


async def send_start(bot: Bot, chat_id: int) -> None:
    await bot.send_message(chat_id, texts.START, reply_markup=keyboards.start())


async def send_question(bot: Bot, chat_id: int, number: int) -> None:
    question, options = texts.QUESTIONS[number - 1]
    body = "\n\n".join(
        texts.OPTION_TEMPLATE.format(letter=letter, text=text)
        for letter, text in zip(ANSWER_LETTERS, options)
    )
    await bot.send_message(
        chat_id,
        texts.QUESTION_TEMPLATE.format(number=number, total=QUESTIONS_COUNT, question=question, options=body),
        reply_markup=keyboards.question(number, options),
    )


def _titles(categories: list[Category]) -> str:
    return "\n".join(f"• {texts.CATEGORY_TITLES[c]}" for c in categories)


def category_text(category: Category) -> str:
    return texts.RESULT_HEADER.format(title=texts.CATEGORY_TITLES[category]) + texts.RESULTS[category]


async def send_category(bot: Bot, chat_id: int, category: Category) -> None:
    await bot.send_message(chat_id, category_text(category), reply_markup=keyboards.result())


async def send_result(bot: Bot, chat_id: int, user: User) -> None:
    """Показывает сохранённый результат: одиночный, смешанный или «без преобладающего»."""
    if not user.test_result:
        await bot.send_message(chat_id, texts.RESULT_NOT_READY, reply_markup=keyboards.start())
        return

    leaders = quiz.decode_result(user.test_result)
    if not leaders:
        answered = quiz.answered_categories(user.scores)
        await bot.send_message(
            chat_id,
            texts.RESULT_NONE.format(titles=_titles(answered)),
            reply_markup=keyboards.result_choices(answered),
        )
        return

    if len(leaders) > 1:
        await bot.send_message(chat_id, texts.RESULT_MIXED_INTRO.format(titles=_titles(leaders)))
        for category in leaders[:-1]:
            await bot.send_message(chat_id, category_text(category))
    await send_category(bot, chat_id, leaders[-1])


async def send_product(bot: Bot, repo: UserRepository, chat_id: int) -> None:
    await repo.set_product_interest(chat_id)
    await repo.add_tags(chat_id, [Tag.PRODUCT_VIEWED])
    await repo.set_stage(chat_id, SalesStage.PRODUCT)
    await bot.send_message(chat_id, texts.PRODUCT, reply_markup=keyboards.product())


async def send_payment(bot: Bot, repo: UserRepository, settings: Settings, user: User) -> None:
    if user.is_customer:
        await send_materials(bot, settings, user.user_id, texts.ALREADY_CUSTOMER)
        return
    if not (settings.payment_url_ru or settings.payment_url_foreign):
        await bot.send_message(user.user_id, texts.PAYMENT_NOT_CONFIGURED)
        return
    await repo.set_payment_pending(user.user_id)
    await bot.send_message(
        user.user_id,
        texts.PAYMENT,
        reply_markup=keyboards.payment(settings.payment_url_ru, settings.payment_url_foreign),
    )


async def send_materials(bot: Bot, settings: Settings, chat_id: int, text: str) -> None:
    markup = keyboards.materials(settings.materials_url)
    if markup is None:
        text = f"{text}\n\n{texts.MATERIALS_NOT_CONFIGURED}"
    await bot.send_message(chat_id, text, reply_markup=markup)


async def complete_purchase(bot: Bot, repo: UserRepository, settings: Settings, user_id: int) -> None:
    """Вызывается только после подтверждения оплаты (админом или платёжной системой)."""
    await repo.mark_customer(user_id)
    await send_materials(bot, settings, user_id, texts.PURCHASE_SUCCESS)
