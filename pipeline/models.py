"""Common record every source emits. Sources know nothing about dedupe/classification."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RawArticle:
    source_kind: str            # google_news_rss | gdelt | gnews | outlet_rss | outlet_scrape
    title: str
    url: str
    source_name: str            # outlet, e.g. "The Hindu"
    source_domain: str = ""     # e.g. thehindu.com
    published: str = ""         # ISO-8601 datetime (UTC or with offset) or "" if unknown
    excerpt: str = ""
    state_hint: str = ""        # state the query/feed was for (tie-breaker only)
    query: str = ""             # query or feed URL that produced it (audit)
    fetched_at: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RawArticle":
        known = {k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "extra"}
        return cls(**known, extra=d.get("extra") or {})
