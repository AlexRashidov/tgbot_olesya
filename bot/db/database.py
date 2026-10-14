"""Подключение к SQLite и создание схемы."""

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id             INTEGER PRIMARY KEY,
    username            TEXT,
    first_name          TEXT,
    source              TEXT,

    test_started        INTEGER NOT NULL DEFAULT 0,
    test_completed      INTEGER NOT NULL DEFAULT 0,
    current_question    INTEGER NOT NULL DEFAULT 0,
    answer_1            TEXT,
    answer_2            TEXT,
    answer_3            TEXT,
    answer_4            TEXT,
    score_structure     INTEGER NOT NULL DEFAULT 0,
    score_volume        INTEGER NOT NULL DEFAULT 0,
    score_perfectionism INTEGER NOT NULL DEFAULT 0,
    score_state         INTEGER NOT NULL DEFAULT 0,
    score_focus         INTEGER NOT NULL DEFAULT 0,
    test_result         TEXT,
    quiz_started_at     INTEGER,
    quiz_reminder_sent  INTEGER NOT NULL DEFAULT 0,

    product_interest    INTEGER NOT NULL DEFAULT 0,
    purchase_status     TEXT NOT NULL DEFAULT 'not_purchased',
    sales_stage         TEXT NOT NULL DEFAULT 'start',

    followup_status     INTEGER NOT NULL DEFAULT 1,
    followup_step       INTEGER NOT NULL DEFAULT 0,
    followup_next_at    INTEGER,

    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_tags (
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_users_followup ON users(followup_next_at);
"""


class Database:
    """Одно соединение aiosqlite на всё приложение (SQLite сам сериализует запись)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена, сначала вызови connect().")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("SQLite подключена: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
