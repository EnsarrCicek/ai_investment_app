from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.multi_timeframe import check_alignment
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone

_ZONE = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=3, last_touch_index=10)


def _confirmed_breakout(retest_held=None) -> BreakoutEvent:
    return BreakoutEvent(index=10, direction="BULLISH", zone=_ZONE, breakout_atr=2.0, confirmed=True, retest_held=retest_held)


def _confirmed_bearish_breakout(retest_held=None) -> BreakoutEvent:
    return BreakoutEvent(index=10, direction="BEARISH", zone=_ZONE, breakout_atr=2.0, confirmed=True, retest_held=retest_held)


def test_strong_bullish_initiation_requires_all_conditions():
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="HIGH",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "STRONG_BULLISH_INITIATION"


def test_incomplete_mtf_evidence_cannot_produce_strong_bullish_initiation():
    # HATA 7C-FIX: weekly zaman dilimi UNKNOWN'sa (ör. yetersiz haftalık
    # geçmiş) check_alignment() artık aligned=False/consensus="UNKNOWN"
    # döner -- bu, aksi halde STRONG_BULLISH_INITIATION için gereken TÜM
    # diğer koşulları (skor, breakout, hacim) sağlayan bir senaryoyu bile
    # eksik MTF kanıtı yüzünden bir alt sınıfa (BULLISH_CONFIRMED) düşürmeli.
    alignment = check_alignment({"1d": "UP", "1wk": "UNKNOWN"})
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="HIGH",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=alignment["aligned"],
        mtf_consensus=alignment["consensus"],
    )
    assert classify_signal(inputs) == "BULLISH_CONFIRMED"


def test_strong_bullish_initiation_does_not_require_high_volume():
    # TECH-VOL 1B: eskiden (1.14.0) NORMAL hacim -> BULLISH_CONFIRMED'a düşüyordu.
    # TECH-VOL 1A dış denetimi yüksek-hacim kapısını ZARARLI buldu; kapı kaldırıldı.
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="NORMAL",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "STRONG_BULLISH_INITIATION"


def test_bullish_confirmed_without_breakout_event():
    inputs = SignalInputs(technical_score=20.0, market_structure="UPTREND", breakout_event=None)
    assert classify_signal(inputs) == "BULLISH_CONFIRMED"


def test_bullish_confirmed_event_grants_bullish_confirmed_at_moderate_score():
    inputs = SignalInputs(
        technical_score=20.0, market_structure="UPTREND", breakout_event=_confirmed_breakout(retest_held=True)
    )
    assert classify_signal(inputs) == "BULLISH_CONFIRMED"


def test_bullish_candidate_when_structure_not_uptrend():
    inputs = SignalInputs(technical_score=20.0, market_structure="RANGE")
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bullish_candidate_when_breakout_not_confirmed_yet():
    pending = BreakoutEvent(index=10, direction="BULLISH", zone=_ZONE, breakout_atr=1.0, confirmed=None)
    inputs = SignalInputs(technical_score=20.0, market_structure="UPTREND", breakout_event=pending)
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bearish_confirmed_event_cannot_grant_bullish_confirmed():
    # HATA 9A-FIX: bir BEARISH kırılım/çöküş olayı (confirmed=True,
    # retest_held=True) bullish onay SAYILAMAZ -- select_live_breakout_event()
    # en son olayı yönden bağımsız seçtiği için (HATA 9/9A audit'leri), bu
    # olmadan gerçek üretim verisinde 15/7833 barda BULLISH_CONFIRMED
    # kirlenmesi kanıtlandı.
    inputs = SignalInputs(
        technical_score=20.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_bearish_breakout(retest_held=True),
    )
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bearish_confirmed_held_event_cannot_grant_strong_bullish_initiation():
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_bearish_breakout(retest_held=True),
        relative_volume_class="VERY_HIGH",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bearish_confirmed_failed_retest_event_cannot_grant_any_bullish_tier():
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_bearish_breakout(retest_held=False),
        relative_volume_class="VERY_HIGH",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bullish_confirmed_held_event_still_grants_strong_bullish_initiation():
    # Regresyon kontrolü: doğru yönde (BULLISH) confirmed+retest-held bir olay
    # HATA 9A-FIX'ten ÖNCEKİ davranışla AYNI şekilde çalışmaya devam etmeli.
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="VERY_HIGH",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "STRONG_BULLISH_INITIATION"


def test_bearish_candidate_for_strongly_negative_score():
    inputs = SignalInputs(technical_score=-30.0, market_structure="DOWNTREND")
    assert classify_signal(inputs) == "BEARISH_CANDIDATE"


def test_bearish_candidate_regardless_of_structure():
    inputs = SignalInputs(technical_score=-30.0, market_structure="RANGE")
    assert classify_signal(inputs) == "BEARISH_CANDIDATE"


def test_no_signal_when_all_context_is_unknown():
    inputs = SignalInputs(technical_score=0.0)
    assert classify_signal(inputs) == "NO_SIGNAL"


def test_watchlist_for_mild_positive_score_in_uptrend():
    inputs = SignalInputs(technical_score=8.0, market_structure="UPTREND")
    assert classify_signal(inputs) == "WATCHLIST"


def test_watchlist_for_mild_negative_score_in_downtrend():
    inputs = SignalInputs(technical_score=-8.0, market_structure="DOWNTREND")
    assert classify_signal(inputs) == "WATCHLIST"


def test_neutral_as_default_fallback():
    inputs = SignalInputs(technical_score=5.0, market_structure="RANGE")
    assert classify_signal(inputs) == "NEUTRAL"
