from datetime import datetime, timezone

from app.engines.analysts.consensus import build_consensus, classify_consensus


def test_classify_consensus_strong_buy_dominant():
    score, label = classify_consensus(strong_buy=8, buy=3, hold=1, sell=0, strong_sell=0)
    assert label == "GUCLU_AL"
    assert score is not None and score > 1.2


def test_classify_consensus_mostly_buy():
    score, label = classify_consensus(strong_buy=1, buy=5, hold=3, sell=0, strong_sell=0)
    assert label == "AL"
    assert score is not None and 0.4 <= score < 1.2


def test_classify_consensus_hold_dominant():
    score, label = classify_consensus(strong_buy=0, buy=1, hold=6, sell=1, strong_sell=0)
    assert label == "TUT"
    assert score is not None and -0.4 < score < 0.4


def test_classify_consensus_sell_dominant():
    score, label = classify_consensus(strong_buy=0, buy=0, hold=1, sell=5, strong_sell=1)
    assert label == "SAT"


def test_classify_consensus_strong_sell_dominant():
    score, label = classify_consensus(strong_buy=0, buy=0, hold=0, sell=2, strong_sell=8)
    assert label == "GUCLU_SAT"


def test_classify_consensus_no_analysts_returns_veri_yok():
    score, label = classify_consensus(strong_buy=0, buy=0, hold=0, sell=0, strong_sell=0)
    assert score is None
    assert label == "VERI_YOK"


def test_build_consensus_computes_upside_and_totals():
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    raw = {
        "price_targets": {"current": 300.0, "high": 580.0, "low": 330.0, "mean": 460.0, "median": 450.0},
        "recommendations": [
            {"period": "0m", "strong_buy": 3, "buy": 8, "hold": 2, "sell": 0, "strong_sell": 0},
            {"period": "-1m", "strong_buy": 3, "buy": 7, "hold": 2, "sell": 0, "strong_sell": 0},
        ],
    }

    consensus = build_consensus("THYAO", raw, now)

    assert consensus.total_analysts == 13
    assert consensus.consensus_label == "AL"
    assert consensus.price_target_mean == 460.0
    assert consensus.upside_pct == round((460.0 - 300.0) / 300.0 * 100, 1)
    assert len(consensus.trend) == 2


def test_build_consensus_handles_missing_recommendations():
    # Bazı BIST hisselerinde (örn. SASA) analist takibi yok — sadece
    # 'current' fiyat dönebilir, recommendations boş liste olabilir.
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    raw = {"price_targets": {"current": 2.27}, "recommendations": []}

    consensus = build_consensus("SASA", raw, now)

    assert consensus.total_analysts == 0
    assert consensus.consensus_label == "VERI_YOK"
    assert consensus.upside_pct is None
    assert consensus.price_target_mean is None
