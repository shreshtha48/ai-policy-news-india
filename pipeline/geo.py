"""State / city normalisation.

Every spelling of a state or metro is mapped to ONE ISO 3166-2 code
(config/states.json). Resolution works on free text (headline + excerpt), so
"UP", "Uttar Pradesh" and "Uttar-Pradesh" can never become three states.

Rules (see README "How states are assigned"):
  * Strong alias hit (state name, CM, state body, metro)  -> that state.
  * Bare "Delhi"/"New Delhi" is weak: it is usually a dateline or the Union
    government. It only counts as IN-DL when there is no Union-govt signal.
  * Union-govt signals with no state hit                  -> IN-CENTRAL.
  * Several states hit -> the one mentioned most; the caller's `hint`
    (feed section / query state) breaks ties, then the earliest mention.
  * No state in the text -> the hint, but ONLY for state-specific outlet
    feeds (The Hindu Telangana section). Search-query hints are never used
    as a fallback (a "Delhi" query returns Union-govt stories).
  * Only non-focus states hit (e.g. Noida -> UP)           -> that code, and
    the pipeline drops it as out of scope.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "states.json"

# Phrases that contain a signal word but mean something else.
_MASK = [
    r"centre of excellence", r"centres of excellence", r"centre for", r"data centres?",
    r"tech centre", r"innovation centre", r"call centres?", r"command centre", r"ai centres?",
    r"centre stage", r"skill(ing)? centres?", r"research centres?", r"state of the art",
]
_DATELINE = re.compile(r"^\s*(new delhi|delhi|mumbai|chennai|bengaluru|hyderabad)\s*[,:\-–]\s*", re.I)


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[\-_/]", " ", text)       # Uttar-Pradesh -> Uttar Pradesh
    return re.sub(r"\s+", " ", text).strip()


def _pattern(alias: str) -> re.Pattern:
    a = _norm(alias)
    body = r"\s+".join(re.escape(p) for p in a.split(" "))
    # Short all-caps acronyms (MCD, BMC, KITS) are case-sensitive: "bmc" in a
    # URL slug or "Kits" as a word should not count.
    flags = 0 if (a.isupper() and len(a) <= 5) else re.I
    return re.compile(rf"(?<![\w]){body}(?![\w])", flags)


@dataclass
class GeoResult:
    state_code: str | None      # IN-XX, IN-CENTRAL, or None
    city: str | None            # metro name only
    basis: str                  # how it was decided (kept for audit)
    in_focus: bool


class Geo:
    def __init__(self, path: Path = CONFIG):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        self.names = {c: s["name"] for c, s in cfg["states"].items()}
        self.names[cfg["central"]["code"]] = cfg["central"]["name"]
        self.central_code = cfg["central"]["code"]
        self.short_codes = cfg["short_codes"]
        self.strong: list[tuple[re.Pattern, str, str | None]] = []   # (pattern, code, metro)
        self.weak_delhi = [_pattern("New Delhi"), _pattern("Delhi")]
        for code, s in cfg["states"].items():
            for a in [s["name"], *s["aliases"], *s.get("cities", [])]:
                self.strong.append((_pattern(a), code, None))
            for metro, aliases in s.get("metros", {}).items():
                if code == "IN-DL":
                    continue            # handled as weak signal
                for a in [metro, *aliases]:
                    self.strong.append((_pattern(a), code, metro))
        self.other: list[tuple[re.Pattern, str]] = [
            (_pattern(a), code)
            for code, aliases in cfg["not_focus_but_known"].items() if not code.startswith("_")
            for a in aliases
        ]
        self.central = [_pattern(a) for a in cfg["central"]["signals"]]
        self.focus = set(cfg["states"])

    # -- public -----------------------------------------------------------
    def code_for(self, value: str) -> str | None:
        """Normalise a single state label ('UP', 'Uttar-Pradesh', 'IN-KA')."""
        if not value:
            return None
        v = value.strip()
        if v.upper() in self.names:
            return v.upper()
        if v.upper() in self.short_codes:
            return self.short_codes[v.upper()]
        r = self.resolve(v)
        return r.state_code

    def resolve(self, text: str, hint: str | None = None, hint_is_fallback: bool = False) -> GeoResult:
        """`hint` = the state of the query/feed that found the article.
        It always breaks ties between states named in the text. It is used as a
        FALLBACK (no state in the text) only when `hint_is_fallback` is set,
        i.e. for a state-specific outlet feed - never for search queries, where
        e.g. a "Delhi" query returns Union-govt stories that are not Delhi's."""
        text = _norm(text or "")
        masked = text
        for m in _MASK:
            masked = re.sub(m, " ", masked, flags=re.I)
        body = _DATELINE.sub("", masked)

        hits: dict[str, list[int]] = {}
        metro_for: dict[str, str] = {}
        for pat, code, metro in self.strong:
            for m in pat.finditer(body):
                hits.setdefault(code, []).append(m.start())
                if metro and code not in metro_for:
                    metro_for[code] = metro

        central = any(p.search(body) for p in self.central)
        delhi_weak = [m.start() for p in self.weak_delhi for m in p.finditer(body)]
        if delhi_weak and "IN-DL" not in hits and not central:
            hits["IN-DL"] = delhi_weak
            metro_for["IN-DL"] = "Delhi"
        if "IN-DL" in hits and "IN-DL" not in metro_for and delhi_weak:
            metro_for["IN-DL"] = "Delhi"

        if hits:
            if len(hits) == 1:
                code, basis = next(iter(hits)), "text"
            else:
                ranked = sorted(hits, key=lambda c: (-len(hits[c]), min(hits[c])))
                top = [c for c in ranked if len(hits[c]) == len(hits[ranked[0]])]
                code = hint if hint in top else ranked[0]
                basis = "text_multi_state"
            return GeoResult(code, metro_for.get(code), basis, True)

        others = {code for pat, code in self.other if pat.search(body)}
        if others:
            return GeoResult(sorted(others)[0], None, "text_non_focus", False)
        if central:
            return GeoResult(self.central_code, None, "central_signal", True)
        if hint and hint_is_fallback:
            return GeoResult(hint, None, "source_hint", hint in self.focus or hint == self.central_code)
        return GeoResult(None, None, "none", False)


@lru_cache(maxsize=1)
def get_geo() -> Geo:
    return Geo()
