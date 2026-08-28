"""BacktestEngine — AŞAMA 28.

Geçmiş fiyat verisi üzerinde DecisionEngine'in ürettiği AL/ZAYIF AL/TUT/
ZAYIF SAT/SAT sinyallerine göre basit bir "sinyalde pozisyon aç/kapat"
stratejisi simüle edilir.

Kapsam kararı: Yalnızca technical_score kullanılır. news_score ve macro_score
için günlük geçmiş serisi saklanmıyor (news_analyses/macro_snapshots yalnızca
"o an geçerli olan" analiz/anlık görüntüyü tutuyor, ana doküman kural 6) —
bu yüzden geçmişe dönük backtest'te noktasal (point-in-time) olarak
kullanılamazlar. DecisionEngine'in "Missing
Data Davranışı" ilkesi sayesinde bu, kararın YANLIŞ olmasına değil, mevcut
tek skorun ağırlığının otomatik %100'e normalize edilmesine yol açar —
canlı sistemle aynı davranış sözleşmesi.

Not: Buradaki skor formülü, TechnicalAnalysisEngine.analyze_with_id ile
birebir aynı olacak şekilde elle senkronize tutulur (ikisi de aynı
indicators.py fonksiyonlarını kullanır). Vektörize (tüm seri için tek
seferde) hesaplanması gerektiğinden — canlı motor yalnızca son günü
hesapladığından — ortak bir yardımcıya taşımak yerine burada ayrı,
küçük bir fonksiyon olarak tutuldu.

25.08.2026 (HATA 3A) — EXECUTION MODELİ: NEXT_SESSION_OPEN.
Önceki sürüm sinyali T gününün Close'undan ÜRETİP yine AYNI T gününün
Close'undan EXECUTE ediyordu (same-bar execution bias — HATA 3 denetiminde
kanıtlandı: canlıda T'nin Close'u ancak seans kapandıktan SONRA bilinir,
o anda artık o fiyattan işlem yapılamaz). Artık sözleşme şudur:

    Signal[T]  = T'nin TAMAMLANMIŞ Close'undan üretilir (T Close ↓)
    Execution  = T+1 seansının Open'ında gerçekleşir (pending signal ↓ Open[T+1])

BUY ve SELL için AYNI kural — hiçbir taraf kayırılmıyor. Sonuç olarak:
- BUY'da Close[T]→Open[T+1] gece hareketi ("overnight gap") yatırımcıya
  AİT DEĞİLDİR (pozisyon henüz yok).
- SELL'de aynı gece hareketi yatırımcıya AİTTİR (pozisyon T+1 açılışına
  kadar hâlâ elde tutuluyor).
Sentetik testlerle (gap-up/gap-down × BUY/SELL) doğrulandı, bkz.
tests/test_backtest_engine.py.

Son bardaki YENİ bir sinyal için T+1 barı yoksa (`unexecuted_signal`,
reason="NO_NEXT_BAR") ya da T+1'in Open'ı geçersizse (NaN/inf/<=0,
`skipped_executions`, reason="INVALID_NEXT_OPEN") — HİÇBİR ZAMAN Close'a
sahte bir fallback YAPILMAZ; bilinmeyen bir execution fiyatı UYDURULMAZ.

Backtest sonunda hâlâ açık bir pozisyon varsa (gerçekten execute edilmiş
bir BUY'dan sonra hiç SELL sinyali gelmemişse) bu GERÇEK bir SELL execution
DEĞİLDİR — `trades[]`'e sahte bir kapanış kaydı EKLENMEZ, yalnızca
`open_position` alanında mark-to-market (`cash + shares * final_close`)
olarak ayrı raporlanır. `trades[]` bundan böyle SADECE gerçek BUY execution
+ gerçek SELL execution çifti olan (closed round-trip) işlemleri içerir —
`trade_count`/`win_rate_pct` bu closed-trade listesinden hesaplanır, AMA
`total_return_pct`/`final_equity`/`equity_curve`/`max_drawdown_pct` açık
pozisyonun gerçekleşmemiş (unrealized) kâr/zararını İÇERİR (bu iki grup
metriğin farklı taban aldığı bilinçli bir tasarım — bkz. TEKNIK_ANALIZ_
METODOLOJISI.md).

Eski `entry_date`/`exit_date`/`entry_price`/`exit_price` alanları
KORUNDU (backward compatibility — Flutter `BacktestTrade` bu adları
sabit okuyor) ama semantikleri artık AÇIKÇA execution an/fiyatıdır
(`entry_date == entry_execution_date`, vb.) — sinyal an/fiyatı ayrıca
`entry_signal_date`/`entry_signal_price`/`exit_signal_date`/
`exit_signal_price` alanlarında EK olarak taşınır.

26.08.2026 (HATA 3B) — VERİ SÖZLEŞMESİ: COMPLETED_DAILY_ONLY.
Kanıtlandı: `run()`/`compare_strategies()` piyasa açıkken ham (partial/
developing) "bugünkü" barı hiç filtrelemeden `technical_score_series()`'e
veriyordu — bu hem skoru hem (açık bir pozisyon varsa) terminal mark-to-
market'i dakikalar içinde değişen, kararsız bir değere bağlıyordu. Karar
(kullanıcı, 26.08.2026): backtest canlı/paper-trading DEĞİLDİR — yalnızca
TAMAMLANMIŞ günlük seanslar kullanılır. Bilinçli olarak REDDEDİLEN
alternatif: "partial günün Close'unu skordan çıkar ama Open'ını execution
için kullan" hibrit modeli (Open'ın gün içinde sabit kaldığı ölçüldü, ama
bu ayrım historical backtest'i live/paper execution ile karıştırır).
`self._provider.get_history(...)`'nin çıktısı artık DOĞRUDAN kullanılmaz —
bkz. `completed_history.prepare_backtest_history()`: ham veri
`filter_completed_daily_bars()`'tan (HATA 2A) geçirilir, `check_data_quality`
(`MIN_HISTORY_DAYS` dahil) bu FİLTRELENMİŞ seri üzerinde çalışır. Sonuç
sözlüğüne `backtest_data_as_of` (kullanılan son tamamlanmış barın tarihi)
ve `data_policy: "COMPLETED_DAILY_ONLY"` eklendi — eski (bu değişiklikten
önceki, partial bar'a maruz) sonuçlardan ayırt edilebilmesi için. HATA 3A'nın
`NEXT_SESSION_OPEN` sözleşmesi (`simulate()`) HİÇ DEĞİŞMEDİ — yalnızca artık
her zaman completed-only bir seri görüyor; son tamamlanmış barda oluşan bir
sinyal için backtest ufkunda henüz bir T+1 yoksa (piyasa hâlâ açıksa) bu
zaten mevcut `unexecuted_signal`/`NO_NEXT_BAR` yoluyla doğru şekilde
yakalanıyor (aynı backtest, T+1 tamamlandıktan sonra yeniden çalıştırılırsa
o sinyal artık normal şekilde execute edilir).

27.08.2026 (HATA 5A) — EXTERNAL 60-SESSION WARM-UP. Kanıtlandı: `df.iloc[
MIN_HISTORY_DAYS:]` deseni (eski `run()`/`compare_strategies()`), indicator
warm-up'ını (60 bar, RSI/MACD/EMA/.../ROC ısınması) İSTENEN BACKTEST
PENCERESİNİN KENDİ İLK 60 SATIRINDAN kesiyordu — "1y" istendiğinde gerçek
simülasyon, istenen pencerenin ilk ~3 ayını (60 işlem günü) HİÇ görmeden
başlıyordu. Gerçek 5-sembol/3-periyot ölçümle kanıtlandı: bu,
`total_return_pct`'in İŞARETİNİ BİLE değiştirebiliyordu. `MIN_HISTORY_DAYS`
KALDIRILDI — warm-up artık `completed_history.prepare_backtest_history()`
içinde AYRICA, istenen pencerenin DIŞINDAN fetch edilir
(`INDICATOR_WARMUP_SESSIONS=60`, DEĞER AYNI, yalnızca KONUMU düzeltildi):
`prepared.indicator_history` (warmup+simulation) `technical_score_series()`'e
girer, sonuç `prepared.simulation_history`'nin (yalnız istenen pencere)
tarihlerine `.loc[]` ile kırpılır — `simulate()`'e YALNIZ bu kırpılmış seri
verilir. `technical_score_series()`/`simulate()`'in KENDİ formülleri/
ağırlıkları HİÇ DEĞİŞMEDİ; `NEXT_SESSION_OPEN` (HATA 3A) sözleşmesi de HİÇ
DEĞİŞMEDİ. Yeni sonuç alanları: `simulation_start`, `warmup_history_start`,
`indicator_warmup_sessions`, `actual_indicator_history_start` (bkz.
`completed_history.PreparedBacktestHistory`). Eski kayıtlar/API tüketicileri
(`requested_window_start`/`actual_history_start`/`from_date`/`to_date`)
KIRILMADI — yalnızca `from_date`'in NEYE eşit olduğu düzeldi (artık
`simulation_start`, `warmup_history_start + 60 session` DEĞİL).
"""

