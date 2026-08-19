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
