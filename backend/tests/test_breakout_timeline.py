"""HATA 4B (27.08.2026) — breakout event timeline: transition detection,
strict causal zone/ATR contract, frozen snapshot, directional scan, dominant
same-day event, confirmation/retest state machines, MAX_EVENT_AGE live
selection, and prefix/full-history causality (no future rewrite of a
historical state) — bkz. app/engines/technical/breakout_timeline.py modül
docstring'i ve TEKNIK_ANALIZ_METODOLOJISI.md HATA 4B bölümü.

Tüm testler saf sentetik veri üzerinde çalışır — ağa bağımlı yok.
"""

import numpy as np
import pandas as pd
import pytest

from app.engines.technical import indicators as ind
from datetime import date

from app.engines.technical.breakout_timeline import (
    BreakoutTimelineEvent,
    ConfirmationState,
    RetestState,
    build_breakout_timeline,
    select_live_breakout_event,
    to_legacy_breakout_event,
)
from app.engines.technical.market_structure import find_swing_points
from app.engines.technical.support_resistance import SRZone, build_zones


def _df(values: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range(start="2026-01-01", periods=len(values))
    close = pd.Series(values, dtype=float, index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close, "Volume": 1000.0},
        index=idx,
    )


# Basit resistance ~100 (left=2/right=2 ile iki dokunuş: idx3 ve idx11), sonra
# tampon barlar (99'a kadar iniş), sonra kullanıcı örneğindeki tam sekans:
# 99, 102, 103, 104, 105.
# Not: iki dokunuş bilinçli olarak biraz FARKLI (100 / 100.6) tutuldu --
# aynı fiyatta iki dokunuş sıfır-genişlikte (low==high) bir zone üretirdi ki bu
# retest'in "dokunuş" ile "tutma" ayrımını test edilemez kılardı. High=Close+0.5
# olduğundan gerçek zone sınırları ~100.5-101.1 civarında oluşur (aşağıdaki
# testler zone.high/zone.low'a göre DİNAMİK değer kullanır, sabit 100 değil).
_RESISTANCE_100_CONSOLIDATION = [90, 95, 98, 100.6, 98, 95, 90, 88, 90, 95, 98, 100, 98, 95, 90, 96, 97, 99]
_KWARGS = {"left_bars": 2, "right_bars": 2, "confirm_bars": 3, "retest_bars": 10}


def _resistance_100_df(tail: list[float]) -> pd.DataFrame:
    return _df(_RESISTANCE_100_CONSOLIDATION + tail)


def _find_bullish_events(timeline):
    return [e for e in timeline if e.direction == "BULLISH"]


# ---------------------------------------------------------------------------
# 1. Transition, state değil.
# ---------------------------------------------------------------------------


def test_transition_based_detection_produces_single_event_not_five():
    df = _resistance_100_df([102, 103, 104, 105])
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bullish = _find_bullish_events(timeline)

    assert len(bullish) == 1
    event = bullish[0]
    assert df.index[event.event_index] == df.index[len(_RESISTANCE_100_CONSOLIDATION)]  # ilk 102 barı


# ---------------------------------------------------------------------------
# 2/3. Confirmation: confirmed_at=T+3, invalidated_at=ilk ihlal barı.
# ---------------------------------------------------------------------------


def test_confirmation_confirmed_at_t_plus_3_when_three_bars_above():
    df = _resistance_100_df([102, 103, 104, 105])
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.confirmation_state == ConfirmationState.CONFIRMED.value
    assert event.confirmed_at == event.event_index + 3
    assert event.invalidated_at is None


def test_confirmation_invalidated_at_first_violation_bar():
    df = _resistance_100_df([102, 103, 98, 101])  # T+1 above, T+2 BELOW (98<=100)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.confirmation_state == ConfirmationState.INVALIDATED.value
    assert event.invalidated_at == event.event_index + 2
    assert event.confirmed_at is None


def test_confirmation_pending_when_not_enough_bars_yet():
    df = _resistance_100_df([102, 103])  # yalnız T+1 var, henüz T+3 yok
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.confirmation_state == ConfirmationState.PENDING_CONFIRMATION.value
    assert event.confirmed_at is None
    assert event.invalidated_at is None


# ---------------------------------------------------------------------------
# 4. Re-break sonrası: INVALIDATED bir event, yeni bir crossing'i bloklamaz.
# ---------------------------------------------------------------------------


