"""Т-Банк, интернет-эквайринг: создание платежа (метод Init) и проверка уведомлений.

Документация: https://developer.tbank.ru/eacq/api
Подпись (Token) = SHA-256 от склеенных значений корневых полей запроса + Password,
отсортированных по имени поля. Вложенные объекты (Receipt, DATA) в подписи не участвуют.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# Статус успешно списанного платежа (одностадийная оплата).
STATUS_CONFIRMED = "CONFIRMED"


class TBankError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class TBankPayment:
    payment_id: str
    url: str


def _value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def make_token(params: dict[str, object], password: str) -> str:
    data = {k: v for k, v in params.items() if k != "Token" and not isinstance(v, (dict, list))}
    data["Password"] = password
    raw = "".join(_value(data[k]) for k in sorted(data))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_notification(data: dict[str, object], terminal_key: str, password: str) -> bool:
    token = data.get("Token")
    if not isinstance(token, str) or data.get("TerminalKey") != terminal_key:
        return False
    return hmac.compare_digest(make_token(data, password), token.lower())


class TBankClient:
    def __init__(self, session: aiohttp.ClientSession, terminal_key: str, password: str, api_url: str,
                 receipt: bool, taxation: str, vat: str) -> None:
        self._session = session
        self._terminal_key = terminal_key
        self._password = password
        self._api_url = api_url
        self._receipt = receipt
        self._taxation = taxation
        self._vat = vat

    async def init(self, *, order_id: str, amount_rub: int, description: str, email: str | None,
                   success_url: str, fail_url: str, notification_url: str) -> TBankPayment:
        kopecks = amount_rub * 100
        params: dict[str, object] = {
            "TerminalKey": self._terminal_key,
            "Amount": kopecks,
            "OrderId": order_id,
            "Description": description[:140],
            "NotificationURL": notification_url,
            "SuccessURL": success_url,
            "FailURL": fail_url,
        }
        if self._receipt and email:
            # Чек по 54-ФЗ: Т-Банк отправит его покупателю на почту.
            params["Receipt"] = {
                "Email": email,
                "Taxation": self._taxation,
                "Items": [{
                    "Name": description[:128],
                    "Price": kopecks,
                    "Quantity": 1,
                    "Amount": kopecks,
                    "Tax": self._vat,
                    "PaymentMethod": "full_payment",
                    "PaymentObject": "service",
                }],
            }
        params["Token"] = make_token(params, self._password)

        async with self._session.post(f"{self._api_url}/Init", json=params,
                                      timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json(content_type=None)

        if not data.get("Success") or not data.get("PaymentURL"):
            raise TBankError(f"Init {order_id}: {data.get('ErrorCode')} {data.get('Message')} {data.get('Details')}")
        return TBankPayment(payment_id=str(data.get("PaymentId", "")), url=data["PaymentURL"])
