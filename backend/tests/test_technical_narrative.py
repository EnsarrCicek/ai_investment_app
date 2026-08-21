from app.engines.technical.narrative import build_narrative

_RESISTANCE_ZONE = {"type": "RESISTANCE", "low": 330.0, "high": 335.0, "touch_count": 3}
_SUPPORT_ZONE = {"type": "SUPPORT", "low": 300.0, "high": 305.0, "touch_count": 2}


def test_bullish_confirmed_breakout_with_retest_held():
    breakout = {
        "direction": "BULLISH",
        "breakout_atr": 0.8,
        "confirmed": True,
        "retest_held": True,
        "zone": _RESISTANCE_ZONE,
    }

    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, breakout)

    assert "330.00" in narrative and "335.00" in narrative
    assert "3 kez test edilmiş" in narrative
    assert "yukarı yönlü kırdı" in narrative
    assert "teyit edildi" in narrative
    assert "yeni destek rolünü test etti ve seviye tutuldu" in narrative
    assert "yükselişin devam etme ihtimalini artırır" in narrative


def test_bearish_confirmed_breakout_without_retest():
    breakout = {
        "direction": "BEARISH",
        "breakout_atr": 1.2,
        "confirmed": True,
        "retest_held": None,
        "zone": _SUPPORT_ZONE,
    }

    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, breakout)

    assert "aşağı yönlü kırdı" in narrative
    assert "düşüşün devam etme ihtimalini artırır" in narrative
    assert "yeni destek rolünü" not in narrative


def test_false_breakout_is_flagged():
    breakout = {
        "direction": "BULLISH",
        "breakout_atr": 0.3,
        "confirmed": False,
        "retest_held": None,
        "zone": _RESISTANCE_ZONE,
    }

    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, breakout)

    assert "YANLIŞ (false breakout)" in narrative
    assert "güvenilmemeli" in narrative


def test_unconfirmed_breakout_says_not_yet_known():
    breakout = {
        "direction": "BULLISH",
        "breakout_atr": 0.5,
        "confirmed": None,
        "retest_held": None,
        "zone": _RESISTANCE_ZONE,
    }

    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, breakout)

    assert "henüz teyit edilmedi" in narrative


def test_retest_failed_raises_doubt():
    breakout = {
        "direction": "BULLISH",
        "breakout_atr": 0.5,
        "confirmed": True,
        "retest_held": False,
        "zone": _RESISTANCE_ZONE,
    }

    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, breakout)

    assert "seviye tutulmadı" in narrative


def test_no_breakout_describes_nearest_levels():
    narrative = build_narrative(_SUPPORT_ZONE, _RESISTANCE_ZONE, None)

    assert "en yakın" in narrative
    assert "300.00" in narrative and "305.00" in narrative
    assert "330.00" in narrative and "335.00" in narrative


def test_no_breakout_and_no_zones_returns_honest_message():
    narrative = build_narrative(None, None, None)

    assert narrative == "Şu an belirgin bir destek/direnç bölgesi tespit edilemedi (yeterli swing noktası yok)."
