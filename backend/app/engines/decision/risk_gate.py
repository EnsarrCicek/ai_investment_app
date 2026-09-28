"""MARKET-RISK-1 — gölge risk kapısı ("kapı etkin olsaydı ne olurdu?").

ÜRETİME BAĞLI DEĞİLDİR: DecisionEngine, bildirimler ve kayıtlı kararlar bu
modülü çağırmaz. Ham karar hiçbir koşulda değiştirilmez; kapı ayrı bir sonuç
üretir:
  ALLOWED        — kapı AL yönünü engellemiyor (kendi başına AL önerisi değil).
  BLOCKED        — AL yönlü ham karar risk nedeniyle engellenirdi.
  INDETERMINATE  — zorunlu risk verileriyle değerlendirme yapılamıyor.
  NOT_APPLICABLE — ham karar AL yönlü değil.
Karar üç durumlu kural sonucundan verilir: bir değerlendirme kesin tetiklendiyse
BLOCKED; hiçbiri kesin tetiklenmedi ama biri belirlenemediyse (gerekli bir kural
hesaplanamadı) INDETERMINATE; ikisi de kesin "tetiklenmedi" ise ALLOWED.
Engellenen AL, SAT'a veya TUT'a DÖNÜŞTÜRÜLMEZ; pozisyon bilgisi kullanılmaz ve
satış talimatı üretilmez. Kapı skoru hiç okumaz: güçlü bir skor bir risk
tetiklemesini aşamaz. Veri yeterliliği ve risk durumu her sonuçta görünür kalır.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engines.decision.engine import _DIRECTION_BY_CLASSIFICATION
from app.engines.risk.shadow_inputs import RISK_TRIGGERED, UNDETERMINED, RiskAssessment

ALLOWED = "ALLOWED"
BLOCKED = "BLOCKED"
INDETERMINATE = "INDETERMINATE"
NOT_APPLICABLE = "NOT_APPLICABLE"

# AL yönlü sınıflar mevcut tek eşlemeden türetilir (kopya liste tutulmaz).
BUY_DIRECTION_CLASSES = frozenset(k for k, v in _DIRECTION_BY_CLASSIFICATION.items() if v == "POSITIVE")


@dataclass(frozen=True)
class ShadowGateResult:
    raw_decision: str
    gate_outcome: str
    reason_codes: tuple[str, ...]
    market: RiskAssessment
    asset: RiskAssessment
    binding: str = "SHADOW_NOT_BOUND_TO_PRODUCTION"


def evaluate_shadow_risk_gate(raw_decision: str, market: RiskAssessment, asset: RiskAssessment) -> ShadowGateResult:
    if raw_decision not in _DIRECTION_BY_CLASSIFICATION:
        raise ValueError(f"bilinmeyen karar sınıfı: {raw_decision!r}")
    assessments = (market, asset)
    triggered = [a for a in assessments if a.risk_status == RISK_TRIGGERED]
    undetermined = [a for a in assessments if a.risk_status == UNDETERMINED]

    if raw_decision not in BUY_DIRECTION_CLASSES:
        outcome, reasons = NOT_APPLICABLE, ()
    elif triggered:
        # Tek bir tetiklenmiş değerlendirme engellemeye yeter; diğerinin verisi eksik olsa bile.
        outcome = BLOCKED
        reasons = tuple(f"{a.scope}:{code}" for a in triggered for code in a.reason_codes)
    elif undetermined:
        outcome = INDETERMINATE
        reasons = tuple(f"{a.scope}:{code}" for a in undetermined for code in a.data_reason_codes)
    else:
        outcome, reasons = ALLOWED, ()
    return ShadowGateResult(raw_decision=raw_decision, gate_outcome=outcome, reason_codes=reasons, market=market, asset=asset)
