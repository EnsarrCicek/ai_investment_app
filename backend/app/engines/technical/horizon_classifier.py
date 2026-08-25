"""Yatırım vadesi sınıflandırması — kullanıcı isteği "hangi hisseyi uzun
süreli alıyoruz hangi hisseyi kısa süreli alıyoruz bunu belirt" (25.08.2026).

`signal_classifier.py` ile aynı ilke: TechnicalAnalysisEngine'in zaten
hesapladığı yapısal alanlardan (market_structure, trend_regime,
relative_strength_class, mtf_aligned/mtf_consensus, signal_class) saf,
LLM'siz bir etiket üretir — skoru DEĞİŞTİRMEZ, yalnızca "bu sinyal kısa
vadeli bir fırsat mı yoksa yapısal/uzun vadeli bir trend mi" sorusuna kural
tabanlı bir cevap ekler. Bilinçli olarak haber/makro KARIŞTIRILMAZ — haberin
kendi `time_horizon` etiketi zaten Haberler sekmesinde ayrı gösteriliyor,
ikisini birleştirmek yanlış bir kesinlik hissi verir.
"""

from dataclasses import dataclass

UZUN_VADELI = "UZUN_VADELI"
ORTA_VADELI = "ORTA_VADELI"
KISA_VADELI = "KISA_VADELI"
BELIRSIZ = "BELIRSIZ"

_BULLISH_SIGNALS = {"STRONG_BULLISH_INITIATION", "BULLISH_CONFIRMED", "BULLISH_CANDIDATE"}
_BEARISH_SIGNALS = {"BEARISH_CANDIDATE"}


@dataclass
class HorizonInputs:
    signal_class: str
    market_structure: str = "UNKNOWN"  # UPTREND/DOWNTREND/RANGE/UNKNOWN
    trend_regime: str = "UNKNOWN"  # TRENDING/CHOPPY/UNKNOWN
    relative_strength_class: str = "UNKNOWN"  # OUTPERFORMING/UNDERPERFORMING/IN_LINE/UNKNOWN
    mtf_aligned: bool = False
    mtf_consensus: str = "UNKNOWN"  # UP/DOWN/CONFLICTING/UNKNOWN


def classify_horizon(inputs: HorizonInputs) -> str:
    bullish = inputs.market_structure == "UPTREND" or inputs.signal_class in _BULLISH_SIGNALS
    bearish = inputs.market_structure == "DOWNTREND" or inputs.signal_class in _BEARISH_SIGNALS

    if inputs.signal_class == "STRONG_BULLISH_INITIATION":
        return KISA_VADELI

    if not bullish and not bearish:
        return BELIRSIZ

    expected_consensus = "UP" if bullish else "DOWN"
    full_confirmation = (
        inputs.mtf_aligned
        and inputs.mtf_consensus == expected_consensus
        and inputs.trend_regime == "TRENDING"
        and inputs.relative_strength_class == ("OUTPERFORMING" if bullish else "UNDERPERFORMING")
    )
    if full_confirmation:
        return UZUN_VADELI

    partial_confirmation = inputs.mtf_consensus == expected_consensus or inputs.trend_regime == "TRENDING"
    if partial_confirmation:
        return ORTA_VADELI

    return KISA_VADELI


def horizon_reason(label: str, inputs: HorizonInputs) -> str:
    if label == UZUN_VADELI:
        return (
            "Günlük ve haftalık zaman dilimi aynı yönde uyumlu, fiyat hareketi verimli/gürültüsüz "
            "bir trend içinde ve endeksten belirgin şekilde ayrışıyor — yapısal, uzun vadeli bir görünüm."
        )
    if label == ORTA_VADELI:
        return (
            "Yön net ama teyit kısmi — ya zaman dilimleri arasında tam uyum ya da güçlü/verimli bir trend "
            "var, ikisi birden değil. Orta vadeli bir görünüm, pozisyon büyüklüğü buna göre ayarlanmalı."
        )
    if label == KISA_VADELI and inputs.signal_class == "STRONG_BULLISH_INITIATION":
        return (
            "Taze bir kırılım/momentum girişi — henüz haftalık trendde veya göreli güçte kalıcı bir teyit "
            "oluşmadı, retest ve teyit süreci kısa vadede belirleyici olacak."
        )
    if label == KISA_VADELI:
        return (
            "Yalnızca teknik skor yön veriyor; yapısal teyit (zaman dilimi uyumu, verimli trend, göreli güç) "
            "henüz yok — kısa vadeli/taktiksel bir sinyal olarak değerlendirilmeli."
        )
    return "Nötr bir sinyal — anlamlı bir vade önerisi için yeterli yön/teyit yok."
