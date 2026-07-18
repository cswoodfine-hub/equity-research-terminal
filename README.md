# Pharma equity research terminal

An equity research terminal for large-cap pharma. One refresh pulls live and
near-live data from free sources, stores a timestamped snapshot, computes what
changed since the last snapshot, and renders charts plus a short written note per
company. See [CLAUDE.md](CLAUDE.md) for architecture and [docs/PRD.md](docs/PRD.md)
for the product spec.

Status: phase 5 (LOE and approvals). Prices (Yahoo), financials (SEC EDGAR), active
trials (ClinicalTrials.gov), patent/exclusivity (FDA Orange + Purple Book), and FDA
approvals (openFDA) refresh for the universe, snapshot, and feed the comps table, a
pipeline heatmap, an LOE cliff, and an approvals feed. The `assets` table now holds
real marketed products keyed by FDA application number. A Streamlit UI has Prices,
Financials, Comps, Pipeline, LOE, and Approvals tabs. Honest gaps are labelled, not
estimated: valuation ratios are US-filer-only, pipeline cells are trial counts (not
deduplicated assets), the LOE cliff is product counts (no free product revenue) with
partial biologics coverage, and openFDA approvals are not exhaustive. The diff engine,
generated notes, and React come later.

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r ../requirements.txt

cp ../.env.example ../.env    # then set SEC_USER_AGENT (required by seed.py)
```

`SEC_USER_AGENT` must be a real identifier, e.g. `Your Name your@email`. EDGAR
blocks requests without it.

## Run

```bash
cd backend

# create the SQLite database from schema.sql (idempotent)
python -c "import db; db.init()"

# load the 18-company universe and resolve SEC CIKs
python seed.py

# serve the API
uvicorn main:app --reload

# in another shell
curl localhost:8000/health                        # {"status":"ok"}
curl -X POST 'localhost:8000/refresh?ticker=LLY'  # one company: prices + financials
curl -X POST 'localhost:8000/refresh?scope=all'   # whole universe (needed for comps)
curl localhost:8000/companies                     # the 18-company universe
curl localhost:8000/companies/LLY/prices          # close series + latest quote
curl localhost:8000/companies/LLY/financials      # stored EDGAR financials
curl localhost:8000/comps                          # the comps table
curl localhost:8000/pipeline                       # company x phase trial counts
curl 'localhost:8000/companies/LLY/trials?phase=Phase%203'  # trials behind a cell
curl localhost:8000/loe                            # company x expiry-year LOE cliff
curl localhost:8000/companies/LLY/exclusivities    # upcoming LOE products
curl localhost:8000/companies/LLY/approvals        # FDA approvals (NDAs + BLAs)
```

Orange/Purple Book and openFDA need no key (openFDA works unauthenticated; set the
optional `OPENFDA_API_KEY` only to raise the rate limit).

`?scope=all` and financials need `SEC_USER_AGENT` set (EDGAR blocks anonymous
requests). Foreign names are quoted by their US ADR symbol (ROG uses RHHBY, BAYN
uses BAYRY), so the bare home ticker never resolves to an unrelated US company.

The database is written to `backend/er_tool.db` by default. Override with the
`ER_TOOL_DB` environment variable.

A refresh inside a source's TTL (prices: 15 minutes) is a no-op for that source and
says so in the response. Market cap has no free source this phase and is left null
rather than estimated.

## UI (Streamlit)

The UI is a thin client over the JSON API. Start the API first (above), then in
another shell:

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/streamlit_app.py
```

The UI has six tabs: Prices (the six-month close chart with a per-company refresh),
Financials (reported revenue, net income, and R&D per company), Comps (the sortable
universe table), Pipeline (a company x phase heatmap of active trials), LOE (a company
x expiry-year cliff of products losing exclusivity, with drill-down), and Approvals (a
per-company FDA approvals feed). The API base URL is configurable in the sidebar
(default `http://localhost:8000`). Blank comps cells are no free data, not zero;
pipeline and LOE counts are trials/products, not deduplicated or revenue-weighted.

A full `?scope=all` refresh pulls every source for all 18 companies (Yahoo, EDGAR,
and paginated ClinicalTrials queries) and can take several minutes; per-source TTLs
mean repeat refreshes skip anything still fresh.

## Test

```bash
cd backend
pytest -q
```

Tests do not touch the network: the CIK resolver runs against a saved fixture in
`backend/tests/fixtures/`.
