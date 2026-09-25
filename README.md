# AI policy activity across Indian states

This is a small pipeline that reads the news every day, picks out what Indian **state governments** are doing with AI (policies, missions, task forces, MoUs, AI rolled out in hospitals or policing, budget lines, rules on deepfakes, and so on) and shows it on a dashboard.

- **Live dashboard:** https://shreshtha48.github.io/ai-policy-news-india/
- **Dataset:** [`data/processed/events.csv`](data/processed/events.csv) (one row per announcement), plus `articles.csv`, `rejected.csv` and an Excel workbook with all of it. Column definitions: [`data/SCHEMA.md`](data/SCHEMA.md)

This README is mostly about the choices we made and why. How to run it is at the bottom.

## Where it stands (first full run, 25 Sep 2026)

| | |
|---|---|
| Window | 1 Jan 2026 to today |
| Articles collected | 38,416 |
| Rejected, with a reason for each | 13,971 |
| Articles kept | 2,389 |
| **Events after removing duplicates** | **1,266** |
| Events per state | Karnataka 262 · Telangana 242 · Maharashtra 206 · Delhi 190 · Gujarat 144 · Tamil Nadu 123 · Central govt 99 |

The number that matters most isn't in that table: **when we read 30 random events by hand, about 18 were state AI policy activity. That's roughly 60%.** The rest is broader AI news that got through. There's a whole section on that below, and on the classifier we built to fix it.

## What counts as "AI policy activity"

We kept this simple. An article counts if it's **about AI** and **a state government is doing something**: announcing, signing, funding, deploying, regulating, or setting something up.

A few calls we made on purpose:

- **CM statements count.** If a CM praises Gemini's infrastructure or says the state "plans" an AI hub, nothing has happened yet, but it tells you where the state is heading. So we keep it as its own category, `statement_intent`, instead of throwing it away.
- **Company investments in a state count.** A company putting ₹70,000 crore into an AI data centre in Hyderabad is almost always announced alongside the government and courted by it, so it goes under Budget / Funding / Investment.
- **Union government news is kept but separated.** MeitY and the IndiaAI Mission get tagged `IN-CENTRAL`. It's useful context, but it isn't state activity.
- **What we drop:** company-only AI news, markets, gadgets, films, cricket, and the Air India "AI-171" type headlines.

There are 8 categories: Policy/Mission, Institution/CoE, Partnership/MoU, Procurement/Contract, Governance deployment (with a sector such as health, agriculture, policing or education), Budget/Funding/Investment, Regulation/Ethics, and Statement/Intent.

## Which states and why

We went with six instead of trying to cover all 28: **Tamil Nadu, Karnataka, Telangana, Delhi, Gujarat and Maharashtra.** Each has a big tech metro (Chennai, Bengaluru, Hyderabad, Delhi, Ahmedabad/GIFT City, Mumbai/Pune), an active state IT or AI push, and lots of English-language coverage, which is what makes a clean dataset possible. The brief said a few states done well beats all of them done badly, and we agree.

City-level news is only tracked for those metros. A story about Coimbatore just counts for Tamil Nadu.

## Where the news comes from and why

We started out wanting a mix of scraping and APIs, and that's what we ended up with. What we didn't expect is how lopsided it would turn out:

