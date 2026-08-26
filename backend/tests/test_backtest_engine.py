import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.engine import compare_strategies, simulate, technical_score_series
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.engine import DEFAULT_WEIGHTS


def _uptrend_df(n=80):
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 + pd.Series(range(n), dtype=float) * 0.5
    close.index = idx
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": [1000.0] * n},
        index=idx,
    )


def _noisy_trending_df(n=150, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = 100 + np.cumsum(rng.normal(0.2, 1.2, n))
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, n),
        },
        index=idx,
    )


def test_technical_score_series_matches_input_length_and_bounds():
    df = _uptrend_df()
    series = technical_score_series(df, DEFAULT_WEIGHTS)
    assert len(series) == len(df)
    assert series.dropna().between(-100, 100).all()


def test_simulate_executes_buy_then_sell_on_signals():
    # HATA 3A: execution artık T+1 Open'da -- Close sadece sinyal uretimi ve
    # mark-to-market icin kullanilir, ASLA execution fiyati olarak degil.
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "Open": [99.0, 105.0, 115.0, 95.0, 85.0],
            "Close": [100.0, 110.0, 120.0, 90.0, 80.0],
        },
        index=idx,
    )
    # gun 0: BUY sinyali (Close=100) -> execution gun 1 Open=105
    # gun 3: SELL sinyali (Close=90) -> execution gun 4 Open=85
    scores = pd.Series([50.0, 10.0, 10.0, -50.0, -10.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["entry_price"] == 105.0  # Open[gun1], DEGIL Close[gun0]=100
    assert trade["exit_price"] == 85.0  # Open[gun4], DEGIL Close[gun3]=90
    assert trade["entry_date"] == "2024-01-02"  # execution tarihi, sinyal tarihi (01-01) DEGIL
    assert trade["exit_date"] == "2024-01-05"
    assert trade["entry_signal_date"] == "2024-01-01"
    assert trade["entry_signal_price"] == 100.0
    assert trade["exit_signal_date"] == "2024-01-04"
    assert trade["exit_signal_price"] == 90.0
    assert trade["return_pct"] == pytest.approx((85.0 - 105.0) / 105.0 * 100, abs=0.01)
    assert result["final_equity"] == pytest.approx(1000.0 / 105.0 * 85.0, abs=0.01)
    assert result["open_position"] is None
    assert result["unexecuted_signal"] is None


def test_simulate_buy_and_sell_are_never_executed_at_signal_close():
    # HATA 3 regresyon kilidi: same-bar execution bias BIR DAHA GERI GELMEMELI.
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "Open": [99.0, 105.0, 115.0, 95.0, 85.0],
            "Close": [100.0, 110.0, 120.0, 90.0, 80.0],
        },
        index=idx,
    )
    scores = pd.Series([50.0, 10.0, 10.0, -50.0, -10.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    trade = result["trades"][0]
    signal_day_close_entry = 100.0  # sinyalin olustugu gunun Close'u
    signal_day_close_exit = 90.0
    assert trade["entry_price"] != signal_day_close_entry
    assert trade["exit_price"] != signal_day_close_exit


def test_simulate_stays_flat_without_buy_signal():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [100.0, 101.0, 102.0], "Close": [100.0, 101.0, 102.0]}, index=idx)
    scores = pd.Series([0.0, 0.0, 0.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trade_count"] == 0
    assert result["final_equity"] == 1000.0
    assert result["open_position"] is None


def test_simulate_open_position_at_end_is_mark_to_market_not_a_closed_trade():
    # HATA 3A: backtest sonunda acik kalan pozisyon GERCEK bir SELL execution
    # DEGILDIR -- trades[]'e sahte bir kapanis kaydi EKLENMEMELI, yalnizca
    # mark-to-market ile ayri (open_position) raporlanmali.
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [99.0, 110.0, 111.0], "Close": [100.0, 110.0, 120.0]}, index=idx)
    scores = pd.Series([50.0, 10.0, 10.0], index=idx)  # yalnizca BUY sinyali (gun0), hic SELL yok

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trades"] == []  # HICBIR gercek kapanmis islem yok
    assert result["trade_count"] == 0
    assert result["win_rate_pct"] == 0.0  # kapali islem yok -> eski API sozlesmesiyle 0.0 (None DEGIL)

    assert result["open_position"] is not None
    pos = result["open_position"]
    assert pos["status"] == "OPEN"
    assert pos["entry_execution_price"] == 110.0  # Open[gun1], BUY sinyalinin (gun0) Close'u DEGIL
    assert pos["entry_signal_price"] == 100.0
    assert pos["mark_price"] == 120.0  # son barin Close'u
    assert pos["unrealized_return_pct"] == pytest.approx((120.0 - 110.0) / 110.0 * 100, abs=0.01)

    # total_return/final_equity/equity_curve/max_drawdown acik pozisyonun
    # gerceklesmemis (unrealized) kar/zararini HALA icermeli (mark-to-market).
    assert result["final_equity"] == pytest.approx(1000.0 / 110.0 * 120.0, abs=0.01)
    assert result["equity_curve"][-1]["equity"] == pytest.approx(1000.0 / 110.0 * 120.0, abs=0.01)


