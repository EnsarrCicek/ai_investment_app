from app.engines.technical.market_structure import SwingPoint, SwingType
from app.engines.technical.support_resistance import build_zones, nearest_zone


def _sp(index: int, price: float, swing_type: SwingType) -> SwingPoint:
    return SwingPoint(index=index, date=None, price=price, type=swing_type)


def test_build_zones_clusters_close_lows_into_one_support_zone():
    points = [
        _sp(0, 100.0, SwingType.LOW),
        _sp(10, 100.5, SwingType.LOW),  # ATR=2, eşik=0.5*2=1.0 -> aynı zone
        _sp(20, 101.0, SwingType.LOW),
    ]
    zones = build_zones(points, atr=2.0, zone_width_atr=0.5)

    assert len(zones) == 1
    zone = zones[0]
    assert zone.type == "SUPPORT"
    assert zone.touch_count == 3
    assert zone.low == 100.0
    assert zone.high == 101.0


def test_build_zones_splits_distant_highs_into_separate_resistance_zones():
    points = [
        _sp(0, 100.0, SwingType.HIGH),
        _sp(10, 110.0, SwingType.HIGH),  # ATR=2, fark=10 >> eşik=1.0
    ]
    zones = build_zones(points, atr=2.0, zone_width_atr=0.5)

    assert len(zones) == 2
    assert all(z.type == "RESISTANCE" for z in zones)
    assert {z.touch_count for z in zones} == {1}


def test_build_zones_separates_support_and_resistance():
    points = [_sp(0, 100.0, SwingType.LOW), _sp(5, 110.0, SwingType.HIGH)]
    zones = build_zones(points, atr=1.0)

    assert {z.type for z in zones} == {"SUPPORT", "RESISTANCE"}


def test_build_zones_returns_empty_for_non_positive_atr():
    points = [_sp(0, 100.0, SwingType.LOW)]
    assert build_zones(points, atr=0.0) == []


def test_nearest_zone_finds_closest_by_midpoint():
    points = [_sp(0, 90.0, SwingType.LOW), _sp(10, 120.0, SwingType.HIGH)]
    zones = build_zones(points, atr=1.0)

    assert nearest_zone(zones, price=95.0).type == "SUPPORT"


def test_nearest_zone_respects_type_filter():
    points = [
        _sp(0, 90.0, SwingType.LOW),
        _sp(10, 91.0, SwingType.LOW),
        _sp(20, 120.0, SwingType.HIGH),
    ]
    zones = build_zones(points, atr=1.0)

    assert nearest_zone(zones, price=91.0, zone_type="RESISTANCE").type == "RESISTANCE"


def test_nearest_zone_returns_none_when_no_zones():
    assert nearest_zone([], price=100.0) is None