import math
from datetime import datetime, timezone

import pandas as pd

from app.engines.backtest.completed_history import prepare_backtest_history
from app.engines.decision.engine import DEFAULT_THRESHOLDS, _classify
from app.engines.technical import indicators as ind
from app.engines.technical.engine import DEFAULT_WEIGHTS as DEFAULT_TECHNICAL_WEIGHTS
from app.engines.technical.scoring import aggregate_available_components_series, clamp_components_df
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider
from app.services.market_data.trading_calendar import session_normalization_to_dict


def technical_score_series(df: pd.DataFrame, weights: dict) -> pd.Series:
    """HATA 5B1 (27.08.2026): bileşen formülleri (RSI/MACD/EMA/Bollinger/
    Momentum/ROC) DEĞİŞMEDİ — yalnızca eksik/tanımsız bir bileşenin nasıl
    ele alındığı değişti. Eskiden `.fillna(0.0)` (5/7 bileşen) bunu SESSİZCE
    "geçerli nötr 0" sayıyordu (weight_sum'da payı KORUNARAK, yani skoru
    seyrelterek); RSI/ROC ise hiç doldurulmuyordu (NaN tüm günü zehirliyordu).
    Artık HİÇBİR component'e `.fillna(0.0)` UYGULANMAZ — ham (unclamped) oran
    NaN/±inf ise `aggregate_available_components_series()` o günün o
    bileşenini numerator'dan VE weight denominator'dan ÇIKARIP KALAN mevcut
    bileşenlerin ağırlığını renormalize eder (bkz. `scoring.py` modül
    docstring'i). `ATR==0`/`band_width==0` gibi eski `.replace(0, pd.NA)`
    kısayolları da kaldırıldı — pandas'ın doğal float bölmesi zaten `0/0→NaN`,
    `x/0→±inf` üretir, ikisi de aynı `is_available()` kontrolünden geçer.
    """
    close = df["Close"]

    rsi_s = ind.rsi(close)
    _, _, macd_hist_s = ind.macd(close)
    ema_short_s = ind.ema(close, 20)
    ema_long_s = ind.ema(close, 50)
    ema_slope_s = ind.ema_slope(close, window=20, slope_lookback=5)
    upper_s, middle_s, _lower_s = ind.bollinger_bands(close)
    atr_s = ind.atr(df)
    momentum_s = ind.momentum(close)
    roc_s = ind.roc(close)
    band_width_s = upper_s - middle_s

    raw_components = pd.DataFrame(
        {
            "rsi": (rsi_s - 50) * 2,
            "macd": (macd_hist_s / atr_s) * 25,
            "trend": ((ema_short_s - ema_long_s) / ema_long_s) * 1000,
            "ema_slope": ema_slope_s * 15,
            "bollinger": ((close - middle_s) / band_width_s) * 100,
            "momentum": (momentum_s / atr_s) * 20,
            "roc": roc_s * 8,
        }
    )
    components_df = clamp_components_df(raw_components)
    return aggregate_available_components_series(components_df, weights)


