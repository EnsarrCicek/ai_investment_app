from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.technical.session_timing import ISTANBUL_TZ, classify_session_time

# 2026-08-17 bir Pazartesi (hafta içi)
_MONDAY = "2026-08-17"
# 2026-08-15 bir Cumartesi (hafta sonu)
_SATURDAY = "2026-08-15"


def _istanbul(date_str: str, hour: int, minute: int) -> datetime:
    return datetime.fromisoformat(f"{date_str}T{hour:02d}:{minute:02d}:00").replace(tzinfo=ISTANBUL_TZ)


def test_classify_session_time_opening_window():
    assert classify_session_time(_istanbul(_MONDAY, 10, 5)) == "OPENING"


def test_classify_session_time_midday():
    assert classify_session_time(_istanbul(_MONDAY, 13, 0)) == "MIDDAY"


def test_classify_session_time_closing_window():
    assert classify_session_time(_istanbul(_MONDAY, 17, 45)) == "CLOSING"


def test_classify_session_time_before_open_is_closed():
    assert classify_session_time(_istanbul(_MONDAY, 9, 30)) == "CLOSED"


def test_classify_session_time_at_close_is_closed():
    assert classify_session_time(_istanbul(_MONDAY, 18, 0)) == "CLOSED"


def test_classify_session_time_weekend_is_closed():
    assert classify_session_time(_istanbul(_SATURDAY, 12, 0)) == "CLOSED"


def test_classify_session_time_converts_from_other_timezone():
    # UTC 07:05 -> İstanbul (UTC+3, DST yok varsayımıyla test tarihinde +3) 10:05 -> OPENING
    utc_time = datetime(2026, 8, 17, 7, 5, tzinfo=ZoneInfo("UTC"))
    assert classify_session_time(utc_time) == "OPENING"


def test_classify_session_time_naive_datetime_assumed_istanbul():
    naive = datetime(2026, 8, 17, 10, 5)  # tzinfo yok
    assert classify_session_time(naive) == "OPENING"
