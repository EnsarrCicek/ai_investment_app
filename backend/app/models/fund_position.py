from datetime import datetime

from pydantic import BaseModel


class FundPosition(BaseModel):
    """Kullanıcının elinde tuttuğu bir fon — AŞAMA 58. portfolio_position.py
    ile aynı prensip (kullanıcı verisi, immutable DEĞİL) ama daha basit: fon
    alım-satımı hisse gibi anlık değil, TEFAS'ta ertesi gün fiyatıyla
    gerçekleşir — bu yüzden gerçekleşmiş kâr/zarar defteri (PortfolioTransaction
    dengi) v1'de YOK, yalnızca "hangi fonu ne kadar tutuyorum" izlenir.
    """

    user_id: str
    fund_code: str
    units: float
    avg_cost: float
    created_at: datetime
