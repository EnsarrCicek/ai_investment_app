"""Technical V1 metodoloji dosya-parmak-izi — HATA 12L/12M.

`app/research/resources/technical_v1_freeze_manifest.json`'daki `methodology_git_commit`
metodolojiyi bir GIT COMMIT'e sabitler; bu modül AYNI metodolojiyi, o
commit'ten SONRAKİ herhangi bir noktada (ör. evidence-capture çalışırken)
kaynak dosyaların GERÇEKTEN o an hangi bayt içeriğine sahip olduğunu
doğrulamak için bağımsız bir DOSYA-SEVİYESİ hash sağlar.

Kapsam (HATA 12L, "21" miscount'undan düzeltilmiş, doğrulanmış 27 benzersiz
dosya) dört gruba ayrılır:
  A) TECHNICAL_COMPUTATION (16) — skor/gösterge/yapı/sınıflandırma formülleri.
  B) TECHNICAL_INPUT_CONTRACT (9) — veri çekimi/tamamlanma/takvim/normalizasyon.
  C) TECHNICAL_MODEL_SCHEMA (1) — `TechnicalAnalysis` alan sözleşmesi.
  D) TECHNICAL_CONFIG_RESOLUTION (1) — Firestore config resolve/fail-fast mantığı.

KASITLI OLARAK HARİÇ: `repositories/technical_analysis_repository.py` —
yalnızca CACHE/PERSISTENCE katmanıdır, bir cache hit/miss'in oluşup
oluşmadığını etkiler ama fresh-compute DEĞERLERİNİ hiçbir zaman değiştirmez
(bkz. HATA 12L).

Altyapı-refactor kuralı (HATA 12L'de kilitlendi): bu dosyalardan birinin
BAYT içeriği değişmesi (ör. `engine.py`'nin HATA 12M dependency-injection
refactor'ü) OTOMATİK olarak Technical V2 anlamına GELMEZ — yalnızca eşlik
eden parity-test paketi başarısız olursa veya gözlemlenebilir davranış
kasıtlı olarak değiştirilirse V2 gerekir.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Proje kökü: bu dosya backend/app/research/methodology_fingerprint.py
# olduğundan üç seviye yukarısı backend/, dört seviye yukarısı repo köküdür.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

TECHNICAL_COMPUTATION_FILES: tuple[str, ...] = (
    "app/engines/technical/indicators.py",
    "app/engines/technical/market_structure.py",
    "app/engines/technical/support_resistance.py",
    "app/engines/technical/breakout.py",
    "app/engines/technical/breakout_timeline.py",
    "app/engines/technical/regime.py",
    "app/engines/technical/relative_strength.py",
    "app/engines/technical/relative_volume.py",
    "app/engines/technical/multi_timeframe.py",
    "app/engines/technical/gap_analysis.py",
    "app/engines/technical/candlestick_patterns.py",
    "app/engines/technical/signal_classifier.py",
    "app/engines/technical/horizon_classifier.py",
    "app/engines/technical/narrative.py",
    "app/engines/technical/scoring.py",
    "app/engines/technical/engine.py",
)

TECHNICAL_INPUT_CONTRACT_FILES: tuple[str, ...] = (
    "app/services/market_data/completed_bars.py",
    "app/services/market_data/trading_calendar.py",
    "app/services/market_data/bist_provider.py",
    "app/services/market_data/benchmark_service.py",
    "app/services/market_data/base.py",
    "app/engines/technical/history_window.py",
    "app/engines/technical/data_quality.py",
    "app/engines/technical/session_timing.py",
    "app/repositories/benchmark_cache_repository.py",
)

TECHNICAL_MODEL_SCHEMA_FILES: tuple[str, ...] = ("app/models/technical_analysis.py",)

TECHNICAL_CONFIG_RESOLUTION_FILES: tuple[str, ...] = ("app/repositories/system_config_repository.py",)

METHODOLOGY_FINGERPRINT_FILES: tuple[str, ...] = (
    TECHNICAL_COMPUTATION_FILES
    + TECHNICAL_INPUT_CONTRACT_FILES
    + TECHNICAL_MODEL_SCHEMA_FILES
    + TECHNICAL_CONFIG_RESOLUTION_FILES
)

EXPECTED_FILE_COUNT = 27

if len(METHODOLOGY_FINGERPRINT_FILES) != EXPECTED_FILE_COUNT:
    raise AssertionError(
        f"METHODOLOGY_FINGERPRINT_FILES {len(METHODOLOGY_FINGERPRINT_FILES)} dosya içeriyor, "
        f"beklenen {EXPECTED_FILE_COUNT} (HATA 12L doğrulanmış liste)"
    )

if len(set(METHODOLOGY_FINGERPRINT_FILES)) != len(METHODOLOGY_FINGERPRINT_FILES):
    raise AssertionError("METHODOLOGY_FINGERPRINT_FILES içinde yinelenen (duplicate) bir yol var")


def _resolve(relative_path: str) -> Path:
    return _BACKEND_ROOT / relative_path


def compute_file_hashes(
    relative_paths: tuple[str, ...] = METHODOLOGY_FINGERPRINT_FILES,
    root: Path | None = None,
) -> dict[str, str]:
    """Her dosyanın HAM (raw) baytlarının SHA-256 hex digest'ini döner.

    `root` yalnızca testlerde geçici bir fixture dizinine yönlendirmek için
    opsiyoneldir -- production çağrısında verilmez (gerçek `_BACKEND_ROOT`
    kullanılır).
    """
    base = root if root is not None else _BACKEND_ROOT
    hashes: dict[str, str] = {}
    for rel_path in relative_paths:
        file_path = base / rel_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Metodoloji parmak-izi dosyası bulunamadı: {rel_path}")
        raw_bytes = file_path.read_bytes()
        hashes[rel_path] = hashlib.sha256(raw_bytes).hexdigest()
    return hashes


def compute_methodology_source_fingerprint(
    relative_paths: tuple[str, ...] = METHODOLOGY_FINGERPRINT_FILES,
    root: Path | None = None,
) -> str:
    """`compute_file_hashes()`'in kanonik (sort_keys) JSON serileştirmesinin
    SHA-256'sı -- tek bir birleşik metodoloji-parmak-izi string'i.

    `compute_scoring_config_hash()`'teki (scoring.py) AYNI kanonikleştirme
    deseni: `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
    """
    file_hashes = compute_file_hashes(relative_paths, root=root)
    canonical = json.dumps(file_hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
