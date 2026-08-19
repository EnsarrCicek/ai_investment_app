import pandas as pd

from app.engines.technical.chart_patterns import (
    confirm_double_bottom,
    confirm_double_top,
    find_double_bottom_candidates,
    find_double_top_candidates,
)
from app.engines.technical.market_structure import SwingPoint, SwingType


def _sp(index: int, price: float, swing_type: SwingType) -> SwingPoint:
    return SwingPoint(index=index, date=None, price=price, type=swing_type)


def test_find_double_bottom_candidates_detects_matching_lows_with_neckline():
    points = [
        _sp(5, 100.0, SwingType.LOW),
        _sp(10, 110.0, SwingType.HIGH),
        _sp(15, 101.0, SwingType.LOW),
    ]
    candidates = find_double_bottom_candidates(points, atr=5.0, tolerance_atr=0.5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["first"].index == 5
    assert candidate["second"].index == 15
    assert candidate["neckline"].index == 10


def test_find_double_bottom_candidates_rejects_lows_too_far_apart():
    points = [
        _sp(5, 100.0, SwingType.LOW),
        _sp(10, 110.0, SwingType.HIGH),
        _sp(15, 130.0, SwingType.LOW),  # fark 30, tolerans 2.5
    ]
    assert find_double_bottom_candidates(points, atr=5.0, tolerance_atr=0.5) == []


def test_find_double_bottom_candidates_requires_high_between_lows():
    points = [_sp(5, 100.0, SwingType.LOW), _sp(10, 101.0, SwingType.LOW)]
    assert find_double_bottom_candidates(points, atr=5.0) == []


def test_find_double_bottom_candidates_returns_empty_for_non_positive_atr():
    points = [_sp(5, 100.0, SwingType.LOW), _sp(10, 110.0, SwingType.HIGH), _sp(15, 101.0, SwingType.LOW)]
    assert find_double_bottom_candidates(points, atr=0.0) == []


def test_find_double_top_candidates_detects_matching_highs_with_neckline():
    points = [
        _sp(5, 120.0, SwingType.HIGH),
        _sp(10, 110.0, SwingType.LOW),
        _sp(15, 119.0, SwingType.HIGH),
    ]
    candidates = find_double_top_candidates(points, atr=5.0, tolerance_atr=0.5)

    assert len(candidates) == 1
    assert candidates[0]["neckline"].index == 10


def test_confirm_double_bottom_true_when_price_breaks_above_neckline():
    candidate = {
        "first": _sp(5, 100.0, SwingType.LOW),
        "second": _sp(15, 101.0, SwingType.LOW),
        "neckline": _sp(10, 110.0, SwingType.HIGH),
    }
    close = pd.Series([100.0] * 16 + [105.0, 108.0, 112.0, 115.0])  # index16-19 sonrası neckline'ı kırıyor

    event = confirm_double_bottom(close, candidate)
    assert event.type == "DOUBLE_BOTTOM"
    assert event.confirmed is True


def test_confirm_double_bottom_false_when_neckline_not_yet_broken():
    candidate = {
        "first": _sp(5, 100.0, SwingType.LOW),
        "second": _sp(15, 101.0, SwingType.LOW),
        "neckline": _sp(10, 110.0, SwingType.HIGH),
    }
    close = pd.Series([100.0] * 16 + [105.0, 108.0, 109.0, 109.0])  # hiçbiri 110'u geçmiyor

    event = confirm_double_bottom(close, candidate)
    assert event.confirmed is False


def test_confirm_double_top_true_when_price_breaks_below_neckline():
    candidate = {
        "first": _sp(5, 120.0, SwingType.HIGH),
        "second": _sp(15, 119.0, SwingType.HIGH),
        "neckline": _sp(10, 110.0, SwingType.LOW),
    }
    close = pd.Series([120.0] * 16 + [115.0, 112.0, 108.0, 105.0])  # 110'un altına iniyor

    event = confirm_double_top(close, candidate)
    assert event.type == "DOUBLE_TOP"
    assert event.confirmed is True


def test_confirm_double_top_false_when_neckline_not_yet_broken():
    candidate = {
        "first": _sp(5, 120.0, SwingType.HIGH),
        "second": _sp(15, 119.0, SwingType.HIGH),
        "neckline": _sp(10, 110.0, SwingType.LOW),
    }
    close = pd.Series([120.0] * 16 + [115.0, 112.0, 111.0, 111.0])  # hiçbiri 110'un altına inmiyor

    event = confirm_double_top(close, candidate)
    assert event.confirmed is False