def test_simulate_last_bar_new_buy_signal_is_not_executed():
    # Durum A: son barda YENI bir sinyal olustu ama T+1 barı yok -- Close'a
    # sahte fallback YAPILMAMALI, hicbir islem/pozisyon acilmamali.
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [100.0, 101.0, 102.0], "Close": [100.0, 101.0, 102.0]}, index=idx)
    scores = pd.Series([0.0, 0.0, 50.0], index=idx)  # son barda BUY

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trades"] == []
    assert result["trade_count"] == 0
    assert result["open_position"] is None
    assert result["final_equity"] == 1000.0  # hicbir sey degismedi
    assert result["unexecuted_signal"] == {
        "action": "BUY",
        "signal_date": "2024-01-03",
        "signal_price": 102.0,
        "reason": "NO_NEXT_BAR",
    }


def test_simulate_last_bar_new_sell_signal_with_open_position_is_not_executed():
    # Durum: pozisyon zaten acik, son barda YENI bir SELL sinyali olusuyor ama
    # T+1 yok -- satis execute edilmemeli, pozisyon OPEN kalmali, final Close
    # ile mark-to-market edilmeli, sahte closed trade OLUSMAMALI.
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [99.0, 110.0, 111.0], "Close": [100.0, 110.0, 90.0]}, index=idx)
    scores = pd.Series([50.0, 0.0, -50.0], index=idx)  # gun0 BUY, son barda (gun2) SELL sinyali

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trades"] == []
    assert result["trade_count"] == 0
    assert result["open_position"] is not None
    assert result["open_position"]["status"] == "OPEN"
    assert result["open_position"]["mark_price"] == 90.0  # son barin Close'u
    assert result["unexecuted_signal"]["action"] == "SELL"
    assert result["unexecuted_signal"]["reason"] == "NO_NEXT_BAR"


@pytest.mark.parametrize("invalid_open", [float("nan"), float("inf"), 0.0, -5.0])
def test_simulate_invalid_next_open_skips_execution_without_close_fallback(invalid_open):
    # HATA 3A: Open[T+1] NaN/inf/<=0 ise Close'a fallback YASAK -- pending
    # signal execute edilmeden dusurulmeli, INVALID_NEXT_OPEN olarak raporlanmali.
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {"Open": [99.0, invalid_open, 105.0], "Close": [100.0, 101.0, 106.0]}, index=idx
    )
    scores = pd.Series([50.0, 0.0, 0.0], index=idx)  # gun0 BUY sinyali -> gun1 Open GECERSIZ

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trades"] == []
    assert result["open_position"] is None
    assert result["final_equity"] == 1000.0  # hicbir islem gerceklesmedi
    assert result["skipped_executions"] == [
        {
            "action": "BUY",
            "signal_date": "2024-01-01",
            "attempted_execution_date": "2024-01-02",
            "reason": "INVALID_NEXT_OPEN",
        }
    ]


