"""Two-stage de-duplication (see cluster() for the event rules).

Stage 1 - same ARTICLE seen twice (e.g. via Google News and via the outlet's
own RSS, or on two runs): key = canonical URL, or (outlet domain, normalised
headline) because Google News only gives a redirect URL.

Stage 2 - same EVENT reported by many outlets: articles are linked when
  * same state, and
  * published within WINDOW_DAYS of each other (unknown dates: title only,
    stricter threshold), and
  * their *distinctive* headline words overlap enough. Generic words
    ("Telangana", "AI", "signs", "MoU", "govt") are removed first and the
    rest are IDF-weighted, so "Telangana signs MoU with Google" and
    "Telangana signs MoU with Microsoft" do NOT merge, while
    "Deakin University, Telangana sign AI pact" and "Telangana inks MoU
    with Deakin University" do.
Linked articles are grouped with union-find (transitive).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

WINDOW_DAYS = 7
THRESHOLD = 0.5
THRESHOLD_NO_DATE = 0.7

GENERIC = set("""
a an the of for to in on at by with and or as is are be will its it from into over under after new
ai artificial intelligence genai generative ml machine learning tech technology digital
govt government state states cm chief minister ministers minister's department dept official officials
signs sign signed inks ink mou mous pact pacts partnership partners partner ties tie up agreement
launches launch launched unveils unveil sets set up to plan plans announces announce announced
policy mission task force centre center excellence coe budget crore rs lakh fund
says said say get gets report reports news latest today india indian national first
deal deals strike strikes strikes agreement agreements major big key
""".split())
_STATE_WORDS = set("""tamil nadu tn karnataka telangana tg ts delhi gujarat maharashtra mh chennai
bengaluru bangalore hyderabad mumbai pune ahmedabad new""".split())
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid",
            "gclid", "oc", "amp", "cmpid"}


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = re.sub(r"/amp/?$|/amp(?=/)", "", p.path).rstrip("/")
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING])
    return urlunparse(("", host, path, "", q, ""))


def norm_title(title: str) -> str:
    t = title.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_SUFFIXES = ("ions", "ors", "ers", "ing", "ed", "es", "s")


def stem(t: str) -> str:
    """Tiny suffix stripper: violators/violations -> violat, cameras -> camera."""
    if len(t) > 5:
        for suf in _SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                return t[: -len(suf)]
    return t


def distinctive_tokens(title: str) -> set[str]:
    toks = norm_title(title).split()
    return {stem(t) for t in toks
            if t not in GENERIC and t not in _STATE_WORDS and len(t) > 2 and not t.isdigit()}


def proper_nouns(title: str) -> set[str]:
    """Capitalised words not at the start of the headline: usually the entity
    (partner company, university, scheme name) that identifies the event."""
    words = re.findall(r"[A-Za-z][\w'&-]*", title)
    return {stem(norm_title(w)) for w in words[1:] if w[0].isupper() and not w.isupper() or (w.isupper() and len(w) > 2)}


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


ENTITY_BOOST = 2.0


def similarity(a: set[str], b: set[str], idf: dict[str, float], entities: set[str] = frozenset()) -> float:
    if not a or not b:
        return 0.0
    shared = a & b
    if not shared:
        return 0.0
    w = lambda s: sum(idf.get(t, 1.0) * (ENTITY_BOOST if t in entities else 1.0) for t in s)
    return w(shared) / min(w(a), w(b))


def cluster(items: list[dict], vectors=None, sem_threshold: float = 0.78) -> list[list[int]]:
    """Group article indices into events.

    items need: state_code, date ('' if unknown), title; optional: category,
    partners (set of named partners). `vectors` = optional L2-normalised
    embeddings (one row per item) for meaning-based similarity.

    Two articles are LINKED when they are in the same state and ANY of:
      * lexical: enough distinctive headline words shared (IDF-weighted);
      * semantic: embedding cosine >= sem_threshold;
      * entity anchor: same category + same named partner (e.g. both name
        Google), even if the wording differs completely;
      * amount anchor: same category + the same rupee figure (>= Rs 100
        crore) in the headline - "Rs 70,000 crore AI data centre" is one
        announcement however it is worded.
    ...and NONE of the vetoes apply:
      * both name partners and they don't overlap (Google vs Microsoft);
      * the merged event would span more than WINDOW_DAYS from its first to
        its last article (stops A~B~C chaining across weeks).
    Links are applied strongest-first, so the span cap keeps the best pairs.
    """
    toks = [distinctive_tokens(it["title"]) for it in items]
    ents = [proper_nouns(it["title"]) & t for it, t in zip(items, toks)]
    df = Counter(t for s in toks for t in s)
    n = max(len(items), 1)
    # floor keeps common-but-meaningful words from counting as zero
    idf = {t: max(0.5, math.log((n + 1) / (c + 0.5))) for t, c in df.items()}
    days = [date.fromisoformat(it["date"]).toordinal() if it.get("date") else None for it in items]
    partners = [set(it.get("partners") or ()) for it in items]
    amounts = [it.get("amount") for it in items]

    by_state: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        by_state.setdefault(it["state_code"], []).append(i)

    candidates: list[tuple[float, int, int]] = []
    for idxs in by_state.values():
        for x in range(len(idxs)):
            i = idxs[x]
            for y in range(x + 1, len(idxs)):
                j = idxs[y]
                dated = days[i] is not None and days[j] is not None
                if dated and abs(days[i] - days[j]) > WINDOW_DAYS:
                    continue
                if partners[i] and partners[j] and not (partners[i] & partners[j]):
                    continue                                   # different partners: never the same event
                score = 0.0
                shared = toks[i] & toks[j]
                thr = THRESHOLD if dated else THRESHOLD_NO_DATE
                if len(shared) >= 2 or (len(shared) == 1 and min(len(toks[i]), len(toks[j])) <= 2):
                    sim = similarity(toks[i], toks[j], idf, ents[i] | ents[j])
                    if sim >= thr:
                        score = max(score, sim)
                if vectors is not None:
                    cos = float(vectors[i] @ vectors[j])
                    if cos >= (sem_threshold if dated else sem_threshold + 0.07):
                        score = max(score, cos)
                if (dated and partners[i] & partners[j] and items[i].get("category")
                        and items[i].get("category") == items[j].get("category")):
                    score = max(score, 0.6)                    # entity anchor
                if (dated and amounts[i] and amounts[i] >= 100 and amounts[i] == amounts[j]
                        and items[i].get("category") == items[j].get("category")):
                    score = max(score, 0.65)                   # same state, same week, same Rs figure
                if score > 0:
                    candidates.append((score, i, j))

    uf = UnionFind(len(items))
    lo = {i: days[i] for i in range(len(items))}
    hi = dict(lo)
    for score, i, j in sorted(candidates, reverse=True):
        ri, rj = uf.find(i), uf.find(j)
        if ri == rj:
            continue
        spans = [v for v in (lo[ri], hi[ri], lo[rj], hi[rj]) if v is not None]
        if spans and max(spans) - min(spans) > WINDOW_DAYS:
            continue                                           # would chain across weeks
        uf.union(ri, rj)
        root = uf.find(ri)
        lo[root] = min(spans) if spans else None
        hi[root] = max(spans) if spans else None
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())