def test_rebreak_after_invalidation_creates_a_second_independent_event():
    # ...,99(idx17), 102(event1), 103, 98(event1 INVALIDATED), 99, 104(event2)
    df = _resistance_100_df([102, 103, 98, 99, 104])
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bullish = sorted(_find_bullish_events(timeline), key=lambda e: e.event_index)

    assert len(bullish) == 2
    assert bullish[0].confirmation_state == ConfirmationState.INVALIDATED.value
    assert bullish[1].event_index > bullish[0].event_index
    assert bullish[1].confirmation_state in (
        ConfirmationState.PENDING_CONFIRMATION.value,
        ConfirmationState.CONFIRMED.value,
    )


# ---------------------------------------------------------------------------
# 5-9. Retest: confirmed_at+1'de başlar, PENDING/HELD/FAILED/EXPIRED.
# ---------------------------------------------------------------------------


def test_retest_window_starts_at_confirmed_at_plus_1_not_event_at_plus_1():
    df = _resistance_100_df([102, 103, 104, 105, 99.5, 106])  # confirmed_at=+3, retest touch en erken +4
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.confirmation_state == ConfirmationState.CONFIRMED.value
    assert event.retest_deadline == event.confirmed_at + 10
    if event.retest_event_at is not None:
        assert event.retest_event_at >= event.confirmed_at + 1


def test_retest_held_when_level_holds_after_touch():
    # event(idx18)=102, confirm 103/104/105 (confirmed_at=idx21), sonra
    # zone BANDI İÇİNE (zone.low..zone.high arası) bir dokunuş ve pencere
    # sonuna kadar hep >= zone.low.
    df_probe = _resistance_100_df([102, 103, 104, 105])
    zone = _find_bullish_events(build_breakout_timeline(df_probe, "TEST", **_KWARGS))[0].zone_snapshot
    touch_price = round((zone.low + zone.high) / 2, 3)  # bant İÇİNDE -- hem touch hem hold koşulunu sağlar

    tail = [102, 103, 104, 105] + [touch_price] + [touch_price] * 9  # touch + 9 more (window=10)
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.confirmation_state == ConfirmationState.CONFIRMED.value
    assert event.retest_state == RetestState.HELD.value
    assert event.retest_event_at == event.confirmed_at + 1
    assert event.retest_known_at == event.retest_deadline


def test_retest_failed_when_level_breaks_after_touch():
    df_probe = _resistance_100_df([102, 103, 104, 105])
    zone = _find_bullish_events(build_breakout_timeline(df_probe, "TEST", **_KWARGS))[0].zone_snapshot
    touch_price = round((zone.low + zone.high) / 2, 3)  # bant içinde -- touch ama henüz kırılmamış
    break_price = zone.low - 3.0  # bandın KESİN altı -- ayrı bir barda gerçek ihlal

    tail = [102, 103, 104, 105] + [touch_price, break_price]
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.retest_state == RetestState.FAILED.value
    assert event.retest_event_at == event.confirmed_at + 1
    assert event.retest_known_at == event.confirmed_at + 2


def test_retest_expired_when_window_fully_elapses_without_touch():
    tail = [102, 103, 104, 105] + [110.0] * 10  # hiç geri dönüş yok, pencere (10 bar) tamamen doluyor
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.retest_state == RetestState.EXPIRED.value
    assert event.retest_event_at is None
    assert event.retest_known_at == event.retest_deadline


def test_retest_pending_when_window_not_yet_elapsed():
    tail = [102, 103, 104, 105] + [110.0] * 3  # yalnız 3 bar geçti, pencere (10) henüz dolmadı
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]

    assert event.retest_state == RetestState.PENDING.value
    assert event.retest_known_at is None


# ---------------------------------------------------------------------------
# 10/11. Aynı gün birden fazla zone kırılırsa: tek dominant event.
# ---------------------------------------------------------------------------


def test_same_day_multiple_resistance_breaks_selects_outermost_as_dominant():
    # İki ayrı resistance: ~100 (idx3/11) ve ~120 (idx20/24), sonra TEK günde
    # ikisini de aşan bir sıçrama (99 -> 125).
    values = _RESISTANCE_100_CONSOLIDATION + [105, 115, 120, 115, 120, 118, 119, 99, 125]
    df = _df(values)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bullish_on_jump_day = [e for e in timeline if e.direction == "BULLISH" and df.index[e.event_index] == df.index[-1]]

    assert len(bullish_on_jump_day) == 1  # tek dominant event, iki ayrı değil
    assert bullish_on_jump_day[0].level >= 100.0


def test_same_day_multiple_support_breaks_selects_outermost_as_dominant():
    # Aynı senaryonun ayna simetriği (destek kırılımı, aşağı yönlü).
    mirrored = [200 - v for v in _RESISTANCE_100_CONSOLIDATION + [105, 115, 120, 115, 120, 118, 119, 99, 125]]
    df = _df(mirrored)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bearish_on_jump_day = [e for e in timeline if e.direction == "BEARISH" and df.index[e.event_index] == df.index[-1]]

    assert len(bearish_on_jump_day) == 1


