"""Редактор текстов бота для администраторов: /texts → раздел → текст → «Изменить» / «Вернуть исходный»."""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.constants import Cb
from bot.db import TextRepository
from bot.handlers.admin import IsAdmin
from bot.services import text_store

logger = logging.getLogger(__name__)
router = Router(name="texts_admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class TextEditStates(StatesGroup):
    waiting_text = State()


def _btn(text: str, data: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=data)]


def _groups_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _btn(group.title, f"{Cb.TEXTS_GROUP_PREFIX}:{i}") for i, group in enumerate(text_store.GROUPS)
    ])


def _items_kb(group_idx: int) -> InlineKeyboardMarkup:
    group = text_store.GROUPS[group_idx]
    rows = [
        _btn(("✏️ " if text_store.is_changed(item.key) else "") + item.title[:60],
             f"{Cb.TEXTS_ITEM_PREFIX}:{item.key}")
        for item in group.items
    ]
    rows.append(_btn(texts.BTN_TEXTS_BACK, Cb.TEXTS_MENU))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_kb(key: str) -> InlineKeyboardMarkup:
    group_idx = next(i for i, g in enumerate(text_store.GROUPS) if any(it.key == key for it in g.items))
    rows = [_btn(texts.BTN_TEXTS_EDIT, f"{Cb.TEXTS_EDIT_PREFIX}:{key}")]
    if text_store.is_changed(key):
        rows.append(_btn(texts.BTN_TEXTS_RESET, f"{Cb.TEXTS_RESET_PREFIX}:{key}"))
    rows.append(_btn(texts.BTN_TEXTS_BACK, f"{Cb.TEXTS_GROUP_PREFIX}:{group_idx}"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_item(bot: Bot, chat_id: int, key: str) -> None:
    item = text_store.ITEMS[key]
    status = texts.TEXTS_STATUS_CHANGED if text_store.is_changed(key) else texts.TEXTS_STATUS_DEFAULT
    await bot.send_message(chat_id, texts.TEXTS_ITEM_HEADER.format(title=item.title, status=status))
    # Сам текст — отдельным сообщением, чтобы его было удобно скопировать.
    value = text_store.get(key)
    try:
        await bot.send_message(chat_id, value, parse_mode=None if item.plain else "HTML",
                               reply_markup=_item_kb(key))
    except TelegramBadRequest:
        await bot.send_message(chat_id, value, parse_mode=None, reply_markup=_item_kb(key))


@router.message(Command("texts"))
async def cmd_texts(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.TEXTS_MENU, reply_markup=_groups_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.TEXTS_CANCELLED)


@router.callback_query(F.data == Cb.TEXTS_MENU)
async def menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(texts.TEXTS_MENU, reply_markup=_groups_kb())


@router.callback_query(F.data.startswith(f"{Cb.TEXTS_GROUP_PREFIX}:"))
async def group(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        idx = int(callback.data.rsplit(":", 1)[1])
        title = text_store.GROUPS[idx].title
    except (ValueError, IndexError):
        return
    await callback.message.answer(texts.TEXTS_GROUP.format(title=title), reply_markup=_items_kb(idx))


@router.callback_query(F.data.startswith(f"{Cb.TEXTS_ITEM_PREFIX}:"))
async def item(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    if key in text_store.ITEMS:
        await _show_item(bot, callback.from_user.id, key)


@router.callback_query(F.data.startswith(f"{Cb.TEXTS_EDIT_PREFIX}:"))
async def edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    if key not in text_store.ITEMS:
        return
    await state.set_state(TextEditStates.waiting_text)
    await state.update_data(key=key)
    item = text_store.ITEMS[key]
    hint = texts.TEXTS_EDIT_HINT_BUTTON if item.plain else texts.TEXTS_EDIT_HINT
    required = text_store.placeholders(text_store.DEFAULTS[key])
    if required:
        hint += "\n\n" + texts.TEXTS_EDIT_PLACEHOLDERS.format(
            names=", ".join("{" + n + "}" for n in sorted(required)))
    await callback.message.answer(texts.TEXTS_EDIT_PROMPT.format(title=item.title) + "\n\n" + hint)


@router.callback_query(F.data.startswith(f"{Cb.TEXTS_RESET_PREFIX}:"))
async def reset(callback: CallbackQuery, text_repo: TextRepository, bot: Bot) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    if key not in text_store.ITEMS:
        return
    await text_repo.delete(key)
    text_store.reset(key)
    logger.info("Администратор %s вернул исходный текст %s", callback.from_user.id, key)
    await callback.message.answer(texts.TEXTS_RESET_DONE)
    await _show_item(bot, callback.from_user.id, key)


@router.message(StateFilter(TextEditStates.waiting_text), F.text, ~F.text.startswith("/"))
async def got_text(message: Message, state: FSMContext, text_repo: TextRepository, bot: Bot) -> None:
    key = (await state.get_data()).get("key")
    if key not in text_store.ITEMS:
        await state.clear()
        return
    item = text_store.ITEMS[key]
    # Форматирование Telegram (жирный, курсив, ссылки) сохраняем как HTML.
    value = (message.text if item.plain else message.html_text).strip()

    error = text_store.validate(key, value)
    if error:
        await message.answer(texts.TEXTS_INVALID.format(error=html.escape(error)))
        return

    # Проверяем, что Telegram принимает текст, — отправляем предпросмотр.
    try:
        await bot.send_message(message.chat.id, texts.TEXTS_PREVIEW, parse_mode="HTML")
        await bot.send_message(message.chat.id, value, parse_mode=None if item.plain else "HTML")
    except TelegramBadRequest as e:
        await message.answer(texts.TEXTS_INVALID.format(error=html.escape(e.message)))
        return

    await text_repo.set(key, value)
    text_store.set_value(key, value)
    await state.clear()
    logger.info("Администратор %s изменил текст %s", message.from_user.id, key)
    await message.answer(texts.TEXTS_SAVED, reply_markup=_item_kb(key))
