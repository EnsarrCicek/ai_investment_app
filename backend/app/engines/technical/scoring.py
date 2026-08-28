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


def aggregate_available_components(components: dict[str, float], weights: dict) -> float | None:
    """Scalar (live) aggregation — yalnız AVAILABLE (finite) component'ler
    üzerinden ağırlıklı ortalama. Hiçbiri available değilse (`weight_sum==0`)
    `None` döner — `0.0`/`100.0` UYDURULMAZ (bkz. modül docstring'i).
    """
    available = {k: v for k, v in components.items() if is_available(v)}
    weight_sum = sum(weights.get(k, 0.0) for k in available)
    if weight_sum == 0:
        return None
    raw = sum(available[k] * weights.get(k, 0.0) for k in available)
    return round(clamp_component(raw / weight_sum), 2)


def aggregate_available_components_series(components_df: pd.DataFrame, weights: dict) -> pd.Series:
    """Vectorized (backtest) aggregation — `aggregate_available_components()`
    ile AYNI contract, satır bazında (her gün KENDİ available-component
    kümesine göre ayrı bir weight_sum). Python row-loop YOK — `finite_mask`
    (her hücre için available mi) ile numerator/denominator vektörize
    hesaplanır. `available_weight_sum==0` olan satırlar `NaN` döner (`None`'ın
    pandas serisi karşılığı) — bir gün hiçbir bileşen available değilse o
    günün skoru da UYDURULMAZ.
    """
    columns = list(components_df.columns)
    weight_row = pd.Series({col: weights.get(col, 0.0) for col in columns}, dtype=float)

    finite_mask = np.isfinite(components_df.to_numpy(dtype=float))
    finite_df = pd.DataFrame(finite_mask, index=components_df.index, columns=columns)

    numerator = components_df.where(finite_df, 0.0).mul(weight_row, axis=1).sum(axis=1)
    denominator = finite_df.astype(float).mul(weight_row, axis=1).sum(axis=1)

    score = (numerator / denominator).where(denominator > 0)
    return score.clip(-100.0, 100.0).round(2)


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
