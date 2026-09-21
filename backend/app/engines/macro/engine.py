"""MacroAnalysisEngine — ana doküman bölüm 15.

Yön sözleşmesi (dokümante edilmiş tasarım kararı): DXY, ABD 10Y tahvil faizi, VIX,
petrol ve USD/TRY'nin YÜKSELMESİ risk-off / BIST için negatif olarak yorumlanır
(dolar güçlenmesi ve faiz artışı gelişen piyasalardan çıkışı, VIX artışı risk
iştahının azalmasını, petrol artışı Türkiye'nin ithalatçı konumu nedeniyle
enflasyon baskısını, TL'nin değer kaybı ise maliyet/enflasyon baskısını temsil
eder). Altın için de risk-off proxy'si olarak aynı yön kullanılmıştır. Bu, TÜM
varlıklar için ortak/piyasa-geneli bir skordur (TechnicalScore gibi varlığa özel
değildir) — ana dokümandaki `macro_snapshots` collection'ı ile uyumludur.
"""

import math
from datetime import datetime, timezone

from app.models.macro_snapshot import MacroSnapshot
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.macro.base import MacroDataProvider
from app.services.macro.yahoo_macro_provider import YahooMacroProvider

ENGINE_VERSION = "1.0.0"

# HATA 16B: `DEFAULT_SCALES`/`DEFAULT_WEIGHTS`'in production `analyze()`
# path'indeki tek rolü artık `resolve_macro_weights()`/`resolve_macro_scales()`
# için beklenen anahtar setini (`set(DEFAULT_WEIGHTS)`/`set(DEFAULT_SCALES)`)
# türetmektir -- DEĞERLERİ artık runtime scoring'e SESSİZCE fallback OLARAK
# kullanılmaz (HATA 16A bulgu #1). Kalan kullanım alanı: bootstrap tooling/
# testlerde/scratch araçlarda "geçerli, tam bir referans config" olarak (bkz.
# `decision/engine.py`'deki `DEFAULT_WEIGHTS`'in AYNI rolü, HATA 5C3B).

# Her göstergenin tipik oynaklığına göre ölçek faktörü (pct_change -> -100..100 puan).
DEFAULT_SCALES = {
    "dxy": 15.0,
    "us_10y_yield": 10.0,
    "vix": 2.0,
    "oil": 5.0,
    "gold": 8.0,
    "usdtry": 8.0,
}

DEFAULT_WEIGHTS = {
    "dxy": 0.20,
    "us_10y_yield": 0.20,
    "vix": 0.20,
    "oil": 0.15,
    "gold": 0.10,
    "usdtry": 0.15,
}

# HATA 16C: tüm 6 gösterge günlük granülaritede piyasa fiyatlarıdır (borsa takvimi
# gerektiren periyodik ekonomik veri açıklamaları değil, bkz. HATA 16A). Freshness
# kontrolü TEK bir muhafazakâr, PAYLAŞILAN eşik kullanır (gösterge başına ayrı değil):
# tam bir çoklu-borsa takvim altyapısı kurmak yerine (ticket madde 8, kasıtlı olarak
# kapsam dışı), en son gözlemin analiz anına göre kaç TAKVİM günü eski olduğuna
# bakılır. 5 gün seçildi çünkü: sıradan 2 günlük hafta sonu (Cuma->Pazartesi = 3
# takvim günü) ve borsa tatiliyle birleşen bir hafta sonu (ör. Perşembe kapanışı ->
# Salı analizi = 5 takvim günü, Pazartesi tatilse) rahatça KAPSANIR, +1 günlük ekstra
# pay bırakılır; buna karşın haftalarca eski/cache'lenmiş GERÇEKTEN stale bir feed
# (6+ gün) yine de YAKALANIR. Bu, HATA 16A bulgu #3'ü (SILENT ACCEPT) kapatır.
MAX_OBSERVATION_AGE_DAYS = 5


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _is_fresh_observation(
    observed_at, now: datetime, max_age_days: int = MAX_OBSERVATION_AGE_DAYS
) -> bool:
    """HATA 16C: bir göstergenin `observed_at`'ının bu run için KULLANILABİLİR
    (fresh) olup olmadığını belirler. Karşılaştırma KASITLI OLARAK takvim
    tarihi (UTC) bazındadır, tam datetime farkı değil -- günlük bar'lar bir
    SEANS tarihini temsil eder, kesin bir kapanış saatini değil, ve farklı
    ticker'lar farklı borsa saat dilimlerinden gelebilir (HATA 16A madde 2).
    Tarih bazlı karşılaştırma, gün sınırına yakın saatlerde yanlış
    taze/stale sınıflandırmasını önler ve timezone-safe'dir (her iki taraf da
    önce UTC'ye normalize edilir).

    - `observed_at` bir `datetime` değilse veya tz-naive ise: FRESH DEĞİL
      (eksik/geçersiz zaman damgası asla "güncel" varsayılmaz).
    - `observed_at` gelecekte ise (age_days < 0): FRESH DEĞİL (bozuk/şüpheli
      veri sessizce "en taze" olarak kabul edilmez).
    - `0 <= age_days <= max_age_days`: FRESH (sınır DAHİL).
    """
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        return False
    observed_utc = observed_at.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    age_days = (now_utc.date() - observed_utc.date()).days
    return 0 <= age_days <= max_age_days


