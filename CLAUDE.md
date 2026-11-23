# CLAUDE.md

## What this is

An equity research terminal for biopharma: large-cap pharma, biotech, and cell and gene. One refresh action pulls live and near-live data for a fixed universe of companies (`data/companies_seed.csv`), stores a timestamped snapshot, computes what changed since the last snapshot, and renders charts plus a short written note per company. On top of that sits a valuation: each asset forecast from patients and price to risk-adjusted value (`forecast.py`), from curated assumptions (`data/assumptions/`), and each company read as a range across lenses (`fair_value.py`). The universe is read on three engines: big pharma, biotech, and cell and gene (`engines.py`). The differentiator is change detection and synthesis over free data sources, not raw data breadth.

## Tech stack

- Backend: Python 3.11+, FastAPI, SQLite via `sqlite3`. Keep SQL portable.
- Frontend: Streamlit (`frontend/streamlit_app.py`), a thin client over the JSON API. Every chart is hand-built SVG from `frontend/components/charts.py`; there are no native Streamlit or Altair charts. A few views are iframe components under `frontend/components/`; the largest, the Comps frame (`compsval/`), is plain JavaScript with its own `node --test` suite. The React port the first plan allowed for was never made.
- Jobs: plain functions triggered by the refresh endpoint or by `backend/scheduled_refresh.py`. No Celery or queue. The schedule is a GitHub Actions workflow.
- LLM: confined to the generated notes (`insights.py`, `brief.py`), to the extractors that read filing, label and press text (`pdufa.py`, `trial_readouts.py`, `press_readouts.py`, `guidance.py`, `biologic_loe.py`, `deals.py`, `dailymed.py`), and to the second read of evidence grades (`grade_review.py`). Never a value, a forecast or a rule. Every call goes through one seam, `backend/llm.py`: Groq, then Gemini, then Anthropic, the first key present wins, and `LLM_PROVIDER` pins one. The notes default to Gemini (`NOTE_LLM_PROVIDER`). The app must function without a key and degrade to rules-only output.

## Repo structure

A map, not an inventory: the backend has about 190 modules and 40 fetchers. `ls` is the truth.

