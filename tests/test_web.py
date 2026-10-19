"""Сквозная проверка оплаты: веб-сервер + SQLite + PaymentService, вместо Telegram — заглушка."""

import asyncio
from urllib.parse import parse_qsl, urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Settings
from bot.constants import OrderChannel, PayMethod, PurchaseStatus
from bot.db import Database, OrderRepository, UserRepository
from bot.services import prodamus, tbank
from bot.services.payments import PaymentService
from bot.web import build_app

SECRET = "prodamus-secret"


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: object) -> None:
        self.sent.append((chat_id, text))


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        bot_token="x", database_path=tmp_path / "bot.db", admin_ids=(999,),
        payment_url_ru="https://static-ru", payment_url_foreign="", materials_url="https://materials",
        delay_scale=1.0, scheduler_tick=60, price_rub=2500, product_name="Таблетка",
        web_host="127.0.0.1", web_port=0, public_base_url="https://bot.example", site_url="https://site.example/",
        cors_origins=("https://site.example",),
        tbank_terminal_key="TK", tbank_password="PW", tbank_api_url="https://unused", tbank_receipt=True,
        tbank_taxation="usn_income", tbank_vat="none",
        prodamus_form_url="https://shop.payform.ru", prodamus_secret=SECRET, prodamus_payment_methods="",
        access_tg_url="https://t.me/+group", access_vk_url="", access_max_url="",
    )
    values.update(overrides)
    return Settings(**values)


def run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path, **overrides):
    settings = make_settings(tmp_path, **overrides)
    db = Database(settings.database_path)
    await db.connect()
    users, orders = UserRepository(db), OrderRepository(db)
    bot = FakeBot()
    payments = PaymentService(bot, settings, users, orders, None, "test_bot")  # type: ignore[arg-type]
    client = TestClient(TestServer(build_app(settings, payments)))
    await client.start_server()
    return settings, db, users, orders, bot, payments, client


def _prodamus_notification(order_num: str, amount: str = "2500.00", status: str = "success"):
    form = {"order_id": "777", "order_num": order_num, "sum": amount, "payment_status": status,
            "products[0][name]": "Таблетка", "products[0][price]": amount}
    signature = prodamus.sign(prodamus.parse_form(form.items()), SECRET)
    return form, signature


