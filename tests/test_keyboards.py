from dataclasses import replace

from bot import keyboards, texts
from bot.constants import Cb
from bot.services import screens
from tests.test_web import make_settings


def _buttons(markup):
    return [(b.text, b.url) for row in markup.inline_keyboard for b in row]


def test_materials_offers_all_groups(tmp_path):
    settings = make_settings(tmp_path, access_tg_url="https://t.me/g", access_vk_url="https://vk.com/g",
                             access_max_url="https://max.ru/g")
    assert _buttons(keyboards.materials(settings)) == [
        (texts.BTN_OPEN_TG, "https://t.me/g"),
        (texts.BTN_OPEN_VK, "https://vk.com/g"),
        (texts.BTN_OPEN_MAX, "https://max.ru/g"),
    ]


def test_buy_button_opens_site_pricing_with_telegram_id(tmp_path):
    settings = make_settings(tmp_path, site_url="https://site.example/")
    url = screens.buy_url(settings, 42)
    assert url == "https://site.example/?tg=42&utm_source=telegram_bot#pricing"
    buy = keyboards.product(url).inline_keyboard[0][0]
    assert buy.text == texts.BTN_BUY and buy.url == url and buy.callback_data is None
    assert keyboards.followup(3, url).inline_keyboard[0][0].url == url
    assert keyboards.contents(url).inline_keyboard[0][0].url == url


def test_buy_button_falls_back_to_in_bot_payment(tmp_path):
    settings = make_settings(tmp_path, site_url="")
    assert screens.buy_url(settings, 42) is None
    assert keyboards.product(None).inline_keyboard[0][0].callback_data == Cb.BUY


def test_materials_falls_back_to_materials_url(tmp_path):
    settings = make_settings(tmp_path, access_tg_url="", materials_url="https://m")
    assert _buttons(keyboards.materials(settings)) == [(texts.BTN_OPEN_MATERIALS, "https://m")]
    assert keyboards.materials(replace(settings, materials_url="")) is None
