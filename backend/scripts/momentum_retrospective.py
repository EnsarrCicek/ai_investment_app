"""Erken momentum motorunun geçmiş gün içi veride bar bar (gelecek verisi olmadan) değerlendirmesi.

Salt-okunur: Yahoo'dan sembol başına TEK gün içi istek (5m, son 60 gün) ve isteğe bağlı Firestore haber OKUMASI.
Hiçbir şey yazılmaz. Her değerlendirme anı T için motor yalnız `T − gecikme` anına kadar tamamlanmış barları ve T'de
yayınlanmış + mevcut olan haber analizlerini görür (motorun kendi kuralı).

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_retrospective.py KTLEV 2026-10-01 2026-10-12 [--controls A,B,C] [--news]
"""

import argparse
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines.technical.session_timing import ISTANBUL_TZ  # noqa: E402
from app.models import momentum_alert as ma  # noqa: E402
from app.services.market_data.trading_calendar import expected_trading_sessions  # noqa: E402
from app.services.momentum.early_momentum_engine import DEFAULT_CONFIG, evaluate  # noqa: E402
from app.services.momentum.intraday_provider import YahooIntradayProvider  # noqa: E402


def load_events(symbol):
    from app.repositories.news_analysis_repository import NewsAnalysisRepository
    from app.repositories.news_raw_repository import NewsRawRepository
    from app.services.momentum.scanner import catalyst_events

    analyses = NewsAnalysisRepository().list_for_asset(symbol, limit=None)
    raws = NewsRawRepository().get_many([a.news_id for a in analyses]) if analyses else {}
    return catalyst_events(analyses, raws)


def run(symbol, start, end, delay_minutes, events, bars, sessions_window=15, overrides=None):
    """Her T için motora canlı tarayıcıyla aynı pencere verilir: T gününe kadarki son `sessions_window` seans
    (canlı `period="15d"`). Pencere seçimi yalnız T'nin TARİHİNE bakar; T'den sonraki barları motor zaten dışlar."""
    config = DEFAULT_CONFIG.model_copy(update={"provider_delay_minutes": delay_minutes, **(overrides or {})})
    df = bars.bars.copy()
    df.index = df.index.tz_convert(ISTANBUL_TZ)
    days = sorted(set(df.index.date))
    rows = []
    for day in expected_trading_sessions(start, end) or []:
        window_days = [d for d in days if d <= day][-sessions_window:]
        window = df[(df.index.date >= window_days[0]) & (df.index.date <= day)] if window_days else df.iloc[0:0]
        t = datetime.combine(day, time(10, 0), tzinfo=ISTANBUL_TZ)
        stop = datetime.combine(day, time(18, 0), tzinfo=ISTANBUL_TZ) + timedelta(minutes=delay_minutes)
        while t < stop:
            rows.append((t, evaluate(symbol, window, bars.provenance, t, config, events)))
            t += timedelta(minutes=5)
    return rows


def prev_close(bars, day):
    prior = bars[bars.index.date < day]
    return float(prior["Close"].iloc[-1]) if len(prior) else None


def summarize(symbol, rows, bars, label):
    print(f"\n=== {symbol} ({label}) ===")
    by_day = {}
    for t, r in rows:
        by_day.setdefault(t.date(), []).append((t, r))
    for day, items in by_day.items():
        pc = prev_close(bars, day)
        day_bars = bars[bars.index.date == day]
        day_close = float(day_bars["Close"].iloc[-1]) if len(day_bars) else None
        statuses = Counter(r.status for _, r in items)
        line = f"{day}  prev_close={pc}  day_close={day_close}  statuses={dict(statuses)}"
        for level in (ma.LEVEL_WATCH, ma.LEVEL_STRONG):
            hit = next(((t, r) for t, r in items if r.level in (level, ma.LEVEL_STRONG)
                        if level == ma.LEVEL_WATCH or r.level == ma.LEVEL_STRONG), None)
            if hit:
                t, r = hit
                price = r.metrics.get("last_close")
                from_prev = (price / pc - 1) * 100 if pc else None
                done = ((price - pc) / (day_close - pc) * 100) if pc and day_close and day_close != pc else None
                def fmt(v, spec):
                    return format(v, spec) if v is not None else "n/a"
                line += (f"\n    first {level}: eval {t:%H:%M} (bar end {r.signal_as_of.astimezone(ISTANBUL_TZ):%H:%M})"
                         f" price={price} vs_prev_close={fmt(from_prev, '+.2f')}% day_move_done={fmt(done, '.0f')}%"
                         f" score={r.momentum_score} comps={ {k: v for k, v in r.components.items() if v} }"
                         f" relvol={r.metrics.get('relative_volume')} breakout={r.metrics.get('breakout_distance_pct')}"
                         f" range={r.metrics.get('range_ratio')} catalyst_events={r.metrics.get('catalyst_events')}")
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("end", type=date.fromisoformat)
    ap.add_argument("--controls", default="")
    ap.add_argument("--news", action="store_true")
    ap.add_argument("--delays", default="15,0")
    ap.add_argument("--override", action="append", default=[], help="yapılandırma alanı=değer (ör. watch_score=55)")
    args = ap.parse_args()
    provider = YahooIntradayProvider()
    overrides = {k: float(v) for k, v in (o.split("=", 1) for o in args.override)}
    for symbol in [args.symbol] + [s for s in args.controls.split(",") if s]:
        bars = provider.get_intraday(symbol, interval="5m", period="60d")
        events = load_events(symbol) if args.news else None
        df = bars.bars.copy()
        df.index = df.index.tz_convert(ISTANBUL_TZ)
        for delay in (int(x) for x in args.delays.split(",")):
            summarize(symbol, run(symbol, args.start, args.end, delay, events, bars, overrides=overrides), df,
                      f"gecikme {delay} dk" + (" (Yahoo gerçekçi)" if delay else " (gerçek zamanlı akış varsayımı)"))


if __name__ == "__main__":
    main()
