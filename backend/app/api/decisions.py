from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id_optional
from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.engines.journal.outcome_evaluator import dominant_factor, evaluate_decision
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.market_data.bist_provider import BistProvider
from app.services.notifications.fcm_sender import notify_if_new_opportunity, notify_if_strong_decision

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/{symbol}")
def get_decision(symbol: str, user_id: str | None = Depends(get_current_user_id_optional)):
    try:
        decision = DecisionEngine().decide_for_asset(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if user_id:
        # AŞAMA 45: yalnızca kullanıcının PORTFÖYÜNDE olan varlıklar için
        # bildirim gönderilir. Dashboard artık BIST100'ün tamamını
        # sorguladığından (AŞAMA 43), "her sorgulanan varlık" eski davranışı
        # onlarca alakasız bildirime yol açardı (bkz. fcm_sender.py notu).
        holding = PortfolioRepository().get_position_for_asset(user_id, symbol.upper())
        if holding is not None:
            notify_if_strong_decision(user_id, decision, quantity_held=holding.quantity)
        else:
            # AŞAMA 48/19: elde tutulmayan varlıklar için yalnızca en yüksek
            # güvenilirlikli sinyalde ("STRONG_BULLISH_INITIATION") ve somut
            # bir miktar öneriyle bildirim gönderilir (bkz. fcm_sender.py).
            notify_if_new_opportunity(user_id, decision)

    return decision


@router.get("/{symbol}/history")
def get_decision_history(symbol: str, limit: int = 20):
    return AIDecisionRepository().list_for_asset(symbol.upper(), limit=limit)


@router.get("/{symbol}/explanation")
def get_decision_explanation(symbol: str, decision_id: str | None = None):
    """HATA 18C: opsiyonel `decision_id` -- verilmezse (varsayılan) TAM
    olarak eski canlı/current davranış (geriye dönük uyumlu, zorunlu).
    Verilirse decision-bound (historical) mod: persisted `AIDecision`
    DOĞRUDAN kullanılır, DecisionEngine YENİDEN ÇAĞRILMAZ. Bilinmeyen
    `decision_id` veya sembol uyuşmazlığı -> 404 (canlı moda SESSİZCE
    düşülmez -- bu, bir kimlik hatasını gizlerdi, bkz. HATA 18C bölüm 12)."""
    try:
        return ExplanationEngine().explain(symbol.upper(), decision_id=decision_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/journal")
def get_decision_journal(symbol: str, limit: int = 20):
    """AŞAMA 62 — "Karar Günlüğü": kullanıcı isteği "her test yaptığımızda
    veri tutsun, hatalarımızdan ders çıkaralım, nerede düştü hangi sebepten."
    Geçmiş tarihli haber/makro arşivi olmadığından (bkz. AŞAMA 57/60) GEÇMİŞE
    dönük sahte bir "o zamanki ortam" üretilmez — bunun yerine zaten teknik+
    haber+makronun TAMAMINI kullanan GERÇEK AIDecision kayıtları, gerçek
    sonraki fiyat hareketiyle (7 ve 30 gün ufku) karşılaştırılıp
    değerlendirilir. `dominant_factor`, kararı en çok etkileyen skor
    bileşenini (technical/news/macro) gösterir — "hangi sebepten" sorusuna
    dürüst, sayısal bir cevap.
    """
    symbol = symbol.upper()
    decisions = AIDecisionRepository().list_for_asset(symbol, limit=limit)
    if not decisions:
        return []

    try:
        history = BistProvider().get_history(symbol, period="2y")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    close_series = history["Close"]
    close_series.index = [ts.date() for ts in close_series.index]

    entries = []
    for decision in decisions:
        entries.append(
            {
                **decision.model_dump(),
                "outcomes": evaluate_decision(decision, close_series),
                "dominant_factor": dominant_factor(decision),
            }
        )
    return entries
