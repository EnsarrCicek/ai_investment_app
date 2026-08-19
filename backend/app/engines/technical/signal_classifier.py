"""Sinyal sınıfı taksonomisi — TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7
adım 12.

TechnicalAnalysisEngine'in ürettiği tek bir sayısal `technical_score` ve
DecisionEngine'in ürettiği AL/ZAYIF AL/TUT/ZAYIF SAT/SAT kararı DEĞİŞMİYOR —
bu modül, market_structure/breakout/relative_volume/relative_strength/
multi_timeframe modüllerinin çıktısını birleştirip AYRI, daha ZENGİN bir
sınıflandırma katmanı üretir (dokümanın önerdiği 7 sınıflı taksonomi). Amaç:
"AL" kararının ARDINDAKİ durumu ayırt etmek — ör. güçlü bir kırılımla mı
geldi (STRONG_BULLISH_INITIATION), yoksa zaten devam eden bir trendin teyidi
mi (BULLISH_CONFIRMED)?

Sınıflar, öncelik sırasına göre (en talepkâr olan önce) kontrol edilir:
STRONG_BULLISH_INITIATION > BULLISH_CONFIRMED > BULLISH_CANDIDATE >
BEARISH_CANDIDATE > NO_SIGNAL > WATCHLIST > NEUTRAL (varsayılan).

Bu, henüz TechnicalAnalysisEngine/DecisionEngine'e bağlanmadı — bağımsız,
girdilerini açıkça alan saf bir fonksiyon; entegrasyon ayrı bir aşamada
backtest ile doğrulanarak yapılacak (bkz. KURULUM_GUNLUGU.md).
"""

from dataclasses import dataclass

from app.engines.technical.breakout import BreakoutEvent


@dataclass
class SignalInputs:
    technical_score: float
    market_structure: str = "UNKNOWN"  # "UPTREND" / "DOWNTREND" / "RANGE" / "UNKNOWN"
    breakout_event: BreakoutEvent | None = None
    relative_volume_class: str = "UNKNOWN"  # LOW/NORMAL/HIGH/VERY_HIGH/UNKNOWN
    relative_strength_class: str = "UNKNOWN"  # OUTPERFORMING/UNDERPERFORMING/IN_LINE/UNKNOWN
    mtf_aligned: bool = False
    mtf_consensus: str = "UNKNOWN"


def classify_signal(inputs: SignalInputs) -> str:
    score = inputs.technical_score
    structure = inputs.market_structure
    breakout = inputs.breakout_event
    high_volume = inputs.relative_volume_class in ("HIGH", "VERY_HIGH")

    breakout_confirmed = bool(breakout and breakout.confirmed is True)
    breakout_not_broken = bool(breakout and breakout.retest_held is not False)
    mtf_bullish = inputs.mtf_aligned and inputs.mtf_consensus == "UP"

    if (
        score >= 40
        and structure == "UPTREND"
        and breakout_confirmed
        and breakout_not_broken
        and high_volume
        and mtf_bullish
    ):
        return "STRONG_BULLISH_INITIATION"

    if score >= 15 and structure == "UPTREND" and (breakout is None or breakout_confirmed):
        return "BULLISH_CONFIRMED"

    if score >= 15:
        return "BULLISH_CANDIDATE"

    if score <= -15:
        return "BEARISH_CANDIDATE"

    all_unknown = (
        structure == "UNKNOWN"
        and inputs.relative_volume_class == "UNKNOWN"
        and inputs.relative_strength_class == "UNKNOWN"
    )
    if all_unknown:
        return "NO_SIGNAL"

    if 0 < score < 15 and structure == "UPTREND":
        return "WATCHLIST"

    if -15 < score <= 0 and structure == "DOWNTREND":
        return "WATCHLIST"

    return "NEUTRAL"
