"""TEFAS (Türkiye Elektronik Fon Alım Satım Platformu) veri sağlayıcısı.

2026'da TEFAS'ın Next.js tabanlı yeni sitesiyle birlikte gelen, kimlik
doğrulama gerektirmeyen resmi JSON API'sini kullanan `pytefas` kütüphanesini
sarmalar (bkz. KURULUM_GUNLUGU.md AŞAMA 58 — eski `/api/DB/BindHistoryInfo`
uç noktası artık devre dışı, siteyi tarayıcı gibi çekmek F5 bot koruması
tarafından engelleniyor; `pytefas`'ın kullandığı `/api/funds/...` uç noktaları
ise doğrudan erişilebilir ve resmi).

TEFAS dakikada 6 istek sınırı uyguluyor — `pytefas.Crawler` bunu kendi içinde
yönetiyor (otomatik retry/bekleme). Bu yüzden çağıran kod (FundSnapshotRepository)
her tarihi Firestore'da KALICI olarak önbelleğe alır — aynı tarih iki kez
gerçekten TEFAS'a sorulmaz.
"""

import pandas as pd
from pytefas import Crawler

DEFAULT_KIND = "YAT"


class TefasProvider:
    def __init__(self, crawler: Crawler | None = None):
        self._crawler = crawler or Crawler()

    def get_snapshot(self, date: str, kind: str = DEFAULT_KIND) -> list[dict]:
        """Tek bir tarih için TÜM fonların (kind'a göre) fiyat/büyüklük anlık
        görüntüsünü döner. Boş liste = o tarihte veri yok (hafta sonu, resmi
        tatil ya da henüz yayınlanmamış gün) — GERÇEK bir hata değildir.
        """
        df = self._crawler.fetch(date, columns="info", kind=kind)
        if df.empty:
            return []
        return df[["fund_code", "fund_name", "price", "investor_count", "portfolio_size"]].to_dict(
            orient="records"
        )

    def get_fund_history(self, fund_code: str, start: str, end: str, kind: str = DEFAULT_KIND) -> pd.DataFrame:
        """Tek bir fonun tarih aralığındaki fiyat geçmişi — fon detay grafiği için."""
        df = self._crawler.fetch(start, end, kind=kind, fund_code=fund_code)
        if df.empty:
            return df
        return df[["date", "price"]].sort_values("date")
