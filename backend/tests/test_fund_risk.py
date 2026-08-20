from app.engines.funds.risk import classify_risk


def test_high_equity_exposure_classified_as_high_risk():
    result = classify_risk({"stock_pct": 80.0, "foreign_stock_pct": 5.0})

    assert result["risk_level"] == "YUKSEK"
    assert result["equity_exposure_pct"] == 85.0


def test_high_safe_exposure_classified_as_low_risk():
    result = classify_risk({"repo_pct": 40.0, "term_deposit_pct": 30.0, "government_bond_pct": 10.0})

    assert result["risk_level"] == "DUSUK"
    assert result["safe_exposure_pct"] == 80.0


def test_mixed_exposure_classified_as_medium_risk():
    result = classify_risk({"stock_pct": 30.0, "government_bond_pct": 30.0})

    assert result["risk_level"] == "ORTA"


def test_missing_columns_treated_as_zero():
    result = classify_risk({})

    assert result["equity_exposure_pct"] == 0.0
    assert result["safe_exposure_pct"] == 0.0
    assert result["risk_level"] == "ORTA"
