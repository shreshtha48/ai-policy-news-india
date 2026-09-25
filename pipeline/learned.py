"""Classifier trained on OUR hand labels (review step 3).

Trained by scripts/train_classifier.py from data/labels/train_sheet.csv:
  * lr     (default): logistic regression on frozen all-MiniLM-L6-v2
             embeddings. Tiny (a few KB, committed to git) and deterministic.
  * setfit (optional): SetFit fine-tunes the MiniLM body itself with
             contrastive pairs - usually more accurate with few labels, but
             the saved body is ~90 MB (models/relevance/setfit_body/, kept out
             of git; the scheduled GitHub Action can't use it - use lr there).
models/relevance/meta.json records the method, the decision threshold chosen
by cross-validation, and the CV precision/recall reported in the README.
When no trained model exists the pipeline falls back to prototypes + rules.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "relevance"


class Learned:
    def __init__(self, model_dir: Path = MODEL_DIR, semantic=None, embed_fn=None):
        self.dir = model_dir
        self.meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))
        self.threshold = float(self.meta.get("threshold", 0.5))
        self.kind = self.meta["method"]
        self._embed = embed_fn or (semantic.embed if semantic else None)
        self.category_head = None
        if self.kind == "lr":
            import joblib
            self.head = joblib.load(model_dir / "head.joblib")
            if self._embed is None:
                raise RuntimeError("lr model needs the embedding model (sentence-transformers)")
        elif self.kind == "setfit":                 # fine-tuned body + sklearn head (see train_classifier.save_setfit)
            import joblib
            from sentence_transformers import SentenceTransformer
            self.body = SentenceTransformer(str(model_dir / "setfit_body"))
            self.head = joblib.load(model_dir / "head.joblib")
        else:
            raise ValueError(f"unknown method {self.kind}")
        if (model_dir / "category.joblib").exists() and self._embed is not None:
            import joblib
            self.category_head = joblib.load(model_dir / "category.joblib")

    def proba(self, texts: list[str]):
        import numpy as np
        if not texts:
            return np.zeros(0)
        if self.kind == "lr":
            return self.head.predict_proba(self._embed(texts))[:, 1]
        return self.head.predict_proba(self.body.encode(texts, show_progress_bar=False))[:, 1]

    def category(self, texts: list[str]) -> list[str]:
        if self.category_head is None or not texts:
            return [""] * len(texts)
        return list(self.category_head.predict(self._embed(texts)))


@lru_cache(maxsize=1)
def get_learned(semantic=None) -> Learned | None:
    if not (MODEL_DIR / "meta.json").exists():
        return None
    try:
        m = Learned(semantic=semantic)
        log.info("using trained %s classifier (threshold %.2f, CV precision %s, recall %s)", m.kind, m.threshold,
                 m.meta.get("cv", {}).get("precision"), m.meta.get("cv", {}).get("recall"))
        return m
    except Exception as e:
        log.warning("trained classifier unavailable (%s): falling back to prototypes/rules", e)
        return None
