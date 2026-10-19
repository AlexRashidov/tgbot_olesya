"""Inline-клавиатуры."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import texts
from bot.config import Settings
from bot.constants import ANSWER_LETTERS, Category, Cb, PayMethod


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def _btn(text: str, data: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=data)]


def _short(text: str) -> str:
    limit = texts.ANSWER_BUTTON_MAX_LEN
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def start() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_START_TEST, Cb.START_TEST))


def continue_quiz() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_CONTINUE_TEST, Cb.CONTINUE_TEST), _btn(texts.BTN_RESTART_TEST, Cb.RESTART_TEST))


def question(number: int, options: tuple[str, ...]) -> InlineKeyboardMarkup:
    return _kb(*(
        _btn(f"{letter}. {_short(option)}", f"{Cb.ANSWER_PREFIX}:{number}:{i}")
        for i, (letter, option) in enumerate(zip(ANSWER_LETTERS, options))
    ))


def result() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_WHAT_NEXT, Cb.WHAT_NEXT))


def result_choices(categories: list[Category]) -> InlineKeyboardMarkup:
    return _kb(
        *(_btn(texts.CATEGORY_TITLES[c], f"{Cb.SHOW_CATEGORY_PREFIX}:{c.value}") for c in categories),
        _btn(texts.BTN_WHAT_NEXT, Cb.WHAT_NEXT),
    )


def method() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_SHOW_EXAMPLE, Cb.SHOW_EXAMPLE))


def example() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_ABOUT_SYSTEM, Cb.ABOUT_SYSTEM))


def _buy(buy_url: str | None) -> list[InlineKeyboardButton]:
    """«Купить»: ссылка на форму оплаты на лендинге, а если сайт не задан — оплата внутри бота."""
    if buy_url:
        return [InlineKeyboardButton(text=texts.BTN_BUY, url=buy_url)]
    return _btn(texts.BTN_BUY, Cb.BUY)


def product(buy_url: str | None = None) -> InlineKeyboardMarkup:
    return _kb(
        _buy(buy_url),
        _btn(texts.BTN_CONTENTS, Cb.CONTENTS),
        _btn(texts.BTN_THINK, Cb.THINK),
    )


def contents(buy_url: str | None = None) -> InlineKeyboardMarkup:
    return _kb(_buy(buy_url), _btn(texts.BTN_BACK_TO_PRODUCT, Cb.BACK_TO_PRODUCT))


def think() -> InlineKeyboardMarkup:
    return _kb(_btn(texts.BTN_BACK_TO_PRODUCT, Cb.BACK_TO_PRODUCT))


def followup(step: int, buy_url: str | None = None) -> InlineKeyboardMarkup:
    if step == 1:
        return _kb(_btn(texts.BTN_MY_RESULT, Cb.MY_RESULT))
    if step == 2:
        return _kb(_btn(texts.BTN_ABOUT_PILL, Cb.ABOUT_SYSTEM))
    return _kb(_buy(buy_url), _btn(texts.BTN_CONTENTS, Cb.CONTENTS))


def payment(links: list[tuple[PayMethod, str]], show_i_paid: bool) -> InlineKeyboardMarkup:
    titles = {PayMethod.RU: texts.BTN_PAY_RU, PayMethod.FOREIGN: texts.BTN_PAY_FOREIGN}
    return _kb(
        *([InlineKeyboardButton(text=titles[method], url=url)] for method, url in links),
        _btn(texts.BTN_I_PAID, Cb.I_PAID) if show_i_paid else [],
    )


def materials(settings: Settings) -> InlineKeyboardMarkup | None:
    """Доступ после оплаты: группы ТГ / ВК / Max (по ТЗ — на выбор), иначе общая ссылка на материалы."""
    groups = [
        (texts.BTN_OPEN_TG, settings.access_tg_url),
        (texts.BTN_OPEN_VK, settings.access_vk_url),
        (texts.BTN_OPEN_MAX, settings.access_max_url),
    ]
    rows = [[InlineKeyboardButton(text=title, url=url)] for title, url in groups if url]
    if not rows and settings.materials_url:
        rows = [[InlineKeyboardButton(text=texts.BTN_OPEN_MATERIALS, url=settings.materials_url)]]
    return _kb(*rows) if rows else None


def admin_payment(user_id: int) -> InlineKeyboardMarkup:
    return _kb(
        _btn(texts.BTN_ADMIN_CONFIRM, f"{Cb.ADMIN_CONFIRM_PREFIX}:{user_id}"),
        _btn(texts.BTN_ADMIN_REJECT, f"{Cb.ADMIN_REJECT_PREFIX}:{user_id}"),
    )
