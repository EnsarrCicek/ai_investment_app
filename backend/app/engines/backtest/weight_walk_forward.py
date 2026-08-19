"""Ağırlık grid'i için walk-forward optimizasyon — TECHNICAL_ANALYSIS_
RESEARCH1.md, rapor madde 7 adım 13.

Not: `walk_forward.py`'deki mevcut `WalkForwardOptimizer` (AŞAMA 29) zaten
DecisionEngine'in karar EŞİKLERİNİ (buy/weak_buy/weak_sell/sell) walk-forward
yöntemiyle optimize ediyordu — bu modül onun YERİNE değil, ONU TAMAMLAYAN
ayrı bir eksen ekler: `technical_indicator_weights` (RSI/MACD/trend/ema_slope/
bollinger/momentum/roc ağırlıkları) için aynı prensiple (train'de seç, testte
— hiç görülmemiş veride — ölç) bir grid araması. İkisi ayrı dosyalarda
kalır çünkü optimize ettikleri parametre farklıdır ve birleştirmek arama
uzayını (weights × thresholds) kontrolsüz büyütürdü.

Mevcut WalkForwardOptimizer'dan farklı olarak bu modül saf/bağımsız
fonksiyonlardan oluşur (provider'a bağımlı değildir, doğrudan bir DataFrame
alır) — birim testte network'e gitmeden, üretilmiş sentetik veriyle test
edilebilir.

Uygulama detayı — göstergelerin ısınma dönemini korumak için: her aday
ağırlık setinin skor serisi TÜM veri üzerinde BİR KEZ hesaplanır (kısa bir
alt-pencerede yeniden hesaplamak, uzun pencereli göstergelerin (EMA50 gibi)
ısınma bağlamını kaybettirirdi), sonra yalnızca ilgili fold aralığı
DİLİMLENİR. Bu, causality garantisini bozmaz (bkz. test_indicator_
causality.py) — bir bar'daki skor yalnızca o bar'a kadarki veriye bağlıdır,
sonradan dilimlemek geçmişe dönük hiçbir şeyi değiştirmez.
"""

import pandas as pd

from app.engines.backtest.engine import simulate, technical_score_series
from app.engines.backtest.metrics import expectancy_pct


def split_walk_forward_indices(n: int, n_splits: int = 4, train_ratio: float = 0.7) -> list[tuple[slice, slice]]:
    """Veriyi n_splits adet ardışık, sabit boyutlu (train, test) blok çiftine böler."""
    block_size = n // n_splits
    if block_size < 10:
        raise ValueError(f"Walk-forward için yeterli veri yok ({n} bar, {n_splits} bölüm için çok küçük)")

    splits: list[tuple[slice, slice]] = []
    for i in range(n_splits):
        start = i * block_size
        end = start + block_size if i < n_splits - 1 else n
        train_size = start + int((end - start) * train_ratio)
        if train_size - start < 5 or end - train_size < 5:
            continue
        splits.append((slice(start, train_size), slice(train_size, end)))
    return splits


def walk_forward_optimize_weights(
    df: pd.DataFrame,
    weight_grid: list[dict],
    thresholds: dict,
    n_splits: int = 4,
    train_ratio: float = 0.7,
    initial_capital: float = 100_000.0,
) -> dict:
    """Her fold için: train bölümünde grid'deki en iyi ağırlık setini
    expectancy_pct'e göre seç, sonra o setin test (out-of-sample) performansını
    ölç. Tüm fold'ların test sonuçlarını birleştirip özet döner.
    """
    n = len(df)
    splits = split_walk_forward_indices(n, n_splits=n_splits, train_ratio=train_ratio)
    if not splits:
        raise ValueError("Walk-forward için hiçbir geçerli bölüm oluşturulamadı")

    candidate_series = [technical_score_series(df, candidate) for candidate in weight_grid]

    fold_results = []
    for train_slice, test_slice in splits:
        best_idx: int | None = None
        best_metric = float("-inf")
        for idx, series in enumerate(candidate_series):
            train_df = df.iloc[train_slice]
            train_scores = series.iloc[train_slice]
            train_result = simulate(train_df, train_scores, thresholds, initial_capital)
            metric_value = expectancy_pct(train_result["trades"])
            if metric_value is not None and metric_value > best_metric:
                best_metric = metric_value
                best_idx = idx

        if best_idx is None:
            best_idx = 0  # hiçbir aday train'de işlem üretmediyse ilk adaya düş

        test_df = df.iloc[test_slice]
        test_scores = candidate_series[best_idx].iloc[test_slice]
        test_result = simulate(test_df, test_scores, thresholds, initial_capital)

        fold_results.append(
            {
                "chosen_weights": weight_grid[best_idx],
                "test_total_return_pct": test_result["total_return_pct"],
                "test_trade_count": test_result["trade_count"],
                "test_win_rate_pct": test_result["win_rate_pct"],
            }
        )

    avg_out_of_sample_return = sum(f["test_total_return_pct"] for f in fold_results) / len(fold_results)
    return {
        "folds": fold_results,
        "avg_out_of_sample_return_pct": round(avg_out_of_sample_return, 2),
        "n_folds": len(fold_results),
    }
