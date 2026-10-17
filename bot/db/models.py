"""Модель пользователя, собранная из строки таблицы users."""

from dataclasses import dataclass

import aiosqlite

from bot.constants import Category, OrderChannel, OrderStatus, PayMethod, PurchaseStatus


@dataclass(slots=True)
class User:
    user_id: int
    username: str | None
    first_name: str | None
    source: str | None
    test_started: bool
    test_completed: bool
    current_question: int
    answers: tuple[str | None, str | None, str | None, str | None]
    scores: dict[Category, int]
    test_result: str | None
    product_interest: bool
    purchase_status: PurchaseStatus
    sales_stage: str
    followup_status: bool
    followup_step: int
    followup_next_at: int | None
    email: str | None

    @property
    def is_customer(self) -> bool:
        return self.purchase_status == PurchaseStatus.PAID

    @property
    def quiz_in_progress(self) -> bool:
        return self.test_started and not self.test_completed and self.current_question > 0

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "User":
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            source=row["source"],
            test_started=bool(row["test_started"]),
            test_completed=bool(row["test_completed"]),
            current_question=row["current_question"],
            answers=(row["answer_1"], row["answer_2"], row["answer_3"], row["answer_4"]),
            scores={c: row[score_column(c)] for c in Category},
            test_result=row["test_result"],
            product_interest=bool(row["product_interest"]),
            purchase_status=PurchaseStatus(row["purchase_status"]),
            sales_stage=row["sales_stage"],
            followup_status=bool(row["followup_status"]),
            followup_step=row["followup_step"],
            followup_next_at=row["followup_next_at"],
            email=row["email"],
        )


@dataclass(slots=True)
class Order:
    order_id: str
    channel: OrderChannel
    method: PayMethod
    user_id: int | None
    amount: int
    status: OrderStatus
    full_name: str | None
    email: str | None
    phone: str | None
    payment_id: str | None
    created_at: int
    paid_at: int | None

    @property
    def is_paid(self) -> bool:
        return self.status == OrderStatus.PAID

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Order":
        return cls(
            order_id=row["order_id"],
            channel=OrderChannel(row["channel"]),
            method=PayMethod(row["method"]),
            user_id=row["user_id"],
            amount=row["amount"],
            status=OrderStatus(row["status"]),
            full_name=row["full_name"],
            email=row["email"],
            phone=row["phone"],
            payment_id=row["payment_id"],
            created_at=row["created_at"],
            paid_at=row["paid_at"],
        )


def score_column(category: Category) -> str:
    return f"score_{category.value.lower()}"
