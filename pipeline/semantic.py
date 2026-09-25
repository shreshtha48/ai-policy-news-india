"""Semantic (embedding) relevance + category classifier and dedupe helper.

Why: keyword rules miss paraphrases ("state strikes deal with Google") and
context. A small sentence-embedding model places each headline (+ snippet)
near the prototype headlines in config/prototypes.json; the nearest
positives give relevance + category, the nearest negatives (corporate AI
news, markets, gadgets, non-AI govt news) pull it down.

Optional: needs `pip install sentence-transformers` (downloads a ~90 MB model
once). Without it the pipeline falls back to keyword rules and says so in
run_summary.json. Embeddings are cached in data/cache/ so re-runs are fast.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "prototypes.json"
CACHE = ROOT / "data" / "cache"


@dataclass
class SemScore:
    pos: float          # mean cosine of the 3 nearest positive prototypes
    neg: float          # mean cosine of the 3 nearest negative prototypes
    category: str       # category of the best-matching positive group
    nearest: str        # the closest prototype (for audit)

    @property
    def margin(self) -> float:
        return self.pos - self.neg


class Semantic:
    def __init__(self, encoder: Callable[[list[str]], "np.ndarray"] | None = None, cfg_path: Path = CFG):
        import numpy as np
        self.np = np
        self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.t = self.cfg["thresholds"]
        self.model_name = self.cfg["model"]
        self._encoder = encoder
        self._cache: dict[str, list[float]] = {}
        self._cache_path = CACHE / f"emb_{hashlib.sha1(self.model_name.encode()).hexdigest()[:8]}.pkl"
        if encoder is None and self._cache_path.exists():
            try:
                self._cache = pickle.loads(self._cache_path.read_bytes())
            except Exception:
                self._cache = {}
        self.pos_texts, self.pos_cats = [], []
        for cat, exs in self.cfg["positive"].items():
            for e in exs:
                self.pos_texts.append(e); self.pos_cats.append(cat)
        self.neg_texts = list(self.cfg["negative"])
        self.P = self.embed(self.pos_texts)
        self.N = self.embed(self.neg_texts)

    # -- encoding -------------------------------------------------------
    def _encode(self, texts: list[str]):
        if self._encoder is not None:
            return self._encoder(texts)
        from sentence_transformers import SentenceTransformer
        if not hasattr(self, "_model"):
            log.info("loading embedding model %s (first run downloads it)", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model.encode(texts, batch_size=64, show_progress_bar=len(texts) > 200,
                                  normalize_embeddings=True)

    def embed(self, texts: Sequence[str]):
        np = self.np
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in self._cache]
        if missing:
            vecs = self._encode([t for _, t in missing])
            for (k, _), v in zip(missing, vecs):
                self._cache[k] = [float(x) for x in v]
            if self._encoder is None:
                CACHE.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_bytes(pickle.dumps(self._cache))
        M = np.array([self._cache[k] for k in keys], dtype="float32") if keys else np.zeros((0, 1), "float32")
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return M / norms

    # -- scoring --------------------------------------------------------
    def score(self, texts: Sequence[str]) -> list[SemScore]:
        np = self.np
        if not texts:
            return []
        X = self.embed(texts)
        SP, SN = X @ self.P.T, X @ self.N.T
        out = []
        for i in range(len(texts)):
            sp, sn = SP[i], SN[i]
            top = np.argsort(-sp)[:3]
            # category = group with the highest mean of its 2 best prototypes
            best_cat, best = "", -1.0
            for cat in dict.fromkeys(self.pos_cats):
                idx = [j for j, c in enumerate(self.pos_cats) if c == cat]
                v = float(np.mean(np.sort(sp[idx])[-2:]))
                if v > best:
                    best_cat, best = cat, v
            out.append(SemScore(pos=float(np.mean(sp[top])), neg=float(np.mean(np.sort(sn)[-3:])),
                                category=best_cat, nearest=self.pos_texts[int(top[0])]))
        return out


@lru_cache(maxsize=1)
def get_semantic() -> Semantic | None:
    """The shared classifier, or None if sentence-transformers isn't installed."""
    try:
        import numpy  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        log.warning("sentence-transformers not installed: using keyword rules only "
                    "(pip install sentence-transformers for the semantic classifier)")
        return None
    try:
        return Semantic()
    except Exception as e:                      # e.g. model download blocked
        log.warning("semantic classifier unavailable (%s): using keyword rules only", e)
        return None
