"""Редактируемые тексты: список, чтение, замена и возврат к исходному значению.

Исходные тексты лежат в bot/texts.py. Правки администратора хранятся в таблице text_overrides
и при запуске накладываются поверх — прямо в атрибуты модуля texts, поэтому остальной код
продолжает читать texts.START, texts.RESULTS[...] и т. д. как раньше.

Ключи:
  START, PRODUCT, BTN_BUY …        — строковые константы из texts.py
  RESULTS.STRUCTURE …              — описание результата
  CATEGORY_TITLES.STRUCTURE …      — название результата
  Q1 … Q4                          — текст вопроса
  Q1.1 … Q4.5                      — вариант ответа (1 = А … 5 = Д)
"""

import logging
import re
import string
from dataclasses import dataclass

from bot import texts
from bot.constants import ANSWER_LETTERS, Category

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TextItem:
    key: str
    title: str
    plain: bool = False  # текст кнопки: без HTML-разметки


@dataclass(frozen=True, slots=True)
class TextGroup:
    title: str
    items: tuple[TextItem, ...]


def _questions() -> tuple[TextItem, ...]:
    items = []
    for n in range(1, len(texts.QUESTIONS) + 1):
        items.append(TextItem(f"Q{n}", f"Вопрос {n}"))
        items.extend(TextItem(f"Q{n}.{i}", f"Вопрос {n}, вариант {letter}", plain=True)
                     for i, letter in enumerate(ANSWER_LETTERS, start=1))
    return tuple(items)


GROUPS: tuple[TextGroup, ...] = (
    TextGroup("Стартовое сообщение", (
        TextItem("START", "Приветствие и приглашение в тест"),
        TextItem("START_TEST_IN_PROGRESS", "Если тест уже начат"),
    )),
    TextGroup("Вопросы теста", _questions()),
    TextGroup("Результаты теста", (
        *(TextItem(f"CATEGORY_TITLES.{c.value}", f"Название: {texts.CATEGORY_TITLES[c]}", plain=True)
          for c in Category),
        *(TextItem(f"RESULTS.{c.value}", f"Описание: {texts.CATEGORY_TITLES[c]}") for c in Category),
        TextItem("RESULT_MIXED_INTRO", "Смешанный результат (вступление)"),
        TextItem("RESULT_NONE", "Нет преобладающего варианта"),
    )),
    TextGroup("Метод, пример, продукт", (
        TextItem("METHOD", "Переход к авторскому методу"),
        TextItem("EXAMPLE", "Личный пример"),
        TextItem("PRODUCT", "Презентация продукта"),
        TextItem("CONTENTS", "Посмотреть содержание"),
        TextItem("THINK", "Пока подумаю"),
    )),
    TextGroup("Прогрев и напоминания", (
        TextItem("FOLLOWUP_1", "Прогрев 1 (через 24 ч)"),
        TextItem("FOLLOWUP_2", "Прогрев 2 (ещё через 48 ч)"),
        TextItem("FOLLOWUP_3", "Прогрев 3 (ещё через 48 ч)"),
        TextItem("QUIZ_REMINDER", "Напоминание о незаконченном тесте"),
    )),
    TextGroup("Оплата и доступ", (
        TextItem("ASK_EMAIL", "Просьба указать почту для чека"),
        TextItem("EMAIL_INVALID", "Ошибка в почте"),
        TextItem("PAYMENT", "Выбор способа оплаты (автоподтверждение)"),
        TextItem("PAYMENT_MANUAL", "Выбор способа оплаты (ручная проверка)"),
        TextItem("PAYMENT_CHECKING", "После «Я оплатил(а)»"),
        TextItem("PAYMENT_REJECTED", "Оплата не найдена"),
        TextItem("PURCHASE_SUCCESS", "Спасибо за покупку"),
        TextItem("ALREADY_CUSTOMER", "Уже есть доступ"),
        TextItem("MATERIALS_NOT_CONFIGURED", "Если ссылка на материалы не задана"),
        TextItem("PAYMENT_NOT_CONFIGURED", "Если оплата не подключена"),
    )),
    TextGroup("Подписка", (
        TextItem("OPT_OUT", "Отписка (/stop)"),
        TextItem("OPT_IN", "Подписка (/subscribe)"),
    )),
    TextGroup("Кнопки", tuple(
        TextItem(name, f"Кнопка «{getattr(texts, name)}»", plain=True)
        for name in (
            "BTN_START_TEST", "BTN_RESTART_TEST", "BTN_CONTINUE_TEST", "BTN_WHAT_NEXT", "BTN_SHOW_EXAMPLE",
            "BTN_ABOUT_SYSTEM", "BTN_BUY", "BTN_CONTENTS", "BTN_THINK", "BTN_BACK_TO_PRODUCT",
            "BTN_MY_RESULT", "BTN_ABOUT_PILL", "BTN_OPEN_MATERIALS", "BTN_OPEN_TG", "BTN_OPEN_VK", "BTN_OPEN_MAX", "BTN_PAY_RU", "BTN_PAY_FOREIGN",
            "BTN_I_PAID",
        )
    )),
)