```
ER Tool/
  CLAUDE.md
  README.md
  Makefile                  # dev, test, verify, hooks, refresh, history-export, history-rebuild
  run.sh                    # venv, schema, seed, then the API on 8000 and the UI on 8501
  .env.example
  streamlit_cloud_app.py    # the API and the UI in one process, for Streamlit Cloud
  githooks/pre-push         # runs make verify before anything leaves the machine
  .github/workflows/refresh.yml   # the daily refresh and the weekday pulse pass
  deploy/                   # a launchd job for a local 06:00 refresh; its paths are absolute
  backend/
    main.py                 # FastAPI app, routes
    db.py                   # connection, schema init, migrations
    schema.sql
    migrations/             # numbered, each applied once
    seed.py                 # load the universe, resolve CIKs
    refresh.py              # orchestrates fetchers, writes refresh_runs
    scheduled_refresh.py    # the whole-universe refresh with no server, for a schedule
    pulse_refresh.py        # reads the daily pulse; opens no refresh_runs row
    history.py              # export and rebuild data/history/*.ndjson
    diff.py                 # snapshot -> changes engine
    insights.py             # rules layer + note generation
    llm.py                  # the one seam in front of the model providers
    contact.py              # the User-Agent identity, read from .env
    loe.py                  # effective LOE: molecule patent over longest listed
    regional_loe.py         # LOE by region
    competitors.py          # who is selling against a product: three registers kept apart
    assumptions.py          # the curated seeds behind each asset's forecast
    forecast.py             # patients x price to revenue, revenue to FCFF, FCFF to rNPV
    fair_value.py           # a company's fair value as a range across lenses
    engines.py              # three engines over one universe, and which one a company is on
    future_pipeline.py      # the launches the model assumes beyond the named pipeline
    company_lines.py        # revenue a company reports that no asset carries
    forecast_board.py       # the Forecast tab's payload
    comps_valuation.py      # the Comps tab's payload
    company_score.py        # the company scorecard
    landscape_score.py      # the clinical scorecard
    product_areas.py        # a product's disease area, from its label
    asset_merge.py          # fold a derived compound into the product it is
    brand_split.py          # route a study to the brand whose label covers it
    trial_mapping.py        # interventions -> assets, pipeline asset derivation
    payer_access.py         # Part D prescribing, plan coverage, Medicaid: display only
    companyfacts.py         # the XBRL parser EDGAR and ESEF data share
    roche.py, bayer.py      # the two non-SEC filers' own workbooks
    cms_catalogue.py        # the data.cms.gov catalogue, cached on disk
    fetchers/
      base.py               # Fetcher protocol, RefreshResult
      prices.py, benchmarks.py, fx_ecb.py, rates_fred.py
      financials_edgar.py, financials_esef.py, financials_ir.py
      filings_edgar.py, filing_text_edgar.py, product_revenue_sec.py
      trials_ctgov.py       # active studies: the pipeline
      trials_completed.py   # completed studies with results: the record
      trial_results.py
      approvals_openfda.py, approvals_pmda.py, eu_medicines_ema.py
      labels_dailymed.py, pharmacology.py, ndc_marketing.py, brand_lookup_openfda.py
      exclusivity_orangebook.py, exclusivity_purplebook.py
      paragraph_iv_fda.py, pte_uspto.py, use_codes_ob.py
      deals_news.py         # business development from headlines
      press_ir.py, press_page.py, news_fda.py
      news_pulse.py         # the daily pulse's briefings, from claude/pulse-feed
      adcomm_fedreg.py, policy_fedreg.py
      consensus_fmp.py, consensus_nasdaq.py
      codes_rxnav.py        # RxCUIs and NDC product codes per marketed asset
      prescribers_cms.py    # Medicare Part D Prescribers, per brand
      formulary_cms.py      # Part D formulary, read from the ZIP by HTTP Range
      demand_cms.py, negotiated_prices_cms.py
      utilization_medicaid.py  # Medicaid State Drug Utilization Data, national rows
      broker_t212.py        # the user's own Trading 212 account, read only
    tools/
    tests/
      fixtures/             # saved sample payloads
      test_*.py
  frontend/
    streamlit_app.py        # the app: the top bar, the tabs, every page
    theme.py                # the page's CSS
    *_view.py               # pure builders for a page's HTML and SVG
    components/
      charts.py             # the SVG chart layer
      tokens.py             # colour, type and spacing, mirrored in assets/tokens.css
      compsval/             # the Comps frame: core.js, shell.js, table.js, figures.js, ...
      <name>/               # the smaller iframe components
    assets/                 # stylesheets, fonts
    tests/compsval/         # node --test, run by backend/tests/test_comps_js.py
  data/
    companies_seed.csv
    *.csv                   # curated registers, each row with its source
    assumptions/            # one seed file an asset or a layer
    history/                # the snapshot history as NDJSON, committed by the workflow
    company_lines/, consensus/
  docs/
    design/                 # the contract for each tab, with "as built" notes
    research/               # dated research notes and the draft rows they produced
    ROADMAP.md, ACTION_PLAN.md
  work/                     # finished working papers; no code reads it, data files cite it
  archive/                  # superseded documents, kept for the record: the v1 PRD, the July tour and logs
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

### Daily pulse (sector news)

- A scheduled Claude run ("Daily biopharma pulse", weekdays 07:45 London, a cloud run with
  no copy of the repository) emails a ranked briefing and saves its items as
  `pulse-YYYY-MM-DD.json` to the Google Drive folder "Terminal pulse feed". A second
  scheduled run ("Pulse relay to terminal", weekdays 08:40 London) copies each file,
  unchanged, to `data/pulse/YYYY-MM-DD.json` on the `claude/pulse-feed` branch, never to
  main. Every file on that branch so far came through the relay.
- Before it tags an item the pulse fetches `data/pulse_universe.json` from main (the
  repository is public): every covered company's ticker as the terminal holds it, its
  press names, its subsidiaries, the drugs it alone owns, and the names that look like a
  covered company and are not one. `backend/pulse_universe.py` writes it from the
  database and the refresh commits it with the day's history.
- Schema 2 (`pulse.py`): each item carries `entities` (a covered company by ticker, with
  a role: subject, party or read_across), an `event_key` that stays the same on every
  day a story runs, `first_reported`, `update`, `phase` and `assets`, and keeps
  `companies` and `tickers` so a schema 1 reader still reads it. The terminal takes a
  ticker only if it holds it, else the entity's name compared whole, else drops the tie
  and reports it; it never guesses. A story repeated without `update` reaches the change
  feed once, and read-across reaches only the company's news, marked as read-across.
- The Universe tab's ranked week (`universe_command._pulse_place`) ranks the pulse's tier
  1 stories among the primary items: a deal after the priced deals, a readout after the
  Phase 3 results, anything else after the rate move. Tier 2 follows the notices, tier 3
  stays on the company's news, and a story a primary item already tells folds into it as
  a row rather than ranking twice.
- The pulse is read by a pass of its own, not by the daily refresh. The two want times
  that cannot be reconciled. Prices have to be read before any market opens, because
  `fetchers/prices.py` takes Yahoo's daily chart as it stands and from the opening bell
  that chart carries a bar for today whose close is the last trade: a refresh after
  08:00 UTC would write an intraday price into the snapshot history, which no later run
  could correct. So the refresh stays at 06:00 UTC. The pulse wants the opposite, since
  its value is the European morning, so `refresh.yml` runs a second schedule at 10:00
  UTC on weekdays that restores, reads the branch into `ER_PULSE_DIR`, runs
  `backend/pulse_refresh.py` and publishes, fetching no source. The 06:00 run still
  reads the whole pulse folder, so a missed pass costs a day, not a file.
- That pass opens no `refresh_runs` row on purpose: `/runs/latest` is what the top bar
  reads for "last refresh", and a pulse pass that opened one would have the terminal
  date the universe to the morning's briefing.
- It is an AI-written summary of the trade press, not a registry. An item is kept only
  with the link it summarises, every view labels it "Daily pulse (AI summary)", and it
  reaches news, the change feed and the Sector news panel only: never a value, a deal
  term or a catalyst. Items outside the universe (private rounds, other biotechs) are
  kept, with no company attached.

### Catalysts

- No free PDUFA calendar API exists. Catalysts are a curated table edited in the UI. Supplement with extraction: when a new 8-K or 6-K reports FDA acceptance of a filing, call the model (through `backend/llm.py`) to pull the PDUFA date and write a catalyst row with `is_curated = 0` for review.

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
- Secrets live in `.env` and are never committed. `SEC_USER_AGENT` is the one the core needs: EDGAR blocks requests without it and `seed.py` uses it to resolve CIKs. Optional: `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `FMP_API_KEY`, `OPENFDA_API_KEY`, `CONTACT_EMAIL`, `T212_API_KEY` and `T212_API_SECRET`. `.env.example` lists them.
- Small commits, one concern each. Conventional commit messages.

