"""Готовые «экраны» бота. Используются и обработчиками, и фоновым планировщиком."""

import html
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from bot import keyboards, texts
from bot.config import Settings
from bot.constants import ANSWER_LETTERS, QUESTIONS_COUNT, Category, PayMethod, SalesStage, Tag
from bot.db import User, UserRepository
from bot.services import quiz


# Если адрес сайта не задан — документы на Яндекс Диске.
FALLBACK_DOCUMENTS = {
    "offer": "https://disk.yandex.ru/i/jop5s3l2ET0fZA",
    "privacy": "https://disk.yandex.ru/i/Uh9dE3r1kTEW_w",
    "consent": "https://disk.yandex.ru/i/Nix9lBfg9JXptQ",
    "marketing": "https://disk.yandex.ru/i/Ah007NR6vaxaTg",
}
SITE_DOCUMENT_PATHS = {
    "offer": "offer",
    "privacy": "privacy",
    "consent": "consent",
    "marketing": "marketing-consent",
}


def document_urls(settings: Settings) -> dict[str, str]:
    """Ссылки на оферту, политику и согласия — страницы на сайте."""
    if not settings.site_url:
        return dict(FALLBACK_DOCUMENTS)
    base = settings.site_url if settings.site_url.endswith("/") else settings.site_url + "/"
    base = urlunsplit(urlsplit(base)._replace(query="", fragment=""))
    return {key: urljoin(base, path) for key, path in SITE_DOCUMENT_PATHS.items()}


async def send_start(bot: Bot, settings: Settings, user: User) -> None:
    """Приветствие. Кто ещё не принял документы — сначала видит их и кнопку согласия."""
    if user.accepted_terms:
        await bot.send_message(user.user_id, texts.START, reply_markup=keyboards.start())
        return
    await bot.send_message(user.user_id, texts.START)
    await send_consent(bot, settings, user.user_id)


async def send_consent(bot: Bot, settings: Settings, chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        texts.CONSENT.format(**{k: html.escape(v) for k, v in document_urls(settings).items()}),
        reply_markup=keyboards.accept_terms(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def send_question(bot: Bot, chat_id: int, number: int) -> None:
    question, options = texts.QUESTIONS[number - 1]
    body = "\n\n".join(
        texts.OPTION_TEMPLATE.format(letter=letter, text=html.escape(text, quote=False))
        for letter, text in zip(ANSWER_LETTERS, options)
    )
    await bot.send_message(
        chat_id,
        texts.QUESTION_TEMPLATE.format(number=number, total=QUESTIONS_COUNT, question=question, options=body),
        reply_markup=keyboards.question(number, options),
    )


def _titles(categories: list[Category]) -> str:
    return "\n".join(f"• {html.escape(texts.CATEGORY_TITLES[c], quote=False)}" for c in categories)


def category_text(category: Category) -> str:
    title = html.escape(texts.CATEGORY_TITLES[category], quote=False)
    return texts.RESULT_HEADER.format(title=title) + texts.RESULTS[category]


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


def buy_url(settings: Settings, user_id: int) -> str | None:
    """Ссылка на форму оплаты на лендинге. Telegram ID нужен, чтобы после оплаты на сайте
    бот выдал материалы и остановил продающие сообщения."""
    if not settings.site_url:
        return None
    parts = urlsplit(settings.site_url)
    query = urlencode({"tg": user_id, "utm_source": "telegram_bot"})
    if parts.query:
        query = f"{parts.query}&{query}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, "pricing"))


async def send_product(bot: Bot, repo: UserRepository, settings: Settings, chat_id: int) -> None:
    await repo.set_product_interest(chat_id)
    await repo.add_tags(chat_id, [Tag.PRODUCT_VIEWED])
    await repo.set_stage(chat_id, SalesStage.PRODUCT)
    await bot.send_message(chat_id, texts.PRODUCT, reply_markup=keyboards.product(buy_url(settings, chat_id)))


async def send_payment(bot: Bot, repo: UserRepository, user: User,
                       links: list[tuple[PayMethod, str, bool]]) -> None:
    """links — (способ оплаты, ссылка, подтверждается ли автоматически)."""
    if not links:
        await bot.send_message(user.user_id, texts.PAYMENT_NOT_CONFIGURED)
        return
    await repo.set_payment_pending(user.user_id)
    manual = any(not automatic for _, _, automatic in links)
    text = texts.PAYMENT_MANUAL if manual else texts.PAYMENT
    if user.email:
        text += "\n\n" + texts.PAYMENT_RECEIPT_EMAIL.format(email=html.escape(user.email))
    await bot.send_message(
        user.user_id,
        text,
        reply_markup=keyboards.payment([(method, url) for method, url, _ in links], show_i_paid=manual),
    )


async def send_materials(bot: Bot, settings: Settings, chat_id: int, text: str) -> None:
    markup = keyboards.materials(settings)
    if markup is None:
        text = f"{text}\n\n{texts.MATERIALS_NOT_CONFIGURED}"
    await bot.send_message(chat_id, text, reply_markup=markup)


async def complete_purchase(bot: Bot, repo: UserRepository, settings: Settings, user_id: int) -> None:
    """Вызывается только после подтверждения оплаты (админом или платёжной системой)."""
    await repo.mark_customer(user_id)
    await send_materials(bot, settings, user_id, texts.PURCHASE_SUCCESS)
