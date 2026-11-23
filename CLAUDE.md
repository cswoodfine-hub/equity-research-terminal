# CLAUDE.md

## What this is

An equity research terminal for biopharma: large-cap pharma, biotech, and cell and gene. One refresh action pulls live and near-live data for a fixed universe of companies (`data/companies_seed.csv`), stores a timestamped snapshot, computes what changed since the last snapshot, and renders charts plus a short written note per company. On top of that sits a valuation: each asset forecast from patients and price to risk-adjusted value (`forecast.py`), from curated assumptions (`data/assumptions/`), and each company read as a range across lenses (`fair_value.py`). The universe is read on three engines: big pharma, biotech, and cell and gene (`engines.py`). The differentiator is change detection and synthesis over free data sources, not raw data breadth.

## Tech stack

- Backend: Python 3.11+, FastAPI, SQLite via `sqlite3`. Keep SQL portable.
- Frontend: Streamlit (`frontend/streamlit_app.py`), a thin client over the JSON API. Every chart is hand-built SVG from `frontend/components/charts.py`; there are no native Streamlit or Altair charts. A few views are iframe components under `frontend/components/`; the largest, the Comps frame (`compsval/`), is plain JavaScript with its own `node --test` suite. The React port the first plan allowed for was never made.
- Jobs: plain functions triggered by the refresh endpoint or by `backend/scheduled_refresh.py`. No Celery or queue. The schedule is a GitHub Actions workflow.
- LLM: confined to the generated notes (`insights.py`, `brief.py`), to the extractors that read filing, label and press text (`pdufa.py`, `trial_readouts.py`, `press_readouts.py`, `guidance.py`, `biologic_loe.py`, `deals.py`, `dailymed.py`), to the second read of evidence grades (`grade_review.py`), and to the Ask tab (`desk_chat.py`), where it answers a question from the desk tools' reads and nothing else. Never a value, a forecast or a rule. Every call goes through one seam, `backend/llm.py`: Groq, then Gemini, then Anthropic, the first key present wins, and `LLM_PROVIDER` pins one. The notes default to Gemini (`NOTE_LLM_PROVIDER`). The app must function without a key and degrade to rules-only output.

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
    run_health.py           # one summary a run: start hour, sources erred or quiet, readers the model failed
    scheduled_refresh.py    # the whole-universe refresh with no server, for a schedule
    pulse_refresh.py        # reads the daily pulse; opens no refresh_runs row
    history.py              # export and rebuild data/history/*.ndjson
    diff.py                 # snapshot -> changes engine
    insights.py             # rules layer + note generation
    llm.py                  # the one seam in front of the model providers
    contact.py              # the User-Agent identity, read from .env
    market_session.py       # whether a daily bar is a finished session or one still trading
    price_record.py         # recorded prices that were not closes, corrected beside the record
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
    mcp_tools.py            # the desk tools: the book's reads shaped for a model to call
    thesis_log.py           # dated, falsifiable reads, appended to ledger/theses.ndjson
    desk_chat.py            # the Ask tab: a question answered from the desk tools' reads
    call_sync.py            # append the call log's missing days from data/history
    insiders.py, holders.py # Form 4 dealing and 13F holders, read from the book
    positioning.py          # short interest, options, insiders, holders: side by side
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
      insiders_edgar.py     # Form 4, per company, capped per run
      holders_13f.py        # the SEC's quarterly Form 13F data sets, by CUSIP
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
  mcp_server/
    lens_mcp.py             # the MCP server: the protocol only, run with uv
  ledger/
    theses.ndjson           # the thesis log; beside data/ so a line does not move the cache
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
- The Prices tab reads Yahoo for itself, apart from the refresh: `/companies/{ticker}/prices/live` (`backend/prices_live.py`) asks the same chart endpoint for five sessions of 5 minute bars and a month of hourly ones, holds the answer in the API's memory for about a minute and writes nothing. No bar, no snapshot, no `refresh_runs` row: a path that cannot write cannot file an intraday price as a close, and a write a minute would move the stamp `response_cache` keeps every valuation against. The page lays the live bars over the stored series (`price_chart.merge_live`) and re-reads each minute while the regular session is open.
- The chart endpoint's `meta` carries no market state and no stated delay (read 2026-11-23). It carries `currentTradingPeriod`, the hours of the pre, regular and post sessions, and `regularMarketTime`, the last trade; whether a session is open is worked out from those. While one is open the last element of an intraday series is the last trade, stamped to the second with a volume of nought, not a bar. `parse_chart` stamps every bar with the one `gmtoffset` in the meta, so bars from the other side of a clock change come out an hour off; each entry of `tradingPeriods` carries its own offset, and the live read drops the sessions that differ.

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

- A scheduled Claude run ("Daily biopharma pulse", weekdays 07:45 London) on the machine
  that holds the clone emails a ranked briefing and commits its items as
  `data/pulse/YYYY-MM-DD.json` to the `claude/pulse-feed` branch, never to main. It
  publishes to git itself; there is no file store in between.
- The pulse is read by a pass of its own, not by the daily refresh. The two want times
  that cannot be reconciled. The refresh is scheduled for 06:00 UTC, before any market
  the book quotes has opened, because from the opening bell Yahoo's daily chart carries
  a bar for today whose close is the last trade. The schedule does not hold: every
  refresh in the committed run log from 2026-10-10 to 2026-11-23 began between 10:26 and
  18:14 UTC. So the price and benchmark fetchers hold back a bar whose session has not
  closed (`backend/market_session.py`), whatever the hour, and the run snapshots the
  last finished close under its own date. The pulse wants the opposite of an early run, since
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

