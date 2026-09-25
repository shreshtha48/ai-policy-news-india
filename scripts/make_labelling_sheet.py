"""Build / extend the hand-labelling sheet for the trained classifier.

  python scripts/make_labelling_sheet.py [--n 200]

Writes data/labels/train_sheet.csv with a stratified sample of what the
pipeline currently KEEPS and REJECTS (plus every near-miss), so the model
learns the hard cases. Open it in Excel and fill:
  label     1 = state-government AI policy activity (our definition, README), 0 = not
  category  (optional, for label=1) one of the 8 category ids - leave empty to accept `suggested_category`
Rows you already labelled are never overwritten; re-running only ADDS new rows.
The `suggested` columns show the current pipeline decision - check, don't copy.
"""
import argparse
import csv
import hashlib
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.build import build, dedupe_articles  # noqa: E402
from pipeline.classify import near_miss  # noqa: E402
from pipeline.run import load_raw  # noqa: E402

SHEET = ROOT / "data" / "labels" / "train_sheet.csv"
COLS = ["label", "category", "suggested", "suggested_category", "reason", "title", "excerpt", "source", "url", "text_id"]


def tid(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="target number of NEW rows")
    ap.add_argument("--seed", type=int, default=13)
    a = ap.parse_args()
    random.seed(a.seed)

    raw = load_raw()
    if not raw:
        sys.exit("no raw data - run the pipeline fetch first")
    events, articles, rejected = build(raw)
    excerpt = {x.title: x.excerpt for x in dedupe_articles(load_raw())}
    cat_of_event = {e["event_id"]: e["category"] for e in events}

    kept = [{"suggested": 1, "suggested_category": cat_of_event.get(r["event_id"], ""), "reason": r["classifier"],
             "title": r["title"], "source": r["source_name"], "url": r["source_url"]} for r in articles]
    rel = {"not_ai", "no_gov_signal", "semantic_low", "learned_low", "no_state"}
    rej = [{"suggested": 0, "suggested_category": "", "reason": r["reason"], "title": r["title"],
            "source": r["source_name"], "url": r["source_url"]} for r in rejected if r["reason"] in rel]

    existing, seen = [], set()
    if SHEET.exists():
        with open(SHEET, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
        seen = {r["text_id"] for r in existing}

    def fresh(rows):
        out, ids = [], set()
        for r in rows:
            i = tid(r["title"])
            if i not in seen and i not in ids:
                ids.add(i); out.append({**r, "text_id": i})
        return out

    kept, rej = fresh(kept), fresh(rej)
    near = [r for r in rej if near_miss(r["title"], r["reason"])]
    other_rej = [r for r in rej if r not in near]
    half = a.n // 2
    pick = random.sample(kept, min(half, len(kept)))
    pick += near[: a.n // 4]
    pick += random.sample(other_rej, min(a.n - len(pick), len(other_rej)))
    random.shuffle(pick)
    for r in pick:
        r.update(label="", category="", excerpt=(excerpt.get(r["title"], "") or "")[:300])

    SHEET.parent.mkdir(parents=True, exist_ok=True)
    with open(SHEET, "w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(existing + pick)
    labelled = sum(1 for r in existing if r.get("label", "").strip())
    print(f"{SHEET}: {len(existing) + len(pick)} rows ({labelled} already labelled, {len(pick)} new)")
    print("Fill `label` with 1/0 (and optionally `category`), then: python scripts/train_classifier.py")


if __name__ == "__main__":
    main()
