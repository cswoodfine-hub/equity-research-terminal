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
    loe.py                  # effective LOE: molecule patent over longest listed
    product_areas.py        # a product's disease area, from its label
    asset_merge.py          # fold a derived compound into the product it is
    brand_split.py          # route a study to the brand whose label covers it
    trial_mapping.py        # interventions -> assets, pipeline asset derivation
    payer_access.py         # Part D prescribing, plan coverage, Medicaid: display only
    fetchers/
      base.py               # Fetcher protocol, RefreshResult
      prices.py
      financials_edgar.py
      filings_edgar.py
      trials_ctgov.py       # active studies: the pipeline
      trials_completed.py   # completed studies with results: the record
      approvals_openfda.py
      exclusivity_orangebook.py
      catalysts.py          # curated CRUD + auto extraction
      deals_news.py         # business development from headlines
      news_rss.py
      codes_rxnav.py        # RxCUIs and NDC product codes per marketed asset
      prescribers_cms.py    # Medicare Part D Prescribers, per brand
      utilization_medicaid.py  # Medicaid State Drug Utilization Data, national rows
      formulary_cms.py      # Part D formulary, read from the ZIP by HTTP Range
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
3. Migrations run once. ``db.init()`` records every applied file in
   ``schema_migrations``, so a migration may change shape or data exactly once. That is
   what makes ``ALTER TABLE`` usable, since SQLite has no ``IF NOT EXISTS`` for it.
4. Freshness is per source. Prices refresh on demand and expire in 15 minutes. Trials, filings, and approvals refresh daily. Orange Book and Purple Book refresh weekly. Store last-fetched per source and skip fetches inside the TTL. Write snapshots on every refresh regardless, so the change history has no gaps.

## Data source rules

Confirm every endpoint against its live docs before relying on it. The specifics below can drift.

### SEC EDGAR (financials, filings)

- Send a real `User-Agent` on every request, for example `Novatalis Research contact@example.com`. Requests without it are blocked.
- Stay under 10 requests per second. Sleep between calls.
- Resolve CIKs once from `https://www.sec.gov/files/company_tickers.json`, the official ticker-to-CIK map. Do not hand-key CIKs.
- Reported financials: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`, cik zero-padded to 10 digits. Pull us-gaap tags Revenues, NetIncomeLoss, ResearchAndDevelopmentExpense, and IFRS tags for foreign filers.
- Recent filings: `https://data.sec.gov/submissions/CIK{cik}.json` returns the recent filings list with form types, accession numbers, and dates. Use this for the filings table and 8-K / 6-K monitoring.
- European filers submit 20-F and 6-K, not 10-K and 8-K. Handle both. Roche and Bayer are not SEC registrants at all (see the seed CSV `is_sec_filer` flag). Both publish a workbook of their own and that is the route (`fetchers/financials_ir.py`): Roche's Finance Information Tool, read by `roche.py`, and every table of Bayer's online annual report, read by `bayer.py`.

### ESEF (financials for an EU filer outside the SEC)

- EU-listed companies file their annual report in the European Single Electronic Format: inline XBRL in the `ifrs-full` taxonomy, the one IFRS 20-F filers use. filings.xbrl.org indexes the reports and serves each as xBRL-JSON: `https://filings.xbrl.org/api/filings?filter[entity.identifier]={LEI}&include=entity`, then each filing's `json_url`.
- Keyed by LEI, carried on the seed CSV and check-digit validated on load. Annual reports only, from fiscal 2020 (with the 2019 comparative). Facts are converted to the company-facts shape and parsed by `companyfacts.py`, the same parser EDGAR data uses.
- The index carries no German filer (none for country DE on 2026-09-25), so it cannot reach Bayer, which reads its annual report workbook instead. The route stands for an EU filer the index does carry and that publishes no workbook.

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

### Deals

- Filings name a counterparty only when the deal is material enough to require it, which
  catches acquisitions and misses licensing. Google News RSS
  (`https://news.google.com/rss/search`) is free and keyless and carries the rest.
  Extraction is rules-only: a deal is taken only when a headline states one plainly, and
  the headline is stored verbatim as the quote.
- A deal value is announced consideration, milestones included. It is never the cash in
  the cash flow statement, which is why the column is `announced_value`.

### Orange Book patents

- Each listed patent is flagged drug substance, drug product, or neither, with a use code
  when it claims a method of use. The molecule patent gates a generic; a method-of-use
  patent covers one indication and can be carved out of a generic label. Store the flags
  and let the substance patent set the LOE.

### Catalysts

- No free PDUFA calendar API exists. Catalysts are a curated table edited in the UI. Supplement with extraction: when a new 8-K or 6-K reports FDA acceptance of a filing, call the Anthropic API to pull the PDUFA date and write a catalyst row with `is_curated = 0` for review.

