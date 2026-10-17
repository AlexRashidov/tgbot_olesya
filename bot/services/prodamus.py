"""Prodamus: ссылка на платёжную форму и проверка уведомлений об оплате.

Документация: https://help.prodamus.ru/payform/integracii/rest-api
Подпись — HMAC-SHA256 от JSON с данными: все значения приводятся к строкам,
ключи сортируются рекурсивно, JSON без пробелов, кириллица не экранируется,
а «/» экранируется как «\\/» (так делает json_encode в PHP-библиотеке Prodamus).
"""

import hashlib
import hmac
import json
import re
from collections.abc import Iterable
from urllib.parse import urlencode

# Статус успешной оплаты в уведомлении.
STATUS_SUCCESS = "success"

_KEY_RE = re.compile(r"^([^\[\]]+)((?:\[[^\[\]]*\])*)$")


def _stringify(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _stringify(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return "" if value is None else str(value)


def sign(data: dict[str, object], secret: str) -> str:
    payload = json.dumps(_stringify(data), ensure_ascii=False, separators=(",", ":")).replace("/", "\\/")
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(data: dict[str, object], secret: str, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(data, secret), signature.strip().lower())


def _listify(node: object) -> object:
    """Словари с ключами 0, 1, 2… превращаем в списки — как PHP-массивы в JSON."""
    if not isinstance(node, dict):
        return node
    node = {k: _listify(v) for k, v in node.items()}
    if node and all(k.isdigit() for k in node) and sorted(int(k) for k in node) == list(range(len(node))):
        return [node[str(i)] for i in range(len(node))]
    return node


def parse_form(pairs: Iterable[tuple[str, str]]) -> dict[str, object]:
    """Разбирает поля формы вида products[0][name]=… во вложенную структуру, как это делает PHP."""
    result: dict[str, object] = {}
    for raw_key, value in pairs:
        match = _KEY_RE.match(raw_key)
        if not match:
            result[raw_key] = value
            continue
        path = [match.group(1)] + re.findall(r"\[([^\[\]]*)\]", match.group(2))
        node = result
        for i, part in enumerate(path):
            last = i == len(path) - 1
            if part == "":  # field[] — следующий индекс
                part = str(len(node))
            if last:
                node[part] = value
            else:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
    return _listify(result)  # type: ignore[return-value]


def _flatten(data: dict[str, object], prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            items.extend(_flatten(value, name))
        elif isinstance(value, list):
            items.extend(_flatten({str(i): v for i, v in enumerate(value)}, name))
        else:
            items.append((name, str(value)))
    return items


def build_link(*, form_url: str, secret: str, order_id: str, amount_rub: int, product_name: str,
               email: str | None, phone: str | None, url_success: str, url_return: str,
               url_notification: str, payment_methods: str = "") -> str:
    data: dict[str, object] = {
        "do": "pay",
        "order_id": order_id,
        "products": [{"name": product_name, "price": str(amount_rub), "quantity": "1"}],
        "urlReturn": url_return,
        "urlSuccess": url_success,
        "urlNotification": url_notification,
    }
    if email:
        data["customer_email"] = email
    if phone:
        data["customer_phone"] = phone
    if payment_methods:
        data["available_payment_methods"] = payment_methods
    data["signature"] = sign(data, secret)
    return f"{form_url}/?{urlencode(_flatten(data))}"


def order_number(data: dict[str, object]) -> str:
    """Наш номер заказа. В уведомлении он приходит в order_num (order_id — внутренний номер Prodamus)."""
    return str(data.get("order_num") or data.get("order_id") or "")
