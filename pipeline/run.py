"""CLI.

  python -m pipeline.run fetch   [--states IN-KA,IN-TG] [--sources ...] [--dry-run]
  python -m pipeline.run process [--raw path.jsonl ...] [--rules-only]
  python -m pipeline.run resolve [--max 50] [--dry-run]
  python -m pipeline.run enrich  [--max 60] [--dry-run]   (read near-miss articles)
  python -m pipeline.run all     [--dry-run]   (fetch -> process -> resolve -> enrich -> process)

Sources: google_news, gdelt, gnews, newsapi, newsdata, outlets.

fetch plans every request first, skips what the ledger says was already done
(closed-month Google slices forever, everything else per day), enforces daily
budgets for the keyed APIs, and appends results to
data/raw/<today>/<source>.jsonl. --dry-run prints the plan and calls nothing.
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
from .plan import Ledger, triage
from .sources import gdelt, google_news, keyed, outlets

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
CFG = ROOT / "config"
ALL_SOURCES = ["google_news", "gdelt", "gnews", "newsapi", "newsdata", "outlets"]
FOCUS = "IN-TN,IN-KA,IN-TG,IN-DL,IN-GJ,IN-MH"
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


def load_raw(paths: list[Path] | None = None) -> list[RawArticle]:
    files = paths or sorted(RAW.rglob("*.jsonl"))
    out, bad = [], 0
    for p in files:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(RawArticle.from_dict(json.loads(line)))
                except json.JSONDecodeError:      # half-written line while a fetch is still running
                    bad += 1
    if bad:
        log.warning("skipped %d incomplete raw lines (a fetch may still be running)", bad)
    return out


def plan_calls(states: list[str], sources: list[str]):
    st, src = _load_json("states.json")["states"], _load_json("sources.json")
    since = src["since"]
    known = {a.url for a in load_raw()} if "outlets" in sources else set()
    calls = []
    for code in states:
        name, metros = st[code]["name"], list(st[code].get("metros", {}))
        if "google_news" in sources:
            calls += google_news.plan(code, name, metros, src["google_news"], since)
        if "gdelt" in sources:
            calls += gdelt.plan(code, name, src["gdelt"], since)
        if "gnews" in sources:
            calls += keyed.plan_gnews(code, name, src["gnews"], since)
        if "newsapi" in sources:
            calls += keyed.plan_newsapi(code, name, src["newsapi"], since)
        if "newsdata" in sources:
            calls += keyed.plan_newsdata(code, name, src["newsdata"], since)
        if "outlets" in sources:
            calls += outlets.plan(code, src["outlets"].get(code, []), since, known)
    budgets = {k: src[k]["daily_budget"] for k in ("gnews", "newsapi", "newsdata")}
    return calls, budgets


def fetch(states: list[str], sources: list[str], dry_run: bool = False):
    calls, budgets = plan_calls(states, sources)
    ledger = Ledger(RAW / "_ledger.json")
    to_run, skipped = triage(calls, ledger, budgets)

    table = Counter((c.api, "RUN") for c in to_run)
    for c, why in skipped:
        table[(c.api, why)] += 1
    print(f"\n{'API':<12} {'status':<34} calls")
    for (api, status), n in sorted(table.items()):
        print(f"{api:<12} {status:<34} {n}")
    keyed_runs = Counter(c.api for c in to_run if c.keyed)
    for api, n in sorted(keyed_runs.items()):
        print(f"  -> {api}: {n} quota calls now, {ledger.used_today(api)} already today, budget {budgets[api]}/day")
    if dry_run:
        print("\n--dry-run: first planned call per API:")
        seen = set()
        for c in to_run:
            if c.api not in seen:
                seen.add(c.api); print(f"  {c.api:<12} {c.key[:150]}")
        mins = sum(2.2 if c.api == "google_news" else 7 if c.api == "gdelt" else 3 for c in to_run) / 60
        print(f"\nestimated time ~{mins:.0f} min. Nothing was called.")
        return

    for i, c in enumerate(to_run, 1):
        try:
            arts = c.run()
            _append(c.api, arts)
            ledger.record(c, len(arts))
            log.info("[%d/%d] %s %s -> %d", i, len(to_run), c.api, c.state, len(arts))
        except Exception as e:                     # never kill the run; not recorded -> retried next time
            log.warning("[%d/%d] %s %s FAILED: %s", i, len(to_run), c.api, c.state, e)


def process(raw_paths: list[Path] | None = None, rules_only: bool = False):
    raw = load_raw(raw_paths)
    if not raw:
        log.error("no raw data found - run `fetch` first (or pass --raw)"); return
    events, articles, rejected = build.build(raw, semantic=None if rules_only else "auto")
    classifier = Counter(a["classifier"] for a in articles)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": build.SINCE,
        "classifier": "rules" if (rules_only or set(classifier) <= {"rules"}) else "rules+semantic",
        "raw_records": len(raw),
        "raw_by_source": dict(Counter(a.source_kind for a in raw)),
        "events": len(events), "articles_kept": len(articles), "rejected": len(rejected),
        "events_by_state": dict(Counter(e["state_code"] for e in events)),
        "events_by_category": dict(Counter(e["category"] for e in events)),
        "articles_by_classifier": dict(classifier),
        "rejected_by_reason": dict(Counter(r["reason"] for r in rejected)),
        "events_date_unknown": sum(e["date_precision"] == "unknown" for e in events),
        "events_url_unresolved": sum(e["url_resolved"] == "false" for e in events),
    }
    export.export(OUT, events, articles, rejected, ROOT / "data" / "reference", summary)
    print(json.dumps(summary, indent=2))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts" / "sync_dashboard_data.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        log.info(mod.sync(quiet=True))
    except Exception as e:
        log.warning("dashboard sync skipped: %s", e)


def load_dotenv(path: Path = ROOT / ".env"):
    """KEY=VALUE lines from .env (git-ignored) -> environment, without overriding real env vars."""
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "process", "resolve", "enrich", "all"])
    ap.add_argument("--states", default=FOCUS)
    ap.add_argument("--sources", default=",".join(ALL_SOURCES))
    ap.add_argument("--raw", nargs="*", type=Path, help="process only these raw .jsonl files")
    ap.add_argument("--dry-run", action="store_true", help="plan only: print calls, make none")
    ap.add_argument("--rules-only", action="store_true", help="skip the semantic classifier")
    ap.add_argument("--max", type=int, default=None, help="resolve (default 50) / enrich (default 60): cap per run")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    states, sources = a.states.split(","), a.sources.split(",")
    if a.cmd == "fetch":
        fetch(states, sources, a.dry_run)
    elif a.cmd == "process":
        process(a.raw, a.rules_only)
    elif a.cmd == "resolve":
        from .resolve import resolve
        resolve(a.max or 50, dry_run=a.dry_run)
    elif a.cmd == "enrich":
        run_enrich(a.max or 60, a.dry_run, a.rules_only)
    elif a.cmd == "all":
        fetch(states, sources, a.dry_run)
        if a.dry_run:
            return
        process(None, a.rules_only)
        from .resolve import resolve
        changed = resolve(a.max or 50)
        changed += run_enrich(a.max or 60, False, a.rules_only, reprocess=False)
        if changed:
            process(None, a.rules_only)


def run_enrich(max_n: int, dry_run: bool, rules_only: bool, reprocess: bool = True) -> int:
    """Read near-miss articles, then re-judge them."""
    import csv
    from .enrich import enrich
    rej_path = OUT / "rejected.csv"
    if not rej_path.exists():
        log.error("run `process` first"); return 0
    with open(rej_path, encoding="utf-8") as f:
        rejected = list(csv.DictReader(f))
    n = enrich(rejected, max_n, dry_run)
    if n and reprocess and not dry_run:
        process(None, rules_only)
    return n


if __name__ == "__main__":
    main()
