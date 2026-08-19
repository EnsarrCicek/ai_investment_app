"""Genişletilmiş backtest metrikleri — TECHNICAL_ANALYSIS_RESEARCH1.md,
rapor madde 7 adım 13.

Mevcut BacktestEngine.simulate() yalnızca total_return/max_drawdown/win_rate
üretiyordu. Bu modül, aynı simulate() çıktısı (equity_curve + trades) üzerine
inşa edilen, saf/bağımsız metrik fonksiyonları sağlar — simulate()'i
DEĞİŞTİRMEZ, sonucunu girdi olarak alır.

Kapsam sınırı: MFE/MAE (Maximum Favorable/Adverse Excursion) bu sürümde
YOK — bunun için simulate()'in açık pozisyon sırasında ara yüksek/düşük
noktaları da kaydetmesi gerekir (şu an yalnızca giriş/çıkış fiyatı
tutuluyor); ayrı bir aşamada, simulate()'e dokunularak eklenecek.
"""

import math

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def sharpe_ratio(equity_curve: list[dict], risk_free_rate_annual: float = 0.0) -> float | None:
    """Yıllıklandırılmış Sharpe oranı — equity eğrisinin günlük getirilerinden.
    Yeterli veri/oynaklık yoksa None döner (Missing Data Davranışı — 0 gibi
    yanlış bir değer UYDURULMAZ).
    """
    equity = pd.Series([p["equity"] for p in equity_curve], dtype=float)
    if len(equity) < 2:
        return None
    daily_returns = equity.pct_change().dropna()
    if daily_returns.empty or daily_returns.std() == 0:
        return None
    daily_rf = risk_free_rate_annual / TRADING_DAYS_PER_YEAR
    excess = daily_returns - daily_rf
    return float((excess.mean() / daily_returns.std()) * math.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(equity_curve: list[dict], risk_free_rate_annual: float = 0.0) -> float | None:
    """Sharpe'a benzer, ama yalnızca NEGATİF getirilerin (downside risk)
    standart sapmasını kullanır — yukarı yönlü oynaklık "risk" sayılmaz.
    """
    equity = pd.Series([p["equity"] for p in equity_curve], dtype=float)
    if len(equity) < 2:
        return None
    daily_returns = equity.pct_change().dropna()
    if daily_returns.empty:
        return None
    daily_rf = risk_free_rate_annual / TRADING_DAYS_PER_YEAR
    excess = daily_returns - daily_rf
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return None
    return float((excess.mean() / downside.std()) * math.sqrt(TRADING_DAYS_PER_YEAR))


def profit_factor(trades: list[dict]) -> float | None:
    """Toplam kazanç / |toplam kayıp| (return_pct bazında). Hiç kayıp yoksa
    None döner (bölme belirsiz — "sonsuz" gibi yanıltıcı bir değer UYDURULMAZ).
    """
    if not trades:
        return None
    gains = sum(t["return_pct"] for t in trades if t["return_pct"] > 0)
    losses = abs(sum(t["return_pct"] for t in trades if t["return_pct"] < 0))
    if losses == 0:
        return None
    return round(gains / losses, 4)


def expectancy_pct(trades: list[dict]) -> float | None:
    """İşlem başına ortalama getiri (%) — pozitifse strateji uzun vadede
    "beklentiye göre" kârlı demektir (işlem sayısı arttıkça daha güvenilir).
    """
    if not trades:
        return None
    return round(sum(t["return_pct"] for t in trades) / len(trades), 4)


def compute_extended_metrics(backtest_result: dict) -> dict:
    """BacktestEngine.run()/simulate()'in döndürdüğü sözlüğü alıp yeni
    metrikleri ekler (mevcut alanları DEĞİŞTİRMEZ, ayrı bir sözlük döner).
    """
    return {
        "sharpe_ratio": sharpe_ratio(backtest_result["equity_curve"]),
        "sortino_ratio": sortino_ratio(backtest_result["equity_curve"]),
        "profit_factor": profit_factor(backtest_result["trades"]),
        "expectancy_pct": expectancy_pct(backtest_result["trades"]),
    }
