"""Train the relevance (and category) classifier from the hand labels.

  python scripts/train_classifier.py                 # logistic regression on MiniLM embeddings (default)
  python scripts/train_classifier.py --method setfit # SetFit fine-tuning (pip install -r requirements-train.txt)

1. Reads data/labels/train_sheet.csv (rows with label 1/0 only).
2. Cross-validates (5-fold for lr, 75/25 holdout for setfit) and reports
   precision / recall / F1, next to the CURRENT pipeline's decisions on the
   same rows (the `suggested` column) as a baseline.
3. Picks the decision threshold that maximises F1 on out-of-fold predictions
   (never below 0.35, to protect precision).
4. Trains on everything and saves models/relevance/ (+ meta.json with the
   metrics). `process` uses it automatically from then on.
Needs >= 30 labelled rows with >= 8 of each class.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHEET = ROOT / "data" / "labels" / "train_sheet.csv"
OUT = ROOT / "models" / "relevance"


def yes(v: str):
    v = (v or "").strip().lower()
    return 1 if v in ("1", "y", "yes", "true") else 0 if v in ("0", "n", "no", "false") else None


def load_rows(path: Path = SHEET):
    with open(path, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if yes(r.get("label")) is not None]
    texts = [f"{r['title']}. {r.get('excerpt', '')}".strip(" .") for r in rows]
    y = [yes(r["label"]) for r in rows]
    return rows, texts, y


def metrics(y, pred):
    tp = sum(1 for a, b in zip(y, pred) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(y, pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y, pred) if a == 1 and b == 0)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "n": len(y)}


def best_threshold(y, prob, floor=0.35):
    best = (0.5, -1.0)
    for t in [x / 100 for x in range(int(floor * 100), 91, 5)]:
        f = metrics(y, [int(p >= t) for p in prob])["f1"]
        if f > best[1]:
            best = (t, f)
    return best[0]


# ---------------- logistic regression on frozen embeddings ----------------
def train_lr(texts, y, embed_fn, folds=5, seed=0):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    X = embed_fn(texts)
    y_arr = np.array(y)
    oof = np.zeros(len(y))
    k = min(folds, int(min(np.bincount(y_arr))))
    for tr, te in StratifiedKFold(n_splits=k, shuffle=True, random_state=seed).split(X, y_arr):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=2.0)
        clf.fit(X[tr], y_arr[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    thr = best_threshold(y, oof)
    final = LogisticRegression(max_iter=2000, class_weight="balanced", C=2.0).fit(X, y_arr)
    return final, oof, thr, f"{k}-fold CV"


# ---------------- SetFit ----------------
def train_setfit(texts, y, model_name, seed=0, epochs=1, iterations=20):
    import numpy as np
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments
    from sklearn.model_selection import train_test_split

    def fit(tx, ty):
        model = SetFitModel.from_pretrained(model_name)
        args = TrainingArguments(batch_size=16, num_epochs=epochs, num_iterations=iterations, seed=seed,
                                 show_progress_bar=False)
        Trainer(model=model, args=args, train_dataset=Dataset.from_dict({"text": tx, "label": ty})).train()
        return model

    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.25, stratify=y, random_state=seed)
    m = fit([texts[i] for i in tr], [y[i] for i in tr])
    p = m.predict_proba([texts[i] for i in te])
    p = (p.numpy() if hasattr(p, "numpy") else np.asarray(p))[:, 1]
    y_te = [y[i] for i in te]
    thr = best_threshold(y_te, p)
    final = fit(texts, y)
    return final, (y_te, p), thr, "25% holdout"


def save_setfit(model, out: Path):
    """Save the fine-tuned body and the head separately. (SetFitModel.save_pretrained /
    from_pretrained round-trips break with recent huggingface_hub versions.)"""
    import joblib
    model.model_body.save(str(out / "setfit_body"))
    joblib.dump(model.model_head, out / "head.joblib")


def train_category(rows, texts, y, embed_fn, min_per_class=4):
    """Multi-class head for positives: user category, else suggested_category."""
    from collections import Counter
    from sklearn.linear_model import LogisticRegression
    pos = [(t, (r.get("category") or r.get("suggested_category") or "").strip())
           for r, t, lab in zip(rows, texts, y) if lab == 1]
    pos = [(t, c) for t, c in pos if c]
    counts = Counter(c for _, c in pos)
    keep = {c for c, n in counts.items() if n >= min_per_class}
    pos = [(t, c) for t, c in pos if c in keep]
    if len(keep) < 2:
        return None, dict(counts)
    X = embed_fn([t for t, _ in pos])
    clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(X, [c for _, c in pos])
    return clf, dict(counts)


def main(argv=None, embed_fn=None, sheet: Path = SHEET, out: Path = OUT):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--method", choices=["lr", "setfit"], default="lr")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--iterations", type=int, default=20)
    a = ap.parse_args(argv)

    rows, texts, y = load_rows(sheet)
    npos, nneg = sum(y), len(y) - sum(y)
    print(f"labelled rows: {len(y)} ({npos} relevant, {nneg} not)")
    if len(y) < 30 or min(npos, nneg) < 8:
        sys.exit("need >= 30 labelled rows with >= 8 of each class - label more in data/labels/train_sheet.csv")

    base = [int(str(r.get("suggested", "")).strip() == "1") for r in rows]
    baseline = metrics(y, base)
    print(f"current pipeline on these rows : {baseline}")

    if embed_fn is None:
        from pipeline.semantic import Semantic
        embed_fn = Semantic().embed
    import joblib
    out.mkdir(parents=True, exist_ok=True)
    if a.method == "lr":
        model, oof, thr, how = train_lr(texts, y, embed_fn)
        cv = metrics(y, [int(p >= thr) for p in oof])
        joblib.dump(model, out / "head.joblib")
    else:
        model_name = json.loads((ROOT / "config" / "prototypes.json").read_text())["model"]
        model, (y_te, p), thr, how = train_setfit(texts, y, model_name, epochs=a.epochs, iterations=a.iterations)
        cv = metrics(y_te, [int(v >= thr) for v in p])
        save_setfit(model, out)
    print(f"trained model ({how}, threshold {thr}): {cv}")

    cat_clf, cat_counts = train_category(rows, texts, y, embed_fn)
    if cat_clf is not None:
        joblib.dump(cat_clf, out / "category.joblib")
    elif (out / "category.joblib").exists():
        (out / "category.joblib").unlink()
    meta = {"method": a.method, "threshold": thr, "cv": cv, "cv_scheme": how, "baseline_current_pipeline": baseline,
            "labelled": len(y), "positives": npos, "category_counts": cat_counts,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"saved {out}  ->  re-run: python -m pipeline.run process")
    return meta


if __name__ == "__main__":
    main()
