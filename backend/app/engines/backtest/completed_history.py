"""Backtest'e özel completed-session-only veri hazırlama katmanı — HATA 3B (26.08.2026).

HATA 3B denetiminde kanıtlandı: `BacktestEngine`/`WalkForwardOptimizer`,
`self._provider.get_history(symbol, period=period)`'i HİÇBİR filtre
uygulamadan doğrudan `technical_score_series()`/`simulate()`'e veriyordu.
Piyasa açıkken bu, Yahoo'nun hâlâ oluşmakta olan ("partial"/developing)
bugünkü günlük barının hem skor hesaplamasına HEM DE (HATA 3A'nın
execution modeli sayesinde) potansiyel olarak execution/terminal
mark-to-market'e sızmasına yol açıyordu — canlı ölçümle kanıtlandı
(GARAN/ASELS'te açık pozisyonun `unrealized_return_pct`'i dakikalar
içinde işaret bile değiştirebiliyordu).

KESİN SÖZLEŞME (kullanıcı kararı, 26.08.2026): Backtest, canlı/paper-trading
DEĞİLDİR — yalnızca TAMAMLANMIŞ günlük seanslar üzerinde çalışır
("COMPLETED_DAILY_ONLY"). Piyasa açıkken bugünün satırı (Open/High/Low/
Close/Volume — HİÇBİR alanı, "Open zaten sabit" gibi bir istisna dahi
YAPILMADAN) backtest'e hiç girmez. Bilinçli olarak REDDEDİLEN alternatif:
"partial günün Close'unu skordan çıkar ama Open'ını execution için kullan"
hibrit modeli — bu, historical backtest ile live/paper execution'ı
karıştırır; live/paper portföy ayrı, gelecekteki bir özelliktir.

Bu modül, `filter_completed_daily_bars()` (HATA 2A, `completed_bars.py`)
ve `check_data_quality()` (`data_quality.py`) çağrılarını TEK bir yerde
birleştirir — üç ayrı canlı giriş noktasının (`BacktestEngine.run()`,
`BacktestEngine.compare_strategies()`, `WalkForwardOptimizer.run()`)
aynı mantığı kopyala-yapıştır ile birbirinden bağımsız (ve zamanla
birbirinden sapabilecek) şekilde tekrarlamasını önler.

ÖNEMLİ: `check_data_quality`'nin `min_history_days` kontrolü RAW history
üzerinde DEĞİL, FİLTRELENMİŞ (completed-only) history üzerinde çalışır —
piyasa açıkken bugünün partial barı "eksik geçmiş" şartını sahte şekilde
karşılayamaz (ör. raw=60 bar, 1'i partial → completed=59 → INSUFFICIENT_HISTORY).
"""

from datetime import date, datetime

import pandas as pd

from app.engines.technical.data_quality import check_data_quality
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.completed_bars import filter_completed_daily_bars


def prepare_backtest_history(
    provider: MarketDataProvider,
    symbol: str,
    period: str,
    min_history_days: int,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, date]:
    """Ham geçmişi çeker, TAMAMLANMAMIŞ ("bugünkü") günlük barı çıkarır,
    kalite kontrolünü FİLTRELENMİŞ seri üzerinde yapar.

    Döner: `(completed_history, backtest_data_as_of)` — ikincisi,
    backtest'in fiilen hesaba kattığı EN SON tamamlanmış günün tarihidir
    (sonuçlara `backtest_data_as_of` alanı olarak şeffaf şekilde eklenir).
    """
    raw_history = provider.get_history(symbol, period=period)
    completed_history = filter_completed_daily_bars(raw_history, now=now)
    check_data_quality(completed_history, symbol, min_history_days=min_history_days, now=now)
    backtest_data_as_of = completed_history.index[-1].date()
    return completed_history, backtest_data_as_of
