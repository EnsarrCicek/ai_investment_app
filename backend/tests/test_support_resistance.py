from app.engines.technical.market_structure import SwingPoint, SwingType
from app.engines.technical.support_resistance import SRZone, build_zones, is_display_role_invalid, nearest_zone


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


# --- HATA 11J: is_display_role_invalid() -- pure current-geometry rule ---


def _zone(zone_type: str, low: float, high: float) -> SRZone:
    return SRZone(type=zone_type, low=low, high=high, touch_count=1, last_touch_index=0)


def test_display_role_invalid_support_price_below_low_is_invalid():
    zone = _zone("SUPPORT", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=99.99) is True


def test_display_role_invalid_support_price_exactly_at_low_is_valid():
    zone = _zone("SUPPORT", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=100.0) is False


def test_display_role_invalid_support_price_inside_band_is_valid():
    zone = _zone("SUPPORT", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=102.5) is False


def test_display_role_invalid_support_price_exactly_at_high_is_valid():
    zone = _zone("SUPPORT", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=105.0) is False


def test_display_role_invalid_support_price_above_high_is_valid():
    # SUPPORT'un kendi bandının ÜSTÜNDE olmak onun rolünü bozmaz -- yalnız
    # zone.low'un ALTINA düşmek geçersiz sayılır (bkz. HATA 11H/11I audit'i).
    zone = _zone("SUPPORT", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=110.0) is False


def test_display_role_invalid_resistance_price_above_high_is_invalid():
    zone = _zone("RESISTANCE", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=105.01) is True


def test_display_role_invalid_resistance_price_exactly_at_high_is_valid():
    zone = _zone("RESISTANCE", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=105.0) is False


def test_display_role_invalid_resistance_price_inside_band_is_valid():
    zone = _zone("RESISTANCE", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=102.5) is False


def test_display_role_invalid_resistance_price_exactly_at_low_is_valid():
    zone = _zone("RESISTANCE", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=100.0) is False


def test_display_role_invalid_resistance_price_below_low_is_valid():
    zone = _zone("RESISTANCE", low=100.0, high=105.0)
    assert is_display_role_invalid(zone, price=95.0) is False


# --- HATA 11J: nearest_zone(..., active_only=True) ---


def test_active_only_nearest_support_skips_invalid_closer_zone():
    price = 100.0
    invalid_closer = _zone("SUPPORT", low=101.0, high=102.0)  # price(100) < low(101) -> invalid
    valid_farther = _zone("SUPPORT", low=90.0, high=95.0)  # price(100) >= low(90) -> valid
    zones = [invalid_closer, valid_farther]

    assert nearest_zone(zones, price=price, zone_type="SUPPORT", active_only=True) is valid_farther


def test_active_only_nearest_resistance_skips_invalid_closer_zone():
    price = 100.0
    invalid_closer = _zone("RESISTANCE", low=98.0, high=99.0)  # price(100) > high(99) -> invalid
    valid_farther = _zone("RESISTANCE", low=105.0, high=110.0)  # price(100) <= high(110) -> valid
    zones = [invalid_closer, valid_farther]

    assert nearest_zone(zones, price=price, zone_type="RESISTANCE", active_only=True) is valid_farther


def test_active_only_nearest_returns_none_when_all_candidates_invalid():
    price = 100.0
    zones = [_zone("SUPPORT", low=101.0, high=102.0), _zone("SUPPORT", low=103.0, high=104.0)]

    assert nearest_zone(zones, price=price, zone_type="SUPPORT", active_only=True) is None


def test_active_only_nearest_still_selects_boundary_candidate():
    price = 100.0
    boundary_valid = _zone("SUPPORT", low=100.0, high=101.0)  # price == low -> valid (sınırda)

    assert nearest_zone([boundary_valid], price=price, zone_type="SUPPORT", active_only=True) is boundary_valid


def test_nearest_zone_generic_behavior_unchanged_when_active_only_not_requested():
    # HATA 11J item 16 -- active_only istenmediginde (varsayilan/eski
    # cagiranlar) yapisal-en-yakin davranis DEGISMEMELI: gecersiz bir zone
    # yine de "en yakin" olarak donebilmeli, tipki active_only eklenmeden
    # ONCEKI davranista oldugu gibi.
    price = 100.0
    invalid_closer = _zone("SUPPORT", low=101.0, high=102.0)
    valid_farther = _zone("SUPPORT", low=90.0, high=95.0)
    zones = [invalid_closer, valid_farther]

    assert nearest_zone(zones, price=price, zone_type="SUPPORT") is invalid_closer
    assert nearest_zone(zones, price=price, zone_type="SUPPORT", active_only=False) is invalid_closer
