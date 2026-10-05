from datetime import datetime

from pydantic import BaseModel


class MarketData(BaseModel):
    asset_id: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    # Fiyatın geldiği AYNI sağlayıcı yanıtının meta bilgisinden (ek istek yok); eksikte None/UNVERIFIED.
    currency: str | None = None
    exchange: str | None = None
    identity_check: str | None = None  # MATCH | UNVERIFIED (uyuşmazlıkta veri üretilmez)
    # Fiyat temeli beyanı (sağlayıcının belgelediği); bilinmiyorsa None. Maliyetle karşılaştırılabilirlik iddiası DEĞİL.
    price_basis: str | None = None


class Quote(BaseModel):
    """Anlık fiyat özeti. `timestamp`, verinin gerçekte hangi ana ait olduğunu
    gösterir — sağlayıcı (Yahoo Finance) hafif gecikmeli olabilir, bu asla
    gizlenmez (bkz. BistProvider.get_quote)."""

    asset_id: str
    # Mevcut anlam KORUNUR: sağlayıcı barının indeks zamanı = bar BAŞLANGICI (gün içi 5 dk bar veya günlük bar
    # tarihi). Son işlem zamanı DEĞİLDİR.
    timestamp: datetime
    last_price: float
    previous_close: float
    change: float
    change_percent: float | None
    open: float
    high: float
    low: float
    volume: int
    source: str
    # Geriye uyumlu ek alanlar (eski kayıtlarda/sahte sağlayıcılarda None):
    price_type: str | None = None  # INTRADAY_BAR_CLOSE | DAILY_BAR_CLOSE
    bar_start: datetime | None = None
    interval: str | None = None  # "5m" | "1d"
    retrieved_at: datetime | None = None  # sağlayıcı yanıtının alındığı an (UTC, saat dilimli)
    currency: str | None = None  # sağlayıcının bildirdiği; yoksa None (varsayılan yazılmaz)
    exchange: str | None = None
    identity_check: str | None = None  # MATCH | UNVERIFIED (uyuşmazlıkta quote üretilmez)
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    last_trade_at: datetime | None = None  # yalnız aynı yanıtta aynı fiyatla ve bar içinde doğrulanırsa
