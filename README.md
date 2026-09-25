# AI policy activity across Indian states

A pipeline that collects news about **AI-related policy activity by Indian state governments** (Jan 2026 to today), classifies it, removes duplicates, and publishes a dataset plus a dashboard.

- **Dataset:** `data/processed/events.csv` (one row per announcement), `articles.csv` (every article, linked to its event), `rejected.csv` (what was dropped and why), `ai_policy_india_states.xlsx` (all of it as sheets). Schema: [`data/SCHEMA.md`](data/SCHEMA.md).
- **Dashboard:** `dashboard/` (Vite + TypeScript source), built into `site/` and deployed to GitHub Pages by `.github/workflows/pipeline.yml`. It reads `dashboard/public/data/*.csv`, which `process` copies from `data/processed/` (`scripts/sync_dashboard_data.py`). Live link: _add after the first deploy_.

## Quick start (Windows PowerShell)

```powershell
cd ai-policy-news-india
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt            # includes sentence-transformers (~300 MB with PyTorch)
# optional, for SetFit training: pip install -r requirements-train.txt
python -m unittest discover -s tests -t .  # 41 offline tests

# optional API keys (skipped cleanly if unset)
$env:GNEWS_API_KEY="..."; $env:NEWS_API_KEY="..."; $env:NEWSDATA_API_KEY="..."

python -m pipeline.run fetch --dry-run                      # prints planned calls per API, calls nothing
python -m pipeline.run all --states IN-TG                   # one state end-to-end
python -m pipeline.run all                                  # all six states (~20 min first time)
```

