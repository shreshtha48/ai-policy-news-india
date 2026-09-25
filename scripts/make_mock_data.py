"""Generate MOCK data in the final schema so the dashboard can be built
before the real pipeline exists. Deterministic (fixed seed).

All records are FICTIONAL: source names are "Mock ..." and URLs point to
example.com. Replace data/mock/* with data/processed/* once scraping works.

Run:  python scripts/make_mock_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mock"
OUT.mkdir(parents=True, exist_ok=True)

STATES = {
    "IN-TN": ("Tamil Nadu", ["Chennai"]),
    "IN-KA": ("Karnataka", ["Bengaluru"]),
    "IN-TG": ("Telangana", ["Hyderabad"]),
    "IN-DL": ("Delhi", ["Delhi"]),
    "IN-GJ": ("Gujarat", ["Ahmedabad"]),
    "IN-MH": ("Maharashtra", ["Mumbai", "Pune"]),
    "IN-CENTRAL": ("Central Government", []),
}
# rough weights so the mock shows uneven activity, like reality will
STATE_WEIGHTS = {"IN-KA": 14, "IN-TG": 13, "IN-TN": 11, "IN-MH": 11,
                 "IN-GJ": 8, "IN-DL": 6, "IN-CENTRAL": 5}

SECTORS = ["health", "agriculture", "policing", "education", "urban", "revenue"]
ACTORS = ["IT Department", "Electronics & IT Dept", "Chief Minister's Office",
          "Health Department", "Agriculture Department", "Police Department",
          "Education Department", "Finance Department", "State Startup Mission"]
PARTNERS = ["a global cloud provider", "an IIT", "an IIIT", "a chipmaker",
            "a state university", "an AI startup consortium", "a big-tech firm"]

# (title template, summary template, subcategory or None)
TEMPLATES = {
    "policy_mission": [
        ("{s} unveils AI policy targeting {n} startups by 2030",
         "{s} released a state AI policy with startup, skilling and compute incentives.", None),
        ("{s} launches state AI Mission with focus on public services",
         "A state AI Mission was announced to coordinate AI adoption across departments.", None),
        ("{s} cabinet approves draft AI and data strategy",
         "The state cabinet cleared a draft AI and data strategy for public consultation.", None),
    ],
    "institution": [
        ("{s} sets up AI task force under IT department",
         "A task force of officials and experts will advise the state on AI adoption.", None),
        ("AI Centre of Excellence inaugurated in {c}",
         "The state opened an AI Centre of Excellence to incubate governance use cases.", None),
    ],
    "partnership": [
        ("{s} signs MoU with {p} for AI skilling",
         "The state signed an MoU with {p} to train students and officials in AI.", None),
        ("{s} partners {p} to build AI compute facility",
         "An MoU with {p} will set up shared GPU compute for startups and researchers.", None),
    ],
    "governance_deployment": [
        ("{s} rolls out AI tool in {sec} department",
         "The state began using an AI system in {sec} services, starting with pilot districts.", "sec"),
        ("AI pilot for {sec} expands across {s} districts",
         "An AI pilot in {sec} was extended after initial results, officials said.", "sec"),
    ],
    "budget_funding": [
        ("{s} budget earmarks Rs {amt} crore for AI",
         "The state budget set aside Rs {amt} crore for AI programmes and infrastructure.", None),
        ("{s} announces Rs {amt} crore AI fund for startups",
         "A Rs {amt} crore fund will back AI startups based in the state.", None),
    ],
    "procurement": [
        ("{s} floats tender for AI-based {sec} system",
         "The state invited bids for an AI system to support {sec} services.", "sec"),
    ],
    "statement_intent": [
        ("{s} CM praises AI infrastructure, says state plans similar hub",
         "The Chief Minister signalled interest in building AI infrastructure; no formal decision yet.", None),
    ],
    "regulation_ethics": [
        ("{s} issues guidelines on AI use by government departments",
         "Departments must follow new guidelines on data privacy and human oversight of AI.", None),
        ("{s} police issue advisory on deepfakes",
         "State police issued an advisory on deepfake fraud and reporting channels.", "policing"),
    ],
}
CAT_WEIGHTS = {"policy_mission": 3, "institution": 3, "partnership": 5,
               "governance_deployment": 6, "budget_funding": 2, "regulation_ethics": 2,
               "procurement": 2, "statement_intent": 3}

MOCK_SOURCES = ["Mock Daily", "Mock Times", "Mock Business Standard",
                "Mock Tech Wire", "Mock Gov Review", "Mock Regional Post",
                "Mock Chronicle", "Mock Herald"]
FETCHERS = ["google_news_rss", "google_news_rss", "google_news_rss", "gdelt", "gnews"]

START, END = date(2025, 1, 1), date(2026, 9, 20)
N_EVENTS = 80


def pick(weights):
    keys = list(weights)
    return random.choices(keys, weights=[weights[k] for k in keys])[0]


def slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")[:60]


events, articles = [], []
for i in range(1, N_EVENTS + 1):
    code = pick(STATE_WEIGHTS)
    state_name, metros = STATES[code]
    cat = pick(CAT_WEIGHTS)
    t_title, t_sum, sub = random.choice(TEMPLATES[cat])
    sector = random.choice(SECTORS) if sub == "sec" else (sub or "")
    city = random.choice(metros) if metros and random.random() < 0.45 else ""
    amt = random.choice([25, 50, 100, 150, 250, 500]) if cat in ("budget_funding", "procurement") else None
    fmt = dict(s=state_name if code != "IN-CENTRAL" else "Centre",
               c=city or (metros[0] if metros else "New Delhi"),
               p=random.choice(PARTNERS), sec=sector or "public", n=random.choice([500, 1000, 2000]),
               amt=amt)
    title = t_title.format(**fmt)
    summary = t_sum.format(**fmt)

    # dates: mostly exact, some month-only, a few unknown (explicit, never guessed)
    pub = START + timedelta(days=random.randint(0, (END - START).days))
    r = random.random()
    if r < 0.78:
        precision, event_date = "day", pub - timedelta(days=random.choice([0, 0, 0, 1]))
    elif r < 0.93:
        precision, event_date = "month", pub.replace(day=1)
    else:
        precision, event_date = "unknown", None

    n_src = random.choices([1, 2, 3, 4, 6, 9], weights=[30, 25, 18, 12, 9, 6])[0]
    eid = f"EVT-{i:04d}"
    first = None
    for j in range(n_src):
        p_date = pub + timedelta(days=0 if j == 0 else random.choice([0, 0, 1, 2, 4]))
        src = MOCK_SOURCES[(i + j) % len(MOCK_SOURCES)]
        # outlets reword headlines -> this is what dedupe must collapse
        a_title = title if j == 0 else random.choice([
            title, title + " - report", "Explained: " + title, title.replace(" AI ", " artificial intelligence ")])
        articles.append({
            "article_id": f"ART-{len(articles) + 1:05d}",
            "event_id": eid,
            "state_code": code,
            "title": a_title,
            "source_name": src,
            "source_url": f"https://example.com/mock/{slug(src)}/{eid.lower()}-{j + 1}",
            "published_date": p_date.isoformat(),
            "fetched_via": random.choice(FETCHERS),
            "is_primary": "true" if j == 0 else "false",
            "state_basis": "text",
            "matched_terms": "ai:ai; gov:government",
        })
        first = first or (src, articles[-1]["source_url"], p_date)

    events.append({
        "event_id": eid,
        "state_code": code,
        "state_name": state_name,
        "city": city,
        "category": cat,
        "sector": sector,
        "title": title,
        "summary": summary,
        "event_date": event_date.isoformat() if event_date else "",
        "date_precision": precision,
        "first_reported_date": first[2].isoformat(),
        "primary_source_name": first[0],
        "primary_source_url": first[1],
        "source_count": n_src,
        "actors": "; ".join(random.sample(ACTORS, k=random.randint(1, 2))),
        "amount_inr_crore": amt if amt is not None else "",
    })

events.sort(key=lambda e: e["first_reported_date"], reverse=True)
articles.sort(key=lambda a: (a["event_id"], a["published_date"]))

for name, rows in [("events_mock.csv", events), ("articles_mock.csv", articles)]:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {name}: {len(rows)} rows")
