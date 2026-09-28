"""MARKET-RISK-1 olay incelemesi çalıştırıcısı — zaman disiplini testleri (ağ yok)."""

from datetime import date, datetime

import pandas as pd

from app.engines.decision.engine import DEFAULT_THRESHOLDS, _classify
from app.engines.risk.shadow_inputs import EXPERIMENTAL_PARAMS_V0 as P
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow.event_review import forward_returns, prepare_run_input, review
from app.services.market_data.trading_calendar import expected_trading_sessions

SESSIONS = expected_trading_sessions(date(2025, 1, 1), date(2026, 9, 25))


def _ohlcv(values, sessions):
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(ISTANBUL_TZ) for d in sessions])
    return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values, "Volume": [1000] * len(values)}, index=idx)


def test_incomplete_session_is_excluded_at_run_input():
    df = _ohlcv([100.0, 101.0, 102.0], SESSIONS[-3:])  # son satır 25.09.2026
    before_close = datetime(2026, 9, 25, 11, 16, tzinfo=ISTANBUL_TZ)
    after_final = datetime(2026, 9, 25, 18, 31, tzinfo=ISTANBUL_TZ)
    assert prepare_run_input(df, before_close).index[-1].date() == date(2026, 9, 24)
    assert prepare_run_input(df, after_final).index[-1].date() == date(2026, 9, 25)


def test_each_t_sees_only_data_up_to_t_and_raw_class_is_kept():
    sessions = SESSIONS[:-1]
    asset = _ohlcv([100.0 + i * 0.1 for i in range(len(sessions))], sessions)
    index = _ohlcv([1000.0 + i for i in range(len(sessions))], sessions)
    review_days = sessions[-5:]
    seen = []

    def spy(asset_df, index_close, t, symbol):
        seen.append((t, asset_df.index[-1].date(), max(index_close.index)))
        return {"status": "OK", "technical_score": 50.0 if t != review_days[2] else -50.0}

    rows = review(asset, index, "X", review_days, P, technical_fn=spy, calendar_sessions=sessions)
    assert all(last_asset <= t and last_index <= t for t, last_asset, last_index in seen)
    assert [r["raw_class_technical_only"] for r in rows] == [_classify(s, DEFAULT_THRESHOLDS) for s in (50, 50, -50, 50, 50)]

    # T sonrası verinin değiştirilmesi T satırını değiştirmez.
    mutated_asset, mutated_index = asset.copy(), index.copy()
    mutated_asset.iloc[-2:, :] = 1.0
    mutated_index.iloc[-2:, :] = 1.0
    again = review(mutated_asset, mutated_index, "X", review_days[:3], P, technical_fn=spy, calendar_sessions=sessions)
    strip = lambda r: {k: v for k, v in r.items() if k != "price_move_after_close"}
    assert [strip(r) for r in again] == [strip(r) for r in rows[:3]]


def test_forward_horizons_are_pending_or_missing_not_filled():
    sessions = SESSIONS[-13:-1]  # 12 seans, son tamamlanmış 24.09.2026
    closes = pd.Series([100.0 + i for i in range(len(sessions))], index=sessions).drop(sessions[6])
    moves = forward_returns(closes, sessions[1], sessions)
    assert moves["T+5"] == "MISSING"  # ufuk seansı tamamlandı ama bar yok; doldurulmaz
    assert moves["T+10"] == round((111.0 / 101.0 - 1) * 100, 4)
    assert moves["T+20"] == "PENDING"  # henüz tamamlanmadı
    assert forward_returns(closes, sessions[6], sessions)["T+5"] == "MISSING_T"


def test_saved_provider_csv_roundtrip_keeps_sessions_and_values(tmp_path):
    from app.research.market_risk_shadow.event_review import load_saved_provider_csv

    df = _ohlcv([100.0, 101.5, 99.25], SESSIONS[-4:-1])
    df.to_csv(tmp_path / "X.csv")
    loaded = load_saved_provider_csv(tmp_path / "X.csv")
    assert [ts.date() for ts in loaded.index] == SESSIONS[-4:-1]
    assert list(loaded["Close"]) == [100.0, 101.5, 99.25]
    assert str(loaded.index.tz) == str(ISTANBUL_TZ)


def test_replay_mode_rejects_unexpected_args_without_downloading(monkeypatch):
    import sys

    import pytest

    import app.services.market_data.bist_provider as bp
    from app.research.market_risk_shadow import event_review

    monkeypatch.setattr(bp, "BistProvider", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ağa çıkıldı")))
    monkeypatch.setattr(sys, "argv", ["event_review", "--from-saved", "x"])
    with pytest.raises(SystemExit):
        event_review.main()


def test_replay_saved_uses_saved_inputs_and_source_run_time_without_network(tmp_path, monkeypatch):
    import json

    import yfinance

    from app.research.market_risk_shadow import event_review

    monkeypatch.setattr(yfinance, "Ticker", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ağa çıkıldı")))
    monkeypatch.setattr(event_review, "default_technical", lambda *a, **k: {"status": "OK", "technical_score": 20.0})
    monkeypatch.setattr(event_review, "REVIEW_START", SESSIONS[-6])
    sessions = SESSIONS[-40:]  # son satır 25.09.2026 (kayıttaki an 11:25 -> tamamlanmamış)
    src = tmp_path / "run"
    src.mkdir()
    _ohlcv([100.0] * 40, sessions).to_csv(src / "IEYHO_provider_ohlcv.csv")
    _ohlcv([1000.0] * 40, sessions).to_csv(src / "XU100_provider_ohlcv.csv")
    (src / "manifest.json").write_text(json.dumps({"run_at": "2026-09-25T11:25:28+03:00"}), encoding="utf-8")

    monkeypatch.setattr(event_review, "review", lambda a, i, sym, days, params, technical_fn=None, calendar_sessions=None:
                        [{"session": d.isoformat(), "last_input": a.index[-1].date().isoformat()} for d in days])
    out = event_review.replay_saved(src, tmp_path / "out")
    rows = json.loads((out / "IEYHO_daily_review.json").read_text(encoding="utf-8"))
    assert rows[-1]["session"] == "2026-09-24" and rows[-1]["last_input"] == "2026-09-24"  # 25.09 dışarıda
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_run"] == "run" and set(manifest["source_input_sha256"]) == {"IEYHO", "XU100"}
