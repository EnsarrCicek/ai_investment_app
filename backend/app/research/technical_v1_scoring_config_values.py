"""Technical V1 CONFIG kimlik-kapısı -- beklenen (expected) ve gözlemlenen
(observed) `scoring_config_hash` değerlerini üreten I/O adaptörleri.
HATA 12N3C2-B2-D.

Bu modül, `identity_gates.evaluate_config_gate()`'in SAF karşılaştırma
katmanından AYRI tutulan iki adaptörü içerir (section 6/20: repository/
dosya I/O'su, saf kapı karşılaştırmasından her zaman ayrı tutulur):

  - `load_expected_scoring_config_hash()`: dondurulmuş `research/
    technical_v1_freeze_manifest.json`'daki `methodology_identity.
    scoring_config_hash`'i okur (section 7). Kod tabanında bu dosyayı
    okuyan/parse eden BAŞKA bir mevcut loader YOKTU (bu HATA'da doğrulandı
    -- yalnızca değerin KENDİSİ, önceden okunmuş bir string parametre
    olarak, `FinalizationContext`/test fixture'larına elle veriliyordu),
    bu yüzden bu KÜÇÜK, tek-amaçlı loader YENİ yazıldı; freeze manifest'in
    KENDİSİ değiştirilmedi.
  - `compute_observed_scoring_config_hash()`: `app/engines/technical/
    engine.py::analyze_with_id()`'nin KENDİSİNİN kullandığı TAM AYNI
    kalıbı yeniden kullanır (`resolve_indicator_weights`/`resolve_family_
    weights`/`compute_scoring_config_hash` -- section 8, ikinci bir
    config-çözümleme algoritması İCAT EDİLMEDİ).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engines.technical.scoring import (
    compute_scoring_config_hash,
    resolve_family_weights,
    resolve_indicator_weights,
)
from app.repositories.system_config_repository import SystemConfigRepository

# Proje kökü: bu dosya backend/app/research/technical_v1_scoring_config_values.py
# olduğundan üç seviye yukarısı backend/, dört seviye yukarısı repo köküdür
# (bkz. methodology_fingerprint.py'nin AYNI _BACKEND_ROOT deseni).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FREEZE_MANIFEST_PATH = _BACKEND_ROOT.parent / "research" / "technical_v1_freeze_manifest.json"


def load_expected_scoring_config_hash(freeze_manifest_path: Path | None = None) -> str:
    """`research/technical_v1_freeze_manifest.json`'daki `methodology_
    identity.scoring_config_hash`'i döner. `freeze_manifest_path`
    yalnızca testlerde geçici bir fixture dosyasına yönlendirmek için
    opsiyoneldir -- production çağrısında verilmez (gerçek dondurulmuş
    dosya kullanılır). Dosyayı DEĞİŞTİRMEZ, yalnızca OKUR."""
    path = freeze_manifest_path if freeze_manifest_path is not None else _DEFAULT_FREEZE_MANIFEST_PATH
    with path.open(encoding="utf-8") as f:
        manifest = json.load(f)
    return manifest["methodology_identity"]["scoring_config_hash"]


def compute_observed_scoring_config_hash(config_repo: SystemConfigRepository) -> str:
    """`TechnicalAnalysisEngine.analyze_with_id()`'nin KENDİSİNİN kullandığı
    TAM AYNI çözümleme kalıbını (`app/engines/technical/engine.py`)
    yeniden kullanarak, ŞU AN Firestore'da GEÇERLİ olan skor config'inden
    deterministik hash'i üretir. `config_repo`, `SystemConfigRepository`
    ile aynı `get_raw(config_id) -> dict | None` sözleşmesine uyan HERHANGİ
    bir nesne olabilir (testlerde sahte/fake bir nesne enjekte edilir --
    bu fonksiyonun kendisi gerçek Firestore'a hiç dokunmaz, yalnızca
    verilen `config_repo`'yu çağırır)."""
    weights = resolve_indicator_weights(config_repo.get_raw("technical_indicator_weights"))
    family_weights = resolve_family_weights(config_repo.get_raw("technical_family_weights"))
    return compute_scoring_config_hash(weights, family_weights)
