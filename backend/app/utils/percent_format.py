"""HATA 5C-UI4 (31.08.2026): backend-generated user-facing yüzde string'leri
(ör. `ExplanationEngine` summary, FCM bildirim body'si) Flutter'ın kendi
`toStringAsFixed(0)` davranışıyla AYNI half-up rounding'i kullansın diye --
Python'un `f"{value:.0f}"` / built-in `round()` varsayılanı ROUND-HALF-TO-
-EVEN'dır (62.5 -> "62"), Flutter/Dart'ın `toStringAsFixed(0)`'ı ise ROUND-
-HALF-AWAY-FROM-ZERO'dur (62.5 -> "63") -- aynı sayı iki platformda farklı
görünüyordu (audit: HATA 5C-UI3 raporu). `Decimal(str(value))` kullanımı,
`value * 100` gibi ondalık aritmetiğin ürettiği binary floating-point
sürprizlerini (ör. `0.005*100` ideal olarak 0.5 olsa da bazı girdilerde
`0.49999999999999994` çıkabilir) quantize ÖNCESİ ondalık string temsiline
dönerek azaltır.

Bu modül yalnızca PRESENTATION (ekranda/bildirimde gösterilen string)
katmanıdır -- `AIDecision.confidence`/`channel_completeness` gibi STORED/
CALCULATED değerleri HİÇBİR ŞEKİLDE değiştirmez veya yeniden yuvarlamaz.
"""

from decimal import ROUND_HALF_UP, Decimal


def _round_half_up_to_int(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_percent_value(value_0_to_100: float) -> str:
    """Zaten 0..100 skalasındaki bir değeri (ör. `AIDecision.confidence`,
    "Sinyal Mutabakatı") ×100 YAPMADAN yüzde string'ine çevirir."""
    return f"%{_round_half_up_to_int(value_0_to_100)}"


def format_percent_fraction(value_0_to_1: float) -> str:
    """0..1 skalasındaki bir değeri (ör. `channel_completeness`,
    `evidence_coverage`, "Veri Kapsamı") ×100 YAPARAK yüzde string'ine
    çevirir."""
    return format_percent_value(value_0_to_1 * 100)