def _is_valid_execution_price(value: float) -> bool:
    """HATA 3A: bilinmeyen/geçersiz bir execution fiyatı ASLA uydurulmaz
    (ör. Open[T+1] NaN/inf/<=0 ise Close'a sessizce fallback YAPILMAZ)."""
    return not math.isnan(value) and not math.isinf(value) and value > 0


def simulate(
    df: pd.DataFrame,
    score_series: pd.Series,
    thresholds: dict,
    initial_capital: float = 100_000.0,
) -> dict:
    """Verilen skor serisine göre sinyal bazlı al-sat simülasyonu. Saf fonksiyon —
    veri çekmeden, tek bir zaten-hesaplanmış skor serisi üzerinde çalışır (bu ayrım
    WalkForwardOptimizer'ın aynı df'in farklı pencerelerini tekrar tekrar simüle
    edebilmesi için gerekli).

    HATA 3A — NEXT_SESSION_OPEN execution modeli (bkz. modül docstring'i):
    T günü Close'undan üretilen sinyal, T+1 günü Open'ında `pending_signal`
    olarak execute edilir — hiçbir zaman aynı barın Close'undan değil.
    """
    close = df["Close"]
    open_ = df["Open"]
    cash = initial_capital
    shares = 0.0
    entry_execution_date = None
    entry_execution_price: float | None = None
    entry_signal_date = None
    entry_signal_price: float | None = None
    pending_signal: dict | None = None  # {"action","signal_date","signal_price"} — bir SONRAKI barda uygulanır
    trades: list[dict] = []
    equity_curve: list[dict] = []
    skipped_executions: list[dict] = []

    for i in range(len(df)):
        date = df.index[i]

        # 1) i-1'de oluşan pending signal varsa, BUGÜNÜN (i) Open'ında execute et.
        if pending_signal is not None:
            open_price = float(open_.iloc[i])
            if _is_valid_execution_price(open_price):
                action = pending_signal["action"]
                if action == "BUY" and shares == 0:
                    shares = cash / open_price
                    cash = 0.0
                    entry_execution_date = date
                    entry_execution_price = open_price
                    entry_signal_date = pending_signal["signal_date"]
                    entry_signal_price = pending_signal["signal_price"]
                elif action == "SELL" and shares > 0:
                    cash = shares * open_price
                    trades.append(
                        {
                            "entry_date": str(entry_execution_date.date()),
                            "exit_date": str(date.date()),
                            "entry_price": round(entry_execution_price, 2),
                            "exit_price": round(open_price, 2),
                            "return_pct": round(
                                (open_price - entry_execution_price) / entry_execution_price * 100, 2
                            ),
                            "entry_signal_date": str(entry_signal_date.date()),
                            "entry_signal_price": round(entry_signal_price, 2),
                            "entry_execution_date": str(entry_execution_date.date()),
                            "entry_execution_price": round(entry_execution_price, 2),
                            "exit_signal_date": str(pending_signal["signal_date"].date()),
                            "exit_signal_price": round(pending_signal["signal_price"], 2),
                            "exit_execution_date": str(date.date()),
                            "exit_execution_price": round(open_price, 2),
                        }
                    )
                    shares = 0.0
                    entry_execution_date = None
                    entry_execution_price = None
                    entry_signal_date = None
                    entry_signal_price = None
                # action=="BUY" ama shares>0 (veya "SELL" ama shares==0) olamaz —
                # pending_signal yalnızca uygun durumdayken oluşturulur (aşağıda).
            else:
                skipped_executions.append(
                    {
                        "action": pending_signal["action"],
                        "signal_date": str(pending_signal["signal_date"].date()),
                        "attempted_execution_date": str(date.date()),
                        "reason": "INVALID_NEXT_OPEN",
                    }
                )
            pending_signal = None

        # 2) BUGÜNÜN (i) Close'u TAMAMLANDIĞINDA sinyal bilinir hale gelir —
        #    hemen execute EDİLMEZ, yalnızca "yarın (i+1) Open'ında uygulanacak"
        #    olarak işaretlenir.
        score = score_series.iloc[i]
        if pd.notna(score):
            decision = _classify(float(score), thresholds)
            if shares == 0 and decision in ("BUY", "WEAK_BUY"):
                pending_signal = {"action": "BUY", "signal_date": date, "signal_price": float(close.iloc[i])}
            elif shares > 0 and decision in ("SELL", "WEAK_SELL"):
                pending_signal = {"action": "SELL", "signal_date": date, "signal_price": float(close.iloc[i])}

        # 3) Mark-to-market: bugünün Close'u ile, olası execution SONRASI durum.
        mark_price = float(close.iloc[i])
        equity_curve.append({"date": str(date.date()), "equity": round(cash + shares * mark_price, 2)})

    # Son barda hâlâ bekleyen bir sinyal varsa: T+1 barı YOK — EXECUTE EDİLMEZ
    # (Close'a sahte fallback YAPILMAZ). Bilgi amaçlı ayrı raporlanır.
    unexecuted_signal = None
    if pending_signal is not None:
        unexecuted_signal = {
            "action": pending_signal["action"],
            "signal_date": str(pending_signal["signal_date"].date()),
            "signal_price": round(pending_signal["signal_price"], 2),
            "reason": "NO_NEXT_BAR",
        }

    # Backtest sonunda hâlâ açık bir pozisyon varsa: bu GERÇEK bir SELL
    # execution DEĞİLDİR — trades[]'e sahte bir kapanış kaydı EKLENMEZ,
    # yalnızca mark-to-market ile ayrı raporlanır (bkz. modül docstring'i).
    open_position = None
    if shares > 0:
        final_price = float(close.iloc[-1])
        open_position = {
            "status": "OPEN",
            "entry_signal_date": str(entry_signal_date.date()),
            "entry_signal_price": round(entry_signal_price, 2),
            "entry_execution_date": str(entry_execution_date.date()),
            "entry_execution_price": round(entry_execution_price, 2),
            "shares": round(shares, 6),
            "mark_price": round(final_price, 2),
            "market_value": round(shares * final_price, 2),
            "unrealized_return_pct": round(
                (final_price - entry_execution_price) / entry_execution_price * 100, 2
            ),
        }
        final_equity = cash + shares * final_price
    else:
        final_equity = cash

    total_return_pct = round((final_equity - initial_capital) / initial_capital * 100, 2)

    equity_values = pd.Series([point["equity"] for point in equity_curve])
    running_max = equity_values.cummax()
    drawdown = (equity_values - running_max) / running_max
    max_drawdown_pct = round(float(drawdown.min() * 100), 2) if not drawdown.empty else 0.0

    # win_rate_pct: yalnızca GERÇEK kapanmış (closed round-trip) işlemlerden.
    # Açık pozisyon hiç trades[]'e girmediğinden burada zaten karışmıyor.
    # Kapalı işlem yoksa 0.0 (Flutter `winRatePct` alanı non-nullable `double`
    # okuyor — mevcut API sözleşmesini bozmamak için `None` DEĞİL, eski
    # davranışla aynı 0.0 varsayılanı korunuyor, bkz. HATA 3A raporu).
    winning_trades = [t for t in trades if t["return_pct"] > 0]
    win_rate_pct = round(len(winning_trades) / len(trades) * 100, 2) if trades else 0.0

    buy_and_hold_return_pct = round(
        (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100, 2
    )

    return {
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": total_return_pct,
        "buy_and_hold_return_pct": buy_and_hold_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "trade_count": len(trades),
        "win_rate_pct": win_rate_pct,
        "trades": trades,
        "open_position": open_position,
        "unexecuted_signal": unexecuted_signal,
        "skipped_executions": skipped_executions,
        "equity_curve": equity_curve,
        "execution_model": "NEXT_SESSION_OPEN",
        "terminal_position_policy": "MARK_TO_MARKET",
    }


def compare_strategies(
    indicator_history: pd.DataFrame,
    simulation_history: pd.DataFrame,
    presets: dict[str, dict],
    thresholds: dict,
    initial_capital: float = 100_000.0,
) -> list[dict]:
    """Aynı fiyat serisi üzerinde birden çok adlandırılmış ağırlık ön ayarını
    (bkz. strategy_presets.py) çalıştırıp getiriye göre sıralanmış bir
    karşılaştırma listesi döner — "hangi strateji daha iyi sonuç veriyor"
    sorusuna tek bir sembol için doğrudan cevap. Not: bu, walk_forward_
    optimize_weights'ten FARKLI bir amaca hizmet eder — o train/test
    ayrımıyla overfit'i önlemeye çalışır, bu ise tüm dönem üzerinde basit,
    yorumlanabilir bir karşılaştırma sunar (çok sembollü toplu tarama için
    tasarlandı, bkz. Flutter Strateji Laboratuvarı ekranı).

    HATA 5A (27.08.2026): `indicator_history` (warm-up DAHİL) ve `simulation_
    history` (yalnız istenen simülasyon penceresi) AYRI parametreler — HER
    preset AYNI `simulation_history`'yi simüle eder (strateji ufukları warm-up
    yüzünden FARKLILAŞMAZ), yalnız skor hesaplaması için (kendi ağırlığıyla)
    `indicator_history`'nin TAMAMI kullanılır, sonra `simulation_history`'nin
    tarihlerine `.loc[]` ile kırpılır.
    """
    results = []
    for name, weights in presets.items():
        scores_all = technical_score_series(indicator_history, weights)
        simulation_scores = scores_all.loc[simulation_history.index]
        result = simulate(simulation_history, simulation_scores, thresholds, initial_capital)
        results.append(
            {
                "preset": name,
                "total_return_pct": result["total_return_pct"],
                "buy_and_hold_return_pct": result["buy_and_hold_return_pct"],
                "max_drawdown_pct": result["max_drawdown_pct"],
                "trade_count": result["trade_count"],
                "win_rate_pct": result["win_rate_pct"],
            }
        )
    results.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return results


class BacktestEngine:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()

    def run(
        self,
        symbol: str,
        period: str = "2y",
        initial_capital: float = 100_000.0,
        now: datetime | None = None,
    ) -> dict:
        prepared = prepare_backtest_history(self._provider, symbol, period, now=now)

        weights = self._config_repo.get("technical_indicator_weights", DEFAULT_TECHNICAL_WEIGHTS)
        thresholds = self._config_repo.get("decision_thresholds", DEFAULT_THRESHOLDS)

        # HATA 5A: skor TÜM indicator_history (warm-up dahil) üzerinden
        # hesaplanır, sonra YALNIZ simulation_history'nin tarihlerine
        # kırpılır — `df.iloc[MIN_HISTORY_DAYS:]` deseni KALDIRILDI, warm-up
        # artık istenen pencerenin İÇİNDEN kesilmiyor (bkz. completed_
        # history.py modül docstring'i).
        scores_all = technical_score_series(prepared.indicator_history, weights)
        simulation_scores = scores_all.loc[prepared.simulation_history.index]

        result = simulate(prepared.simulation_history, simulation_scores, thresholds, initial_capital)
        return {
            "asset": symbol,
            "period": period,
            "from_date": str(prepared.simulation_history.index[0].date()),
            "to_date": str(prepared.simulation_history.index[-1].date()),
            "thresholds": thresholds,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backtest_data_as_of": str(prepared.backtest_data_as_of),
            "data_policy": "COMPLETED_DAILY_ONLY",
            "requested_window_start": str(prepared.requested_window_start),
            "simulation_start": str(prepared.simulation_start),
            "warmup_history_start": str(prepared.warmup_history_start),
            "indicator_warmup_sessions": prepared.indicator_warmup_sessions,
            "actual_history_start": str(prepared.actual_history_start),
            "actual_indicator_history_start": str(prepared.actual_indicator_history_start),
            "history_validation_status": prepared.history_validation_status,
            **session_normalization_to_dict(prepared.normalization),
            **result,
        }

    def compare_strategies(
        self,
        symbol: str,
        presets: dict[str, dict],
        period: str = "2y",
        initial_capital: float = 100_000.0,
        now: datetime | None = None,
    ) -> dict:
        prepared = prepare_backtest_history(self._provider, symbol, period, now=now)

        thresholds = self._config_repo.get("decision_thresholds", DEFAULT_THRESHOLDS)
        # HATA 3D, madde 14 / HATA 3E: aynı normalize edilmiş, aynı leading-edge
        # çözümlenmiş history TÜM preset'ler için kullanıldığından, provenance
        # TOP-LEVEL tek bir yerde taşınır — her preset sonucuna AYRI AYRI
        # kopyalanmaz. HATA 5A: TÜM preset'ler AYNI `simulation_history`'yi
        # (warm-up hariç) simüle eder — strateji ufukları warm-up nedeniyle
        # FARKLILAŞMAZ.
        results = compare_strategies(
            prepared.indicator_history, prepared.simulation_history, presets, thresholds, initial_capital
        )
        return {
            "asset": symbol,
            "period": period,
            "from_date": str(prepared.simulation_history.index[0].date()),
            "to_date": str(prepared.simulation_history.index[-1].date()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backtest_data_as_of": str(prepared.backtest_data_as_of),
            "data_policy": "COMPLETED_DAILY_ONLY",
            "requested_window_start": str(prepared.requested_window_start),
            "simulation_start": str(prepared.simulation_start),
            "warmup_history_start": str(prepared.warmup_history_start),
            "indicator_warmup_sessions": prepared.indicator_warmup_sessions,
            "actual_history_start": str(prepared.actual_history_start),
            "actual_indicator_history_start": str(prepared.actual_indicator_history_start),
            "history_validation_status": prepared.history_validation_status,
            **session_normalization_to_dict(prepared.normalization),
            "results": results,
        }
