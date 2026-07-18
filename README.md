# Pharma equity research terminal

An equity research terminal for large-cap pharma. One refresh pulls live and
near-live data from free sources, stores a timestamped snapshot, computes what
changed since the last snapshot, and renders charts plus a short written note per
company. See [CLAUDE.md](CLAUDE.md) for architecture and [docs/PRD.md](docs/PRD.md)
for the product spec.

Status: phase 7 (generated notes). Prices (Yahoo), financials (SEC EDGAR), trials
(ClinicalTrials.gov), patent/exclusivity (Orange + Purple Book), approvals (openFDA),
and filings (EDGAR submissions) refresh for the universe. Every refresh writes
snapshots, and a diff engine turns consecutive snapshots into a `changes` feed: trial
status/date/phase changes, new 8-K/6-K, and new approvals, ranked with catalysts
within 60 days and near-term LOE into a "what changed" view. Catalysts are a curated
table with a 90-day calendar; news comes from EDGAR 8-K/6-K. On top of that feed sits
the note layer: a per-company morning note, written by the Anthropic API when a key is
set and by a rules-only fallback when it is not. A Streamlit UI has What changed (note
plus feed), Prices, Financials, Comps, Pipeline, LOE, Approvals, Catalysts, and News
tabs. Honest gaps are labelled: valuation ratios are US-filer-only, pipeline cells are
trial counts, the LOE cliff is product counts with partial biologics, catalysts are
curated (empty until added), news is EDGAR-only, and the change feed needs two
refreshes to populate. React comes later.

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
curl localhost:8000/changes                        # ranked what-changed feed
curl localhost:8000/companies/LLY/filings          # recent EDGAR filings
curl localhost:8000/companies/LLY/news             # EDGAR 8-K/6-K news
curl localhost:8000/catalysts                      # curated catalyst calendar
curl localhost:8000/companies/LLY/note             # stored morning note
curl 'localhost:8000/companies/LLY/note?refresh=true'   # generate a new one
```

## Generated notes

The what-changed feed has two layers. The rules layer always runs. The note layer
summarises one company's slice of it into a short paragraph.

Set `ANTHROPIC_API_KEY` and the note is written by `claude-opus-4-8`, prompted to use
only the supplied feed items and never to invent a number. Leave it unset and the note
is a deterministic list of the flagged items, and `model` in the response reads
`rules` so the UI can say which layer produced it. If the API errors, the note falls
back to the rules layer and reports the error rather than failing the request.

Every note is stored in `insights` with the `changes.id` values it was built from, so
a note can be traced back to its evidence.

The what-changed feed needs at least two refreshes per company to show anything: the
first establishes that company's snapshot baselines and the next detects diffs against
them. Baselines are per company, so refreshing one ticker does not affect the others.
A first-seen filing or approval is also only reported when its own date falls within
the last 180 days, which keeps back catalogue out of the feed when coverage of a
company starts late.

Orange/Purple Book and openFDA need no key (openFDA works unauthenticated; set the
optional `OPENFDA_API_KEY` only to raise the rate limit).

`?scope=all` and financials need `SEC_USER_AGENT` set (EDGAR blocks anonymous
requests). Foreign names are quoted by their US ADR symbol (ROG uses RHHBY, BAYN
uses BAYRY), so the bare home ticker never resolves to an unrelated US company.

The database is written to `backend/er_tool.db` by default. Override with the
`ER_TOOL_DB` environment variable.

A database refreshed before the per-company baseline fix still holds the change rows
that defect produced, and any note that cites them. `python -m cleanup` reports them
and `python -m cleanup --apply` deletes them after copying the database file aside. It
retires a first-seen approval or filing dated more than 180 days before its own
detection, so genuinely recent items recorded in the same run survive: on the
development database 9 of the 625 rows were real. Snapshots are left untouched, which
is what stops the deleted rows coming back on the next refresh.

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

The UI opens on a **What changed** tab (the ranked feed), then Prices, Financials,
Comps, Pipeline, LOE, Approvals, a **Catalysts** tab (a 90-day calendar with an add
form; the table is curated), and a **News** tab (per-company EDGAR 8-K/6-K). The API
base URL is configurable in the sidebar (default `http://localhost:8000`). Blank comps
cells are no free data, not zero; pipeline and LOE counts are trials/products, not
deduplicated or revenue-weighted; the what-changed feed fills in after a second refresh.

A full `?scope=all` refresh pulls every source for all 18 companies (Yahoo, EDGAR, and
paginated ClinicalTrials queries). Companies run in parallel, four at a time. Measured
cold on 2026-07-18: 68s sequential, 33s parallel. Set `ER_TOOL_REFRESH_WORKERS` to
change the worker count; raising it much above 4 risks EDGAR's 10 requests/second
limit. Per-source TTLs mean repeat refreshes skip anything still fresh.

## Test

```bash
cd backend
pytest -q
```

Tests do not touch the network: the CIK resolver runs against a saved fixture in
`backend/tests/fixtures/`.
