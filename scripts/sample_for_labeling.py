"""Draw a random sample for hand-labelling (precision check, review item F2).

  python scripts/sample_for_labeling.py            -> data/labels/sample_events.csv (50 kept events)
                                                    + data/labels/sample_rejected.csv (30 near-miss rejects)
Fill the `correct` column with y / n, then run scripts/eval_labels.py.
"""
import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P, L = ROOT / "data" / "processed", ROOT / "data" / "labels"
L.mkdir(parents=True, exist_ok=True)
random.seed(7)


def read(name):
    with open(P / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


events, articles, rejected = read("events.csv"), read("articles.csv"), read("rejected.csv")
clf = {a["event_id"]: a["classifier"] for a in articles if a["is_primary"] == "true"}
sample = random.sample(events, min(50, len(events)))
with open(L / "sample_events.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["correct", "correct_category", "event_id", "state_code", "category", "classifier", "title", "primary_source_url"])
    for e in sample:
        w.writerow(["", "", e["event_id"], e["state_code"], e["category"], clf.get(e["event_id"], ""), e["title"], e["primary_source_url"]])
# near misses: rejected for relevance, highest semantic score first (recall check)
near = [r for r in rejected if r["reason"] in ("semantic_low", "no_gov_signal", "not_ai")]
near.sort(key=lambda r: float(r["relevance_score"] or -9), reverse=True)
with open(L / "sample_rejected.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["should_keep", "reason", "relevance_score", "state_code", "title", "source_url"])
    for r in near[:30]:
        w.writerow(["", r["reason"], r["relevance_score"], r["state_code"], r["title"], r["source_url"]])
print(f"wrote {L/'sample_events.csv'} ({len(sample)}) and {L/'sample_rejected.csv'} ({min(30, len(near))})")