def resolve_macro_weights(raw_doc: dict | None) -> dict[str, float]:
    """`macro_indicator_weights` config'i için FAIL-FAST okuma sözleşmesi
    (HATA 16B) -- `decision/engine.py::resolve_decision_weights()` ile AYNI
    desen: `SystemConfigRepository.get()`'in auto-seed/sessiz-partial-merge
    davranışı (HATA 5B2C'nin kök nedeni, HATA 16A'da macro için doğrulanmış
    bulgu #1) burada TEKRARLANMAZ; `get_raw()`'ın ham çıktısı alınır.

      - `raw_doc is None` (doküman HİÇ yok): `ValueError` (FAIL-FAST) --
        `DEFAULT_WEIGHTS`'e SESSİZCE düşülmez, bu production config
        corruption/deletion olarak ele alınır.
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir
        değer non-numeric/bool/NaN/±inf/negatifse: `ValueError` (FAIL-FAST).
      - Ağırlıkların toplamı <= 0 ise: `ValueError` (tek tek sıfır ağırlık
        SERBESTTİR -- ör. `usdtry=0` -- ama TÜMÜ sıfır/negatif olamaz).
        NOT: bu yalnızca CONFIG seviyesinde toplam pozitifliği garanti eder;
        belirli bir RUN'da mevcut göstergelerin TAMAMI sıfır ağırlıklı
        kanallara denk gelebilir -- bu durum `MacroAnalysisEngine.analyze()`
        içinde AYRICA, DecisionEngine'in `NO_POSITIVE_WEIGHT_AVAILABLE`
        deseniyle simetrik şekilde ele alınır (HATA 16A bulgu #2).
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.
    """
    if raw_doc is None:
        raise ValueError(
            "'macro_indicator_weights' config dokümanı Firestore'da bulunamadı -- "
            "bu, MacroAnalysisEngine için REQUIRED bir production config'tir; code "
            "DEFAULT_WEIGHTS'e SESSİZCE düşülmez (production config corruption/"
            "deletion olarak ele alınır) -- fail-fast."
        )

    expected_keys = set(DEFAULT_WEIGHTS)
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'macro_indicator_weights' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(
                f"'macro_indicator_weights.{key}' geçersiz değer: {value!r} "
                "(finite, negatif olmayan bir sayı olmalı)."
            )

    if sum(raw_doc.values()) <= 0:
        raise ValueError("'macro_indicator_weights': ağırlıkların toplamı > 0 olmalı.")

    return {k: float(v) for k, v in raw_doc.items()}


def resolve_macro_scales(raw_doc: dict | None) -> dict[str, float]:
    """`macro_indicator_scales` config'i için FAIL-FAST okuma sözleşmesi
    (HATA 16B). `resolve_macro_weights()`'ten KASITLI OLARAK FARKLI bir
    invariant taşır: bir scale değeri bir AĞIRLIK değil, `pct_change`'i
    -100..100 puan aralığına çeviren bir çarpandır -- 0 veya negatif bir
    scale, o göstergeyi WEIGHT mekanizması yerine SESSİZCE ölçek üzerinden
    devre dışı bırakır/yön değiştirir, ki bu hiçbir mevcut production
    semantics'i tarafından desteklenmez -- bu yüzden her scale STRICTLY
    pozitif olmalıdır (weight'in aksine, tek tek sıfır scale SERBEST
    DEĞİLDİR).

      - `raw_doc is None`: `ValueError` (FAIL-FAST) -- `DEFAULT_SCALES`'e
        SESSİZCE düşülmez.
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir
        değer non-numeric/bool/NaN/±inf/<=0 ise: `ValueError` (FAIL-FAST).
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.
    """
    if raw_doc is None:
        raise ValueError(
            "'macro_indicator_scales' config dokümanı Firestore'da bulunamadı -- "
            "bu, MacroAnalysisEngine için REQUIRED bir production config'tir; code "
            "DEFAULT_SCALES'e SESSİZCE düşülmez (production config corruption/"
            "deletion olarak ele alınır) -- fail-fast."
        )

    expected_keys = set(DEFAULT_SCALES)
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'macro_indicator_scales' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"'macro_indicator_scales.{key}' geçersiz değer: {value!r} "
                "(finite, strictly pozitif bir sayı olmalı)."
            )

    return {k: float(v) for k, v in raw_doc.items()}


