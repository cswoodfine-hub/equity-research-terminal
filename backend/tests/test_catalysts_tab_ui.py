"""The Catalysts tab (company-scorecard.md 1.5, 5.4), driven server-side through AppTest.

The tab opens on Drivers and risks: the events of the next 12 months beside what could
cost the company, ranked and worded by ``drivers.section``, the same function Key insights
takes its Next from. At stake follows only when a catalyst is priced, and the calendar
sits folded under it. What the tab no longer prints is tested as hard as what it does:
the unpriced lines, the open calendar, the old caption that said every row was Phase 3.

The app tests need the API on localhost:8000 (or ER_API_BASE) and are skipped without it.
The copy checks at the foot need nothing running.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import calendar_view  # noqa: E402
import drivers as D  # noqa: E402

BASE = os.getenv("ER_API_BASE", "http://localhost:8000")
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
ROW = re.compile(
    r'<(a|div) class="dr-row" data-kind="([a-z]+)"[^>]*>'
    r'<span class="dr-lead( date)?">(.*?)(<span class="dr-m"[^>]*>M</span>)?</span>'
    r'<span class="dr-text">(.*?)</span></\1>', re.S)


def _api_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


needs_api = pytest.mark.skipif(not _api_up(), reason="API not running on 8000")


def _get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _patch_button_group_serialisation():
    """The AppTest defect test_comps_tab_ui.py works around: a single-select segmented
    control's session value is a string, and ButtonGroup.indices iterates its characters."""
    from streamlit.testing.v1 import element_tree

    def indices(self):
        values = self.value
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            values = [values]
        labels = [getattr(o, "content", o) for o in self.options]
        out = []
        for v in values:
            label = self.format_func(v) if self.format_func else v
            label = getattr(label, "content", label)
            if label in labels:
                out.append(labels.index(label))
        return out

    element_tree.ButtonGroup.indices = property(indices)


def _open(ticker: str):
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    test = AppTest.from_file(str(APP), default_timeout=300)
    test.query_params["ticker"] = ticker
    test.run()
    return test


@pytest.fixture(scope="module")
def azn_app():
    return _open("AZN")


@pytest.fixture(scope="module")
def crsp_app():
    return _open("CRSP")


def _tab(app, label: str = "Catalysts"):
    found = [t for t in app.tabs if t.label == label]
    assert len(found) == 1, f"no {label} tab"
    return found[0]


def _walk(block):
    """Every element under ``block`` in the order the page draws them, blocks included."""
    for child in getattr(block, "children", {}).values():
        yield child
        yield from _walk(child)


def _markdowns(block) -> list:
    return [str(n.value) for n in _walk(block) if getattr(n, "type", "") == "markdown"]


def _expanders(block) -> list:
    return [n for n in _walk(block) if getattr(n, "type", "") == "expander"]


def _rows(markup: str) -> list:
    """(kind, lead, text, model) for every Drivers or Risks row in the markup."""
    return [(m.group(2), html.unescape(m.group(4)), html.unescape(m.group(6)),
             bool(m.group(5))) for m in ROW.finditer(markup)]


def _visible(markup: str) -> str:
    """The text a reader sees: tags and their attributes (registry titles, verbatim) gone."""
    return html.unescape(re.sub(r"<style>.*?</style>|<[^>]+>", " ", markup, flags=re.S))


def _expected(ticker: str) -> dict:
    """What drivers.section gives for the company from the API's own answers."""
    board = _get("/comps/valuation").get("scorecard") or {}
    company = (board.get("companies") or {}).get(ticker)
    context = _get(f"/companies/{urllib.parse.quote(ticker)}/comps-context")
    feed = _get(f"/changes?ticker={urllib.parse.quote(ticker)}")
    return D.section(ticker, context, company, feed, board.get("today"))


# --- 1. Drivers and risks ----------------------------------------------------------


@needs_api
def test_drivers_and_risks_is_first_on_the_tab(azn_app):
    assert not azn_app.exception
    first = _markdowns(_tab(azn_app))[0]
    assert 'class="sec"' in first and "Drivers and risks" in first
    assert D.SECTION_BASIS in first


@needs_api
def test_the_rows_are_the_ranked_list(azn_app):
    """Drivers' five rows, the rest under "Show n more", and Risks, each as
    drivers.section words it: one list, so Key insights' Next is its first three."""
    tab = _tab(azn_app)
    want = _expected("AZN")
    assert want["state"] == "ok"
    body = "".join(_markdowns(tab))
    drawn = _rows(body)
    shown = [r for r in drawn if r[0] == "driver"][:len(want["drivers"]["shown"])]
    assert [(lead, text) for _k, lead, text, _m in shown] == [
        (r["lead"], r["text"]) for r in want["drivers"]["shown"]]
    assert [m for *_x, m in shown] == [r["model"] for r in want["drivers"]["shown"]]
    risks = [r for r in drawn if r[0] in ("exclusivity", "slip", "pool")]
    assert [(lead, text) for _k, lead, text, _m in risks] == [
        (r["lead"], r["text"]) for r in want["risks"]["rows"]]
    assert f'{D.DRIVERS_TITLE}</span><span class="b">{want["drivers"]["basis"]}' in body
    if want["drivers"]["more"]:
        more = [e for e in _expanders(tab) if e.label == want["drivers"]["more_label"]]
        assert len(more) == 1 and not more[0].proto.expanded
        inside = _rows("".join(_markdowns(more[0])))
        assert [(lead, text) for _k, lead, text, _m in inside] == [
            (r["lead"], r["text"]) for r in want["drivers"]["more"]]


