from datetime import datetime

from pydantic import BaseModel


class PortfolioPosition(BaseModel):
    user_id: str
    asset: str
    buy_price: float
    buy_date: datetime
    quantity: float
    created_at: datetime
    # Kayıtlı `buy_price` değerinin para birimi (ISO 4217). Eski kayıtlarda yok/None = BİLİNMİYOR;
    # TRY varsayılmaz. Güncel piyasa fiyatının para birimiyle (pnl yanıtındaki current_price_currency) karıştırılmaz.
    currency: str | None = None


def merged_currency(lots: list[PortfolioPosition]) -> str | None:
    """Birleşik pozisyonun para birimi: tüm lotlarda bilinen ve AYNI ise o; herhangi biri eksik/farklıysa None."""
    currencies = {lot.currency for lot in lots}
    return currencies.pop() if len(currencies) == 1 and None not in currencies else None
