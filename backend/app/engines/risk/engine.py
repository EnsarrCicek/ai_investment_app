"""RiskEngine — ana doküman bölüm 44.

Kapsam kararı: Bölüm 44'te listelenen risklerden (volatilite, maximum drawdown,
likidite, gap riski, haber yoğunluğu, sektör riski, piyasa riski, korelasyon,
portföy konsantrasyonu) bu ilk sürümde yalnızca **volatilite, maximum drawdown
ve portföy konsantrasyonu** uygulanıyor — bunlar mevcut market_data/portfolio
verisinden doğrudan, LLM'siz hesaplanabiliyor. Haber yoğunluğu EventIntelligence-
Engine'e (LLM, henüz yok), korelasyon ve sektör riski ise ayrı bir veri
modeline (sektör sınıflandırması, çoklu varlık zaman serisi hizalaması)
ihtiyaç duyduğu için bilinçli olarak sonraki bir iyileştirmeye bırakıldı.
"""

from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

TRADING_DAYS_PER_YEAR = 252


class RiskEngine:
    def __init__(self, provider: MarketDataProvider | None = None):
        self._provider = provider or BistProvider()

    def asset_risk(self, symbol: str, period: str = "6mo") -> dict:
        df = self._provider.get_history(symbol, period=period)
        close = df["Close"]
        returns = close.pct_change().dropna()

        if returns.empty:
            raise ValueError(f"'{symbol}' için risk hesaplamaya yetecek veri yok")

        volatility_annualized_pct = float(returns.std() * (TRADING_DAYS_PER_YEAR**0.5) * 100)

        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown_pct = float(drawdown.min() * 100)

        return {
            "asset": symbol,
            "volatility_annualized_pct": round(volatility_annualized_pct, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "period": period,
        }

    def portfolio_concentration(self, position_values: dict[str, float]) -> dict:
        """position_values: {asset: current_value}. Herfindahl-Hirschman Index (0-1, 1=tek varlık)."""
        total = sum(position_values.values())
        if total <= 0:
            return {"herfindahl_index": 0.0, "weights_pct": {}}

        weights_pct = {asset: round(value / total * 100, 2) for asset, value in position_values.items()}
        hhi = round(sum((w / 100) ** 2 for w in weights_pct.values()), 4)

        return {"herfindahl_index": hhi, "weights_pct": weights_pct}
