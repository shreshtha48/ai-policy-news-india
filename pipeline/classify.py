"""Where we draw the line: relevance + category + sector + actors + amount.

An article is "AI policy activity" only if ALL of these hold:
  1. it is about AI           (AI_TERMS)
  2. a government is acting   (GOV_TERMS, a state body, or the state is the
                               grammatical subject of the headline:
                               "Karnataka explores voice AI ...")
  3. it is not an obvious off-topic item (EXCLUDE: markets, gadgets, Air India
     flight numbers, entertainment ...)
  4. it maps to a category    (otherwise: an AI speech/opinion with no concrete
                               action -> rejected as 'no_concrete_action')
Rules are deliberately transparent regexes: every rejection carries a reason
and is written to rejected.csv so the line can be audited and tuned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

AI_TERMS = re.compile(
    r"\bartificial[\s-]intelligence\b|\bGen\s?AI\b|\bgenerative AI\b|\bmachine learning\b"
    r"|\bdeep ?fakes?\b|\bLLMs?\b|\blarge language model|\bAI\b|\bA\.I\.", re.I)
AI_CASE_SENSITIVE = re.compile(r"\bAI\b")      # "ai" lowercase in slugs/words shouldn't count
AI_WORDY = re.compile(r"artificial[\s-]intelligence|gen\s?ai|generative ai|machine learning"
                      r"|deep ?fakes?|\bllms?\b|large language model", re.I)

GOV_TERMS = re.compile(
    r"\bgovernment\b|\bgovt\b|\bminister\b|\bministry\b|\bCM\b|\bchief minister\b|\bcabinet\b"
    r"|\bdepartment\b|\bdept\b|\bpolicy\b|\bmission\b|\bMoUs?\b|\bpact\b|\btask ?force\b"
    r"|\bbudget\b|\bpolice\b|\bcollector\b|\bdistrict administration\b|\bmunicipal\b"
    r"|\bcivic body\b|\bassembly\b|\bsecretariat\b|\be-?governance\b|\bpublic services?\b"
    r"|\bcitizen services?\b|\bstate-run\b|\bofficials?\b|\bmantralaya\b|\bscheme\b"
    r"|\bguidelines\b|\badvisory\b|\bregulat\w*|\bstate\b|\bUnion\b|\bCentre\b|\bMeitY\b|\bIndiaAI\b"
    r"|\bT-Hub\b|\bKITS\b|\bStartupTN\b|\bTNeGA\b|\bi-?Hub Gujarat\b|\bMahaIT\b|\bBBMP\b|\bGHMC\b"
    r"|\bBMC\b|\bNDMC\b|\bMCD\b|\bGIFT City\b", re.I)
STATE_SUBJECT = re.compile(
    r"^(tamil nadu|tn|karnataka|telangana|delhi|gujarat|maharashtra)(\s+(govt|government|cabinet|cm))?"
    r"\s+(to|will|plans?|launches?|unveils?|signs?|sets?|explores?|rolls?|announces?|approves?|"
    r"introduces?|partners?|ties|inks?|deploys?|adopts?|begins?|starts?|gets?|opens?|issues?|allocates?|"
    r"earmarks?|notifies|releases?|forms?|creates?|seeks?|eyes|bets|pushes|mulls|readies)\b", re.I)

EXCLUDE = re.compile(
    r"\bshares?\b.*\b(rise|fall|jump|surge|slip)|\bSensex\b|\bNifty\b|\bIPO\b|\bQ[1-4] results\b"
    r"|\bbox office\b|\biPhone\b|\bsmartphone\b|\blaptop\b|\bhoroscope\b|\bcricket\b|\bIPL\b"
    r"|\bAir India\b|\bAI[\s-]?\d{2,4}\b|\bmovie\b|\bfilm\b|\btrailer\b", re.I)

# Order matters: first match wins (see README for why).
CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("budget_funding", re.compile(r"\bbudget\b|\ballocat\w*|\boutlay\b|\bearmark\w*|\bcorpus\b"
                                  r"|\bfund of funds\b|\bAI fund\b|\bgrants?\b|\bsanction(s|ed)?\b", re.I)),
    ("regulation_ethics", re.compile(r"\bguidelines?\b|\bregulat\w*|\bethic\w*|\bdeep ?fakes?\b|\badvisory\b"
                                     r"|\bban(s|ned)?\b|\bresponsible AI\b|\bmisuse\b|\bSOPs?\b|\bprivacy\b"
                                     r"|\bgovernance framework\b|\bcode of conduct\b", re.I)),
    ("partnership", re.compile(r"\bMoUs?\b|\bpact\b|\bpartner\w*|\bties? up\b|\btie-up\b|\bcollaborat\w*"
                               r"|\bagreement\b|\bjoins hands\b|\bLoI\b|\binks?\b|\bsigns?\b", re.I)),
    ("policy_mission", re.compile(r"\bpolicy\b|\bmission\b|\bstrategy\b|\broadmap\b|\bblueprint\b"
                                  r"|\baction plan\b|\bvision document\b|\bframework\b", re.I)),
    ("institution", re.compile(r"\btask ?force\b|\bcentres? of excellence\b|\bCoE\b|\bcommittee\b"
                               r"|\bcouncil\b|\bAI city\b|\binstitute\b|\bAI hub\b|\bcell\b|\blab\b"
                               r"|\bsets? up\b|\bestablish\w*|\binaugurat\w*|\bAI university\b", re.I)),
    ("governance_deployment", re.compile(r"\bdeploy\w*|\blaunch\w*|\broll(s|ed)? out\b|\bpilot\w*"
                                         r"|\bintroduc\w*|\bAI[\s-](powered|based|enabled|driven)\b"
                                         r"|\bchatbot\b|\bus(es|ing|e) AI\b|\badopt\w*|\bimplement\w*"
                                         r"|\bcameras?\b|\bsurveillance\b|\bportal\b|\bapp\b|\bexplor\w*"
                                         r"|\bscreening\b|\bdiagnos\w*|\bforecast\w*|\bmonitor\w*", re.I)),
]

SECTOR_RULES: list[tuple[str, re.Pattern]] = [
    ("health", re.compile(r"\bhealth\w*|\bhospital|\bmedical\b|\bpatients?\b|\bdiagnos|\bTB\b|\bcancer\b|\bdoctor", re.I)),
    ("agriculture", re.compile(r"\bagri\w*|\bfarm\w*|\bcrops?\b|\bkisan\b|\bsoil\b|\birrigation\b|\bmonsoon\b", re.I)),
    ("policing", re.compile(r"\bpolice\b|\bcrime\b|\bcyber ?crime\b|\bCCTV\b|\blaw and order\b|\bsurveillance\b|\bdeep ?fakes?\b", re.I)),
    ("education", re.compile(r"\bschools?\b|\bstudents?\b|\bteachers?\b|\beducation\b|\bcurriculum\b|\bskilling\b|\bskills?\b|\buniversit|\bcolleges?\b", re.I)),
    ("urban", re.compile(r"\bcivic\b|\bmunicipal\b|\burban\b|\btraffic\b|\bwaste\b|\bwater supply\b|\bmetro rail\b|\bGHMC\b|\bBBMP\b|\bBMC\b", re.I)),
    ("revenue", re.compile(r"\brevenue\b|\btax\w*|\bland records?\b|\bregistration\b|\bGST\b|\bstamps?\b", re.I)),
]

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


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    category: str = ""
    sector: str = ""


def is_ai(text: str) -> bool:
    return bool(AI_CASE_SENSITIVE.search(text) or AI_WORDY.search(text))


def has_gov_signal(title: str, text: str) -> bool:
    return bool(GOV_TERMS.search(text) or STATE_SUBJECT.search(title.strip()))


def category_of(text: str) -> str:
    for cat, pat in CATEGORY_RULES:
        if pat.search(text):
            return cat
    return ""


def sector_of(text: str) -> str:
    for sec, pat in SECTOR_RULES:
        if pat.search(text):
            return sec
    return ""


def judge(title: str, excerpt: str = "") -> Verdict:
    text = f"{title}. {excerpt}".strip()
    if not is_ai(text):
        return Verdict(False, "not_ai")
    if EXCLUDE.search(title):
        return Verdict(False, "excluded_topic")
    if not has_gov_signal(title, text):
        return Verdict(False, "no_gov_signal")
    # Category is decided on the headline first (it states the action);
    # the excerpt is only a fallback.
    cat = category_of(title) or category_of(excerpt)
    if not cat:
        return Verdict(False, "no_concrete_action")
    return Verdict(True, "", cat, sector_of(text))


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
