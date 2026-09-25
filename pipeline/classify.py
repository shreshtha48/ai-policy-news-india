"""Where we draw the line: relevance + category + sector + actors + amount.

All keyword lists live in config/keywords.json and are matched
case-insensitively with typo tolerance (pipeline/keywords.py).

An article is "AI policy activity" when ALL of these hold:
  1. it is about AI                 (ai_terms: AI, GenAI, LLM, chatbot, Gemini,
                                     deepfake, data centre, GPU ...)
  2. it is not obviously off-topic  (exclude_title: markets, gadgets, films,
                                     Air India / "AI-171" flight numbers ...)
  3. a government is involved       (gov_terms: govt, CM, minister, department,
                                     MoU, tender, budget, scheme, state leaders
                                     and bodies ...), OR the state is the
                                     subject of the headline ("Karnataka
                                     explores voice AI"), OR a focus state /
                                     metro is named together with a deal word
                                     or a concrete action in the headline
                                     ("Hyderabad to get AI centre of excellence")
Nothing is rejected for lacking a concrete action: a CM praising an AI
project or saying the state "plans" something signals the state's stance, so
it is kept as category `statement_intent` (the fallback category).
Every rejection carries a reason and goes to rejected.csv.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geo import get_geo
from .keywords import get_lexicon, masked, normalise

# Pattern-shaped exclusions that keywords can't express.
EXCLUDE_RE = re.compile(r"\bAI[\s-]?\d{2,4}\b|\bshares?\b.*\b(rise|rises|fall|falls|jump|jumps|surge|surges|slip|slips)\b",
                        re.I)
STATE_SUBJECT = re.compile(
    r"^(tamil nadu|tn|karnataka|telangana|delhi|gujarat|maharashtra)(\s+(govt|government|cabinet|cm))?"
    r"\s+(to|will|plans?|launches?|unveils?|signs?|sets?|explores?|rolls?|announces?|approves?|"
    r"introduces?|partners?|ties|inks?|deploys?|adopts?|begins?|starts?|gets?|opens?|issues?|allocates?|"
    r"earmarks?|notifies|releases?|forms?|creates?|seeks?|eyes|bets|pushes|mulls|readies|invites?|woos?|"
    r"floats?|awards?|aims?|wants?)\b", re.I)
FOCUS_STATE_RE = re.compile(r"\b(tamil nadu|karnataka|telangana|delhi|gujarat|maharashtra|chennai|bengaluru|"
                            r"bangalore|hyderabad|mumbai|pune|ahmedabad|gandhinagar)\b", re.I)


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    category: str = ""
    sector: str = ""
    matched: dict = field(default_factory=dict)   # which keywords fired (audit trail)
    cat_source: str = ""                          # title | excerpt | fallback


def judge(title: str, excerpt: str = "") -> Verdict:
    L = get_lexicon()
    text = f"{title}. {excerpt}".strip()
    t_toks, x_toks = normalise(title).split(), normalise(text).split()
    ai = L.ai.find(x_toks)
    if not ai:
        return Verdict(False, "not_ai")
    excl = L.exclude.find(t_toks)
    if excl or EXCLUDE_RE.search(title):
        return Verdict(False, "excluded_topic", matched={"ai": ai, "exclude": excl or ["pattern"]})
    gov = L.gov.find(masked(" ".join(x_toks), L.masks).split())
    deal = L.deal.find(x_toks)
    subject = bool(STATE_SUBJECT.search(title.strip()))
    g = get_geo().resolve(text)
    state_named = bool(g.in_focus and g.state_code and g.state_code != get_geo().central_code)
    headline_action = category_of(title)[1] == "title"
    if not (gov or subject or (state_named and (deal or headline_action))):
        return Verdict(False, "no_gov_signal", matched={"ai": ai})
    # Category: headline decides (it states the action); excerpt is fallback;
    # statement_intent is the catch-all for stance/intent pieces.
    cat, src = category_of(title, excerpt)
    sector = _first(L.sector_order, L.sectors, x_toks) or ""
    return Verdict(True, "", cat, sector,
                   matched={"ai": ai, "gov": gov or (["state_as_subject"] if subject else
                                                     deal or ["state_named+action"])}, cat_source=src)


def category_of(title: str, excerpt: str = "") -> tuple[str, str]:
    """(category, where it came from). The headline states the action, so it
    decides first; the excerpt is a fallback; statement_intent is the catch-all."""
    L = get_lexicon()
    order = [c for c in L.category_order if c != "statement_intent"]
    cat = _first(order, L.categories, normalise(title).split())
    if cat:
        return cat, "title"
    cat = _first(order, L.categories, normalise(excerpt).split())
    if cat:
        return cat, "excerpt"
    return "statement_intent", "fallback"


def _first(order, sets, toks) -> str:
    for name in order:
        if sets[name].any(toks):
            return name
    return ""


ACTOR_PATTERNS = [
    (r"\bIT (department|dept|minister)\b|\bITE&C\b", "State IT Department"),
    (r"\bchief minister\b|\bCM\b", "Chief Minister"),
    (r"\bcabinet\b", "State Cabinet"),
    (r"\bpolice\b", "Police"),
    (r"\bhealth (department|dept|minister)\b", "Health Department"),
    (r"\beducation (department|dept|minister)\b|\bschool education\b", "Education Department"),
    (r"\bagriculture (department|dept|minister)\b", "Agriculture Department"),
    (r"\bT-Hub\b", "T-Hub"), (r"\bKITS\b", "KITS"), (r"\bStartupTN\b", "StartupTN"),
    (r"\bTNeGA\b", "TNeGA"), (r"\bMahaIT\b", "MahaIT"), (r"\bi-?Hub Gujarat\b", "i-Hub Gujarat"),
    (r"\bMeitY\b", "MeitY"), (r"\bIndiaAI\b", "IndiaAI Mission"), (r"\bNASSCOM\b", "NASSCOM"),
    (r"\bIIT[\s-]?(Madras|Bombay|Delhi|Hyderabad|Gandhinagar|Kanpur|Kharagpur)\b", None),
    (r"\bIIIT[\s-]?(Hyderabad|Bangalore|Bengaluru|Delhi)\b", None), (r"\bIISc\b", "IISc"),
    (r"\bTata Consultancy Services\b|\bHyperVault\b", "TCS"),
    (r"\b(Google|Microsoft|Nvidia|NVIDIA|OpenAI|Anthropic|Meta|Amazon|AWS|IBM|Intel|Infosys|TCS|Wipro|HCL\w*"
     r"|Sarvam|ElevenLabs|Qualcomm|Adobe|Salesforce|Reliance|Jio|L&T|Accenture|Cisco|Oracle|AMD|Micron|Fortune|CtrlS|Airtel|Yotta|Sify|Adani|Philips|Unilever|Deakin|HAL|NIMS)\b", None),
    (r"\b[A-Z][a-z]+ University\b", None),
]
ACTOR_RES = [(re.compile(p), label) for p, label in ACTOR_PATTERNS]

AMOUNT = re.compile(r"(?:Rs\.?|₹|INR)\s?([\d,]+(?:\.\d+)?)\s*(lakh crore|crore|cr\b)", re.I)


def actors_of(text: str) -> list[str]:
    found: list[str] = []
    for pat, label in ACTOR_RES:
        for m in pat.finditer(text):
            name = label or m.group(0)
            if name not in found:
                found.append(name)
    return found[:5]


PARTNER_LABELS = {"IISc", "NASSCOM", "TCS"}


def partners_of(text: str) -> set[str]:
    """Named outside parties (companies, universities, IITs) - used by dedupe:
    two headlines naming DIFFERENT partners are never the same event."""
    out = set()
    for pat, label in ACTOR_RES:
        if label is None or label in PARTNER_LABELS:
            for m in pat.finditer(text):
                out.add((label or m.group(0)).lower())
    return out


def amount_crore(text: str) -> float | None:
    best = None
    for num, unit in AMOUNT.findall(text):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        if unit.lower() == "lakh crore":
            v *= 100000
        best = v if best is None else max(best, v)
    return best


def near_miss(title: str, reason: str = "not_ai") -> bool:
    """A rejected headline worth reading in full (review step 2). It must name
    a focus state (not the Union govt), and:
      * rejected as not_ai        -> the headline names a concrete action
        (MoU, deploys, tender, CoE...) - the body may say it's AI;
      * rejected for gov/semantic -> it already mentions AI - the body may
        show the government is involved."""
    L = get_lexicon()
    g = get_geo().resolve(title)
    if not (g.in_focus and g.state_code and g.state_code != get_geo().central_code):
        return False
    toks = normalise(title).split()
    if reason == "not_ai":
        return category_of(title)[1] == "title"
    return bool(L.ai.find(toks))
