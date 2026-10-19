"""Оплата: создание заказов и ссылок на оплату, обработка подтверждений от платёжных систем.

Если Т-Банк / Prodamus не настроены в .env, используются статичные ссылки
PAYMENT_URL_RU / PAYMENT_URL_FOREIGN, а оплату подтверждает администратор вручную.
"""

import html
import logging
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from aiogram import Bot

from bot import texts
from bot.config import Settings
from bot.constants import OrderChannel, PayMethod
from bot.db import Order, OrderRepository, UserRepository
from bot.services import prodamus, screens
from bot.services.tbank import TBankClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PaymentLink:
    method: PayMethod
    url: str
    automatic: bool  # True — оплата подтвердится сама по уведомлению платёжной системы
    order_id: str | None = None


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = f"{parts.query}&{urlencode(params)}" if parts.query else urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, parts.fragment))


class PaymentService:
    def __init__(self, bot: Bot, settings: Settings, users: UserRepository, orders: OrderRepository,
                 tbank: TBankClient | None, bot_username: str) -> None:
        self._bot = bot
        self._settings = settings
        self._users = users
        self._orders = orders
        self._tbank = tbank
        self._bot_url = f"https://t.me/{bot_username}"

    @property
    def orders(self) -> OrderRepository:
        return self._orders

    def available_methods(self) -> list[PayMethod]:
        s = self._settings
        methods = []
        if (self._tbank and s.tbank_enabled) or s.payment_url_ru:
            methods.append(PayMethod.RU)
        if s.prodamus_enabled or s.payment_url_foreign:
            methods.append(PayMethod.FOREIGN)
        return methods

    # ---------- Создание ссылок ----------

    async def create_link(self, method: PayMethod, channel: OrderChannel, *, user_id: int | None = None,
                          full_name: str | None = None, email: str | None = None,
                          phone: str | None = None) -> PaymentLink | None:
        s = self._settings
        automatic = (method == PayMethod.RU and self._tbank is not None and s.tbank_enabled) or (
            method == PayMethod.FOREIGN and s.prodamus_enabled
        )
        if not automatic:
            static = s.payment_url_ru if method == PayMethod.RU else s.payment_url_foreign
            return PaymentLink(method, static, automatic=False) if static else None

        order = await self._orders.create(
            uuid.uuid4().hex, channel, method, s.price_rub,
            user_id=user_id, full_name=full_name, email=email, phone=phone,
        )
        if channel == OrderChannel.SITE and s.site_url:
            success_url = _with_query(s.site_url, order=order.order_id)
            fail_url = s.site_url
        else:
            success_url = fail_url = self._bot_url

        try:
            if method == PayMethod.RU:
                assert self._tbank is not None
                payment = await self._tbank.init(
                    order_id=order.order_id,
                    amount_rub=order.amount,
                    description=s.product_name,
                    email=email,
                    success_url=success_url,
                    fail_url=fail_url,
                    notification_url=f"{s.public_base_url}/webhooks/tbank",
                )
                await self._orders.set_payment_id(order.order_id, payment.payment_id)
                url = payment.url
            else:
                url = prodamus.build_link(
                    form_url=s.prodamus_form_url,
                    secret=s.prodamus_secret,
                    order_id=order.order_id,
                    amount_rub=order.amount,
                    product_name=s.product_name,
                    email=email,
                    phone=phone,
                    url_success=success_url,
                    url_return=fail_url,
                    url_notification=f"{s.public_base_url}/webhooks/prodamus",
                    payment_methods=s.prodamus_payment_methods,
                )
        except Exception:
            logger.exception("Не удалось создать платёж %s (%s)", order.order_id, method)
            static = s.payment_url_ru if method == PayMethod.RU else s.payment_url_foreign
            return PaymentLink(method, static, automatic=False) if static else None

        return PaymentLink(method, url, automatic=True, order_id=order.order_id)

    async def links_for_user(self, user_id: int, email: str | None) -> list[PaymentLink]:
        links = []
        for method in self.available_methods():
            link = await self.create_link(method, OrderChannel.BOT, user_id=user_id, email=email)
            if link:
                links.append(link)
        return links

    async def bot_user_for_checkout(self, raw_id: object) -> int | None:
        """Telegram ID из ссылки «Купить» в боте → пользователь бота (или None, если не найден).

        Заодно отмечает, что пользователь перешёл к оплате (статус pending, теги purchase_clicked)."""
        text = str(raw_id).strip() if isinstance(raw_id, (str, int)) else ""
        if not text.isdigit() or len(text) > 15:
            return None
        user = await self._users.get(int(text))
        if user is None:
            return None
        if not user.is_customer:
            await self._users.set_payment_pending(user.user_id)
        return user.user_id

    # ---------- Подтверждение оплаты ----------

    async def find_order(self, *ids: str) -> Order | None:
        for order_id in ids:
            if order_id:
                order = await self._orders.get(order_id)
                if order:
                    return order
        return None

    async def confirm(self, order: Order, payment_id: str | None, amount_rub: float | None) -> None:
        """Вызывается после проверенного уведомления об успешной оплате. Повторные вызовы безопасны."""
        if amount_rub is not None and amount_rub + 0.01 < order.amount:
            logger.error("Заказ %s: оплачено %s ₽ вместо %s ₽ — доступ не выдан", order.order_id,
                         amount_rub, order.amount)
            await self._notify_admins(texts.ADMIN_ORDER_WRONG_AMOUNT.format(
                order_id=order.order_id, paid=amount_rub, expected=order.amount))
            return

        if not await self._orders.mark_paid(order.order_id, payment_id):
            return  # уведомление уже обрабатывали

        logger.info("Заказ %s оплачен (%s, %s)", order.order_id, order.channel, order.method)
        user = await self._users.get(order.user_id) if order.user_id is not None else None
        # Покупатель пришёл из бота (в бот или на сайт по ссылке с его Telegram ID) — выдаём материалы
        # в боте и останавливаем продающую цепочку.
        if user and not user.is_customer:
            await screens.complete_purchase(self._bot, self._users, self._settings, user.user_id)

        if order.channel == OrderChannel.BOT and order.user_id is not None:
            await self._notify_admins(texts.ADMIN_ORDER_PAID_BOT.format(
                user_id=order.user_id,
                name=html.escape(user.first_name or "—") if user else "—",
                username=f"@{user.username}" if user and user.username else "—",
                method=texts.METHOD_TITLES[order.method],
            ))
        else:
            await self._notify_admins(texts.ADMIN_ORDER_PAID_SITE.format(
                name=html.escape(order.full_name or "—"),
                email=html.escape(order.email or "—"),
                phone=html.escape(order.phone or "—"),
                method=texts.METHOD_TITLES[order.method],
            ))

    def access_links(self) -> dict[str, str]:
        s = self._settings
        links = {"telegram": s.access_tg_url, "vk": s.access_vk_url, "max": s.access_max_url}
        return {k: v for k, v in links.items() if v}

    async def _notify_admins(self, text: str) -> None:
        for admin_id in self._settings.admin_ids:
            try:
                await self._bot.send_message(admin_id, text)
            except Exception:
                logger.exception("Не удалось уведомить администратора %s", admin_id)
