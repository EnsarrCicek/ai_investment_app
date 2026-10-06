from datetime import datetime

from pydantic import BaseModel


class PortfolioTransaction(BaseModel):
    """Bir pozisyonun kapatılması (satış) kaydı.

    ai_decisions/news_analyses ile aynı ilke: immutable — bir kez
    gerçekleştikten sonra bu kayıt asla değiştirilmez/silinmez. Portföy
    pozisyonlarının (PortfolioPosition) aksine bu, "ne olduğunun" kalıcı
    kaydıdır; kullanıcı geçmişini düzenleyemez.
    """

    user_id: str
    asset: str
    quantity: float
    buy_price: float
    buy_date: datetime
    sell_price: float
    sell_date: datetime
    realized_pnl: float
    realized_pnl_percent: float
    created_at: datetime
    immutable: bool = True
    # Pozisyonun kayıtlı para birimi taşınır; pozisyonda yoksa None (eski işlemler de None). TRY varsayılmaz.
    currency: str | None = None
    # Satış defteri alanları (bkz. app/services/portfolio/sale_ledger.py). Eski kayıtlarda None.
    # `quantity` = satılan adet; `buy_price` = satış anındaki ağırlıklı ortalama maliyet (float gösterim).
    # Kesin değerler Decimal metni olarak saklanır (float sapması yok).
    disposal_method: str | None = None  # WEIGHTED_AVERAGE
    average_cost_at_sale: str | None = None
    disposed_cost_basis: str | None = None
    sale_proceeds: str | None = None
    realized_pnl_exact: str | None = None
    remaining_quantity: str | None = None
    remaining_cost_basis: str | None = None
    position_version_before: str | None = None
    # False = gerçekleşen K/Z, adet/maliyet tabanı kurumsal işlemler açısından doğrulanmadan hesaplandı.
    basis_verified: bool | None = None
    # Satış anındaki lot kimlikleri; satış yalnız bu lotların tamamı hâlâ mevcutsa pozisyona uygulanır.
    ledger_lot_ids: list[str] | None = None
