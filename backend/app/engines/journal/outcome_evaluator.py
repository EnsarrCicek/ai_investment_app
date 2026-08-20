"""Karar doğruluk değerlendirmesi ("Karar Günlüğü") — AŞAMA 62.

Kullanıcı isteği: "her test yaptığımızda veri tutsun, yaptığı hataları ona
göre eğitim yapıcaz, daha sonra nerede düştü hangi sebepten." Geçmiş tarihli
haber/makro arşivi olmadığından (bkz. AŞAMA 57/60) GEÇMİŞE dönük sahte bir
"o zamanki haber/makro ortamı" üretilemez — bunun yerine BUGÜNDEN İTİBAREN
biriken GERÇEK AIDecision kayıtları (zaten teknik+haber+makronun TAMAMINI
kullanıyor, bkz. DecisionEngine.decide_for_asset) gerçek sonraki fiyat
hareketiyle karşılaştırılıp değerlendirilir. Zamanla gerçek bir "hangi
kararlar tuttu, hangileri tutmadı, o an hangi skor bileşeni baskındı" arşivi
oluşur — bu, kullanıcının istediği "eğitim" döngüsünün dürüst/uygulanabilir
karşılığıdır.
"""

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.models.ai_decision import AIDecision

EVALUATION_HORIZONS_DAYS = [7, 30]

DIRECTIONAL_DECISIONS = {"BUY", "WEAK_BUY", "SELL", "WEAK_SELL"}
BUY_DECISIONS = {"BUY", "WEAK_BUY"}


def _find_close_on_or_before(close_by_date: dict[date, float], target: date) -> float | None:
    eligible = [d for d in close_by_date if d <= target]
    if not eligible:
        return None
    return close_by_date[max(eligible)]


def _find_close_on_or_after(close_by_date: dict[date, float], target: date) -> float | None:
    eligible = [d for d in close_by_date if d >= target]
    if not eligible:
        return None
    return close_by_date[min(eligible)]


def dominant_factor(decision: AIDecision) -> str | None:
    """Karara en çok katkı veren skor bileşeni — "hangi sebepten" sorusuna
    dürüst, sayısal bir cevap (LLM yok, ağırlık × skor büyüklüğü kıyası)."""
    contributions: dict[str, float] = {}
    if decision.technical_score is not None:
        contributions["technical"] = abs(decision.technical_score * decision.technical_weight)
    if decision.news_score is not None:
        contributions["news"] = abs(decision.news_score * decision.news_weight)
    if decision.macro_score is not None:
        contributions["macro"] = abs(decision.macro_score * decision.macro_weight)
    if not contributions:
        return None
    return max(contributions, key=lambda k: contributions[k])


def evaluate_decision(
    decision: AIDecision,
    close_history: pd.Series,
    horizons_days: list[int] = EVALUATION_HORIZONS_DAYS,
    now: datetime | None = None,
) -> dict[int, dict]:
    """close_history: index=datetime.date, value=float (bkz. benchmark_service.py
    ile aynı tz-safe desen — date anahtarlı, Timestamp değil).
    """
    now = now or datetime.now(timezone.utc)
    close_by_date = {idx: float(val) for idx, val in close_history.items()}
    decision_date = decision.created_at.date()
    price_at_decision = _find_close_on_or_before(close_by_date, decision_date)

    outcomes: dict[int, dict] = {}
    for horizon in horizons_days:
        target_date = decision_date + timedelta(days=horizon)
        if now.date() < target_date:
            outcomes[horizon] = {"status": "BEKLEMEDE"}
            continue

        price_at_horizon = _find_close_on_or_after(close_by_date, target_date)
        if price_at_decision is None or price_at_horizon is None or price_at_decision == 0:
            outcomes[horizon] = {"status": "VERI_YOK"}
            continue

        realized_return_pct = round((price_at_horizon - price_at_decision) / price_at_decision * 100, 2)

        if decision.decision not in DIRECTIONAL_DECISIONS:
            outcomes[horizon] = {"status": "NOTR", "realized_return_pct": realized_return_pct}
            continue

        is_buy = decision.decision in BUY_DECISIONS
        was_correct = realized_return_pct > 0 if is_buy else realized_return_pct < 0
        outcomes[horizon] = {
            "status": "DOGRU" if was_correct else "YANLIS",
            "realized_return_pct": realized_return_pct,
        }

    return outcomes
