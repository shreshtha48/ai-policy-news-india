"""Where we draw the line: relevance + category + sector + actors + amount.

All keyword lists live in config/keywords.json and are matched
case-insensitively with typo tolerance (pipeline/keywords.py).

An article is "AI policy activity" when ALL of these hold:
  1. it is about AI                 (ai_terms: AI, GenAI, LLM, chatbot, Gemini,
                                     deepfake, data centre, GPU ...)
  2. it is not obviously off-topic  (exclude_title: markets, gadgets, films,
                                     Air India / "AI-171" flight numbers ...)
  3. a government is involved       (gov_terms: govt, CM, minister, department,
                                     MoU, tender, budget, scheme ...), OR the
                                     state is the subject of the headline
                                     ("Karnataka explores voice AI"), OR a
                                     focus state is named together with a
                                     deal/money word (invest, MoU, contract,
                                     crore, data centre)
Nothing is rejected for lacking a concrete action: a CM praising an AI
project or saying the state "plans" something signals the state's stance, so
it is kept as category `statement_intent` (the fallback category).
Every rejection carries a reason and goes to rejected.csv.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .keywords import get_lexicon, normalise

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
    gov = L.gov.find(x_toks)
    deal = L.deal.find(x_toks)
    subject = bool(STATE_SUBJECT.search(title.strip()))
    if not (gov or subject or (deal and FOCUS_STATE_RE.search(text))):
        return Verdict(False, "no_gov_signal", matched={"ai": ai})
    # Category: headline decides (it states the action); excerpt is fallback;
    # statement_intent is the catch-all for stance/intent pieces.
    cat = _first(L.category_order[:-1], L.categories, t_toks) or \
          _first(L.category_order[:-1], L.categories, normalise(excerpt).split()) or "statement_intent"
    sector = _first(L.sector_order, L.sectors, x_toks) or ""
    return Verdict(True, "", cat, sector,
                   matched={"ai": ai, "gov": gov or (["state_as_subject"] if subject else deal)})


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
    (r"\b(Google|Microsoft|Nvidia|NVIDIA|OpenAI|Anthropic|Meta|Amazon|AWS|IBM|Intel|Infosys|TCS|Wipro|HCL\w*"
     r"|Sarvam|ElevenLabs|Qualcomm|Adobe|Salesforce|Tata \w+|Reliance|Jio|L&T|Accenture|Cisco|Oracle|AMD|Micron)\b", None),
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
