from types import SimpleNamespace

import pytest

from app.services.news import article_fetcher


def _fake_response(html: bytes, status: int = 200):
    def raise_for_status():
        if status >= 400:
            raise article_fetcher.requests.HTTPError(f"HTTP {status}")

    return SimpleNamespace(content=html, raise_for_status=raise_for_status)


def test_fetch_article_text_returns_empty_for_google_news_host():
    # news.google.com bir SPA kabuğu döner, gerçek içerik değil — hiç istek
    # atılmamalı (bkz. article_fetcher.py docstring'i).
    assert article_fetcher.fetch_article_text("https://news.google.com/rss/articles/abc") == ""


def test_fetch_article_text_extracts_real_paragraphs(monkeypatch):
    html = b"""
    <html><body>
    <nav>Menu ignored</nav>
    <p>Kisa.</p>
    <p>THYAO hisseleri bugun borsada guclu bir yukselis kaydetti ve analistler hedef fiyatlarini yukseltti.</p>
    <p>Sirket yetkilileri onumuzdeki ceyrekte de guclu buyume beklentisi icinde olduklarini belirtti.</p>
    <footer>Copyright ignored</footer>
    </body></html>
    """
    monkeypatch.setattr(article_fetcher.requests, "get", lambda *a, **k: _fake_response(html))

    text = article_fetcher.fetch_article_text("https://example.com/article")

    assert "guclu bir yukselis" in text
    assert "Menu ignored" not in text
    assert "Copyright ignored" not in text
    assert "Kisa." not in text  # 40 karakterden kisa paragraflar atlanir


def test_fetch_article_text_truncates_to_max_chars(monkeypatch):
    long_paragraph = "A" * 50 + " " + "b" * 5000
    html = f"<html><body><p>{long_paragraph}</p></body></html>".encode()
    monkeypatch.setattr(article_fetcher.requests, "get", lambda *a, **k: _fake_response(html))

    text = article_fetcher.fetch_article_text("https://example.com/article", max_chars=100)

    assert len(text) == 100


def test_fetch_article_text_returns_empty_on_request_exception(monkeypatch):
    def _raise(*args, **kwargs):
        raise article_fetcher.requests.RequestException("network down")

    monkeypatch.setattr(article_fetcher.requests, "get", _raise)

    assert article_fetcher.fetch_article_text("https://example.com/article") == ""


def test_fetch_article_text_returns_empty_on_http_error(monkeypatch):
    monkeypatch.setattr(article_fetcher.requests, "get", lambda *a, **k: _fake_response(b"", status=404))

    assert article_fetcher.fetch_article_text("https://example.com/missing") == ""


def test_fetch_article_text_returns_empty_for_empty_url():
    assert article_fetcher.fetch_article_text("") == ""


@pytest.mark.parametrize("url", [None])
def test_fetch_article_text_returns_empty_for_none_url(url):
    assert article_fetcher.fetch_article_text(url) == ""
