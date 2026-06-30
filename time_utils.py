"""
Timezone helpers for reports and daily counters.

The bot is usually deployed on Railway, where the server clock may be UTC.
Learners use the bot in Vietnam, so "today" should be based on Vietnam time.
"""

import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", DEFAULT_TIMEZONE)

try:
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    print(f"Invalid APP_TIMEZONE '{APP_TIMEZONE_NAME}', falling back to {DEFAULT_TIMEZONE}.")
    APP_TIMEZONE_NAME = DEFAULT_TIMEZONE
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


def now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def today_local():
    return now_local().date()


def local_date_for(value: datetime):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE).date()


def local_day_bounds_utc(day):
    start_local = datetime.combine(day, time.min, tzinfo=APP_TIMEZONE)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def report_window_bounds_utc(end_utc=None):
    """
    Return the reporting window as the last 24 hours.

    Reports are sent at 23:00 ICT by default, so using the calendar day would
    permanently miss messages sent between 23:00 and midnight. A rolling report
    window matches the actual schedule: previous report time -> current report time.
    """
    if end_utc is None:
        end_utc = datetime.now(timezone.utc)
    elif end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)

    end_utc = end_utc.astimezone(timezone.utc)
    return end_utc - timedelta(days=1), end_utc


def as_db_utc_naive(value: datetime) -> datetime:
    """Match PostgreSQL TIMESTAMP values that are stored in UTC."""
    return value.astimezone(timezone.utc).replace(tzinfo=None)
