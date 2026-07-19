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
curl 'localhost:8000/companies/LLY/statements?basis=quarterly'  # three statements
curl localhost:8000/comps                          # the comps table
curl localhost:8000/pipeline                       # company x phase trial counts
curl 'localhost:8000/companies/LLY/trials?phase=Phase%203'  # trials behind a cell
curl localhost:8000/loe                            # company x expiry-year LOE cliff
curl localhost:8000/companies/LLY/exclusivities    # upcoming LOE products
curl localhost:8000/companies/LLY/approvals        # approvals, with expiry and revenue
curl localhost:8000/companies/LLY/exposure         # cliff by year, and its coverage
curl localhost:8000/companies/LLY/revenue          # curated product revenue
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

**Financials** carries the three statements at every period a filer tags, quarterly or
annual, with a snapshot of the latest reported period against the same period a year
earlier. Coverage is uneven by filer and the tab says so rather than papering over it:
of the 18 companies, 16 file with the SEC and 2 (Roche, Bayer) do not, and among the 16
the 20-F filers vary from full interim tagging to annual only. A line the filer does not
tag is a dash, never a zero. Dotted figures are computed from two reported lines, which
covers subtotals a filer skips (Lilly never tags gross profit) and fourth quarters,
which nobody tags and which are the reported year less the reported nine months.
Per-share lines are excluded from that subtraction, since EPS does not add up across
quarters. Cash flow columns are cumulative from the year start, as a 10-Q reports them.

**Approvals** lists each approved product with the latest expiry the Orange or Purple
Book carries for it, the basis of that date, and its revenue. Protection is per asset,
so several approvals of one product share it, and a dash means the books hold no entry
rather than that the product is unprotected.

**Product revenue comes from the SEC Financial Statement Data Sets.** The companyfacts
API collapses every XBRL dimension and returns the consolidated `Revenues` line alone,
which is why product revenue looks unavailable from the API. The quarterly bulk data
sets keep the dimensions in a `segments` column, so `ProductOrService=Zepbound` is right
there and free. Roughly 80MB a quarter, cached under `backend/cache/` and refreshed
quarterly, which is as often as the source moves.

A worldwide figure is only taken when the filing states one, or when the geography
members form a partition the fetcher recognises (US plus non-US, and similar). An
unrecognised split yields nothing rather than a plausible number, because a filer
reporting both a total and its parts would otherwise be double counted. Category members
on the same axis (therapeutic areas, `OtherProductTotal`, gross-before-rebates totals)
are filtered by name and then by having to match an asset's brand name.

Nothing is entered by hand. A figure is what the company reported or it is absent, so a
filer that tags no product axis (AbbVie) shows none rather than a number someone typed
once and never revisited.

Coverage is 13 of the 16 SEC filers, 124 products. AbbVie tags no product axis at all,
and GSK and Regeneron spread their products across segments in a way that would need
summing. Novo reports in DKK and Sanofi in EUR; the unit travels with each figure and
nothing is converted.

**A primary completion date in the past is usually normal.** ClinicalTrials.gov marks
each date actual or estimated and the app now stores which. An actual date that has
passed means the primary endpoint was reached; the trial stays active, not recruiting
while it follows participants for overall survival, which routinely runs years and in
one Merck study to 2033. An estimated date that has passed is the opposite: a forecast
missed and never revised. Across the universe 469 dates are actual, all necessarily in
the past, and 106 of the 2,109 estimated ones are overdue. The trials table says which
each is.

**PDUFA dates are extracted from the 8-K that announces the acceptance.** No free
calendar of FDA decision dates exists, so the filing is the source. Candidate 8-K and
6-K filings are filtered by their item taxonomy, then by whether the text mentions a
review at all, which on the current database sends 1 filing of 12 to the model rather
than all of them. The Anthropic API reads the document and returns the date, the product
and a verbatim quote.

Nothing it returns is trusted on its own. The date must parse, be in the future, and sit
inside a plausible review window; the product name must appear in the filing; and the
quote must appear in the filing near-verbatim. A model that supplies a product name from
its own knowledge, or reasons a date out of "expected within six months", fails those
checks and the row is dropped. Rows land with `is_curated = 0` and link to the document.

Needs `ANTHROPIC_API_KEY`. Without it the step reports that it did nothing and the
calendar carries registry readouts alone.

**Exclusivity is United States only, and biologics carry no patent dates.** The Orange
Book and the Purple Book are FDA publications, so every expiry in this app is a US
date; a product protected in the US to 2035 can face a generic in Europe or Japan years
earlier and nothing here knows it. Worse for biologics: the Purple Book publishes
regulatory exclusivity and no patents at all, so all 109 biologics in the universe show
an exclusivity date rather than the patent that actually gates a biosimilar. Keytruda's
only entry is an orphan exclusivity, so it now shows no cliff date rather than a wrong
one. Small molecule dates come from Orange Book patents and are sound. Orphan
exclusivity is excluded from the cliff entirely, which takes it from 348 products to
292.

**Revenue mix** on the Approvals tab draws the largest drivers as their own slices and
brackets the rest into one. A pie is only readable while the slices are few and
different in size, so anything past the sixth product, or under 2% of the total, joins
the bracket. The donut totals to company revenue, not to the tagged products: the gap
between them is drawn as a hollow wedge, which for Lilly is the 15.1bn of collaboration
revenue, lines reported only as a total, and products the app holds no asset for.

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
