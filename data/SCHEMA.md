# Data schema (contract between pipeline and dashboard)

The dashboard reads CSVs only. The mock files in `data/mock/` use **exactly** the
same columns the real pipeline will write to `data/processed/`, so switching
from mock to real is a path change.

> MOCK DATA IS FICTIONAL. Sources are "Mock ..." and URLs point to example.com.
> Regenerate with `python scripts/make_mock_data.py` (deterministic).

## Files

| File | Grain | Used for |
|---|---|---|
| `events_mock.csv` | 1 row = 1 **deduplicated event** | Main table, all charts, counts |
| `articles_mock.csv` | 1 row = 1 **news article** (many per event) | "Covered by N sources" drill-down |
| `reference/states.csv` | 1 row per state code | Display names, filters, map join |
| `reference/categories.csv` | 1 row per category | Labels, legend, tooltips |

Join: `articles.event_id -> events.event_id`; `events.state_code -> states.state_code`;
`events.category -> categories.category`.

**Count events, not articles.** One announcement covered by 9 outlets is 1 event
with `source_count = 9`.

## events_mock.csv

| Column | Type | Rules |
|---|---|---|
| `event_id` | string | `EVT-0001`. Stable primary key |
| `state_code` | enum | ISO 3166-2: `IN-TN IN-KA IN-TG IN-DL IN-GJ IN-MH`, plus `IN-CENTRAL` for Union govt. Always use the code, never free text |
| `state_name` | string | Display name, derived from code |
| `city` | string, nullable | **Only** for metros (Chennai, Bengaluru, Hyderabad, Delhi, Mumbai, Pune, Ahmedabad). Empty otherwise |
| `category` | enum | `policy_mission institution partnership governance_deployment budget_funding regulation_ethics` |
| `sector` | enum, nullable | `health agriculture policing education urban revenue`. Mainly for `governance_deployment` |
| `title` | string | Canonical headline (from primary source) |
| `summary` | string | One line |
| `event_date` | ISO date, nullable | When it happened. **Empty when unknown**, never guessed |
| `date_precision` | enum | `day` = exact; `month` = only month known (`event_date` is the 1st, display as "Mar 2026"); `unknown` = `event_date` empty |
| `first_reported_date` | ISO date, always set | Earliest article date. **Use this for timelines** because it's never empty |
| `primary_source_name` | string | Outlet of the chosen primary article |
| `primary_source_url` | URL | Link to show on the card/table |
| `source_count` | int >= 1 | Number of distinct articles merged into this event, a proxy for significance |
| `actors` | string, `; `-separated | Govt bodies/partners involved |
| `amount_inr_crore` | number, nullable | Only for money announcements (mostly `budget_funding`) |

## articles_mock.csv

| Column | Type | Rules |
|---|---|---|
| `article_id` | string | `ART-00001` |
| `event_id` | string | FK to events |
| `state_code` | enum | Same as event |
| `title` | string | As published (outlets reword, which is why dedupe exists) |
| `source_name`, `source_url` | string | |
| `published_date` | ISO date | |
| `fetched_via` | enum | `google_news_rss gdelt gnews` |
| `is_primary` | bool | `true` for the one article chosen as the event's primary |

## Dashboard notes

- Default: exclude `IN-CENTRAL` from state comparisons (toggle to show it).
- Handle empty `city`, `sector`, `event_date` and `amount_inr_crore` without breaking.
- Suggested views: events per state (bar), per state x category (heatmap),
  over time by `first_reported_date` (monthly), a filterable event table linking
  to `primary_source_url`, and a drill-down listing the articles for an event.
