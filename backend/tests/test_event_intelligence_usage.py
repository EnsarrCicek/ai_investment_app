from datetime import date, datetime, timedelta, timezone

import pytest

from app.engines.event_intelligence.usage import compute_cost_usd, summarize
from app.models.token_usage import TokenUsageLog


def test_compute_cost_usd_luna():
    # $0.20/1M girdi + $1.20/1M çıktı
    cost = compute_cost_usd("gpt-5.6-luna", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == pytest.approx(1.40)


def test_compute_cost_usd_unknown_model_falls_back_to_luna_pricing():
    cost_unknown = compute_cost_usd("some-future-model", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    cost_luna = compute_cost_usd("gpt-5.6-luna", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost_unknown == cost_luna


_ANCHOR = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _log(cost_usd, days_ago=0, total_tokens=150):
    # Gerçek "şimdi"ye değil, sabit bir referans ana göre hesaplanır — testler
    # gece yarısını (UTC) geçtiğinde "days_ago=0" ile sabit `today` parametresi
    # uyuşmaz hale gelip kırılgan (flaky) olmasın diye.
    created = _ANCHOR - timedelta(days=days_ago)
    return TokenUsageLog(
        news_id="n",
        asset="THYAO",
        model_used="gpt-5.6-luna",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        created_at=created,
    )


def test_summarize_empty_logs():
    result = summarize([], budget_usd=5.0)
    assert result["spent_total_usd"] == 0
    assert result["remaining_usd"] == 5.0
    assert result["spent_today_usd"] == 0
    assert result["calls_today"] == 0
    assert result["daily_breakdown"] == []


def test_summarize_splits_today_vs_total():
    today = date(2026, 8, 18)
    logs = [
        _log(0.01, days_ago=0),
        _log(0.02, days_ago=0),
        _log(0.05, days_ago=1),
    ]
    result = summarize(logs, budget_usd=5.0, today=today)

    assert result["calls_total"] == 3
    assert result["calls_today"] == 2
    assert result["spent_today_usd"] == pytest.approx(0.03)
    assert result["spent_total_usd"] == pytest.approx(0.08)
    assert result["remaining_usd"] == pytest.approx(5.0 - 0.08)


def test_summarize_daily_breakdown_sorted_most_recent_first():
    today = date(2026, 8, 18)
    logs = [_log(0.01, days_ago=2), _log(0.02, days_ago=0), _log(0.03, days_ago=1)]
    result = summarize(logs, budget_usd=5.0, today=today)

    dates = [d["date"] for d in result["daily_breakdown"]]
    assert dates == sorted(dates, reverse=True)
