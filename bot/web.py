"""HTTP-сервер рядом с ботом: уведомления об оплате и API для формы оплаты на лендинге.

POST /webhooks/tbank     — уведомления Т-Банка (JSON, подпись Token)
POST /webhooks/prodamus  — уведомления Prodamus (форма, подпись в заголовке Sign)
POST /api/checkout       — форма на сайте: создаёт заказ и возвращает ссылку на оплату
GET  /api/orders/{id}    — статус заказа для страницы «Спасибо» и ссылки на группы после оплаты
GET  /health             — проверка, что сервер жив
"""

import html
import logging
import re
import time
from collections import defaultdict, deque

import aiohttp
from aiohttp import web

from bot.config import Settings
from bot.constants import OrderChannel, PayMethod
from bot.services import prodamus, tbank
from bot.services.payments import PaymentService

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
ORDER_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Не больше CHECKOUT_LIMIT заказов с одного IP за CHECKOUT_WINDOW секунд.
CHECKOUT_LIMIT = 10
CHECKOUT_WINDOW = 10 * 60

SETTINGS_KEY = web.AppKey("settings", Settings)
PAYMENTS_KEY = web.AppKey("payments", PaymentService)
RATE_KEY = web.AppKey("rate", dict)


def _cors_headers(request: web.Request) -> dict[str, str]:
    origin = request.headers.get("Origin", "").rstrip("/")
    allowed = request.app[SETTINGS_KEY].cors_origins
    if origin and origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Vary": "Origin",
        }
    return {}


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=_cors_headers(request))
    try:
        response = await handler(request)
    except web.HTTPException as e:
        e.headers.update(_cors_headers(request))
        raise
    response.headers.update(_cors_headers(request))
    return response


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


# ---------- Вебхуки платёжных систем ----------