# ---------------------------------------------------------------------------
# 12. Directional scan: type-agnostic nearest_zone'un kaçırdığı breakout artık bulunuyor.
# ---------------------------------------------------------------------------


def test_directional_scan_finds_breakout_that_nearest_zone_would_have_missed():
    # Fiyat, support'a (103-104 civarı) resistance'tan (99-101 civarı, zaten
    # kırılmış) DAHA YAKIN kalacak şekilde kurgulandı -- eski tip-agnostik
    # nearest_zone() bu breakout'u KAÇIRIRDI (HATA 4B audit'i, gerçek kodla
    # kanıtlandı). Yeni directional scan support'u YOK SAYIP resistance
    # tarafındaki kırılımı bulmalı.
    support_consolidation = [103, 104, 103.5, 104, 103.5, 104, 103.5]
    resistance_consolidation = [99, 100, 99.5, 100, 99.5, 100, 99.5]
    # iki bölgeyi de left/right=2 ile onaylatacak şekilde art arda kur, sonra jump.
    values = resistance_consolidation + support_consolidation + [104.2, 105.0]
    df = _df(values)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bullish = _find_bullish_events(timeline)

    assert len(bullish) >= 1
    assert any(e.level < 103.0 for e in bullish)  # resistance (~100) kırılımı GERÇEKTEN bulundu


# ---------------------------------------------------------------------------
# 13. Future-volatility append: geçmiş zone/event ATR[T-1] kontratı sayesinde DEĞİŞMEMELİ.
# ---------------------------------------------------------------------------


def test_future_high_volatility_append_does_not_change_historical_events():
    # Yalnızca base'de ZATEN TERMİNAL bir state'e ulaşmış event'ler
    # karşılaştırılır -- hâlâ PENDING olan bir event'in gelecekte gerçekten
    # yeni barlarla çözülmesi BEKLENEN davranıştır (bu, invariant'ı ihlal
    # etmez; ihlal, ZATEN ÇÖZÜLMÜŞ bir event'in state'inin değişmesi olurdu).
    df_base = _resistance_100_df([102, 103, 104, 105])  # tek, net biçimde CONFIRMED olan event
    timeline_base = build_breakout_timeline(df_base, "TEST", **_KWARGS)
    terminal_base = [e for e in timeline_base if e.confirmation_state != ConfirmationState.PENDING_CONFIRMATION.value]
    assert terminal_base  # fixture gerçekten en az bir terminal event üretiyor mu

    rng = np.random.default_rng(5)
    extra = 106 + np.cumsum(rng.normal(0, 15.0, 20))  # çok yüksek volatilite eklentisi
    df_extended = pd.concat([df_base, _df(list(extra)).set_axis(
        pd.bdate_range(start=df_base.index[-1] + pd.Timedelta(days=1), periods=20)
    )])
    timeline_extended = build_breakout_timeline(df_extended, "TEST", **_KWARGS)

    extended_by_id = {e.event_id: e for e in timeline_extended}
    for old in terminal_base:
        event = extended_by_id[old.event_id]
        assert event.level == old.level
        assert event.zone_snapshot.low == old.zone_snapshot.low
        assert event.zone_snapshot.high == old.zone_snapshot.high
        assert event.confirmation_state == old.confirmation_state
        assert event.confirmed_at == old.confirmed_at
        assert event.invalidated_at == old.invalidated_at


# ---------------------------------------------------------------------------
# 14. Reference (naif per-T prefix) A ile production (optimized, tek geçiş) B parity.
# ---------------------------------------------------------------------------


