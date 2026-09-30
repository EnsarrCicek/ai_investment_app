from datetime import date
from decimal import Decimal

from app.research.official_bist.raw_package import evaluable_sessions, readiness, row_status, symbol_rows
from app.research.official_bist.rights_adjustment import RightsEvent
from app.services.market_data.trading_calendar import expected_trading_sessions

DAYS = [d.isoformat() for d in expected_trading_sessions(date(2024, 5, 7), date(2024, 12, 20))]
TR = "TARIH;ISLEM  KODU;BULTEN ADI;ONCEKI KAPANIS FIYATI;ACILIS FIYATI;EN DUSUK FIYAT;EN YUKSEK FIYAT;KAPANIS FIYATI;TOPLAM ISLEM HACMI;TOPLAM ISLEM ADEDI"
EN = ("TRADE DATE;INSTRUMENT SERIES CODE;INSTRUMENT NAME;PREVIOUS LAST PRICE;OPENING PRICE;LOWEST PRICE;HIGHEST PRICE;"
      "CLOSING PRICE;TOTAL TRADED VALUE;TOTAL TRADED VOLUME")


def ok_rows(days=DAYS, flags=()):
    return [{"trade_date": d, "status": "OK", "corporate_action_flag": "01" if d in flags else ""} for d in days]


def test_row_status_zero_missing_invalid():
    assert row_status(None) == "MISSING"
    assert row_status({"open": "0", "high": "0", "low": "0", "close": "0"}) == "ZERO_PRICE"
    assert row_status({"open": "10", "high": "9", "low": "8", "close": "8.5"}) == "INVALID"
    assert row_status({"open": "10", "high": "11", "low": "9", "close": "10"}) == "OK"


def test_missing_day_not_filled_and_source_kept():
    d1, d2 = "2024-06-03", "2024-06-04"
    indexed = {d1: ([TR, EN], {"ABC.E": [f"{d1};ABC.E;X;9;10;9;11;10;1000;100"]}), d2: ([TR, EN], {})}
    bulletins = {d: {"path": f"x/thb{d.replace('-', '')}1.zip", "sha256": d} for d in (d1, d2)}
    rows = symbol_rows("ABC.E", [d1, d2], indexed, bulletins)
    assert rows[0]["status"] == "OK" and rows[0]["close"] == "10" and rows[0]["price_basis"] == "OFFICIAL_RAW_SESSION_PRICE"
    assert rows[1]["status"] == "MISSING" and rows[1]["close"] == "" and rows[1]["source_sha256"] == d2


def test_evaluable_requires_continuous_window():
    full = evaluable_sessions(ok_rows())
    assert full and full[0] == "2024-11-22"
    gap = ok_rows()
    gap[100]["status"] = "MISSING"  # pencere içinde bir boşluk
    assert len(evaluable_sessions(gap)) < len(full)


def test_no_flags_is_not_proof_and_unverified_identity_not_ready():
    r = readiness("ABC", ok_rows(), None, set(), [])
    assert r["flag_explanation"] == "NONE_OBSERVED_NOT_PROOF"
    assert r["status"] == "NOT_READY" and {"IDENTITY_NOT_VERIFIED", "CORPORATE_ACTION_SCAN_NOT_DONE"} <= set(r["blockers"])


def test_unexplained_flag_blocks_and_explained_with_identity_is_limited_ready():
    r = readiness("ABC", ok_rows(flags=("2024-12-10",)), {"result": "MATCH"}, set(), [])
    assert "UNEXPLAINED_CORPORATE_ACTION_FLAGS" in r["blockers"] and r["status"] == "NOT_READY"
    ev = [RightsEvent("ABC", date(2024, 12, 10), Decimal(3), Decimal(1), "x")]
    r2 = readiness("ABC", ok_rows(flags=("2024-12-10",)), {"result": "MATCH"}, {("ABC", "2024-12-10")}, ev)
    assert r2["status"] == "READY_FOR_RESEARCH_WITH_LIMITS" and r2["blockers"] == []
