"""TechnicalAnalysisEngine — ana doküman bölüm 5.

Kapsam notu: İlk sürümde RSI, MACD, EMA trend (kesişim), Bollinger Bands,
Momentum ve ROC göstergeleri TechnicalScore'a doğrudan katkı sağlar; ATR
volatilite normalizasyonu için, Volume/Volume SMA ise yön değil "doğrulama"
(confidence) amacıyla kullanılır. ADX, Stochastic RSI, Support/Resistance,
ayrı bir "Trend Strength" metriği ve Relative Strength bu ilk sürümde
YOKTUR — ana doküman bölüm 5 bunları "ilk etapta desteklenebilecek"
göstergeler olarak listeliyor (zorunlu değil); bilinçli olarak sonraki bir
iyileştirmeye bırakılmıştır (bkz. KURULUM_GUNLUGU.md).

Performans (AŞAMA 44): analyze_with_id() her çağrıldığında yfinance'e taze
bir istek atardı — Dashboard tüm BIST100'ü (100 sembol) her açılışta yeniden
hesaplıyordu, bu da ~60-80 saniyelik yükleme süresine yol açıyordu. Şimdi
macro/news ile aynı ilke uygulanıyor: TECHNICAL_CACHE_TTL_SECONDS'tan daha
taze bir TechnicalAnalysis zaten Firestore'da varsa, yfinance'e HİÇ
gidilmeden o kayıt döner. BIST günlük bar kullandığından (gün içi anlık
tick değil), birkaç dakikalık bir gecikme kararın doğruluğunu etkilemez.
"""

from datetime import datetime, timezone

from app.engines.technical import indicators as ind
from app.models.technical_analysis import TechnicalAnalysis
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

ENGINE_VERSION = "1.0.0"

DEFAULT_WEIGHTS = {
    "rsi": 0.1667,
    "macd": 0.1667,
    "trend": 0.1667,
    "bollinger": 0.1667,
    "momentum": 0.1667,
    "roc": 0.1665,
}

MIN_HISTORY_DAYS = 60
TECHNICAL_CACHE_TTL_SECONDS = 900  # 15 dakika


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class TechnicalAnalysisEngine:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
        analysis_repo: TechnicalAnalysisRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()
        self._analysis_repo = analysis_repo or TechnicalAnalysisRepository()

    def analyze(self, symbol: str, persist: bool = True) -> TechnicalAnalysis:
        analysis, _doc_id = self.analyze_with_id(symbol, persist=persist)
        return analysis

    def analyze_with_id(
        self, symbol: str, persist: bool = True, max_age_seconds: int = TECHNICAL_CACHE_TTL_SECONDS
    ) -> tuple[TechnicalAnalysis, str | None]:
        cached, cached_id = self._analysis_repo.get_latest_with_id(symbol)
        if cached is not None:
            age = (datetime.now(timezone.utc) - cached.created_at).total_seconds()
            if age < max_age_seconds:
                return cached, cached_id

        df = self._provider.get_history(symbol, period="6mo")
        if len(df) < MIN_HISTORY_DAYS:
            raise ValueError(
                f"'{symbol}' için yeterli geçmiş veri yok ({len(df)} gün, en az {MIN_HISTORY_DAYS} gerekli)"
            )

        weights = self._config_repo.get("technical_indicator_weights", DEFAULT_WEIGHTS)

        close, volume = df["Close"], df["Volume"]

        rsi_val = float(ind.rsi(close).iloc[-1])
        _, _, macd_hist = ind.macd(close)
        macd_hist_val = float(macd_hist.iloc[-1])
        ema_short_val = float(ind.ema(close, 20).iloc[-1])
        ema_long_val = float(ind.ema(close, 50).iloc[-1])
        upper, middle, lower = ind.bollinger_bands(close)
        upper_val, middle_val, lower_val = float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])
        atr_val = float(ind.atr(df).iloc[-1])
        momentum_val = float(ind.momentum(close).iloc[-1])
        roc_val = float(ind.roc(close).iloc[-1])
        volume_sma_val = float(ind.volume_sma(volume).iloc[-1])
        current_volume = float(volume.iloc[-1])
        close_val = float(close.iloc[-1])

        band_width = upper_val - middle_val

        components = {
            "rsi": _clamp((rsi_val - 50) * 2),
            "macd": _clamp((macd_hist_val / atr_val) * 25) if atr_val else 0.0,
            "trend": _clamp(((ema_short_val - ema_long_val) / ema_long_val) * 1000) if ema_long_val else 0.0,
            "bollinger": _clamp(((close_val - middle_val) / band_width) * 100) if band_width else 0.0,
            "momentum": _clamp((momentum_val / atr_val) * 20) if atr_val else 0.0,
            "roc": _clamp(roc_val * 8),
        }

        final_score = round(
            _clamp(sum(components[k] * weights.get(k, 0.0) for k in components)), 2
        )

        agreement = sum(
            1 for s in components.values() if (s >= 0) == (final_score >= 0)
        ) / len(components)
        volume_confirmation = min(current_volume / volume_sma_val, 2.0) / 2.0 if volume_sma_val else 0.5
        confidence = round(_clamp(0.4 + 0.4 * agreement + 0.2 * volume_confirmation, 0.0, 1.0), 2)

        trend = "BULLISH" if final_score > 15 else "BEARISH" if final_score < -15 else "NEUTRAL"

        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=final_score,
            trend=trend,
            confidence=confidence,
            components=components,
            indicators={
                "rsi": round(rsi_val, 2),
                "macd_histogram": round(macd_hist_val, 4),
                "ema_20": round(ema_short_val, 2),
                "ema_50": round(ema_long_val, 2),
                "bollinger_upper": round(upper_val, 2),
                "bollinger_middle": round(middle_val, 2),
                "bollinger_lower": round(lower_val, 2),
                "atr": round(atr_val, 4),
                "momentum": round(momentum_val, 4),
                "roc": round(roc_val, 4),
                "volume": int(current_volume),
                "volume_sma": round(volume_sma_val, 2),
            },
            created_at=datetime.now(timezone.utc),
            engine_version=ENGINE_VERSION,
        )

        doc_id = self._analysis_repo.add(analysis) if persist else None
        return analysis, doc_id