### RxNav (drug codes for the payer files)

- `https://rxnav.nlm.nih.gov/REST/`: keyless. `rxcui.json?idtype=NDA|BLA|ANDA&id=` by
  the prefixed application number, plus the brand concept (`rxcui.json?name=&search=2`,
  kept only when `tty` is BN and the name is the brand, then `related.json?tty=SBD+BPCK`).
  NDC history from `allhistoricalndcs`. Only SBD and BPCK codes are brand-specific;
  an unbranded concept keeps only the active NDCs filed under the asset's own application.
- Terms: at most 20 requests per second per IP (the fetcher paces 10), results cached
  12 to 24 hours (the guard re-looks an asset after 30 days or when its application
  numbers change), and NLM's attribution statement on every view built on it. The
  statement is `fetchers.codes_rxnav.ATTRIBUTION`; the fact profile's byline carries it.

### CMS Part D Prescribers and the Part D formulary (data.cms.gov)

- Keyless, US government works. Resolve each dataset's id from
  `https://data.cms.gov/data.json` by title, never hand-keyed; the catalogue is 17.7 MB,
  so it is cached on disk for 7 days (`backend/cms_catalogue.py`).
- Prescribers: `https://data.cms.gov/data-api/v1/dataset/{uuid}/data`, `size` at most
  5000, `column=` to select, `filter[col]=` exact and case-insensitive, `/data/stats` for
  `found_rows` and `total_rows`. Read the Geography and Drug national rows for every year
  from 2020 and the Provider and Drug file for the newest year only, reduced in memory: no
  NPI or prescriber name is stored. A new year is noticed by a change in the series'
  `total_rows`, one stats call a run. The provider file leaves out any NPI and drug with
  fewer than 11 claims, so its figures describe that file population and say so;
  `Tot_Benes` is blank under 11. Volume deciles stay null until CMS says whether its
  national prescriber count includes prescribers under 11 claims.
- Formulary: the monthly "Prescription Drug Plan Formulary and Pharmacy Network
  Information" ZIP (2.3 GB). Read only five small members by HTTP Range requests (about
  9 MB): the basic formulary, plan information and beneficiary cost files are parsed, the
  excluded drugs and indication based coverage files only counted. A server that answers
  a range with the whole file is refused before its body is read. A release already in
  `partd_formulary_releases` is never read again. From October the file describes the
  next contract year, so label by `CONTRACT_YEAR`, never by the release month. The
  Agreement for Use is a disclaimer, not a login: present the data accurately.
- Labelling: every view says "Medicare Part D only" with its year or release. The
  formulary excludes employer, PACE and demonstration plans, counts formularies and plans
  rather than people, and a plan's tiers are its own. Part D cost is gross of rebates and
  is never revenue. The Prescribers patient count and the Spending by Drug one differ
  (Eliquis 2024: 4,423,497 and 4,424,796) and are never put in one figure.

### Medicaid State Drug Utilization Data (data.medicaid.gov)

- Keyless, US public domain. Each year is its own dataset: find the ids by title
  (`State Drug Utilization Data YYYY`) in
  `https://data.medicaid.gov/api/1/metastore/schemas/dataset/items`, then query
  `https://data.medicaid.gov/api/1/datastore/query/{id}/0` with `state = 'XX'` (the
  national rows), at most 8000 rows a page, sorted on ndc, quarter and utilization type.
  `properties[]` column selection is ignored.
- Hold the two newest full years (a year is full when national fourth-quarter rows
  exist). A year is read again only when its dataset id or modified date moves.
- Amounts are before Medicaid rebates, so the figures are volume, never revenue, and every
  view says "Medicaid only, before rebates". CMS suppresses small package rows and the
  dictionary gives no threshold: never write one. A product code is matched through
  `drug_codes` at read time, and a code CMS lists under another drug's name in months
  RxNorm does not list it for the brand is left out.

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
- Do not add data sources that need a paid subscription.
- A source that needs a login is allowed. It is not free in the way a registry is, so it
  carries conditions: the session belongs to a throwaway account rather than a personal
  one, credentials live in `.env` and never in the repo or the database, the fetcher
  reports a soft error rather than crashing when the session expires, and any view built
  on one says so. Expect these to break more often than the registries and to break
  silently. A cookie is a session, not an API, and the account carrying it can be
  rate-limited or closed by the platform.

## House style for generated text and UI copy

Applies to the note-generation prompt and any UI microcopy.

- Sentence-case headings.
- No em dashes.
- Banned words: additionally, highlight, underscore, pivotal, showcase, testament.
- Direct and unhedged. Specific over abstract. Lead with the number or the change.
