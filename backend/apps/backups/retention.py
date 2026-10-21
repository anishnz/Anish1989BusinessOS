"""
Which old backups to keep ("grandfather-father-son"):

- every backup from the last `all_days` days,
- then the newest backup of each day, up to `daily_days` days old,
- then the newest backup of each month, for the last `monthly` months.

The newest backup is always kept. Days and months are counted in the
platform's time zone (TIME_ZONE, Pacific/Auckland by default).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone


def to_keep(items: list[tuple[object, datetime]], *, now: datetime, all_days: int, daily_days: int, monthly: int) -> set:
    """items: [(id, created time)]. Returns the ids to keep."""
    keep, days_seen, months_seen = set(), set(), set()
    ordered = sorted(items, key=lambda item: item[1], reverse=True)
    if ordered:
        keep.add(ordered[0][0])
    local_now = timezone.localtime(now)
    this_month = local_now.year * 12 + local_now.month
    for item_id, created in ordered:
        local = timezone.localtime(created)
        age = now - created
        day = local.date()
        month = local.year * 12 + local.month
        if age <= timedelta(days=all_days):
            keep.add(item_id)
        elif age <= timedelta(days=daily_days):
            if day not in days_seen:
                keep.add(item_id)
        elif this_month - month < monthly and month not in months_seen:
            keep.add(item_id)
        days_seen.add(day)
        months_seen.add(month)
    return keep
