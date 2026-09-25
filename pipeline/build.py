"""raw articles -> (articles, events, rejected) tables in the SCHEMA.md format."""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from datetime import date

from . import classify
from .dates import to_ist_date
from .dedupe import canonical_url, cluster, norm_title
from .geo import get_geo
from .models import RawArticle

log = logging.getLogger(__name__)

SINCE = "2025-01-01"          # records older than this are out of scope
# Primary-source preference: official > major outlets > everything else.
TIER1 = {"thehindu.com", "indianexpress.com", "hindustantimes.com", "timesofindia.indiatimes.com",
         "deccanherald.com", "economictimes.indiatimes.com", "livemint.com", "business-standard.com",
         "newindianexpress.com", "telanganatoday.com", "deccanchronicle.com", "thehansindia.com",
         "moneycontrol.com", "ndtv.com", "indiatoday.in", "medianama.com", "etgovernment.com"}
KIND_RANK = {"outlet_rss": 0, "outlet_scrape": 0, "gnews": 1, "gdelt": 1, "google_news_rss": 2}


def _tier(domain: str) -> int:
    if domain.endswith(".gov.in") or domain.endswith(".nic.in") or domain == "gov.in":
        return 0
    return 1 if domain in TIER1 else 2


def _hid(prefix: str, *parts: str, n: int = 10) -> str:
    return f"{prefix}-" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:n].upper()


def _first_sentence(s: str, limit: int = 220) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    s = m.group(1) if m else s
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def dedupe_articles(raw: list[RawArticle]) -> list[RawArticle]:
    """Stage 1: collapse the same article seen via several routes / runs."""
    by_key: dict[str, RawArticle] = {}
    alias: dict[str, str] = {}
    for a in raw:
        if not a.title or not a.url:
            continue
        k_url = canonical_url(a.url)
        k_title = f"{a.source_domain or a.source_name.lower()}|{norm_title(a.title)}"
        key = alias.get(k_url) or alias.get(k_title) or k_url
        alias[k_url] = alias[k_title] = key
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = a
            continue
        # merge: keep the richer / more direct record, fill gaps from the other
        better, other = (a, cur) if KIND_RANK.get(a.source_kind, 3) < KIND_RANK.get(cur.source_kind, 3) else (cur, a)
        better.published = better.published or other.published
        better.excerpt = better.excerpt or other.excerpt
        better.source_domain = better.source_domain or other.source_domain
        better.extra = {**other.extra, **better.extra,
                        "seen_via": sorted(set(better.extra.get("seen_via", [better.source_kind]) +
                                               other.extra.get("seen_via", [other.source_kind])))}
        by_key[key] = better
    return list(by_key.values())


def build(raw: list[RawArticle], since: str = SINCE):
    geo = get_geo()
    arts = dedupe_articles(raw)
    kept, rejected = [], []
    for a in arts:
        d, prec = to_ist_date(a.published)
        text = f"{a.title}. {a.excerpt}"
        base = {"title": a.title, "source_name": a.source_name, "source_url": a.url,
                "published_date": d, "fetched_via": a.source_kind}
        if d and d < since:
            rejected.append({**base, "state_code": "", "reason": "before_" + since}); continue
        v = classify.judge(a.title, a.excerpt)
        g = geo.resolve(text, hint=a.state_hint or None)
        if not v.keep:
            rejected.append({**base, "state_code": g.state_code or "", "reason": v.reason}); continue
        if not g.state_code:
            rejected.append({**base, "state_code": "", "reason": "no_state"}); continue
        if not g.in_focus:
            rejected.append({**base, "state_code": g.state_code, "reason": "non_focus_state"}); continue
        kept.append({"raw": a, "date": d, "precision": prec, "state_code": g.state_code,
                     "city": g.city or "", "state_basis": g.basis, "category": v.category,
                     "sector": v.sector, "title": a.title, "text": text,
                     "canon": canonical_url(a.url), "domain": a.source_domain})

    groups = cluster(kept)
    events, articles = [], []
    cat_order = [c for c, _ in classify.CATEGORY_RULES]
    for g in groups:
        members = [kept[i] for i in g]
        members.sort(key=lambda m: (m["date"] or "9999", _tier(m["domain"]), KIND_RANK.get(m["raw"].source_kind, 3)))
        primary = min(members, key=lambda m: (_tier(m["domain"]), m["date"] or "9999",
                                               KIND_RANK.get(m["raw"].source_kind, 3)))
        dated = [m["date"] for m in members if m["date"]]
        first = min(dated) if dated else ""
        cats = Counter(m["category"] for m in members)
        top = max(cats.values())
        category = min((c for c in cats if cats[c] == top), key=cat_order.index)
        sectors = Counter(m["sector"] for m in members if m["sector"])
        cities = Counter(m["city"] for m in members if m["city"])
        all_text = " ".join(m["text"] for m in members)
        excerpt = next((m["raw"].excerpt for m in [primary] + members if m["raw"].excerpt), "")
        amount = classify.amount_crore(all_text) if category in ("budget_funding", "partnership") else None
        eid = _hid("EVT", primary["state_code"], members[0]["canon"], n=8)
        outlets = {(m["domain"] or m["raw"].source_name.lower()) for m in members}
        events.append({
            "event_id": eid,
            "state_code": primary["state_code"],
            "state_name": geo.names.get(primary["state_code"], primary["state_code"]),
            "city": cities.most_common(1)[0][0] if cities else "",
            "category": category,
            "sector": sectors.most_common(1)[0][0] if sectors else "",
            "title": primary["title"],
            "summary": _first_sentence(excerpt) if excerpt else _first_sentence(primary["title"]),
            "event_date": first,
            "date_precision": "day" if first else "unknown",
            "first_reported_date": first or date.fromisoformat(primary["raw"].fetched_at[:10]).isoformat(),
            "primary_source_name": primary["raw"].source_name,
            "primary_source_url": primary["raw"].url,
            "source_count": len(outlets),
            "actors": "; ".join(classify.actors_of(all_text)),
            "amount_inr_crore": "" if amount is None else (int(amount) if amount == int(amount) else amount),
        })
        for m in members:
            articles.append({
                "article_id": _hid("ART", m["canon"]),
                "event_id": eid,
                "state_code": m["state_code"],
                "title": m["title"],
                "source_name": m["raw"].source_name,
                "source_url": m["raw"].url,
                "published_date": m["date"],
                "fetched_via": m["raw"].source_kind,
                "is_primary": "true" if m is primary else "false",
                "state_basis": m["state_basis"],
            })
    events.sort(key=lambda e: (e["first_reported_date"], e["source_count"]), reverse=True)
    articles.sort(key=lambda a: (a["event_id"], a["published_date"]))
    log.info("raw=%d unique=%d kept=%d events=%d rejected=%d", len(raw), len(arts), len(kept),
             len(events), len(rejected))
    return events, articles, rejected
