"""Score the hand labels: precision overall / per category / per classifier,
plus how many near-miss rejects should have been kept (missed news).

  python scripts/eval_labels.py
"""
import csv
from collections import defaultdict
from pathlib import Path

L = Path(__file__).resolve().parents[1] / "data" / "labels"


def rows(name):
    p = L / name
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("correct") or r.get("should_keep") or "").strip()]


def yes(v):
    return v.strip().lower() in ("y", "yes", "1", "true")


ev = rows("sample_events.csv")
if ev:
    ok = sum(yes(r["correct"]) for r in ev)
    print(f"Precision (kept events): {ok}/{len(ev)} = {ok/len(ev):.0%}")
    for key in ("category", "classifier", "state_code"):
        g = defaultdict(lambda: [0, 0])
        for r in ev:
            g[r[key]][0] += yes(r["correct"]); g[r[key]][1] += 1
        print(f"  by {key}: " + ", ".join(f"{k or '-'} {a}/{b}" for k, (a, b) in sorted(g.items())))
    cat_rows = [r for r in ev if yes(r["correct"]) and r.get("correct_category", "").strip()]
    if cat_rows:
        c = sum(r["correct_category"].strip() == r["category"] for r in cat_rows)
        print(f"Category accuracy (where labelled): {c}/{len(cat_rows)}")
rj = rows("sample_rejected.csv")
if rj:
    miss = [r for r in rj if yes(r["should_keep"])]
    print(f"Near-miss rejects that should have been kept: {len(miss)}/{len(rj)}")
    for r in miss[:10]:
        print(f"  [{r['reason']} {r['relevance_score']}] {r['title'][:90]}")
    print("-> add missed headlines to config/prototypes.json, or lower thresholds.keep")
if not ev and not rj:
    print("No labels yet: run scripts/sample_for_labeling.py and fill the y/n column.")
