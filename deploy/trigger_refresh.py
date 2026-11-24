#!/usr/bin/python3
"""Ask GitHub to start the scheduled refresh now, from this Mac, at the hour it is due.

GitHub's own scheduler fires the refresh workflow late: over the two weeks to
2026-11-24 the 06:00 UTC run was created between 12:45 and 18:00 UTC, and the 10:00
UTC pulse pass between 17:35 and 21:57. The job starts the minute it is created, so
nothing inside the workflow can bring it forward. A workflow_dispatch request is acted
on within a minute, so a launchd job on this Mac sends one at the hour the run is due
and GitHub's schedule stays as the backup for a day the Mac is off.

    trigger_refresh.py refresh      the whole-universe refresh
    trigger_refresh.py pulse        the daily pulse pass alone
    add --dry-run to check the token and what would be sent, and send nothing

Before sending, it asks GitHub for today's runs and sends nothing where a run of the
same kind has already succeeded today or is queued or running, so a Mac that wakes at
noon does not start a second refresh behind one GitHub has already done. The workflow
does the same check the other way round (its gate job).

The token is a fine-grained GitHub token limited to this one repository with the
Actions permission set to read and write. It is read from the login keychain, never
from a file in the repository, which lives in a synced folder:

    security add-generic-password -a "$USER" -s novatalis-lens-dispatch -w

That prompts for the token without echoing it. Nothing here prints the token, and a
response GitHub sends back is logged by its status only.

Standard library only, so it runs on the system Python with no virtual environment.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = os.getenv("NOVATALIS_REPO", "cswoodfine-hub/equity-research-terminal")
WORKFLOW = "refresh.yml"
REF = os.getenv("NOVATALIS_REF", "main")
SERVICE = "novatalis-lens-dispatch"
API = "https://api.github.com"
# The run-name the workflow gives each kind (.github/workflows/refresh.yml); the check
# for a run already done today is made on it.
TITLES = {"refresh": "Daily refresh", "pulse": "Daily pulse"}
ACTIVE = ("queued", "in_progress", "waiting", "requested", "pending")
TIMEOUT_S = 30


def token_from_keychain(service: str = SERVICE) -> str | None:
    """The token from the login keychain, or None where there is none."""
    try:
        got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service,
                              "-w"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (got.stdout or "").strip()
    return value if got.returncode == 0 and value else None


def request(method: str, path: str, token: str, body: dict | None = None) -> tuple:
    """(status, parsed body or None). A failure to connect is status 0."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "novatalis-lens-trigger"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def done_today(runs: list, kind: str, today: str) -> dict | None:
    """The run of ``kind`` created today (UTC) that succeeded or is still going, if any."""
    for run in runs:
        if (run.get("display_title") == TITLES[kind]
                and str(run.get("created_at") or "")[:10] == today
                and (run.get("conclusion") == "success" or run.get("status") in ACTIVE)):
            return run
    return None


def main(argv: list, *, token_fn=token_from_keychain, request_fn=request,
         now=None, out=print) -> int:
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry-run" in argv
    stamp = (now or dt.datetime.now(dt.timezone.utc))
    if len(args) != 1 or args[0] not in TITLES:
        out("usage: trigger_refresh.py refresh|pulse [--dry-run]")
        return 64
    kind = args[0]
    log = lambda msg: out(f"{stamp:%Y-%m-%d %H:%M:%S} UTC {kind}: {msg}")

    token = token_fn()
    if not token:
        log(f"no token in the login keychain under {SERVICE}; nothing sent")
        return 2

    status, body = request_fn("GET", f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"
                              f"?per_page=30", token)
    if status != 200 or not isinstance(body, dict):
        log(f"could not read today's runs (HTTP {status}); nothing sent")
        return 3
    already = done_today(body.get("workflow_runs") or [], kind, f"{stamp:%Y-%m-%d}")
    if already:
        log(f"a run of this kind is already "
            f"{already.get('conclusion') or already.get('status')} today "
            f"(run {already.get('id')}); nothing sent")
        return 0

    payload = {"ref": REF, "inputs": {"pulse_only": "true" if kind == "pulse" else "false"}}
    if dry:
        log(f"dry run: would ask for {WORKFLOW} on {REF} with {payload['inputs']}")
        return 0
    status, _ = request_fn("POST", f"/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
                           token, payload)
    if status == 204:
        log(f"asked GitHub to start {TITLES[kind].lower()} on {REF}")
        return 0
    log(f"GitHub refused the request (HTTP {status}); GitHub's own schedule is the backup")
    return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
