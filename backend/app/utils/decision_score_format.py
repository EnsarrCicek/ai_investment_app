"""HATA 18B: `AIDecision.final_score`'un threshold-safe, adaptive-hassasiyetli
insan-okunur sunumu.

Kilitli kural (HATA 18A bulgu #1'in düzeltmesi): gösterilen string, HİÇBİR
ZAMAN persisted `decision` etiketinden FARKLI bir sınıflandırma katmanına
işaret ETMEMELİDİR. Örnek: final_score=39.996 (bilimsel olarak WEAK_BUY,
BUY eşiği 40.0'ın ALTINDA) eski `:+.1f` formatıyla "+40.0" gösteriyordu --
bu, BUY eşiğini geçmiş gibi GÖRÜNÜYORDU (bkz. HATA 18A raporu).

Sabit 2/3 ondalık YERİNE (bir skor her zaman herhangi bir sabit hassasiyette
bile eşiğe yeterince yakın olabilir): 1 ondalıktan başlayıp, gösterilecek
string'i DecisionEngine'in TEK, gerçek sınıflandırma mantığıyla
(`_classify()` -- burada İKİNCİ KEZ YAZILMAZ, doğrudan import edilir)
yeniden sınıflandırarak persisted `decision` ile eşleşene kadar hassasiyeti
artırır. Sınırlı deneme dizisi tükenirse (patolojik durum), `final_score`'un
TAM, round-trip-safe temsiline (`repr()`) düşer -- bu değer, `decision`'ı
ÜRETEN değerin ta kendisi olduğundan, sınıflandırması TANIM GEREĞİ eşleşir
(epsilon/tolerans hack'i YOK).

Eşikler DAİMA persisted `AIDecision.decision_thresholds` (HATA 17D) snapshot'ından
gelir -- canlı `SystemConfigRepository`'den ASLA okunmaz (zaten hesaplanmış bir
kararın sunumu, sonradan değişen config'ten ETKİLENMEMELİ). Eski (17D-öncesi)
kayıtlarda `decision_thresholds=None` -- bu durumda GÜNCEL eşikler UYDURULMAZ,
doğrudan `final_score`'un round-trip-safe temsili gösterilir.

`ExplanationEngine` ve `fcm_sender.py` YALNIZCA bu fonksiyonu kullanır --
ikisinin de kendi başına `:+.1f` (veya başka sabit hassasiyetli) formatlaması
YOKTUR (bkz. HATA 18A bulgu #1, HATA 18B raporu).

NOT: Bu modül yalnızca PRESENTATION (ekranda/bildirimde gösterilen string)
katmanıdır -- `AIDecision.final_score`'un kendisini (API serialization dahil)
HİÇBİR ŞEKİLDE değiştirmez veya yeniden yuvarlamaz (bkz. `percent_format.py`
ile aynı ilke).
"""

from app.engines.decision.engine import _classify

# Sınırlı deneme dizisi: bu domain'deki skorlar (ağırlıklı ortalamalar,
# tipik olarak birkaç ondalıklı ağırlık/skor çarpımlarından türer) makul bir
# sınırlı hassasiyette her zaman ayrışır; yine de bir üst sınır olmadan
# sonsuz döngü riskine girmemek için sınırlı, ardından TAM repr() fallback'i
# kullanılır (bkz. modül docstring'i).
_MAX_ADAPTIVE_DECIMALS = 6


def _normalize_negative_zero(text: str) -> str:
    """"-0.0"/"-0.00" gibi kozmetik negatif-sıfır gösterimini "+0.0..."'a
    çevirir -- bilimsel işaret (final_score'un kendisi) HİÇBİR ŞEKİLDE
    değişmez, yalnızca zaten sıfıra yuvarlanmış BİR STRING üzerinde çalışır
    (bkz. HATA 18A "Small magnitude scores" bulgusu: +0.04/-0.04 ikisi de
    meşru HOLD/nötr bandında -- "-0.0" göstermek yanlış bir yön ima eder gibi
    okunabilir, oysa ikisi de aynı nötr sınıfa aittir)."""
    if text.startswith("-") and float(text) == 0.0:
        return "+" + text[1:]
    return text


def _signed_round_trip_repr(value: float) -> str:
    """`value`'nun TAM, round-trip-safe (aynı float'a geri parse edilen)
    temsili -- Python'un `repr(float)` her zaman bu özelliği garanti eder
    (short-repr algoritması, Python 3.1+)."""
    text = repr(value)
    if not text.startswith("-"):
        text = f"+{text}"
    return _normalize_negative_zero(text)


def format_decision_score(
    final_score: float,
    decision: str,
    decision_thresholds: dict[str, float] | None,
) -> str:
    """`final_score`'u, gösterilen string'in `_classify()` ile yeniden
    sınıflandırıldığında DAİMA persisted `decision` ile eşleştiği, adaptif
    hassasiyetli bir string'e çevirir. Bkz. modül docstring'i."""
    if decision_thresholds is None:
        # HATA 17D-öncesi (legacy) kayıt: eşik snapshot'ı yok. Güncel
        # config'ten TAHMİN ETMEK YERİNE (config drift, geçmiş bir kararın
        # sunumunu SESSİZCE değiştirebilirdi), doğrudan tam/round-trip-safe
        # temsili göster -- ne config lookup, ne crash, ne uydurma eşik.
        return _signed_round_trip_repr(final_score)

    for decimals in range(1, _MAX_ADAPTIVE_DECIMALS + 1):
        candidate = _normalize_negative_zero(f"{final_score:+.{decimals}f}")
        if _classify(float(candidate), decision_thresholds) == decision:
            return candidate

    # Sınırlı adaptif deneme tükendi (patolojik durum) -- TAM round-trip-safe
    # temsile düş. Bu, `decision`'ı ÜRETEN değerin ta kendisi olduğundan,
    # sınıflandırması TANIM GEREĞİ `decision` ile eşleşir.
    return _signed_round_trip_repr(final_score)
