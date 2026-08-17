"""RiskEngine — ana doküman bölüm 44.

Kapsam kararı: Bölüm 44'te listelenen risklerden (volatilite, maximum drawdown,
likidite, gap riski, haber yoğunluğu, sektör riski, piyasa riski, korelasyon,
portföy konsantrasyonu) bu sürümde **sektör riski ve haber yoğunluğu hariç
hepsi** uygulanıyor:
- Sektör riski: ayrı bir veri modeline (sektör sınıflandırması) ihtiyaç duyuyor
  — `Asset` modelinde böyle bir alan yok ve fabrikasyon veri kullanmak yerine
  bilinçli olarak ertelendi (ana doküman kural 11-12: yalnız gerçek/izlenebilir
  veri).
- Haber yoğunluğu: EventIntelligenceEngine'e (LLM, henüz yok) bağlı.

Piyasa riski (beta) ve korelasyon, Yahoo Finance'ten zaten kullanılan aynı
mekanizmayla (BistProvider) hesaplanıyor — BIST 100 endeksi için gerçek Yahoo
ticker'ı olan "XU100" (`BistProvider` bunu "XU100.IS" olarak sorgular).
"""

import pandas as pd

from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

TRADING_DAYS_PER_YEAR = 252
DEFAULT_BENCHMARK = "XU100"


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

    def asset_liquidity(self, symbol: str, quantity: float, period: str = "3mo") -> dict:
        """quantity: elde tutulan/tutulacak adet. days_to_liquidate: ortalama günlük
        hacme göre bu pozisyonu satmanın kaç gün süreceğinin kaba tahmini — yüksek
        değer = düşük likidite riski.
        """
        df = self._provider.get_history(symbol, period=period)
        volume = df["Volume"].dropna()

        if volume.empty or volume.mean() == 0:
            raise ValueError(f"'{symbol}' için likidite hesaplamaya yetecek hacim verisi yok")

        avg_daily_volume = float(volume.mean())
        return {
            "asset": symbol,
            "avg_daily_volume": round(avg_daily_volume, 2),
            "position_quantity": quantity,
            "days_to_liquidate": round(quantity / avg_daily_volume, 4),
            "period": period,
        }

    def gap_risk(self, symbol: str, period: str = "6mo") -> dict:
        """Bir önceki kapanışla o günkü açılış arasındaki farkın (gece/hafta sonu
        haberlerine karşı korunmasızlığın) büyüklüğü.
        """
        df = self._provider.get_history(symbol, period=period)
        prev_close = df["Close"].shift(1)
        gaps_pct = ((df["Open"] - prev_close) / prev_close * 100).dropna()

        if gaps_pct.empty:
            raise ValueError(f"'{symbol}' için gap riski hesaplamaya yetecek veri yok")

        return {
            "asset": symbol,
            "max_gap_pct": round(float(gaps_pct.abs().max()), 2),
            "avg_abs_gap_pct": round(float(gaps_pct.abs().mean()), 2),
            "period": period,
        }

    def market_risk(self, symbol: str, benchmark: str = DEFAULT_BENCHMARK, period: str = "6mo") -> dict:
        """Beta: varlığın piyasa (BIST 100) hareketlerine duyarlılığı. Beta>1 piyasadan
        daha oynak, Beta<1 daha az oynak, negatif beta piyasayla ters yönlü demektir.
        """
        asset_returns = self._provider.get_history(symbol, period=period)["Close"].pct_change().dropna()
        benchmark_returns = self._provider.get_history(benchmark, period=period)["Close"].pct_change().dropna()

        aligned = pd.concat([asset_returns, benchmark_returns], axis=1, join="inner")
        aligned.columns = ["asset", "benchmark"]

        if len(aligned) < 2:
            raise ValueError(f"'{symbol}' için piyasa riski hesaplamaya yetecek örtüşen veri yok")

        variance = aligned["benchmark"].var()
        beta = float(aligned["asset"].cov(aligned["benchmark"]) / variance) if variance else 0.0

        return {
            "asset": symbol,
            "benchmark": benchmark,
            "beta": round(beta, 4),
            "correlation_with_market": round(float(aligned["asset"].corr(aligned["benchmark"])), 4),
            "period": period,
        }

    def portfolio_correlation(self, symbols: list[str], period: str = "6mo") -> dict:
        """Portföydeki varlıkların birbirine göre eş hareket etme derecesi. Yüksek
        ortalama korelasyon = düşük çeşitlendirme (hepsi aynı anda düşebilir).
        """
        unique_symbols = sorted(set(symbols))
        if len(unique_symbols) < 2:
            raise ValueError("Korelasyon hesaplamak için portföyde en az 2 farklı varlık gerekir")

        returns = {
            symbol: self._provider.get_history(symbol, period=period)["Close"].pct_change().dropna()
            for symbol in unique_symbols
        }
        returns_df = pd.DataFrame(returns).dropna()
        if len(returns_df) < 2:
            raise ValueError("Varlıkların örtüşen geçmiş verisi korelasyon hesaplamaya yetmiyor")

        corr_matrix = returns_df.corr()
        pairwise = [
            corr_matrix.loc[a, b]
            for i, a in enumerate(unique_symbols)
            for b in unique_symbols[i + 1 :]
        ]

        return {
            "assets": unique_symbols,
            "correlation_matrix": {
                a: {b: round(float(corr_matrix.loc[a, b]), 4) for b in unique_symbols} for a in unique_symbols
            },
            "average_correlation": round(float(sum(pairwise) / len(pairwise)), 4),
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
