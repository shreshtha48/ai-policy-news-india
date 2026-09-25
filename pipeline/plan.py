"""Call planning: every network request is planned first, then filtered by the
ledger and daily budgets, then (unless --dry-run) executed.

Ledger (data/raw/_ledger.json)
  * permanent: calls whose answer can't change - Google News slices for
    months that have already ended. Fetched once, never again.
  * daily:     everything else, keyed by UTC date. The same call twice on the
    same day is skipped, so re-running costs no API quota.
Only successful calls are recorded, so a failed call is retried next run.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .models import RawArticle

log = logging.getLogger(__name__)


@dataclass
class Call:
    api: str                                   # google_news | gdelt | gnews | newsapi | newsdata | outlets
    state: str
    key: str                                   # unique description of the request
    run: Callable[[], list[RawArticle]]
    permanent: bool = False                    # result can't change (past-month slice)
    keyed: bool = False                        # spends a paid/limited API quota
    skip_reason: str = ""                      # set at plan time (e.g. missing API key)
    meta: dict = field(default_factory=dict)


def month_slices(since: str, today: date | None = None) -> list[tuple[str, str, bool]]:
    """[(after, before, is_closed)] month by month from `since` to today.
    Google's after:/before: are exclusive-ish, so slices overlap by a day;
    dedupe removes the overlap."""
    today = today or datetime.now(timezone.utc).date()
    d = date.fromisoformat(since).replace(day=1)
    out = []
    while d <= today:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        after = (d.replace(day=1)).isoformat()
        before = nxt.isoformat()
        closed = nxt + timedelta(days=3) <= today     # grace period for late indexing
        out.append((after, before, closed))
        d = nxt
    return out


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"permanent": {}, "daily": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("ledger unreadable, starting fresh: %s", path)
        self.today = datetime.now(timezone.utc).date().isoformat()

    def _day(self) -> dict:
        return self.data["daily"].setdefault(self.today, {})

    def done(self, c: Call) -> bool:
        return c.key in self.data["permanent"] or c.key in self._day().get(c.api, {})

    def used_today(self, api: str) -> int:
        return len(self._day().get(api, {}))

    def record(self, c: Call, n: int):
        if c.permanent:
            self.data["permanent"][c.key] = {"date": self.today, "n": n}
        self._day().setdefault(c.api, {})[c.key] = n
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # keep only the last 14 days of daily entries
        days = sorted(self.data["daily"])[-14:]
        self.data["daily"] = {d: self.data["daily"][d] for d in days}
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def triage(calls: list[Call], ledger: Ledger, budgets: dict[str, int]) -> tuple[list[Call], list[tuple[Call, str]]]:
    """Split planned calls into (to_run, skipped_with_reason), applying budgets."""
    run, skipped = [], []
    planned_per_api: dict[str, int] = {}
    for c in calls:
        if c.skip_reason:
            skipped.append((c, c.skip_reason)); continue
        if ledger.done(c):
            skipped.append((c, "already fetched" + (" (closed month)" if c.permanent else " today"))); continue
        if c.api in budgets:
            used = ledger.used_today(c.api) + planned_per_api.get(c.api, 0)
            if used >= budgets[c.api]:
                skipped.append((c, f"daily budget {budgets[c.api]} reached")); continue
        planned_per_api[c.api] = planned_per_api.get(c.api, 0) + 1
        run.append(c)
    return run, skipped