## Desk tools (MCP)

The book's reads are exposed to a language model as tools, so a model can connect things
no single page connects and every figure it uses is one the book computed.

- `backend/mcp_tools.py` is the catalogue: what each tool asks the API and how the answer
  is cut to size. It is plain standard library and imports nothing from the backend,
  because it also runs inside the server process on a different interpreter.
- `mcp_server/lens_mcp.py` is the protocol and nothing else. The SDK needs Python 3.10 or
  later and the backend runs on 3.9, so it is a separate process that reaches the API
  over HTTP. Run it with `uv run mcp_server/lens_mcp.py` (stdio) or `--http PORT`. The API
  must be up. It binds to 127.0.0.1 and has no authentication: one analyst's own machine.
- The tools read. One writes: `lens_log_thesis` appends to `ledger/theses.ndjson`
  (`thesis_log.py`), append-only, marked against XBI on its due date. No tool changes a
  value, an assumption or a catalyst, and the what-if tool saves nothing.
- The model is still confined as the LLM rule above says: never a value, a forecast or a
  rule. A read made through the tools is commentary until it is logged as a thesis and
  marked.
- A new tool is a new entry in `mcp_tools.TOOLS` over an API route. Give it a route first
  if the read does not exist; do not compute in the tool.
- The Ask tab is the same tools inside the app (`desk_chat.py`, `POST /ask`). The model is
  pinned with `CHAT_LLM_PROVIDER` (Gemini by default, like the notes) and reached through
  `llm.conversation`, the tool-using side of the one seam. An answer comes back with every
  read it was made from. The reader's own holdings are not offered to it unless
  `CHAT_ALLOW_PORTFOLIO=1`, because what a tool returns is sent to the model's provider.
  With no key the tab says so and the rest of the app is unaffected.

### The call log follows the committed record

- Only the scheduled run records calls (`model_calls`, `gate_calls`), so the dated record
  has one writer. A book refreshed from the terminal gets them from `data/history`:
  `call_sync.py` appends the days the history files hold beyond the book at API start,
  changes nothing already there, and refuses where the book and the file disagree. Pull
  `main`, restart the API, and the gate odds are current.
- A number is not a row. The scheduled book and a book refreshed on a machine both take
  the next number in every history table, so after one refresh each the same number is
  two rows. `history.py` says what makes a row the same row (`history.SAME_ROW`) and
  merges nothing with another book: `rebuild` loads nothing, `export` writes nothing and
  `restore-check` turns the database away. A table added to `HISTORY_TABLES` needs its
  entry there. `python backend/history.py parted` says where a book and the record differ.

### Form 4 (insider transactions)

- An issuer's `submissions` list on EDGAR carries its Form 4s beside the ones it filed as
  a shareholder of somebody else, and only the document's `issuerCik` separates them.
  The rendered path (`xslF345X06/...`) is the raw XML without its first directory; the
  number follows the schema version.
- Codes P and S are the decisions; everything else (awards, exercises, tax withholding,
  gifts) is counted apart and never netted in. The Rule 10b5-1 box is one for the whole
  form and dates from April 2023. A foreign private issuer may show no forms at all.

### Form 13F (institutional holders)

- The SEC's Form 13F data sets, one ZIP of tab-separated tables a quarter, about 100 MB
  each. A download address is read off the listing page and never built from a pattern:
  the newest file and the older ones sit under different paths. INFOTABLE is 3.8 million
  lines and is read row by row out of the ZIP, never unpacked.
- A release is cut by filing date, not by quarter, and holds late reports for many
  earlier periods. The quarter is taken from each filing, not from the file name.
- Filtered by the CUSIPs in `data/cusips.csv`, each confirmed against the SEC's Official
  List of Section 13(f) Securities and check-digit validated. A company whose US line
  trades over the counter (Roche, Bayer) is not a 13(f) security: it is left out with
  the reason in `data/cusips_left_out.csv`, and the reader answers with that reason.
- VALUE is in dollars from 2023 and some filers still report thousands; such a value is
  left null and never scaled. The readme says nothing on amendments: the cover page boxes
  decide, and a "new holdings" amendment at least half the size of the report it amends
  is read as a restatement, which is a judgement and is documented in the fetcher.
- Long positions of managers over the reporting threshold only, filed up to 45 days
  after the quarter end, options held apart. Lent shares are reported twice, so reported
  holdings can exceed the shares outstanding.

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
- A refresh while a market is open no longer files an intraday price as that day's close: the daily price and benchmark fetchers hold back the bar of a session still trading (`backend/market_session.py`). Until 2026-11-23 they did not. Measured that day, 28 days of snapshots from 2026-07-24 to 2026-11-20 carry a mid-session price under the name of a close (1,232 company-days, median 1.2% from the settled close), and 382 of the 1,542 model calls were priced off one. That record is left as it was written. The scheduled run appends each such price and the close it settled at to `price_corrections` (`backend/price_record.py`), and `call_log.score` reports every horizon from the recorded price and from the settled close, side by side. The Refresh button on the Prices tab is not that refresh: it is the live read, which writes nothing and is safe at any hour.
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
