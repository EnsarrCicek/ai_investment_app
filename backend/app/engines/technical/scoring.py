"""HATA 5B1 (27.08.2026) — technical_score component aggregation contract.

Denetimde kanıtlandı (HATA 5B/5B1 audit'leri): `technical_score`'un 7
bileşeni (RSI/MACD/trend/EMA slope/Bollinger/Momentum/ROC), bir bileşen
kendi matematiksel hazırlık döneminde (warm-up) veya tanımsız bir oranda
(0/0, x/0) olduğunda İKİ AYRI, TUTARSIZ ve HER İKİSİ DE YANLIŞ şekilde ele
alınıyordu:

- Backtest (`backtest/engine.py`): 5/7 bileşen `.fillna(0.0)` ile SESSİZCE
  "geçerli nötr 0" sayılıyordu (weight_sum'daki payı KORUNARAK) — bu, projenin
  kendi "missing data için neutral 0 UYDURMA" ilkesini doğrudan ihlal eder.
  Kalan 2/7 bileşen (RSI/ROC) hiç doldurulmuyordu — NaN tüm günün skorunu
  NaN'a "zehirliyordu" (yalnızca o bileşenin DEĞİL).
- Live (`technical/engine.py`): `if atr_val else 0.0` gibi guard'lar yalnızca
  LİTERAL SIFIR paydayı yakalıyordu — NaN Python'da TRUTHY olduğundan
  (`bool(float('nan'))==True`) bu guard'lar NaN'ı HİÇ yakalamıyordu; sonuç
  `_clamp(nan) = max(low, min(high, nan)) = 100.0` (Python'ın min/max'ının
  NaN karşılaştırma davranışı nedeniyle DETERMİNİSTİK olarak +100) — yani
  eksik bir bileşen, live'da HER ZAMAN sahte bir "maksimum bullish" sinyaline
  dönüşüyordu.

Bu modül, HER İKİ motorun da PAYLAŞTIĞI TEK bir contract'a bağlanır:

    AVAILABLE   ⟺ value is not None AND math.isfinite(value)
                  (finite pozitif, finite negatif, finite 0.0 dahil — 0.0
                  MISSING DEĞİLDİR, weight denominator'da KALIR)
    UNAVAILABLE ⟺ None, NaN, +inf, veya -inf
                  (numerator'dan VE weight denominator'dan ÇIKARILIR)

    score = Σ(w_i · c_i, yalnız available i)  /  Σ(w_i, yalnız available i)
    hiçbir component available değilse (denominator == 0): score = None
    (0.0 UYDURULMAZ, +100 UYDURULMAZ)

**Bilinçli olarak DEĞİŞTİRİLMEYEN:** 7 bileşenin kendi ham formülleri
(RSI/MACD/EMA/Bollinger/Momentum/ROC hesaplama mantığı, `indicators.py`),
ağırlıklar (`SystemConfigRepository`), threshold'lar — hiçbiri bu modülün
kapsamında DEĞİŞMEDİ. Bu YALNIZCA aggregation semantics'idir (bir bileşen
ne zaman "var" sayılır, weight_sum nasıl hesaplanır).

**Kapsam dışı bırakılan, AYRI bir konu (HATA 5B2, DONDURULDU):** bileşenler
arası korelasyon/double-counting (momentum↔ROC ~0.98, Bollinger↔RSI ~0.90
vb.) — bu modül hiçbir ağırlığı/bileşeni SİLMEZ, yalnızca "mevcut olan
bileşenlerin ağırlığını doğru normalize eder."

**Zero-denominator ≠ valid zero, per-component gerekçe (HATA 5B1 audit'i):**
RSI'ın düz (flat) bir seride `50.0` (component=`0.0`) dönmesi `indicators.
rsi()`'ın KENDİ, kasıtlı matematiksel tanımıdır (`_rsi_from_averages`'ın
`avg_gain==0 and avg_loss==0 → 50.0` dalı) — GERÇEK bir geçerli sıfırdır.
Buna karşılık MACD/Momentum'un `ATR==0` durumunda payı da (macd_hist/momentum
diff) aynı düz-fiyat nedeniyle sıfırlandığından bu bir 0/0 BELİRSİZLİK
durumudur (Bollinger'ın `band_width==0` durumu da aynı şekilde `close==middle`
olduğundan 0/0'dır) — matematiksel olarak "tanımsız", "geçerli ölçülmüş
sıfır" DEĞİLDİR. Bu modül ikisini de AYNI mekanizmayla (finite kontrolü)
doğru ayırt eder: RSI'ın `0.0`'ı zaten finite bir değer olarak GELİR ve
AVAILABLE sayılır; MACD/Momentum/Bollinger'ın 0/0'ı NaN/inf olarak gelir
(`safe_ratio`/doğal pandas float bölmesi) ve UNAVAILABLE sayılır.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd


def is_available(value: float | None) -> bool:
    """Bir technical_score bileşeni "mevcut" sayılır ancak `value` `None`
    DEĞİLSE VE finite ise (`math.isfinite`). `math.isfinite(None)` `TypeError`
    fırlattığından `None` kontrolü HER ZAMAN `isfinite`'tan ÖNCE yapılır.
    """
    if value is None:
        return False
    return math.isfinite(value)


def clamp_component(value: float, low: float = -100.0, high: float = 100.0) -> float:
    """`value` finite ise `[low, high]`'a sıkıştırır; DEĞİLSE (NaN/±inf) NaN
    döner — Python'ın `max(low, min(high, value))` deseninin NaN'ı
    DETERMİNİSTİK olarak `high`'a çevirdiği (HATA 5B1'de kanıtlanan) hatanın
    KÖKÜNDEN düzeltmesi: NaN/inf hiçbir zaman bu fonksiyonun `min`/`max`
    çağrılarına ULAŞMAZ.
    """
    if not math.isfinite(value):
        return float("nan")
    return max(low, min(high, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    """`numerator/denominator`'ı yalnızca HER İKİSİ de finite VE `denominator
    != 0` ise hesaplar; aksi halde NaN döner. Live (scalar) tarafında Python
    float bölmesinin `x/0.0` için `ZeroDivisionError` fırlattığı (backtest'in
    vektörize pandas bölmesinin aksine, ki o NaN/inf üretir) durumu güvenle
    kapatır — hem `0/0` hem `x/0` hem `NaN` girdisi AYNI, tutarlı "tanımsız"
    (NaN) sonucunu üretir.
    """
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return float("nan")
    return numerator / denominator


def aggregate_available_components(
    components: dict[str, float], weights: dict, round_digits: int | None = 2
) -> float | None:
    """Scalar (live) aggregation — yalnız AVAILABLE (finite) component'ler
    üzerinden ağırlıklı ortalama. Hiçbiri available değilse (`weight_sum==0`)
    `None` döner — `0.0`/`100.0` UYDURULMAZ (bkz. modül docstring'i).

    HATA 5B2D FINAL PRE-COMMIT GATE (27.08.2026, madde 4/5) — `round_digits`:
    HATA 5B1'in TEK SEVİYELİ (flat 7-component) kullanımı İÇİN varsayılan
    (`2`) HİÇ DEĞİŞMEDİ. Ancak HATA 5B2D'nin İKİ SEVİYELİ (component ->
    family -> technical_score) kullanımında bu fonksiyon RECURSIVE olarak
    İKİ KEZ çağrılıyor — eğer Level 1 (component -> family) de `round(2)`
    uygulasaydı, Level 2 (family -> technical_score) YUVARLANMIŞ family
    değerleri üzerinden hesaplama yapardı ("double rounding") ve final
    `technical_score` gerçek tam-hassasiyetli sonuçtan (nadiren ama gerçek
    şekilde) sapabilirdi. Contract: internal hesaplama TAM HASSASİYETLE
    yapılır (`round_digits=None` ile family seviyesinde), final skor YALNIZ
    EN SONDA bir kez yuvarlanır (`round_digits=2`, varsayılan, DEĞİŞMEDİ);
    `family_scores` (persisted/provenance) ayrıca, tam-hassasiyetli
    değerlerden AYRI olarak `round(v, 2)` ile üretilir -- bu yuvarlama
    final `technical_score` hesabına HİÇ GERİ BESLENMEZ (bkz. `engine.py`/
    `backtest/engine.py`, `raw_family_scores` vs `stored_family_scores`).
    """
    available = {k: v for k, v in components.items() if is_available(v)}
    weight_sum = sum(weights.get(k, 0.0) for k in available)
    if weight_sum == 0:
        return None
    raw = sum(available[k] * weights.get(k, 0.0) for k in available)
    result = clamp_component(raw / weight_sum)
    return round(result, round_digits) if round_digits is not None else result


def aggregate_available_components_series(
    components_df: pd.DataFrame, weights: dict, round_digits: int | None = 2
) -> pd.Series:
    """Vectorized (backtest) aggregation — `aggregate_available_components()`
    ile AYNI contract (`round_digits` dahil, bkz. o fonksiyonun docstring'i),
    satır bazında (her gün KENDİ available-component kümesine göre ayrı bir
    weight_sum). Python row-loop YOK — `finite_mask` (her hücre için
    available mi) ile numerator/denominator vektörize hesaplanır.
    `available_weight_sum==0` olan satırlar `NaN` döner (`None`'ın pandas
    serisi karşılığı) — bir gün hiçbir bileşen available değilse o günün
    skoru da UYDURULMAZ.
    """
    columns = list(components_df.columns)
    weight_row = pd.Series({col: weights.get(col, 0.0) for col in columns}, dtype=float)

    finite_mask = np.isfinite(components_df.to_numpy(dtype=float))
    finite_df = pd.DataFrame(finite_mask, index=components_df.index, columns=columns)

    numerator = components_df.where(finite_df, 0.0).mul(weight_row, axis=1).sum(axis=1)
    denominator = finite_df.astype(float).mul(weight_row, axis=1).sum(axis=1)

    score = (numerator / denominator).where(denominator > 0)
    clipped = score.clip(-100.0, 100.0)
    return clipped.round(round_digits) if round_digits is not None else clipped


# HATA 5B2D (27.08.2026) -- FAMILY-LEVEL AGGREGATION. HATA 5B2/5B2A/5B2B
# audit'leri (92 sembol × 2 yıl, gerçek Firestore config) kanıtladı: 7
# nominal bileşen istatistiksel olarak yalnızca ~2 efektif bağımsız boyut
# taşıyor (PCA: ilk 2 PC toplam varyansın ~%93'ünü açıklıyor) -- momentum↔ROC
# formula-level bir matematiksel özdeşlik (`sign` her ikisinde de AYNI
# `Close[T]-Close[T-10]` payından geliyor), RSI↔Bollinger/MACD↔momentum ise
# güçlü, kalıcı (cross-symbol + out-of-time stabil) empirik regularite'ler.
# Kabul edilen üç family (data-driven clustering + formula-level gerekçe,
# bkz. TEKNIK_ANALIZ_METODOLOJISI.md HATA 5B2 bölümü):
#
#   trend                -- {trend}                        (en bağımsız, dendrogram'da EN SON birleşiyor)
#   oscillator_position   -- {rsi, bollinger, ema_slope}     (within-family mean |corr|=0.84, empirik olarak en tutarlı grup)
#   momentum_rate         -- {macd, momentum, roc}           (momentum/ROC yönü matematiksel özdeş; MACD ile empirik ~0.85-0.89)
#
# Family membership BİLİNÇLİ OLARAK versioned bir KOD sabiti (Firestore'da
# kullanıcı-tunable bir taxonomy DEĞİL) -- indikatör formülleriyle (RSI
# periyodu, EMA pencereleri, Bollinger σ çarpanı) AYNI mantık: "hangi
# component'in hangi family'ye ait olduğu" bir kalibrasyon parametresi değil,
# bu audit zincirinin (5B2/5B2A/5B2B) kanıtladığı bir taxonomy/metodoloji
# gerçeğidir -- yanlışlıkla veya rastgele değiştirilmesi score semantics'ini
# sessizce bozar, bu yüzden `ENGINE_VERSION` bump'ı gerektirir.
FAMILY_MEMBERSHIP: dict[str, tuple[str, ...]] = {
    "trend": ("trend",),
    "oscillator_position": ("rsi", "bollinger", "ema_slope"),
    "momentum_rate": ("macd", "momentum", "roc"),
}

# Top-level family weight'i İÇİN kabul edilen initial prior: EQUAL (1/3).
# HATA 5B2A'da algebraik olarak KANITLANDI: family weight'i mevcut component
# weight'lerinin TOPLAMINDAN türetmek (`sum(member component weights)`)
# double-counting'i HİÇ ÇÖZMEZ -- matematiksel olarak mevcut (bozuk) flat
# mimariye BİREBİR ÖZDEŞTİR. Equal-family, member-count bias'ını GERÇEKTEN
# ortadan kaldıran, "bilimsel olarak optimal" OLDUĞU iddia edilmeyen, minimal
# parametre sayılı nötr bir prior'dur (bkz. HATA 5B2B, madde 29). `1.0/3.0`
# kullanılır -- `0.3333` gibi yuvarlanmış literal'ler toplamı `0.9999` yapıp
# sessizce bir renormalizasyon hatası yaratabilirdi.
DEFAULT_TECHNICAL_FAMILY_WEIGHTS: dict[str, float] = {
    "trend": 1.0 / 3.0,
    "oscillator_position": 1.0 / 3.0,
    "momentum_rate": 1.0 / 3.0,
}

# HATA 5B1'in scalar/vectorized aggregation contract'ı ("available olan
# değerlerin ağırlıklı ortalaması, unavailable olanlar hem numerator hem
# weight-denominator'dan çıkar") kavramsal olarak component'e ÖZGÜ DEĞİLDİR
# -- HATA 5B2D bunu İKİNCİ KEZ, bağımsız bir implementasyon YAZMADAN, AYNI
# fonksiyonları family_score hesaplamasında (component -> family) VE
# technical_score hesaplamasında (family -> technical_score) RECURSIVE
# olarak yeniden kullanır. Genel isimler yalnızca ÇAĞRI YERİNDE okunabilirlik
# için eklenir -- `aggregate_available_components`/`_series`'in KENDİSİ
# (isim, davranış, mevcut testler) HİÇ DEĞİŞMEDİ.
aggregate_available_scores = aggregate_available_components
aggregate_available_scores_series = aggregate_available_components_series


def resolve_family_weights(raw_doc: dict | None) -> dict[str, float]:
    """`technical_family_weights` config'i için FAIL-FAST okuma sözleşmesi
    (HATA 5B2D, madde 12). HATA 5B2C'nin kök nedenini (`SystemConfigRepository.
    get()`'in eksik/partial bir dokümanı default'larla SESSİZCE tamamlaması
    -- `ema_slope` anahtarının aylarca fark edilmeden eksik kalması) TEKRAR
    ETMEMEK için bu fonksiyon `get()` YERİNE `get_raw()`'ın (auto-seed/merge
    YAPMAYAN) ham çıktısını alır:

      - `raw_doc is None` (doküman HİÇ yok): `DEFAULT_TECHNICAL_FAMILY_
        WEIGHTS` döner -- Firestore'a HİÇBİR ŞEY YAZILMAZ (seeding bilinçli
        olarak ayrı bir pre-deploy adımına bırakıldı).
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir
        değer non-numeric/NaN/±inf/negatifse: `ValueError` (FAIL-FAST) --
        SESSİZCE tamamlanmaz/birleştirilmez.
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.
    """
    if raw_doc is None:
        return dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)

    expected_keys = set(FAMILY_MEMBERSHIP)
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'technical_family_weights' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(
                f"'technical_family_weights.{key}' geçersiz değer: {value!r} "
                "(finite, negatif olmayan bir sayı olmalı)."
            )

    if sum(raw_doc.values()) <= 0:
        raise ValueError("'technical_family_weights': available ağırlıkların toplamı > 0 olmalı.")

    return {k: float(v) for k, v in raw_doc.items()}


def resolve_indicator_weights(raw_doc: dict | None) -> dict[str, float]:
    """`technical_indicator_weights` için FAIL-FAST okuma sözleşmesi (HATA
    5B2D FINAL COMMIT GATE, madde 1-4) -- `resolve_family_weights()`'ten
    KASITLI OLARAK FARKLI bir invariant taşır: bu doküman HATA 5B2C ile
    production'da BİLİNÇLİ OLARAK 7/7 explicit/complete hale getirilmiş,
    1.7.0 family mimarisi için REQUIRED bir production config/methodology
    source-of-truth'tur (code `DEFAULT_WEIGHTS`'ten DEĞERCE FARKLIDIR) --
    `technical_family_weights`'in aksine (o henüz pre-deploy'da oluşturulacak,
    default'u zaten planlanan production semantics'iyle AYNI), bu dokümanın
    TAMAMEN KAYBOLMASI "normal default case" DEĞİL, **production config
    corruption/deletion** olarak ele alınır:

      - `raw_doc is None` (doküman HİÇ yok): `ValueError` (FAIL-FAST) --
        code `DEFAULT_WEIGHTS`'e SESSİZCE düşülmez, `0.0`/uydurma bir skor
        ASLA üretilmez.
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir
        değer non-numeric/NaN/±inf/negatifse: `ValueError` (FAIL-FAST).
      - Her family içinde (bkz. `FAMILY_MEMBERSHIP`) en az bir POZİTİF
        weight olmalı -- aksi halde o family'nin tüm member'ları KONFİGÜRE
        SEVİYESİNDE (veri mevcudiyetinden BAĞIMSIZ) her zaman weight_sum=0
        üretir, ki bu "geçici olarak unavailable" ile KARIŞTIRILMAMASI
        gereken, sessiz bir config hatasıdır.
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.

    Beklenen anahtar seti `FAMILY_MEMBERSHIP`'in TÜM member'larının
    birleşiminden türetilir (`rsi`/`macd`/`trend`/`ema_slope`/`bollinger`/
    `momentum`/`roc`) -- ayrı, elle-bakımlı bir sabit listeye GEREK YOK.
    """
    if raw_doc is None:
        raise ValueError(
            "'technical_indicator_weights' config dokümanı Firestore'da bulunamadı -- "
            "bu, 1.7.0 family mimarisi için REQUIRED bir production config'tir "
            "(HATA 5B2C ile 7/7 explicit hale getirildi); code DEFAULT_WEIGHTS'e "
            "SESSİZCE düşülmez (production config corruption/deletion olarak ele "
            "alınır, 'normal default case' DEĞİLDİR) -- fail-fast."
        )

    expected_keys = {member for members in FAMILY_MEMBERSHIP.values() for member in members}
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'technical_indicator_weights' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(
                f"'technical_indicator_weights.{key}' geçersiz değer: {value!r} "
                "(finite, negatif olmayan bir sayı olmalı)."
            )

    for family, members in FAMILY_MEMBERSHIP.items():
        if sum(raw_doc[m] for m in members) <= 0:
            raise ValueError(
                f"'technical_indicator_weights': '{family}' family'si içinde ({', '.join(members)}) "
                "en az bir pozitif weight olmalı."
            )

    return {k: float(v) for k, v in raw_doc.items()}


def compute_scoring_config_hash(indicator_weights: dict[str, float], family_weights: dict[str, float]) -> str:
    """HATA 5B2D TRUE FINAL COMMIT GATE (27.08.2026) -- `TechnicalAnalysis`
    cache'inin (`technical/engine.py::analyze_with_id()`) yalnızca `age`/
    `engine_version` kontrol etmesi YETERSİZDİ: 1.7.0 family scoring artık
    İKİ Firestore config'ine (`technical_indicator_weights`, `technical_
    family_weights`) BAĞIMLI -- AYNI `engine_version` altında bu config'ler
    değişirse (ya da REQUIRED `technical_indicator_weights` silinirse) cache
    eski/yanlış bir skoru sessizce döndürebilir/config corruption'ı
    maskeleyebilirdi.

    Bu fonksiyon, `technical_score`'u FİİLEN ETKİLEYEN iki RESOLVED (yani
    zaten `resolve_indicator_weights()`/`resolve_family_weights()`'ten
    geçmiş, fail-fast doğrulanmış) config'ten deterministik bir parmak izi
    üretir -- `TechnicalAnalysis.scoring_config_hash` olarak persist edilir,
    cache bir sonraki çağrıda BUNU da karşılaştırır.

    Kasıtlı olarak DAHİL EDİLMEYEN:
      - Family membership (`FAMILY_MEMBERSHIP`) -- bu taxonomy/formula
        semantics'idir, zaten `ENGINE_VERSION` bump'ı gerektirir (versioned
        kod sabiti, Firestore config DEĞİL) -- ayrıca hash'lemeye GEREK YOK.
      - `decision_thresholds` -- bunlar `technical_score`'un HESAPLANMASINI
        değil, YALNIZCA sonraki sınıflandırmayı etkiler.

    Determinism: `json.dumps(..., sort_keys=True)` dict insertion sırasından
    BAĞIMSIZ kanonik bir serileştirme üretir (aynı key/value -> aynı string,
    sıra farketmez); `hashlib.sha256` bunun üzerinden sabit uzunlukta bir
    hex digest üretir. NaN/±inf/non-numeric zaten `resolve_*_weights()`
    tarafından reddedildiğinden bu fonksiyona hiç ulaşmaz.
    """
    payload = {
        "indicator_weights": {k: float(v) for k, v in indicator_weights.items()},
        "family_weights": {k: float(v) for k, v in family_weights.items()},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# HATA 5C3A (28.08.2026) -- confidence artık "Sinyal Mutabakatı" (signal
# agreement): SKOR BÜYÜKLÜĞÜNDEN bağımsız, YALNIZCA mevcut technical
# family'lerinin final teknik yönle ne kadar uyuştuğunu ölçen, ayrı bir
# metrik (bkz. HATA 5C2/5C2A/5C2B/5C2C audit zinciri). Eşik AYNEN mevcut
# `trend` alanının (BULLISH/NEUTRAL/BEARISH) semantics'idir -- +15/-15 YENİ
# bir parametre DEĞİL, zaten var olan sınır TEK bir helper'da merkezileşir.
TECHNICAL_DIRECTION_POSITIVE_THRESHOLD = 15.0
TECHNICAL_DIRECTION_NEGATIVE_THRESHOLD = -15.0


def technical_direction(score: float) -> str:
    """`score > +15` POSITIVE, `score < -15` NEGATIVE, aksi halde NEUTRAL --
    tam olarak `trend` alanının (BULLISH/BEARISH/NEUTRAL) sınırıdır, +15 ve
    -15'in KENDİSİ NEUTRAL'a düşer (dışlayıcı/exclusive boundary). Hem `trend`
    türetimi hem `compute_family_agreement()` AYNI bu helper'ı kullanır --
    sınır iki ayrı yerde tekrar YAZILMAZ (HATA 5C2B, madde 7).
    """
    if score > TECHNICAL_DIRECTION_POSITIVE_THRESHOLD:
        return "POSITIVE"
    if score < TECHNICAL_DIRECTION_NEGATIVE_THRESHOLD:
        return "NEGATIVE"
    return "NEUTRAL"


def compute_family_agreement(
    raw_family_scores: dict[str, float | None],
    final_score: float,
    family_weights: dict[str, float],
) -> float:
    """"Sinyal Mutabakatı": mevcut (available) family'lerin, `technical_
    family_weights` ile AĞIRLIKLANDIRILMIŞ olarak, final teknik yönle ne
    kadar uyuştuğu (bkz. HATA 5C2A, madde 3-5). Yalnızca `final_score is not
    None` iken çağrılmalıdır (çağıran sorumluluğu, bkz. `engine.py`).

    Denominator (`Σ family_weights[f], f ∈ available`) `final_score`'u
    ÜRETEN `aggregate_available_scores()` çağrısının KENDİ weight_sum'ıyla
    MATEMATİKSEL OLARAK ÖZDEŞTİR -- `final_score` `None` DEĞİLSE bu payda
    YAPISAL OLARAK sıfır olamaz (HATA 5C2B'de kanıtlanan garanti), bu yüzden
    ayrı bir sıfır-bölme guard'ı GEREKMEZ.
    """
    final_direction = technical_direction(final_score)
    available = {f: s for f, s in raw_family_scores.items() if is_available(s)}
    denominator = sum(family_weights.get(f, 0.0) for f in available)
    numerator = sum(
        family_weights.get(f, 0.0)
        for f, s in available.items()
        if technical_direction(s) == final_direction
    )
    return numerator / denominator


def compute_evidence_coverage(
    stored_components: dict[str, float],
    indicator_weights: dict[str, float],
    family_weights: dict[str, float],
) -> float:
    """"Veri Kapsamı": mevcut indicator evidence'in, beklenen 7 component/3
    family'nin ne kadarını kapsadığını ölçen, hiyerarşik ağırlıklı bir oran
    (bkz. HATA 5C2A, madde 6-8). Confidence'a (agreement) KARIŞTIRILMAZ --
    ayrı, bağımsız bir metrik.

        member_coverage[f] = Σ(indicator_weight[m], m ∈ available members of f)
                              / Σ(indicator_weight[m], m ∈ ALL members of f)
        evidence_coverage  = Σ(family_weight[f] * member_coverage[f], f ∈ ALL families)
                              / Σ(family_weight[f], f ∈ ALL families)

    `indicator_weights`/`family_weights` `resolve_indicator_weights()`/
    `resolve_family_weights()`'ten geçmiş RESOLVED (validated) dict'ler
    OLMALIDIR -- bu fonksiyon kendi başına validasyon YAPMAZ. Bu garantiler
    sayesinde her iki payda da (`member_total`, `family_total`) HİÇBİR ZAMAN
    sıfır olamaz: `resolve_indicator_weights` her family'de en az bir pozitif
    weight, `resolve_family_weights` toplamda en az bir pozitif family weight
    zorunlu kılar (FAIL-FAST, bkz. o fonksiyonların docstring'i).

    Zero-weight bir member'ın mevcut/mevcut-olmama durumu `member_coverage`'ı
    HİÇ ETKİLEMEZ (hem numerator hem denominator'a katkısı 0'dır) -- bu,
    "disabled/zero-weight evidence eksik sayılmaz" ilkesini (HATA 5C2C, madde
    8) ayrı bir özel-durum kodu OLMADAN, formülün doğal sonucu olarak sağlar.
    """
    family_total = sum(family_weights.values())
    coverage_sum = 0.0
    for family, members in FAMILY_MEMBERSHIP.items():
        member_total = sum(indicator_weights.get(m, 0.0) for m in members)
        available_total = sum(indicator_weights.get(m, 0.0) for m in members if m in stored_components)
        coverage_sum += family_weights.get(family, 0.0) * (available_total / member_total)
    return coverage_sum / family_total


def clamp_components_df(raw_components: pd.DataFrame, low: float = -100.0, high: float = 100.0) -> pd.DataFrame:
    """Her hücreyi, KENDİ ham (unclamped) finiteliğine göre ele alır:
    finite hücreler `[low, high]`'a sıkıştırılır; NaN/±inf hücreler `clip()`
    ne üretirse üretsin (ör. `inf.clip(...)==high` — YANLIŞ bir "available"
    izlenimi verirdi) SONUÇTA NaN'a geri döner. Bu, availability kontrolünün
    HER ZAMAN clamp'tan ÖNCEKİ ham değere bakmasını garanti eder — aksi
    halde bir `inf` oranı, clip tarafından `100.0`'a (finite!) çevrilip
    yanlışlıkla "available" sayılabilirdi.
    """
    finite_mask = np.isfinite(raw_components.to_numpy(dtype=float))
    finite_df = pd.DataFrame(finite_mask, index=raw_components.index, columns=raw_components.columns)
    return raw_components.clip(low, high).where(finite_df)
