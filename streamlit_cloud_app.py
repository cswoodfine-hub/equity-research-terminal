"""Entry point for running the terminal as one process, for Streamlit Cloud.

Locally the app is two processes: uvicorn serving the API and streamlit serving the UI,
which talks to it over HTTP. A Streamlit Cloud container runs one command, so this
starts the API inside the same process, on a thread, and then hands over to the app
unchanged. Nothing in the API or the UI knows the difference.

The data is the harder half. A fresh container has no database, and the committed
history is deliberately only the part no source can hand back: snapshots, detected
changes, catalysts and notes. Prices, financials, assets and trials are left out of it
because they are re-fetchable, which is true and also means a container rebuilt from
history alone shows an empty universe.

So the database is looked for in three places, in order of how recent each is, and the
app says which one it got. Nothing is fabricated to fill a gap: an empty universe reads
as an empty universe.
"""

from __future__ import annotations

import gzip
import io
import os
import pathlib
import runpy
import shutil
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
for path in (BACKEND, FRONTEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import streamlit as st  # noqa: E402  after sys.path, so backend imports resolve

API_PORT = int(os.getenv("ER_API_PORT", "8000"))
API_BASE = f"http://127.0.0.1:{API_PORT}"
# A gzipped SQLite file the daily workflow can publish. Set as a Streamlit secret to
# give the deployed app the same data the scheduled refresh produced.
DB_URL = os.getenv("ER_DB_URL", "")
STARTUP_TIMEOUT_S = 45


def _download_database(url: str, target: pathlib.Path) -> str:
    """Fetch a gzipped database published by the refresh, or say why it could not."""
    request = urllib.request.Request(url, headers={"User-Agent": "NovatalisTerminal/0.1"})
    token = os.getenv("ER_DB_TOKEN", "").strip()
    if token:                      # a private repo's release asset needs one
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/octet-stream")
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    body = gzip.decompress(payload) if url.endswith(".gz") else payload
    target.write_bytes(body)
    return f"downloaded {len(body) / 1e6:.0f} MB from the published refresh"


@st.cache_resource(show_spinner="Preparing the database")
def prepare_database() -> str:
    """Put a database in place and report, in one sentence, where it came from."""
    import db
    import history
    import seed

    target = pathlib.Path(db.DB_PATH)
    if target.exists() and target.stat().st_size > 1_000_000:
        return "using the database already on disk"

    if DB_URL:
        try:
            db.init(str(target))
            return _download_database(DB_URL, target)
        except Exception as exc:            # a bad URL must not take the app down
            st.warning(f"Could not fetch the published database: {exc}")

    # Whatever is on file. The history holds the change feed and the notes; the
    # current-state tables stay empty until a refresh runs, and the app says so
    # rather than implying the universe is empty.
    db.init(str(target))
    seed.load_companies(str(target))
    loaded = history.rebuild(str(target))
    rows = sum(loaded.values()) if isinstance(loaded, dict) else 0
    return (f"rebuilt from the committed history, {rows:,} rows. Prices, financials and "
            "trials are not in that export, so press Refresh to fetch them.")


@st.cache_resource(show_spinner="Starting the API")
def start_api() -> str:
    """Run uvicorn on a thread and wait until it answers, so the first page load does
    not race the server it is about to call."""
    import uvicorn

    import main

    server = uvicorn.Server(uvicorn.Config(
        main.app, host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    deadline = time.time() + STARTUP_TIMEOUT_S
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API_BASE}/health", timeout=2):
                return API_BASE
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"the API did not answer on {API_BASE} within "
                       f"{STARTUP_TIMEOUT_S} seconds")


provenance = prepare_database()
os.environ["ER_API_BASE"] = start_api()

# The app itself, run unchanged and as the main module, so its own relative paths and
# its ``__main__`` guard behave exactly as they do locally.
sys.argv = [str(FRONTEND / "streamlit_app.py")]
runpy.run_path(str(FRONTEND / "streamlit_app.py"), run_name="__main__")

st.sidebar.caption(f"Data: {provenance}")