## Running

```bash
./run.sh                 # or: make dev. Venv, schema, seed, then the API on 8000 and the UI on 8501
make verify              # the suite, with a real exit code; run it from the repo root
make hooks               # install the pre-push hook, which runs make verify
make refresh             # pull every source for the universe (needs the API up)
make refresh-daily       # the same with no server, logged to logs/
make history-rebuild     # rebuild the database from data/history/*.ndjson
```

By hand:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import db; db.init()"          # schema and migrations, idempotent
python seed.py                            # the universe, CIKs resolved
uvicorn main:app --reload                 # API on 8000
# in another shell, from the repo root:
streamlit run frontend/streamlit_app.py   # UI on 8501
```

- The app tests skip when the API is not on 8000, and the JavaScript tests skip when `node` is not installed. A green run with either missing has not tested that part.
- Refresh only before 08:00 UTC or after the US close. A refresh while a market is open writes an intraday price into the snapshot history as that day's close (see "Daily pulse" above).
- `uvicorn --reload` restarts the API on any edit under `backend/`, which empties its caches; the first page after that is slow.

## Rules for you, Claude Code

- Work one piece of work per session. Use plan mode, get the plan agreed, then implement. (The build phases this rule was written for are in `archive/PRD.md` and ended in July 2026.)
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
