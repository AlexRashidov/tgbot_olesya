import hashlib
import hmac
from urllib.parse import parse_qsl, urlsplit

from bot.services import prodamus, tbank


# ---------- Т-Банк ----------

def test_tbank_token_matches_documented_algorithm():
    params = {
        "TerminalKey": "TinkoffBankTest",
        "Amount": 250000,
        "OrderId": "abc",
        "Description": "Таблетка",
        "Receipt": {"Email": "a@b.ru"},  # вложенные объекты в подписи не участвуют
    }
    expected_raw = "250000" + "Таблетка" + "abc" + "secret" + "TinkoffBankTest"
    expected = hashlib.sha256(expected_raw.encode()).hexdigest()
    assert tbank.make_token(params, "secret") == expected


def test_tbank_notification_verification():
    data = {
        "TerminalKey": "TK",
        "OrderId": "o1",
        "Success": True,
        "Status": "CONFIRMED",
        "PaymentId": 13660,
        "ErrorCode": "0",
        "Amount": 250000,
        "Data": {"x": "y"},
    }
    data["Token"] = tbank.make_token(data, "pw")
    assert tbank.verify_notification(data, "TK", "pw")
    assert not tbank.verify_notification(data, "TK", "wrong")
    assert not tbank.verify_notification(data, "OTHER", "pw")
    tampered = {**data, "Amount": 100}
    assert not tbank.verify_notification(tampered, "TK", "pw")


def test_tbank_booleans_are_lowercase_in_token():
    a = tbank.make_token({"Success": True}, "p")
    b = tbank.make_token({"Success": "true"}, "p")
    assert a == b


# ---------- Prodamus ----------

def test_prodamus_parse_form_builds_nested_lists():
    data = prodamus.parse_form([
        ("order_id", "1"),
        ("products[0][name]", "Таблетка"),
        ("products[0][price]", "2500.00"),
        ("products[1][name]", "Другое"),
    ])
    assert data == {
        "order_id": "1",
        "products": [{"name": "Таблетка", "price": "2500.00"}, {"name": "Другое"}],
    }


def test_prodamus_sign_matches_php_json_encode():
    data = {"b": "x/y", "a": "Привет", "products": [{"price": 2500, "name": "Т"}]}
    # Как PHP: ключи по алфавиту, числа строками, без пробелов, кириллица как есть, «/» → «\/».
    payload = '{"a":"Привет","b":"x\\/y","products":[{"name":"Т","price":"2500"}]}'
    expected = hmac.new(b"key", payload.encode(), hashlib.sha256).hexdigest()
    assert prodamus.sign(data, "key") == expected
    assert prodamus.verify(data, "key", expected.upper())
    assert not prodamus.verify(data, "key", "")
    assert not prodamus.verify({**data, "a": "x"}, "key", expected)


def test_prodamus_webhook_roundtrip():
    form = [("order_num", "abc"), ("sum", "2500.00"), ("payment_status", "success"),
            ("products[0][name]", "Таблетка"), ("products[0][price]", "2500.00")]
    data = prodamus.parse_form(form)
    signature = prodamus.sign(data, "secret")
    assert prodamus.verify(prodamus.parse_form(form), "secret", signature)
    assert prodamus.order_number(data) == "abc"


def test_prodamus_link_contains_order_and_signature():
    url = prodamus.build_link(
        form_url="https://shop.payform.ru", secret="s", order_id="o1", amount_rub=2500,
        product_name="Таблетка", email="a@b.ru", phone=None,
        url_success="https://site/?order=o1", url_return="https://site/", url_notification="https://bot/webhooks/prodamus",
    )
    parts = urlsplit(url)
    assert parts.netloc == "shop.payform.ru"
    query = dict(parse_qsl(parts.query))
    assert query["order_id"] == "o1"
    assert query["products[0][price]"] == "2500"
    assert query["customer_email"] == "a@b.ru"
    signature = query.pop("signature")
    assert prodamus.verify(prodamus.parse_form(query.items()), "s", signature)