ITEMS: dict[str, TextItem] = {item.key: item for group in GROUPS for item in group.items}

# Ограничения Telegram: сообщение — 4096 символов, кнопка — лучше не длиннее 64.
MAX_MESSAGE_LEN = 4000
MAX_BUTTON_LEN = 64

_QUESTION_KEY_RE = re.compile(r"^Q(\d+)(?:\.(\d+))?$")


def _question_key(key: str) -> tuple[int, int | None] | None:
    """«Q2» → (2, None), «Q2.5» → (2, 5); для остальных ключей — None."""
    match = _QUESTION_KEY_RE.match(key)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def get(key: str) -> str:
    q = _question_key(key)
    if q:
        number, option = q
        question, options = texts.QUESTIONS[number - 1]
        return options[option - 1] if option else question
    name, _, sub = key.partition(".")
    value = getattr(texts, name)
    return value[Category(sub)] if sub else value


def _set(key: str, value: str) -> None:
    q = _question_key(key)
    if q:
        number, option = q
        idx = number - 1
        question, options = texts.QUESTIONS[idx]
        if option:
            opts = list(options)
            opts[option - 1] = value
            new = (question, tuple(opts))
        else:
            new = (value, options)
        questions = list(texts.QUESTIONS)
        questions[idx] = new
        texts.QUESTIONS = tuple(questions)
        return
    name, _, sub = key.partition(".")
    if sub:
        getattr(texts, name)[Category(sub)] = value
    else:
        setattr(texts, name, value)


# Исходные значения из texts.py — снимаем до применения правок.
DEFAULTS: dict[str, str] = {key: get(key) for key in ITEMS}


def placeholders(value: str) -> set[str] | None:
    """Имена {подстановок} в тексте; None — если фигурные скобки расставлены неправильно."""
    try:
        return {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
    except ValueError:
        return None


def validate(key: str, value: str) -> str | None:
    """Текст ошибки или None, если значение подходит."""
    item = ITEMS[key]
    value = value.strip()
    if not value:
        return "Текст не может быть пустым."
    limit = MAX_BUTTON_LEN if item.plain else MAX_MESSAGE_LEN
    if len(value) > limit:
        return f"Слишком длинно: {len(value)} символов, максимум {limit}."
    required = placeholders(DEFAULTS[key])
    if required:
        found = placeholders(value)
        if found != required:
            names = ", ".join("{" + n + "}" for n in sorted(required))
            return f"В тексте должны остаться подстановки {names} — без изменений."
    return None


def set_value(key: str, value: str) -> None:
    _set(key, value)


def reset(key: str) -> None:
    _set(key, DEFAULTS[key])


def is_changed(key: str) -> bool:
    return get(key) != DEFAULTS[key]


async def apply_overrides(overrides: dict[str, str]) -> None:
    for key, value in overrides.items():
        if key not in ITEMS:
            logger.warning("Пропускаю неизвестный ключ текста %s", key)
            continue
        if validate(key, value) is not None:
            logger.warning("Пропускаю некорректный текст %s", key)
            continue
        _set(key, value)
    if overrides:
        logger.info("Применено правок текстов: %s", len(overrides))
