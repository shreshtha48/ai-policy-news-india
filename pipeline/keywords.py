"""Case-insensitive, typo-tolerant keyword matching (config/keywords.json).

How a keyword matches:
  1. Text and keyword go through the same `normalise()`: lowercase,
     'A.I.' -> 'ai', 'M.o.U.' -> 'mou', hyphen/slash -> space,
     centre/center, programme/program and -ise/-ize unified.
     So "AI", "ai", "A.I.", "Ai-powered" and "AI powered" are one thing.
  2. Phrases match as consecutive words ("task force", "memorandum of understanding").
  3. `word*` matches as a prefix ("allocat*" -> allocation, allocated).
  4. Words with 6+ letters also match a misspelling (same first letter):
       - 6-8 letters: one missing, extra or swapped letter
         ("minster", "goverment", "allcoation") but NOT one substituted
         letter, since that is usually a different word (policy/police,
         contract/contrast, deploy/deplore);
       - 9+ letters: up to 2 edits ("artifical inteligence", "memorandam").
     Short words (ai, cm, mou, rfp, app) are exact-only: fuzzy-matching them
     would turn "am", "mom", "apt" into hits.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "keywords.json"
FUZZY_MIN_LEN = 6

_SPELLING = [(r"\bcenter(s?)\b", r"centre\1"), (r"\bprogram(s?)\b", r"programme\1"),
             (r"\b(\w{3,})iz(e|es|ed|ing|ation|ations)\b", r"\1is\2"), (r"\bgovt\.", "govt")]


def normalise(text: str) -> str:
    t = (text or "").replace("’", "'").replace("‘", "'").replace("–", " ").replace("—", " ")
    # dotted acronyms: A.I. / M.o.U. / U.P. -> ai / mou / up
    t = re.sub(r"\b((?:[A-Za-z]\.){2,})", lambda m: m.group(1).replace(".", ""), t)
    t = t.lower()
    t = re.sub(r"'s\b", "", t)
    t = re.sub(r"[-/_]", " ", t)
    for pat, rep in _SPELLING:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class Keyword:
    __slots__ = ("raw", "tokens", "prefix")

    def __init__(self, raw: str):
        self.raw = raw
        self.prefix = raw.endswith("*")
        self.tokens = normalise(raw.rstrip("*")).split()


class KeywordSet:
    """A named list of keywords; `find(text)` returns the keywords that hit."""

    def __init__(self, name: str, words: list[str]):
        self.name = name
        self.keywords = [Keyword(w) for w in words if w and not w.startswith("_")]
        self.vocab = {t for k in self.keywords for t in k.tokens}

    def find(self, text: str | list[str]) -> list[str]:
        toks = normalise(text).split() if isinstance(text, str) else text
        hits = []
        for k in self.keywords:
            if _match(k, toks):
                hits.append(k.raw)
        return hits

    def any(self, text) -> bool:
        toks = normalise(text).split() if isinstance(text, str) else text
        return any(_match(k, toks) for k in self.keywords)


def _osa(a: str, b: str) -> int:
    """Edit distance where swapping two neighbours counts as 1 ('allcoation')."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


@lru_cache(maxsize=200_000)
def _fuzzy_eq(token: str, kw: str) -> bool:
    if token == kw:
        return True
    if len(kw) < FUZZY_MIN_LEN or len(token) < FUZZY_MIN_LEN - 1:
        return False
    if token[0] != kw[0] or abs(len(token) - len(kw)) > 2:
        return False
    # "startup" vs "startuptn", "govern" vs "government": cutting/adding letters
    # at the END changes the word, it isn't a typo.
    if abs(len(token) - len(kw)) >= 2 and (kw.startswith(token) or token.startswith(kw)):
        return False
    dist = _osa(token, kw)
    if len(kw) >= 9:                       # long words: any 2 edits (artifical, inteligence)
        return dist <= 2
    if dist != 1:
        return False
    # 6-8 letters: one missing/extra letter or one swap - NOT a substituted
    # letter, because that usually makes a different real word
    # (policy/police, contract/contrast, deploy/deplore).
    return len(token) != len(kw) or sorted(token) == sorted(kw)


def _tok_eq(token: str, kw: str, prefix: bool) -> bool:
    if prefix:
        if token.startswith(kw):
            return True
        # typo in the stem: compare the same-length head ("allcoation" ~ "allocat")
        return len(kw) >= FUZZY_MIN_LEN and any(_fuzzy_eq(token[: len(kw) + d], kw) for d in (0, 1))
    return _fuzzy_eq(token, kw)


def _match(k: Keyword, toks: list[str]) -> bool:
    n = len(k.tokens)
    if n == 0:
        return False
    for i in range(len(toks) - n + 1):
        ok = True
        for j, kt in enumerate(k.tokens):
            last = j == n - 1
            if not _tok_eq(toks[i + j], kt, k.prefix and last):
                ok = False
                break
        if ok:
            return True
    return False


class Lexicon:
    def __init__(self, path: Path = CONFIG):
        c = json.loads(path.read_text(encoding="utf-8"))
        self.ai = KeywordSet("ai_terms", c["ai_terms"])
        self.gov = KeywordSet("gov_terms", c["gov_terms"])
        self.deal = KeywordSet("deal_terms", c["deal_terms"])
        self.exclude = KeywordSet("exclude_title", c["exclude_title"])
        self.category_order = c["categories"]["_order"]
        self.categories = {k: KeywordSet(k, c["categories"][k]) for k in self.category_order}
        self.masks = [normalise(m) for m in c.get("mask_phrases", [])]
        self.sector_order = c["sectors"]["_order"]
        self.sectors = {k: KeywordSet(k, c["sectors"][k]) for k in self.sector_order}


@lru_cache(maxsize=1)
def get_lexicon() -> Lexicon:
    return Lexicon()


def masked(norm_text: str, masks: list[str]) -> str:
    """Remove mask phrases (already normalised) from normalised text."""
    t = f" {norm_text} "
    for m in masks:
        t = t.replace(f" {m} ", " ")
    return t.strip()
