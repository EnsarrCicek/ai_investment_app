import pandas as pd
import pytest

from app.services.market_data.bist_provider import _fetch_with_retry

_EMPTY = pd.DataFrame()
_DATA = pd.DataFrame({"Close": [1.0, 2.0]})


def test_returns_immediately_on_first_success(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)
    calls = []

    def fetch():
        calls.append(1)
        return _DATA

    result = _fetch_with_retry(fetch, attempts=3, delay_seconds=0)

    assert result is _DATA
    assert len(calls) == 1


def test_retries_on_empty_result_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)
    results = iter([_EMPTY, _EMPTY, _DATA])

    result = _fetch_with_retry(lambda: next(results), attempts=3, delay_seconds=0)

    assert result is _DATA


def test_retries_on_exception_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)
    attempts_made = []

    def fetch():
        attempts_made.append(1)
        if len(attempts_made) < 2:
            raise ConnectionError("geçici ağ hatası")
        return _DATA

    result = _fetch_with_retry(fetch, attempts=3, delay_seconds=0)

    assert result is _DATA
    assert len(attempts_made) == 2


def test_raises_last_exception_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)

    def fetch():
        raise ConnectionError("hâlâ başarısız")

    with pytest.raises(ConnectionError, match="hâlâ başarısız"):
        _fetch_with_retry(fetch, attempts=3, delay_seconds=0)


def test_returns_last_empty_result_after_exhausting_attempts_without_exception(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)

    result = _fetch_with_retry(lambda: _EMPTY, attempts=3, delay_seconds=0)

    assert result.empty


def test_respects_attempts_count(monkeypatch):
    monkeypatch.setattr("app.services.market_data.bist_provider.time.sleep", lambda _: None)
    calls = []

    def fetch():
        calls.append(1)
        return _EMPTY

    _fetch_with_retry(fetch, attempts=4, delay_seconds=0)

    assert len(calls) == 4
