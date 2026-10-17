"""Настройки из переменных окружения / файла .env (токены, строка подключения к БД, ссылки)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from bot.constants import SCHEDULER_TICK_SECONDS

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _int_list(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in raw.replace(" ", "").split(",") if x)


def _str_list(raw: str) -> tuple[str, ...]:
    return tuple(x.strip().rstrip("/") for x in raw.split(",") if x.strip())


def _bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    admin_ids: tuple[int, ...]
    payment_url_ru: str
    payment_url_foreign: str
    materials_url: str
    delay_scale: float
    scheduler_tick: int

    # Продукт
    price_rub: int
    product_name: str

    # Веб-сервер для вебхуков оплаты и формы на сайте
    web_host: str
    web_port: int
    public_base_url: str  # https://bot.example.ru — адрес, по которому платёжки шлют уведомления
    site_url: str  # адрес лендинга, куда возвращать покупателя с сайта
    cors_origins: tuple[str, ...]

    # Т-Банк (интернет-эквайринг)
    tbank_terminal_key: str
    tbank_password: str
    tbank_api_url: str
    tbank_receipt: bool
    tbank_taxation: str
    tbank_vat: str

    # Prodamus
    prodamus_form_url: str
    prodamus_secret: str
    prodamus_payment_methods: str

    # Куда пускать покупателя с сайта после оплаты
    access_tg_url: str
    access_vk_url: str
    access_max_url: str

    # Только для локальной проверки: фальшивая форма Prodamus на /dev/payform. Никогда не включать на сервере.
    dev_fake_payments: bool = False

    @property
    def tbank_enabled(self) -> bool:
        return bool(self.tbank_terminal_key and self.tbank_password and self.public_base_url)

    @property
    def prodamus_enabled(self) -> bool:
        return bool(self.prodamus_form_url and self.prodamus_secret and self.public_base_url)

    @property
    def web_enabled(self) -> bool:
        return self.web_port > 0


def _database_path(url: str) -> Path:
    # Формат как у SQLAlchemy: sqlite:///relative.db или sqlite:///C:/abs/path.db
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"DATABASE_URL должен начинаться с {prefix!r}, получено: {url!r}")
    path = Path(url[len(prefix):])
    return path if path.is_absolute() else BASE_DIR / path


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируй .env.example в .env и впиши токен от @BotFather.")

    return Settings(
        bot_token=token,
        database_path=_database_path(os.getenv("DATABASE_URL", "sqlite:///data/bot.db")),
        admin_ids=_int_list(os.getenv("ADMIN_IDS", "")),
        payment_url_ru=os.getenv("PAYMENT_URL_RU", "").strip(),
        payment_url_foreign=os.getenv("PAYMENT_URL_FOREIGN", "").strip(),
        materials_url=os.getenv("MATERIALS_URL", "").strip(),
        delay_scale=float(os.getenv("DELAY_SCALE", "1")),
        scheduler_tick=int(os.getenv("SCHEDULER_TICK_SECONDS", str(SCHEDULER_TICK_SECONDS))),
        price_rub=int(os.getenv("PRICE_RUB", "2500")),
        product_name=os.getenv("PRODUCT_NAME", "Таблетка от прокрастинации").strip(),
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        site_url=os.getenv("SITE_URL", "").strip(),
        cors_origins=_str_list(os.getenv("CORS_ORIGINS", "")),
        tbank_terminal_key=os.getenv("TBANK_TERMINAL_KEY", "").strip(),
        tbank_password=os.getenv("TBANK_PASSWORD", "").strip(),
        tbank_api_url=os.getenv("TBANK_API_URL", "https://securepay.tinkoff.ru/v2").strip().rstrip("/"),
        tbank_receipt=_bool(os.getenv("TBANK_RECEIPT", "1")),
        tbank_taxation=os.getenv("TBANK_TAXATION", "usn_income").strip(),
        tbank_vat=os.getenv("TBANK_VAT", "none").strip(),
        prodamus_form_url=os.getenv("PRODAMUS_FORM_URL", "").strip().rstrip("/"),
        prodamus_secret=os.getenv("PRODAMUS_SECRET", "").strip(),
        prodamus_payment_methods=os.getenv("PRODAMUS_PAYMENT_METHODS", "").strip(),
        access_tg_url=os.getenv("ACCESS_TG_URL", "").strip(),
        access_vk_url=os.getenv("ACCESS_VK_URL", "").strip(),
        access_max_url=os.getenv("ACCESS_MAX_URL", "").strip(),
        dev_fake_payments=_bool(os.getenv("DEV_FAKE_PAYMENTS", "0")),
    )
