"""FastAPI app: health check and a stubbed refresh endpoint.

Phase 1 has no fetchers. POST /refresh records a refresh_runs row and marks it
complete so the plumbing (and the UI's refresh button, later) has something real
to call. Real fetcher orchestration arrives in phase 2.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

import db

try:  # optional local .env, mirrors seed.py
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists so a fresh checkout can serve /refresh immediately.
    db.init()
    yield


app = FastAPI(title="Pharma equity research terminal", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/refresh")
def refresh() -> dict:
    """Record a refresh run and return it. Stub: no sources are fetched yet."""
    detail = json.dumps({"sources": [], "note": "stubbed refresh; no fetchers in phase 1"})
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO refresh_runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cur.lastrowid
        conn.execute(
            """
            UPDATE refresh_runs
               SET finished_at = datetime('now'), status = 'complete', detail = ?
             WHERE id = ?
            """,
            (detail, run_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, started_at, finished_at, status, detail FROM refresh_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row)