class MacroAnalysisEngine:
    def __init__(
        self,
        provider: MacroDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
        snapshot_repo: MacroSnapshotRepository | None = None,
    ):
        self._provider = provider or YahooMacroProvider()
        self._config_repo = config_repo or SystemConfigRepository()
        self._snapshot_repo = snapshot_repo or MacroSnapshotRepository()

    def analyze(self, persist: bool = True) -> tuple[MacroSnapshot, str | None]:
        # HATA 16B: `get()` (auto-seed + sessiz partial-merge, HATA 5B2C'nin
        # kök nedeni, HATA 16A'da macro için doğrulanmış bulgu #1) ARTIK
        # KULLANILMIYOR -- `get_raw()` + fail-fast resolver'lar (yukarıda)
        # production path'te TEK kaynak. Resolver'lar provider fetch'ten
        # ÖNCE çağrılır: geçersiz/eksik config, hiçbir Yahoo çağrısı
        # yapılmadan fail-fast eder.
        weights = resolve_macro_weights(self._config_repo.get_raw("macro_indicator_weights"))
        scales = resolve_macro_scales(self._config_repo.get_raw("macro_indicator_scales"))

        changes = self._provider.get_indicator_changes()
        if not changes:
            raise ValueError("Hiçbir makro gösterge verisi alınamadı")

        # HATA 16C: provider'dan dönen HER gösterge önce freshness kontrolünden
        # geçer -- stale/eksik/gelecek tarihli `observed_at` taşıyan göstergeler
        # bu run için TAMAMEN ELENİR (skorlanmaz, sıfıra/nötre çevrilmez).
        # Component hesaplaması ve HATA 16B'nin available-weight renormalizasyonu
        # yalnızca FRESH göstergeler üzerinden çalışır -- stale bir göstergenin
        # ağırlığı hiçbir zaman "kayıp" gibi cezalandırılmaz, sadece mevcut
        # değildir (aynı `available_weight` mekanizması, HATA 16B).
        now = datetime.now(timezone.utc)
        fresh_changes = {
            key: data
            for key, data in changes.items()
            if _is_fresh_observation(data.get("observed_at"), now)
        }
        if not fresh_changes:
            raise ValueError(
                "Makro skor üretilemedi: alınan göstergelerin tamamı stale/geçersiz "
                f"gözlem zamanlı ({MAX_OBSERVATION_AGE_DAYS} takvim gününden eski, eksik "
                "veya gelecek tarihli) -- macro_score uydurulmaz, MacroSnapshot kaydedilmez."
            )
        changes = fresh_changes

        components = {}
        for key, data in changes.items():
            # Tüm göstergeler için: yükseliş = risk-off = negatif katkı (yukarıdaki not).
            components[key] = _clamp(-data["pct_change"] * scales[key])

        available_weight = sum(weights[k] for k in components)
        # HATA 16B (HATA 16A bulgu #2): config toplamda geçerli/pozitif olsa
        # bile (ör. dxy=0, diğerleri pozitif) bu RUN'da mevcut göstergelerin
        # TAMAMI sıfır ağırlıklı kanallara denk gelebilir -- eski kod burada
        # `macro_score = 0.0` UYDURURDU (confirmed production bug, HATA 16A).
        # `DecisionEngine.decide()`'daki `NO_POSITIVE_WEIGHT_AVAILABLE`
        # deseniyle SİMETRİK: veri GERÇEKTEN var (provider başarılı oldu),
        # yalnızca configured ağırlığı sıfır -- 0 score/confidence ASLA
        # uydurulmaz, hiçbir MacroSnapshot kaydedilmez.
        if available_weight == 0:
            raise ValueError(
                "Makro skor üretilemedi: bu çalıştırmada mevcut göstergelerin "
                f"({sorted(components)}) tamamı sıfır ağırlıklı kanallara ait "
                "(NO_POSITIVE_WEIGHT_AVAILABLE) -- macro_score uydurulmaz, "
                "MacroSnapshot kaydedilmez."
            )

        macro_score = round(
            sum(components[k] * weights[k] for k in components) / available_weight, 2
        )

        completeness = len(components) / len(weights)
        agreement = sum(
            1 for s in components.values() if (s >= 0) == (macro_score >= 0)
        ) / len(components)
        confidence = round(_clamp(0.3 + 0.4 * agreement + 0.3 * completeness, 0.0, 1.0), 2)

        snapshot = MacroSnapshot(
            macro_score=macro_score,
            confidence=confidence,
            components=components,
            indicators=changes,
            created_at=datetime.now(timezone.utc),
            engine_version=ENGINE_VERSION,
        )

        doc_id = self._snapshot_repo.add(snapshot) if persist else None
        return snapshot, doc_id
