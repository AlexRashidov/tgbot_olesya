"""Логика теста: подсчёт результата. Без зависимостей от Telegram и БД — легко тестировать."""

from bot.constants import (
    ANSWER_CATEGORIES,
    RESULT_NONE,
    RESULT_SEPARATOR,
    Category,
    result_tag,
)


def category_for_answer(option_index: int) -> Category:
    return ANSWER_CATEGORIES[option_index]


def leading_categories(scores: dict[Category, int]) -> list[Category]:
    """Ведущие категории.

    • одна категория с максимумом баллов — один результат;
    • несколько категорий с одинаковым максимумом — смешанный результат;
    • все ответы в разных категориях (максимум = 1) — преобладающей нет, возвращается [].
    """
    top = max(scores.values(), default=0)
    if top <= 1:
        return []
    return [c for c in Category if scores.get(c, 0) == top]


def encode_result(categories: list[Category]) -> str:
    return RESULT_SEPARATOR.join(c.value for c in categories) if categories else RESULT_NONE


def decode_result(raw: str) -> list[Category]:
    if not raw or raw == RESULT_NONE:
        return []
    return [Category(x) for x in raw.split(RESULT_SEPARATOR)]


def tags_for_result(categories: list[Category]) -> list[str]:
    return [result_tag(c) for c in categories]


def answered_categories(scores: dict[Category, int]) -> list[Category]:
    """Категории, которые встретились в ответах (для случая «нет преобладающего»)."""
    return [c for c in Category if scores.get(c, 0) > 0]