def test_simulate_buy_gap_up_overnight_move_excluded_from_return():
    # Sentetik Test A (HATA 3A): T Close=100 BUY sinyali, T+1 Open=110,
    # T+1 Close=112. entry=110 olmali; 100->110 gap yatirimci getirisi DEGIL,
    # yalnizca 110->112 hareketi yatirimci getirisidir.
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    df = pd.DataFrame({"Open": [99.0, 110.0], "Close": [100.0, 112.0]}, index=idx)
    scores = pd.Series([50.0, 0.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    pos = result["open_position"]
    assert pos["entry_execution_price"] == 110.0
    expected_equity_day1 = 1000.0 / 110.0 * 112.0  # sadece Open[T+1]->Close[T+1]
    assert result["equity_curve"][-1]["equity"] == pytest.approx(expected_equity_day1, abs=0.01)


def test_simulate_buy_gap_down_entry_uses_next_open():
    # Sentetik Test B: T Close=100 BUY sinyali, T+1 Open=90 -> entry=90.
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    df = pd.DataFrame({"Open": [99.0, 90.0], "Close": [100.0, 95.0]}, index=idx)
    scores = pd.Series([50.0, 0.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["open_position"]["entry_execution_price"] == 90.0


def test_simulate_sell_gap_down_overnight_loss_owned_by_position():
    # Sentetik Test C: pozisyon acik, T Close=100 SELL sinyali, T+1 Open=90
    # -> exit=90; 100->90 overnight kaybi POZISYONA AIT.
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    df = pd.DataFrame(
        {"Open": [99.0, 100.0, 95.0, 90.0], "Close": [100.0, 102.0, 100.0, 88.0]}, index=idx
    )
    scores = pd.Series([50.0, 0.0, -50.0, 0.0], index=idx)  # gun0 BUY, gun2 SELL sinyali (Close=100)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    trade = result["trades"][0]
    assert trade["exit_price"] == 90.0
    assert trade["exit_signal_price"] == 100.0
    # Sinyal gunu (gun2) hala acik pozisyon Close(=100) ile mark ediliyor;
    # T+1'de (gun3) satis Open(=90)'da gerceklesiyor -> overnight kaybi
    # gun2->gun3 equity gecisinde YATIRIMCIYA yansimali.
    assert result["equity_curve"][2]["equity"] == pytest.approx(1000.0)  # 10 hisse * 100
    assert result["equity_curve"][3]["equity"] == pytest.approx(900.0)  # 10 hisse * 90


def test_simulate_sell_gap_up_overnight_gain_owned_by_position():
    # Sentetik Test D: pozisyon acik, T Close=100 SELL sinyali, T+1 Open=110
    # -> exit=110; overnight hareket POZISYONA AIT.
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    df = pd.DataFrame(
        {"Open": [99.0, 100.0, 95.0, 110.0], "Close": [100.0, 102.0, 100.0, 105.0]}, index=idx
    )
    scores = pd.Series([50.0, 0.0, -50.0, 0.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    trade = result["trades"][0]
    assert trade["exit_price"] == 110.0
    assert result["equity_curve"][2]["equity"] == pytest.approx(1000.0)
    assert result["equity_curve"][3]["equity"] == pytest.approx(1100.0)


def test_compare_strategies_returns_one_result_per_preset_sorted_by_return():
    df = _noisy_trending_df()

    results = compare_strategies(df, STRATEGY_PRESETS, DEFAULT_THRESHOLDS)

    assert len(results) == len(STRATEGY_PRESETS)
    assert {r["preset"] for r in results} == set(STRATEGY_PRESETS.keys())
    returns = [r["total_return_pct"] for r in results]
    assert returns == sorted(returns, reverse=True)


def test_compare_strategies_each_result_has_expected_metrics():
    df = _noisy_trending_df()

    results = compare_strategies(df, STRATEGY_PRESETS, DEFAULT_THRESHOLDS)

    for r in results:
        assert set(r.keys()) == {
            "preset",
            "total_return_pct",
            "buy_and_hold_return_pct",
            "max_drawdown_pct",
            "trade_count",
            "win_rate_pct",
        }
