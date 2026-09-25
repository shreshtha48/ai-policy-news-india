"""Best-effort decoding of Google News redirect links (S3 step 2).

Current Google News links (news.google.com/rss/articles/CBMi...) don't
redirect over plain HTTP; decoding needs an extra request to Google. We use
the optional `googlenewsdecoder` package, capped per run, only for events'
primary articles that still have no real URL (most get one for free from
API/feed copies during dedupe). Results are cached in
data/cache/google_urls.json and applied on the next `process`.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "google_urls.json"


def resolve(max_urls: int = 50, interval: float = 2.0, dry_run: bool = False) -> int:
    ev = ROOT / "data" / "processed" / "events.csv"
    if not ev.exists():
        log.error("run `process` first"); return 0
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    with open(ev, encoding="utf-8") as f:
        todo = [r["primary_source_url"] for r in csv.DictReader(f)
                if "news.google.com" in r["primary_source_url"] and r["primary_source_url"] not in cache]
    todo = todo[:max_urls]
    log.info("google links to decode: %d (cap %d)", len(todo), max_urls)
    if dry_run or not todo:
        return len(todo)
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        log.warning("pip install googlenewsdecoder to decode Google News links; skipping")
        return 0
    ok = 0
    for u in todo:
        try:
            res = gnewsdecoder(u, interval=interval)
            if res.get("status") and res.get("decoded_url"):
                cache[u] = res["decoded_url"]; ok += 1
            else:
                log.debug("decode failed %s: %s", u, res.get("message"))
        except Exception as e:
            log.warning("decode error %s: %s", u, e)
            time.sleep(interval)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    log.info("decoded %d/%d", ok, len(todo))
    return ok
