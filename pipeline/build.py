"""raw articles -> (events, articles, rejected) in the SCHEMA.md format.

Decision per article (after article-level dedupe):
  1. out of window (< since)               -> rejected  before_<since>
  2. excluded topic (markets, Air India..)  -> rejected  excluded_topic
  3. relevance, best available first:
       learned  = classifier trained on our hand labels (learned.py):
                  keep if P(relevant) >= CV-chosen threshold       ("learned")
       semantic = embedding similarity to prototypes (semantic.py):
                  keep if rules keep AND semantic.pos >= rule_floor ("rules+semantic")
                  or semantic.pos >= keep AND margin >= margin AND
                  (AI keyword present OR semantic.pos >= strong)    ("semantic")
       rules    = keyword judge only (no model installed)          ("rules")
     Near-misses read in full by `enrich` are judged on headline + lead text.
  4. state: text first; feed state only for state-specific outlet feeds
  5. category: headline keyword category if the headline names one,
     else the semantic category, else excerpt keywords, else statement_intent
Then events are clustered (dedupe.cluster) and summarised.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from pathlib import Path

from . import classify
from .dates import to_ist_date
from .dedupe import canonical_url, cluster, norm_title
from .geo import get_geo
from .keywords import get_lexicon, normalise
from .models import RawArticle
from .sources.rss import domain_of

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
SINCE = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["since"]

TIER1 = {"thehindu.com", "indianexpress.com", "hindustantimes.com", "timesofindia.indiatimes.com",
         "deccanherald.com", "economictimes.indiatimes.com", "livemint.com", "business-standard.com",
         "newindianexpress.com", "telanganatoday.com", "deccanchronicle.com", "thehansindia.com",
         "moneycontrol.com", "ndtv.com", "indiatoday.in", "medianama.com", "etgovernment.com",
         "deshgujarat.com", "freepressjournal.in", "dtnext.in", "ahmedabadmirror.com"}
# lower = preferred record when the same article arrives via several routes
KIND_RANK = {"outlet_rss": 0, "outlet_scrape": 0, "newsapi": 1, "gnews": 1, "newsdata": 1, "gdelt": 2,
             "google_news_rss": 3}
FEED_KINDS = {"outlet_rss", "outlet_scrape"}          # state-specific feeds: their state may be a fallback
GOOGLE_HOST = "news.google.com"


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


def is_resolved(url: str) -> bool:
    return GOOGLE_HOST not in url


def load_url_cache() -> dict:
    p = ROOT / "data" / "cache" / "google_urls.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def dedupe_articles(raw: list[RawArticle]) -> list[RawArticle]:
    """Stage 1: collapse the same article seen via several routes / runs.
    Keys: canonical URL, and (outlet domain, normalised headline) - the second
    is what joins a Google News redirect to the same article from an API or
    feed, whose REAL url is then kept (S3 step 1)."""
    url_cache = load_url_cache()
    by_key: dict[str, RawArticle] = {}
    alias: dict[str, str] = {}
    for a in raw:
        if not a.title or not a.url:
            continue
        if not is_resolved(a.url) and a.url in url_cache:        # decoded earlier (run resolve)
            a.extra = {**a.extra, "google_url": a.url}
            a.url = url_cache[a.url]
            a.source_domain = a.source_domain or domain_of(a.url)
        k_url = canonical_url(a.url)
        k_title = f"{a.source_domain or a.source_name.lower()}|{norm_title(a.title)}"
        key = alias.get(k_url) or alias.get(k_title) or k_url
        alias[k_url] = alias[k_title] = key
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = a
            continue
        better, other = (a, cur) if KIND_RANK.get(a.source_kind, 4) < KIND_RANK.get(cur.source_kind, 4) else (cur, a)
        if not is_resolved(better.url) and is_resolved(other.url):
            better.extra = {**better.extra, "google_url": better.url}
            better.url = other.url
        better.published = better.published or other.published
        better.excerpt = better.excerpt or other.excerpt
        better.source_domain = better.source_domain or other.source_domain
        better.state_hint = better.state_hint or other.state_hint
        kinds = set(better.extra.get("seen_via", [better.source_kind])) | set(other.extra.get("seen_via", [other.source_kind]))
        better.extra = {**other.extra, **better.extra, "seen_via": sorted(kinds)}
        by_key[key] = better
    return list(by_key.values())


def build(raw: list[RawArticle], since: str = SINCE, semantic="auto", learned="auto", bodies=None):
    """semantic / learned: 'auto' (use if available), None (off), or an instance.
    bodies: {url: lead text} from `enrich` ('auto' = data/cache/bodies.json)."""
    if semantic == "auto":
        from .semantic import get_semantic
        semantic = get_semantic()
    if learned == "auto":
        from .learned import get_learned
        learned = get_learned(semantic) if semantic else None
    if bodies is None:
        from .enrich import body_leads
        bodies = body_leads()
    geo, L = get_geo(), get_lexicon()
    arts = dedupe_articles(raw)
    for a in arts:                     # near-misses read in full: use the lead as the excerpt
        lead = bodies.get(a.url) or bodies.get(a.extra.get("google_url", ""))
        if lead and not a.excerpt:
            a.excerpt = lead[:600]
            a.extra = {**a.extra, "excerpt_from": "article"}
    rejected, cands = [], []
    for a in arts:
        d, prec = to_ist_date(a.published)
        base = {"title": a.title, "source_name": a.source_name, "source_url": a.url,
                "published_date": d, "fetched_via": a.source_kind}
        if d and d < since:
            rejected.append({**base, "state_code": "", "reason": f"before_{since}", "relevance_score": ""}); continue
        if L.exclude.find(normalise(a.title).split()) or classify.EXCLUDE_RE.search(a.title):
            rejected.append({**base, "state_code": "", "reason": "excluded_topic", "relevance_score": ""}); continue
        cands.append((a, d, base))

    texts = [f"{a.title}. {a.excerpt}".strip(" .") for a, _, _ in cands]
    sems = semantic.score(texts) if semantic else [None] * len(cands)
    probs = learned.proba(texts) if learned else [None] * len(cands)
    lcats = learned.category(texts) if learned else [""] * len(cands)
    t = semantic.t if semantic else {}

    kept = []
    for (a, d, base), text, sem, prob, lcat in zip(cands, texts, sems, probs, lcats):
        v = classify.judge(a.title, a.excerpt)
        has_ai = bool(L.ai.find(normalise(text).split()))
        score = round(sem.margin, 3) if sem else ""
        if prob is not None:
            score = round(float(prob), 3)
            keep = prob >= learned.threshold
            how, reason = ("learned", "") if keep else ("", "learned_low")
        elif sem is None:
            keep, how = v.keep, "rules"
            reason = v.reason
        else:
            sem_ok = sem.pos >= t["keep"] and sem.margin >= t["margin"] and (has_ai or sem.pos >= t["strong"])
            if v.keep and sem.pos >= t["rule_floor"]:
                keep, how, reason = True, "rules+semantic", ""
            elif sem_ok:
                keep, how, reason = True, "semantic", ""
            else:
                keep, how = False, ""
                reason = v.reason or "semantic_low"
                if v.keep:                          # rules said yes, meaning says clearly no
                    reason = "semantic_low"
        g = geo.resolve(text, hint=a.state_hint or None, hint_is_fallback=a.source_kind in FEED_KINDS)
        if not keep:
            rejected.append({**base, "state_code": g.state_code or "", "reason": reason, "relevance_score": score}); continue
        if not g.state_code:
            rejected.append({**base, "state_code": "", "reason": "no_state", "relevance_score": score}); continue
        if not g.in_focus:
            rejected.append({**base, "state_code": g.state_code, "reason": "non_focus_state", "relevance_score": score}); continue
        cat, src = classify.category_of(a.title, "")
        if src != "title":
            cat = lcat or (sem.category if sem else classify.category_of(a.title, a.excerpt)[0])
        L_sec = next((s for s in L.sector_order if L.sectors[s].any(normalise(text).split())), "")
        kept.append({"raw": a, "date": d, "precision": "day" if d else "unknown", "state_code": g.state_code,
                     "city": g.city or "", "state_basis": g.basis, "category": cat, "sector": L_sec,
                     "title": a.title, "text": text, "canon": canonical_url(a.url), "domain": a.source_domain,
                     "partners": classify.partners_of(text), "classifier": how, "score": score,
                     "amount": classify.amount_crore(a.title),
                     "matched": "; ".join(f"{k}:{'|'.join(ws)}" for k, ws in v.matched.items())
                                + ("; excerpt:article" if a.extra.get("excerpt_from") == "article" else "")})

    vectors = semantic.embed([m["title"] for m in kept]) if (semantic and kept) else None
    groups = cluster(kept, vectors=vectors, sem_threshold=t.get("dedupe", 0.78)) if kept else []
    events, articles = [], []
    cat_order = L.category_order
    for g in groups:
        members = [kept[i] for i in g]
        members.sort(key=lambda m: (m["date"] or "9999", _tier(m["domain"]), KIND_RANK.get(m["raw"].source_kind, 4)))
        primary = min(members, key=lambda m: (not is_resolved(m["raw"].url), _tier(m["domain"]),
                                               m["date"] or "9999", KIND_RANK.get(m["raw"].source_kind, 4)))
        dated = [m["date"] for m in members if m["date"]]
        first = min(dated) if dated else ""
        # statement_intent only if NO member names a concrete action
        cats = Counter(m["category"] for m in members if m["category"] != "statement_intent") \
            or Counter(m["category"] for m in members)
        top = max(cats.values())
        category = min((c for c in cats if cats[c] == top), key=cat_order.index)
        sectors = Counter(m["sector"] for m in members if m["sector"])
        cities = Counter(m["city"] for m in members if m["city"])
        all_text = " ".join(m["text"] for m in members)
        excerpt = next((m["raw"].excerpt for m in [primary] + members if m["raw"].excerpt), "")
        amount = classify.amount_crore(all_text) if category in ("budget_funding", "partnership", "procurement") else None
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
            "first_reported_date": first,                         # empty when unknown (O4)
            "primary_source_name": primary["raw"].source_name,
            "primary_source_url": primary["raw"].url,
            "url_resolved": "true" if is_resolved(primary["raw"].url) else "false",
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
                "url_resolved": "true" if is_resolved(m["raw"].url) else "false",
                "published_date": m["date"],
                "fetched_via": m["raw"].source_kind,
                "is_primary": "true" if m is primary else "false",
                "state_basis": m["state_basis"],
                "classifier": m["classifier"],
                "relevance_score": m["score"],
                "matched_terms": m["matched"],
            })
    events.sort(key=lambda e: (e["first_reported_date"] or "0000", e["source_count"]), reverse=True)
    articles.sort(key=lambda a: (a["event_id"], a["published_date"]))
    log.info("raw=%d unique=%d kept=%d events=%d rejected=%d classifier=%s", len(raw), len(arts), len(kept),
             len(events), len(rejected), "learned" if learned else "semantic" if semantic else "rules")
    return events, articles, rejected
