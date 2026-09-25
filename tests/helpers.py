import re

import numpy as np


class FakeEncoder:
    """Deterministic bag-of-words 'embedding' so model paths are testable
    offline (real runs use sentence-transformers)."""
    VOCAB = ["state", "government", "govt", "minister", "cm", "mou", "pact", "signs", "tender", "bids",
             "budget", "crore", "policy", "mission", "task", "force", "deploy", "deploys", "cameras", "police",
             "guidelines", "deepfake", "smartphone", "stocks", "startup", "funding", "film", "ai", "artificial",
             "intelligence", "praises", "hub", "flyover", "bus", "telangana", "karnataka", "schools", "holidays",
             "cricket", "match", "shares", "tool"]

    def __call__(self, texts):
        out = []
        for t in texts:
            w = re.findall(r"[a-z]+", t.lower())
            v = np.array([w.count(x) for x in self.VOCAB], dtype="float32") + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.array(out)