| Command | What it does |
|---|---|
| `fetch [--states] [--sources] [--dry-run]` | Plans every request, skips ones already done (ledger), enforces daily API budgets, appends results to `data/raw/<date>/<source>.jsonl` |
| `process [--rules-only]` | Rebuilds `data/processed/` from all raw files (no network except the model download on first use) |
| `resolve [--max 50]` | Best-effort decoding of Google News redirect links for event primaries (cached) |
| `enrich [--max 60]` | Reads the first paragraphs of **near-miss** rejects (state + action but no AI word, or AI but no government signal) and re-judges them |
| `all` | fetch -> process -> resolve -> enrich -> process (also syncs the dashboard's data) |

**Training the classifier on our own labels** (recommended once after the first full run):

```powershell
python scripts/make_labelling_sheet.py            # data/labels/train_sheet.csv, ~200 rows
# open it in Excel: label = 1 (state-govt AI policy activity) or 0; category optional
python scripts/train_classifier.py                # prints CV precision/recall vs the current rules
python -m pipeline.run process                    # now uses the trained model ("classifier": learned)
```

## Scope: which states and why

Six states, chosen for tech-industry density, a metro tech hub, active state AI/IT policy, and dense English-language coverage: **Tamil Nadu (Chennai), Karnataka (Bengaluru), Telangana (Hyderabad), Delhi, Gujarat (Ahmedabad / GIFT City), Maharashtra (Mumbai, Pune)**. Union-government items are tagged `IN-CENTRAL` and kept separately. Items only about other states are dropped as `non_focus_state`. The window is **1 Jan 2026 onwards**.

City-level news is only tracked for those metros (`city` column). Other cities just resolve to their state.

## Sources, and why

| Source | Key? | Role | Reaches back |
|---|---|---|---|
| Google News RSS (India edition) | no | **Primary.** Per state: 3 topic queries, 1 per metro, 3–5 leader/body queries ("Revanth Reddy AI", "GIFT City AI"), 1 query restricted to that state's regional outlets. **Each query is split by month**, because a query returns at most ~100 items. | Jan 2026 |
| GDELT DOC API | no | Secondary. Rate-limited, noisy. | ~3 months |
| GNews / NewsAPI.org / NewsData.io | yes | **Recent enrichment:** real outlet URLs and snippets that Google News lacks, plus independent confirmation. 1 call per state per day each. | 30 d / 1 mo / 48 h |
| Outlet feeds | no | The Hindu state/city RSS (latest items), Telangana Today AI tag (paged WordPress feed = history, plus an HTML scraper), DeshGujarat (paged feed) | varies |

Every call goes through a **ledger** (`data/raw/_ledger.json`). Google slices for months that have ended are fetched once and never again. Everything else is fetched at most once a day, so a rerun costs no quota. Keyed APIs have a daily budget (default 20, far below the free limits). A daily GitHub Action (`.github/workflows/pipeline.yml`, 06:00 IST) runs the pipeline, commits `data/raw` + `data/processed`, and redeploys the dashboard. Pushes to `main` that touch the dashboard or data only rebuild and redeploy. It needs the three keys as repository secrets. Caches (embedding model, article leads, decoded links) live in the Actions cache, not in git.

Gujarat has the thinnest English coverage, so it gets extra leader/body queries (Bhupendra Patel, GIFT City, Gandhinagar, iHub), a site query over DeshGujarat, Ahmedabad Mirror, Indian Express, Times of India and the state information department, plus DeshGujarat's paged feeds.

## Where we drew the line (what counts as "AI policy activity")

An article is kept when it is **about AI** and **a state government is involved**:

1. **About AI:** AI, GenAI, LLMs, chatbots, Gemini/ChatGPT, computer vision, deepfakes, AI data centres, GPUs, IndiaAI and more (`config/keywords.json`).
2. **Government involved:** government words (govt, CM, minister, department, police, cabinet, MoU, tender, budget, scheme, authorities, administration…), state leaders and bodies (Revanth Reddy, T-Hub, TNeGA…), the state as the subject of the headline ("Karnataka explores voice AI…"), or a focus state named together with a deal or a concrete action ("Hyderabad to get AI centre of excellence").
3. **Not off-topic:** stock moves, gadgets, films, cricket, Air India / "AI-171" are excluded.
4. **Model check.** The best available model decides, and what decided each article is recorded (`classifier`, `relevance_score`, `matched_terms`):
    - **Trained classifier** (`learned`): logistic regression on MiniLM sentence embeddings, trained on our hand-labelled sheet. It keeps an article when P(relevant) ≥ a threshold chosen by cross-validation. Optionally, **SetFit** fine-tunes the embedding model itself (`--method setfit`). CV precision and recall and the rules baseline are saved in `models/relevance/meta.json`.
    - **Prototype classifier** (`rules+semantic` / `semantic`), used until a model is trained: each headline + snippet is compared with ~60 labelled example headlines (`config/prototypes.json`), including near-miss negatives. It can veto keyword matches that mean something else and rescue items the keywords missed.
    - **Rules only** (`rules`) when `sentence-transformers` isn't installed.
5. **Read the article for near-misses** (`enrich`). Headlines often lack context: "Telangana Police deploys C-SIGHT for CSEAM investigations" never says AI. Rejected headlines that name a focus state plus a concrete action (or AI but no government) are decoded, downloaded and reduced to their first ~1,200 characters with trafilatura. That lead is then judged. Leads stay in a local cache and are never republished. We rejected the alternative of calling "CoE", "skilling" or "digital infrastructure" AI words: on the Telangana data it recovered 2 headlines (1 wrong) and would admit every non-AI skilling scheme.

**Statements of intent count.** A CM praising AI infrastructure or saying the state "plans" something signals the state's stance, so it's kept as `statement_intent` rather than dropped. Company investments in a state (AI data centres) count as `budget_funding` (labelled Budget / Funding / Investment) because they are announced with and courted by the state.

**Categories** (headline decides first, then the semantic model, then the snippet): Policy/Mission · Institution/CoE · Partnership/MoU · Procurement/Contract · Governance deployment (+ sector: health, agriculture, policing, education, urban, revenue) · Budget/Funding/Investment · Regulation/Ethics · Statement/Intent.

**Keyword matching is case-insensitive and tolerates typos:**

- "A.I." / "Ai-powered" / "M.o.U" / "center" are all normalised first.
- Words of 6–8 letters match with one missing, extra or swapped letter ("goverment", "minster", "allcoation").
- Words of 9+ letters allow two errors ("artifical inteligence").
- A single *substituted* letter is not accepted, because it makes a different word (policy/police, contract/contrast).

## Normalising states and dates

- **States:** every spelling, short code and metro maps to one ISO 3166-2 code (`config/states.json`): "UP", "Uttar Pradesh" and "Uttar-Pradesh" all become `IN-UP`, and TS and TG both become `IN-TG`. The state is read from the **text**, not from the query that found it.
    - A "New Delhi" dateline or a Union ministry doesn't make an item Delhi.
    - "Centre of excellence" and "AI centre" are not the Union government.
    - Gurugram and Noida are Haryana and UP, not Delhi.
    - The query's state is only a tie-breaker. It's a fallback only for a state's own section feed.
- **Dates:** all converted to an IST calendar date (a 23:30 UTC article is the next day in India). Unknown dates stay **empty** with `date_precision = unknown`. They are never guessed and never filled with the fetch date.

## How duplicates are collapsed

1. **Same article, several routes:** matched on canonical URL (tracking parameters and AMP stripped) **or** on outlet + normalised headline. The second key joins a Google News redirect to the same article from an API or feed, and the real outlet URL is kept (`url_resolved`).
2. **Same event, many outlets:** articles in the same state within **7 days** are linked if any of these holds:
    - they share enough *distinctive* headline words (generic words such as state names, "AI", "signs" and "MoU" are removed and rarer words weigh more);
    - their embeddings are very close (cosine ≥ 0.78);
    - they name the same partner in the same category;
    - they carry the same rupee figure (≥ ₹100 crore) in the same category.

    Links are **vetoed** when the headlines name *different* partners (an MoU with Google ≠ an MoU with Microsoft the same week), and **an event may not span more than 7 days**, which stops A~B~C chaining. The primary source prefers `.gov.in`, then major outlets, then earliest. `source_count` = distinct outlets.

On the first real Telangana fetch (335 Google News items), the ₹70,000 crore TCS AI data centre came from 16 outlets under a dozen different headlines, and collapsed into one event.

## Known holes (on purpose, stated openly)

- **English only.** Gujarati and Marathi outlets sometimes report state deals first. A multilingual embedding model plus regional-language Google News queries is the natural next step.
- **Keyed APIs only see the last 30 days / 48 h** on free tiers. Jan–Aug 2026 comes from Google News and paged outlet feeds.
- **Some links remain Google redirects** (`url_resolved = false`). Decoding uses an unofficial method (`googlenewsdecoder`) that can break.
- **Headline-only classification for older items**, because Google News gives no snippet.
- **Rule and prototype lists need upkeep.** Leader names change after elections.
- **Measured quality:** _fill in from `models/relevance/meta.json` after training_: CV precision / recall of the trained model vs the keyword-rules baseline on the same labelled rows. Labels were drawn half from kept and half from rejected items (including every near-miss), so they over-represent hard cases.
- **Event date = first report date**, not a date pulled from the article text.
- **Unverified formats** (logged and skipped if they fail): The Hindu city feeds, DeshGujarat feeds, GNews / NewsAPI / NewsData response shapes (tested against their documented formats only).
- NewsAPI's free plan is licensed for development only.

## Repository layout

```
config/      states.json (aliases -> ISO codes) · sources.json (per-state source matrix)
             keywords.json (all keyword lists) · prototypes.json (semantic examples + thresholds)
pipeline/    run.py (CLI) · plan.py (ledger, budgets, month slices) · sources/ (one module per source)
             classify.py · semantic.py · learned.py · enrich.py · geo.py · dates.py · dedupe.py
             build.py · export.py · resolve.py
models/      relevance/ (trained classifier head + meta.json with CV metrics)
data/        raw/ (append-only fetch results) · processed/ (outputs) · mock/ (fictional dashboard data)
             reference/ (states, categories) · labels/ (hand-labelled samples) · SCHEMA.md
scripts/     make_labelling_sheet.py · train_classifier.py · sync_dashboard_data.py
             sample_for_labeling.py · eval_labels.py · make_mock_data.py
tests/       offline unit tests + fixtures mirroring live formats
dashboard/   site/   dashboard source and GitHub Pages build
```
