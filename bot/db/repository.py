"""Все SQL-запросы к пользователям и тегам."""

import time
from collections.abc import Iterable

from bot.constants import (
    QUESTIONS_COUNT,
    RESULT_TAGS,
    Category,
    OrderChannel,
    OrderStatus,
    PayMethod,
    PurchaseStatus,
    SalesStage,
    Tag,
)
from bot.db.database import Database
from bot.db.models import Order, User, score_column


def now() -> int:
    return int(time.time())


class UserRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------- Пользователи ----------

    async def get(self, user_id: int) -> User | None:
        async with self._db.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return User.from_row(row) if row else None

    async def upsert(self, user_id: int, username: str | None, first_name: str | None,
                     source: str | None = None) -> User:
        ts = now()
        await self._db.conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                source = COALESCE(users.source, excluded.source),
                updated_at = excluded.updated_at
            """,
            (user_id, username, first_name, source, ts, ts),
        )
        await self._db.conn.commit()
        user = await self.get(user_id)
        assert user is not None
        return user

    async def _update(self, user_id: int, **fields: object) -> None:
        # Имена полей приходят только из кода этого модуля, не от пользователя.
        fields["updated_at"] = now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        await self._db.conn.execute(
            f"UPDATE users SET {assignments} WHERE user_id = ?",
            (*fields.values(), user_id),
        )
        await self._db.conn.commit()

    async def set_stage(self, user_id: int, stage: SalesStage) -> None:
        await self._update(user_id, sales_stage=stage.value)

    async def set_product_interest(self, user_id: int) -> None:
        await self._update(user_id, product_interest=1)

    async def set_email(self, user_id: int, email: str) -> None:
        await self._update(user_id, email=email)

    async def set_followup_allowed(self, user_id: int, allowed: bool) -> None:
        await self._update(user_id, followup_status=int(allowed))
        if allowed:
            await self.remove_tags(user_id, [Tag.FOLLOWUP_OPT_OUT])
        else:
            await self.add_tags(user_id, [Tag.FOLLOWUP_OPT_OUT])

    # ---------- Тест ----------

    async def start_quiz(self, user_id: int) -> None:
        """Начать тест с нуля. Покупку и состояние прогрева не трогает."""
        await self._update(
            user_id,
            test_started=1,
            test_completed=0,
            current_question=1,
            answer_1=None, answer_2=None, answer_3=None, answer_4=None,
            **{score_column(c): 0 for c in Category},
            test_result=None,
            quiz_started_at=now(),
            quiz_reminder_sent=0,
            sales_stage=SalesStage.QUIZ.value,
        )
        await self.remove_tags(user_id, [Tag.TEST_COMPLETED, *RESULT_TAGS])
        await self.add_tags(user_id, [Tag.TEST_STARTED])

    async def save_answer(self, user_id: int, question: int, category: Category) -> bool:
        """Сохраняет ответ, если это текущий вопрос. Возвращает False для устаревшего нажатия."""
        if not 1 <= question <= QUESTIONS_COUNT:
            return False
        column = score_column(category)
        cur = await self._db.conn.execute(
            f"""
            UPDATE users
            SET answer_{question} = ?, {column} = {column} + 1,
                current_question = current_question + 1, updated_at = ?
            WHERE user_id = ? AND current_question = ? AND test_completed = 0
            """,
            (category.value, now(), user_id, question),
        )
        await self._db.conn.commit()
        return cur.rowcount == 1

    async def complete_quiz(self, user_id: int, test_result: str, result_tags: Iterable[str],
                            first_followup_at: int) -> None:
        await self._update(
            user_id,
            test_completed=1,
            current_question=0,
            test_result=test_result,
            sales_stage=SalesStage.RESULT.value,
        )
        await self.add_tags(user_id, [Tag.TEST_COMPLETED, *result_tags])
        # Цепочку прогрева запускаем один раз: повторное прохождение её не перезапускает.
        await self._db.conn.execute(
            """
            UPDATE users SET followup_next_at = ?
            WHERE user_id = ? AND followup_step = 0 AND followup_next_at IS NULL
              AND purchase_status != ?
            """,
            (first_followup_at, user_id, PurchaseStatus.PAID.value),
        )
        await self._db.conn.commit()

    # ---------- Оплата ----------

    async def set_payment_pending(self, user_id: int) -> None:
        await self._db.conn.execute(
            "UPDATE users SET purchase_status = ?, sales_stage = ?, updated_at = ? "
            "WHERE user_id = ? AND purchase_status != ?",
            (PurchaseStatus.PENDING.value, SalesStage.PAYMENT.value, now(), user_id, PurchaseStatus.PAID.value),
        )
        await self._db.conn.commit()
        await self.add_tags(user_id, [Tag.PURCHASE_CLICKED, Tag.PAYMENT_PENDING])

    async def mark_customer(self, user_id: int) -> None:
        await self._update(
            user_id,
            purchase_status=PurchaseStatus.PAID.value,
            sales_stage=SalesStage.CUSTOMER.value,
            followup_next_at=None,  # исключаем из продающей цепочки
        )
        await self.remove_tags(user_id, [Tag.PAYMENT_PENDING])
        await self.add_tags(user_id, [Tag.CUSTOMER])

    async def reset_payment(self, user_id: int) -> None:
        await self._db.conn.execute(
            "UPDATE users SET purchase_status = ?, updated_at = ? WHERE user_id = ? AND purchase_status = ?",
            (PurchaseStatus.NOT_PURCHASED.value, now(), user_id, PurchaseStatus.PENDING.value),
        )
        await self._db.conn.commit()
        await self.remove_tags(user_id, [Tag.PAYMENT_PENDING])

    # ---------- Фоновые задачи ----------

    async def due_followups(self, at: int) -> list[User]:
        async with self._db.conn.execute(
            """
            SELECT * FROM users
            WHERE followup_next_at IS NOT NULL AND followup_next_at <= ?
              AND followup_status = 1 AND purchase_status != ?
            """,
            (at, PurchaseStatus.PAID.value),
        ) as cur:
            rows = await cur.fetchall()
        return [User.from_row(r) for r in rows]

    async def advance_followup(self, user_id: int, step: int, next_at: int | None) -> None:
        await self._update(user_id, followup_step=step, followup_next_at=next_at)

    async def due_quiz_reminders(self, started_before: int) -> list[User]:
        async with self._db.conn.execute(
            """
            SELECT * FROM users
            WHERE test_started = 1 AND test_completed = 0 AND current_question > 0
              AND quiz_reminder_sent = 0 AND followup_status = 1
              AND quiz_started_at <= ?
            """,
            (started_before,),
        ) as cur:
            rows = await cur.fetchall()
        return [User.from_row(r) for r in rows]

    async def mark_quiz_reminder_sent(self, user_id: int) -> None:
        await self._update(user_id, quiz_reminder_sent=1)

    # ---------- Теги ----------

    async def add_tags(self, user_id: int, tags: Iterable[str]) -> None:
        ts = now()
        await self._db.conn.executemany(
            "INSERT OR IGNORE INTO user_tags (user_id, tag, created_at) VALUES (?, ?, ?)",
            [(user_id, str(t), ts) for t in tags],
        )
        await self._db.conn.commit()

    async def remove_tags(self, user_id: int, tags: Iterable[str]) -> None:
        await self._db.conn.executemany(
            "DELETE FROM user_tags WHERE user_id = ? AND tag = ?",
            [(user_id, str(t)) for t in tags],
        )
        await self._db.conn.commit()

    async def get_tags(self, user_id: int) -> set[str]:
        async with self._db.conn.execute("SELECT tag FROM user_tags WHERE user_id = ?", (user_id,)) as cur:
            return {row["tag"] for row in await cur.fetchall()}

    # ---------- Статистика ----------

    async def stats(self) -> dict[str, int]:
        async with self._db.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(test_started), 0) AS started,
                COALESCE(SUM(test_completed), 0) AS completed,
                COALESCE(SUM(purchase_status = ?), 0) AS pending,
                COALESCE(SUM(purchase_status = ?), 0) AS customers,
                COALESCE(SUM(followup_status = 0), 0) AS opted_out
            FROM users
            """,
            (PurchaseStatus.PENDING.value, PurchaseStatus.PAID.value),
        ) as cur:
            row = await cur.fetchone()
        result = dict(row)
        async with self._db.conn.execute(
            "SELECT tag, COUNT(*) AS n FROM user_tags WHERE tag IN (?, ?) GROUP BY tag",
            (Tag.PRODUCT_VIEWED.value, Tag.PURCHASE_CLICKED.value),
        ) as cur:
            by_tag = {r["tag"]: r["n"] for r in await cur.fetchall()}
        result["product_viewed"] = by_tag.get(Tag.PRODUCT_VIEWED.value, 0)
        result["purchase_clicked"] = by_tag.get(Tag.PURCHASE_CLICKED.value, 0)
        async with self._db.conn.execute(
            "SELECT channel, COUNT(*) AS n FROM orders WHERE status = ? GROUP BY channel",
            (OrderStatus.PAID.value,),
        ) as cur:
            by_channel = {r["channel"]: r["n"] for r in await cur.fetchall()}
        result["paid_bot"] = by_channel.get(OrderChannel.BOT.value, 0)
        result["paid_site"] = by_channel.get(OrderChannel.SITE.value, 0)
        return result


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, order_id: str, channel: OrderChannel, method: PayMethod, amount: int,
                     user_id: int | None = None, full_name: str | None = None, email: str | None = None,
                     phone: str | None = None) -> Order:
        await self._db.conn.execute(
            """
            INSERT INTO orders (order_id, channel, method, user_id, amount, full_name, email, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, channel.value, method.value, user_id, amount, full_name, email, phone, now()),
        )
        await self._db.conn.commit()
        order = await self.get(order_id)
        assert order is not None
        return order

    async def get(self, order_id: str) -> Order | None:
        async with self._db.conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
        return Order.from_row(row) if row else None

    async def set_payment_id(self, order_id: str, payment_id: str) -> None:
        await self._db.conn.execute("UPDATE orders SET payment_id = ? WHERE order_id = ?", (payment_id, order_id))
        await self._db.conn.commit()

    async def mark_paid(self, order_id: str, payment_id: str | None) -> bool:
        """True — заказ только что стал оплаченным; False — уже был оплачен (повторный вебхук)."""
        cur = await self._db.conn.execute(
            """
            UPDATE orders SET status = ?, paid_at = ?, payment_id = COALESCE(?, payment_id)
            WHERE order_id = ? AND status != ?
            """,
            (OrderStatus.PAID.value, now(), payment_id, order_id, OrderStatus.PAID.value),
        )
        await self._db.conn.commit()
        return cur.rowcount == 1


class TextRepository:
    """Тексты, изменённые администратором через бота."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def all(self) -> dict[str, str]:
        async with self._db.conn.execute("SELECT key, value FROM text_overrides") as cur:
            return {row["key"]: row["value"] for row in await cur.fetchall()}

    async def set(self, key: str, value: str) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO text_overrides (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now()),
        )
        await self._db.conn.commit()

    async def delete(self, key: str) -> None:
        await self._db.conn.execute("DELETE FROM text_overrides WHERE key = ?", (key,))
        await self._db.conn.commit()
