"""FLOW 1B istatistik ilkelleri — saf numpy/pandas (scipy yok, I/O yok).

Temel ilke: hisse-gün satırları bağımsız SAYILMAZ. Her istatistik önce tarih
bazında (kesitsel) hesaplanır; belirsizlik, bu tarih serisinin ortalaması
üzerinde hareketli blok bootstrap (birincil) ve Newey-West HAC (ikincil) ile
ölçülür. Parametreler kilitli protokoldedir.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

BOOTSTRAP_BLOCK_LENGTH = 20
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 12001


def rank_pct(values: pd.Series) -> pd.Series:
    return values.rank(method="average")


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    xc = x - x.mean()
    yc = y - y.mean()
    denom = math.sqrt(float((xc * xc).sum()) * float((yc * yc).sum()))
    if denom == 0:
        return float("nan")
    return float((xc * yc).sum() / denom)


def spearman(x: pd.Series, y: pd.Series) -> float:
    """Ortalama-sıra dönüşümlü Pearson (= Spearman). NaN çiftleri atılır."""
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return float("nan")
    return pearson(rank_pct(x[mask]).to_numpy(float), rank_pct(y[mask]).to_numpy(float))


def rank_residual(feature: pd.Series, controls: pd.DataFrame) -> pd.Series:
    """rank(feature) ~ 1 + rank(controls) OLS artığı. Girdiler NaN içermemeli."""
    y = rank_pct(feature).to_numpy(float)
    x_cols = [rank_pct(controls[c]).to_numpy(float) for c in controls.columns]
    x = np.column_stack([np.ones(len(y)), *x_cols])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return pd.Series(y - x @ beta, index=feature.index)


def partial_rank_ic(feature: pd.Series, controls: pd.DataFrame, target: pd.Series) -> float:
    """Sıra semi-partial korelasyonu: yalnızca feature kontrollere göre
    artıklaştırılır; artık ile rank(target) arasındaki Pearson. Kontrolün
    kendisinin hedefle ilişkisi HESAPLANMAZ (Technical-kör)."""
    frame = pd.concat([feature.rename("_f"), controls, target.rename("_y")], axis=1).dropna()
    if len(frame) < 3 + controls.shape[1]:
        return float("nan")
    resid = rank_residual(frame["_f"], frame[list(controls.columns)])
    feature_ranks = rank_pct(frame["_f"]).to_numpy(float)
    # Feature kontrollerce TAMAMEN açıklanıyorsa artık yalnızca kayan-nokta
    # gürültüsüdür; korelasyonu tanımsızdır (0 veya sahte değer UYDURULMAZ).
    if float(resid.std()) <= 1e-9 * max(float(feature_ranks.std()), 1.0):
        return float("nan")
    return pearson(resid.to_numpy(float), rank_pct(frame["_y"]).to_numpy(float))


def block_bootstrap_means(
    series: np.ndarray,
    block_length: int = BOOTSTRAP_BLOCK_LENGTH,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> np.ndarray:
    """Dairesel (circular) blok bootstrap: sıralı seri uçtan uca sarılır,
    rastgele başlangıçlı `block_length` uzunluklu bloklar birleştirilip n'e
    kırpılır; her replika için ortalama döner. Dairesel sarma, düz "moving
    block" sürümünün seri uçlarını eksik örnekleme yanlılığını giderir (kısa
    serilerde CI'ın ortalamayı dışlamasına yol açıyordu — sentetik smoke
    testinde gözlendi, gerçek sonuçlardan ÖNCE düzeltildi). Kümülatif toplam
    ile vektörize."""
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n == 0:
        return np.array([])
    L = min(block_length, n)
    k = math.ceil(n / L)
    last_len = n - (k - 1) * L
    wrapped = np.concatenate([x, x[:L]])
    cs = np.concatenate([[0.0], np.cumsum(wrapped)])
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(replicates, k))
    full = cs[starts[:, :-1] + L] - cs[starts[:, :-1]]
    last = cs[starts[:, -1] + last_len] - cs[starts[:, -1]]
    return (full.sum(axis=1) + last) / n


def newey_west_t(series: np.ndarray, lag: int) -> float:
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    s = float((e * e).sum()) / n
    for j in range(1, min(lag, n - 1) + 1):
        w = 1.0 - j / (lag + 1.0)
        s += 2.0 * w * float((e[j:] * e[:-j]).sum()) / n
    if s <= 0:
        return float("nan")
    return float(x.mean() / math.sqrt(s / n))


def summarize_series(series: pd.Series, horizon: int, scale: float = 1.0,
                     block_length: int = BOOTSTRAP_BLOCK_LENGTH) -> dict:
    """Tarih bazlı bir istatistik serisinin özeti + blok bootstrap CI + NW t.
    `block_length` serinin KENDİ adımları cinsindendir (günlük seride 20
    seans; her 10 seansta bir örneklenen seride 2 = yine 20 seans)."""
    x = series.dropna().sort_index().to_numpy(float) * scale
    n = len(x)
    if n == 0:
        return {"n_dates": 0, "mean": None, "median": None, "std": None, "positive_rate": None,
                "ci_low": None, "ci_high": None, "p_boot": None, "nw_t": None}
    boot = block_bootstrap_means(x, block_length=block_length)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p = 2.0 * min(float((boot <= 0).mean()), float((boot >= 0).mean()))
    p = max(min(p, 1.0), 1.0 / BOOTSTRAP_REPLICATES)
    return {
        "n_dates": int(n),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "std": float(x.std(ddof=1)) if n > 1 else None,
        "positive_rate": float((x > 0).mean()),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "p_boot": float(p),
        "nw_t": newey_west_t(x, max(horizon, 1)),
    }


def label_positive(summary: dict) -> str:
    if summary.get("ci_low") is None:
        return "NOT_EVALUABLE"
    if summary["ci_low"] > 0:
        return "SUPPORTED"
    if summary["ci_high"] < 0:
        return "EVIDENCE_OPPOSITE_DIRECTION"
    return "NOT_ESTABLISHED"


def label_negative(summary: dict) -> str:
    """Negatif yönlü hipotezler (H2/H5) için."""
    if summary.get("ci_low") is None:
        return "NOT_EVALUABLE"
    if summary["ci_high"] < 0:
        return "SUPPORTED"
    if summary["ci_low"] > 0:
        return "EVIDENCE_OPPOSITE_DIRECTION"
    return "NOT_ESTABLISHED"


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    items = sorted((p, k) for k, p in p_values.items() if p is not None)
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[k] = running
    return adjusted


def assign_quintiles(values: pd.Series) -> pd.Series:
    """Sıra üzerinden 5 eşit sayılı kova (1..5). Çağıran minimum kesit
    büyüklüğünü garanti eder."""
    ranks = values.rank(method="first")
    return pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def monotonicity(quintile_means: list[float]) -> dict:
    """Ortalama kova getirilerinin 1..5 ile Spearman'ı ve artan adım sayısı."""
    arr = pd.Series(quintile_means, dtype=float)
    if arr.isna().any():
        return {"spearman_vs_rank": None, "increasing_steps_of_4": None}
    rho = spearman(pd.Series([1, 2, 3, 4, 5], dtype=float), arr)
    steps = int(sum(1 for a, b in zip(arr[:-1], arr[1:]) if b > a))
    return {"spearman_vs_rank": rho, "increasing_steps_of_4": steps}
