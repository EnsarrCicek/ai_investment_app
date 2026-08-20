"""BacktestEngine — AŞAMA 28.

Geçmiş fiyat verisi üzerinde DecisionEngine'in ürettiği AL/ZAYIF AL/TUT/
ZAYIF SAT/SAT sinyallerine göre basit bir "sinyalde pozisyon aç/kapat"
stratejisi simüle edilir.

Kapsam kararı: Yalnızca technical_score kullanılır. news_score ve macro_score
için günlük geçmiş serisi saklanmıyor (news_analyses/macro_snapshots yalnızca
"o an geçerli olan" analiz/anlık görüntüyü tutuyor, ana doküman kural 6) —
bu yüzden geçmişe dönük backtest'te noktasal (point-in-time) olarak
kullanılamazlar. DecisionEngine'in "Missing
Data Davranışı" ilkesi sayesinde bu, kararın YANLIŞ olmasına değil, mevcut
tek skorun ağırlığının otomatik %100'e normalize edilmesine yol açar —
canlı sistemle aynı davranış sözleşmesi.

Not: Buradaki skor formülü, TechnicalAnalysisEngine.analyze_with_id ile
birebir aynı olacak şekilde elle senkronize tutulur (ikisi de aynı
indicators.py fonksiyonlarını kullanır). Vektörize (tüm seri için tek
seferde) hesaplanması gerektiğinden — canlı motor yalnızca son günü
hesapladığından — ortak bir yardımcıya taşımak yerine burada ayrı,
küçük bir fonksiyon olarak tutuldu.
"""

from datetime import datetime, timezone

import pandas as pd

from app.engines.decision.engine import DEFAULT_THRESHOLDS, _classify
from app.engines.technical import indicators as ind
from app.engines.technical.data_quality import check_data_quality
from app.engines.technical.engine import DEFAULT_WEIGHTS as DEFAULT_TECHNICAL_WEIGHTS
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

MIN_HISTORY_DAYS = 60


def _clamp_series(series: pd.Series) -> pd.Series:
    return series.clip(-100.0, 100.0)


def technical_score_series(df: pd.DataFrame, weights: dict) -> pd.Series:
    close = df["Close"]

    rsi_s = ind.rsi(close)
    _, _, macd_hist_s = ind.macd(close)
    ema_short_s = ind.ema(close, 20)
    ema_long_s = ind.ema(close, 50)
    ema_slope_s = ind.ema_slope(close, window=20, slope_lookback=5)
    upper_s, middle_s, _lower_s = ind.bollinger_bands(close)
    atr_s = ind.atr(df).replace(0, pd.NA)
    momentum_s = ind.momentum(close)
    roc_s = ind.roc(close)
    band_width_s = (upper_s - middle_s).replace(0, pd.NA)
    ema_long_safe = ema_long_s.replace(0, pd.NA)

    components = {
        "rsi": _clamp_series((rsi_s - 50) * 2),
        "macd": _clamp_series((macd_hist_s / atr_s) * 25).fillna(0.0),
        "trend": _clamp_series(((ema_short_s - ema_long_s) / ema_long_safe) * 1000).fillna(0.0),
        "ema_slope": _clamp_series(ema_slope_s * 15).fillna(0.0),
        "bollinger": _clamp_series(((close - middle_s) / band_width_s) * 100).fillna(0.0),
        "momentum": _clamp_series((momentum_s / atr_s) * 20).fillna(0.0),
        "roc": _clamp_series(roc_s * 8),
    }
    weight_sum = sum(weights.get(key, 0.0) for key in components)
    raw_score = sum(components[key] * weights.get(key, 0.0) for key in components)
    score = raw_score / weight_sum if weight_sum else raw_score * 0.0
    return _clamp_series(score).round(2)


