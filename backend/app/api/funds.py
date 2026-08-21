from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id, get_current_user_id_optional
from app.models.fund_investment_settings import FundInvestmentSettings
from app.models.fund_position import FundPosition
from app.repositories.fund_investment_settings_repository import FundInvestmentSettingsRepository
from app.repositories.fund_position_repository import FundPositionRepository
from app.schemas.funds import FundAllocateRequest, FundInvestmentSettingsUpdate, FundPositionCreate
from app.services.funds.allocation import recommend_allocation
from app.services.funds.analysis_cache_service import get_ranked_funds
from app.services.news.firm_extraction import extract_analyst_firm
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider
from app.services.notifications.fund_notifier import (
    notify_ad_hoc_allocation,
    notify_monthly_allocation,
    notify_switch_recommendations,
)
from app.utils.turkish_text import tr_upper as _tr_upper

router = APIRouter(prefix="/funds", tags=["funds"])


@router.get("")
def list_funds(
    limit: int = 50, q: str | None = None, user_id: str | None = Depends(get_current_user_id_optional)
):
    """Sıralanmış fon listesi (en iyi skordan en kötüye). `q` verilirse fon
    kodunda/adında (büyük-küçük harf duyarsız) arama yapılır — AŞAMA 60:
    kullanıcı isteği "arama kısmı ekle, her fona ulaşabileyim" — limit yalnızca
    öneri listesini kısaltmak için, arama TÜM (kalite filtresini geçen) fon
    evreninde yapılır.

    AŞAMA 58: kullanıcı oturum açmışsa yan etki olarak (a) aylık bütçe önerisi
    bildirimi (bu ay zaten gönderilmediyse) ve (b) tuttuğu fonlar için
    değiştirme önerisi bildirimi kontrol edilir — decisions.py'deki "GET her
    açıldığında bildirim kontrolü" ile aynı mimari desen (bu projede
    scheduler yok).
    """
    try:
        ranked = get_ranked_funds()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if user_id:
        settings = FundInvestmentSettingsRepository().get(user_id)
        if settings is not None and settings.monthly_budget > 0:
            notify_monthly_allocation(user_id, ranked, settings.monthly_budget)

        positions = FundPositionRepository().list_for_user(user_id)
        if positions:
            score_by_code = {f.fund_code: f.composite_score for f in ranked}
            held_scores = {p.fund_code: score_by_code[p.fund_code] for p in positions if p.fund_code in score_by_code}
            notify_switch_recommendations(user_id, held_scores, ranked)

    if q:
        needle = _tr_upper(q.strip())
        ranked = [f for f in ranked if needle in _tr_upper(f.fund_code) or needle in _tr_upper(f.fund_name)]

    return ranked[:limit]


@router.get("/settings")
def get_settings(user_id: str = Depends(get_current_user_id)):
    settings = FundInvestmentSettingsRepository().get(user_id)
    if settings is None:
        return {"user_id": user_id, "monthly_income": None, "monthly_budget": 0.0}
    return settings


@router.put("/settings")
def update_settings(payload: FundInvestmentSettingsUpdate, user_id: str = Depends(get_current_user_id)):
    settings = FundInvestmentSettings(
        user_id=user_id, **payload.model_dump(), updated_at=datetime.now(timezone.utc)
    )
    FundInvestmentSettingsRepository().set(settings)
    return settings


@router.get("/allocation-preview")
def allocation_preview(amount_tl: float, user_id: str = Depends(get_current_user_id)):
    """Ayarlar sekmesinde "aylık X TL girdim, bunu nasıl dağıtırsın" önizlemesi
    — AŞAMA 58 devamı. /allocate'ten FARKLI olarak bildirim GÖNDERMEZ, dedup'a
    dokunmaz; kullanıcı tutarı değiştirdikçe istediği kadar sorgulayabilir.
    Dağıtım mantığı (skora orantılı, en iyi 3 fon) /allocate ile birebir aynı
    — kullanıcı burada gördüğü önizlemeyle ayın başında gelecek gerçek
    bildirim arasında fark olmasın diye.
    """
    try:
        ranked = get_ranked_funds()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"amount_tl": amount_tl, "allocation": recommend_allocation(ranked, amount_tl)}


