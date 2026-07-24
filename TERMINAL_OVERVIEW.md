# Equity Research Terminal — Overview

A single-operator equity research terminal for large-cap pharma. One refresh pulls live
and near-live data for a fixed universe of companies, stores a timestamped snapshot,
computes what changed since the last snapshot, and renders charts plus a short written
note per company.

The differentiator is **change detection and synthesis over free data sources**, not raw
data breadth. Every refresh writes history, so over months the app accumulates a
proprietary time series of how each company's pipeline, filings, and exclusivity moved,
which cannot be bought after the fact.

---

## The universe

18 large-cap pharma names, fixed:

`LLY  NVO  MRK  PFE  ABBV  JNJ  AZN  GSK  NVS  ROG  SNY  BMY  AMGN  GILD  VRTX  REGN  BIIB  BAYN`

Notes on coverage:
- Most file with the SEC (10-K / 8-K). European names (AZN, GSK, NVO, SNY) file 20-F / 6-K.
- **Roche (ROG) and Bayer (BAYN) are not SEC registrants at all**, so EDGAR holds no
  financials for them; the UI says so rather than inventing numbers.
- Loss-of-exclusivity data is **US only** (FDA Orange Book and Purple Book). A product
  protected in the US to 2035 can face a generic in Europe years earlier, and no free
  source publishes those foreign dates.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLite (via `sqlite3`) |
| Frontend | Streamlit + Altair, plus hand-built SVG panels |
| Jobs | Plain async functions triggered by the refresh endpoint (no queue) |
| LLM | Provider-agnostic seam over Groq / Gemini / Anthropic, used only for the notes and PDUFA extraction |

The frontend is Streamlit rather than the originally-planned React + Vite. Several
panels (the price rail, the growth-vs-margin trend, the revenue-mix donut, the catalyst
calendar) are built as **hand-written SVG** to dodge a Streamlit defect where a chart
rendered inside a hidden tab is measured at a few pixels and collapses.

---

## Architecture and data flow

```
  ┌─────────────┐   refresh    ┌──────────────┐   snapshot   ┌───────────┐
  │  fetchers/  │ ───────────► │ current-state│ ───────────► │ snapshots │
  │ (per source)│              │   tables     │              │  (JSON)   │
  └─────────────┘              └──────────────┘              └─────┬─────┘
                                      │                            │ diff
                                      ▼                            ▼
                               ┌──────────────┐              ┌───────────┐
                               │  FastAPI     │ ◄─────────── │  changes  │
                               │  endpoints   │              └───────────┘
                               └──────┬───────┘
                                      │ JSON
                                      ▼
                               ┌──────────────┐
                               │  Streamlit   │  tabs + right-hand horizon rail
                               └──────────────┘
```

Backend and frontend run as two processes:
- API: `uvicorn main:app` on port 8000
- UI: `streamlit run frontend/streamlit_app.py` on port 8501, which reads the API

---

## Core concepts

1. **The unit of analysis is the asset-indication pair, not the company.** A drug in three
   indications is three rows in `asset_indications`, each with its own phase and catalyst.
   Every pipeline view builds off this.

2. **Snapshots are the product.** On every refresh, the tracked fields of each entity are
   written to `snapshots` as JSON. The diff between the last two snapshots of an entity
   produces rows in `changes`. History is never overwritten.

3. **Freshness is per source.** Prices expire in 15 minutes; trials, filings, and
   approvals refresh daily; Orange Book and Purple Book refresh weekly. A fetch inside its
   TTL is skipped, but a snapshot is written on every refresh so the change history has no
   gaps.

4. **Never fabricate a value.** If a source has no data for a field, the app stores null
   and the UI shows "no free data" rather than an estimate. This rule is absolute.

---

## Data sources