def test_site_checkout_and_prodamus_webhook(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            body = {"method": "foreign", "lastName": "Иванова", "firstName": "Анна", "middleName": "Петровна",
                    "email": "anna@example.com", "phone": "+79000000000", "consents": True}
            resp = await client.post("/api/checkout", json=body, headers={"Origin": "https://site.example"})
            assert resp.status == 200
            assert resp.headers["Access-Control-Allow-Origin"] == "https://site.example"
            data = await resp.json()
            assert data["automatic"] is True
            order_id = data["orderId"]
            query = dict(parse_qsl(urlsplit(data["url"]).query))
            assert query["urlSuccess"] == f"https://site.example/?order={order_id}"

            # До оплаты ссылок на группы нет.
            status = await (await client.get(f"/api/orders/{order_id}")).json()
            assert status == {"status": "new"}

            # Поддельная подпись отклоняется.
            form, signature = _prodamus_notification(order_id)
            resp = await client.post("/webhooks/prodamus", data=form, headers={"Sign": "bad"})
            assert resp.status == 403

            resp = await client.post("/webhooks/prodamus", data=form, headers={"Sign": signature})
            assert resp.status == 200
            # Повторное уведомление не дублирует уведомление админу.
            await client.post("/webhooks/prodamus", data=form, headers={"Sign": signature})

            status = await (await client.get(f"/api/orders/{order_id}")).json()
            assert status == {"status": "paid", "links": {"telegram": "https://t.me/+group"}}
            admin_messages = [t for chat, t in bot.sent if chat == 999]
            assert len(admin_messages) == 1 and "Иванова Анна Петровна" in admin_messages[0]
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_bot_order_paid_via_tbank_webhook(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            await users.upsert(42, "anna", "Анна")
            await users.set_payment_pending(42)
            order = await orders.create("a" * 32, OrderChannel.BOT, PayMethod.RU, 2500, user_id=42)

            notification = {"TerminalKey": "TK", "OrderId": order.order_id, "Success": True,
                            "Status": "CONFIRMED", "PaymentId": 123, "ErrorCode": "0", "Amount": 250000}
            notification["Token"] = tbank.make_token(notification, "PW")
            resp = await client.post("/webhooks/tbank", json=notification)
            assert await resp.text() == "OK"

            user = await users.get(42)
            assert user.purchase_status == PurchaseStatus.PAID
            assert user.followup_next_at is None
            assert any(chat == 42 for chat, _ in bot.sent)  # покупатель получил материалы
            assert (await orders.get(order.order_id)).payment_id == "123"
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_wrong_amount_does_not_grant_access(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            await users.upsert(7, None, "Олег")
            order = await orders.create("b" * 32, OrderChannel.BOT, PayMethod.FOREIGN, 2500, user_id=7)
            form, signature = _prodamus_notification(order.order_id, amount="10.00")
            await client.post("/webhooks/prodamus", data=form, headers={"Sign": signature})
            assert not (await orders.get(order.order_id)).is_paid
            assert not (await users.get(7)).is_customer
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_webhooks_disabled_without_secrets(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(
            tmp_path, prodamus_secret="", tbank_password="")
        try:
            assert (await client.post("/webhooks/prodamus", data={"a": "b"})).status == 404
            assert (await client.post("/webhooks/tbank", json={})).status == 404
        finally:
            await client.close()
            await db.close()

    run(scenario())


@pytest.mark.parametrize("body, status", [
    ({"method": "ru"}, 400),
    ({"method": "crypto", "lastName": "a", "firstName": "b", "middleName": "c", "email": "a@b.ru",
      "phone": "1", "consents": True}, 400),
    ({"method": "ru", "lastName": "a", "firstName": "b", "middleName": "c", "email": "bad",
      "phone": "1", "consents": True}, 400),
    ({"method": "ru", "lastName": "a", "firstName": "b", "middleName": "c", "email": "a@b.ru",
      "phone": "1", "consents": False}, 400),
])
def test_checkout_validation(tmp_path, body, status):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            assert (await client.post("/api/checkout", json=body)).status == status
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_site_purchase_from_bot_link_unlocks_bot(tmp_path):
    """Бот → «Купить» → лендинг с ?tg=<id> → оплата → материалы в боте и конец прогрева."""
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            await users.upsert(55, "anna", "Анна")
            body = {"method": "foreign", "lastName": "a", "firstName": "b", "middleName": "c",
                    "email": "a@b.ru", "phone": "1", "consents": True, "telegramId": "55"}
            data = await (await client.post("/api/checkout", json=body)).json()
            order = await orders.get(data["orderId"])
            assert order.channel == OrderChannel.SITE and order.user_id == 55
            assert (await users.get(55)).purchase_status == PurchaseStatus.PENDING

            form, signature = _prodamus_notification(order.order_id)
            await client.post("/webhooks/prodamus", data=form, headers={"Sign": signature})

            user = await users.get(55)
            assert user.is_customer and user.followup_next_at is None
            assert any(chat == 55 for chat, _ in bot.sent)  # материалы пришли в бот
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_unknown_telegram_id_is_ignored(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            body = {"method": "foreign", "lastName": "a", "firstName": "b", "middleName": "c",
                    "email": "a@b.ru", "phone": "1", "consents": True, "telegramId": "999999"}
            data = await (await client.post("/api/checkout", json=body)).json()
            assert (await orders.get(data["orderId"])).user_id is None
            assert await payments.bot_user_for_checkout("abc") is None
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_dev_fake_payform_pays_order(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path, dev_fake_payments=True)
        try:
            body = {"method": "foreign", "lastName": "a", "firstName": "b", "middleName": "c",
                    "email": "a@b.ru", "phone": "1", "consents": True}
            data = await (await client.post("/api/checkout", json=body)).json()
            query = dict(parse_qsl(urlsplit(data["url"]).query))
            page = await client.get("/dev/payform/", params=query)
            assert "Тестовая оплата" in await page.text()

            resp = await client.post("/dev/payform/pay", allow_redirects=False, data={
                "action": "pay", "order_id": query["order_id"], "price": query["products[0][price]"],
                "url_success": query["urlSuccess"], "url_return": query["urlReturn"],
            })
            assert resp.status == 303
            assert (await orders.get(data["orderId"])).is_paid
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_dev_payform_is_off_by_default(tmp_path):
    async def scenario():
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path)
        try:
            assert (await client.get("/dev/payform/")).status == 404
        finally:
            await client.close()
            await db.close()

    run(scenario())


def test_checkout_falls_back_to_static_link(tmp_path):
    async def scenario():
        # Т-Банк не настроен → статичная ссылка без автоподтверждения.
        settings, db, users, orders, bot, payments, client = await _setup(tmp_path, tbank_terminal_key="")
        try:
            body = {"method": "ru", "lastName": "a", "firstName": "b", "middleName": "c",
                    "email": "a@b.ru", "phone": "1", "consents": True}
            data = await (await client.post("/api/checkout", json=body)).json()
            assert data == {"url": "https://static-ru", "orderId": None, "automatic": False}
        finally:
            await client.close()
            await db.close()

    run(scenario())
