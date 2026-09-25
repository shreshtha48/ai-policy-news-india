"""Date normalisation. Everything becomes an IST calendar date (India news);
unknown stays unknown - we never invent a date.

Returns (YYYY-MM-DD or "", precision) with precision in {day, month, unknown}.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def to_ist_date(value: str) -> tuple[str, str]:
    v = (value or "").strip()
    if not v:
        return "", "unknown"
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)          # naive timestamps from Indian sites are IST
        return dt.astimezone(IST).date().isoformat(), "day"
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return v, "day"
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", v)          # "Mar 2026"
    if m and m.group(1).lower() in _MONTHS:
        return date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1).isoformat(), "month"
    return "", "unknown"
