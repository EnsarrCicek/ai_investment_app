"""MARKET-RISK-1 (gölge mod) — ortak veri sözleşmesi ve deneysel parametreler.

Değerlendiriciler yalnızca kendilerine VERİLEN günlük kapanış serileri üzerinde
çalışır: ağ, Firestore, ortam değişkeni veya gizli veri çağrısı YOKTUR.

Veri sözleşmesi (`validate_daily_closes`):
  * Girdi, seans tarihine göre indekslenmiş kapanış serisidir. Barların
    TAMAMLANMIŞ olduğunu çağıran garanti eder (ör. `completed_bars`
    filtresinden geçmiş seri); değerlendirici gün içi durumu bilemez.
  * `as_of_session` (T) sonrasındaki satırlar değerlendirmeye HİÇ girmez.
  * T bir beklenen BIST seansı olmalı ve seride bulunmalı (yoksa eski/eksik).
  * T'ye kadar son `required_sessions` beklenen seansın HEPSİ bulunmalı;
    eksik seans ileri doldurulmaz. Tekrarlı tarih, NaN/sonsuz/pozitif olmayan
    değer veya takvimin desteklemediği yıl -> veri yetersiz.
  * Hisse ve endeks aynı beklenen seans listesine göre denetlendiğinden,
    ikisi de yeterliyse tarihleri hizalıdır.

Parametreler DOĞRULANMAMIŞ araştırma parametreleridir; üretim varsayılanı
yoktur (değerlendiriciler parametre setini açıkça ister) ve üretim kararına
bağlı değildir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from app.services.market_data.trading_calendar import expected_trading_sessions

SUFFICIENT = "SUFFICIENT"
INSUFFICIENT = "INSUFFICIENT"
RISK_TRIGGERED = "RISK_TRIGGERED"
NO_RULE_TRIGGERED = "NO_DEFINED_RULE_TRIGGERED"  # güvenli olduğu anlamına gelmez
NOT_EVALUATED = "NOT_EVALUATED"
EVALUATED = "EVALUATED"
PARTIAL = "PARTIAL"
UNDETERMINED = "UNDETERMINED"  # veto ne kanıtlandı ne dışlandı (gerekli bir kural hesaplanamadı)
# Uygulama sürümü (eşiklerden AYRI): her kural yalnızca kendi verisiyle ve üç
# durumlu (Doğru/Yanlış/Bilinmiyor) AND/OR ile değerlendirilir.
RULE_LOGIC_VERSION = "per-rule-three-valued-v1"
# Ölçümler eşiklerle karşılaştırılmadan önce bu hassasiyete yuvarlanır; böylece
# "eşik dahil" kuralı ikili kayan nokta artıklarından etkilenmez.
MEASURE_DECIMALS = 6


@dataclass(frozen=True)
class ShadowRiskParams:
    """Sınır davranışı: düşüş/kayıp eşikleri DAHİL (>=), yüzdelik eşiği DAHİL (>=),
    trend kuralı KESİN (kapanış < SMA). Birleşim kuralları sürüme bağlıdır:
      piyasa: DRAWDOWN VE (VOLATİLİTE VEYA TREND)
      hisse : (DÖNEM KAYBI VE ENDEKSE GÖRE ZAYIFLIK) VEYA SERT GÜNLÜK DÜŞÜŞ
    """

    version: str
    market_high_lookback: int
    market_drawdown_trigger_pct: float
    market_vol_window: int
    market_vol_percentile_window: int
    market_vol_percentile_trigger: float
    market_trend_window: int
    asset_drop_window: int
    asset_drop_trigger_pct: float
    asset_relative_window: int
    asset_relative_underperformance_trigger_pct: float
    asset_sharp_daily_drop_trigger_pct: float

    def required_market_sessions(self) -> int:
        # T dahil: zirve penceresi, SMA penceresi ve (volatilite penceresi +
        # yüzdelik geçmişi) için gereken kapanış sayısının en büyüğü.
        return max(
            self.market_high_lookback,
            self.market_trend_window,
            self.market_vol_window + self.market_vol_percentile_window,
        )

    def required_asset_sessions(self) -> int:
        # N seanslık getiri N+1 kapanış ister; günlük getiri 2 kapanış.
        return max(self.asset_drop_window, self.asset_relative_window, 1) + 1


# Deneysel örnek set — doğrulanmamış, IEYHO veya herhangi bir olaya bakılarak
# ayarlanmamış; üretim varsayılanı DEĞİLDİR.
EXPERIMENTAL_PARAMS_V0 = ShadowRiskParams(
    version="market-risk-shadow-experimental-v0",
    market_high_lookback=20,
    market_drawdown_trigger_pct=8.0,
    market_vol_window=20,
    market_vol_percentile_window=250,
    market_vol_percentile_trigger=90.0,
    market_trend_window=50,
    asset_drop_window=5,
    asset_drop_trigger_pct=15.0,
    asset_relative_window=20,
    asset_relative_underperformance_trigger_pct=10.0,
    asset_sharp_daily_drop_trigger_pct=9.5,
)


@dataclass(frozen=True)
class ValidatedCloses:
    status: str
    reason_codes: tuple[str, ...]
    closes: pd.Series | None  # T'de biten, tam `required_sessions` uzunluğunda


@dataclass(frozen=True)
class RiskAssessment:
    scope: str
    as_of_session: date
    params_version: str
    required_sessions: int
    data_status: str
    data_reason_codes: tuple[str, ...]
    risk_status: str
    reason_codes: tuple[str, ...]
    measures: dict = field(default_factory=dict)
    rules: tuple = ()
    logic_version: str = RULE_LOGIC_VERSION


@dataclass(frozen=True)
class RuleResult:
    """Tek bir kuralın sonucu: `triggered` None ise kural hesaplanamadı."""

    rule: str
    status: str  # EVALUATED | NOT_EVALUATED
    triggered: bool | None
    required_sessions: int
    missing_reasons: tuple[str, ...] = ()
    measure: float | bool | None = None


def kleene_and(*values: bool | None) -> bool | None:
    # Girdiler Python bool/None olmalı (numpy bool `is True` testini geçmez).
    if any(v is False for v in values):
        return False
    return True if all(v is True for v in values) else None


def kleene_or(*values: bool | None) -> bool | None:
    if any(v is True for v in values):
        return True
    return False if all(v is False for v in values) else None


def build_assessment(scope, as_of_session, params_version, rules, composite, measures) -> "RiskAssessment":
    evaluated = [r for r in rules if r.status == EVALUATED]
    data_status = SUFFICIENT if len(evaluated) == len(rules) else (PARTIAL if evaluated else INSUFFICIENT)
    risk_status = {True: RISK_TRIGGERED, False: NO_RULE_TRIGGERED, None: UNDETERMINED}[composite]
    return RiskAssessment(
        scope=scope, as_of_session=as_of_session, params_version=params_version,
        required_sessions=max(r.required_sessions for r in rules),
        data_status=data_status,
        data_reason_codes=tuple(f"{r.rule}:{m}" for r in rules for m in r.missing_reasons),
        risk_status=risk_status,
        reason_codes=tuple(r.rule for r in rules if r.triggered is True),
        measures=measures,
        rules=tuple(rules),
    )


def _to_session_index(series: pd.Series) -> pd.Series:
    index = pd.Index([pd.Timestamp(value).date() for value in series.index])
    return pd.Series(series.to_numpy(), index=index)


def validate_daily_closes(closes: pd.Series | None, as_of_session: date, required_sessions: int) -> ValidatedCloses:
    if closes is None or len(closes) == 0:
        return ValidatedCloses(INSUFFICIENT, ("NO_DATA",), None)
    series = _to_session_index(closes)
    if series.index.has_duplicates:
        return ValidatedCloses(INSUFFICIENT, ("DUPLICATE_SESSIONS",), None)
    series = series.sort_index()
    series = series[series.index <= as_of_session]  # T sonrası hiçbir satır kullanılmaz

    # Gereken seans sayısını kapsayacak kadar geriye bak (tatiller dahil pay).
    lookback_days = required_sessions * 2 + 30
    expected = expected_trading_sessions(as_of_session - timedelta(days=lookback_days), as_of_session)
    if expected is None:
        return ValidatedCloses(INSUFFICIENT, ("CALENDAR_UNSUPPORTED",), None)
    if not expected or expected[-1] != as_of_session:
        return ValidatedCloses(INSUFFICIENT, ("AS_OF_NOT_EXPECTED_SESSION",), None)
    if as_of_session not in series.index:
        return ValidatedCloses(INSUFFICIENT, ("AS_OF_SESSION_MISSING",), None)
    needed = expected[-required_sessions:]
    if len(needed) < required_sessions:
        return ValidatedCloses(INSUFFICIENT, ("CALENDAR_WINDOW_TOO_SHORT",), None)
    missing = [d for d in needed if d not in series.index]
    if missing:
        return ValidatedCloses(INSUFFICIENT, ("MISSING_EXPECTED_SESSIONS",), None)
    window = series.loc[needed].astype(float)
    if not all(math.isfinite(v) and v > 0 for v in window.to_numpy()):
        return ValidatedCloses(INSUFFICIENT, ("NON_FINITE_OR_NON_POSITIVE_CLOSE",), None)
    return ValidatedCloses(SUFFICIENT, (), window)


def pct_change_over(closes: pd.Series, sessions: int) -> float:
    return round((closes.iloc[-1] / closes.iloc[-1 - sessions] - 1.0) * 100.0, MEASURE_DECIMALS)