@needs_api
def test_every_risk_row_starts_with_a_number_and_runs_under_15_words(azn_app):
    for kind, lead, text, _m in _rows("".join(_markdowns(_tab(azn_app)))):
        if kind == "driver":
            continue
        assert re.match(r"[\d$]", lead), lead
        assert len(f"{lead} {text}".split()) < 15, text


@needs_api
def test_a_company_with_nothing_ahead_reads_one_muted_line(crsp_app):
    assert not crsp_app.exception
    want = _expected("CRSP")
    body = "".join(_markdowns(_tab(crsp_app)))
    if want["state"] != "empty":
        pytest.skip(f"CRSP has {want['state']} Drivers and risks on this book")
    assert f'<div class="dr-empty">{D.EMPTY.format(T="CRSP")}</div>' in body
    assert not _rows(body)


@needs_api
def test_the_copy_keeps_the_house_style(azn_app, crsp_app):
    for app in (azn_app, crsp_app):
        tab = _tab(app)
        for markup in _markdowns(tab):
            if 'class="cal' in markup:
                continue                  # the grid prints registry titles verbatim
            seen = _visible(markup)
            assert "—" not in seen, seen
            for word in BANNED:
                assert not re.search(rf"\b{word}\b", seen, re.I), (word, seen)


# --- 2. At stake --------------------------------------------------------------------


@needs_api
def test_at_stake_prints_no_unpriced_line(azn_app, crsp_app):
    for ticker, app in (("AZN", azn_app), ("CRSP", crsp_app)):
        body = " ".join(_markdowns(_tab(app)))
        assert "unpriced" not in body
        stakes = _get(f"/companies/{ticker}/catalysts/stakes")
        drawn = ">At stake<" in body
        assert drawn == bool(stakes.get("priced")), ticker
        for row in stakes.get("priced") or []:
            assert html.escape(row["asset_name"], quote=False) in body


# --- 3. The calendar ----------------------------------------------------------------


@needs_api
def test_the_calendar_is_folded_and_its_caption_names_the_phases(azn_app):
    tab = _tab(azn_app)
    folds = [e for e in _expanders(tab) if e.label.startswith("Calendar, 24 months · ")]
    assert len(folds) == 1
    fold = folds[0]
    assert not fold.proto.expanded
    assert "Catalyst calendar for" not in " ".join(_markdowns(tab))
    cal = _get(f"/catalysts?within_days={24 * 31}&ticker=AZN")
    n = len(calendar_view.within(cal, 24))
    assert fold.label == f"Calendar, 24 months · {n} dated {'event' if n == 1 else 'events'}"
    inside = " ".join(_markdowns(fold))
    if n:
        assert 'class="cal"' in inside
        assert f"{n} ahead in the next 24 months." in inside
        assert "Phase 1/2, Phase 2 and Phase 3" in inside
        assert "from a Phase 3 primary completion" not in inside
        assert len(fold.dataframe) == 1 and len(fold.dataframe[0].value) == n


@needs_api
def test_competition_by_indication_is_not_on_the_tab(azn_app):
    assert "Competition by indication" not in " ".join(_markdowns(_tab(azn_app)))


# --- 4. The copy, nothing running ---------------------------------------------------

TODAY = dt.date(2026, 10, 1)


def _cat(date: str, confidence: str = "estimated") -> dict:
    return {"expected_date": date, "date_confidence": confidence,
            "catalyst_type": "data readout", "title": "Phase 3, a study"}


def test_the_caption_is_the_one_of_8_5():
    items = [_cat("2026-11-03"), _cat("2027-02", "month")]
    assert calendar_view.caption(items, 24, TODAY) == (
        "2 ahead in the next 24 months. 1 carry a month and no day, which is all the "
        "registry gives, so they sit in the month rather than on a date in it. Readouts "
        "come from the primary completion dates of Phase 1/2, Phase 2 and Phase 3 "
        "trials, regulatory dates from filings announcing an FDA acceptance, and both "
        "are rebuilt on every refresh.")
    assert calendar_view.caption([_cat("2026-11-03")], 24, TODAY).startswith(
        "1 ahead in the next 24 months. Readouts come from")


def test_the_fold_counts_what_the_grid_draws():
    items = [_cat("2026-11-03"), _cat("2027-02", "month"), _cat("2031-01")]
    assert calendar_view.expander_label(items, 24, TODAY) == (
        "Calendar, 24 months · 2 dated events")
    assert calendar_view.expander_label(items[:1], 24, TODAY) == (
        "Calendar, 24 months · 1 dated event")
    assert calendar_view.expander_label([], 24, TODAY) == (
        "Calendar, 24 months · 0 dated events")


def test_the_fixed_copy_keeps_the_house_style():
    for text in (calendar_view.SOURCES, calendar_view.caption([_cat("2027-02", "month")],
                                                              24, TODAY),
                 D.SECTION_TITLE, D.SECTION_BASIS, D.DRIVERS_TITLE, D.RISKS_TITLE,
                 D.EMPTY, D.CONTEXT_FAILED):
        assert "—" not in text
        assert not any(re.search(rf"\b{w}\b", text, re.I) for w in BANNED)
    for heading in (D.SECTION_TITLE, D.DRIVERS_TITLE, D.RISKS_TITLE):
        first, *rest = heading.split()
        assert first[:1].isupper() and all(w == w.lower() for w in rest), heading
