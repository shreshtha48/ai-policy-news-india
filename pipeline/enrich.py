"""Read the article for near-misses (review step 2).

Headlines often lack context ("Telangana Police deploys C-SIGHT for CSEAM
investigations" never says AI). Instead of loosening the keyword lists, we
read the first paragraphs of articles that were REJECTED but look close
(classify.near_miss: state named + a concrete action when the AI word is
missing, or an AI word when the government signal is missing), and let
`process` judge them again with that lead text as their excerpt.

  python -m pipeline.run enrich [--max 60] [--dry-run]

* Google News links are decoded first (googlenewsdecoder; shared cache with
  `resolve`), then the page is downloaded and the main text extracted with
  trafilatura (fallback: <p> tags). Only the first ~1,200 characters are
  kept, and only locally in data/cache/bodies.json - used for classification,
  never republished.
* Capped per run; failures are cached too so they aren't retried every day.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import http
from .classify import near_miss

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
BODIES = ROOT / "data" / "cache" / "bodies.json"
GURLS = ROOT / "data" / "cache" / "google_urls.json"
LEAD_CHARS = 1200
RETRY_FAILED_AFTER_DAYS = 7


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(p: Path, d: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def extract_lead(html: str, url: str = "") -> str:
    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(html, url=url or None, favor_precision=True, include_comments=False,
                                   include_tables=False) or ""
    except ImportError:
        pass
    if not text:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer", "aside"]):
            t.decompose()
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = "\n".join(p for p in paras if len(p) > 60)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:LEAD_CHARS]


def decode_google(url: str, cache: dict) -> str | None:
    if "news.google.com" not in url:
        return url
    if url in cache:
        return cache[url]
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        log.warning("pip install googlenewsdecoder to read Google News articles")
        return None
    try:
        res = gnewsdecoder(url, interval=1)
        if res.get("status") and res.get("decoded_url"):
            cache[url] = res["decoded_url"]
            return cache[url]
    except Exception as e:
        log.debug("decode failed %s: %s", url, e)
    return None


def candidates(rejected: list[dict]) -> list[dict]:
    """Rejected rows worth reading: relevance rejections whose headline is a near-miss."""
    rel = {"not_ai", "no_gov_signal", "semantic_low", "learned_low"}
    return [r for r in rejected if r["reason"] in rel and near_miss(r["title"], r["reason"])]


def enrich(rejected: list[dict], max_n: int = 60, dry_run: bool = False) -> int:
    bodies, gurls = _load(BODIES), _load(GURLS)
    today = datetime.now(timezone.utc).date()

    def stale_failure(entry) -> bool:
        if entry.get("ok"):
            return False
        d = datetime.fromisoformat(entry.get("fetched", "2000-01-01")).date()
        return (today - d).days >= RETRY_FAILED_AFTER_DAYS

    todo = [r for r in candidates(rejected)
            if r["source_url"] not in bodies or stale_failure(bodies[r["source_url"]])][:max_n]
    log.info("near-miss articles to read: %d (cap %d)", len(todo), max_n)
    if dry_run:
        for r in todo[:15]:
            print(f"  would read: {r['title'][:100]}")
        return len(todo)
    ok = 0
    for i, r in enumerate(todo, 1):
        url = r["source_url"]
        entry = {"fetched": today.isoformat(), "ok": False, "title": r["title"]}
        real = decode_google(url, gurls)
        if real:
            try:
                resp = http.get(real, min_interval=2.0)
                if resp.ok and "html" in resp.headers.get("content-type", "html"):
                    lead = extract_lead(resp.text, real)
                    if len(lead) > 150:
                        entry.update(ok=True, final_url=real, lead=lead); ok += 1
            except Exception as e:
                log.debug("read failed %s: %s", real, e)
        bodies[url] = entry
        if i % 10 == 0:
            _save(BODIES, bodies); _save(GURLS, gurls)
    _save(BODIES, bodies); _save(GURLS, gurls)
    log.info("read %d/%d near-miss articles", ok, len(todo))
    return ok


def body_leads() -> dict[str, str]:
    """{article url: lead text} for successfully read articles."""
    return {u: e["lead"] for u, e in _load(BODIES).items() if e.get("ok") and e.get("lead")}
