"""MARKET-RISK-1 evren karşılaştırması: evren bütünlüğü, başarısız semboller, devam (ağ yok)."""

import json

import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow import universe_review as ur
from app.services.market_data.trading_calendar import expected_trading_sessions

from datetime import date

SESSIONS = expected_trading_sessions(date(2023, 1, 2), date(2026, 9, 24))


def _csv(path, n=len(SESSIONS)):
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(ISTANBUL_TZ) for d in SESSIONS[-n:]])
    pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 100}, index=idx).to_csv(path)


def _setup(tmp_path, symbols):
    out = tmp_path / "u"
    out.mkdir()
    (out / "universe_manifest.json").write_text(json.dumps({"symbols": symbols}), encoding="utf-8")
    reuse = tmp_path / "reuse"
    reuse.mkdir()
    (reuse / "fetch_manifest.json").write_text(json.dumps({"run_at": "2026-09-25T11:25:28+03:00", "fetch_start": "2022-06-01"}), encoding="utf-8")
    _csv(reuse / "XU100_provider_ohlcv.csv")
    _csv(reuse / "AAA_provider_ohlcv.csv")
    return out, reuse


def _fake_download(symbol, target, inputs):
    if symbol == "BAD":
        return {"status": "FAILED", "reason": "EMPTY_HISTORY"}
    _csv(target)
    return {"status": "DOWNLOADED", "fetched_at": "2026-09-25T12:00:00+03:00"}


def _stub_review(calls):
    def review(df, index_df, symbol, days, params, technical_fn=None, calendar_sessions=None):
        calls.append(symbol)
        return [{"session": d.isoformat(), "technical_status": "OK", "technical_reason": "", "raw_class_technical_only": "BUY",
                 "shadow_gate": "ALLOWED", "market_risk": "NO_DEFINED_RULE_TRIGGERED", "asset_risk": "NO_DEFINED_RULE_TRIGGERED",
                 "market_rules": {k: {"status": "EVALUATED"} for k in ("INDEX_DRAWDOWN_FROM_HIGH", "INDEX_VOLATILITY_ELEVATED", "INDEX_BELOW_TREND")},
                 "asset_rules": {k: {"status": "EVALUATED"} for k in ("ASSET_PERIOD_DECLINE", "ASSET_UNDERPERFORMS_INDEX", "SHARP_DAILY_DECLINE_OBSERVED")},
                 "price_move_after_close": {"T+5": 1.0, "T+10": "PENDING", "T+20": "PENDING"}} for d in days[:3]]
    return review


def test_every_manifest_symbol_is_reported_and_failed_symbols_are_kept(tmp_path):
    out, reuse = _setup(tmp_path, ["AAA", "BAD", "CCC"])
    entries = ur.fetch_inputs(out, reuse, downloader=_fake_download)
    assert entries["AAA"]["status"] == "REUSED" and entries["CCC"]["status"] == "DOWNLOADED"
    assert entries["BAD"] == {**entries["BAD"], "status": "FAILED", "reason": "EMPTY_HISTORY"}
    calls = []
    ur.compute_all(out, review_fn=_stub_review(calls), identity={"id": 1}, log=lambda *_: None)
    assert calls == ["AAA", "CCC"]
    summary = ur.summarize(out)
    assert {k.split()[0] for k in summary["per_symbol_year"]} == {"AAA", "BAD", "CCC"}
    assert summary["per_symbol_year"]["BAD 2024"]["compute_status"] == "NOT_COMPUTED"
    assert summary["per_symbol_year"]["BAD 2024"]["not_computed_reason"] == "EMPTY_HISTORY"
    assert summary["counts"] == {"universe": 3, "downloaded_or_reused": 2, "computed": 2, "produced_valid_decision": 2}


def test_resume_skips_completed_symbols_without_duplicating_and_recomputes_on_identity_change(tmp_path):
    out, reuse = _setup(tmp_path, ["AAA", "CCC"])
    ur.fetch_inputs(out, reuse, downloader=_fake_download)
    first = []
    ur.compute_all(out, review_fn=_stub_review(first), identity={"id": 1}, log=lambda *_: None)
    again = []
    ur.compute_all(out, review_fn=_stub_review(again), identity={"id": 1}, log=lambda *_: None)
    assert first == ["AAA", "CCC"] and again == []
    rows = json.loads((out / "results" / "AAA.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == len({r["session"] for r in rows}) == 3
    changed = []
    ur.compute_all(out, review_fn=_stub_review(changed), identity={"id": 2}, log=lambda *_: None)
    assert changed == ["AAA", "CCC"]


def test_interrupted_fetch_resumes_without_redownloading(tmp_path):
    out, reuse = _setup(tmp_path, ["CCC", "DDD"])
    seen = []

    def flaky(symbol, target, inputs):
        seen.append(symbol)
        return _fake_download(symbol, target, inputs)

    ur.fetch_inputs(out, reuse, downloader=flaky)
    ur.fetch_inputs(out, reuse, downloader=flaky)
    assert seen == ["CCC", "DDD"]
