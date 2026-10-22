"""Константы бота: категории теста, статусы, теги, callback-данные, интервалы."""

from enum import StrEnum


class Category(StrEnum):
    """Типы затруднений (счётчики теста)."""

    STRUCTURE = "STRUCTURE"
    VOLUME = "VOLUME"
    PERFECTIONISM = "PERFECTIONISM"
    STATE = "STATE"
    FOCUS = "FOCUS"


# Порядок вариантов ответа А–Д совпадает с порядком категорий:
# А → STRUCTURE, Б → VOLUME, В → PERFECTIONISM, Г → STATE, Д → FOCUS.
ANSWER_LETTERS = ("А", "Б", "В", "Г", "Д")
ANSWER_CATEGORIES = (
    Category.STRUCTURE,
    Category.VOLUME,
    Category.PERFECTIONISM,
    Category.STATE,
    Category.FOCUS,
)

QUESTIONS_COUNT = 4

# Значение test_result, когда преобладающей категории нет (все ответы разные).
RESULT_NONE = "NONE"
RESULT_SEPARATOR = ","


class PurchaseStatus(StrEnum):
    NOT_PURCHASED = "not_purchased"
    PENDING = "pending"
    PAID = "paid"


class OrderStatus(StrEnum):
    NEW = "new"
    PAID = "paid"


class OrderChannel(StrEnum):
    BOT = "bot"
    SITE = "site"


class PayMethod(StrEnum):
    RU = "ru"  # карта РФ — Т-Банк
    FOREIGN = "foreign"  # иностранная карта — Prodamus


class SalesStage(StrEnum):
    START = "start"
    QUIZ = "quiz"
    RESULT = "result"
    METHOD = "method"
    EXAMPLE = "example"
    PRODUCT = "product"
    CONTENTS = "contents"
    THINKING = "thinking"
    PAYMENT = "payment"
    CUSTOMER = "customer"


class Tag(StrEnum):
    TERMS_ACCEPTED = "terms_accepted"
    TEST_STARTED = "test_started"
    TEST_COMPLETED = "test_completed"
    PRODUCT_VIEWED = "product_viewed"
    PURCHASE_CLICKED = "purchase_clicked"
    PAYMENT_PENDING = "payment_pending"
    CUSTOMER = "customer"
    FOLLOWUP_OPT_OUT = "followup_opt_out"


def result_tag(category: Category) -> str:
    return f"result_{category.value.lower()}"


RESULT_TAGS = tuple(result_tag(c) for c in Category)


class Cb:
    """Callback-данные inline-кнопок."""

    ACCEPT_TERMS = "terms:accept"
    START_TEST = "test:start"
    RESTART_TEST = "test:restart"
    CONTINUE_TEST = "test:continue"
    ANSWER_PREFIX = "ans"  # ans:<номер вопроса>:<индекс варианта>
    SHOW_CATEGORY_PREFIX = "cat"  # cat:<CATEGORY>
    MY_RESULT = "result:show"
    WHAT_NEXT = "funnel:method"
    SHOW_EXAMPLE = "funnel:example"
    ABOUT_SYSTEM = "funnel:product"
    CONTENTS = "funnel:contents"
    THINK = "funnel:think"
    BACK_TO_PRODUCT = "funnel:product_back"
    BUY = "pay:buy"
    I_PAID = "pay:done"
    ADMIN_CONFIRM_PREFIX = "adm:ok"  # adm:ok:<user_id>
    ADMIN_REJECT_PREFIX = "adm:no"  # adm:no:<user_id>
    # Редактор текстов (только для администраторов)
    TEXTS_MENU = "tx:menu"
    TEXTS_GROUP_PREFIX = "tx:g"  # tx:g:<номер группы>
    TEXTS_ITEM_PREFIX = "tx:k"  # tx:k:<ключ текста>
    TEXTS_EDIT_PREFIX = "tx:e"  # tx:e:<ключ текста>
    TEXTS_RESET_PREFIX = "tx:r"  # tx:r:<ключ текста>


# Интервалы фоновых сообщений (в секундах, до умножения на DELAY_SCALE из конфига).
HOUR = 60 * 60
FOLLOWUP_DELAYS = (24 * HOUR, 48 * HOUR, 48 * HOUR)
FOLLOWUP_STEPS = len(FOLLOWUP_DELAYS)
QUIZ_REMINDER_DELAY = 24 * HOUR

# Как часто фоновый планировщик проверяет базу.
SCHEDULER_TICK_SECONDS = 60
# Пауза между отправками, чтобы не упираться в лимиты Telegram.
SEND_PAUSE_SECONDS = 0.05