@router.get("/positions")
def list_positions(user_id: str = Depends(get_current_user_id)):
    positions = FundPositionRepository().list_for_user(user_id)
    try:
        ranked = get_ranked_funds()
        score_by_code = {f.fund_code: f for f in ranked}
    except ValueError:
        score_by_code = {}

    results = []
    for p in positions:
        current = score_by_code.get(p.fund_code)
        results.append(
            {
                "fund_code": p.fund_code,
                "units": p.units,
                "avg_cost": p.avg_cost,
                "current_price": current.price if current else None,
                "composite_score": current.composite_score if current else None,
                "current_value": round(p.units * current.price, 2) if current else None,
                "invested_amount": round(p.units * p.avg_cost, 2),
            }
        )
    return results


@router.post("/positions")
def create_position(payload: FundPositionCreate, user_id: str = Depends(get_current_user_id)):
    position = FundPosition(user_id=user_id, **payload.model_dump(), created_at=datetime.now(timezone.utc))
    position_id = FundPositionRepository().add(position)
    return {"id": position_id, **position.model_dump()}


@router.delete("/positions/{fund_code}")
def delete_position(fund_code: str, user_id: str = Depends(get_current_user_id)):
    FundPositionRepository().delete_for_fund(user_id, fund_code)
    return {"deleted_fund_code": fund_code}


@router.post("/allocate")
def allocate(payload: FundAllocateRequest, user_id: str = Depends(get_current_user_id)):
    """"Ekstra Para" butonu — AŞAMA 58. TEFAS'ta genel kullanıcılar için açık
    bir işlem-emri API'si olmadığından GERÇEK bir alım YAPILMAZ; bu uç nokta
    o anki en iyi fonlara göre bir dağıtım önerisi hesaplayıp hem anında
    yanıt olarak döner (Flutter ekranda göstersin) hem de aynı içerikle bir
    push bildirimi gönderir (kullanıcı isteği: "o an hangi fonlar alınacaksa
    onların bildirimini yollasın").
    """
    try:
        ranked = get_ranked_funds()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    allocation = recommend_allocation(ranked, payload.amount_tl)
    notify_ad_hoc_allocation(user_id, ranked, payload.amount_tl)
    return {"amount_tl": payload.amount_tl, "allocation": allocation}


# NOT: /funds/{code} ve /funds/{code}/news, dosyadaki tüm sabit-yol
# uç noktalarından (settings, positions, allocate vb.) SONRA tanımlanmalı —
# aksi halde FastAPI "settings"i bir fon kodu sanıp bu route'a düşürürdü.


@router.get("/{code}")
def get_fund(code: str):
    """Tek bir fonun tam analiz kaydı — arama sonucundan/listeden tıklanınca
    fon detay ekranı için (AŞAMA 60)."""
    try:
        ranked = get_ranked_funds()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    code = code.upper()
    for fund in ranked:
        if fund.fund_code == code:
            return fund
    raise HTTPException(status_code=404, detail=f"'{code}' bulunamadı (veri kalitesi filtresini geçmemiş olabilir)")


@router.get("/{code}/news")
def get_fund_news(code: str):
    """AŞAMA 60 — kullanıcı isteği: "ünlü borsa bilgileri paylaşan
    sayfalardan önerilerine bakıp bunu önerdiler ve şu yüzden gibi anlat."
    Google News RSS'te bu fonla ilgili GERÇEKTEN bulunan haber/yorum
    kaynaklarını listeler (bkz. GoogleNewsRssProvider, AŞAMA 55) — belirli bir
    hesabın/otoritenin bu fonu önerdiğini İDDİA ETMEZ, yalnızca gerçek makale
    başlıklarını/kaynaklarını olduğu gibi gösterir, yorumu kullanıcıya bırakır.
    """
    code = code.upper()
    fund_name = None
    try:
        ranked = get_ranked_funds()
        for fund in ranked:
            if fund.fund_code == code:
                fund_name = fund.fund_name
                break
    except ValueError:
        pass

    suffix = f"{fund_name} fon" if fund_name else "fon"
    items = GoogleNewsRssProvider().get_latest_news(code, limit=10, query_suffix=suffix)
    for item in items:
        item.analyst_firm = extract_analyst_firm(f"{item.title} {item.summary}")
    return items
