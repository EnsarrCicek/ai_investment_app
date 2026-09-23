from datetime import datetime, timezone

import pytest

from app.models.market_data import MarketData, Quote
from app.services.market_data.base import MarketDataProvider


class FakeMarketDataProvider(MarketDataProvider):
    """Testler için Firestore/Yahoo Finance'e hiç gitmeyen sahte provider."""

    def __init__(self, close_price: float = 100.0, history_df=None):
        self._close_price = close_price
        self._history_df = history_df

    def get_latest(self, symbol: str) -> MarketData:
        return MarketData(
            asset_id=symbol,
            timestamp=datetime.now(timezone.utc),
            open=self._close_price,
            high=self._close_price,
            low=self._close_price,
            close=self._close_price,
            volume=0,
            source="fake",
        )

    def get_quote(self, symbol: str) -> Quote:
        return Quote(
            asset_id=symbol,
            timestamp=datetime.now(timezone.utc),
            last_price=self._close_price,
            previous_close=self._close_price,
            change=0.0,
            change_percent=0.0,
            open=self._close_price,
            high=self._close_price,
            low=self._close_price,
            volume=0,
            source="fake",
        )

    def get_history(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ):
        if self._history_df is None:
            raise NotImplementedError
        return self._history_df


@pytest.fixture
def fake_provider():
    return FakeMarketDataProvider


@pytest.fixture
def v1_era_engine_version(monkeypatch):
    """TECH-VOL 1B: Technical V1 pipeline MEKANİĞİNİ (kimlik kapıları, claim/
    evidence/finalization, activation-lock sözleşmesi) V1'in dondurduğu
    metodolojiyle eşleşen bir çalışan motor altında test etmek için
    `ENGINE_VERSION`'ı V1 freeze manifest'indeki değere sabitler. Üretimde
    çalışan motor 1.15.0'dır ve V1 SUPERSEDED guard'ı gerçek davranışta
    V1 aktivasyonunu/attempt'lerini REDDEDER (bkz. test_technical_v1_superseded_guard.py)."""
    import json
    from pathlib import Path

    import app.engines.technical.engine as engine_module

    manifest = json.loads(
        (Path(engine_module.__file__).resolve().parents[2] / "research" / "resources" / "technical_v1_freeze_manifest.json")
        .read_text(encoding="utf-8")
    )
    monkeypatch.setattr(engine_module, "ENGINE_VERSION", manifest["methodology_identity"]["engine_version"])
