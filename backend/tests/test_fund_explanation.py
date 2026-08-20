from app.engines.funds.explanation import build_explanation


def test_includes_all_available_return_horizons():
    text = build_explanation(5.0, 10.0, 20.0, 30.0, "YUKSEK", rank=1, total_count=100)

    assert "1 ay: %+5.0" in text
    assert "1 yıl: %+30.0" in text
    assert "1. sırada" in text
    assert "Yüksek" in text


def test_omits_missing_horizons():
    text = build_explanation(None, None, None, 30.0, "DUSUK", rank=5, total_count=50)

    assert "1 ay" not in text
    assert "1 yıl: %+30.0" in text


def test_handles_negative_returns_with_sign():
    text = build_explanation(-3.5, None, None, None, "ORTA", rank=10, total_count=20)

    assert "%-3.5" in text


def test_notes_missing_risk_level():
    text = build_explanation(1.0, None, None, None, None, rank=1, total_count=1)

    assert "hesaplanamadı" in text
