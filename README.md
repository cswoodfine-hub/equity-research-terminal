# Pharma equity research terminal

An equity research terminal for large-cap pharma. One refresh pulls live and
near-live data from free sources, stores a timestamped snapshot, computes what
changed since the last snapshot, and renders charts plus a short written note per
company. See [CLAUDE.md](CLAUDE.md) for architecture and [docs/PRD.md](docs/PRD.md)
for the product spec.

Status: phase 2 (vertical slice). One company (LLY) works end to end: a prices
fetcher pulls six months of daily closes from Yahoo, refresh snapshots then upserts
and reports per-source status, and a Streamlit UI shows the chart with a refresh
button. Other sources, the diff engine, and the React frontend come in later phases.

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
curl localhost:8000/health                       # {"status":"ok"}
curl -X POST 'localhost:8000/refresh?ticker=LLY' # fetch LLY prices, returns the run
curl localhost:8000/companies                    # the 18-company universe
curl localhost:8000/companies/LLY/prices         # close series + latest quote
```

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

Pick a company, click Refresh prices, and the six-month close chart renders. The API
base URL is configurable in the sidebar (default `http://localhost:8000`).

## Test

```bash
cd backend
pytest -q
```

Tests do not touch the network: the CIK resolver runs against a saved fixture in
`backend/tests/fixtures/`.
