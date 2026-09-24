"""Holdout başlangıcı kuralı (protokol `holdout_status.activation_note`):
market open'ı (10:00 Europe/Istanbul) aktivasyon anından KESİNLİKLE sonra olan
ilk BIST seansı."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.research.technical_holdout import (
    HoldoutStartUndeterminableError,
    compute_effective_holdout_start,
    session_is_in_holdout,
)

IST = ZoneInfo("Europe/Istanbul")


@pytest.mark.parametrize(
    ("activation", "expected"),
    [
        (datetime(2026, 8, 21, 9, 59, 59, tzinfo=IST), date(2026, 8, 21)),  # açılıştan önce -> aynı gün
        (datetime(2026, 8, 21, 10, 0, 0, tzinfo=IST), date(2026, 8, 24)),  # TAM açılış -> strictly-after değil
        (datetime(2026, 8, 21, 10, 0, 1, tzinfo=IST), date(2026, 8, 24)),  # seans içinde -> sonraki seans
        (datetime(2026, 8, 21, 19, 0, tzinfo=IST), date(2026, 8, 24)),  # kapanıştan sonra, Cuma
        (datetime(2026, 8, 22, 6, 0, tzinfo=IST), date(2026, 8, 24)),  # hafta sonu
        (datetime(2026, 8, 20, 23, 30, tzinfo=timezone.utc), date(2026, 8, 21)),  # UTC gece yarısı -> IST ertesi gün
        (datetime(2026, 5, 26, 10, 30, tzinfo=IST), date(2026, 6, 1)),  # arife yarım günü + Kurban Bayramı tatili
    ],
)
def test_first_session_whose_open_is_strictly_after_activation(activation, expected):
    assert compute_effective_holdout_start(activation) == expected


def test_start_is_a_pure_function_of_the_initial_event_time():
    t = datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc)  # 09:00 IST
    assert {compute_effective_holdout_start(t) for _ in range(3)} == {date(2026, 9, 16)}


def test_unsupported_calendar_year_fails_closed():
    with pytest.raises(HoldoutStartUndeterminableError):
        compute_effective_holdout_start(datetime(2026, 12, 31, 12, 0, tzinfo=IST))
    with pytest.raises(HoldoutStartUndeterminableError):
        compute_effective_holdout_start(datetime(2027, 1, 5, 8, 0, tzinfo=IST))


def test_naive_activation_time_rejected():
    with pytest.raises(ValueError):
        compute_effective_holdout_start(datetime(2026, 8, 21, 8, 0))


def test_session_eligibility_boundary():
    start = date(2026, 8, 24)
    assert not session_is_in_holdout("2026-08-21", start)
    assert session_is_in_holdout("2026-08-24", start)
    assert session_is_in_holdout("2026-08-25", start)
