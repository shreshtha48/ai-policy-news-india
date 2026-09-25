"""CLI.

  python -m pipeline.run fetch   [--states IN-KA,IN-TG] [--sources google_news,gdelt,gnews,outlets]
  python -m pipeline.run process [--raw path.jsonl ...]
  python -m pipeline.run all     (fetch then process)

fetch   appends raw results to data/raw/<today>/<source>.jsonl (never overwrites,
        so feeds that only show the latest items accumulate history over runs).
process reads every raw file (or just --raw files) and rewrites data/processed/.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import build, export
from .models import RawArticle
from .sources import gdelt, gnews, google_news, outlets

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
CFG = ROOT / "config"
ALL_SOURCES = ["google_news", "gdelt", "gnews", "outlets"]
log = logging.getLogger("pipeline")


def _load_json(name):
    return json.loads((CFG / name).read_text(encoding="utf-8"))


def _append(source: str, arts: list[RawArticle]):
    day = datetime.now(timezone.utc).date().isoformat()
    p = RAW / day / f"{source}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for a in arts:
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
    log.info("saved %d -> %s", len(arts), p.relative_to(ROOT))


def load_raw(paths: list[Path] | None = None) -> list[RawArticle]:
    files = paths or sorted(RAW.rglob("*.jsonl"))
    out = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            out += [RawArticle.from_dict(json.loads(line)) for line in f if line.strip()]
    return out


def fetch(states: list[str], sources: list[str]):
    st, src = _load_json("states.json")["states"], _load_json("sources.json")
    known = {a.url for a in load_raw()}
    for code in states:
        name, metros = st[code]["name"], list(st[code].get("metros", {}))
        if "google_news" in sources:
            _append("google_news", google_news.fetch(code, name, metros, src["google_news"]))
        if "gdelt" in sources:
            _append("gdelt", gdelt.fetch(code, name, src["gdelt"]))
        if "gnews" in sources:
            _append("gnews", gnews.fetch(code, name, src["gnews"]))
        if "outlets" in sources:
            _append("outlets", outlets.fetch(code, src["outlets"].get(code, []), known))


def process(raw_paths: list[Path] | None = None):
    raw = load_raw(raw_paths)
    if not raw:
        log.error("no raw data found - run `fetch` first (or pass --raw)"); return
    events, articles, rejected = build.build(raw)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_records": len(raw),
        "raw_by_source": dict(Counter(a.source_kind for a in raw)),
        "events": len(events), "articles_kept": len(articles), "rejected": len(rejected),
        "events_by_state": dict(Counter(e["state_code"] for e in events)),
        "events_by_category": dict(Counter(e["category"] for e in events)),
        "rejected_by_reason": dict(Counter(r["reason"] for r in rejected)),
        "events_date_unknown": sum(e["date_precision"] == "unknown" for e in events),
    }
    export.export(OUT, events, articles, rejected, ROOT / "data" / "reference", summary)
    log.info("wrote %s", OUT.relative_to(ROOT))
    print(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "process", "all"])
    ap.add_argument("--states", default="IN-TN,IN-KA,IN-TG,IN-DL,IN-GJ,IN-MH")
    ap.add_argument("--sources", default=",".join(ALL_SOURCES))
    ap.add_argument("--raw", nargs="*", type=Path, help="process only these raw .jsonl files")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd in ("fetch", "all"):
        fetch(a.states.split(","), a.sources.split(","))
    if a.cmd in ("process", "all"):
        process(a.raw)


if __name__ == "__main__":
    main()