| Source | Provides | Cadence |
|---|---|---|
| **SEC EDGAR** (companyfacts XBRL) | Reported financials: revenue, net income, R&D | Daily |
| **SEC EDGAR** (submissions) | Recent filings, 8-K / 6-K material-event monitoring | Daily |
| **SEC Financial Statement Data Sets** | Per-product revenue (keeps the segment dimension the XBRL API collapses) | Quarterly |
| **ClinicalTrials.gov v2** | Trials: phase, status, primary completion date, enrolment, conditions | Daily |
| **openFDA** (drugsfda) | FDA approvals, queried by both manufacturer and sponsor to catch acquired subsidiaries | Daily |
| **FDA Orange Book** | Small-molecule patents and exclusivity | Weekly |
| **FDA Purple Book** | Biologic regulatory exclusivity (no patents; US only) | Weekly |
| **yfinance** | Prices and intraday, wrapped in retries; failures are a soft reported error | On demand (15-min TTL) |
| **RSS** | Company news headlines | Daily |

All EDGAR requests send a real `User-Agent` and stay under the rate limit. CIKs are
resolved once from the official ticker-to-CIK map, never hand-keyed.

---

## What the UI shows (tabs)

A company selector at top drives every tab. A persistent **Horizon rail** on the right
shows, for the selected company: catalysts in the next 90 days (day scale), the 3-to-24
month window (month scale), and the exclusivity cliff beyond 24 months (per year).

| Tab | Contents |
|---|---|
| **Key insights** | Headline stats, an intraday sparkline, and the AI **morning note** synthesising the change feed, with a rules-only fallback |
| **Prices** | Interactive close chart with drag-to-zoom, window buttons that re-scale five years of stored daily closes |
| **Financials** | Three statements (income, balance, cash flow) on a quarterly or annual basis, a live snapshot strip, and a **growth-against-margin** panel showing the most recent year, each series on its own scale |
| **Pipeline** | Therapeutic-area bar chart; click an area and a phase to list the trials, each row clickable for its full description and linked to ClinicalTrials.gov |
| **LOE** | Per-company exclusivity cliff by year (orphan exclusivity excluded, since it does not gate competitors), plus an upcoming-expiry table with the protection basis |
| **Approvals** | FDA approvals with modality, application number, exclusivity expiry, and per-product revenue |
| **Catalysts** | A month calendar of one company's upcoming readouts and PDUFA dates |
| **Comps** | Cross-sectional table of the 18 companies, a phase matrix, and the revenue-mix donut |
| **News** | Recent headlines from company RSS |

---

## The change engine (snapshot → diff → changes → feed → note)

- **`diff.py`** compares the last two snapshots of each tracked entity and writes typed
  rows to `changes`: trial status changes, primary-completion-date slips, new filings, new
  approvals, phase advances.
- **`whatchanged.py`** merges recent changes, upcoming catalysts (inside 60 days), and
  near-term loss of exclusivity into one feed, ranked by significance then date.
- **`insights.py`** is a two-layer note system. `build_rules_note` is always available and
  needs no key: it groups the flagged feed into a plain briefing. `generate_note` upgrades
  that to written prose through whichever LLM provider has a key, and falls back to the
  rules note if the model errors or no key is set. Every note stores the ids of the
  changes that produced it, so it is always traceable to its evidence.

### Catalysts

- No free PDUFA calendar exists, so PDUFA dates are **auto-extracted from 8-K / 6-K
  filings** by the LLM when a filing reports FDA acceptance, written with `is_curated = 0`
  for review rather than hand-entered.
- Data readouts are **derived** from trial primary-completion dates: Phase 3 always, plus
  **notable Phase 2 / Phase 2/3** trials (enrolment ≥ 150, the median of the eligible
  Phase 2 studies, which keeps the well-powered efficacy readouts and drops the small
  dose-finding tail). Derivation is idempotent; a moving date shows up as a change.

---

## The LLM layer

