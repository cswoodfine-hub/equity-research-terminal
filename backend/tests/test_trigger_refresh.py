"""The Mac's on-time trigger for the refresh (deploy/trigger_refresh.py), and the
workflow it talks to."""

import datetime as dt
import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("trigger_refresh",
                                              ROOT / "deploy" / "trigger_refresh.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

NOW = dt.datetime(2026, 11, 24, 6, 0, tzinfo=dt.timezone.utc)
SECRET = "github_pat_NEVERPRINTED"


class GitHub:
    """A stand-in for the API: today's runs, and every request it was sent."""

    def __init__(self, runs=(), list_status=200, dispatch_status=204):
        self.runs, self.list_status, self.dispatch_status = list(runs), list_status, dispatch_status
        self.sent = []

    def __call__(self, method, path, token, body=None):
        assert token == SECRET
        self.sent.append((method, path, body))
        if method == "GET":
            return self.list_status, {"workflow_runs": self.runs}
        return self.dispatch_status, None


def _run(argv, github, token=SECRET):
    lines = []
    code = T.main(argv, token_fn=lambda: token, request_fn=github, now=NOW,
                  out=lines.append)
    return code, lines


def test_a_refresh_is_asked_for_when_none_has_run_today():
    gh = GitHub(runs=[{"display_title": "Daily refresh", "created_at": "2026-11-23T17:48:00Z",
                       "conclusion": "success", "status": "completed", "id": 1}])
    code, lines = _run(["refresh"], gh)
    assert code == 0
    method, path, body = gh.sent[-1]
    assert method == "POST" and path.endswith("/actions/workflows/refresh.yml/dispatches")
    assert body == {"ref": "main", "inputs": {"pulse_only": "false"}}
    assert "asked GitHub to start daily refresh" in lines[-1]


def test_a_pulse_pass_asks_for_the_pulse_alone():
    gh = GitHub()
    assert _run(["pulse"], gh)[0] == 0
    assert gh.sent[-1][2]["inputs"] == {"pulse_only": "true"}


@pytest.mark.parametrize("conclusion,status", [("success", "completed"),
                                               (None, "in_progress"), (None, "queued")])
def test_nothing_is_sent_when_that_kind_has_run_or_is_running_today(conclusion, status):
    gh = GitHub(runs=[{"display_title": "Daily refresh", "created_at": "2026-11-24T05:59:00Z",
                       "conclusion": conclusion, "status": status, "id": 7}])
    code, lines = _run(["refresh"], gh)
    assert code == 0 and [m for m, _, _ in gh.sent] == ["GET"]
    assert "nothing sent" in lines[-1] and "run 7" in lines[-1]


def test_a_failed_run_today_or_a_run_of_the_other_kind_does_not_stop_it():
    gh = GitHub(runs=[
        {"display_title": "Daily refresh", "created_at": "2026-11-24T05:00:00Z",
         "conclusion": "failure", "status": "completed", "id": 8},
        {"display_title": "Daily pulse", "created_at": "2026-11-24T05:30:00Z",
         "conclusion": "success", "status": "completed", "id": 9}])
    _run(["refresh"], gh)
    assert gh.sent[-1][0] == "POST"


def test_a_dry_run_reads_and_sends_nothing():
    gh = GitHub()
    code, lines = _run(["refresh", "--dry-run"], gh)
    assert code == 0 and [m for m, _, _ in gh.sent] == ["GET"]
    assert "dry run" in lines[-1]


def test_with_no_token_nothing_is_asked_of_github():
    gh = GitHub()
    code, lines = _run(["refresh"], gh, token=None)
    assert code == 2 and gh.sent == [] and "no token" in lines[-1]


def test_a_refused_request_says_so_and_names_the_backup():
    code, lines = _run(["refresh"], GitHub(dispatch_status=403))
    assert code == 4 and "HTTP 403" in lines[-1] and "backup" in lines[-1]
    code, lines = _run(["refresh"], GitHub(list_status=401))
    assert code == 3 and "HTTP 401" in lines[-1]


def test_the_token_is_never_printed():
    for argv, gh in ((["refresh"], GitHub()), (["refresh"], GitHub(dispatch_status=500)),
                     (["pulse", "--dry-run"], GitHub())):
        _, lines = _run(argv, gh)
        assert all(SECRET not in line for line in lines)


def test_an_unknown_kind_is_refused():
    assert _run(["everything"], GitHub())[0] == 64


# --- the workflow it talks to -------------------------------------------------------------
WORKFLOW = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()


def test_the_workflow_names_its_runs_as_the_trigger_expects():
    assert "'Daily pulse' || 'Daily refresh'" in WORKFLOW
    assert set(T.TITLES.values()) == {"Daily refresh", "Daily pulse"}
    assert "pulse_only:" in WORKFLOW and "workflow_dispatch:" in WORKFLOW


def test_every_test_of_which_schedule_fired_names_the_pulse_cron_exactly():
    crons = re.findall(r"- cron: '([^']+)'", WORKFLOW)
    assert len(crons) == 2
    pulse = next(c for c in crons if c.endswith("1-5"))
    named = re.findall(r"github\.event\.schedule == '([^']+)'", WORKFLOW)
    assert named and set(named) == {pulse}, (named, pulse)
    assert not any(c.startswith("0 ") for c in crons), "the top of the hour is GitHub's busiest"


def test_the_refresh_waits_on_the_gate():
    assert "needs: gate" in WORKFLOW
    assert "if: needs.gate.outputs.run == 'true'" in WORKFLOW
