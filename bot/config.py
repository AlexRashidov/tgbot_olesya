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
    )