`llm.py` is a provider seam. Selection is explicit (`LLM_PROVIDER`) or automatic, in order
**Groq → Gemini → Anthropic**, picking the first key present. Groq and Gemini are called
over their REST endpoints with `urllib` (no SDK needed); Anthropic keeps its SDK. The key
rides in a header, never the URL.

- The app **functions fully without any key**, degrading to rules-only output.
- The current free provider is **Groq (Llama 3.3 70B)**. A deterministic house-style pass
  fixes the model's grammar: it strips filler sentence-openers and capitalises sentence
  and line starts, so the note reads as prose even when the model returns lower case.

House style for generated text: sentence-case headings, no em dashes, lead with the
number, and banned words (`additionally, highlight, underscore, pivotal, showcase,
testament`).

---

## API endpoints

```
GET  /health
GET  /companies
GET  /companies/{ticker}/prices
GET  /companies/{ticker}/intraday
GET  /companies/{ticker}/financials
GET  /companies/{ticker}/statements
GET  /comps
GET  /pipeline
GET  /companies/{ticker}/trials
GET  /loe
GET  /companies/{ticker}/exclusivities
GET  /companies/{ticker}/approvals
GET  /companies/{ticker}/revenue      POST to override a figure
GET  /companies/{ticker}/exposure
GET  /changes
GET  /companies/{ticker}/note
GET  /companies/{ticker}/filings
GET  /companies/{ticker}/news
GET  /catalysts                        POST to add; POST /{id}/accept to curate
POST /refresh                          ?scope=all or a single company
```

---

## Database (SQLite)

Current-state and history tables:

- **Reference**: `companies`, `assets`, `indications`, `asset_indications`,
  `asset_economics`, `valuation_assumptions`
- **Market and financials**: `prices`, `financials`, `consensus_estimates`,
  `asset_revenue`
- **Pipeline and regulatory**: `trials`, `trial_asset_map`, `approvals`, `exclusivities`,
  `catalysts`
- **Filings and news**: `filings`, `news`
- **Change engine**: `refresh_runs`, `snapshots`, `changes`, `insights`

---

## Running it

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import db; db.init()"          # create SQLite from schema.sql
uvicorn main:app --reload                 # port 8000

# frontend
cd frontend
streamlit run streamlit_app.py            # port 8501

# trigger a refresh
curl -X POST localhost:8000/refresh
```

Secrets live in `.env` at the repo root (gitignored). The core app needs none. Optional:
`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `FMP_API_KEY`, `OPENFDA_API_KEY`,
`SEC_USER_AGENT`.

---

## Testing

Around 250 tests, one command from `backend/`:

```bash
cd backend && python -m pytest tests/ -q
```

Every parser has a unit test backed by a saved sample payload in `tests/fixtures/`,
because EDGAR and ClinicalTrials payloads are messy and drift; the tests catch that. When
a real payload differs from the notes, trust the payload, update the fetcher, and update
the fixture.

---

## Design principles

- **Never fabricate a value.** Null over estimate, "no free data" over a guess.
- **Snapshot before mutating current-state tables**, so a diff is always possible.
- **No paid subscriptions and no scraping behind logins.** Every source has a free route.
- **Small commits, one concern each**, conventional commit messages.
- **The UI states its own caveats**: US-only LOE dates, partial biologic coverage, orphan
  exclusivity is not a cliff, and a dash means no free data rather than zero.

---

## Known limitations

- Loss-of-exclusivity dates are **US only**; foreign generic entry can be years earlier.
- Biologic coverage (Purple Book) is partial and carries no patents, only regulatory
  exclusivity.
- Prices come from yfinance, which is unofficial and can rate-limit; failures are reported
  softly rather than crashing.
- Roche and Bayer have no SEC financials in the app (they are not SEC registrants).
- Trial-to-asset mapping is imperfect; an override table (`trial_asset_map`) exists for
  misses.
- The generated note runs on a small free model by default, so it can add mild editorial
  phrasing; the facts come only from the supplied feed.
