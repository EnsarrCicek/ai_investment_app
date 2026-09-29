import copy
import csv
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.research.official_bist import build_bsoke_fener as bb
from app.research.official_bist.rights_adjustment import (
    AdjustmentError, RightsEvent, adjust_rows, ohlc_consistent, theoretical_price)

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "app/research/official_bist/runs/bsoke_fener_20260929_v2"
local_only = pytest.mark.skipif(not (RAW / "BSOKE_official_daily.csv").exists(), reason="yerel resmî veri yok")
EV = RightsEvent("X", date(2024, 12, 10), Decimal(3), Decimal("1.00"), "test")


def row(d, o, h, l, c, q="100"):
    return {"trade_date": d, "open": o, "high": h, "low": l, "close": c, "total_traded_quantity_raw": q}


def sample():
    return [row("2024-12-06", "60", "62", "59", "61"), row("2024-12-09", "59.75", "62", "59.5", "61.65"),
            row("2024-12-10", "17.77", "17.77", "15", "15.22", "30517103")]


def test_theoretical_price_matches_official_circular_example_and_events():
    assert theoretical_price(Decimal("6.00"), Decimal(1), Decimal(1)) == (Decimal("3.5"), True)  # genelge örneği
    ft, _ = theoretical_price(Decimal("61.65"), Decimal(3), Decimal(1))
    assert ft == Decimal("16.1625")
    ft, _ = theoretical_price(Decimal("48.52"), Decimal(4), Decimal(1))
    assert ft == Decimal("10.504")


def test_price_below_subscription_price_excludes_rights():
    assert theoretical_price(Decimal("0.80"), Decimal(3), Decimal(1)) == (Decimal("0.80"), False)


def test_factor_boundary_only_before_rights_start_and_volume_untouched():
    res = adjust_rows(sample(), EV)
    by = {r["trade_date"]: r for r in res["rows"]}
    dk = Decimal(res["dk"])
    assert by["2024-12-09"]["segment"] == "PRE_RIGHTS_ADJUSTED" and Decimal(by["2024-12-09"]["factor_applied"]) == dk
    assert Decimal(by["2024-12-09"]["derived_close"]) == Decimal("16.1625")
    assert by["2024-12-10"]["factor_applied"] == "1" and by["2024-12-10"]["derived_open"] == "17.77"
    assert by["2024-12-10"]["total_traded_quantity_raw"] == "30517103"
    assert res["fk_session"] == "2024-12-09"


def test_double_adjustment_blocked():
    res = adjust_rows(sample(), EV)
    with pytest.raises(AdjustmentError):
        adjust_rows(res["rows"], EV)


def test_missing_session_before_rights_start_blocks():
    rows = [r for r in sample() if r["trade_date"] != "2024-12-09"]
    with pytest.raises(AdjustmentError):
        adjust_rows(rows, EV)


def test_ohlc_consistency_preserved_and_input_not_mutated():
    rows = sample()
    before = copy.deepcopy(rows)
    res = adjust_rows(rows, EV)
    assert rows == before
    assert all(ohlc_consistent(r, "derived_") and ohlc_consistent(r, "raw_") for r in res["rows"])


@local_only
def test_raw_official_files_unchanged_after_build(tmp_path):
    from app.research.official_bist import build_rights_adjusted
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW.glob("*.csv")}
    assert build_rights_adjusted.main(tmp_path / "out") == 0
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW.glob("*.csv")}
    assert before == after
    derived = list(csv.DictReader((tmp_path / "out" / "BSOKE_research_rights_adjusted.csv").open(encoding="utf-8")))
    assert {r["series_kind"] for r in derived} == {"RESEARCH_RIGHTS_ADJUSTED_NOT_OFFICIAL"}


class _FakeResp:
    status = 200

    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_local_write_error_is_not_retried_as_network_error(tmp_path, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        return _FakeResp(b"PK\x03\x04fake")

    monkeypatch.setattr(bb.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    monkeypatch.setattr(bb, "PRIOR", tmp_path / "no_prior")
    not_a_dir = tmp_path / "bulletins"
    not_a_dir.write_text("dosya, klasör değil")  # yerel yazma hatası üretir
    with pytest.raises(OSError):
        bb.obtain(date(2024, 11, 1), not_a_dir, {})
    assert len(calls) == 1  # yerel hata yeniden istek üretmedi


def test_network_error_is_retried_limited(tmp_path, monkeypatch):
    calls = []

    def failing(req, timeout):
        calls.append(1)
        raise TimeoutError("ağ")

    monkeypatch.setattr(bb.urllib.request, "urlopen", failing)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    monkeypatch.setattr(bb, "PRIOR", tmp_path / "no_prior")
    (tmp_path / "b").mkdir()
    out = bb.obtain(date(2024, 11, 1), tmp_path / "b", {})
    assert out["origin"] == "ERISILEMEDI" and len(calls) == bb.MAX_ATTEMPTS


# --- Değerlendirme tarihine göre görünüm ---------------------------------------------------------

from app.research.official_bist.rights_adjustment import price_view_as_of  # noqa: E402

T_PRE, T_EV = date(2024, 12, 9), date(2024, 12, 10)


def test_as_of_changing_future_bar_does_not_affect_view():
    a = price_view_as_of(sample(), [EV], T_PRE)
    changed = sample()
    changed[-1]["close"] = "999"
    changed.append(row("2024-12-11", "1", "1", "1", "1"))
    b = price_view_as_of(changed, [EV], T_PRE)
    assert a == b and a["rows"][-1]["trade_date"] == "2024-12-09"


def test_as_of_future_rights_event_does_not_change_prices_and_is_not_listed():
    v = price_view_as_of(sample(), [EV], T_PRE)
    assert v["applied_events"] == []
    assert all(r["factor_applied"] == "1" and r["derived_close"] == r["raw_close"] for r in v["rows"])
    assert "2024-12-10" not in json_dump(v)


def test_as_of_after_effective_applies_factor_only_before_boundary():
    v = price_view_as_of(sample(), [EV], T_EV)
    by = {r["trade_date"]: r for r in v["rows"]}
    assert Decimal(by["2024-12-09"]["derived_close"]) == Decimal("16.1625")
    assert by["2024-12-10"]["factor_applied"] == "1" and by["2024-12-10"]["derived_close"] == "15.22"
    assert by["2024-12-10"]["total_traded_quantity_raw"] == "30517103"
    assert v["applied_events"][0]["fk_session"] == "2024-12-09"


def test_as_of_raw_inputs_preserved_and_derived_input_rejected():
    rows = sample()
    before = copy.deepcopy(rows)
    v = price_view_as_of(rows, [EV], T_EV)
    assert rows == before
    with pytest.raises(AdjustmentError):
        price_view_as_of([{**r, "series_kind": "x"} for r in v["rows"]], [EV], T_EV)


def json_dump(obj):
    import json
    return json.dumps(obj)