async def tbank_webhook(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    payments = request.app[PAYMENTS_KEY]
    if not settings.tbank_enabled:
        # Без пароля терминала подпись не проверить — такие уведомления не принимаем.
        return web.Response(status=404, text="not configured")
    try:
        data = await request.json()
    except ValueError:
        return web.Response(status=400, text="bad json")
    if not isinstance(data, dict):
        return web.Response(status=400, text="bad json")

    if not tbank.verify_notification(data, settings.tbank_terminal_key, settings.tbank_password):
        logger.warning("Т-Банк: неверная подпись уведомления %s", data.get("OrderId"))
        return web.Response(status=403, text="bad token")

    if data.get("Status") == tbank.STATUS_CONFIRMED and data.get("Success") in (True, "true"):
        order = await payments.find_order(str(data.get("OrderId", "")))
        if order is None:
            logger.warning("Т-Банк: заказ %s не найден", data.get("OrderId"))
        else:
            amount = int(data.get("Amount", 0)) / 100
            await payments.confirm(order, str(data.get("PaymentId", "")) or None, amount)
    # Т-Банк ждёт ответ «OK», иначе будет присылать уведомление повторно.
    return web.Response(text="OK")


async def prodamus_webhook(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    payments = request.app[PAYMENTS_KEY]
    if not settings.prodamus_enabled:
        return web.Response(status=404, text="not configured")
    form = await request.post()
    data = prodamus.parse_form((k, str(v)) for k, v in form.items())

    if not prodamus.verify(data, settings.prodamus_secret, request.headers.get("Sign", "")):
        logger.warning("Prodamus: неверная подпись уведомления %s", prodamus.order_number(data))
        return web.Response(status=403, text="bad sign")

    if data.get("payment_status") == prodamus.STATUS_SUCCESS:
        order = await payments.find_order(str(data.get("order_num", "")), str(data.get("order_id", "")))
        if order is None:
            logger.warning("Prodamus: заказ %s не найден", prodamus.order_number(data))
        else:
            try:
                amount = float(str(data.get("sum", "0")).replace(",", "."))
            except ValueError:
                amount = None
            await payments.confirm(order, str(data.get("order_id", "")) or None, amount)
    return web.Response(text="success")


# ---------- API для лендинга ----------

def _rate_limited(request: web.Request) -> bool:
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    hits: deque[float] = request.app[RATE_KEY][ip]
    now = time.monotonic()
    while hits and now - hits[0] > CHECKOUT_WINDOW:
        hits.popleft()
    if len(hits) >= CHECKOUT_LIMIT:
        return True
    hits.append(now)
    return False


def _field(data: dict, name: str, limit: int) -> str:
    value = data.get(name)
    return value.strip()[:limit] if isinstance(value, str) else ""


async def checkout(request: web.Request) -> web.Response:
    payments = request.app[PAYMENTS_KEY]
    if _rate_limited(request):
        return _json_error("Слишком много попыток. Попробуйте через несколько минут.", 429)
    try:
        data = await request.json()
    except ValueError:
        return _json_error("Некорректный запрос.")
    if not isinstance(data, dict):
        return _json_error("Некорректный запрос.")

    try:
        method = PayMethod(data.get("method"))
    except ValueError:
        return _json_error("Выберите способ оплаты.")

    last_name = _field(data, "lastName", 100)
    first_name = _field(data, "firstName", 100)
    middle_name = _field(data, "middleName", 100)
    email = _field(data, "email", 254)
    phone = _field(data, "phone", 32)

    if not (last_name and first_name and middle_name and phone):
        return _json_error("Заполните все поля.")
    if not EMAIL_RE.match(email):
        return _json_error("Проверьте адрес электронной почты.")
    if data.get("consents") is not True:
        return _json_error("Нужно принять условия и дать согласия.")

    # Пришёл из бота по ссылке с ?tg=<id> — привязываем заказ к пользователю бота.
    user_id = await payments.bot_user_for_checkout(data.get("telegramId"))

    link = await payments.create_link(
        method, OrderChannel.SITE, user_id=user_id,
        full_name=f"{last_name} {first_name} {middle_name}", email=email, phone=phone,
    )
    if link is None:
        return _json_error("Этот способ оплаты пока недоступен. Выберите другой.", 503)
    return web.json_response({"url": link.url, "orderId": link.order_id, "automatic": link.automatic})


async def order_status(request: web.Request) -> web.Response:
    payments = request.app[PAYMENTS_KEY]
    order_id = request.match_info["order_id"]
    if not ORDER_ID_RE.match(order_id):
        return _json_error("Заказ не найден.", 404)
    order = await payments.orders.get(order_id)
    if order is None or order.channel != OrderChannel.SITE:
        return _json_error("Заказ не найден.", 404)
    # Ссылки на закрытые группы отдаём только после подтверждённой оплаты.
    body: dict[str, object] = {"status": order.status.value}
    if order.is_paid:
        body["links"] = payments.access_links()
    return web.json_response(body)


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


# ---------- Фальшивая форма оплаты для локальной проверки (DEV_FAKE_PAYMENTS=1) ----------

DEV_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Тестовая оплата</title>
<style>body{{font-family:system-ui,sans-serif;background:#f7f2e9;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#fff;padding:32px;border-radius:20px;max-width:420px;width:calc(100% - 32px);box-shadow:0 10px 40px #0001}}
p{{color:#555;line-height:1.6}}button{{width:100%;padding:14px;border:0;border-radius:30px;font-size:15px;margin-top:10px;cursor:pointer}}
.pay{{background:#0b4939;color:#fff}}.cancel{{background:#eee}}</style></head><body>
<form method="post" action="/dev/payform/pay">
<h2>⚠️ Тестовая оплата</h2>
<p>Это не настоящая платёжная форма — деньги не списываются. Она нужна только для локальной проверки.</p>
<p><b>{product}</b><br>Сумма: {price} ₽<br>Почта: {email}<br>Заказ: <code>{order_id}</code></p>
<input type="hidden" name="order_id" value="{order_id}"><input type="hidden" name="price" value="{price}">
<input type="hidden" name="url_success" value="{url_success}"><input type="hidden" name="url_return" value="{url_return}">
<button class="pay" name="action" value="pay">Оплатить (тест)</button>
<button class="cancel" name="action" value="cancel">Отменить</button>
</form></body></html>"""


async def dev_payform(request: web.Request) -> web.Response:
    q = request.query
    page = DEV_PAGE.format(
        product=html.escape(q.get("products[0][name]", "")),
        price=html.escape(q.get("products[0][price]", "")),
        email=html.escape(q.get("customer_email", "—")),
        order_id=html.escape(q.get("order_id", "")),
        url_success=html.escape(q.get("urlSuccess", "")),
        url_return=html.escape(q.get("urlReturn", "")),
    )
    return web.Response(text=page, content_type="text/html")


async def dev_pay(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    form = await request.post()
    if form.get("action") != "pay":
        raise web.HTTPSeeOther(str(form.get("url_return") or "/health"))

    # Шлём себе такое же уведомление, как прислал бы Prodamus, — с настоящей подписью.
    price = str(form.get("price", "0"))
    notification = {
        "order_id": "dev-" + str(form.get("order_id", "")),
        "order_num": str(form.get("order_id", "")),
        "sum": f"{price}.00",
        "payment_status": prodamus.STATUS_SUCCESS,
        "products[0][name]": settings.product_name,
        "products[0][price]": f"{price}.00",
    }
    signature = prodamus.sign(prodamus.parse_form(notification.items()), settings.prodamus_secret)
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{request.scheme}://{request.host}/webhooks/prodamus",
                                data=notification, headers={"Sign": signature}) as resp:
            logger.info("Тестовая оплата %s: вебхук ответил %s", notification["order_num"], resp.status)
    raise web.HTTPSeeOther(str(form.get("url_success") or "/health"))


def build_app(settings: Settings, payments: PaymentService) -> web.Application:
    app = web.Application(middlewares=[cors_middleware], client_max_size=64 * 1024)
    app[SETTINGS_KEY] = settings
    app[PAYMENTS_KEY] = payments
    app[RATE_KEY] = defaultdict(deque)
    app.router.add_post("/webhooks/tbank", tbank_webhook)
    app.router.add_post("/webhooks/prodamus", prodamus_webhook)
    app.router.add_post("/api/checkout", checkout)
    app.router.add_route("OPTIONS", "/api/checkout", checkout)  # preflight обрабатывает middleware
    app.router.add_get("/api/orders/{order_id}", order_status)
    app.router.add_route("OPTIONS", "/api/orders/{order_id}", order_status)
    app.router.add_get("/health", health)
    if settings.dev_fake_payments:
        logger.warning("ВКЛЮЧЕНА ТЕСТОВАЯ ОПЛАТА (DEV_FAKE_PAYMENTS=1) — только для локальной проверки!")
        app.router.add_get("/dev/payform/", dev_payform)
        app.router.add_post("/dev/payform/pay", dev_pay)
    return app