def _reference_naive_timeline(df, symbol, left_bars, right_bars, confirm_bars, retest_bars):
    """Test-only NAIVE reference: her T için swing tespiti/ATR'yi T-1
    prefix'inden YENİDEN hesaplar (production kodunun optimize ettiği,
    ama yavaş/doğruluk referansı olan yol) -- HATA 4B audit'inde kanıtlanan
    189/189 + tam event-alanı eşitliğini bu testte de doğrular."""
    from app.engines.technical.breakout_timeline import _resolve_confirmation, _resolve_retest

    close = df["Close"]
    n = len(df)
    candidates = []
    for t in range(1, n):
        prefix_atr_series = ind.atr(df.iloc[:t])
        if len(prefix_atr_series) == 0 or pd.isna(prefix_atr_series.iloc[-1]):
            continue
        atr_t_minus_1 = float(prefix_atr_series.iloc[-1])
        if atr_t_minus_1 <= 0:
            continue
        prefix_points = find_swing_points(df.iloc[:t], left_bars=left_bars, right_bars=right_bars)
        zones = build_zones(prefix_points, atr=atr_t_minus_1)
        prev_close, curr_close = float(close.iloc[t - 1]), float(close.iloc[t])
        bullish = [z for z in zones if z.type == "RESISTANCE" and prev_close <= z.high < curr_close]
        bearish = [z for z in zones if z.type == "SUPPORT" and prev_close >= z.low > curr_close]
        if bullish:
            candidates.append((t, "BULLISH", max(bullish, key=lambda z: z.high)))
        if bearish:
            candidates.append((t, "BEARISH", min(bearish, key=lambda z: z.low)))

    events = []
    atr_series = ind.atr(df)
    for event_index, direction, zone in candidates:
        level = zone.high if direction == "BULLISH" else zone.low
        confirmation_state, confirmed_at, invalidated_at = _resolve_confirmation(
            close, event_index, direction, level, confirm_bars, n
        )
        retest_state = retest_event_at = retest_known_at = None
        if confirmation_state == ConfirmationState.CONFIRMED.value:
            retest_state, retest_event_at, retest_known_at = _resolve_retest(
                close, confirmed_at, direction, zone, retest_bars, n
            )
        event_at = df.index[event_index].date()
        events.append(
            (
                f"{symbol}:{direction}:{event_at.isoformat()}",
                event_index,
                direction,
                round(level, 6),
                confirmation_state,
                confirmed_at,
                invalidated_at,
                retest_state,
                retest_event_at,
                retest_known_at,
            )
        )
    return events


def _optimized_as_tuples(timeline):
    return [
        (
            e.event_id, e.event_index, e.direction, e.level, e.confirmation_state,
            e.confirmed_at, e.invalidated_at, e.retest_state, e.retest_event_at, e.retest_known_at,
        )
        for e in timeline
    ]


def test_reference_prefix_matches_optimized_production_synthetic():
    rng = np.random.default_rng(17)
    values = list(100 + np.cumsum(rng.normal(0, 1.2, 140)))
    df = _df(values)

    reference = _reference_naive_timeline(df, "TEST", left_bars=5, right_bars=5, confirm_bars=3, retest_bars=10)
    optimized = _optimized_as_tuples(build_breakout_timeline(df, "TEST"))

    assert reference == optimized
    assert len(reference) > 0  # fixture gerçekten event üretiyor mu, boş karşılaştırma değil


# ---------------------------------------------------------------------------
# 15. MAX_EVENT_AGE: T+15 dahil, T+16 hariç.
# ---------------------------------------------------------------------------


def test_max_event_age_t15_eligible_t16_stale():
    # confirmed_at=+3, retest 10 bar sonra (deadline=+13) EXPIRED -- resolved_at=+13=event_at+13.
    tail = [102, 103, 104, 105] + [110.0] * 10
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]
    assert event.retest_state == RetestState.EXPIRED.value

    age_15_index = event.event_index + 15
    age_16_index = event.event_index + 16

    selected_at_15 = select_live_breakout_event(timeline, today_index=age_15_index)
    selected_at_16 = select_live_breakout_event(timeline, today_index=age_16_index)

    assert selected_at_15 is not None and selected_at_15.event_id == event.event_id
    assert selected_at_16 is None or selected_at_16.event_id != event.event_id


# ---------------------------------------------------------------------------
# INVALIDATED: live selection'da HİÇ gösterilmez.
# ---------------------------------------------------------------------------


def test_invalidated_event_never_selected_as_live_breakout():
    # 101, ihlalden SONRA da level'ın (~101.1) altında kaldığından yeni bir
    # crossing YARATMAZ -- bu testin amacı yalnız TEK (invalidated) event'i
    # izole etmek.
    df = _resistance_100_df([102, 103, 98, 99])
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    bullish = _find_bullish_events(timeline)
    assert len(bullish) == 1
    assert bullish[0].confirmation_state == ConfirmationState.INVALIDATED.value

    selected = select_live_breakout_event(timeline, today_index=len(df) - 1)
    assert selected is None


