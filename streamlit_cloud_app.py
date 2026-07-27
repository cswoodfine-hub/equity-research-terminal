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
import json
import os
import pathlib
import runpy
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

def setting(name: str, default: str = "") -> str:
    """A value from Streamlit's secrets, or the environment, or the default.

    Secrets first, because that is where a deployed app is configured, and reading
    only the environment would leave the app silently falling back to the committed
    history with no sign of why.
    """
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:              # no secrets file at all, which is the local case
        pass
    return (os.getenv(name) or default).strip()


API_PORT = int(setting("ER_API_PORT", "8000"))
API_BASE = f"http://127.0.0.1:{API_PORT}"
# Where the daily refresh publishes its database. Set ER_DB_REPO to "owner/repo" and
# the app resolves the tag each time it starts, which it has to: uploading an asset
# gives it a new id, so a URL captured once points at yesterday's file by tomorrow.
# ER_DB_URL is the escape hatch for a plain public URL.
DB_REPO = setting("ER_DB_REPO")
DB_TAG = setting("ER_DB_TAG", "data-latest")
DB_URL = setting("ER_DB_URL")
STARTUP_TIMEOUT_S = 45


def _shipped_stamp(target: pathlib.Path) -> str:
    """When the shipped database was last refreshed, read from its own run ledger, so
    the sidebar says how old the data is rather than only where it came from."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(target))
        row = conn.execute(
            "SELECT finished_at FROM refresh_runs WHERE status IN ('complete','partial')"
            "  ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return f", refreshed {row[0]} UTC" if row and row[0] else ""
    except Exception:
        return ""


def _resolve_release_asset(repo: str, tag: str, token: str) -> str:
    """The API URL of the published database, looked up by tag.

    An asset keeps its name and loses its id every time it is replaced, so the id is
    resolved on each start rather than configured once. The API URL is used, not the
    browser one, because a private repository only serves the former to a token.
    """
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers={"User-Agent": "NovatalisTerminal/0.1",
                 "Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    for asset in release.get("assets", []):
        if asset.get("name", "").endswith(".gz"):
            return asset["url"]
    raise RuntimeError(f"release {tag} in {repo} publishes no .gz asset")


def _download_database(url: str, target: pathlib.Path) -> str:
    """Fetch a gzipped database published by the refresh, or say why it could not."""
    request = urllib.request.Request(url, headers={"User-Agent": "NovatalisTerminal/0.1"})
    token = setting("ER_DB_TOKEN")
    if token:                      # a private repo's release asset needs one
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/octet-stream")
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    # The release asset is gzipped whatever its URL ends in, so the magic number
    # decides rather than the path.
    body = gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
    target.write_bytes(body)
    return f"downloaded {len(body) / 1e6:.0f} MB from the published refresh"


@st.cache_resource(show_spinner="Preparing the database")
def prepare_database() -> str:
    """Put a database in place and report, in one sentence, where it came from."""
    import db
    import history
    import seed

    target = pathlib.Path(db.DB_PATH)

    # A database committed to the repository. Streamlit clones the repo into the
    # container, so this needs no token, no release and no network: the file is
    # already on disk beside the code.
    #
    # It is preferred over whatever the container happens to be holding, because a
    # redeploy can reuse a filesystem: keeping the older copy meant shipping new data
    # and seeing yesterday's, with nothing on screen to say why.
    shipped = ROOT / "data" / "er_tool.db.gz"
    if shipped.exists() and (not target.exists()
                             or shipped.stat().st_mtime > target.stat().st_mtime):
        db.init(str(target))
        target.write_bytes(gzip.decompress(shipped.read_bytes()))
        return f"the database shipped with the app{_shipped_stamp(target)}"

    if target.exists() and target.stat().st_size > 1_000_000:
        return f"the database already in this container{_shipped_stamp(target)}"

    if DB_REPO or DB_URL:
        try:
            token = setting("ER_DB_TOKEN")
            url = (_resolve_release_asset(DB_REPO, DB_TAG, token) if DB_REPO
                   else DB_URL)
            db.init(str(target))
            return _download_database(url, target)
        except Exception as exc:      # a bad tag or token must not take the app down
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