def simulate(
    df: pd.DataFrame,
    score_series: pd.Series,
    thresholds: dict,
    initial_capital: float = 100_000.0,
) -> dict:
    """Verilen skor serisine göre sinyal bazlı al-sat simülasyonu. Saf fonksiyon —
    veri çekmeden, tek bir zaten-hesaplanmış skor serisi üzerinde çalışır (bu ayrım
    WalkForwardOptimizer'ın aynı df'in farklı pencerelerini tekrar tekrar simüle
    edebilmesi için gerekli).
    """
    close = df["Close"]
    cash = initial_capital
    shares = 0.0
    entry_price: float | None = None
    entry_date = None
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for i in range(len(df)):
        date = df.index[i]
        price = float(close.iloc[i])
        score = score_series.iloc[i]

        if pd.notna(score):
            decision = _classify(float(score), thresholds)
            if shares == 0 and decision in ("BUY", "WEAK_BUY"):
                shares = cash / price
                cash = 0.0
                entry_price = price
                entry_date = date
            elif shares > 0 and decision in ("SELL", "WEAK_SELL"):
                cash = shares * price
                trades.append(
                    {
                        "entry_date": str(entry_date.date()),
                        "exit_date": str(date.date()),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(price, 2),
                        "return_pct": round((price - entry_price) / entry_price * 100, 2),
                    }
                )
                shares = 0.0
                entry_price = None
                entry_date = None

        equity_curve.append({"date": str(date.date()), "equity": round(cash + shares * price, 2)})

    if shares > 0:
        final_price = float(close.iloc[-1])
        cash = shares * final_price
        trades.append(
            {
                "entry_date": str(entry_date.date()),
                "exit_date": str(df.index[-1].date()),
                "entry_price": round(entry_price, 2),
                "exit_price": round(final_price, 2),
                "return_pct": round((final_price - entry_price) / entry_price * 100, 2),
                "note": "Backtest sonunda açık kalan pozisyon son fiyattan kapatıldı (mark-to-market)",
            }
        )
        shares = 0.0

    final_equity = cash
    total_return_pct = round((final_equity - initial_capital) / initial_capital * 100, 2)

    equity_values = pd.Series([point["equity"] for point in equity_curve])
    running_max = equity_values.cummax()
    drawdown = (equity_values - running_max) / running_max
    max_drawdown_pct = round(float(drawdown.min() * 100), 2) if not drawdown.empty else 0.0

    winning_trades = [t for t in trades if t["return_pct"] > 0]
    win_rate_pct = round(len(winning_trades) / len(trades) * 100, 2) if trades else 0.0

    buy_and_hold_return_pct = round(
        (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100, 2
    )

    return {
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": total_return_pct,
        "buy_and_hold_return_pct": buy_and_hold_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "trade_count": len(trades),
        "win_rate_pct": win_rate_pct,
        "trades": trades,
        "equity_curve": equity_curve,
    }


def compare_strategies(
    df: pd.DataFrame,
    presets: dict[str, dict],
    thresholds: dict,
    initial_capital: float = 100_000.0,
) -> list[dict]:
    """Aynı fiyat serisi üzerinde birden çok adlandırılmış ağırlık ön ayarını
    (bkz. strategy_presets.py) çalıştırıp getiriye göre sıralanmış bir
    karşılaştırma listesi döner — "hangi strateji daha iyi sonuç veriyor"
    sorusuna tek bir sembol için doğrudan cevap. Not: bu, walk_forward_
    optimize_weights'ten FARKLI bir amaca hizmet eder — o train/test
    ayrımıyla overfit'i önlemeye çalışır, bu ise tüm dönem üzerinde basit,
    yorumlanabilir bir karşılaştırma sunar (çok sembollü toplu tarama için
    tasarlandı, bkz. Flutter Strateji Laboratuvarı ekranı).
    """
    warm_df = df.iloc[MIN_HISTORY_DAYS:]
    results = []
    for name, weights in presets.items():
        score_series = technical_score_series(df, weights).iloc[MIN_HISTORY_DAYS:]
        result = simulate(warm_df, score_series, thresholds, initial_capital)
        results.append(
            {
                "preset": name,
                "total_return_pct": result["total_return_pct"],
                "buy_and_hold_return_pct": result["buy_and_hold_return_pct"],
                "max_drawdown_pct": result["max_drawdown_pct"],
                "trade_count": result["trade_count"],
                "win_rate_pct": result["win_rate_pct"],
            }
        )
    results.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return results


class BacktestEngine:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()

    def run(self, symbol: str, period: str = "2y", initial_capital: float = 100_000.0) -> dict:
        df = self._provider.get_history(symbol, period=period)
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS)

        weights = self._config_repo.get("technical_indicator_weights", DEFAULT_TECHNICAL_WEIGHTS)
        thresholds = self._config_repo.get("decision_thresholds", DEFAULT_THRESHOLDS)

        warm_df = df.iloc[MIN_HISTORY_DAYS:]
        score_series = technical_score_series(df, weights).iloc[MIN_HISTORY_DAYS:]

        result = simulate(warm_df, score_series, thresholds, initial_capital)
        return {
            "asset": symbol,
            "period": period,
            "from_date": str(warm_df.index[0].date()),
            "to_date": str(warm_df.index[-1].date()),
            "thresholds": thresholds,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **result,
        }

    def compare_strategies(
        self, symbol: str, presets: dict[str, dict], period: str = "2y", initial_capital: float = 100_000.0
    ) -> dict:
        df = self._provider.get_history(symbol, period=period)
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS)

        thresholds = self._config_repo.get("decision_thresholds", DEFAULT_THRESHOLDS)
        warm_df = df.iloc[MIN_HISTORY_DAYS:]
        results = compare_strategies(df, presets, thresholds, initial_capital)
        return {
            "asset": symbol,
            "period": period,
            "from_date": str(warm_df.index[0].date()),
            "to_date": str(warm_df.index[-1].date()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
