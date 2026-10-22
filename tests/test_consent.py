import asyncio

from bot import texts
from bot.db import Database, UserRepository
from bot.services import screens
from tests.test_web import make_settings


def test_document_urls_point_to_site_pages(tmp_path):
    settings = make_settings(tmp_path, site_url="https://site.example/")
    assert screens.document_urls(settings) == {
        "offer": "https://site.example/offer",
        "privacy": "https://site.example/privacy",
        "consent": "https://site.example/consent",
        "marketing": "https://site.example/marketing-consent",
    }


def test_document_urls_fall_back_to_disk(tmp_path):
    settings = make_settings(tmp_path, site_url="")
    assert screens.document_urls(settings)["offer"].startswith("https://disk.yandex.ru/")


def test_consent_text_has_all_documents(tmp_path):
    urls = screens.document_urls(make_settings(tmp_path, site_url="https://site.example/"))
    text = texts.CONSENT.format(**urls)
    for url in urls.values():
        assert f'href="{url}"' in text


def test_accept_terms_is_saved_once(tmp_path):
    async def scenario():
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            users = UserRepository(db)
            await users.upsert(1, None, "Анна")
            assert not (await users.get(1)).accepted_terms
            await users.accept_terms(1)
            first = (await users.get(1)).consent_at
            assert first is not None
            await users.accept_terms(1)
            assert (await users.get(1)).consent_at == first
            assert "terms_accepted" in await users.get_tags(1)
        finally:
            await db.close()

    asyncio.run(scenario())
