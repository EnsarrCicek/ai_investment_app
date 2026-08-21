from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.models.ipo import IpoNote
from app.repositories.ipo_note_repository import IpoNoteRepository
from app.schemas.ipo import IpoNoteCreate
from app.services.ipo.cache_service import get_ipo_detail, get_ipo_listings
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider

router = APIRouter(prefix="/ipo", tags=["ipo"])

# AŞAMA 67: "notes" ve "detail" statik yollar, {symbol} tarzı bir catch-all
# YOK bu router'da ama ileride eklenirse route-order kuralı (bkz. AŞAMA 60/62)
# hatırlanmalı — bu yüzden statik yollar dosyanın başında tanımlanır.


@router.get("")
def list_ipos():
    """halkarz.com'dan GERÇEK, güncel halka arz takvimini döner — kesin bir
    'gir/girme' tavsiyesi ÜRETİLMEZ, karar kullanıcıya bırakılır."""
    try:
        return get_ipo_listings()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Halka arz takvimi alınamadı: {exc}")


@router.get("/detail")
def get_ipo_detail_endpoint(url: str):
    try:
        detail = get_ipo_detail(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Halka arz detayı alınamadı: {exc}")
    if detail is None:
        raise HTTPException(status_code=404, detail="Halka arz detayı bulunamadı")
    return detail


@router.get("/news")
def get_ipo_news(company: str, limit: int = 10):
    """Bu şirketin halka arzıyla ilgili GERÇEK haber/yorum kaynaklarını
    listeler — henüz borsa kodu almamış şirketler için de çalışır (arama
    şirket ADIYLA yapılır, bkz. GoogleNewsRssProvider)."""
    return GoogleNewsRssProvider().get_latest_news(company, limit=limit, query_suffix="halka arz")


@router.post("/notes")
def create_ipo_note(payload: IpoNoteCreate, user_id: str = Depends(get_current_user_id)):
    note = IpoNote(
        user_id=user_id,
        company_name=payload.company_name,
        bist_code=payload.bist_code,
        note_text=payload.note_text,
        created_at=datetime.now(timezone.utc),
    )
    repo = IpoNoteRepository()
    note_id = repo.add(note)
    note.id = note_id
    return note


@router.get("/notes")
def list_ipo_notes(company_name: str | None = None, user_id: str = Depends(get_current_user_id)):
    return IpoNoteRepository().list_for_user(user_id, company_name=company_name)


@router.delete("/notes/{note_id}")
def delete_ipo_note(note_id: str, user_id: str = Depends(get_current_user_id)):
    deleted = IpoNoteRepository().delete(user_id, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not bulunamadı")
    return {"deleted": True}