| Source | Articles | Why it's there |
|---|---|---|
| Google News RSS | 21,519 | The backbone. It's free, has an India edition, needs no key, and it's the only source that reaches back to January. |
| Outlet feeds (The Hindu state sections, Telangana Today, DeshGujarat) | 15,520 | Direct regional coverage. Includes one real HTML scraper (Telangana Today's AI tag pages). |
| GDELT | 1,250 | Free second opinion. Noisy and heavily rate-limited. |
| NewsData.io | 60 | Only sees the last 48 hours on the free plan. |
| GNews | 54 | Last 30 days only. |
| NewsAPI.org | 13 | Last month only, and it barely indexes Indian outlets. |

We got keys for all three paid-tier APIs, but on free plans they can't see further back than a month. So we stopped treating them as sources and started treating them as **enrichment**: when an API has the same article as Google News, we take the outlet's real link and its snippet from the API, because Google News gives neither.

Two things made Google News work:

1. **Every query is split by month.** Google News returns at most ~100 results per query, so one "last 12 months" query for Karnataka silently stops somewhere in the summer. Nine monthly slices fix that.
2. **Each state gets a few kinds of queries:** topic queries ("Karnataka AI policy OR mission…"), one per metro, one per leader or state body ("Revanth Reddy AI", "GIFT City AI", "T-Hub AI"), and one limited to that state's own outlets. The leader queries matter more than you'd think, because a lot of headlines never name the state.

Gujarat had the thinnest English coverage, so it gets extra leader and body queries plus DeshGujarat's paged feeds.

To avoid wasting API calls, every request goes through a **call log** (`data/raw/_ledger.json`). A month that has already ended is fetched once and never again, and everything else at most once a day. `--dry-run` shows exactly which calls would be made before you spend anything.

## Getting states and dates right

This is where it's easy to mess up quietly, so we were strict about it.

**States.** Every spelling, short code and metro maps to one ISO code in [`config/states.json`](config/states.json). "UP", "Uttar Pradesh" and "Uttar-Pradesh" all become `IN-UP`; "TS" and "TG" both become `IN-TG`; "Bangalore" becomes `IN-KA`. The state is read from the **article text, not from the search query that found it.** We learned that the hard way:

- **A "Delhi" search returns Union-government stories**, and plenty of other national stories are datelined "New Delhi". So a bare "New Delhi" isn't enough to call something Delhi. It has to be "Delhi govt", "Delhi CM", "Delhi Police" and so on.
- **"Centre" doesn't always mean the Union government.** "CM inaugurates AI centre" got tagged as the Union government because the word "Centre" was on that list. Now "Centre" only counts in phrases like "the Centre" or "Centre to…".
- **Gurugram and Noida are Haryana and UP,** not Delhi.

**Dates.** Everything is converted to an Indian calendar date. A story published at 11:30 pm UTC is the next day in India. If we don't know a date we leave it empty and mark it `unknown`. We never guess one, and we never fill in the day we happened to fetch it.

## Collapsing duplicates

The same announcement shows up in ten outlets under ten different headlines. The ₹70,000 crore TCS data centre in Hyderabad was reported by 34 outlets; on the dashboard it's one event with a count of 34.

We do it in two passes:

1. **Same article seen twice**, through Google News and an API, or on two different days. This is matched on the cleaned-up URL, or on outlet plus headline (because Google's redirect links never match the real URL).
2. **Same event, different articles.** Two articles in the same state within 7 days are joined if any of these hold:
    - they share enough distinctive headline words (generic ones like the state name, "AI", "signs" and "MoU" are ignored);
    - their meaning is very close (sentence embeddings);
    - they name the same partner, e.g. both mention Google;
    - they quote the same rupee figure.

There are two brakes. Headlines naming **different** partners never merge, since an MoU with Google and one with Microsoft in the same week are two events. And an event can't stretch past 7 days, which stops A-looks-like-B-looks-like-C chains from swallowing a month of coverage.

## What went wrong with keyword filtering

We started with keyword rules: an AI word, plus a government word, plus an action word. It's transparent, and every rejection is logged with a reason in `rejected.csv`, which made the problems easy to see. The problems were real, though:

- **Words mean different things.** "AI-171" is an Air India flight. "Startup" nearly matched "StartupTN" (a state body). "Investor" matched "invest". "State-of-the-art" contains "state".
- **Typo tolerance cuts both ways.** We match "goverment", "minster" and "artifical inteligence" on purpose. A one-letter difference is also how "policy" becomes "police" and "contract" becomes "contrast", though, so we only allow missing, extra or swapped letters, never a changed one.
- **Headlines leave out the context.** "Telangana Police deploys C-SIGHT for CSEAM investigations" is an AI tool, but the headline never says so. "Revanth to launch Telangana AI Innovation Hub" was rejected because a CM's name wasn't on the government word list.
- **Adding words backfires.** At one point we considered treating "CoE", "skilling" and "digital infrastructure" as AI words. On the Telangana data that recovered 2 headlines, and 1 of them was wrong, while it would have let in every non-AI skilling scheme in six states. We didn't do it.
- **Order matters.** "Telangana signs ₹5,000 crore MoU with Microsoft" came out as Budget, because budget was checked before partnership. Fixed now.

Every fix above is in the rules now, with a test for each. The bigger lesson, though, is that keywords can't read context, and patching them one case at a time only gets you so far.

## Where the data is noisy right now

After the keyword rules, a small embedding model ([all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)) double-checks each article. It compares the headline with about 60 example headlines we wrote (`config/prototypes.json`) and can overrule the rules either way. In the full run it vetoed 150 articles the rules had kept and rescued 190 the rules had dropped.

Reading 30 random events by hand gave about 18 correct (roughly 60%). The misses fall into a few groups:

- **Rescued, but just general AI news:** "Trump says he plans to form 'AI Force'", "Two IIT Delhi grads built and sold an AI startup". The embedding model's rescues are mostly noise, and that's the weakest part of the pipeline right now.
- **Right topic, wrong actor:** "AI-driven political campaigns heat up Tamil Nadu election", "Delhi HC protects Yuvraj Singh's personality rights against deepfakes". AI and a state are both involved, but it isn't the state government acting.
- **National events tagged as Delhi:** the AI Impact Summit was held in New Delhi, so its coverage lands on Delhi. Delhi's 190 events are inflated by this.
- **One possible over-merge:** the biggest Gujarat event (39 outlets) is a World Bank meeting that seems to have pulled in unrelated Gujarat coverage from the same week.

This is why we built a trained classifier.

## The classifier: what it's for and how it trains

**What it's for.** It replaces our guesswork with a model that learns from real examples of what we mean. The keyword rules and the 60 hand-written examples encode our guesses about what "state AI policy" looks like. The classifier learns it from articles we've actually labelled, including the awkward cases above (election campaigns, court rulings, national summits, startup stories), which are hard to write rules for but easy to label.

**How it trains:**

1. `scripts/make_labelling_sheet.py` builds a sheet of about 200 articles: half from what the pipeline currently keeps, half from what it rejects, plus every near-miss. It's weighted towards hard cases on purpose.
2. We label each row 1 (state AI policy activity) or 0. There's a `suggested` column showing the current decision, as a check, not something to copy.
3. `scripts/train_classifier.py` turns each headline and snippet into an embedding with the same MiniLM model. It then trains a logistic regression on top: a few KB, committed to git, and fast enough for the daily GitHub run. It uses 5-fold cross-validation to pick the probability cut-off with the best F1, reports precision and recall, and compares them with the current rules on the same rows. Everything goes into `models/relevance/meta.json`.
4. There's also a `--method setfit` option ([SetFit](https://github.com/huggingface/setfit)), which fine-tunes the embedding model itself and usually does better with few labels. It saves a ~90 MB model, though, so it's kept out of git and the daily GitHub run can't use it.

Once `models/relevance/` exists, the pipeline uses it automatically, and each article records which classifier kept it (`classifier` column) and its score.

**Where it stands:** built and tested, **not trained yet.** We shipped the MVP first. Labelling ~200 rows takes about 40 minutes, and it's the next thing to do. We expect it to cut most of the noise above, especially the "right topic, wrong actor" group, and the README will get the measured precision and recall once it's done.

There's one more fix aimed at the same problem: **reading the article for near-misses** (`python -m pipeline.run enrich`). For rejected headlines that name a state and an action but no AI word, like the C-SIGHT one, we fetch the first ~1,200 characters of the article and judge again. That text stays in a local cache and is never republished.

## Other known holes

- **English only.** Gujarati and Marathi outlets sometimes break state deals first.
- **Most links are still Google redirects.** Only 158 of 1,266 events have the outlet's own URL so far. The redirects work in a browser but aren't clean. `python -m pipeline.run resolve` decodes them 50 at a time using an unofficial method that can break.
- **Some Google News months hit the ~100-result cap** for the busiest queries (for example Hyderabad). Splitting those months in half is the obvious next step.
- **Event date is the first report date,** not a date pulled from the article text.
- **Some feeds weren't checked against the live site before the first run:** The Hindu city feeds and DeshGujarat. They fail quietly if they break, and it shows in the logs.
- **NewsAPI's free plan is licensed for development only.**
- **Leader names change after elections,** so the lists in `config/keywords.json` need upkeep.

## Running it

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt                 # includes the embedding model library (~300 MB with PyTorch)
python -m unittest discover -s tests -t .       # 41 offline tests

# API keys go in .env (git-ignored): GNEWS_API_KEY, NEWS_API_KEY, NEWSDATA_API_KEY - all optional
python -m pipeline.run fetch --dry-run          # see the planned calls, spends nothing
python -m pipeline.run all                      # fetch -> process -> resolve links -> read near-misses -> process
```

Dashboard: `cd dashboard`, `npm install`, then `npm run dev` (it reads the CSVs that `process` copies into `dashboard/public/data/`).

Every day at 06:00 IST, a GitHub Action (`.github/workflows/pipeline.yml`) runs the pipeline, commits the new data and redeploys the dashboard. Pushing changes to the dashboard redeploys it too.

(Please note: A significant portion of this readme is created using LLM and so is the dashboard logic for this repo, the script logics have been human verified and  readme also had been scanned for errors)

## Repo map

```
config/      states.json (spellings -> ISO codes) · sources.json (what we query per state)
             keywords.json (all keyword lists) · prototypes.json (example headlines for the embedding check)
pipeline/    run.py (commands) · plan.py (call log, budgets, month slices) · sources/ (one file per source)
             geo.py · dates.py · classify.py · semantic.py · learned.py · enrich.py · dedupe.py · build.py
data/        raw/ (everything fetched) · processed/ (outputs) · labels/ (hand labels) · reference/ · mock/
scripts/     make_labelling_sheet.py · train_classifier.py · sync_dashboard_data.py · eval_labels.py
dashboard/   the dashboard (Vite + TypeScript); built into site/ by the GitHub Action
tests/       offline tests, with fixtures copied from the real response formats
```
