from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.engines.technical.history_window import (
    ANALYSIS_WINDOW_MONTHS,
    PRE_ROLL_DAYS,
    HistoryValidationStatus,
    compute_history_window,
    resolve_expected_start,
)

TZ = ZoneInfo("Europe/Istanbul")


def test_compute_history_window_uses_relativedelta_months_not_fixed_days():
    now = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)

    window = compute_history_window(now)

    assert window.analysis_start == date(2026, 2, 25)
    assert window.provider_request_start == date(2026, 2, 10)  # analysis_start - 15 gün
    assert window.provider_request_end == date(2026, 8, 26)  # now + 1 gün (Yahoo 'end' exclusive)


def test_compute_history_window_constants_unchanged():
    assert ANALYSIS_WINDOW_MONTHS == 6
    assert PRE_ROLL_DAYS == 15


def _df_from_dates(dates: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": [100.0] * len(dates),
            "High": [101.0] * len(dates),
            "Low": [99.0] * len(dates),
            "Close": [100.0] * len(dates),
            "Volume": [1000] * len(dates),
        },
        index=index,
    )


def test_resolve_expected_start_verified_when_pre_roll_has_evidence():
    analysis_start = date(2026, 2, 25)
    # pre-roll penceresinde (analysis_start'tan ONCE) en az bir bar var.
    provider_history = _df_from_dates(["2026-02-12", "2026-02-26", "2026-03-01"])

    expected_start, status = resolve_expected_start(provider_history, analysis_start)

    assert expected_start == analysis_start
    assert status == HistoryValidationStatus.VERIFIED_PRE_WINDOW


def test_resolve_expected_start_unverified_when_pre_roll_empty():
    analysis_start = date(2026, 2, 25)
    provider_history = _df_from_dates([])

    expected_start, status = resolve_expected_start(provider_history, analysis_start)

    assert expected_start == analysis_start
    assert status == HistoryValidationStatus.LEADING_EDGE_UNVERIFIED


def test_resolve_expected_start_unverified_when_first_bar_after_analysis_start():
    # Sağlayıcı, pre-roll dahil hiçbir bar analysis_start'tan ÖNCEYE ait değil
    # (ör. yeni halka arz VEYA sağlayıcının pre-roll'u tamamen kaybetmesi —
    # ikisi ayırt edilemez, bkz. modül docstring'i).
    analysis_start = date(2026, 2, 25)
    provider_history = _df_from_dates(["2026-03-01", "2026-03-02"])

    expected_start, status = resolve_expected_start(provider_history, analysis_start)

    assert expected_start == date(2026, 3, 1)  # ilk gözlemlenen bar
    assert status == HistoryValidationStatus.LEADING_EDGE_UNVERIFIED


def test_resolve_expected_start_empty_provider_history_is_unverified():
    analysis_start = date(2026, 2, 25)

    expected_start, status = resolve_expected_start(pd.DataFrame(), analysis_start)

    assert expected_start == analysis_start
    assert status == HistoryValidationStatus.LEADING_EDGE_UNVERIFIED
