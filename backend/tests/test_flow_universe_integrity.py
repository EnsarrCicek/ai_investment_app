"""FLOW 1C-R1 — genel `freeze_symbols()` çağıranın verdiği sembolleri AYNEN
kullanmalı; Technical V1 dondurulmuş 100'ü (FLOW 1B evreni) asla enjekte
etmemeli. Yahoo yok: sahte provider."""

from datetime import datetime, timezone

import pandas as pd

from app.research.flow_v1 import dataset as ds
from app.research.flow_v1.dataset import BENCHMARK_SYMBOL, freeze_symbols, load_frozen_universe


class _FakeProvider:
    def __init__(self):
        self.requested: list[str] = []

    def get_history(self, symbol, start=None, end=None, interval="1d", period=None):
        self.requested.append(symbol)
        idx = pd.DatetimeIndex(["2024-01-02"]).tz_localize("Europe/Istanbul")
        return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1.0]}, index=idx)


def _freeze(tmp_path, symbols):
    provider = _FakeProvider()
    manifest = freeze_symbols(
        symbols,
        data_file=tmp_path / "frozen_ohlcv.json.gz",
        manifest_file=tmp_path / "dataset_manifest.json",
        dataset_id="TEST",
        extra_manifest={},
        provider=provider,
        now=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    return provider, manifest


def test_freeze_symbols_requests_exactly_caller_symbols_plus_explicit_benchmark(tmp_path):
    caller = ["AAA.IS", "BBB.IS", "CCC.IS"]
    provider, manifest = _freeze(tmp_path, caller)
    # Genel sözleşme: çağıranın sembolleri, SIRASIYLA, ardından yalnızca açık benchmark (XU100).
    assert provider.requested == [*caller, BENCHMARK_SYMBOL]
    assert set(manifest["symbols"]) == {*caller, BENCHMARK_SYMBOL}
    frozen_100, _ = load_frozen_universe()
    assert not set(provider.requested) & set(frozen_100)
    assert not set(manifest["symbols"]) & set(frozen_100)


def test_freeze_symbols_does_not_consult_flow_1b_universe(tmp_path, monkeypatch):
    def _forbidden():
        raise AssertionError("genel freeze_symbols load_frozen_universe() çağırmamalı")

    monkeypatch.setattr(ds, "load_frozen_universe", _forbidden)
    provider, _ = _freeze(tmp_path, ["AAA.IS"])
    assert provider.requested == ["AAA.IS", BENCHMARK_SYMBOL]


def test_flow_1b_wrapper_still_uses_frozen_100(tmp_path, monkeypatch):
    captured = {}

    def _capture(symbols, **kwargs):
        captured["symbols"] = list(symbols)
        return {}

    monkeypatch.setattr(ds, "freeze_symbols", _capture)
    ds.freeze_dataset(provider=_FakeProvider())
    frozen_100, _ = load_frozen_universe()
    assert captured["symbols"] == frozen_100
