"""Skorlama öncesi zorunlu veri kalite kontrolleri (hard-veto).

TECHNICAL_ANALYSIS_RESEARCH1.md'nin en çok vurguladığı noktalardan biri:
eksik/bayat/tutarsız veri üzerinden üretilen bir TechnicalScore, YANLIŞ ama
kendinden emin görünen bir sinyaldir — bu, hiç sinyal üretmemekten daha
kötüdür. Bu yüzden bu kontroller skorlama mantığı (engine.py) BAŞLAMADAN
önce, ayrı ve merkezi bir yerde çalışır; hem TechnicalAnalysisEngine hem de
BacktestEngine aynı fonksiyonu kullanır (canlı sistemle aynı davranış
sözleşmesi — bkz. backtest/engine.py modül docstring'i).

Kapsam (ilk sürüm): eksik sütun, yetersiz geçmiş, son bar'da eksik OHLCV
değeri, bayat veri (son bar günümüzden çok uzaksa). Spread/likidite/post-news
gap gibi ek veto koşulları ileride ayrı aşamalarda eklenecek (bkz. rapor
madde 7 — geliştirme sırası).
"""

from datetime import datetime, timezone

import pandas as pd

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# BIST hafta sonu (Cts-Paz) kapalı; +1-2 gün resmi tatil toleransı için 5 gün.
DEFAULT_MAX_STALENESS_DAYS = 5


class DataQualityError(ValueError):
    """ValueError'dan türer: mevcut API katmanlarındaki `except ValueError`
    yakalama noktaları hiçbir değişiklik gerektirmeden bunu da yakalar.
    `reason_code`, ileride istemci tarafında veya loglarda hangi veto
    koşulunun tetiklendiğini ayırt edebilmek için eklendi.
    """

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(message)


def check_data_quality(
    df: pd.DataFrame,
    symbol: str,
    min_history_days: int,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    now: datetime | None = None,
) -> None:
    """Herhangi bir kontrol başarısız olursa DataQualityError fırlatır, aksi halde sessizce döner."""
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise DataQualityError(
            "MISSING_COLUMNS", f"'{symbol}' için eksik sütun(lar): {missing_columns}"
        )

    if len(df) < min_history_days:
        raise DataQualityError(
            "INSUFFICIENT_HISTORY",
            f"'{symbol}' için yeterli geçmiş veri yok ({len(df)} gün, en az {min_history_days} gerekli)",
        )

    last_row = df.iloc[-1]
    if last_row[REQUIRED_COLUMNS].isna().any():
        raise DataQualityError(
            "MISSING_OHLCV", f"'{symbol}' için son bar eksik OHLCV değeri içeriyor"
        )

    reference_now = pd.Timestamp(now or datetime.now(timezone.utc))
    if reference_now.tzinfo is None:
        reference_now = reference_now.tz_localize("UTC")

    last_bar_date = df.index[-1]
    if last_bar_date.tzinfo is None:
        last_bar_date = last_bar_date.tz_localize("UTC")

    staleness_days = (reference_now - last_bar_date).days
    if staleness_days > max_staleness_days:
        raise DataQualityError(
            "STALE_DATA",
            f"'{symbol}' için veri bayat (son bar {staleness_days} gün önce, "
            f"en fazla {max_staleness_days} gün izin veriliyor)",
        )
