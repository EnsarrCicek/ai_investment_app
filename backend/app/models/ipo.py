from datetime import datetime

from pydantic import BaseModel, Field


class IpoListing(BaseModel):
    """halkarz.com anasayfasındaki bir halka arz kaydı — ham, olduğu gibi
    (bkz. services/ipo/halkarz_provider.py). Hiçbir alan yorumlanmaz/
    sınıflandırılmaz; tarih metni ve rozet metni SİTEDE GEÇTİĞİ GİBİ tutulur."""

    company_name: str
    bist_code: str | None = None
    detail_url: str
    date_text: str
    badge_text: str | None = None


class IpoDetail(BaseModel):
    """Bir halka arzın detay sayfasından çekilen GERÇEK bilgi tablosu —
    anahtarlar sitedeki Türkçe etiketlerin kendisi (ör. 'Halka Arz Fiyatı/Aralığı'),
    hiçbir alan uydurulmaz/hesaplanmaz."""

    company_name: str
    bist_code: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    demand_results: list[dict[str, str]] = Field(default_factory=list)
    fetched_at: datetime


class IpoNote(BaseModel):
    """Kullanıcının kendi gözlemini (ör. 'şu an bu kadar alış bu kadar satış
    var, bence satmalısın') serbest metin olarak kaydettiği, KALICI ve
    değiştirilemez bir not — AI tarafından üretilmez, yalnızca saklanır."""

    id: str | None = None
    user_id: str
    company_name: str
    bist_code: str | None = None
    note_text: str
    created_at: datetime
