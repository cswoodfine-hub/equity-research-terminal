# CLAUDE.md

## What this is

An equity research terminal for large-cap pharma. One refresh action pulls live and near-live data for a fixed universe of companies, stores a timestamped snapshot, computes what changed since the last snapshot, and renders charts plus a short written note per company. The differentiator is change detection and synthesis over free data sources, not raw data breadth.

## Tech stack

- Backend: Python 3.11+, FastAPI, SQLite via `sqlite3` or SQLAlchemy Core. DuckDB is an acceptable swap for the snapshot and analytical tables; keep SQL portable.
- Frontend: React + Vite + TypeScript, Recharts for charts, TanStack Query for data fetching.
- Jobs: plain async functions triggered by the refresh endpoint. No Celery or queue in v1.
- LLM: the Anthropic API for the generated-notes step only. The app must function without it and degrade to rules-only output when no key is present.

Fast path: if the frontend slows you down, build the whole thing in Streamlit first and port later. The backend, schema, and fetchers stay identical.

## Repo structure

```
equity-research/
  CLAUDE.md
  README.md
  .env.example
  backend/
    main.py                 # FastAPI app, routes
    db.py                   # connection, schema init
    schema.sql
    refresh.py              # orchestrates fetchers, writes refresh_runs
    diff.py                 # snapshot -> changes engine
    insights.py             # rules layer + Anthropic note generation
    fetchers/
      base.py               # Fetcher protocol, RefreshResult
      prices.py
      financials_edgar.py
      filings_edgar.py
      trials_ctgov.py
      approvals_openfda.py
      exclusivity_orangebook.py
      catalysts.py          # curated CRUD + auto extraction
      news_rss.py
    tests/
      fixtures/             # saved sample payloads
      test_*.py
  frontend/
    src/
      api/
      components/
      views/                # PipelineHeatmap, LoeCliff, CatalystCalendar, Comps, WhatChanged
      App.tsx
  data/
    companies_seed.csv
  docs/
    PRD.md
```

## Core concepts (read before writing code)

1. The unit of analysis is the asset-indication pair, not the company. A drug in three indications is three rows in `asset_indications`, each with its own phase and catalyst. Every pipeline view builds off this table.
2. Snapshots are the product. On every refresh, write the tracked fields of each entity to `snapshots` as JSON. The diff between the last two snapshots of an entity produces rows in `changes`. Over months this becomes a proprietary time series you cannot buy. Never overwrite history.
3. Freshness is per source. Prices refresh on demand and expire in 15 minutes. Trials, filings, and approvals refresh daily. Orange Book and Purple Book refresh weekly. Store last-fetched per source and skip fetches inside the TTL. Write snapshots on every refresh regardless, so the change history has no gaps.

## Data source rules

Confirm every endpoint against its live docs before relying on it. The specifics below can drift.

### SEC EDGAR (financials, filings)

- Send a real `User-Agent` on every request, for example `Novatalis Research contact@example.com`. Requests without it are blocked.
- Stay under 10 requests per second. Sleep between calls.
- Resolve CIKs once from `https://www.sec.gov/files/company_tickers.json`, the official ticker-to-CIK map. Do not hand-key CIKs.
- Reported financials: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`, cik zero-padded to 10 digits. Pull us-gaap tags Revenues, NetIncomeLoss, ResearchAndDevelopmentExpense, and IFRS tags for foreign filers.
- Recent filings: `https://data.sec.gov/submissions/CIK{cik}.json` returns the recent filings list with form types, accession numbers, and dates. Use this for the filings table and 8-K / 6-K monitoring.
- European filers submit 20-F and 6-K, not 10-K and 8-K. Handle both. Roche and Bayer are not SEC registrants at all; their financials come from IR, not EDGAR (see the seed CSV `is_sec_filer` flag).

### ClinicalTrials.gov (pipeline)

- API v2 base: `https://clinicaltrials.gov/api/v2/studies`. Query by sponsor with `query.spons`, select fields with `fields=`, page with `pageSize` and `pageToken`.
- Store nct_id, phase, overallStatus, primaryCompletionDate, lastUpdatePosted. A change in overallStatus or a slip in primaryCompletionDate is a real signal; the diff engine must track both.
- Mapping trials to assets is the hard part. Match on intervention name against asset generic, brand, and code. Keep the `trial_asset_map` override table for misses.

### openFDA (approvals, labels, safety)

- Endpoints under `https://api.fda.gov/drug/` (drugsfda, label, event). A free key raises the limit to about 1000 requests per minute; register and set `OPENFDA_API_KEY`.

### Prices and estimates

- yfinance is free but unofficial and can break or get rate-limited without warning. Wrap it in retries and treat failures as a soft, reported error, not a crash.
- FMP's paid tier is the stable fallback for quotes and the one genuinely useful cheap dataset, consensus EPS and revenue. Everything else has a free route.

### LOE and patents

- FDA Orange Book (small molecules) and Purple Book (biologics) publish downloadable data files with exclusivity and expiry dates. Download and refresh weekly. These power the LOE cliff chart.

### Catalysts

- No free PDUFA calendar API exists. Catalysts are a curated table edited in the UI. Supplement with extraction: when a new 8-K or 6-K reports FDA acceptance of a filing, call the Anthropic API to pull the PDUFA date and write a catalyst row with `is_curated = 0` for review.

## Fetcher contract

Every source implements the same interface.

```python
from typing import Protocol

class RefreshResult:
    source: str
    rows_fetched: int
    errors: list[str]
    skipped_ttl: bool
    elapsed_ms: int

class Fetcher(Protocol):
    source: str
    ttl_seconds: int

    def fetch(self) -> list[dict]: ...          # raw payload from the source
    def normalise(self, raw: list[dict]) -> list[dict]: ...  # to table shape
    def snapshot(self, rows: list[dict]) -> None: ...        # write to snapshots
    def upsert(self, rows: list[dict]) -> RefreshResult: ... # update current-state tables
```

## Conventions

- One fetcher module per source under `backend/fetchers/`. No cross-imports between fetchers.
- Every parser has a unit test with a saved sample payload in `tests/fixtures/`. EDGAR and ClinicalTrials payloads are messy and change; tests catch drift.
- Never fabricate a value. If a source has no data for a field, store null and let the UI show "no free data" rather than an estimate. This rule is absolute.
- Secrets live in `.env` and are never committed. Core needs none. Optional: `ANTHROPIC_API_KEY`, `FMP_API_KEY`, `OPENFDA_API_KEY`, `SEC_USER_AGENT`.
- Small commits, one concern each. Conventional commit messages.

## Running

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import db; db.init()"          # creates SQLite from schema.sql
uvicorn main:app --reload

# frontend
cd frontend
npm install
npm run dev

# trigger a refresh
curl -X POST localhost:8000/refresh
```

## Rules for you, Claude Code

- Work one build phase per session (see `docs/PRD.md`). Use plan mode, get the plan agreed, then implement.
- Snapshot before you mutate current-state tables, so a diff is always possible.
- When a source's real payload differs from these notes, trust the payload, update the fetcher, and update the fixture. Report the discrepancy in your summary.
- Do not add data sources that need paid subscriptions or scraping behind logins.

## House style for generated text and UI copy

Applies to the note-generation prompt and any UI microcopy.

- Sentence-case headings.
- No em dashes.
- Banned words: additionally, highlight, underscore, pivotal, showcase, testament.
- Direct and unhedged. Specific over abstract. Lead with the number or the change.