def test_live_selector_falls_back_to_older_resolved_event_once_newer_one_is_invalidated():
    # HATA 4B pre-commit audit'inde kanıtlanan davranış, burada kilitleniyor:
    # event1 (eski, zaten RESOLVED, hâlâ age<=15) + event2 (yeni, önce OPEN).
    # event2 açıkken event2 seçilir; event2 sonradan INVALIDATED olup canlı
    # seçimden düşünce, live selector event1'e GERİ DÖNER (event1'in
    # `notify_if_new_opportunity()` tarafında zaten bildirilmiş olabileceği
    # anlamına gelir -- bu yüzden dedupe event_id BAZLI ve kalıcı olmalı,
    # bkz. test_fcm_sender.py::test_new_opportunity_event1_then_event2_then_event1_fallback_is_suppressed).
    zone = SRZone(type="RESISTANCE", low=99.0, high=100.0, touch_count=2, last_touch_index=0)

    def _event(event_index, event_at_str, confirmation_state, retest_state, confirmed_at=None):
        return BreakoutTimelineEvent(
            event_id=f"THYAO:BULLISH:{event_at_str}",
            symbol="THYAO", direction="BULLISH",
            event_index=event_index, event_at=date.fromisoformat(event_at_str),
            level=100.0, zone_snapshot=zone, zone_known_at=event_index - 1,
            breakout_strength_atr=1.0,
            confirmation_state=confirmation_state, confirmed_at=confirmed_at, invalidated_at=None,
            retest_state=retest_state, retest_event_at=None, retest_known_at=None,
            retest_deadline=(confirmed_at + 10) if confirmed_at else None,
            resolved_at=None,
        )

    event1 = _event(10, "2026-08-01", ConfirmationState.CONFIRMED.value, RetestState.EXPIRED.value, confirmed_at=13)
    event2_open = _event(20, "2026-08-15", ConfirmationState.PENDING_CONFIRMATION.value, None)
    event2_invalidated = _event(20, "2026-08-15", ConfirmationState.INVALIDATED.value, None)

    selected_while_open = select_live_breakout_event([event1, event2_open], today_index=20)
    assert selected_while_open.event_id == event2_open.event_id

    selected_after_invalidation = select_live_breakout_event([event1, event2_invalidated], today_index=24)
    assert selected_after_invalidation is not None
    assert selected_after_invalidation.event_id == event1.event_id  # age=14<=15 -- geri döndü


# ---------------------------------------------------------------------------
# HATA 4A causality regression: prefix view'da PENDING olan bir event, full
# history'de sonradan CONFIRMED olsa bile "T'de zaten CONFIRMED" olarak
# geriye YAZILMAMALI -- prefix ile sorgulanan timeline hâlâ PENDING göstermeli.
# ---------------------------------------------------------------------------


def test_prefix_view_never_shows_a_future_confirmed_state_as_already_known():
    tail = [102, 103, 104, 105]
    df_full = _resistance_100_df(tail)
    event_day_pos = len(_RESISTANCE_100_CONSOLIDATION)

    df_prefix = df_full.iloc[: event_day_pos + 2]  # yalnızca T+1'e kadar (henüz T+3 yok)
    timeline_prefix = build_breakout_timeline(df_prefix, "TEST", **_KWARGS)
    timeline_full = build_breakout_timeline(df_full, "TEST", **_KWARGS)

    event_prefix = _find_bullish_events(timeline_prefix)[0]
    event_full = _find_bullish_events(timeline_full)[0]

    assert event_prefix.confirmation_state == ConfirmationState.PENDING_CONFIRMATION.value
    assert event_full.confirmation_state == ConfirmationState.CONFIRMED.value
    assert event_prefix.event_id == event_full.event_id  # aynı event, farklı zamanlarda sorgulanmış


# ---------------------------------------------------------------------------
# Legacy API mapping.
# ---------------------------------------------------------------------------


def test_legacy_mapping_expired_retest_maps_to_none_not_false():
    tail = [102, 103, 104, 105] + [110.0] * 10  # EXPIRED
    df = _resistance_100_df(tail)
    timeline = build_breakout_timeline(df, "TEST", **_KWARGS)
    event = _find_bullish_events(timeline)[0]
    assert event.retest_state == RetestState.EXPIRED.value

    legacy = to_legacy_breakout_event(event)
    assert legacy.confirmed is True
    assert legacy.retest_held is None  # EXPIRED != FAILED


def test_legacy_mapping_none_when_no_live_event():
    assert to_legacy_breakout_event(None) is None


@pytest.mark.parametrize(
    "confirmation_state,expected",
    [
        (ConfirmationState.PENDING_CONFIRMATION.value, None),
        (ConfirmationState.CONFIRMED.value, True),
        (ConfirmationState.INVALIDATED.value, False),
    ],
)
def test_legacy_confirmed_mapping_matrix(confirmation_state, expected):
    from app.engines.technical.breakout_timeline import _CONFIRMED_LEGACY_MAP

    assert _CONFIRMED_LEGACY_MAP[confirmation_state] == expected
