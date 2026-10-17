import asyncio

import pytest

from bot import texts
from bot.constants import Category
from bot.services import text_store


@pytest.fixture(autouse=True)
def restore_texts():
    yield
    for key in text_store.ITEMS:
        text_store.reset(key)


def test_every_item_is_readable_and_has_default():
    for key in text_store.ITEMS:
        assert text_store.get(key) == text_store.DEFAULTS[key]


def test_constants_starting_with_q_are_not_questions():
    text_store.set_value("QUIZ_REMINDER", "Напоминание")
    assert texts.QUIZ_REMINDER == "Напоминание"


def test_set_and_reset_plain_constant():
    text_store.set_value("START", "Новый текст")
    assert texts.START == "Новый текст"
    assert text_store.is_changed("START")
    text_store.reset("START")
    assert not text_store.is_changed("START")


def test_set_result_and_question_option():
    text_store.set_value("RESULTS.FOCUS", "Фокус")
    assert texts.RESULTS[Category.FOCUS] == "Фокус"

    text_store.set_value("Q2", "Новый вопрос")
    text_store.set_value("Q2.5", "Новый вариант Д")
    question, options = texts.QUESTIONS[1]
    assert question == "Новый вопрос"
    assert options[4] == "Новый вариант Д"
    assert len(options) == 5


def test_validate_requires_placeholders():
    assert text_store.validate("RESULT_NONE", "Без подстановки") is not None
    assert text_store.validate("RESULT_NONE", "Список: {titles}") is None
    assert text_store.validate("RESULT_NONE", "Сломано {titles") is not None


def test_validate_limits():
    assert text_store.validate("BTN_BUY", "x" * 65) is not None
    assert text_store.validate("BTN_BUY", "Купить") is None
    assert text_store.validate("START", "   ") is not None


def test_apply_overrides_skips_unknown_and_invalid():
    asyncio.run(text_store.apply_overrides({
        "START": "Из базы",
        "NOPE": "x",
        "RESULT_NONE": "без подстановки",
    }))
    assert texts.START == "Из базы"
    assert texts.RESULT_NONE == text_store.DEFAULTS["RESULT_NONE"]
