# Pharma equity research terminal

An equity research terminal for large-cap pharma. One refresh pulls live and
near-live data from free sources, stores a timestamped snapshot, computes what
changed since the last snapshot, and renders charts plus a short written note per
company. See [CLAUDE.md](CLAUDE.md) for architecture and [docs/PRD.md](docs/PRD.md)
for the product spec.

Status: phase 1 (scaffold). Backend skeleton, database, and seed loader only. No
fetchers or frontend yet.

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
curl localhost:8000/health           # {"status":"ok"}
curl -X POST localhost:8000/refresh  # a refresh_runs row, status "complete"
```

The database is written to `backend/er_tool.db` by default. Override with the
`ER_TOOL_DB` environment variable.

## Test

```bash
cd backend
pytest -q
```

Tests do not touch the network: the CIK resolver runs against a saved fixture in
`backend/tests/fixtures/`.
