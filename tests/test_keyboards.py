from dataclasses import replace

from bot import keyboards, texts
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


def test_materials_falls_back_to_materials_url(tmp_path):
    settings = make_settings(tmp_path, access_tg_url="", materials_url="https://m")
    assert _buttons(keyboards.materials(settings)) == [(texts.BTN_OPEN_MATERIALS, "https://m")]
    assert keyboards.materials(replace(settings, materials_url="")) is None
