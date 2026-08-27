"""WalkForwardOptimizer — AŞAMA 29.

BacktestEngine'in tek bir sabit eşik setiyle çalışmasının riski: o eşikler
tüm geçmiş veriye bakılarak "en iyi sonucu veren" şekilde seçilirse, bu
sadece geçmişe aşırı uydurma (overfitting) olur ve gelecekte işe
yaramayabilir. Walk-forward optimizasyon bunu önlemek için standart yöntem:
veriyi ardışık pencerelere böl, her pencerede eşikleri yalnızca EĞİTİM
kısmında seç, sonra bu eşikleri hiç görmediği TEST kısmında dene, pencereyi
kaydır ve tekrarla. Rapor edilen performans yalnızca test (out-of-sample)
sonuçlarının toplamıdır — eğitim sonuçları asla performans iddiası olarak
kullanılmaz.

Kapsam kararı: Optimize edilen parametre, 6 teknik gösterge ağırlığı değil
(arama uzayı çok büyük ve MVP için gereksiz), yalnızca DecisionEngine'in
karar eşikleridir (buy/weak_buy/weak_sell/sell) — küçük, yorumlanabilir bir
arama uzayı ve doğrudan "ne kadar agresif alım-satım yapılsın" sorusuna
karşılık gelir.

26.08.2026 (HATA 3B): `BacktestEngine.run()` ile AYNI completed-session-only
veri sözleşmesi burada da kullanılır (bkz. `completed_history.py`) — bu
sınıf kendi BAĞIMSIZ `get_history()` çağrısını yaptığından, o düzeltmeyi
otomatik devralmıyordu; HATA 3B denetiminde bu ayrıca tespit edildi.
"""

from datetime import datetime, timezone

import pandas as pd

from app.engines.backtest.completed_history import prepare_backtest_history
from app.engines.backtest.engine import MIN_HISTORY_DAYS, simulate, technical_score_series
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.engine import DEFAULT_WEIGHTS as DEFAULT_TECHNICAL_WEIGHTS
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider
from app.services.market_data.trading_calendar import session_normalization_to_dict

DEFAULT_CANDIDATE_THRESHOLDS = [
    {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0},  # varsayılan (DecisionEngine ile aynı)
    {"buy": 30.0, "weak_buy": 10.0, "weak_sell": -10.0, "sell": -30.0},  # agresif — daha sık işlem
    {"buy": 50.0, "weak_buy": 25.0, "weak_sell": -25.0, "sell": -50.0},  # muhafazakar — daha seyrek işlem
]


class WalkForwardOptimizer:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()

    def run(
        self,
        symbol: str,
        period: str = "3y",
        train_days: int = 252,
        test_days: int = 63,
        candidate_thresholds: list[dict] | None = None,
        initial_capital: float = 100_000.0,
        now: datetime | None = None,
    ) -> dict:
        # HATA 3B (26.08.2026): BacktestEngine ile AYNI completed-session-only
        # sözleşmesi — bkz. completed_history.py, engine.py modül docstring'i.
        # HATA 3E: `prepared.history` pre-roll KESİNLİKLE İÇERMEZ — train/test
        # pencere sınırları yalnızca fiili analiz penceresinden hesaplanır.
        prepared = prepare_backtest_history(self._provider, symbol, period, MIN_HISTORY_DAYS, now=now)
        df = prepared.history
        if len(df) < MIN_HISTORY_DAYS + train_days + test_days:
            raise ValueError(
                f"'{symbol}' için walk-forward optimizasyona yetecek geçmiş veri yok "
                f"({len(df)} gün, en az {MIN_HISTORY_DAYS + train_days + test_days} gerekli)"
            )

        weights = self._config_repo.get("technical_indicator_weights", DEFAULT_TECHNICAL_WEIGHTS)
        candidates = candidate_thresholds or DEFAULT_CANDIDATE_THRESHOLDS

        full_score_series = technical_score_series(df, weights)

        windows = []
        start = MIN_HISTORY_DAYS
        while start + train_days + test_days <= len(df):
            train_slice = slice(start, start + train_days)
            test_slice = slice(start + train_days, start + train_days + test_days)

            best_candidate = None
            best_train_return = None
            for candidate in candidates:
                train_result = simulate(
                    df.iloc[train_slice], full_score_series.iloc[train_slice], candidate, initial_capital
                )
                if best_train_return is None or train_result["total_return_pct"] > best_train_return:
                    best_train_return = train_result["total_return_pct"]
                    best_candidate = candidate

            test_result = simulate(
                df.iloc[test_slice], full_score_series.iloc[test_slice], best_candidate, initial_capital
            )

            windows.append(
                {
                    "train_from": str(df.index[train_slice.start].date()),
                    "train_to": str(df.index[train_slice.stop - 1].date()),
                    "test_from": str(df.index[test_slice.start].date()),
                    "test_to": str(df.index[test_slice.stop - 1].date()),
                    "chosen_thresholds": best_candidate,
                    "train_return_pct": best_train_return,
                    "test_return_pct": test_result["total_return_pct"],
                    "test_trade_count": test_result["trade_count"],
                    "test_max_drawdown_pct": test_result["max_drawdown_pct"],
                }
            )

            start += test_days

        out_of_sample_returns = [w["test_return_pct"] for w in windows]
        compounded = 1.0
        for pct in out_of_sample_returns:
            compounded *= 1 + pct / 100
        aggregate_out_of_sample_return_pct = round((compounded - 1) * 100, 2)

        profitable_windows = sum(1 for r in out_of_sample_returns if r > 0)
        window_win_rate_pct = (
            round(profitable_windows / len(windows) * 100, 2) if windows else 0.0
        )

        return {
            "asset": symbol,
            "period": period,
            "train_days": train_days,
            "test_days": test_days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backtest_data_as_of": str(prepared.backtest_data_as_of),
            "data_policy": "COMPLETED_DAILY_ONLY",
            "requested_window_start": str(prepared.requested_window_start),
            "actual_history_start": str(prepared.actual_history_start),
            "history_validation_status": prepared.history_validation_status,
            **session_normalization_to_dict(prepared.normalization),
            "window_count": len(windows),
            "window_win_rate_pct": window_win_rate_pct,
            "aggregate_out_of_sample_return_pct": aggregate_out_of_sample_return_pct,
            "windows": windows,
        }
