"""Streamlit terminal: key insights, prices, financials, comps, pipeline, and LOE.

A thin client over the FastAPI JSON endpoints. One company is selected in the sidebar
and drives every per-company view, so the feed, the note, and the horizon rail always
describe the same company.

Presentation rules live in ``theme`` and the horizon rail in ``rail``. Valuation ratios
resolve only for US filers (shares outstanding and USD reporting); those cells show a
dash, which means no free data rather than zero.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import importlib
import json
import re
import os
from collections import Counter
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

import calendar_view
import price_chart
import revenue_mix
import scorecard_chart
import treemap
import theme as T
import trend as trend_module
import universe_page
from components import charts as CH
from components import approvnav
from components import covnav
from components import enginepick
from components import clicklist
from components import compsval
from components import prodcards
from components import drawchart
from components import render as R
from components import tokens as TK

# A running server re-reads this script on a save, but not a module the script imports
# when the checkout sits under a dot-directory, as a worktree does: Streamlit's watcher
# skips those. So the script can be newer than the wrapper held in memory, and would
# call it with arguments it does not take. A wrapper behind the revision this script
# is written against is reloaded once, here.
if getattr(compsval, "REVISION", 0) < 4:
    compsval = importlib.reload(compsval)

# Overridable so run.sh can point a frontend at whichever API port it started.
DEFAULT_API = os.getenv("ER_API_BASE", "http://localhost:8000")
DEFAULT_TICKER = "LLY"

# The companies whose Universe overview is the redesigned command centre (universe_page,
# universe_cc). Every other company keeps today's overview exactly; rolling out is one
# edit to this set.
_REDESIGN_TICKERS = {"AZN"}


def _universe_redesigned(ticker: str, view: str) -> bool:
    """True when the Universe tab draws the redesigned overview for ``ticker``: the
    Overview view of a company in the set. Markets, Policy and the as-of branch stay."""
    return view == "Overview" and ticker in _REDESIGN_TICKERS

# The landing page renders inside a component iframe, which inherits none of the host
# page's CSS variables, so the tokens it needs are handed across. One source of truth
# stays in tokens.py.
LANDING_TOKENS = {
    "ground": TK.GROUND, "panel": TK.PANEL, "rule": TK.RULE,
    "rule-strong": TK.RULE_STRONG, "text": TK.TEXT, "muted": TK.MUTED,
    "up": TK.UP, "down": TK.DOWN, "flag": TK.FLAG,
    "orange-book": TK.ORANGE_BOOK, "purple-book": TK.PURPLE_BOOK,
    "font-ui": TK.FONT_UI, "font-mono": TK.FONT_MONO, "font-prose": TK.FONT_PROSE,
}
# The Comps valuation view is the same kind of iframe, with more of the palette: the faint
# rule, the narrow face, the phase ramp and the spacing base. It has no colour of its own:
# selection and focus are derived from these tokens in research.css, as on every other tab.
# "phase-filed" is left out on purpose: its value is the flag colour, which this view keeps
# for uncertainty alone. Built only from tokens.py, so there is still one source of truth.
COMPS_TOKENS = {
    **LANDING_TOKENS,
    "rule-faint": TK.RULE_FAINT,
    "font-ui-narrow": TK.FONT_UI_NARROW,
    "phase-preclinical": TK.PHASE_RAMP["preclinical"],
    "phase-1": TK.PHASE_RAMP["Phase 1"], "phase-2": TK.PHASE_RAMP["Phase 2"],
    "phase-3": TK.PHASE_RAMP["Phase 3"], "phase-approved": TK.PHASE_RAMP["approved"],
    "space": f"{TK.SPACE}px", "radius": f"{TK.RADIUS}px",
    "radius-small": f"{TK.RADIUS_SMALL}px",
}
PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]
# How long a headline runs before it is cut, chosen to hold the box to two lines at the
# width six of them take. The full text is always the first row of the box's own detail,
# so the cut costs a click rather than the fact.
_LEAD_CHARS = 76

# The window the coverage grid reads, and how it is named. A year rather than a quarter,
# because the map beside it already reads a quarter and two views of one window are one
# view printed twice.
COVERAGE_DAYS = 365
COVERAGE_MONTHS = 12

# Only used to name the map's window in the coverage note on the rare render where
# the map itself did not draw. The map's own payload states it and overrides this.
MARKETMAP_FALLBACK_DAYS = 90

# How many forward-dated boxes fit before the list stops being a view and starts being a
# table. The rest are on each company's own Catalysts tab. Two across in half the page,
# so an even count fills its last row.
_AHEAD_SHOWN = 6

# The same idea on Key insights, across the full page rather than half of it. Six, the
# count the universe headline row uses, because it is the largest that still divides into
# two even rows at the narrow width, and three rows do not leave room for the note. What
# is cut is the oldest; the company's own Catalysts, Portfolio and News tabs carry it.
_INSIGHT_SHOWN = 6

# Detected changes listed under the two bands, split across two columns. Twelve fills the
# width at the height a tall screen leaves and stops the list turning into the whole page
# on a company with a busy week; the section count states the true total either way.
_CHANGES_SHOWN = 12

# Forward-dated boxes in the column beside the note. Four rather than the six the
# universe tab shows, because these carry registry trial titles that wrap to four lines
# in a half-width box, and a third row of them was the one thing pushing this tab off the
# screen. The section count still states the true total, and the Catalysts tab has them
# all.
_INSIGHT_AHEAD = 4


# What a filing states when there is no trial yet, most advanced first. Mirrors
# pipeline_filing.STAGES: these are headings a programme sits under, below every phase.
FILING_STAGES = ["IND cleared", "IND-enabling", "Development candidate", "Preclinical",
                 "Discovery"]
# Charts collapse the two seamless phases into the phase each one reaches, which is the
# convention elsewhere in the app: the Key insights strip already counts Phase 2/3 as
# late phase. Six ordinal steps of one hue is more than colour can carry, and these two
# are the pair worth losing, being 12.3% of the universe between them.
#
# Merged, never dropped. Deleting them would hide 316 trials, and 19% of Merck's
# pipeline. The API still returns all six, so nothing downstream loses the distinction
# and this is a display choice that can be reversed here alone.
PHASE_MERGE = {"Phase 1/2": "Phase 2", "Phase 2/3": "Phase 3"}
# Phase 4 runs after approval, so it is not pipeline and the charts leave it out. What
# is in it says so: continuation studies supplying drug to patients already on it,
# local registration studies for products approved elsewhere, and post-marketing safety
# work on things already sold. None of it is a future approval, and counting it stated
# a pipeline 4.3% larger than there is.
POST_APPROVAL = ("Phase 4",)
DISPLAY_PHASES = [p for p in PIPELINE_PHASES
                  if p not in PHASE_MERGE and p not in POST_APPROVAL]
# Price chart windows, widest last. None means every session held. Windows wider than
# the stored history are hidden rather than drawn short.
PRICE_WINDOWS = [("1M", 31), ("3M", 92), ("6M", 183), ("1Y", 365), ("5Y", 1826),
                 ("Max", None)]
# The price chart's height. The component takes a fixed pixel height rather than sizing
# itself, so this is set against what the tab has left once the heading, the one control
# row, the window and figures row and the legend are drawn: enough that the chart is the
# tab and low enough that it ends above the fold on a laptop.
PRICE_CHART_HEIGHT = 430
# Bar interval, coarsest ask first as a trader reads them. Each maps to (base series held
# on the backend, pandas resample rule or None, is-intraday). 15m/30m resample from the
# 5m base, 4H from the 60m base, 1W/1M from daily; the rest are a base as-is.
PRICE_INTERVALS = ["5 min", "15 min", "30 min", "1H", "4H", "1D", "1W", "1M"]
_INTERVAL_BASE = {
    "5 min": ("5m", None, True), "15 min": ("5m", "15min", True),
    "30 min": ("5m", "30min", True), "1H": ("60m", None, True),
    "4H": ("60m", "4h", True), "1D": ("1d", None, False),
    "1W": ("1d", "W", False), "1M": ("1d", "ME", False),
}
# Sessions in the Key insights sparkline. Trading sessions rather than calendar days,
# so a bank holiday or a weekend does not silently shorten the line.
SPARK_SESSIONS = 5
CATALYST_TYPES = ["PDUFA", "data readout", "EMA decision", "AdCom", "conference", "other"]
# Quarters in the growth-against-margin panel: the most recent year, one bar per quarter.
# The registry page for a trial, keyed by its NCT id.
# Months of catalyst calendar. Two years covers the readout horizon without a control
# to set it: the dates inside it are estimates anyway, so a tighter window would be
# false precision about which of them matter.
CALENDAR_MONTHS = 24


# --- Transport ----------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def api_get(base: str, path: str, timeout: int = 30):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(base: str, path: str, timeout: int = 300):
    request = urllib.request.Request(base.rstrip("/") + path, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_json(base: str, path: str, payload: dict, timeout: int = 60):
    """POST with a JSON body. The forecast editor is the first write-back surface the
    app has had, so this is the first caller."""
    request = urllib.request.Request(
        base.rstrip("/") + path, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rerun_here():
    """Rerun only the fragment this is called from, so a click inside one tab does not
    redraw the other eleven. Streamlit allows that only during the fragment's own rerun;
    when the fragment is running as part of a full-page run, the page reruns instead."""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


# --- Presentation helpers -----------------------------------------------
def section(label: str, count=None, basis: str = ""):
    """A section rule, optionally carrying the period its figures are measured over.

    The basis is a chip rather than more grey text because of one specific misreading:
    the financials tab puts a quarter's income statement directly above a year's cash
    flow, in the same tiles at the same weight, and the only thing separating 25.3bn of
    quarterly revenue from 19.7bn of annual free cash flow was a muted line at the far
    right of the rule. Two bases stacked need to say so where the eye already is.
    """
    tail = f'<span class="sec-count">{count}</span>' if count is not None else ""
    chip = (f'<span class="sec-basis">{html_escape(basis)}</span>' if basis else "")
    st.markdown(f'<div class="sec"><span class="sec-label">{label}</span>{chip}'
                f'{tail}</div>', unsafe_allow_html=True)


def note_markup(text: str) -> str:
    """The folded byline as a string, for callers that put it inside another block."""
    return (f'<details class="note-d"><summary>notes</summary>'
            f'<div class="byline">{text}</div></details>')


def note(text: str):
    """A byline folded away, for a view that has to fit a screen.

    The Universe tab is read at a glance and its explanations are long, because most of
    what they say is what a figure is not: area is not market capitalisation, a readout
    date is not a commitment. Deleting them would buy the height by making the page less
    honest, so they collapse to one line instead and open where a reader wants them.
    """
    st.markdown(note_markup(text), unsafe_allow_html=True)


def state(title: str, detail: str, error: bool = False):
    """An empty state says what to do next. An error says what happened and how to fix."""
    st.markdown(
        f'<div class="state{" err" if error else ""}"><div class="t">{title}</div>'
        f'<div class="d">{detail}</div></div>', unsafe_allow_html=True)


def run_refresh(base: str, path: str, key: str, spinner: str):
    """Trigger a refresh and keep the per-source result for the freshness strip."""
    with st.spinner(spinner):
        try:
            st.session_state[key] = api_post(base, path)
            st.session_state["last_run"] = st.session_state[key]
            api_get.clear()
            # The comps valuation payload and the focal context have their own minute of
            # cache; a refresh is new data.
            _comps_valuation_payload.clear()
            _comps_context.clear()
        except (urllib.error.URLError, OSError) as exc:
            st.session_state["refresh_error"] = str(exc)


def _downsample(values: list, labels: list, cap: int = 240):
    """Evenly thin a long series for display. The stored data is untouched; a
    5-year daily line at full grain would put five thousand hover slots in the
    SVG for no legible gain."""
    if len(values) <= cap:
        return values, labels
    step = len(values) / cap
    idx = [int(i * step) for i in range(cap)]
    if idx[-1] != len(values) - 1:
        idx[-1] = len(values) - 1        # the latest close must survive thinning
    return [values[i] for i in idx], [labels[i] for i in idx]


FEED_SECTIONS = (
    ("filing", "Material events",
     "8-K items that move a case: acquisitions, agreements, impairments. Exhibits and "
     "shareholder votes are filtered out."),
    ("change", "Changes since the last refresh",
     "Snapshot diffs: trial status and date moves, new filings, new approvals. Dated "
     "by when the event happened, not when it was detected."),
    ("catalyst", "Catalysts inside 60 days",
     "Phase 3 readouts derived from registry completion dates, plus anything curated."),
    ("loe", "Loss of exclusivity ahead",
     "Latest protection per marketed product, next 24 months. Orphan exclusivity is "
     "not a cliff."),
)


def html_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _headline_revenue(prof: dict):
    """The figure that leads a profile: the latest full year, or the latest quarter where
    there is no year at all.

    The year is preferred even when a quarter is newer, because this number is read
    against the same number on other products and a quarter beside a year compares a
    product to a quarter of itself. The quarter is here for the case that has no year:
    Empaveli came to Biogen in May 2026 and is in no annual data set until 2027, and a
    figure the company printed in July beats "no free data".
    """
    annual = [r for r in (prof.get("revenue") or []) if r.get("value") is not None]
    if annual:
        return max(annual, key=lambda r: r["fiscal_year"])
    quarters = [r for r in (prof.get("quarterly_revenue") or [])
                if r.get("value") is not None and r.get("period") != "H1"]
    return max(quarters, key=lambda r: r["period_end"] or "") if quarters else None


def _money(row: dict) -> str:
    """A revenue figure at the scale it reads at. A quarter of a small product is tens of
    millions, and "0.03 bn" is a number a reader has to decode rather than read."""
    value, unit = row["value"], row.get("unit") or ""
    if abs(value) >= 1e9:
        return f'{T.num(value / 1e9, 2)} {unit} bn'
    return f'{T.num(value / 1e6, 1)} {unit} m'


def _period_label(row: dict) -> str:
    """FY2025, or Q2 2026 for a quarter."""
    period = row.get("period") or "FY"
    return f'FY{row["fiscal_year"]}' if period == "FY" else f'{period} {row["fiscal_year"]}'


def _prof_rows(pairs) -> str:
    """A block of key/value rows for the profile, skipping any pair with no value so an
    empty field never draws a blank row."""
    out = []
    for k, v, *rest in pairs:
        if v is None or v == "":
            continue
        cls = " none" if (rest and rest[0]) else ""
        out.append(f'<div class="prof-row"><span class="prof-k">{html_escape(k)}</span>'
                   f'<span class="prof-v{cls}">{html_escape(v)}</span></div>')
    return "".join(out)


def _render_product_profile(api_base, ticker, product, today) -> None:
    """The fact profile for one product: sourced facts on the left, the analyst's curated
    market-size / peak-sales / competitor view on the right, editable and saved back. Read
    from the profile endpoint, so it always reflects what is actually on file."""
    aid = product["asset_id"]
    try:
        prof = api_get(api_base, f"/companies/{ticker}/product/{aid}")
    except Exception:                       # a stale id or a backend hiccup: drop it
        st.session_state.pop("profile_asset", None)
        return

    head, closer = st.columns([6, 1])
    with head:
        section(f"{prof['brand']} fact profile", prof.get("modality") or "")
    with closer:
        if st.button("close", key=f"pf_close_{aid}", use_container_width=True):
            st.session_state.pop("profile_asset", None)
            _rerun_here()

    loe = prof.get("loe") or {}
    dem = prof.get("demand")
    rev = _headline_revenue(prof)
    loe_txt = (f'{loe.get("loe_year")}' if loe.get("loe_year") else "—")
    if loe.get("loe_earliest_year") and loe.get("loe_year") \
            and loe["loe_earliest_year"] != loe["loe_year"] \
            and "molecule" in (prof.get("modality") or "").lower():
        loe_txt = f'{loe["loe_earliest_year"]}–{loe["loe_year"]}'
    # A date that has gone is an event, not a countdown, and the heading says so rather
    # than printing a range that reads as protection the product still has.
    if loe.get("loe_past") and loe.get("loe_year"):
        loe_txt = f'lapsed {loe["loe_year"]}'
    elif loe.get("loe_past"):
        loe_txt = "lapsed"
    # The later patents sit beside the date rather than inside it. A method-of-use patent
    # covers one indication and a generic carves it out of the label; a second molecule
    # patent claims a salt or a form. Neither holds the market once the molecule is open,
    # and both are worth seeing.
    loe_note = html_escape(loe.get("basis") or "no expiry on file")
    if loe.get("loe_identifier"):
        loe_note += f' {html_escape(str(loe["loe_identifier"]))}'
    tail = []
    if loe.get("later_substance_year"):
        tail.append(f'molecule patents to {loe["later_substance_year"]}')
    if loe.get("use_patent_year") and loe.get("loe_year") \
            and loe["use_patent_year"] > loe["loe_year"]:
        tail.append(f'use patents to {loe["use_patent_year"]}')
    if tail:
        loe_note += " &middot; " + ", ".join(tail)
    stats = (
        '<div class="pos">'
        f'<div><span class="k">latest revenue</span>'
        f'<span class="v{"" if rev else " none"}">'
        f'{_money(rev) if rev else "no free data"}'
        f'</span><span class="sub">{_period_label(rev) if rev else "SEC tags few products"}</span></div>'
        f'<div><span class="k">exclusivity</span>'
        f'<span class="v{"" if loe.get("loe_year") else " none"}">{loe_txt}</span>'
        f'<span class="sub">{loe_note}</span></div>'
        f'<div><span class="k">Medicare spend</span>'
        f'<span class="v{"" if dem else " none"}">'
        f'{"$" + T.num(dem["spend"] / 1e9, 2) + " bn" if dem else "no free data"}</span>'
        f'<span class="sub">{html_escape(_medicare_tile_sub(dem))}</span></div>'
        f'<div><span class="k">first approval</span>'
        f'<span class="v{"" if prof.get("first_approval") else " none"}">'
        f'{(prof.get("first_approval") or "—")[:10]}</span>'
        f'<span class="sub">{html_escape((prof.get("generic") or "").lower())}</span></div>'
        '</div>')
    if prof.get("summary"):
        # The label's own first sentence, which says what the drug is and what it
        # treats. Not written here, so a product with no label carries no summary.
        #
        # A sentence, except where the label does not write in sentences. Darzalex
        # Faspro's runs to two hundred words of indications joined by commas and filled
        # the whole column, so a long one is folded to its opening and opens in place.
        _sum = prof["summary"]
        if len(_sum) > 260:
            _head = _sum[:230].rsplit(" ", 1)[0]
            st.markdown(
                f'<details class="prof-summary long"><summary>{html_escape(_head)}'
                f'<span class="more">more</span></summary>'
                f'{html_escape(_sum)}</details>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="prof-summary">{html_escape(_sum)}</div>',
                        unsafe_allow_html=True)
    st.markdown(stats, unsafe_allow_html=True)

    html = ['<div class="prof">']
    # Revenue history, when the SEC tags more than the latest year.
    if len(prof.get("revenue") or []) > 1:
        html.append('<div class="prof-sub">revenue, tagged years</div>')
        html.append(_prof_rows(
            [(f'FY{r["fiscal_year"]}', f'{T.num(r["value"] / 1e9, 2)} {r.get("unit") or ""} bn')
             for r in prof["revenue"]]))
    # The quarters, read from the earnings exhibit. Kept in their own block rather than
    # merged into the years above: a quarter printed beside a year reads as a collapse.
    quarters = [r for r in (prof.get("quarterly_revenue") or []) if r["period"] != "H1"]
    if quarters:
        html.append('<div class="prof-sub">revenue, quarters stated</div>')
        html.append(_prof_rows(
            [(_period_label(r), _money(r)) for r in quarters]))
    # Approvals, one line each with the approved indication.
    if prof.get("approvals"):
        html.append('<div class="prof-sub">approvals</div>')
        for ap in prof["approvals"]:
            ind = (ap.get("indication_text") or "").strip()
            ind = ind if len(ind) <= 90 else ind[:89] + "…"
            html.append(
                f'<div class="prof-line"><span class="d">{(ap.get("approval_date") or "")[:10]}</span>'
                f'{html_escape(ap.get("application_number") or "")}'
                f'{" · " + html_escape(ind) if ind else ""}</div>')
    # The patent stack. A product does not have a patent, it has a stack of them, and
    # the stack is why two pages could once disagree about Farxiga: dapagliflozin's own
    # patent went in April 2026 while the book also lists a second molecule patent to
    # 2030 and method-of-use patents for the heart failure and kidney indications to
    # 2041. Showing it is what makes the date arguable rather than mysterious.
    #
    # The one that sets the date leads and is marked. The rest are folded, because a
    # reader who wants the cliff wants one line and a reader who doubts it wants all
    # twenty-one.
    patents = prof.get("patents") or []
    if patents:
        governing = [p for p in patents if p.get("governs")]
        rest = [p for p in patents if not p.get("governs")]
        html.append(f'<div class="prof-sub">patents and exclusivity &middot; '
                    f'{len(patents)} on file</div>')

        def _patent_row(p, lead=False):
            kind = p.get("kind") or p.get("type") or ""
            base = (p.get("expiry") or "")[:10]
            eff = (p.get("effective") or "")[:10]
            ped = (f'<span class="pt-ped">+6mo to {eff}</span>'
                   if p.get("extended_to") and p["extended_to"] != base else "")
            mark = ('<span class="pt-gov">sets the date</span>' if lead else "")
            return (f'<div class="prof-row pt{" gov" if lead else ""}">'
                    f'<span class="prof-k">{html_escape(p.get("identifier") or "—")}'
                    f'<span class="pt-kind">{html_escape(kind)}</span></span>'
                    f'<span class="prof-v">{html_escape(base)}{ped}{mark}</span></div>')

        for p in governing:
            html.append(_patent_row(p, lead=True))
        if rest:
            html.append(f'<details class="pt-more"><summary>{len(rest)} more, '
                        f'to {html_escape((rest[-1].get("effective") or "")[:4])}'
                        f'</summary>')
            html.extend(_patent_row(p) for p in rest)
            html.append("</details>")
        if not governing:
            note_txt = ("no drug substance patent flagged, so the date is the latest "
                        "listed expiry")
            html.append(f'<div class="prof-row"><span class="prof-k">basis</span>'
                        f'<span class="prof-v none">{note_txt}</span></div>')

    # Label, supplements, challenges: the regulatory footprint.
    lab = prof.get("label")
    if lab:
        html.append('<div class="prof-sub">label</div>')
        html.append(_prof_rows([
            ("approved indications", str(lab.get("indication_count"))
             if lab.get("indication_count") is not None else None),
            ("label updated", (lab.get("effective_time") or "")[:10] or None),
            ("population", (lab.get("population_text") or "")[:60] or None)]))
    if prof.get("supplement_count"):
        html.append('<div class="prof-sub">efficacy supplements</div>')
        for s in prof.get("supplements") or []:
            d = (s.get("description") or "").strip()
            d = d if len(d) <= 80 else d[:79] + "…"
            html.append(f'<div class="prof-line"><span class="d">'
                        f'{(s.get("approval_date") or "")[:10]}</span>{html_escape(d)}</div>')
    if prof.get("challenges"):
        html.append('<div class="prof-sub">Paragraph IV challenges</div>')
        html.append(_prof_rows([
            (c.get("application_number") or "application",
             (c.get("first_submission") or "")[:10] or "filed")
            for c in prof["challenges"]]))
    # The drug's own studies. For a marketed product these are the label-expansion
    # trials that drive the next indication; for a pipeline compound they are the
    # whole programme.
    if prof.get("trials"):
        phases = prof.get("trials_by_phase") or {}
        phase_txt = ", ".join(f'{n} {ph}' for ph, n in sorted(phases.items()))
        html.append(f'<div class="prof-sub">trials · {prof["trial_count"]} '
                    f'{"· " + html_escape(phase_txt) if phase_txt else ""}</div>')
        for tr in prof["trials"]:
            title = (tr.get("title") or "").strip()
            title = title if len(title) <= 78 else title[:77].rstrip() + "…"
            due = (tr.get("primary_completion_date") or "")[:10] or "no date"
            link = (f'<a href="https://clinicaltrials.gov/study/{html_escape(tr["nct_id"])}"'
                    f' target="_blank" rel="noopener">{html_escape(title)}</a>')
            html.append(
                f'<div class="prof-line" title="{html_escape(tr.get("title") or "")} '
                f'({html_escape(tr.get("nct_id") or "")})">'
                f'<span class="d">{html_escape(due)}</span>'
                f'<span class="ph">{html_escape(tr.get("phase") or "")}</span> {link}'
                f'</div>')
    if prof.get("completed_trials"):
        html.append(
            f'<div class="prof-sub">completed with results &middot; '
            f'{prof.get("completed_count")}</div>')
        for tr in prof["completed_trials"]:
            title = (tr.get("title") or "").strip()
            title = title if len(title) <= 74 else title[:73].rstrip() + "…"
            done = (tr.get("completion_date") or "")[:10] or "no date"
            outcome = (tr.get("primary_outcome") or "").strip()
            outcome = outcome if len(outcome) <= 64 else outcome[:63].rstrip() + "…"
            link = (f'<a href="https://clinicaltrials.gov/study/'
                    f'{html_escape(tr["nct_id"])}?tab=results" target="_blank"'
                    f' rel="noopener">{html_escape(title)}</a>')
            html.append(
                f'<div class="prof-line" title="{html_escape(tr.get("title") or "")} '
                f'({html_escape(tr.get("nct_id") or "")})">'
                f'<span class="d">{html_escape(done)}</span>'
                f'<span class="ph">{html_escape(tr.get("phase") or "")}</span> {link}'
                + (f'<span class="ep">{html_escape(outcome)}</span>' if outcome else "")
                + '</div>')
    if prof.get("catalysts"):
        html.append('<div class="prof-sub">upcoming catalysts</div>')
        for c in prof["catalysts"]:
            t = (c.get("title") or "").strip()
            t = t if len(t) <= 80 else t[:79] + "…"
            html.append(f'<div class="prof-line"><span class="d">'
                        f'{(c.get("expected_date") or "")[:10]}</span>{html_escape(t)}</div>')
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)
    # What used to be three company-wide tables at the foot of the tab, cut to this one
    # product. Asked of a portfolio they were a ranking; asked of a drug they are the
    # three things a reader wants next to its revenue: who actually takes it, what the
    # filer books for it, and what is still being trialled on it.
    _profile_detail(api_base, ticker, prof, aid)

    st.markdown(
        '<div class="byline">Every field here is sourced: approval and supplements '
        'from openFDA, revenue from the SEC data sets, exclusivity from the Orange and '
        'Purple Books, demand from CMS, the label from DailyMed. A field with no free '
        'data is left out rather than filled. '
        f'{html_escape(_payer_byline(prof.get("access")))}</div>',
        unsafe_allow_html=True)


def _profile_detail(api_base: str, ticker: str, prof: dict, aid) -> None:
    """Medicare demand, booked revenue and live studies, for this product alone.

    Each is absent for most products, and an absence is stated rather than drawn as a
    gap: free data carries CMS spending for the drugs Medicare buys, tagged revenue only
    where the filer tags a product axis, and a trial only where one is running.
    """
    # By id: a brand or generic substring also caught a neighbour whose CMS name
    # contained it.
    demand = [d for d in (api_get(api_base, f"/companies/{ticker}/demand").get("drugs")
                          or []) if str(d.get("asset_id")) == str(aid)]
    # Revenue rows carry the asset id, so this one needs no name matching at all.
    revenue = [r for r in (api_get(api_base, f"/companies/{ticker}/revenue").get("rows")
                           or []) if r.get("asset_id") == aid]
    studies = [s for s in (api_get(api_base, f"/companies/{ticker}/post-approval")
                           .get("studies") or []) if s.get("asset_id") == aid]

    cols = st.columns(3, gap="medium")
    with cols[0]:
        section("Medicare demand", len(demand) or None, "US Part D and Part B")
        if not demand:
            state("Not in the CMS files",
                  "CMS publishes spending for the drugs Medicare buys. A product it "
                  "does not cover, or one sold only outside the US, has no row.")
        else:
            # Each row is one Medicare part with a year series; the latest year is what
            # a reader wants, and the part says whether it is the pharmacy or the clinic.
            rows_html = []
            for d in demand[:6]:
                latest = (d.get("series") or [])[-1:] or [{}]
                point = latest[0]
                rows_html.append(
                    f'<div class="fitem"><span class="d">'
                    f'{html_escape(str(point.get("year") or ""))}</span>'
                    f'<span class="t">{html_escape(d.get("brand") or "")}</span>'
                    f'<span class="why">{html_escape(d.get("part_label") or "")}</span>'
                    f'<span class="s">'
                    f'{T.num((point.get("spending") or 0) / 1e6, 0)}m</span></div>')
            st.markdown('<div class="feed">' + "".join(rows_html) + "</div>",
                        unsafe_allow_html=True)
    with cols[1]:
        section("Booked revenue", len(revenue) or None, "as the filer tags it")
        if not revenue:
            state("Not tagged",
                  "The SEC data sets carry revenue per product only where the filer "
                  "tags a product axis. Most do not, for most products.")
        else:
            st.markdown('<div class="feed">' + "".join(
                f'<div class="fitem"><span class="d">FY{r.get("fiscal_year")}</span>'
                f'<span class="t">{html_escape(prof.get("brand") or "")}</span>'
                f'<span class="why"></span><span class="s">'
                f'{T.num((r.get("value") or 0) / 1e9, 2)} {html_escape(r.get("unit") or "")}'
                f' bn</span></div>' for r in revenue[:8]) + "</div>",
                unsafe_allow_html=True)
    with cols[2]:
        section("Studies underway", len(studies) or None, "on this approved product")
        if not studies:
            state("None running",
                  "No registered trial is open on this product. Lifecycle work is a new "
                  "indication, a formulation or a post-marketing commitment, and not "
                  "every product has one.")
        else:
            st.markdown('<div class="feed">' + "".join(
                _post_approval_row(s) for s in studies[:8]) + "</div>",
                unsafe_allow_html=True)
    # Who prescribes it in Medicare, which Part D plans cover it, how often Medicaid
    # fills it: a second row, under the three above.
    _payer_row(prof)


# --- payer access: Part D prescribing, Part D plan coverage, Medicaid -------------------
# The fact profile's second row (backend/payer_access.py). Each panel leads with one
# figure and one small picture and keeps the rest behind the folded detail under the row.
# Every panel says whose population it counts: Part D prescribers or plans, or Medicaid
# prescriptions before rebates. Nothing here is revenue, and none of it is valued.
_PAYER_PANELS = (("prescribing", "Part D prescribing"),
                 ("formulary", "Part D plan coverage"),
                 ("medicaid", "Medicaid prescriptions"))
_PAYER_SCOPE = {"prescribing": "Medicare Part D only",
                "formulary": "Medicare Part D plans only",
                "medicaid": "Medicaid only, before rebates"}
# Tiers are ordinal, cheapest first, and keep one colour each across brands.
_PAYER_TIERS = 6


def _payer_n(value) -> str:
    return f"{value:,.0f}" if value is not None else "no free data"


def _payer_pct(share, digits: int = 0) -> str:
    return f"{share * 100:.{digits}f}%" if share is not None else "no free data"


def _payer_scope(access: dict, key: str) -> str:
    """The panel's first line: whose population its figures count, and when."""
    block = (access or {}).get(key) or {}
    return (f'<div class="byline pa-scope">'
            f'{html_escape(block.get("scope_label") or _PAYER_SCOPE[key])}</div>')


def _payer_chip(access: dict, key: str) -> str:
    """The section rule's chip: short, because the full scope is the line under it."""
    block = (access or {}).get(key) or {}
    if key == "prescribing" and block.get("year"):
        return str(block["year"])
    if key == "formulary" and block.get("release_date"):
        return f'{block["release_date"][:7]} release'
    return "before rebates" if key == "medicaid" else "Medicare"


def _payer_state(why) -> str:
    return (f'<div class="state"><div class="d">{html_escape(why or "")}</div></div>'
            if why else "")


def _payer_co_line(access: dict) -> str:
    co = (access or {}).get("co_marketed")
    if not co or not co.get("owners"):
        return ""
    owners = co["owners"]
    where = (f"{owners[0]}'s page" if len(owners) == 1
             else "the pages of " + ", ".join(owners))
    return (f'<div class="byline pa-co">{html_escape(co["label"])}. The same brand shows '
            f'on {html_escape(where)}.</div>')


def _payer_days_text(p: dict) -> str:
    dc = p.get("days_covered") or {}
    value = dc.get("value")
    if not dc.get("applies", True):
        return (dc.get("note") or "").rstrip(".") + "." if dc.get("note") else ""
    if value is None:
        if (p.get("national") or {}).get("beneficiaries") is None:
            return "CMS suppresses the beneficiary count, so days covered cannot be read."
        return "Days covered: no free data."
    if value <= 1:
        return (f"Days supplied cover {value:.0%} of each beneficiary's year. A proxy, "
                f"not a PDC: it also falls when patients start or stop mid-year.")
    # Not only the frequent-dosing case: a daily tablet passes 1 when two strengths are
    # filled together, refills come early or packs run under 30 days (Lamictal XR, 1.04).
    return (f"Days supplied come to {value:.2f} times each beneficiary's year. A proxy, "
            f"not a PDC: it passes 1 where supplies overlap, as when two strengths are "
            f"filled together, and where fills run under 30 days, which CMS counts as "
            f"full 30-day fills, as for a drug given every week or two.")


def _payer_prescribing_html(access: dict) -> str:
    p = (access or {}).get("prescribing")
    scope = _payer_scope(access, "prescribing")
    if not p:
        return scope + _payer_state(((access or {}).get("why_empty") or {})
                                    .get("prescribing"))
    nat, f = p.get("national") or {}, p.get("file") or {}
    # A brand CMS lists by container is summed, so a prescriber who writes for the vial
    # and the pen is counted twice: the count is a ceiling and the lead says so.
    ceiling = "At most " if nat.get("upper_bound") else ""
    out = [scope, f'<div class="pa-lead">{ceiling}<b>{_payer_n(nat.get("prescribers"))}'
           f'</b> prescribers, {_payer_n(nat.get("claims"))} claims</div>']
    if f.get("top10pct") is not None:
        out.append(f'<div class="pa-sub">Top 10% of the file population write '
                   f'{_payer_pct(f["top10pct"])} of its claims</div>')
    deciles = f.get("deciles")
    if f.get("why"):
        # A pull the budget has not reached, or one that did not reconcile: the file
        # figures are held back, and "fewer than 10 prescribers" would be a wrong reason.
        out.append(f'<div class="byline">{html_escape(f["why"])}.</div>')
    elif deciles:
        out.append(CH.bar_chart(
            [{"label": str(i + 1), "value": v * 100 if v is not None else None}
             for i, v in enumerate(deciles)], width=300, height=104,
            value_fmt=lambda v: f"{v:.0f}%"))
        out.append('<div class="byline">Share of file claims by prescriber decile, '
                   'heaviest first. The file population is prescribers with 11 or more '
                   'claims for the drug.</div>')
    elif f:
        out.append('<div class="byline">Fewer than 10 prescribers in the file, so no '
                   'deciles.</div>')
    out.append(f'<div class="pa-text">{html_escape(_payer_days_text(p))}</div>')
    if p.get("part_b_note"):
        out.append(f'<div class="byline">{html_escape(p["part_b_note"])}</div>')
    return "".join(out)


def _payer_formulary_html(access: dict) -> str:
    f = (access or {}).get("formulary")
    scope = _payer_scope(access, "formulary")
    if not f:
        return scope + _payer_state(((access or {}).get("why_empty") or {})
                                    .get("formulary"))
    out = [scope,
           f'<div class="pa-lead">Listed on <b>{_payer_n(f.get("formularies_listing"))}'
           f'</b> of {_payer_n(f.get("formularies_total"))} formularies</div>']
    # Restrictions only where something lists the brand: "prior authorisation on 0"
    # beside "listed on 0" reads as an open door.
    if f.get("formularies_listing"):
        out.append(f'<div class="pa-sub">Prior authorisation on '
                   f'{_payer_n(f.get("pa_formularies"))}, step therapy on '
                   f'{_payer_n(f.get("st_formularies"))}</div>')
    if f.get("zero_reason"):
        out.append(_payer_state(f["zero_reason"]))
    tiers = f.get("tiers") or []
    if tiers:
        ramp = T.ordinal_ramp(_PAYER_TIERS)
        out.append(CH.share_strip(
            [{"label": str(t["tier"]), "value": t["formularies"],
              "colour": ramp[min(max(int(t["tier"]), 1), _PAYER_TIERS) - 1]}
             for t in tiers], width=300, height=22, label="tier mix"))
        out.append('<div class="byline">Its lowest tier on each formulary, tier 1 '
                   'cheapest. Tiers are each plan\'s own.</div>')
    return "".join(out)


def _payer_change(growth: float, bound) -> str:
    """A Medicaid change in words, saying which way a suppressed quarter can move it."""
    word = "up" if growth >= 0 else "down"
    size = f"{abs(growth):.1%}"
    if bound == "at_least":         # only the later count is a floor: true change no lower
        return f"{word} {'at least' if growth >= 0 else 'at most'} {size}"
    if bound == "at_most":          # only the earlier count is a floor: no higher
        return f"{word} {'at most' if growth >= 0 else 'at least'} {size}"
    if bound == "both":
        return f"{word} {size} between two lower bounds"
    return f"{word} {size}"


def _payer_signed_change(growth: float, bound) -> str:
    sign = f"{growth:+.1%}"
    return {"at_least": f"at least {sign}", "at_most": f"at most {sign}",
            "both": f"{sign} between lower bounds"}.get(bound, sign)


def _payer_medicaid_html(access: dict) -> str:
    m = (access or {}).get("medicaid")
    scope = _payer_scope(access, "medicaid")
    if not m:
        return scope + _payer_state(((access or {}).get("why_empty") or {})
                                    .get("medicaid"))
    latest = m.get("latest")
    out = [scope]
    if latest:
        floor = "At least " if latest.get("lower_bound") else ""
        growth = latest.get("growth")
        move = ""
        if growth is not None:
            move = f", {_payer_change(growth, latest.get('growth_bound'))} on a year"
        out.append(f'<div class="pa-lead">{floor}<b>{_payer_n(latest["prescriptions"])}'
                   f'</b> prescriptions in {latest["year"]} Q{latest["quarter"]}'
                   f'{move}</div>')
    values = [q.get("prescriptions") for q in m.get("quarters") or []]
    if len([v for v in values if v is not None]) > 1:
        out.append(CH.sparkline(values, width=300, height=36, label_last=False))
        first, last = (m["quarters"][0], m["quarters"][-1])
        out.append(f'<div class="byline">Quarterly, {first["year"]} Q{first["quarter"]} '
                   f'to {last["year"]} Q{last["quarter"]}, fee-for-service and managed '
                   f'care.</div>')
    out.append('<div class="pa-text">Gross of Medicaid rebates, so this is volume, not '
               'revenue.</div>')
    return "".join(out)


def _payer_rows(pairs) -> str:
    return "".join(f'<div class="prof-row"><span class="prof-k">{html_escape(k)}</span>'
                   f'<span class="prof-v">{html_escape(v)}</span></div>'
                   for k, v in pairs if v is not None)


def _payer_detail_html(access: dict) -> str:
    """The folded detail under the row: the figures behind each panel's lead."""
    if not access:
        return ""
    p, f, m, codes = (access.get("prescribing"), access.get("formulary"),
                      access.get("medicaid"), access.get("codes") or {})
    if not (p or f or m):
        return ""
    out = ['<details class="pa-more"><summary>Prescribers, plans and quarters</summary>']
    if p:
        nat, fl, dc = p.get("national") or {}, p.get("file") or {}, p["days_covered"]
        held_back = fl.get("why")
        if fl.get("status") != "complete":
            fl = {}                 # no file figure to show; held_back says why
        out.append(f'<div class="prof-sub">Part D prescribing, {p["year"]}</div>')
        out.append(_payer_rows([
            ("beneficiaries, at most" if nat.get("upper_bound") else "beneficiaries",
             _payer_n(nat.get("beneficiaries"))),
            ("30-day fills", _payer_n(nat.get("fills_30d"))),
            ("days covered, a proxy", f'{dc["value"]:.3f}'
             if dc.get("value") is not None else None),
            ("file prescribers, 11 or more claims", _payer_n(fl.get("prescribers"))
             if fl else None),
            ("file share of national claims", _payer_pct(fl.get("claims_share"))
             if fl.get("claims_share") is not None else None),
            ("prescribers writing half the file claims",
             _payer_n(fl.get("prescribers_for_50pct"))
             if fl.get("prescribers_for_50pct") is not None else None),
            ("median claims per file prescriber", f'{fl["median_claims"]:,.0f}'
             if fl.get("median_claims") is not None else None),
            ("days supplied per claim", f'{fl["days_per_claim"]:.1f}'
             if fl.get("days_per_claim") is not None else None),
            ("file-based days covered", f'{dc["file_value"]:.3f}'
             if dc.get("file_value") is not None else None)]))
        for line in (nat.get("note"), held_back and f"{held_back}.", dc.get("file_note"),
                     (p.get("volume_deciles") or {}).get("note")):
            if line:
                out.append(f'<div class="byline">{html_escape(line)}</div>')
        if p.get("specialties"):
            out.append('<div class="prof-sub">Prescriber specialty, share of file '
                       'claims</div>')
            out.append(_payer_rows([(s["specialty"], _payer_pct(s.get("claims_share")))
                                    for s in p["specialties"][:8]]))
        if len(p.get("series") or []) > 1:
            out.append('<div class="prof-sub">National prescribers and beneficiaries'
                       '</div>')
            out.append(_payer_rows([
                (str(s["year"]), f'{_payer_n(s.get("prescribers"))} / '
                                 f'{_payer_n(s.get("beneficiaries"))}')
                for s in p["series"]]))
    if f:
        out.append(f'<div class="prof-sub">Part D plan coverage, '
                   f'{html_escape(f.get("release_date") or "")} release</div>')
        split = f.get("by_plan_type") or {}
        rows = [("plans listing", f'{_payer_n(f.get("plans_listing"))} of '
                                  f'{_payer_n(f.get("plans_total"))}')]
        for kind in ("MA-PD", "PDP"):
            s = split.get(kind)
            if s:
                rows.append((f"{kind} plans: listing, PA, ST, QL",
                             f'{s["listing"]:,} of {s["plans"]:,}; {s["pa"]:,}, '
                             f'{s["st"]:,}, {s["ql"]:,}'))
        if not split:
            rows.append(("plans with PA, ST, QL", f'{_payer_n(f.get("pa_plans"))}, '
                         f'{_payer_n(f.get("st_plans"))}, {_payer_n(f.get("ql_plans"))}'))
        rows += [("quantity limit, formularies", _payer_n(f.get("ql_formularies"))),
                 ("plans with it on a specialty tier",
                  _payer_n(f.get("specialty_plans_listing"))),
                 ("selected for Medicare negotiation", "yes" if f.get("selected_drug")
                  else "no"),
                 ("brand RxNorm codes listed", f'{_payer_n(f.get("rxcuis_listed"))} of '
                                               f'{_payer_n(f.get("rxcuis_known"))}')]
        out.append(_payer_rows(rows))
    if m:
        out.append('<div class="prof-sub">Medicaid prescriptions by year</div>')
        out.append(_payer_rows([
            (f'{y["year"]}{"" if y.get("full_year") else ", part year"}',
             # A year whose every package CMS suppressed has no count, not "no free data".
             "suppressed by CMS" if y["prescriptions"] is None else
             ("at least " if y.get("lower_bound") else "") + _payer_n(y["prescriptions"])
             + (f', {_payer_signed_change(y["growth"], y.get("growth_bound"))}'
                if y.get("growth") is not None else ""))
            for y in m.get("years") or []]))
        latest_q = next((q for q in reversed(m.get("quarters") or [])
                         if q.get("prescriptions") is not None), None)
        if latest_q:
            out.append(_payer_rows([(
                f'{latest_q["year"]} Q{latest_q["quarter"]}: fee-for-service, managed care',
                f'{_payer_n(latest_q.get("ffsu"))}, {_payer_n(latest_q.get("mcou"))}')]))
        for line in (m.get("unbranded_note"),
                     (m.get("reused_codes") or {}).get("note")):
            if line:
                out.append(f'<div class="byline">{html_escape(line)}</div>')
        if m.get("reused_codes"):
            r = m["reused_codes"]
            out.append(f'<div class="byline">{r["prescriptions"]:,} prescriptions on '
                       f'{html_escape(", ".join(r["codes"]))}.</div>')
    if codes:
        out.append('<div class="prof-sub">Drug codes</div>')
        out.append(_payer_rows([
            ("brand RxNorm codes", _payer_n(codes.get("brand_rxcuis"))),
            ("brand product codes", _payer_n(codes.get("brand_ndc9s"))),
            ("RxNorm release", codes.get("rxnorm_version"))]))
    caveats = []
    for block in (p, f, m):
        for line in (block or {}).get("caveats") or []:
            if line not in caveats:
                caveats.append(line)
    out.extend(f'<div class="byline">{html_escape(c)}</div>' for c in caveats)
    out.append("</details>")
    return "".join(out)


def _payer_byline(access) -> str:
    """The sources of the payer row, with the statement NLM asks every user of RxNav to
    carry."""
    text = ("Part D prescribing from CMS's Medicare Part D Prescribers files, plan coverage "
            "from its monthly Part D formulary file, Medicaid prescriptions from the State "
            "Drug Utilization Data, drug codes from RxNav.")
    attribution = (access or {}).get("attribution")
    return text + (f" {attribution}" if attribution else "")


def _payer_shows(prof: dict) -> bool:
    """Whether the row is drawn: a marketed product with the payer view on its profile.
    A pipeline compound would only print "not marketed" three times."""
    return bool((prof or {}).get("access") and (prof or {}).get("is_marketed"))


def _payer_row(prof: dict) -> None:
    """The fact profile's payer row: three panels and the folded detail under them."""
    if not _payer_shows(prof):
        return
    access = prof["access"]
    cols = st.columns(3, gap="medium")
    builders = {"prescribing": _payer_prescribing_html,
                "formulary": _payer_formulary_html, "medicaid": _payer_medicaid_html}
    for col, (key, title) in zip(cols, _PAYER_PANELS):
        with col:
            section(title, None, _payer_chip(access, key))
            st.markdown(builders[key](access), unsafe_allow_html=True)
    st.markdown(_payer_co_line(access) + _payer_detail_html(access),
                unsafe_allow_html=True)


def _pct_from_start(closes) -> list:
    """A price series as percent change from its first value, so many companies plot on
    one comparable scale: every line starts at zero and its height is the move, not the
    share price. LLY near 1200 and PFE near 25 become comparable."""
    real = [c for c in closes if c is not None]
    base = real[0] if real else None
    if not base:
        return list(closes)
    return [((c / base - 1) * 100) if c is not None else None for c in closes]


# The therapeutic areas in the order the backend declares them, so each keeps one
# colour whatever company is open and whichever areas that company happens to have. An
# area not listed here still gets a colour, taken from the end of the palette.
AREA_ORDER = ("Oncology", "Immunology and inflammation", "Metabolic", "Neuroscience",
              "Cardiovascular", "Infectious disease", "Respiratory", "Haematology",
              "Urology", "Renal and hepatic", "Ophthalmology", "Healthy volunteers")


def area_colours(areas) -> dict:
    """{area: colour} for the areas given, keyed on the fixed order above."""
    palette = T.categorical(len(AREA_ORDER))
    known = {name: palette[i] for i, name in enumerate(AREA_ORDER)}
    spare = [c for c in reversed(palette)]
    out = {}
    for area in areas:
        out[area] = known.get(area) or spare[len(out) % len(spare)]
    return out


_DEAL_BADGE = {"acquisition": "Acquisition", "licensing": "Licence",
               "collaboration": "Collaboration", "divestiture": "Divestiture"}

# A filing dates every deal in it to the day it was filed, which can be months after the
# market saw the deal. The card says which of the two a date is.
_DEAL_DATE_NOTE = {
    "news": "The day it was announced, from the headline that announced it.",
    "filing": "The day it was filed. No earlier announcement date is on file.",
}


def deal_size(deals) -> str | None:
    """The announced total across the deals that state one.

    Announced consideration, not cash: it includes milestones that may never be earned,
    so it is never the acquisition line in the financials tab and is labelled to say so.

    Deals that state no figure are simply not in the sum, and the header does not count
    them either. Most pharma business development is announced without terms, so saying so
    on every deal and again in the header was the loudest thing on the panel and told a
    reader nothing: the deal count sits beside this, and a figure is either there or it is
    not.
    """
    priced = [d["announced_usd"] for d in deals if d.get("announced_usd")]
    if not priced:
        return None
    total = sum(priced)
    return f"${total / 1e9:.1f}bn announced" if total >= 1e9 \
        else f"${total / 1e6:.0f}m announced"


# --- One company's events as headline boxes ------------------------------
# The universe tab reads as a front page because every item on it is the same object: a
# chip saying what kind of thing this is, a sentence, a date, and a detail that opens in
# place. Key insights held the same material in three different list shapes, so a deal, a
# readout and a catalyst looked like three unrelated features of the app rather than
# three things that happened to one company. These turn each of them into the same box.
#
# Nothing here invents a field. Where a source has no figure the chip carries the kind
# instead, which is what the box is for.
# How each kind of deal reads in a sentence. A company is acquired, a partner is
# collaborated with, and "acquisition with Kelonia" is not English.
_DEAL_PHRASE = {"acquisition": "acquisition of", "divestiture": "divestiture of",
                "licensing": "licence with", "collaboration": "collaboration with"}

# What the chip says for a deal with no stated figure, which is most of them. Short,
# because the chip shares its line with the date inside a box a sixth of the page wide:
# spelled out, "COLLABORATION" is wider than the box and pushed the date off the edge.
# The full word is the Type row of the detail, so the abbreviation costs nothing.
_DEAL_CHIP = {"acquisition": "M&A", "licensing": "Licence",
              "collaboration": "Partner", "divestiture": "Divest"}


def _deal_lead(deal, ticker: str) -> dict:
    kind = deal.get("deal_type") or ""
    counterparty = deal.get("counterparty") or "an undisclosed counterparty"
    rows = [{"label": "Counterparty", "value": counterparty},
            {"label": "Type", "value": _DEAL_BADGE.get(kind, "Deal")}]
    # The stated structure first, since it is four commitments rather than one figure and
    # the single headline number is wrong whichever of them it picks.
    if deal.get("terms_summary"):
        rows.append({"label": "Terms", "value": deal["terms_summary"]})
    if deal.get("announced_value"):
        rows.append({"label": "Announced", "value": deal["announced_value"]})
    if deal.get("area"):
        rows.append({"label": "Area", "value": deal["area"]})
    rows.append({"label": "Date on file",
                 "value": _DEAL_DATE_NOTE.get(deal.get("event_date_source"),
                                              "The date on file.")})
    # The same figure the universe row shows for the same deal, written the same way.
    # announced_usd is the stated structure where the filing gives one, which is what
    # headlines.py ranks and prints, so the two tabs cannot disagree about a deal's size.
    # Spelled out as "$10.6 billion" it was also wide enough to push the date off the
    # box; the stated wording stays in the Announced row of the detail.
    usd = deal.get("announced_usd")
    if usd:
        figure = (f"${usd / 1e9:.2f}".rstrip("0").rstrip(".") + "bn" if usd >= 1e9
                  else f"${usd / 1e6:,.0f}m")
    else:
        # Most pharma business development is announced without terms, so the chip says
        # what kind of deal it is rather than nothing.
        figure = _DEAL_CHIP.get(kind, "Deal")
    return {
        "kind": "deal",
        "figure": figure,
        "ticker": ticker,
        "headline": f'{_DEAL_PHRASE.get(kind, "deal with")} {counterparty}',
        "date": (deal.get("event_date") or "")[:10],
        "summary": rows,
        "evidence": deal.get("terms_evidence") or "",
        "url": deal.get("article_url") or deal.get("source_url") or "",
    }


def _readout_lead(readout, ticker: str) -> dict:
    """A signed readout. Hit and miss take their own accent, because a Phase 3 that
    missed and a Phase 3 that met are the two most different items on the page and the
    green the phase ramp gives them both is the one thing they must not share."""
    positive = readout.get("outcome") == "positive"
    drug = readout.get("drug") or "an unnamed programme"
    phase = readout.get("phase") or ""
    return {
        "kind": "readout_hit" if positive else "readout_miss",
        "figure": f"Ph {phase}".strip(),
        "ticker": ticker,
        "headline": f'{drug} {"met" if positive else "missed"} in Phase {phase}'.strip(),
        "date": (readout.get("event_date") or "")[:10],
        "summary": [{"label": "Programme", "value": drug},
                    {"label": "Phase", "value": f"Phase {phase}".strip()},
                    {"label": "Outcome", "value": readout.get("outcome") or ""}],
        "evidence": readout.get("quote") or "",
        "url": readout.get("url") or readout.get("source_url") or "",
    }


# Where a news item came from, as the chip says it. EDGAR is the fallback because a row
# with no source is an SEC filing: the FDA feeds all name themselves.
_NEWS_SOURCES = {"fda_press": "FDA press", "fda_drugs": "FDA drug",
                 "fda_safety": "FDA safety",
                 # The company's own words, whether they came off its feed or its page.
                 # Which of the two is a fetcher's business and not a reader's; that it
                 # was the company speaking rather than the SEC or the FDA is the fact
                 # the chip is for.
                 "press_ir": "Company", "press_page": "Company"}
# One screen of headlines. The rest are a scroll rather than a click, and the note says
# how many were cut.
_NEWS_SHOWN = 40


def news_row(item) -> str:
    """One announcement as a line: when, what it says, and who published it.

    The whole row is the anchor, so the headline is the link rather than a cell called
    "Link" sitting beside it.
    """
    url = item.get("url")
    source = _NEWS_SOURCES.get(item.get("source"), "EDGAR")
    # "8-K: 8-K" is what the fetcher stores when it cannot resolve the filing's item
    # description, which is most of them for some filers. Said once it reads as the form
    # it is; said twice it reads as a rendering fault.
    title = (item.get("title") or "").strip()
    head, _, tail = title.partition(": ")
    if tail.strip() == head.strip():
        title = head
    open_tag = (f'<a class="fitem link" href="{html_escape(url)}" target="_blank" '
                'rel="noopener noreferrer">' if url else '<div class="fitem">')
    return (f'{open_tag}'
            f'<span class="d">{html_escape((item.get("published_at") or "")[:10])}</span>'
            f'<span class="t">{html_escape(title)}</span>'
            f'<span class="why"></span>'
            f'<span class="s">{html_escape(source)}</span>'
            f'{"</a>" if url else "</div>"}')


# What each figure on a product card means, shown on hover. Every one is a measurement
# whose basis is not obvious from the number: a revenue that is worldwide and tagged, a
# date that is the last unexpired patent rather than a forecast.
_WHY_APPROVED = ("The FDA approval date for this application, from the openFDA drugs "
                 "register. The original approval, not a later supplement.")
_WHY_REVENUE = ("Worldwide revenue for the latest full year as the filer tagged it in "
                "the SEC Financial Statement Data Sets. Free data tags revenue for only "
                "a few products, so \u201cno free data\u201d means the company did not "
                "tag this one, never that it earned nothing.")
_WHY_LOE = ("The date the product loses its US market, and the patent that sets it. A "
            "product has a stack of patents, not one: the molecule patent gates a "
            "generic outright, a formulation or method-of-use patent running later does "
            "not, and for a biologic the 12-year statutory floor applies underneath. "
            "Open the product for the whole stack. A listed patent can be shortened by "
            "a challenge, and a statutory floor is a legal minimum, not a forecast.")
_WHY_RANGE = ("First expiry to the one that sets the date. A generic can challenge the "
              "earlier patents, so the wall is a window rather than one date. Open the "
              "product to see which patent each end is.")
_WHY_LAPSED = ("This product's protection has already gone. The date is the event, not "
               "a forecast: the patent that gated a generic has expired, and later "
               "patents on the same product cover a formulation or one indication and "
               "do not hold the molecule.")
# A therapeutic area by its head word, for a chart too narrow to carry the full name.
# "Immunology and inflammation" is 27 characters against a label column of about ten,
# and a clipped label is worse than a short one. Used by the pipeline bars and the
# portfolio's disease ring, so the two never disagree about what an area is called.
AREA_SHORT = {"Immunology and inflammation": "Immunology",
              "Infectious disease": "Infectious",
              "Healthy volunteers": "Volunteers",
              "Renal and hepatic": "Renal"}


def area_label(area: str) -> str:
    return AREA_SHORT.get(area, area)


_WHY_MODALITY = ("Small molecule or biologic, which decides the register the expiry "
                 "comes from: the Orange Book for one, the Purple Book for the other.")
_WHY_BASIS = "Which patent or exclusivity sets the date above."

# How long after approval a small molecule can still hold unexpired protection. Beyond
# it, nothing listed means nothing left rather than nothing published: five years of new
# chemical entity exclusivity plus a patent term that rarely runs past the middle of the
# product's second decade on sale.
_LOE_LAPSED_AFTER_YEARS = 14

# One screen of lifecycle studies. The rest are on the company's own Pipeline and
# Catalysts tabs, and the section count states the true total.
_POST_APPROVAL_SHOWN = 30


def _post_approval_row(study) -> str:
    """One trial on a product the company already sells: when, which product, what it is."""
    url = (f'https://clinicaltrials.gov/study/{study["nct_id"]}'
           if study.get("nct_id") else "")
    open_tag = (f'<a class="fitem link" href="{html_escape(url)}" target="_blank" '
                'rel="noopener noreferrer">' if url else '<div class="fitem">')
    return (f'{open_tag}'
            f'<span class="d">{html_escape((study.get("due") or "no date")[:10])}</span>'
            f'<span class="t"><b>{html_escape(study.get("product") or "")}</b> '
            f'{html_escape((study.get("title") or "")[:96])}</span>'
            f'<span class="why">{html_escape(study.get("status") or "")}</span>'
            f'<span class="s">{html_escape(study.get("phase") or "")}</span>'
            f'{"</a>" if url else "</div>"}')


def change_row(item) -> str:
    """One detected change as a line: when, what, and how much it matters.

    A list rather than a box. These are one-sentence facts already, twenty-five of them
    for GSK, and a grid of boxes would give each one the weight of a Phase 3 result.
    """
    date = (item.get("date") or "")[:10]
    sev = item.get("significance") or "low"
    url = item.get("url")
    open_tag = (f'<a class="fitem link" href="{html_escape(url)}" target="_blank" '
                'rel="noopener noreferrer">' if url else '<div class="fitem">')
    # Four children whether or not a rule is named, so the severity column stays flush
    # right down the list.
    return (f'{open_tag}<span class="d">{date}</span>'
            f'<span class="t">{html_escape(item.get("headline") or "")}</span>'
            f'<span class="why">{html_escape(item.get("reason") or "")}</span>'
            f'<span class="s {sev}">{sev}</span>{"</a>" if url else "</div>"}')


# High first, then newest. A risk-factor rewrite from April outranks a label version bump
# from this morning, and sorting by date alone buried both of GSK's approvals under
# twenty-three label revisions.
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _flip_date(value) -> str:
    """A date that sorts newest-first while ascending, so it can ride behind severity.

    Inverting each digit rather than reversing the sort, because severity and date run in
    opposite directions and a single key cannot do both.
    """
    return "".join(str(9 - int(ch)) if ch.isdigit() else ch
                   for ch in str(value or "")[:10])


# What the chip says for a feed item. The feed's own kind is a mechanism word; these are
# what the thing is.
_FEED_FIGURE = {"catalyst": "Catalyst", "loe": "Exclusivity", "filing": "Filing",
                "market": "Rates", "policy": "Policy"}

# Shorter than the universe row's limit, because a catalyst headline is a registry trial
# title, "Phase 3, A Study of Lebrikizumab in Adult Participants With Moderate to Severe
# Atopic Dermatitis", and these boxes are half the page wide. At the shared limit every
# one of them ran to four lines and the column set the height of the whole tab. The full
# title is the first row of the detail, so opening the box loses nothing.
_FEED_LEAD_CHARS = 54


def _feed_lead(item) -> dict:
    full = item.get("headline") or ""
    rows = []
    if len(full) > _FEED_LEAD_CHARS:
        rows.append({"label": "Full title", "value": full})
    if item.get("reason"):
        rows.append({"label": "Why it is flagged", "value": item["reason"]})
    if item.get("significance"):
        rows.append({"label": "Significance", "value": item["significance"]})
    if item.get("change_type"):
        rows.append({"label": "Change", "value": item["change_type"]})
    return {
        "kind": item.get("kind") or "filing",
        "figure": _FEED_FIGURE.get(item.get("kind"), item.get("kind") or "Item"),
        "ticker": item.get("ticker") or "",
        "headline": (full if len(full) <= _FEED_LEAD_CHARS
                     else full[:_FEED_LEAD_CHARS - 1].rstrip() + "…"),
        "date": (item.get("date") or "")[:10],
        "summary": rows,
        "evidence": item.get("evidence") or "",
        "url": item.get("url") or "",
    }


# --- Statements ----------------------------------------------------------
STATEMENT_ORDER = (("income", "Income statement"), ("balance", "Balance sheet"),
                   ("cashflow", "Cash flow"))


def line_scale(unit: str | None, currency: str | None):
    """(divisor, decimals, header unit) for one line.

    Per-share figures and share counts are not currency and must not be scaled to
    billions with a currency label; a diluted share count shown as 0.90 says nothing.
    """
    unit = unit or ""
    if "/" in unit:                      # USD/shares, DKK/shares
        return 1, 2, "per share"
    if unit == "shares":
        return 1e6, 0, "m"
    return 1e9, 2, f"{currency or unit} bn".strip()


# Columns in the statements grid. The API caps it at twelve.
STATEMENT_PERIODS = 12

ABSOLUTE, COMMON_SIZE, GROWTH = "Absolute", "Common size", "Growth"
LENSES = (ABSOLUTE, COMMON_SIZE, GROWTH)

# How far back a growth column looks. A quarter is compared with the same quarter a year
# earlier, never the one before it: pharma quarters carry stocking, launch timing and
# tender phasing, and sequential change reads as news when it is a calendar. A year is
# compared with the year before.
_YEAR_BACK_DAYS = 365
_YEAR_BACK_TOLERANCE = 45


def _year_ago_column(periods: list, index: int) -> int | None:
    """The column a year before ``index``, by date rather than by counting back four.

    Counting positions assumes the columns are a regular series, and they are not: a
    filer that missed an interim period, or whose fourth quarter is derived, leaves a
    hole that would silently shift every comparison by one quarter.
    """
    import datetime as _dt

    def when(i):
        try:
            return _dt.date.fromisoformat(str(periods[i]["period_end"])[:10])
        except (ValueError, TypeError, KeyError, IndexError):
            return None

    here = when(index)
    if here is None:
        return None
    target = here - _dt.timedelta(days=_YEAR_BACK_DAYS)
    best, gap = None, None
    for other in range(index + 1, len(periods)):
        there = when(other)
        if there is None:
            continue
        distance = abs((there - target).days)
        if distance <= _YEAR_BACK_TOLERANCE and (gap is None or distance < gap):
            best, gap = other, distance
    return best


def _bn(value, dp=1):
    """A figure in billions, or None where the line was never tagged."""
    return T.num(value / 1e9, dp) if value is not None else None


# Where a figure stops reading in billions. A major's cash is 30bn and a developer's is
# 898m, and rendering the second as "0.9bn" throws away the digits that matter: the whole
# biotech engine lives between one and nine hundred million, where a billions figure has
# one significant digit and moves in steps of a hundred million.
BILLIONS_ABOVE = 1e9


def _scaled(value, dp=1):
    """(figure, unit) at the scale the number reads at, or (None, "")."""
    if value is None:
        return None, ""
    if abs(value) >= BILLIONS_ABOVE:
        return T.num(value / 1e9, dp), "bn"
    return T.num(value / 1e6, 0), "m"


def _times(value, dp=2):
    return f"{value:.{dp}f}x" if value is not None else None


def _cash_block(api_base: str, ticker: str) -> None:
    """The year's cash and what the balance sheet owes, for a company with revenue.

    What it kept, not what it earned. Every figure is computed from lines already
    filed; one missing an input is a dash naming the line it wanted, never a zero.
    """
    cash = api_get(api_base, f"/companies/{ticker}/cashflow")
    # No tail: every tile below carries its own unit, and the rail sits close enough at
    # half a page that a currency here is cut off by it.
    section("The year",
            basis=(f'FY{cash["fiscal_year"]}' if cash.get("fiscal_year")
                   else "latest year"))
    # Ordered as a sentence: what the year earned before the accountants got to it, how
    # much of that became cash, what share of profit that was, what the company owes
    # against those earnings, and what it spent buying other people. Net debt is quoted
    # in turns of EBITDA, so EBITDA has to be on the row before it rather than implied.
    st.markdown(metric_tiles([
        ("EBITDA", _bn(cash.get("ebitda")), "bn", "", "", "before D&A"),
        ("Free cash flow", _bn(cash.get("fcf")), "bn", "", "",
         (T.pct(cash["fcf_margin"] * 100, 1) + " of revenue"
          if cash.get("fcf_margin") is not None else "")),
        ("Cash conversion", _times(cash.get("cash_conversion")), "", "", "",
         "FCF over net income"),
        ("Net debt", _bn(cash.get("net_debt")), "bn", "", "",
         (_times(cash.get("net_debt_ebitda")) + " EBITDA"
          if cash.get("net_debt_ebitda") is not None else "")),
        # Cash paid is not the announced value on the deals, and the two figures are one
        # click apart, so this one says which it is.
        ("Acquisitions", _bn((cash.get("inputs") or {}).get("acquisitions")), "bn",
         "", "", "cash paid"),
    ], one_row=True), unsafe_allow_html=True)

    inputs = cash.get("inputs") or {}
    missing = [name.replace("_", " ") for name, value in inputs.items()
               if value is None and name not in
               ("cash_lines", "debt_as_of", "operating_income_basis")]
    derived = str(inputs.get("operating_income_basis") or "")
    notes = "".join((
        ("Operating income is not tagged by this filer, so EBITDA takes the "
         "subtraction its income statement already shows: revenue less cost of sales, "
         "R&D and SG&A. " if derived.startswith("derived") else ""),
        (f"Nothing is computed from a line the filer did not tag: this company is "
         f"missing {html_escape(', '.join(missing))}." if missing else ""),
    ))
    if notes:
        note(notes)


def _street_figure(metric: str, value, currency: str):
    """A consensus figure and the unit it is quoted in. None stays None."""
    if value is None:
        return None, ""
    if metric == "RevenueGrowth":
        return T.num(value, 1), "%"
    if metric in ("EPS", "PriceTarget"):
        return T.num(value, 2), (f"{currency} " if currency else "") + "per share"
    return T.num(value / 1e9, 2), (f"{currency} " if currency else "") + "bn"


def _street_block(api_base: str, ticker: str) -> None:
    """What the year ahead is expected to be: management's number, the street's, mine.

    Only periods carrying an estimate show. A period holding nothing but a reported
    actual is the block above this one said twice, and a company with no estimates on
    file gets no heading at all rather than an empty one.

    The three columns are not the same kind of number and the block says so. Guidance is
    what the company stated, quoted verbatim in the fold. Street is the paid feed or a
    curated row. Mine is the drug forecast rolled up, which covers only the assets that
    have one: Vertex's is one product against a company guiding thirteen billion, so the
    tile names the assets rather than letting the layout imply coverage it does not have.
    """
    try:
        view = api_get(api_base, f"/companies/{ticker}/street")
    except (urllib.error.URLError, OSError):
        return
    rows = [row for row in (view.get("rows") or [])
            if row.get("guidance") or row.get("street")]
    if not rows:
        return
    fallback = view.get("reporting_currency") or ""
    covered = view.get("mine_lines") or []
    section("The year ahead", basis="guidance vs street vs mine")
    quotes = []
    # Every period's figures in one row, read left to right in time. A strip per period
    # stacked them into a column, one tile deep, when a company has only street figures.
    tiles = []
    for row in rows:
        metric, period = row["metric"], row["period"]
        name = "" if metric == "Revenue" else (
            " growth" if metric == "RevenueGrowth" else
            " price target" if metric == "PriceTarget" else
            " product sales" if metric == "ProductSales" else " EPS")
        for label, entry in (("guidance", row.get("guidance")),
                             ("street", row.get("street"))):
            if not entry or entry.get("value") is None:
                continue
            currency = entry.get("currency") or (
                "" if metric == "RevenueGrowth" else fallback)
            value, unit = _street_figure(metric, entry["value"], currency)
            low, _ = _street_figure(metric, entry.get("low"), "")
            high, _ = _street_figure(metric, entry.get("high"), "")
            detail = f"{low} to {high}" if low and high and low != high else ""
            if entry.get("as_of"):
                detail = (detail + ", " if detail else "") + entry["as_of"]
            delta = row.get(f"{label}_vs_street")
            tiles.append((f"{period}{name} {label}", value, unit,
                          (f"{delta * 100:+.0f}% vs street" if delta else ""),
                          " up" if delta and delta > 0 else
                          " down" if delta else "", detail))
            if label == "guidance" and entry.get("note"):
                quotes.append(f'{period}: "{entry["note"]}"')
        if row.get("mine") is not None:
            value, unit = _street_figure(metric, row["mine"], "USD")
            delta = row.get("mine_vs_street")
            tiles.append((f"{period}{name} mine", value, unit,
                          (f"{delta * 100:+.0f}% vs street" if delta else ""),
                          " up" if delta and delta > 0 else
                          " down" if delta else "",
                          ", ".join(covered) if len(covered) < 3
                          else f"{len(covered)} assets modelled"))
    if tiles:
        st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)
    if quotes:
        # The sentence the figure was read out of, so a guidance number can always be
        # argued with rather than taken on trust.
        note(" ".join(_quoted(quote) for quote in quotes))


def _pre_revenue_blocks(api_base: str, ticker: str, left, right) -> None:
    """The two columns for a company that has no product yet.

    Revenue, margin and cash conversion are the wrong questions to ask a developer, and
    asking them is why this tab was blank for seven companies. What it is judged on is
    what it spends and how long the money lasts, which is what these say.
    """
    money = api_get(api_base, f"/companies/{ticker}/runway")
    with left:
        section("The quarter", "annualised",
                basis=(money.get("cash_as_of") or "")[:10])
        months = money.get("runway_months")
        burn = abs(money["burn_annual"]) if money.get("burn_annual") else None
        st.markdown(metric_tiles([
            ("Cash", *_scaled(money.get("cash")), "", "",
             "and investments" if money.get("includes_investments") else "on hand"),
            ("Burn", *_scaled(burn), "", "", "a year, trailing twelve months"),
            ("Runway", (f"{months:.0f}" if months is not None else None), " mo",
             "", "", "on the cash alone"),
            ("R&D", *_scaled(money.get("rd_annual")), "", "", "a year"),
        ]), unsafe_allow_html=True)
    with right:
        # Whether the money reaches the next readout, which is the question a developer
        # is actually valued on. Everything here is dated after the balance sheet, so no
        # tagged figure carries it yet.
        raised, voucher = money.get("raised_since"), money.get("voucher_since")
        funded = money.get("funded_to_readout")
        count = money.get("catalyst_count") or 0
        section("What the cash reaches", basis="post-period")
        st.markdown(metric_tiles([
            ("Available", *_scaled(money.get("available")), "", "",
             "cash plus what came after"),
            ("Raised", *_scaled(raised), "", "",
             (money["raises"][0]["kind"] if money.get("raises")
              else "since the balance sheet")),
            ("Cash out", (money.get("cash_out") or "")[:10] or None, "", "", "",
             "at the trailing burn"),
            ("Catalysts funded", (str(count) if money.get("cash_out") else None), "",
             "", "",
             ("reaches the next readout" if funded
              else "the next readout is beyond it" if funded is False
              else "nothing dated ahead")),
        ]), unsafe_allow_html=True)
        if voucher:
            figure, unit = _scaled(voucher)
            note(f"{figure}{unit} of the available figure is a priority review "
                 "voucher sold after the balance sheet date.")


def _cash_panel(built: dict) -> None:
    """Cash by period, for a company with no revenue to plot growth against.

    The balance sheet is already in the payload, so this costs no second fetch. Bars
    rather than a line: a balance is a level at a date, not a rate over one.
    """
    balance = (built.get("statements") or {}).get("balance") or {}
    line = next((l for l in balance.get("lines") or []
                 if l["key"] == "CashAndEquivalents"), None)
    if not line or not balance.get("periods"):
        return
    figures = [cell["value"] for cell in line["cells"] if cell["value"] is not None]
    if not figures:
        return
    # The same scale the tiles use. Sana holds 101m, and a chart of it in billions is
    # four bars between 0.1 and 0.2 where the tiles beside it read in whole millions.
    billions = max(figures) >= BILLIONS_ABOVE
    divisor, unit, places = (1e9, "bn", 1) if billions else (1e6, "m", 0)
    bars = [{"label": period["label"],
             "value": (cell["value"] / divisor if cell["value"] is not None else None)}
            for period, cell in zip(balance["periods"], line["cells"])][::-1]
    section("Cash", f'{built.get("currency") or ""} {unit} at each period end')
    st.markdown(
        f'<div class="trend">'
        f'{CH.bar_chart(bars, 1100, 240, value_fmt=lambda v: T.num(v, places))}</div>',
        unsafe_allow_html=True)


# What each use of cash is drawn in. Research leads in the plotted-series colour because
# it is the one a pharmaceutical company is judged on; buybacks and dividends take
# neighbouring warm hues because they are the same act, money handed back.
ALLOCATION_COLOURS = {
    "rd": TK.UP,
    # A darker green beside the brighter one: research bought rather than done, so
    # it reads as related to the segment it sits next to and not as a sixth thing.
    "acquired_rd": T.P.phase_tints[2],
    "capex": TK.MUTED,
    "acquisitions": TK.PURPLE_BOOK,
    "buybacks": TK.ORANGE_BOOK,
    "dividends": TK.FLAG,
}
ALLOCATION_LABELS = {"rd": "Research", "acquired_rd": "Acquired R&D",
                     "capex": "Plant",
                     "acquisitions": "Acquisitions", "buybacks": "Buybacks",
                     "dividends": "Dividends"}
# Drawn in this order left to right: what the business costs to run, then what is done
# with the money afterwards.
ALLOCATION_ORDER = ("rd", "acquired_rd", "capex", "acquisitions",
                    "buybacks", "dividends")


def _allocation_band(api_base: str, ticker: str) -> None:
    """Where the money went, one stacked bar a year.

    The mix is the clearest statement of strategy a company makes, and it was the one
    thing on this tab that could be read off the filings and was not being read: Merck
    spends eighteen billion on research and one on its own shares, Johnson & Johnson
    twelve on dividends and fifteen on buying other companies.
    """
    spend = api_get(api_base, f"/companies/{ticker}/allocation")
    years = spend.get("years") or []
    if len(years) < 2:
        return

    scale = 1e9 if max(
        (value for row in years for key in ALLOCATION_ORDER
         if (value := row.get(key))), default=0) >= BILLIONS_ABOVE else 1e6
    unit = "bn" if scale == 1e9 else "m"
    rows = [{"label": f'FY{row["fiscal_year"] % 100:02d}',
             "segments": [{"name": ALLOCATION_LABELS[key],
                           "value": row[key] / scale,
                           "colour": ALLOCATION_COLOURS[key]}
                          for key in ALLOCATION_ORDER if row.get(key)]}
            for row in years]
    legend = [(ALLOCATION_LABELS[key], ALLOCATION_COLOURS[key])
              for key in ALLOCATION_ORDER
              if any(row.get(key) for row in years)]

    section("Where the money went",
            f'{spend.get("currency") or ""} {unit} a year'.strip())
    st.markdown(
        f'<div class="trend">'
        # 36 per row rather than 26: the band shares a row with the trend panel now,
        # so it scales to half the width and the bars came out too thin to compare
        # one year's mix against another.
        f'{CH.stacked_bar(rows, 1100, 48 + 36 * len(rows), legend=legend, value_fmt=lambda v: T.num(v, 1))}'
        f'</div>', unsafe_allow_html=True)

    # No notes fold under this band. What it said was a caveat about research being
    # an operating expense, which the segment order already shows, and a recital of
    # figures the bar prints; on a tab that has to fit a screen it was a line of
    # chrome hiding four sentences nobody opened.


def statement_table(block: dict, currency: str | None,
                    lens: str = ABSOLUTE) -> str:
    """One statement as a table: lines down, periods across, most recent first.

    Three lenses over the same grid, because an analyst asks three questions of a
    statement and only one of them is what the number was. Common size asks what share
    of sales a line takes; growth asks which way it is moving. Both were arithmetic the
    reader was doing by eye across six columns.

    The common-size base comes from the API, read at each column's own period. Taking
    it from a line in this grid would work for the balance sheet and silently fail for
    cash flow, whose base is revenue, which is not one of its lines and whose columns
    are cumulative where the income statement's are discrete.
    """
    periods, lines = block["periods"], block["lines"]
    common_size = lens == COMMON_SIZE
    growth = lens == GROWTH
    base = block["base"]["values"] if common_size else []

    head = "".join(f'<th class="{"now" if i == 0 else ""}">{html_escape(p["label"])}</th>'
                   for i, p in enumerate(periods))
    body = []
    for line in lines:
        divisor, decimals, _ = line_scale(line.get("unit"), currency)
        cells = []
        for index, cell in enumerate(line["cells"]):
            value = cell["value"]
            if common_size:
                # A per-share line has no meaning as a share of sales, so it is left
                # out of the column rather than divided into a number that reads.
                divisor_ok = "/" not in (line.get("unit") or "")
                denominator = base[index] if index < len(base) else None
                value = (value / denominator * 100
                         if divisor_ok and value is not None and denominator else None)
                text = T.num(value, 1)
            elif growth:
                back = _year_ago_column(periods, index)
                earlier = (line["cells"][back]["value"]
                           if back is not None and back < len(line["cells"]) else None)
                # A sign change has no percentage: a loss becoming a profit is not
                # "up 240%", it is a different thing happening, and the arithmetic that
                # produces that number is the arithmetic that hides it.
                value = ((value / earlier - 1) * 100
                         if value is not None and earlier not in (None, 0)
                         and (value > 0) == (earlier > 0) else None)
                text = T.pct(value, 1) if value is not None else "—"
            else:
                text = T.num(value / divisor if value is not None else None, decimals)
            classes = ["now" if index == 0 else "",
                       "neg" if value is not None and value < 0 else "",
                       "gap" if value is None else ""]
            figure = (f'<span class="der">{text}</span>'
                      if cell["derived"] and value is not None else text)
            cells.append(f'<td class="{" ".join(c for c in classes if c)}">{figure}</td>')
        # The column header carries the currency, so only the lines that are not in it
        # name their unit. Without this a diluted share count reads as a money figure.
        _, _, unit_label = line_scale(line.get("unit"), currency)
        label = html_escape(line["label"])
        if lens == ABSOLUTE and unit_label not in (f"{currency} bn", "bn"):
            label += f'<span class="lu">, {html_escape(unit_label)}</span>'
        if line.get("note"):
            label = f'<span title="{html_escape(line["note"])}">{label}</span>'
        body.append(f'<tr class="{line["role"]}"><td class="l">{label}</td>'
                    + "".join(cells) + "</tr>")

    # The unit belongs in the header of the grid it describes, and it changes with the
    # mode: putting it on the section rule instead left "USD bn" standing over a table
    # of percentages.
    unit = (f'% of {block["base"]["label"].lower()}' if common_size
            else "% on a year earlier" if growth
            else f'{currency or ""} bn'.strip())
    return (f'<div class="fin-wrap"><table class="fin">'
            f'<thead><tr><th class="l">{html_escape(unit)}</th>'
            f'{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def metric_tiles(items, one_row: bool = False) -> str:
    """A row of headline figures, in one language every block can use.

    Each item is (label, value, unit, change, tone, note). The unit rides with the
    number, since a scale stated three lines away has to be worked out. The change sits
    on the same baseline as the number, because it is part of the figure rather than a
    line of its own: stacked underneath, four figures read as twelve unrelated lines.
    A note appears only where the number cannot be read without it.
    """
    # one_row puts every figure on a single line whatever the count, for a block that has
    # the full width of the page. The default still wraps, which is what a half-width
    # column needs.
    out = []
    for label, value, unit, change, tone, note in items:
        missing = value is None or value == T.num(None)
        figure = ("no free data" if missing
                  else f'{value}<span class="u">{unit}</span>' if unit
                  else str(value))
        out.append(
            f'<div><span class="k">{html_escape(label)}</span>'
            f'<span class="row"><span class="v{" none" if missing else ""}">{figure}</span>'
            + (f'<span class="d{tone}">{html_escape(change)}</span>' if change else "")
            + '</span>'
            + (f'<span class="n">{html_escape(note)}</span>' if note else "")
            + '</div>')
    return (f'<div class="tiles{" tiles-row" if one_row else ""}">'
            f'{"".join(out)}</div>')


CURVE_KEYS = ("penetration_peak_pct", "ramp_midpoint_year")


# --- the book -------------------------------------------------------------------
# What the company's modelled assets are worth a share, one row each, ranked. The row is
# the picker: an analyst reads the book to decide what to look at next, so the list and
# the control are the same object, and a click opens the product beneath without a
# page reload (the clicklist component returns the id to Python).

_BOOK_TOP = 12
_BUILD_TOP = 14
_BOOK_TOKENS = {"panel": TK.PANEL, "panel-hi": TK.RULE, "rule": TK.RULE,
                "rule-strong": TK.RULE_STRONG, "muted": TK.MUTED, "text": TK.TEXT,
                "up": TK.UP, "down": TK.DOWN, "flag": TK.FLAG,
                "purple-book": TK.PURPLE_BOOK, "font-mono": TK.FONT_MONO,
                "font-ui": TK.FONT_UI}
# Lives with the rows it styles rather than in theme.py: the rows render inside the
# component's iframe, which inherits none of the page's CSS.
_BOOK_CSS = """
.bk { display: grid; grid-template-columns: minmax(0, 1fr) 96px 54px 84px; gap: 0.55rem;
      align-items: center; font-size: 11.5px; line-height: 1.25; padding: 3px 6px 3px 8px;
      border-bottom: 1px solid var(--rule); border-left: 2px solid transparent; }
.bk:hover { background: var(--panel-hi); }
.bk.sel { border-left-color: var(--up); background: var(--panel); }
.bk.sel .bk-n { color: var(--up); }
.bk-n { color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bk-bar { height: 7px; background: var(--rule); }
.bk-bar i { display: block; height: 100%; background: var(--up); }
.bk.pipe .bk-bar i { background: var(--purple-book); }
.bk.off .bk-bar i { background: repeating-linear-gradient(135deg, var(--muted) 0 2px,
                    transparent 2px 5px); }
.bk-v { font-family: var(--font-mono); text-align: right; color: var(--text);
        font-weight: 600; }
.bk.off .bk-v { color: var(--muted); font-weight: 400; }
.bk-m { font-family: var(--font-mono); font-size: 9.5px; color: var(--muted);
        text-align: right; white-space: nowrap; }
.bk.pipe .bk-m { color: var(--purple-book); }
.bk-more { margin: 0; }
.bk-more > summary { list-style: none; cursor: pointer; font-family: var(--font-mono);
                     font-size: 10px; letter-spacing: 0.05em; text-transform: uppercase;
                     color: var(--muted); padding: 5px 8px; }
.bk-more > summary::-webkit-details-marker { display: none; }
.bk-more > summary:hover { color: var(--text); }
.bk-tail { font-size: 10.5px; color: var(--muted); padding: 6px 8px 2px; line-height: 1.45; }
.bk-h { display: flex; justify-content: space-between; font-family: var(--font-mono);
        font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase;
        color: var(--muted); padding: 7px 8px 3px; border-bottom: 1px solid var(--rule-strong); }
.bk-h span:last-child { color: var(--text); }
.bk-tail b { color: var(--text); font-weight: 500; }
"""


def _book_row(m: dict, top_ps: float, selected) -> str:
    """One asset as a row: name, a bar in proportion to the largest, the figure, and
    the one fact that qualifies it. A pipeline asset's figure is risk-adjusted, so its
    bar takes the pipeline colour and its qualifier is the PoS it was cut by; a marketed
    product's is the year exclusivity ends. An asset on a placeholder curve is hatched
    and its figure muted, because it is drawn and not counted."""
    pipe = not m.get("is_marketed")
    counted = m.get("counted", True)
    ps = m.get("per_share")
    width = (max(ps, 0.0) / top_ps * 100.0) if (top_ps and ps) else 0.0
    classes = ("bk" + (" pipe" if pipe else "") + ("" if counted else " off")
               + (" sel" if m.get("asset_id") == selected else ""))
    if not counted:
        meta = "placeholder"
    elif pipe:
        meta = f"PoS {m['pos']:.0%}" if m.get("pos") is not None else "pipeline"
    else:
        meta = (f"LOE {m['loe_year']}" if m.get("loe_year")
                else "lapsed" if m.get("loe_in_base") else "no LOE")
        # The first region to open ahead of the US, where one does. Nothing opens ahead
        # of a US market already lost.
        us_year = m.get("loe_year")

        def opens_first(r):
            if m.get("loe_in_base"):
                return False
            if r.get("in_base"):
                return True
            return bool(r.get("loe_year")) and (us_year is None or r["loe_year"] < us_year)

        ahead = [r for r in m.get("regions") or [] if opens_first(r)]
        if ahead:
            first = min(ahead, key=lambda r: (not r.get("in_base"), r.get("loe_year") or 0))
            meta += (f" · {_REGION_WORD.get(first.get('region'), first.get('region'))} "
                     f"{'lapsed' if first.get('in_base') else first['loe_year']}")
    return (f'<div class="{classes}" data-id="{m.get("asset_id")}">'
            f'<span class="bk-n">{html_escape(m.get("name") or "")}</span>'
            f'<span class="bk-bar"><i style="width:{width:.0f}%"></i></span>'
            f'<span class="bk-v">{T.num(ps, 2) if ps is not None else "—"}</span>'
            f'<span class="bk-m">{html_escape(meta)}</span></div>')


def _value_book(v: dict, ticker: str, selected):
    """The ranked list, as a clickable component. Returns the asset id of a fresh click
    or None. The first dozen are always open; the rest fold behind their own total, so
    a book of forty-three reads at a glance and is still all reachable."""
    modelled = sorted(v.get("modelled") or [],
                      key=lambda m: -(m.get("per_share") or 0.0))
    top_ps = max((m.get("per_share") or 0.0 for m in modelled), default=0.0) or 1.0
    rows = []
    # Two groups, because the sum of the parts is two sums: the marketed book at its
    # NPV, and the pipeline after each asset's probability. A heading over each says
    # what the group adds up to, so "is the pipeline in it" is answered by the list.
    groups = [("approved", [m for m in modelled if m.get("is_marketed")]),
              ("pipeline, after PoS", [m for m in modelled if not m.get("is_marketed")])]
    for label, members in groups:
        if not members:
            continue
        total = sum(m.get("per_share") or 0.0 for m in members if m.get("counted", True))
        rows.append({"id": None, "html": f'<div class="bk-h"><span>{html_escape(label)}'
                                         f' · {len(members)}</span><span>{total:,.2f} a share'
                                         f'</span></div>'})
        head, rest = members[:_BOOK_TOP], members[_BOOK_TOP:]
        rows += [{"id": m["asset_id"], "html": _book_row(m, top_ps, selected)}
                 for m in head]
        if rest:
            rest_ps = sum(m.get("per_share") or 0.0 for m in rest)
            inner = "".join(_book_row(m, top_ps, selected) for m in rest)
            is_open = any(m.get("asset_id") == selected for m in rest)
            rows.append({"id": None, "html":
                         f'<details class="bk-more"{" open" if is_open else ""}>'
                         f'<summary>{len(rest)} more · {rest_ps:.2f} a share</summary>'
                         f'{inner}</details>'})
    tail = []
    lines = [s for s in v.get("streams") or [] if s.get("per_share") is not None]
    if lines:
        tail.append("lines no asset carries: " + ", ".join(
            f'<b>{html_escape(s["line"])}</b> {s["per_share"]:.2f}' for s in lines)
            + " a share")
    unmodelled = (v.get("coverage") or {}).get("unmodelled") or []
    if unmodelled:
        tail.append("not modelled: " + ", ".join(
            f'{html_escape(u["name"])} {u["revenue"] / 1e6:,.0f}mm' for u in unmodelled))
    if tail:
        rows.append({"id": None, "html": f'<div class="bk-tail">{" · ".join(tail)}</div>'})
    clicked = clicklist.click_list(rows, tokens=_BOOK_TOKENS, selected=selected,
                                   css=_BOOK_CSS, key=f"fc_book_{ticker}")
    # A click is acted on once: the nonce changes per click, so a rerun triggered by
    # anything else does not re-select a product the reader has since moved off.
    if (isinstance(clicked, dict)
            and clicked.get("nonce") != st.session_state.get("fc_book_nonce")):
        st.session_state["fc_book_nonce"] = clicked.get("nonce")
        return clicked.get("id")
    return None


def _mix_hex(a: str, b: str, t: float) -> str:
    """Token colour ``a`` moved a share ``t`` of the way to token colour ``b``: a derived
    shade, never a new colour."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def _revenue_build(v: dict) -> None:
    """History running into forecast, stacked by what produces it.

    The first chart in any sell-side model. Every modelled asset is a band, every
    revenue line no asset carries is a band, an asset drawn on a placeholder curve is
    hatched so it is seen and not believed, and the reported figures sit over the top
    as the line the bands have to meet.

    Fourteen bands are named and the rest are one. A build of forty-three named bands was
    a legend of forty-three names over a chart nobody could read; drawn across the whole
    page, the fourteen largest by value hold, each in its own colour, and the remainder is
    one grey band so the total is still the total. Revenue lines no asset carries are
    each a shade of grey of their own, so a line is never mistaken for a product.

    What has no path is not drawn as one. Revenue with neither a product row nor a line
    is stated as a figure beside the chart, because a flat band for it would be a
    forecast nobody made.
    """
    modelled = v.get("modelled") or []
    streams = v.get("streams") or []
    history = [(int(r["fiscal_year"]), r["value"]) for r in v.get("reported_revenue") or []
               if r.get("value") is not None]
    if not modelled and not streams:
        return
    forecast_years = sorted({y for m in modelled for y in m.get("years") or []}
                            | {y for s in streams for y in s.get("years") or []})
    if not forecast_years:
        return
    hist_years = [y for y, _ in history if y < forecast_years[0]][-4:]
    years = hist_years + forecast_years
    labels = [str(y) for y in years]

    base = [TK.UP, TK.PURPLE_BOOK, TK.ORANGE_BOOK, TK.FLAG, TK.DOWN,
            TK.PHASE_RAMP["Phase 2"], TK.PHASE_RAMP["Phase 3"]]
    # Seven token colours, then the same seven lightened toward the text colour: fourteen
    # products each told apart, with no colour from outside the palette.
    palette = base + [_mix_hex(c, TK.TEXT, 0.45) for c in base]
    greys = [_mix_hex(TK.MUTED, TK.GROUND, f) for f in (0.0, 0.25, 0.45, 0.6, 0.15, 0.35)]
    ranked = sorted(modelled, key=lambda m: -(m.get("rnpv_share") or 0))
    head, rest = ranked[:_BUILD_TOP], ranked[_BUILD_TOP:]
    series = []
    for i, m in enumerate(head):
        by_year = dict(zip(m.get("years") or [], m.get("revenue_share") or []))
        series.append({"name": m["name"][:22], "colour": palette[i % len(palette)],
                       "hatched": not m.get("counted", True),
                       "values": [by_year.get(y) for y in years]})
    if rest:
        other = {}
        for m in rest:
            for y, value in zip(m.get("years") or [], m.get("revenue_share") or []):
                other[y] = other.get(y, 0.0) + (value or 0.0)
        series.append({"name": f"{len(rest)} smaller products", "colour": TK.RULE_STRONG,
                       "values": [other.get(y) for y in years]})
    for j, s in enumerate(streams):
        by_year = dict(zip(s.get("years") or [], s.get("revenue") or []))
        series.append({"name": s["line"][:24], "colour": greys[j % len(greys)],
                       "values": [by_year.get(y) for y in years]})
    ref_by_year = dict(history)
    section("Revenue build", basis=f"{_mm()} · reported over modelled")
    R.show(CH.stacked_columns(
        labels, series, 1500, 420, value_fmt=lambda x: f"{x:,.0f}",
        reference={"name": "reported", "colour": TK.TEXT,
                   "values": [ref_by_year.get(y) for y in years]}),
        css_class="chart-mount stretch")


def _book_top(api_base: str, ticker: str):
    """The asset worth most a share, for the picker to open on. None where the book
    is empty or the API is down; the same cached call the book itself makes."""
    try:
        v = api_get(api_base, f"/companies/{ticker}/forecast-verdict")
    except (urllib.error.URLError, OSError):
        return None
    modelled = [m for m in (v.get("modelled") or []) if m.get("per_share") is not None]
    if not modelled:
        return None
    return max(modelled, key=lambda m: m["per_share"])["asset_id"]


# The book's reporting currency, set where the whole-company verdict is read and used by
# every figure under it. Per-share figures are translated to dollars; revenue, rNPV and
# the P&L stay in the filer's own currency, and a bare "mm" read Novo's 199,762mm krone
# rNPV for Ozempic as dollars. The P&L said "mm USD" for every filer.
_BOOK_UNIT = {"currency": "USD"}


def _mm() -> str:
    cur = _BOOK_UNIT["currency"]
    return "mm" if cur == "USD" else f"mm {cur}"


def _intro(text: str) -> None:
    """The question a view answers, in one line above it."""
    st.markdown(f'<div class="view-intro">{html_escape(text)}</div>',
                unsafe_allow_html=True)


# --- Comps valuation -----------------------------------------------------
# The whole universe in one read. The view chooses its own peers from all 70 companies,
# so a peer from another engine can be added in the frame without a rerun. A minute of
# cache keeps a rerun of the page from rebuilding the payload; the view's Reload button
# clears it. Read directly rather than through api_get, so that a reload is a real read
# of the API rather than a second cache handing back the same body.
@st.cache_data(ttl=60, show_spinner=False)
def _comps_valuation_payload(api_base: str) -> dict:
    with urllib.request.urlopen(api_base.rstrip("/") + "/comps/valuation",
                                timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


# The focal company's own evidence for Drivers and risks: its dated catalysts of the next
# twelve months and the competition in its most valuable indications. One company per
# read, the same minute of cache and the same direct read as the payload, so the view's
# Reload button is a real read of both.
@st.cache_data(ttl=60, show_spinner=False)
def _comps_context(api_base: str, ticker: str) -> dict:
    with urllib.request.urlopen(
            api_base.rstrip("/")
            + f"/companies/{urllib.parse.quote(ticker)}/comps-context",
            timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _compsval_action(kinds: tuple, seen_key: str):
    """The valuation view's last action when it is one of ``kinds`` and its nonce is
    not the one recorded under ``seen_key``; otherwise None.

    The component's value persists in session state after the click, so the nonce, not
    the value, says whether an action is new.
    """
    value = st.session_state.get("compsval")
    if (isinstance(value, dict) and value.get("action") in kinds
            and value.get("nonce") is not None
            and value.get("nonce") != st.session_state.get(seen_key)):
        return value
    return None


def _compsval_focus():
    """The ticker the valuation view last asked to make focal, while that request is
    still unapplied; otherwise None.

    The view posts ``{"action": "focus", "ticker", "nonce"}``. The pre-selectbox hook
    records each nonce it applies, and a rerun caused by anything else does not send
    the page back to a company the analyst has since moved off. (Revision 4 of the frame
    sends no ``indication`` action: the competition rows that linked to a landscape left
    with Drivers and risks, design company-scorecard.md 6.4.)
    """
    value = _compsval_action(("focus",), "_compsval_nonce")
    if value is None:
        return None
    return str(value.get("ticker") or "").strip().upper()


def _cm_ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st."""
    tail = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{tail}"


def _company_map_points(scorecard: dict, ticker: str, records=None) -> list:
    """The bubbles of the company map (design company-scorecard.md 3.1, 8.1) for the
    open company's cohort, read from the scorecard as it came: one per company with a
    company score and a value score, nothing computed here.

    ``records`` are the payload's company records, read for each price date: a bubble's
    tooltip names its price date when it is not the cohort's latest. An open company
    with no cohort, or a scorecard that failed, gives no points.
    """
    sc = scorecard if isinstance(scorecard, dict) else {}
    companies = sc.get("companies") or {}
    own = companies.get(ticker) or {}
    cohort_id = own.get("cohort")
    cohort = (sc.get("cohorts") or {}).get(cohort_id) or {}
    if sc.get("error") or not cohort_id or not cohort:
        return []
    meta = (sc.get("method") or {}).get("pillars") or {}
    business = [p.get("id") for p in cohort.get("pillars") or []
                if (meta.get(p.get("id")) or {}).get("kind") == "business"]
    price_of = {}
    for rec in records or []:
        if isinstance(rec, dict):
            price_of[rec.get("ticker")] = ((rec.get("market") or {}).get("price_as_of"))
    members = [t for t, r in companies.items() if (r or {}).get("cohort") == cohort_id]
    dates = [price_of.get(t) for t in members if price_of.get(t)]
    latest = max(dates) if dates else None
    n = cohort.get("n") or len(members)
    points = []
    for t in members:
        r = companies[t]
        chart = r.get("chart")
        if not chart or r.get("rank") is None:
            continue
        lo, hi = (r.get("rank_range") or [None, None])[:2]
        rank_text = f"{_cm_ordinal(int(r['rank']))} of {r.get('ranked_of') or n}"
        range_text = r.get("range_text") or (f"{lo}–{hi}" if lo is not None else "")
        pillars = r.get("pillars") or {}
        parts = []
        for pid in business:
            s = (pillars.get(pid) or {}).get("score")
            if s is None:
                continue
            label = (meta.get(pid) or {}).get("label") or pid
            parts.append(f"{label if not parts else label.lower()} {s}")
        tip = (f"{t} {r.get('name') or t}. Company score {r.get('score')}, {rank_text}"
               + (f", range {range_text}" if range_text else "") + "."
               + (f" Value {r.get('value')}." if r.get("value") is not None else ""))
        if parts:
            tip += " " + ", ".join(parts)
            k, k_of = r.get("pillars_scored"), r.get("pillars_of")
            tip += (f" (on {k} of {k_of} pillars)." if k is not None and k_of and k < k_of
                    else ".")
        when = price_of.get(t)
        if when and latest and when != latest:
            try:
                when_text = dt.date.fromisoformat(str(when)[:10]).strftime("%-d %b %Y")
            except ValueError:
                when_text = str(when)
            tip += f" Price of {when_text}."
        aria = (f"{t}, rank {r['rank']}"
                + (f", range {lo} to {hi}" if lo is not None else "")
                + f", company score {r.get('score')}"
                + (f", value {r.get('value')}" if r.get("value") is not None else ""))
        points.append({"ticker": t, "x": chart.get("x"), "y": chart.get("y"),
                       "size": chart.get("size"), "complete": bool(chart.get("complete")),
                       "rank": r["rank"], "tip": tip, "aria": aria})
    return points


# A fragment: the frame recomputes every peer set, basis, preset and bridge input itself,
# so Python hears only two actions and none should redraw the other tabs for nothing. A
# reload reruns this fragment alone. A new focal company reruns the page, because the
# top bar and every other tab follow it; the hook before the company selector applies it.
@st.fragment
def _comps_valuation_view(api_base: str, ticker: str, engine: str, live: bool):
    """The Companies view: one component over the whole universe, the focal company
    being the one the top bar has open. It opens on the company map of the focal
    company's cohort, drawn here and handed to the frame, which binds its bubbles."""
    try:
        payload = _comps_valuation_payload(api_base)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        state("Companies unavailable",
              f"The API did not answer on /comps/valuation: {html_escape(str(exc))}. "
              "Check it is running, then open this tab again.", error=True)
        return
    # The chart is drawn in Python, the look of the clinical scorecard, and the frame only
    # shows it. A drawing that fails leaves the frame its table and its panel.
    try:
        chart_svg = CH.company_map(
            _company_map_points(payload.get("scorecard"), ticker, payload.get("companies")),
            760, 480, open_ticker=ticker)
    except Exception as exc:  # the scorecard's shape is the API's; the view still opens
        print(f"company map failed for {ticker}: {exc!r}", flush=True)
        chart_svg = ""
    picked = compsval.comps_valuation(payload, focal=ticker, engine=engine,
                                      tokens=COMPS_TOKENS, live=live,
                                      mode="full", key="compsval", chart_svg=chart_svg)
    if not (isinstance(picked, dict) and picked.get("nonce") is not None
            and picked.get("nonce") != st.session_state.get("_compsval_seen")):
        return
    st.session_state["_compsval_seen"] = picked.get("nonce")
    # The hook before the company selector records the nonce of a focus action it has
    # applied, which it can only do in a full run. A nonce it has not recorded means this
    # is the fragment's own rerun, so the page reruns for the hook.
    hooked = picked.get("nonce") == st.session_state.get("_compsval_nonce")
    if picked.get("action") == "focus":
        wanted = str(picked.get("ticker") or "").strip().upper()
        if wanted and wanted != ticker and not hooked:
            st.rerun()
    elif picked.get("action") == "reload":
        _comps_valuation_payload.clear()
        _comps_context.clear()
        _rerun_here()


def _peer_value_section(api_base: str, ticker: str) -> None:
    """The value the peer set's multiple implies for the company, on the Forecast tab.

    One more lens on the same question the fair value range asks, so it sits under that
    range. It is the Comps valuation component in its bridge mode: the peer set, the
    metric and the bridge inputs are the ones chosen in Comps, read from the browser
    storage the two frames share, and nothing comes back to Python from it. Drawn for
    every company, modelled or not, because a peer multiple needs no product model.
    """
    section("Value implied by peer multiples",
            basis="peer set and metric from Comps · $ a share")
    try:
        payload = _comps_valuation_payload(api_base)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        state("Peer multiples unavailable",
              f"The API did not answer on /comps/valuation: {html_escape(str(exc))}.",
              error=True)
        return
    # Live as the Comps view is: the time machine's state is read where the page set
    # it, which a rerun of the Forecast fragment alone does not repeat.
    compsval.comps_valuation(payload, focal=ticker,
                             engine=st.session_state.get("engine") or "",
                             tokens=COMPS_TOKENS, live=not globals().get("asof_state"),
                             mode="bridge")


@st.cache_data(ttl=600, show_spinner=False)
def _landscape_index(api_base: str):
    try:
        return api_get(api_base, "/indications")
    except (urllib.error.URLError, OSError):
        return None


def _pct(value, digits: int = 1) -> str:
    return "·" if value is None else f"{value * 100:.{digits}f}%"


def _land_num(value, digits: int = 1) -> str:
    return "·" if value is None else f"{value:,.{digits}f}"


def _indication_landscape(api_base: str, ticker: str) -> None:
    """Every big pharma candidate for one indication, whatever its modality or mechanism,
    compared on what it is, what its trials posted and what the model says it is worth.

    Opens on the most contested indication the company is in. Three views of the same
    candidates: the candidates themselves (stage, science, value, share of the pool), the
    efficacy their trials posted against placebo, and their safety record against placebo
    in the same trials.
    """
    section("Indication landscape")
    index = _landscape_index(api_base)
    if not index:
        state("No landscape yet", "the API returned no indications with a big pharma "
              "candidate marketed or in Phase 2 and later")
        return
    by_id = {i["id"]: i for i in index}
    mine = [i["id"] for i in index if ticker in (i.get("tickers") or [])]
    options = mine + [i["id"] for i in index if i["id"] not in mine]
    # No index is passed: the first option is the default, and a default beside a session
    # value draws a warning.
    pick = st.selectbox(
        "Indication", options, key=f"land_pick_{ticker}",
        format_func=lambda i: (f'{by_id[i]["name"]} · {by_id[i]["companies"]} companies '
                               f'in development'
                               + (f" · {ticker} in it" if i in mine else "")),
        label_visibility="collapsed")
    with st.spinner("Reading every candidate's trials and safety record"):
        try:
            # Longer than the page's usual 30 seconds: a landscape whose companies have
            # no cached verdict yet builds their books the first time it is opened.
            with urllib.request.urlopen(
                    api_base.rstrip("/") + f"/indications/{pick}/landscape",
                    timeout=240) as resp:
                land = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:
            state("The landscape did not load", str(exc), error=True)
            return
    cands = land.get("candidates") or []
    if not cands:
        state("No candidates", "nothing big pharma holds is linked to this indication")
        return
    cov = land.get("coverage") or {}
    pool = land.get("pool") or {}
    cells = [
        ("candidates", str(cov.get("candidates", len(cands))), "",
         f'{len(land.get("companies") or [])} companies'),
        ("marketed", str(sum(1 for c in cands if c["stage"] == "Marketed")), "",
         f'{sum(1 for c in cands if c["is_marketed"] and c["stage"] != "Marketed")} more '
         f'sold elsewhere, trialled here'),
        ("phase 3", str(sum(1 for c in cands if c["stage"] in ("Phase 3", "Phase 2/3"))),
         "", f'{sum(1 for c in cands if c["stage"] == "Phase 2")} in Phase 2'),
        ("mechanism known", f'{cov.get("with_mechanism", 0)}', "",
         "ChEMBL and the FDA label"),
        ("modelled", f'{cov.get("with_model", 0)}', "", "valued in the book"),
        ("trials posted", f'{cov.get("trials_with_results", 0)}', "",
         f'of {cov.get("trials", 0)} linked'),
    ]
    if pool.get("pool"):
        cells.append(("shared pool", f'{pool["pool"] / 1e6:,.1f}mm', "",
                      f'{pool.get("claimants")} claimants'
                      + (f' · {_pct(pool.get("uncrowded_share"), 0)} claimed, '
                         f'{_pct(pool.get("crowded_share"), 0)} after crowding'
                         if pool.get("uncrowded_share") is not None else "")))
    st.markdown('<div class="pos">' + "".join(
        f'<span><span class="k">{html_escape(k)}</span><span class="v {cls}">{html_escape(v)}'
        f'</span><span class="sub">{html_escape(sub)}</span></span>'
        for k, v, cls, sub in cells) + "</div>", unsafe_allow_html=True)
    members = (land.get("indication") or {}).get("members") or []
    if len(members) > 1:
        note("One population under several names, read together: " + ", ".join(members))

    # A switch, not a third level of tabs: this sits inside the Comps tab's own views,
    # and tabs inside tabs inside tabs read as three navigations at once.
    view = st.segmented_control(
        "View", ["Overview", "Candidates", "Efficacy", "Safety"], default="Overview",
        key=f"land_view_{pick}", label_visibility="collapsed") or "Overview"
    if view == "Overview":
        _landscape_overview(api_base, pick, ticker)
    elif view == "Candidates":
        _landscape_candidates(cands)
    elif view == "Efficacy":
        _landscape_efficacy(land.get("endpoints") or [], cands, pick)
    else:
        _landscape_safety(land.get("safety") or [])


def _get_long(api_base: str, path: str, timeout: int = 240):
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _how(text: str) -> None:
    """A reading instruction, shown rather than folded: the overview is read fast, and a
    note behind a toggle is one nobody opens."""
    st.markdown(f'<div class="how-read">{html_escape(text)}</div>', unsafe_allow_html=True)


def _verdict_card(card: dict, lead: bool = False, meaning: bool = True) -> str:
    detail = (f'<div class="vc-detail">{html_escape(card["detail"])}</div>'
              if card.get("detail") else "")
    mean = (f'<div class="vc-mean"><span>What this means</span>'
            f'{html_escape(card["meaning"])}</div>' if meaning and card.get("meaning") else "")
    return (f'<div class="vc{" vc-lead" if lead else ""} vc-{html_escape(card["kind"])}">'
            f'<div class="vc-title">{html_escape(card["title"])}</div>'
            f'<div class="vc-head">{html_escape(card["headline"])}</div>{detail}{mean}</div>')


def _score_cell(value, focal: bool = False, mark: str | None = None) -> str:
    """A score out of 100 as its figure and a bar, or the null dash.

    ``mark`` is a slot after the figure: None for no slot, "" for an empty one and "†"
    for the dagger of a drug scored on strength and wins alone. Every cell of a column
    that carries a dagger gets the slot, so the figures still line up."""
    if value is None:
        return '<td class="n m">—</td>'
    slot = "" if mark is None else f'<span class="sc-dg">{html_escape(mark)}</span>'
    return (f'<td class="n"><span class="sc{" sc-f" if focal else ""}">'
            f'<i style="width:{max(0.0, min(100.0, value)):.0f}%"></i></span>{value:.0f}'
            f'{slot}</td>')


def _score_range(a: dict, table: bool = False) -> str:
    """Where a drug's rank falls in 95 of 100 redraws, as "2 to 3". Where it never moved,
    the table shows the rank itself ("1") and the words nothing; blank where the drug is
    not placed."""
    rr = a.get("rank_range")
    if not rr:
        return ""
    if rr[0] == rr[1]:
        return str(rr[0]) if table else ""
    return f"{rr[0]} to {rr[1]}"


def _score_tip(a: dict) -> str:
    """The tooltip of a bubble: its scores and rank with the range the rank could sit
    in, then the lines printed under the chart."""
    e, s_, v = a["efficacy"], a["safety"], a["evidence"]
    span = _score_range(a)
    head = (f'{a["name"]} ({a["ticker"]}), {a["stage"]}. Overall {a["overall"]:.0f}, '
            f'rank {a["rank"]}' + (f" (could sit {span})" if span else "")
            + f': efficacy {e["score"]:.0f}, safety {s_["score"]:.0f}, evidence '
            + (f'{v["score"]:.0f}' if v.get("score") is not None else "not stated") + ".")
    care = [s_["read_with_care"]] if s_.get("read_with_care") else []
    return " ".join([head] + (e.get("lines") or [])[:3] + (s_.get("lines") or [])[:1] + care)


def _score_why(a: dict, numbered: bool = False, notes: bool = False) -> str:
    """One drug's words: its name, then the lines printed under the chart, then, on
    demand, the notes that say what else each score rests on."""
    span = _score_range(a)
    meta = (f'{a["ticker"]} · overall {a["overall"]:.0f}'
            + (f" · rank could sit {span}" if span else ""))
    lead = f'{a["rank"]}. ' if numbered else ""
    lines = (a["efficacy"].get("lines") or []) + (a["safety"].get("lines") or [])
    body = " ".join(html_escape(x) for x in lines)
    more = ((a["efficacy"].get("notes") or []) + (a["safety"].get("notes") or [])
            if notes else [])
    tail = (f'<div class="sc-notes">{" ".join(html_escape(x) for x in more)}</div>'
            if more else "")
    return (f'<div class="sc-why"><b>{lead}{html_escape(a["name"])}</b> '
            f'<span class="m">{html_escape(meta)}</span><br>{body}{tail}</div>')


_STAGE_SHORT = (("Marketed", "marketed"), ("Phase 3", "Phase 3"), ("Phase 2/3", "Phase 2/3"),
                ("Phase 2", "Phase 2"), ("Phase 1", "Phase 1"))


def _stage_short(stage: str) -> str:
    """The stage in one word or two: a marketed drug trialled here is still marketed."""
    for key, short in _STAGE_SHORT:
        if (stage or "").startswith(key):
            return short
    return stage or ""


def _plain_cell(value, why: str | None = None, num: bool = False, tip: str | None = None) -> str:
    """A text cell, or the null dash with the reason on hover."""
    if value in (None, ""):
        why_tip = f' title="{html_escape(why)}"' if why else ""
        return f'<td class="{"n " if num else ""}m"{why_tip}>—</td>'
    hover = f' title="{html_escape(tip)}"' if tip else ""
    return f'<td class="{"n" if num else "sc-txt"}"{hover}>{html_escape(str(value))}</td>'


def _score_rows(placed: list, ticker: str) -> str:
    """The ranked table: rank and the range it could sit in, the drug, its stage, its four
    scores, then how it was given in the trials that scored it (people treated, dose,
    form, frequency, trial length). The open company's rows are marked; a dagger on an
    efficacy figure that rests on strength and wins alone carries its meaning on hover."""
    dagger_tip = ("Size of effect not compared: no peer was tested against the same control "
                  "on the same measure in trials of about the same length, so its size "
                  "counts at 50.")
    rows = ""
    for a in placed:
        focal = a["ticker"] == ticker
        name = (f'<b>{html_escape(a["name"])}</b>' if focal else html_escape(a["name"]))
        rr = a.get("rank_range") or []
        span = (f"{rr[0]}\u2013{rr[1]}" if len(rr) == 2 and rr[0] != rr[1] else "")
        rank = f'{a["rank"]}' + (f'<span class="m sc-rng"> {html_escape(span)}</span>' if span else "")
        e = a["efficacy"].get("score")
        dag = a["efficacy"].get("size_basis") == "not comparable"
        eff = ("<td class=\"n m\">—</td>" if e is None else
               f'<td class="n"{f" title={chr(34)}{html_escape(dagger_tip)}{chr(34)}" if dag else ""}>'
               f'{e:.0f}{"<span class=sc-dg>†</span>" if dag else ""}</td>')
        num = lambda v: "<td class=\"n m\">—</td>" if v is None else f'<td class="n">{v:.0f}</td>'
        reg = a.get("regimen") or {}
        why = reg.get("why") or {}
        n = reg.get("participants")
        rows += (f'<tr class="{"sc-mine" if focal else ""}">'
                 f'<td class="n m sc-rk">{rank}</td>'
                 f'<td>{name} <span class="m">{html_escape(a["ticker"])}</span></td>'
                 f'<td class="m sc-txt">{html_escape(_stage_short(a["stage"]))}</td>'
                 + _score_cell(a["overall"], focal) + eff
                 + num(a["safety"].get("score")) + num(a["evidence"].get("score"))
                 + _plain_cell(f"{n:,}" if n else None, "no participants posted", num=True)
                 + _plain_cell(reg.get("dose"), why.get("dose"))
                 + _plain_cell(reg.get("form"), why.get("form"))
                 + _plain_cell(reg.get("frequency"), why.get("frequency"))
                 + _plain_cell(reg.get("duration"), why.get("duration"),
                               tip=reg.get("duration_span")) + "</tr>")
    head = ("<th title=\"Rank, then where it falls in 95 of 100 redraws of every trial result "
            "within its margin of error\">#</th><th>compound</th><th>stage</th>"
            "<th>overall</th><th>efficacy</th><th>safety</th><th>evidence</th>"
            "<th class=\"sc-reg\" title=\"People treated in its controlled trials\">n</th>"
            "<th class=\"sc-reg\" title=\"Doses its own arms name\">dose</th>"
            "<th class=\"sc-reg\" title=\"How it was given in these trials\">form</th>"
            "<th class=\"sc-reg\" title=\"Dosing schedule its arms name\">frequency</th>"
            "<th class=\"sc-reg\" title=\"Time point of the primary endpoints: treatment length in a "
            "fixed-length trial, follow-up in a survival trial\">weeks</th>")
    return ('<div class="land-wrap"><table class="land sc-table"><thead><tr>'
            f'{head}</tr></thead><tbody>{rows}</tbody></table></div>')


# The terms on screen an analyst might otherwise look up, each in plain words and then
# the method's usual name, so it can be checked elsewhere.
_SCORE_TERMS = (
    ("z-score", "a result divided by its standard error, how far it would vary from one "
                "trial to the next. 1.96 is the usual bar for a real effect (p = 0.05); "
                "3.29 is the bar at p = 0.001 and scores full strength."),
    ("Allowing for the number each trial tested", "the more endpoints a trial tests, the "
                                                  "higher the bar each must clear, so testing "
                                                  "more cannot buy wins (a false discovery "
                                                  "rate correction, within each trial)."),
    ("Averaged across trials, larger trials counting more", "each trial weighted by its "
                                                            "precision, with room for trials "
                                                            "that disagree (a random-effects "
                                                            "meta-analysis)."),
    ("On that basis", "an indirect comparison: each drug against the control both were "
                      "tested on, not a trial of the two against each other."),
    ("Moved toward the class average", "a result pulled part of the way toward the average "
                                       "of its mechanism class, a less certain result "
                                       "further (shrinkage). Only where four or more drugs "
                                       "of one class share a measure and a control."),
    ("Moved toward the average of the drugs here", "strength and wins from one or two "
                                                   "trials pulled part of the way toward the "
                                                   "average of every drug in the indication, "
                                                   "so a single trial cannot carry a drug to "
                                                   "the top (shrinkage)."),
    ("95% interval", "a range built this way holds the true figure 95 times in 100."),
    ("Hazard ratio", "the rate of death or progression on the drug over the rate on the "
                     "comparator, below 1 favouring the drug: 0.72 is a 28% lower rate."),
    ("Points", "percentage points, a difference between two percentages, such as the "
               "drug's rate less the control's."),
)


def _score_method(method: dict) -> str:
    """How it is scored, one labelled line a part, the range after the overall, then
    the caveat and the terms in plain words."""
    parts = [("Efficacy", method.get("efficacy")), ("Safety", method.get("safety")),
             ("Evidence", method.get("evidence")),
             ("Overall", " ".join(t for t in (method.get("overall"),
                                              method.get("uncertainty")) if t))]
    body = "".join(f'<div><span class="k">{k}:</span> {html_escape(_decap(v))}</div>'
                   for k, v in parts if v)
    caveat = (f'<div>{html_escape(method["caveat"])}</div>' if method.get("caveat") else "")
    terms = "".join(f'<div><span class="k">{html_escape(k)}:</span> {html_escape(v)}</div>'
                    for k, v in _SCORE_TERMS)
    return (f'<div class="how-read sc-how"><div>How it is scored, each from 0 to 100.</div>'
            f'{body}{caveat}<div class="sc-terms"><div>The terms in plain words.</div>'
            f'{terms}</div></div>')


def _landscape_scorecard(sc: dict, ticker: str) -> None:
    """The primary figure of an indication, laid out as Comps > Companies: the clinical
    scorecard on the left, the ranked table on the right. What each score rests on, how it
    is scored and who is not on the chart are a click away, never printed under it."""
    assets = sc.get("assets") or []
    placed = [a for a in assets if a.get("placed")]
    rest = [a for a in assets if not a.get("placed")]
    if not placed:
        state("No drug can be scored here yet",
              "A score needs a posted result against a comparator and a safety figure "
              "against a control, and no candidate in this indication has both.")
        return
    section("Clinical scorecard", f"{len(placed)} of {len(assets)} scored",
            basis="efficacy, safety and weight of evidence, averaged · posted results only")
    # Keyed so the theme can stack the chart over the table on a narrow screen.
    with st.container(key="sc_map"):
        left, right = st.columns([1, 1.15], gap="medium")
    with left:
        chart = CH.score_map(
            [{"name": a["name"], "ticker": a["ticker"], "x": a["efficacy"]["score"],
              "y": a["safety"]["score"], "evidence": a["evidence"].get("score"),
              "stage": a["stage"], "boxed": a["boxed"], "rank": a.get("rank"),
              "nosize": a["efficacy"].get("size_basis") == "not comparable",
              "tip": _score_tip(a)} for a in placed],
            760, 500, highlight=ticker,
            x_caption=("efficacy score" if any(a["efficacy"].get("size_basis") == "ranked"
                                               for a in placed)
                       else "efficacy score (strength and wins, no size)"))
        if chart:
            R.show(chart, css_class="chart-mount stretch")
    with right:
        st.markdown(_score_rows(placed, ticker), unsafe_allow_html=True)

    with st.expander("What every score rests on", expanded=False):
        st.markdown("".join(_score_why(a, numbered=True, notes=True) for a in placed),
                    unsafe_allow_html=True)
    with st.expander("How it is scored", expanded=False):
        if rest:
            by_reason: dict = {}
            for a in rest:
                by_reason.setdefault(a.get("why_not") or "not scored", []).append(a)
            parts = []
            for reason, group in by_reason.items():
                names = ", ".join(f'{a["name"]} ({a["ticker"]})' for a in group[:8])
                more = f" and {len(group) - 8} more" if len(group) > 8 else ""
                parts.append(f"{_cap(reason)} ({len(group)}): {names}{more}.")
            st.markdown('<div class="how-read">Not on the chart, because a score is never '
                        f'guessed. {html_escape(" ".join(parts))}</div>',
                        unsafe_allow_html=True)
        st.markdown(_score_method(sc.get("method") or {}), unsafe_allow_html=True)


def _decap(text) -> str:
    text = text or ""
    return text[:1].lower() + text[1:] if text else text


def _landscape_overview(api_base: str, pick: int, ticker: str) -> None:
    """The landscape read for you: the clinical scorecard beside its ranked table, then the
    verdict cards, each its headline and its evidence."""
    try:
        ov = _get_long(api_base, f"/indications/{pick}/overview")
    except (urllib.error.URLError, OSError) as exc:
        state("The overview did not load", str(exc), error=True)
        return
    cards = ov.get("cards") or []
    if ov.get("scorecard"):
        _landscape_scorecard(ov["scorecard"], ticker)
    if not cards:
        if not ov.get("scorecard"):
            state("Not enough to read yet", "no candidate here has posted results or a model")
        return
    st.markdown(_verdict_card(cards[0], lead=True, meaning=False), unsafe_allow_html=True)
    rest = cards[1:]
    if rest:
        st.markdown('<div class="vc-grid">' + "".join(_verdict_card(c, meaning=False)
                                                       for c in rest)
                    + "</div>", unsafe_allow_html=True)


def _stage_chip(stage: str) -> str:
    cls = ("s-mkt" if stage == "Marketed" else "s-mkt-here" if stage.startswith("Marketed")
           else "s-p3" if stage in ("Phase 3", "Phase 2/3") or stage.startswith("Phase 3")
           else "s-p2" if stage.startswith("Phase 2") else "s-p1")
    return f'<span class="stage {cls}">{html_escape(stage)}</span>'


def _landscape_candidates(cands: list) -> None:
    """One row a drug, eight columns in reading order: which drug, how far along, what it
    is, how it is given, what it is worth, its share of the pool, its evidence and any
    boxed warning. Thirteen equal columns made every row a wall of the same weight."""
    head = ("compound", "stage", "what it is", "given", "value a share", "pool kept",
            "evidence", "")
    rows = ""
    for c in cands:
        mech = "; ".join(m["value"] for m in c["mechanisms"][:2]) or (
            "; ".join(c["classes"][:2]) or "mechanism: no free data")
        # A target already named in the mechanism ("PD-1 inhibitor" over "PD-1") says it
        # twice; only a target the mechanism does not spell out is added.
        targets = ", ".join(t for t in c["targets"][:3] if t.lower() not in mech.lower())
        model = c.get("model") or {}
        cur = model.get("currency") or ""
        value = (f'{model["per_share"]:,.2f}' if model.get("per_share") is not None else "·")
        value_sub = " · ".join(x for x in (
            f'PoS {_pct(model.get("pos"), 0)}' if model.get("pos") is not None else "",
            (f'peak {model["peak_revenue"]:,.0f}mm{" " + cur if cur and cur != "USD" else ""}'
             f' {model.get("peak_year") or ""}').strip() if model.get("peak_revenue") else "")
            if x)
        pooled = c.get("pool") or {}
        kept = _pct(pooled.get("ratio"), 0) if pooled.get("pooled") else "·"
        stage = c["stage"] + (" (elsewhere)" if c.get("phase_elsewhere") else "")
        modality = c.get("modality") or ", ".join(c.get("molecule_type") or []) or ""
        route = ", ".join(c["route"]).lower()
        boxed = c.get("boxed_warning") or ""
        how = " ".join(f'<span class="tag">{html_escape(x)}</span>' for x in c["linked_by"])
        warn = (f'<span class="tag warn" title="{html_escape(boxed)}">boxed warning</span>'
                if boxed else "")
        rows += (
            f'<tr><td>{html_escape(c["name"] or "")} '
            f'<span class="m">{html_escape(c["ticker"])}</span>'
            + (f'<span class="sub">sold as {html_escape(", ".join(c["brands"]))}</span>'
               if c.get("brands") else "") + '</td>'
            f'<td>{_stage_chip(stage)}</td>'
            f'<td>{html_escape(mech)}'
            + (f'<span class="sub">{html_escape(targets)}</span>' if targets else "")
            + f'</td><td class="m">{html_escape(modality)}'
            + (f'<span class="sub">{html_escape(route)}</span>' if route else "") + '</td>'
            f'<td class="n">{value}'
            + (f'<span class="sub">{html_escape(value_sub)}</span>' if value_sub else "")
            + f'</td><td class="n">{kept}</td>'
            f'<td class="n">{c["with_results"]}/{len(c["trials"])} posted'
            f'<span class="sub">{how}</span></td>'
            f'<td>{warn}</td></tr>')
    st.markdown(f'<div class="land-wrap"><table class="land"><thead><tr>'
                f'{"".join(f"<th>{h}</th>" for h in head)}'
                f'</tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)
    note("Value a share is the drug's modelled value per share of its own company, so it "
         "ranks a drug within its company, not across companies. Pool kept is the share of "
         "its own forecast a drug keeps once the patients every claimant draws on are "
         "counted once. Evidence: trials with posted results over trials linked here, and "
         "how the drug was linked. Hover a boxed warning to read it.")

    # The same candidates by what they act on, which is the axis modality hides.
    by_mech: dict = {}
    for c in cands:
        keys = [m["value"] for m in c["mechanisms"]] or c["classes"][:1] or ["not in ChEMBL"]
        for k in keys[:2]:
            by_mech.setdefault(k, []).append(c)
    section("Mechanisms in play", len(by_mech))
    mrows = ""
    for mech, members in sorted(by_mech.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        who = ", ".join(f'{m["name"]} ({m["ticker"]}, {m["stage"]})' for m in members)
        mrows += (f'<tr><td>{html_escape(mech)}</td><td class="n">{len(members)}</td>'
                  f'<td class="m">{html_escape(who)}</td></tr>')
    st.markdown(f'<div class="land-wrap"><table class="land"><thead><tr><th>mechanism</th><th>drugs</th><th>who</th>'
                f'</tr></thead><tbody>{mrows}</tbody></table></div>', unsafe_allow_html=True)


def _landscape_efficacy(groups: list, cands: list, pick: int) -> None:
    if not groups:
        state("No posted results", "none of these candidates' trials on this indication "
              "has results posted to ClinicalTrials.gov yet")
    else:
        def label(i):
            g = groups[i]
            return (f'{_short(g["title"], 80)} · {g["unit"] or "no unit"} · '
                    f'{g["n_assets"]} drug{"s" if g["n_assets"] != 1 else ""}, '
                    f'{len(g["rows"])} arms')
        gi = st.selectbox("Endpoint", list(range(len(groups))), format_func=label,
                          key=f"land_ep_{pick}", label_visibility="collapsed")
        g = groups[gi]
        rows = [r for r in g["rows"] if r["value"] is not None]
        chart_rows = [{"label": _short(f'{r["name"]} · {r["arm"]}'
                                       + (f' · {r["category"]}' if r.get("category") else ""),
                                       52)
                       + (f' · w{r["weeks"]:.0f}' if r.get("weeks") else ""),
                       "value": r["value"], "reference": r["placebo"],
                       "group": r["nct_id"]} for r in rows[:40]]
        chart = CH.against_reference(chart_rows, 900, value_fmt=lambda v: f"{v:,.1f}")
        if chart:
            R.show(chart, css_class="chart-mount stretch")
        note("Filled: the arm. Open: the same trial's comparator, placebo where there is "
             "one, else the arm the sponsor calls the control, else the other of two arms. "
             "The figure at the right is the arm less its comparator. Rows between rules "
             "are one trial.")
        head = ("drug", "trial", "wk", "arm", "n", "value", "comparator", "difference",
                "sponsor's estimate", "p")
        body = ""
        last = None
        for r in rows:
            cls = ' class="grp"' if last is not None and r["nct_id"] != last else ""
            last = r["nct_id"]
            est = (f'{r["estimate"]:,.2f}' + (f' ({r["ci"][0]:,.2f} to {r["ci"][1]:,.2f})'
                                              if r.get("ci") else "")
                   if r.get("estimate") is not None else "·")
            spread = f' ± {r["spread"]:,.2f}' if r.get("spread") is not None else ""
            body += (f'<tr{cls}><td>{html_escape(r["name"])} <span class="m">'
                     f'{html_escape(r["ticker"])}</span></td>'
                     f'<td><a href="https://clinicaltrials.gov/study/{r["nct_id"]}" '
                     f'target="_blank">{r["nct_id"]}</a> <span class="m">'
                     f'{html_escape(r["phase"] or "")}</span></td>'
                     f'<td class="n">{_land_num(r.get("weeks"), 0)}</td>'
                     f'<td>{html_escape(_short(r["arm"] or "", 48))}'
                     + ('' if r["arm_is_drug"] else ' <span class="tag">other arm</span>')
                     + f'</td><td class="n">{r["n"] or "·"}</td>'
                     f'<td class="n">{_land_num(r["value"], 2)}{html_escape(spread)}</td>'
                     f'<td class="n">{_land_num(r["placebo"], 2)}'
                     + (f' <span class="tag">{html_escape(r["reference_kind"])}</span>'
                        if r.get("reference_kind") and r["reference_kind"] != "placebo" else "")
                     + '</td>'
                     f'<td class="n">{_land_num(r["delta"], 2)}</td>'
                     f'<td class="n">{html_escape(est)}</td>'
                     f'<td class="n">{html_escape(r["p_value"] or "·")}</td></tr>')
        st.markdown(f'<div class="land-wrap"><table class="land"><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}'
                    f'</tr></thead><tbody>{body}</tbody></table></div>', unsafe_allow_html=True)
        note(f'{g["title"]} ({g["unit"] or "no unit"}, {g["param_type"] or "measure"}). '
             "Trials differ in population, duration and background therapy, so read a "
             "difference against its own placebo before reading it against another trial's. "
             "An arm tagged other arm names none of the drug's names: an active comparator "
             "or an arm the sponsor labelled by letter.")
    quotes = [(c, q) for c in cands for q in (c.get("readouts") or [])]
    if quotes:
        section("Readouts from the press", len(quotes), "the sentence each was read from")
        qrows = "".join(
            f'<tr><td class="pol-d">{html_escape((q.get("date") or "")[:10])}</td>'
            f'<td class="pol-l">{html_escape(c["name"])}</td>'
            f'<td class="pol-k">{html_escape(q.get("outcome") or "")}</td>'
            f'<td class="pol-t">'
            + (f'<a href="{html_escape(q["url"])}" target="_blank">' if q.get("url") else "")
            + html_escape(_short(q.get("quote") or "", 260))
            + ("</a>" if q.get("url") else "") + "</td></tr>"
            for c, q in quotes)
        st.markdown(f'<table class="pol"><tbody>{qrows}</tbody></table>',
                    unsafe_allow_html=True)


def _landscape_safety(rows: list) -> None:
    rated = [r for r in rows if r.get("trials")]
    if not rated:
        state("No posted safety data", "none of these candidates' trials on this "
              "indication has adverse events posted to ClinicalTrials.gov yet")
    else:
        left, right = st.columns(2, gap="medium")
        for col, key, title in ((left, "serious", "Serious adverse events"),
                                (right, "withdrawn", "Withdrawn for an adverse event")):
            with col:
                section(title, basis="% · control open")
                pts = [{"label": _short(f'{r["name"]} ({r["ticker"]})', 30),
                        "value": r[f"{key}_rate"] * 100,
                        "reference": (r[f"placebo_{key}_rate"] * 100
                                      if r.get(f"placebo_{key}_rate") is not None else None),
                        "group": r["asset_id"]}
                       for r in rated if r.get(f"{key}_rate") is not None]
                chart = CH.against_reference(pts, 520, label_width=170,
                                             value_fmt=lambda v: f"{v:.0f}%",
                                             delta_fmt=lambda v: f"{v:+.1f} pts")
                if chart:
                    R.show(chart, css_class="chart-mount stretch")
                else:
                    note("no rate posted")
        def _vs(r, key, digits=1):
            mine, ctrl = r.get(f"{key}_rate"), r.get(f"placebo_{key}_rate")
            if mine is None:
                return "·"
            return (f'{_pct(mine, digits)}<span class="sub">vs {_pct(ctrl, digits)}</span>'
                    if ctrl is not None else _pct(mine, digits))

        head = ("drug", "trials", "participants", "serious AE", "withdrawn for AE",
                "deaths", "commonest events, drug vs control", "")
        body = ""
        for r in rated:
            events = "<br>".join(
                f'{html_escape(e["term"])} {_pct(e["rate"], 0)}'
                + (f' <span class="m">vs {_pct(e["placebo_rate"], 0)}</span>'
                   if e.get("placebo_rate") is not None else "")
                for e in (r.get("top_events") or [])[:4])
            boxed = r.get("boxed_warning") or ""
            warn = (f'<span class="tag warn" title="{html_escape(boxed)}">boxed warning</span>'
                    if boxed else "")
            body += (f'<tr><td>{html_escape(r["name"])} <span class="m">'
                     f'{html_escape(r["ticker"])}</span></td>'
                     f'<td class="n">{r["trials"]}<span class="sub">'
                     f'{html_escape(r.get("control_kind") or "no control")}</span></td>'
                     f'<td class="n">{r.get("participants") or "·"}<span class="sub">'
                     f'vs {r.get("placebo_participants") or "·"}</span></td>'
                     f'<td class="n">{_vs(r, "serious")}</td>'
                     f'<td class="n">{_vs(r, "withdrawn")}</td>'
                     f'<td class="n">{_vs(r, "deaths", 2)}</td>'
                     f'<td>{events}</td><td>{warn}</td></tr>')
        st.markdown(f'<div class="land-wrap"><table class="land"><thead><tr>'
                    f'{"".join(f"<th>{h}</th>" for h in head)}'
                    f'</tr></thead><tbody>{body}</tbody></table></div>', unsafe_allow_html=True)
        note("Drug arms pooled across the drug's trials on this indication, against the "
             "control arms of the same trials: placebo, the arm the sponsor calls the "
             "control, or the other of two arms. A trial with no control adds to the drug "
             "side only. Participants: drug arms / control arms. The commonest events are "
             "the drug's rate with the control's in brackets.")
    warned = [r for r in rows if not r.get("trials") and r.get("boxed_warning")]
    if warned:
        section("Boxed warnings without posted trial safety", len(warned))
        st.markdown('<table class="pol"><tbody>' + "".join(
            f'<tr><td class="pol-l">{html_escape(r["name"])}</td>'
            f'<td class="pol-t">{html_escape(_short(r["boxed_warning"], 300))}</td></tr>'
            for r in warned) + "</tbody></table>", unsafe_allow_html=True)


def _rating_tile(api_base: str, ticker: str, up) -> tuple:
    """The rating Key insights shows, with the twelve-month move beside it.

    "Against the price" alone read +12% as a call, while the rating is the return above
    the cost of equity, where a fairly priced share is a hold. Both tabs now say the same
    thing, from the same cached fair value.
    """
    try:
        rated = (api_get(api_base, f"/companies/{ticker}/fair-value") or {}).get("rating") or {}
    except (urllib.error.URLError, OSError):
        rated = {}
    call = rated.get("rating") if rated.get("ok") else None
    move = f"{up:+.0%}" if up is not None else ""
    if not call:
        return ("against the price", move or "—", "", None, "",
                "12-month value over the close")
    tone = " up" if call in ("Strong buy", "Buy") else " down" if call == "Sell" else ""
    return ("rating", call, "", move, tone,
            f"model range {T.num(rated.get('low_today'), 0)} to "
            f"{T.num(rated.get('high_today'), 0)}")


def _sotp_bridge(s: dict) -> None:
    """The sum of the parts as a bridge, per share, read against the price.

    Marketed products, then the pipeline after its probability, then the lines no
    asset carries, add to the modelled enterprise value; net cash turns it into
    equity; the roll-forward at the cost of equity less the dividend is the
    twelve-month figure. The price is the dashed rule the bars are read against,
    and it is not one of them.
    """
    m, p, lines = s.get("marketed") or {}, s.get("pipeline") or {}, s.get("lines") or {}
    if m.get("per_share") is None:
        return
    steps = [{"label": "marketed", "value": m["per_share"], "kind": "start"}]
    if p.get("n"):
        steps.append({"label": "pipeline", "value": p.get("per_share") or 0.0,
                      "kind": "step"})
    if lines.get("n"):
        steps.append({"label": "lines", "value": lines.get("per_share") or 0.0,
                      "kind": "step"})
    future = s.get("future") or {}
    if future.get("per_share") is not None:
        steps.append({"label": "launches", "value": future["per_share"],
                      "kind": "step"})
    else:
        steps.append({"label": "launches", "value": None, "kind": "null"})
    growth = s.get("growth_investment") or {}
    if growth.get("per_share"):
        steps.append({"label": "growth capital", "value": growth["per_share"],
                      "kind": "step"})
    anchor_year = (s.get("valuation_anchor") or "")[:4]
    steps.append({"label": f"FY{anchor_year[2:]} EV" if anchor_year else "EV",
                  "kind": "end"})
    # The rNPV stands at the fiscal year end; carry it to the price date before the
    # price rule means anything.
    if s.get("carry_per_share"):
        steps.append({"label": "to close", "value": s["carry_per_share"],
                      "kind": "step"})
        steps.append({"label": "EV today", "kind": "end"})
    if s.get("net_cash_per_share") is not None:
        steps.append({"label": "net cash" if s["net_cash_per_share"] >= 0 else "net debt",
                      "value": s["net_cash_per_share"], "kind": "step"})
        # Pensions, minorities, deal instalments owed and stakes held at equity. The
        # equity figure counts them, so a bridge without them ended above the headline:
        # AstraZeneca's bars summed to 175.93 against the 175.38 printed over them.
        if s.get("other_claims_per_share"):
            steps.append({"label": "other claims", "value": s["other_claims_per_share"],
                          "kind": "step"})
        steps.append({"label": "equity", "kind": "end"})
    else:
        steps.append({"label": "net cash", "value": None, "kind": "null"})
    if s.get("forward_12m") is not None and s.get("equity_per_share") is not None:
        ke = s.get("cost_of_equity") or 0.0
        steps.append({"label": f"+{ke * 100:.1f}%", "value": s["equity_per_share"] * ke,
                      "kind": "step"})
        if s.get("dps"):
            steps.append({"label": "dividend", "value": -s["dps"], "kind": "step"})
        steps.append({"label": "12m", "kind": "end"})
    # The price is named in the chip, not at the end of its rule, where it sat on the
    # twelve-month bar.
    section("Sum of the parts",
            basis=(f"$ a share · the price dashed, {s['close']:,.2f}" if s.get("close")
                   else "$ a share"))
    R.show(CH.waterfall(steps, 800, 210, value_fmt=lambda x: f"{x:,.2f}",
                        reference=({"label": None, "value": s["close"]}
                                   if s.get("close") else None)),
           css_class="chart-mount stretch")
    bits = []
    if p.get("n") and p.get("per_share_unrisked") is not None:
        bits.append(f"pipeline {p['per_share_unrisked']:,.2f} before probability, "
                    f"{(p.get('per_share') or 0):,.2f} after")
    if future.get("per_share") is not None:
        own = future.get("own_rate")
        bits.append(f"future launches at "
                    f"{future.get('rate_used', future['rate']):.2f} of revenue per R&D "
                    f"dollar: own {own:.2f} on {future.get('own_launches')} launches at "
                    f"{future.get('credibility', 0):.0%} weight, pool "
                    f"{future['rate']:.2f} across {future.get('pooled_filers')} filers"
                    if own is not None else
                    f"future launches at {future['rate']:.2f} of revenue per R&D dollar, "
                    f"the pool across {future.get('pooled_filers')} filers")
        bits.append(f"{future.get('lag_years')}y lag, first in "
                    f"{future.get('first_launch_year')}")
    if (s.get("growth_investment") or {}).get("share"):
        g = s["growth_investment"]
        bits.append(f"growth capital at {g['share']:.2f} of every dollar of revenue the "
                    f"book adds: {g.get('basis') or ''}")
        if future.get("history_cohorts"):
            history = future.get("history_rd") or {}
            bits.append(f"{sum(history.values()):,.0f}mm of R&D already spent "
                        f"({min(history)}-{max(history)}) buys the launches before then, "
                        f"less {future.get('named_overlap') or 0:,.0f}mm of revenue from "
                        "launches the book names")
        # A cap that binds in some year but trims less than half a percent overall read
        # as "which cuts 0% of what they would sell": a fact about nothing.
        if future.get("capped_from") and (future.get("capped_share") or 0) >= 0.005:
            bits.append(f"launches held to the book's best year in real terms, "
                        f"{future.get('book_peak_year')}'s "
                        f"{future.get('book_peak', 0):,.0f}mm grown at the long-run rate, "
                        f"from {future['capped_from']}, which cuts "
                        f"{future.get('capped_share', 0):.0%} of what they would sell")
    # Computed since the franchise was built and rendered nowhere, so the one input
    # on this page that already moves with the market looked like a fixed assumption.
    if future.get("long_run_basis") and future.get("long_run_growth") is not None:
        bits.append(f"long-run growth {future['long_run_growth']:.2%}, "
                    f"{_short(future['long_run_basis'], 62)}")
    # Computed on every foreign filer's per-share figure and rendered nowhere, so a
    # Novo figure in dollars gave no way to see the krone rate that made it. The
    # translation is the largest per-unit sensitivity in the app: one for one.
    _fx = s.get("fx") or {}
    if _fx.get("rate") and _fx.get("currency"):
        bits.append(f"translated at {_fx['currency']} {_fx['rate']:.4f} USD"
                    + (f", {_fx['as_of']}" if _fx.get("as_of") else ""))
    if s.get("balance_sheet_as_of"):
        bits.append(f"balance sheet {s['balance_sheet_as_of']}"
                    + (f", cash {s['cash']:,.0f}mm on hand and no debt line filed"
                       if (s.get("debt_basis") or "").startswith("no debt")
                       and s.get("cash") is not None else ""))
    if s.get("valuation_anchor") and s.get("years_to_price"):
        bits.append(f"valued at {s['valuation_anchor']}, carried "
                    f"{s['years_to_price']:.2f}y to the {s.get('price_date')} close")
    if s.get("cost_of_equity") is not None:
        bits.append(f"cost of equity {s['cost_of_equity']:.2%}, "
                    f"{_short(s.get('cost_of_equity_basis'), 44)}")
    if s.get("dps"):
        bits.append(f"dividends FY{s.get('dividends_year')} {s['dps']:,.2f} a share")
    for missing in s.get("missing") or []:
        bits.append(missing)
    if bits:
        # Folded, one per line. Run together under the chart they were a wall of small
        # print the eye skipped, and each is a separate fact about how the bars were made.
        with st.expander("How the sum is built"):
            st.markdown('<div class="byline">' + "<br>".join(html_escape(b) for b in bits)
                        + "</div>", unsafe_allow_html=True)


def _revenue_bars(path, last, base, growth, has_lines, has_pipe) -> str:
    """Revenue by year as stacked columns, in HTML so the plot can fill its column.

    Each forecast year stacks what is sold, the lines no asset carries and the pipeline
    after its probability, with what the probability takes off hatched on top, so the
    risked total and the haircut read on one bar. The reported year is one grey bar:
    the book's own revenue, with the whole company's drawn as a dashed line across the
    plot. Heights are flex shares of the tallest stack rather than pixels, which is
    what lets the plot stretch to meet the value column beside it. A null is a gap,
    never a zero.
    """
    actual = _mix_hex(TK.TEXT, TK.GROUND, 0.4)
    lines_c = _mix_hex(TK.MUTED, TK.GROUND, 0.5)
    # Purple, the pipeline's colour in the value list on this tab: the Phase 3 green it
    # had read as part of the marketed bar under it. What PoS takes off is the same purple
    # hatched over a dim ground of it, so a thin cap stays apart from the risked segment.
    pipe_c = TK.PURPLE_BOOK
    cut_c = _mix_hex(pipe_c, TK.GROUND, 0.65)
    cols = []
    if last:
        cols.append({"year": f"FY{last['fiscal_year']}A", "growth": None, "total": base,
                     "segs": [("the book, reported", base, actual, "")]})
    for r, g in zip(path, growth):
        pipe, risked = r.get("pipeline"), r.get("pipeline_risked")
        haircut = (pipe - risked) if pipe is not None and risked is not None else None
        segs = [("marketed", r.get("marketed"), TK.UP, "")]
        if has_lines:
            segs.append(("lines", r.get("lines"), lines_c, ""))
        if has_pipe:
            segs += [("pipeline, after PoS", risked, pipe_c, ""),
                     ("taken off by PoS", haircut, pipe_c, " hatch")]
        cols.append({"year": f"FY{r['year']}E", "growth": g,
                     "total": r.get("total_risked"), "segs": segs})
    company = last.get("value") if last else None
    stacks = [sum(v for _n, v, _c, _h in c["segs"] if v and v > 0) for c in cols]
    top = max(stacks + [company or 0.0, 0.0])
    if top <= 0:
        return ""

    def share(v):
        # Flex shares out of a thousand: a sum under one would leave the column unfilled.
        return f"{max(v, 0.0) / top * 1000:.3f}"

    out = []
    for c, height in zip(cols, stacks):
        segs = [(n, v, col, h) for n, v, col, h in c["segs"] if v and v > 0]
        parts = [f'<div style="flex:{share(top - height)} 1 0"></div>']
        for i, (name, v, colour, hatch) in enumerate(reversed(segs)):
            label = (f'<span class="rb-v">{c["total"]:,.0f}</span>'
                     if i == 0 and c["total"] is not None else "")
            ground = f";--c2:{cut_c}" if hatch else ""
            parts.append(f'<div class="rb-seg{hatch}" style="flex:{share(v)} 1 0;'
                         f'--c:{colour}{ground}" title="{html_escape(c["year"])} '
                         f'{html_escape(name)}: {v:,.0f}">{label}</div>')
        g = c["growth"]
        tone = "" if g is None else " up" if g > 0 else " down" if g < 0 else ""
        out.append(f'<div class="rb-col"><div class="rb-stack">{"".join(parts)}</div>'
                   f'<div class="rb-x"><span>{html_escape(c["year"])}</span>'
                   f'<span class="rb-g{tone}">{"" if g is None else f"{g:+.1%}"}</span>'
                   "</div></div>")
    ref = ""
    if company:
        ref = (f'<div class="rb-ref"><div style="flex:{share(top - company)} 1 0"></div>'
               f'<div class="rb-line"></div><div style="flex:{share(company)} 1 0"></div>'
               "</div>")
    keys = [("marketed", TK.UP, "")]
    if has_lines:
        keys.append(("lines", lines_c, ""))
    if has_pipe:
        keys += [("pipeline, after PoS", pipe_c, ""), ("taken off by PoS", pipe_c, " hatch")]
    if last:
        keys.append(("the book, reported", actual, ""))
    legend = "".join(f'<span><i class="rb-sw{h}" style="--c:{col}'
                     + (f";--c2:{cut_c}" if h else "")
                     + f'"></i>{html_escape(n)}</span>' for n, col, h in keys)
    if company:
        legend += (f'<span><i class="rb-sw dash"></i>whole company, '
                   f'FY{last["fiscal_year"]} {company:,.0f}</span>')
    return (f'<div class="rbar"><div class="rb-legend">{legend}</div>'
            f'<div class="rb-plot">{ref}{"".join(out)}</div></div>')


def _revenue_split(s: dict) -> None:
    """Revenue by year, marketed against pipeline, beside the last year reported.

    The pipeline is shown before and after its probability, because the sum of the
    parts counts it after and the build draws it before, and a reader should be able
    to see both numbers in one place. Whatever has no forecast is named under it.
    """
    path = s.get("revenue_path") or []
    last = s.get("last_reported")
    if not path:
        return
    section("Revenue by year", basis=f"{_mm()} · the modelled book")
    years = ([f"FY{last['fiscal_year']}A"] if last else []) + [f"FY{r['year']}E" for r in path]
    has_lines = any(r.get("lines") for r in path)
    has_pipe = any(r.get("pipeline") for r in path)
    rows = [("marketed", [None if last else None] + [r["marketed"] for r in path])]
    if has_pipe:
        rows.append(("pipeline, before PoS", [None] + [r["pipeline"] for r in path]))
        rows.append(("pipeline, after PoS", [None] + [r["pipeline_risked"] for r in path]))
    if has_lines:
        rows.append(("lines", [None] + [r["lines"] for r in path]))
    base = s.get("last_modelled")
    rows.append(("total, risked", ([base] if last else [])
                 + [r["total_risked"] for r in path]))
    if not last:
        rows = [(k, v[1:]) for k, v in rows]
    growth = []
    # Growth runs on the modelled book against its own reported revenue. Measured
    # against the whole company's total, a book covering 68% of Sanofi read as a 21.5%
    # fall; the company total sits in its own row so the gap stays visible.
    prev = base
    for r in path:
        growth.append((r["total_risked"] / prev - 1.0) if prev else None)
        prev = r["total_risked"]
    rows.append(("growth", ([None] if last else []) + growth))
    if last:
        rows.append(("reported, whole company", [last["value"]] + [None] * len(path)))

    def cell(value, pct=False):
        if value is None:
            return '<td class="rs-v none">·</td>'
        if pct:
            tone = " up" if value > 0 else " down" if value < 0 else ""
            return f'<td class="rs-v{tone}">{value:+.1%}</td>'
        return f'<td class="rs-v">{value:,.0f}</td>'
    head = "".join(f"<th>{html_escape(y)}</th>" for y in years)
    body = ""
    for label, values in rows:
        cls = (' class="rs-total"' if label.startswith("total")
               else ' class="rs-growth"' if label == "growth"
               else ' class="rs-ref"' if label.startswith("reported") else "")
        body += (f'<tr{cls}><td class="rs-k">{html_escape(label)}</td>'
                 + "".join(cell(v, pct=(label == "growth")) for v in values) + "</tr>")
    st.markdown(_revenue_bars(path, last, base, growth, has_lines, has_pipe),
                unsafe_allow_html=True)
    # What has no forecast qualifies the bars, so it sits under them and the half ends
    # on its fold, level with the value half's.
    if s.get("not_valued"):
        st.markdown('<div class="byline rb-foot">no forecast, so not in any of these: '
                    + html_escape(", ".join(f"{n['name']} {n['revenue']:,.0f}mm"
                                            for n in s["not_valued"])) + "</div>",
                    unsafe_allow_html=True)
    # The bars carry the totals and the growth; the split to the unit sits under them.
    with st.expander("The figures"):
        st.markdown(f'<table class="rs"><thead><tr><th></th>{head}</tr></thead>'
                    f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def _breakpoints(api_base: str, ticker: str):
    try:
        return api_get(api_base, f"/companies/{ticker}/breakpoints")
    except (urllib.error.URLError, OSError):
        return None


def _lever_value(kind: str, value, key: str = "") -> str:
    if value is None:
        return "·"
    if key == "launch_rate":
        return f"{value:.3f} per R&D $"
    if kind == "year":
        return f"{int(value)}"
    if kind == "years":
        return f"{int(value)}y" if float(value).is_integer() else f"{value:.1f}y"
    if kind == "level":
        return f"${value:,.0f}mm"
    if kind in ("scale",):
        return f"×{value:.2f}"
    if kind == "price":
        return f"${value * 1e6:,.0f}"
    return f"{value:.2%}"


def _lever_move(kind: str, model, value, key: str = "") -> str:
    if value is None:
        return "not reachable alone"
    if key == "launch_rate":
        return f"{value - model:+.3f}"
    if kind == "year":
        return f"{int(value) - int(model):+d}y"
    if kind == "years":
        return f"{value - model:+.0f}y"
    if kind in ("scale", "price", "level"):
        return f"{value / model - 1:+.0%}" if model else "·"
    return f"{(value - model) * 100:+.2f} pts"


def _fair_value_range(api_base: str, ticker: str) -> None:
    """The value across lenses, each a range with its basis, against the price.

    The sum of the parts is the model's own number and is drawn as such; the rest are the
    ways a price is otherwise judged, and they are checks on it rather than answers. The
    line under the chart splits the gap to the price into what the revenue forecast
    explains, read against the company's own guidance, and what is left for the
    valuation's conventions."""
    try:
        fv = api_get(api_base, f"/companies/{ticker}/fair-value")
    except (urllib.error.URLError, OSError):
        return
    if not fv or not fv.get("ok") or not fv.get("lenses"):
        return
    close = fv["close"]
    money = (lambda v: f"${v:,.2f}") if close < 100 else (lambda v: f"${v:,.0f}")
    section("Fair value range", basis="$ a share · each lens a range, the price dashed")
    rows = [{"label": l["lens"], "low": l["low"], "high": l["high"], "mid": l.get("mid"),
             "emphasis": l["key"].startswith("sotp")} for l in fv["lenses"]]
    R.show(CH.football_field(rows, 800, 32 + 24 * len(rows), marker=close,
                             value_fmt=money, label_width=270),
           css_class="chart-mount stretch")
    split = fv.get("revenue_split") or {}
    guidance_text = None
    if split.get("ok") and split.get("matched_equity") is not None:
        g, m = split["guidance"], split["modelled"]
        unmodelled = split.get("unmodelled_prior_year") or 0.0
        gap = close - fv["equity_per_share"]
        cur = f"{split.get('unit') or ''} ".lstrip()
        text = (f"FY{split['year']}: the modelled book reads {cur}{m['total'] / 1e3:,.1f}bn"
                + (f" plus {cur}{unmodelled / 1e3:,.1f}bn of FY{split['year'] - 1} revenue it "
                   "does not carry" if unmodelled >= 1 else "")
                + f", against guidance of {cur}{g['mid'] / 1e3:,.1f}bn ({split['gap_pct']:+.1%}; "
                f"{g['basis']}). Matched to guidance the value is "
                f"{money(split['matched_equity'])}, so the revenue level explains "
                f"{split['explained_by_revenue']:+,.2f} of the {gap:+,.2f} gap to the price, "
                f"and {split['left_for_conventions']:+,.2f} is left for how long growth "
                "lasts, costs, discounting and what the book does not carry.")
        guidance_text = text
    elif split.get("reason"):
        guidance_text = "revenue against guidance: " + split["reason"]
    with st.expander("How each lens is built"):
        # The guidance reading explains the gap between the lenses and the price, so it
        # opens with them rather than floating under the chart on its own.
        if guidance_text:
            st.markdown(f'<div class="byline">{html_escape(guidance_text)}</div>',
                        unsafe_allow_html=True)
        body = "".join(
            f'<tr><td class="rs-k">{html_escape(l["lens"])}</td>'
            f'<td class="rs-v">{html_escape(money(l["low"]))}</td>'
            f'<td class="rs-v">{html_escape(money(l["mid"])) if l.get("mid") is not None else "·"}</td>'
            f'<td class="rs-v">{html_escape(money(l["high"]))}</td>'
            f'<td class="rs-k">{html_escape(l.get("basis") or "")}</td></tr>'
            for l in fv["lenses"])
        st.markdown('<table class="rs"><thead><tr><th>lens</th><th>low</th><th>mid</th>'
                    f'<th>high</th><th>basis</th></tr></thead><tbody>{body}</tbody></table>',
                    unsafe_allow_html=True)


def _what_breaks_it(api_base: str, ticker: str, limit: int = 10) -> None:
    """Which assumptions the value rests on, and how far each can move before the value
    and the price meet. A board does not need the number to the cent; it needs to know
    what breaks it, and whether that rests on a filing or on a judgement."""
    b = _breakpoints(api_base, ticker)
    if not b or not b.get("ok"):
        return
    levers = [l for l in b.get("levers") or [] if l.get("reachable")][:limit]
    if not levers:
        return
    gap = b.get("gap_per_share") or 0.0
    basis = ("what the price needs, each alone" if b.get("direction") == "up"
             else "how far each can fall before the price, each alone")
    section("What breaks it", basis=basis)
    # The lead sentence is the answer and stays. The ones after it restate the table's
    # evidence column and the risks table below, so they fold with the caption.
    sentences = (b.get("sentence") or {}).get("body") or []
    if sentences:
        st.markdown(f'<div class="byline">{html_escape(sentences[0])}</div>',
                    unsafe_allow_html=True)
    body = ""
    for l in levers:
        shown = l.get("shown") or []
        model = _lever_value(l["kind"], l["model"], l.get("key", ""))
        brk = _lever_value(l["kind"], l["break"], l.get("key", ""))
        if l["kind"] == "scale" and len(shown) == 1 and shown[0].get("break") is not None:
            model, brk = f"{shown[0]['model']:.2%}", f"{shown[0]['break']:.2%}"
        grade = l.get("evidence") or "ungraded"
        body += (f'<tr><td class="rs-k">{html_escape(l["name"])}</td>'
                 f'<td class="rs-k">{html_escape(l["lever"])}</td>'
                 f'<td class="rs-v">{html_escape(model)}</td>'
                 f'<td class="rs-v">{html_escape(brk)}</td>'
                 f'<td class="rs-v">{html_escape(_lever_move(l["kind"], l["model"], l["break"], l.get("key", "")))}</td>'
                 f'<td class="rs-k">{html_escape(grade)} · {html_escape(l.get("evidence_class") or "")}</td></tr>')
    st.markdown('<table class="rs"><thead><tr><th>where</th><th>assumption</th>'
                '<th>model</th><th>break</th><th>move</th><th>evidence</th></tr></thead>'
                f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)
    held = " and ".join(b.get("held") or [])
    folded = [f"value {b['equity_per_share']:,.2f} against a close of {b['close']:,.2f}, "
              f"a gap of {gap:+,.2f} a share; each row moves one assumption alone and "
              f"holds {held}"] + list(sentences[1:])
    uncapped = next((l for l in levers if l.get("key") == "fade_shift_uncapped"
                     and l.get("shown")), None)
    if uncapped:
        peaks = "; ".join(f'{p["product"]} {p["model"]:,.0f}mm to {p["break"]:,.0f}mm'
                          for p in uncapped["shown"])
        folded.append("uncapped growth fade at the break, peak revenue: " + peaks)
    note("<br>".join(html_escape(line) for line in folded))
    groups = b.get("groups") or []
    if not groups:
        return
    section("Risks that move together", basis="valued apart, fail together")
    rows = ""
    for g in groups:
        members = ", ".join(
            f"{m['name']} {m['per_share']:,.2f}" if m.get("per_share") is not None
            else m["name"] for m in g.get("members") or [])
        fail = (f"{g['if_all_fail']:,.2f}" if g.get("if_all_fail") is not None
                else "exposure only")
        also = ", ".join(g.get("elsewhere") or []) or "·"
        exposure = (f"{g['exposure_per_share']:,.2f}"
                    if g.get("exposure_per_share") is not None else "·")
        rows += (f'<tr><td class="rs-k">{html_escape(g["group"])}</td>'
                 f'<td class="rs-k">{html_escape(g["kind"])}</td>'
                 f'<td class="rs-k">{html_escape(members)}</td>'
                 f'<td class="rs-v">{html_escape(exposure)}</td>'
                 f'<td class="rs-v">{html_escape(fail)}</td>'
                 f'<td class="rs-k">{html_escape(also)}</td></tr>')
    st.markdown('<table class="rs"><thead><tr><th>group</th><th>kind</th><th>members, $ a '
                'share</th><th>exposure</th><th>value if all fail</th><th>also held by</th>'
                f'</tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    note("a mechanism group's pipeline members failed together is a stress, not a "
         "probability; a payer group or franchise is exposure only")


def _pipeline_development(api_base: str, ticker: str) -> None:
    """Every counted pipeline line's next gate against what reaching it costs, folded
    with the further reads: a view beside the value, never in it
    (docs/design/development-cost.md). A failed read says it did not load."""
    try:
        payload, problem = api_get(api_base, f"/companies/{ticker}/development"), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        payload, problem = None, str(exc).rstrip(".")
    failing = len((payload or {}).get("failing") or [])
    label = "Pipeline development, next gate" + (
        f" · {failing} {'gate costs' if failing == 1 else 'gates cost'} more to reach "
        f"than {'it is' if failing == 1 else 'they are'} worth risked" if failing else "")
    with st.expander(label, expanded=False):
        if problem:
            st.markdown(f'<div class="byline">{html_escape(_GATE_FAILED.format(error=problem))}'
                        '</div>', unsafe_allow_html=True)
        else:
            st.markdown(_gate_book_html(payload), unsafe_allow_html=True)


def _book(api_base: str, ticker: str, selected):
    """The company above the compound, because that is the unit of coverage.

    States three things together and refuses to state the first without the other two:
    what the modelled pipeline is worth per share, what fraction of today's price that
    explains, and how much of the business it actually covers. A model over one product
    of six will always look small against a market capitalisation, and reading that as
    "the market is wrong" rather than "the model is thin" is the easiest mistake this
    page could invite.

    Under it, the two views of the same book: what each asset is worth (the list, which
    is also the picker) and when the revenue that makes it arrives (the build). Returns
    the verdict and the id of a row the reader just clicked, if any.
    """
    try:
        v = api_get(api_base, f"/companies/{ticker}/forecast-verdict")
    except (urllib.error.URLError, OSError):
        return None, None
    if not v.get("ok") or not (v.get("per_share") or v.get("streams")
                               or v.get("placeholders")):
        # Without this the tab opened straight on an empty assumptions grid for
        # whichever asset sorts first (Bayer's acetaminophen), with nothing to say the
        # company has no model yet rather than the page having failed.
        if v.get("ok") or v.get("modelled") is not None:
            section(f"{ticker} · the whole company")
            state(f"No model for {ticker} yet",
                  "No asset carries assumptions, so there is no sum of the parts, "
                  "twelve-month value or rating. Pick an asset below and enter or import "
                  "its assumptions to start one.")
            # A peer multiple needs no product model, so this lens stands alone here.
            _peer_value_section(api_base, ticker)
        return v, None, None
    note_body = v.get("note") or {}
    coverage = v.get("coverage") or {}
    modelled = v.get("modelled") or []
    counted = [m for m in modelled if m.get("counted", True)]
    _BOOK_UNIT["currency"] = (((v.get("sotp") or {}).get("fx") or {}).get("currency")
                              or "USD")

    section(f"{ticker} · the whole company",
            basis=f"{len(counted)} counted of {len(modelled)} drawn")
    sotp = v.get("sotp") or {}
    if sotp.get("equity_per_share") is not None:
        up = sotp.get("upside")
        tiles = [("equity per share", T.num(sotp["equity_per_share"], 2), "", None, "",
                  "sum of the parts, today"),
                 ("12-month value", T.num(sotp.get("forward_12m"), 2)
                  if sotp.get("forward_12m") is not None else "—", "", None, "",
                  "rolled at the cost of equity, less dividends"),
                 ("share price", T.num(v.get("close"), 2), "", None, "",
                  f"close {v.get('close_date') or ''}"),
                 _rating_tile(api_base, ticker, up)]
    elif sotp.get("enterprise_per_share") is not None:
        # The balance sheet could not be added: the sum stops at enterprise value and
        # the cash on hand is shown beside it rather than folded in.
        tiles = [("enterprise per share",
                  T.num(sotp.get("enterprise_today_per_share",
                                 sotp["enterprise_per_share"]), 2), "",
                  None, "", "sum of the parts, today, before the balance sheet"),
                 ("cash on hand", T.num(sotp.get("cash_per_share"), 2)
                  if sotp.get("cash_per_share") is not None else "none", "", None, "",
                  "a share; no debt line filed against it"),
                 ("share price", T.num(v.get("close"), 2), "", None, "",
                  f"close {v.get('close_date') or ''}"),
                 ("share of price",
                  T.pct((v.get("pct_of_price") or 0) * 100, 1) if v.get("pct_of_price")
                  else "—", "", None, "", "enterprise value over the close")]
    else:
        tiles = [("pipeline per share",
                  T.num(v.get("per_share"), 2) if v.get("per_share") else "—", "", None,
                  "", "counted assets and lines"),
                 ("share price", T.num(v.get("close"), 2), "", None, "",
                  f"close {v.get('close_date') or ''}"),
                 ("share of price",
                  T.pct((v.get("pct_of_price") or 0) * 100, 1) if v.get("pct_of_price")
                  else "—", "", None, "", "explained by the model")]
    if coverage.get("share") is not None:
        basis = ("reported revenue" if coverage.get("basis") == "reported total"
                 else "tagged product rows")
        tiles.append(("revenue covered", T.pct(coverage["share"] * 100, 1), "",
                      None, "", f"of FY{coverage['fiscal_year']} {basis}"))
    nxt = v.get("next_catalyst") or {}
    if nxt.get("expected_date"):
        tiles.append(("next catalyst", nxt["expected_date"], "", None, "",
                      (nxt.get("title") or nxt.get("catalyst_type") or "")[:34]))
    # The figures first, across the page; then the value on the left (the sum of the
    # parts over the range of lenses) and the forecast on the right (the summary over
    # the revenue by year); then the revenue build across the page; then each asset,
    # the list beside the one picked; and the further reads at the foot. The value
    # keeps the wider share for its charts' step labels, but less than it had: the
    # forecast half holds the densest text. Whichever half is shorter gives way above
    # its second section, so both end on one line.
    st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)
    value_col, forecast_col = st.columns([1.3, 1], gap="medium")
    with value_col:
        if sotp.get("marketed", {}).get("per_share") is not None:
            _sotp_bridge(sotp)
        _fair_value_range(api_base, ticker)
    with forecast_col:
        section("Forecast summary")
        st.markdown(f'<div class="call-lead fc-summary">'
                    f'{html_escape(note_body.get("headline") or "")}</div>',
                    unsafe_allow_html=True)
        if sotp.get("marketed", {}).get("per_share") is not None:
            _revenue_split(sotp)
    _revenue_build(v)

    list_col, bench_col = st.columns([1, 1.5], gap="medium")
    with list_col:
        section("Value by asset", basis="$ a share · click one")
        clicked = _value_book(v, ticker, selected)
    with bench_col:
        bench = st.container()
    # The picked asset's levers and layers run the full width under the pair.
    below = st.container()
    bits = list(note_body.get("body") or [])
    if coverage.get("untagged_revenue"):
        bits.append(f"{coverage['untagged_revenue'] / 1e6:,.0f}mm of "
                    f"FY{coverage['fiscal_year']} revenue has neither a product row nor "
                    f"a line and is not drawn: there is no path to draw for it.")
    if coverage.get("outside_reported_revenue"):
        names = ", ".join(s["name"] for s in coverage.get("outside_lines") or [])
        bits.append(f"{coverage['outside_reported_revenue'] / 1e6:,.0f}mm is earned "
                    f"outside the reported total ({names}), so it is valued and drawn "
                    "but is not coverage of it.")
    if any(not m.get("counted", True) for m in modelled):
        bits.append("Hatched bands run on a placeholder curve and are left out of the "
                    "per-share figure.")
    if bits:
        note(" ".join(bits))
    # The further reads, at the foot: what the price needs, the risks that move together,
    # the value a peer multiple implies, and the Medicare selections.
    _what_breaks_it(api_base, ticker)
    _pipeline_development(api_base, ticker)
    _peer_value_section(api_base, ticker)
    _ira_strip(api_base, ticker)
    return v, clicked, {"bench": bench, "below": below}


# --- the workbench ----------------------------------------------------------------
# One product: what the model says it is worth, drawn as the path that makes it and the
# bridge that turns the path into a figure, with the levers under both. Everything on
# screen traces to an assumption row with a source; the engine computes and never
# invents, and where it refuses the tab says which numbers are missing.

_MODE_WORD = {"marketed": "anchored on revenue", "franchise": "share of a franchise",
              "one_time": "one-time, patient-built", "chronic": "chronic, patient-built"}


def _short(text, limit: int = 40) -> str:
    """The first clause of a basis, cut at a word rather than mid-way through one."""
    head = (text or "").split(",")[0].strip()
    if len(head) <= limit:
        return head
    cut = head[:limit].rsplit(" ", 1)[0]
    return cut or head[:limit]


_REGION_WORD = {"INTL": "ex-US", "EU": "Europe", "JP": "Japan", "CN": "China",
                "EM": "EM", "APAC": "APAC", "ESTROW": "Est. RoW", "ROW": "RoW"}


def _identity(data: dict, result: dict) -> str:
    """The product's facts as chips: how it is built, what it is, when exclusivity ends,
    how far the model looks, and whether its curve or its erosion came from a default.
    Facts rather than figures, so they take the chip form the section basis uses."""
    chips = [f'<span class="hot">{html_escape(_MODE_WORD.get(result.get("mode"), result.get("mode") or ""))}</span>']
    if data.get("modality"):
        chips.append(f'<span>{html_escape(data["modality"])}</span>')
    regions = result.get("regions") or []
    # Where the product's sales are split by region, the US date is only the US's, and
    # each region shows its own date and how much of the product it carries.
    where = f"US {result.get('us_share', 1.0):.0%} " if regions else ""
    if result.get("loe_year"):
        chips.append(f'<span class="hot">LOE {where}{result["loe_year"]} · '
                     f'{html_escape(_short(result.get("loe_basis"), 36))}</span>')
    elif result.get("loe_in_base"):
        chips.append(f'<span class="hot">LOE {where}past · '
                     f'{html_escape(_short(result.get("loe_basis"), 36))}</span>')
    else:
        chips.append(f'<span>{"US " if regions else ""}no LOE on file</span>')
    for region in regions:
        when = ("past" if region.get("in_base") else region.get("loe_year") or "none")
        chips.append(f'<span class="hot" title="{html_escape(region.get("loe_basis") or "")}">'
                     f'{html_escape(_REGION_WORD.get(region.get("region"), region.get("region") or ""))} '
                     f'{region.get("share", 0):.0%} {when}</span>')
    years = result.get("dcf_years") or result.get("years") or []
    if years:
        chips.append(f'<span>{years[0]}–{years[-1]}</span>')
    if (result.get("curve_basis") or "").startswith("placeholder"):
        chips.append('<span class="warn">placeholder curve</span>')
    if (result.get("erosion_basis") or "").startswith("curated default"):
        chips.append('<span>erosion: curated default</span>')
    return f'<div class="fc-id">{"".join(chips)}</div>'


def _lever_controls(ticker: str, sel: int, result: dict, scalars: dict) -> dict:
    """The levers this product actually has, as sliders in one row. Returns the
    overrides to send to the what-if, keyed as that endpoint takes them.

    A patient-built forecast is moved by its volume, its price, its PoS and the rate.
    A product anchored on reported revenue has no curve and no price, and 297 of the
    323 forecasts on file are built that way, so its sliders are its growth, the rate
    it fades to, the year exclusivity ends and the drop the year after. Nothing is
    saved by moving one: the base stays as the grey line, and Reset returns to it.
    """
    mode = result.get("mode")
    key = lambda name: f"fc_wi_{name}_{ticker}_{sel}"
    base_wacc = round(result["wacc"], 4)
    base_pos = round(result["pos"], 4)
    moved: dict = {}
    keys: list[str] = []

    def wacc_slider(col):
        base = round(base_wacc * 100, 2)
        with col:
            got = st.slider("WACC", round(base - 3.0, 2), round(base + 3.0, 2), base,
                            0.25, format="%.2f%%", key=key("wacc"))
        keys.append(key("wacc"))
        if abs(got - base) > 1e-9:
            moved["wacc"] = round(got / 100.0, 6)

    if mode in ("marketed", "franchise"):
        # The what-if sends growth to the rate the mode grows from: a franchise's pool.
        growth = scalars.get("franchise_growth_pct" if mode == "franchise"
                             else "revenue_growth_pct")
        fade = scalars.get("terminal_growth_pct")
        # A loss already in the base cannot erode again, so neither slider could move it.
        loe = None if result.get("loe_in_base") else result.get("loe_year")
        year1 = result.get("erosion_year1_pct")
        cols = st.columns([1, 1, 1, 1, 1, 0.5])
        slot = 0
        if growth is not None:
            base = round(growth * 100, 1)
            with cols[slot]:
                got = st.slider("pool growth" if mode == "franchise" else "growth",
                                round(max(base - 10.0, -40.0), 1),
                                round(base + 10.0, 1), base, 0.5, format="%.1f%%",
                                key=key("growth"),
                                help=("annual growth of the franchise pool, before erosion"
                                      if mode == "franchise"
                                      else "near-term annual growth, before erosion"))
            keys.append(key("growth")); slot += 1
            if abs(got - base) > 1e-9:
                moved["growth"] = round(got / 100.0, 4)
        if mode == "marketed" and fade is not None:
            base = round(fade * 100, 1)
            with cols[slot]:
                got = st.slider("long-run growth", round(base - 4.0, 1), round(base + 4.0, 1),
                                base, 0.5, format="%.1f%%", key=key("terminal"),
                                help="the rate the near-term growth fades to")
            keys.append(key("terminal")); slot += 1
            if abs(got - base) > 1e-9:
                moved["terminal_growth"] = round(got / 100.0, 4)
        if loe:
            with cols[slot]:
                got = st.slider("LOE year", int(loe) - 6, int(loe) + 8, int(loe), 1,
                                key=key("loe"), help="the year exclusivity ends")
            keys.append(key("loe")); slot += 1
            if got != int(loe):
                moved["loe_year"] = got
        if loe and year1 is not None:
            base = round(year1 * 100, 0)
            with cols[slot]:
                got = st.slider("year-one erosion", 5.0, 95.0, float(base), 5.0,
                                format="%.0f%%", key=key("erosion"),
                                help="revenue lost in the first year after LOE")
            keys.append(key("erosion")); slot += 1
            if abs(got - base) > 1e-9:
                moved["erosion"] = round(got / 100.0, 4)
        wacc_slider(cols[slot]); slot += 1
        reset_col = cols[-1]
    else:
        cols = st.columns([1, 1, 1, 1, 0.5])
        with cols[0]:
            got = st.slider("volume", 0.4, 1.6, 1.0, 0.05, format="%.2fx",
                            key=key("volume"),
                            help=("scales the published peak, since a launch has no "
                                  "patient curve" if mode == "launch" else
                                  "scales the patient curve; the acceptance lever the "
                                  "uptake audit surfaced"))
        keys.append(key("volume"))
        if abs(got - 1.0) > 1e-9:
            moved["volume"] = got
        price = result.get("net_price")
        if price:
            with cols[1]:
                got = st.slider("net price", 50, 150, 100, 5, format="%d%%",
                                key=key("price"), help="as a share of the price on file")
            keys.append(key("price"))
            if got != 100:
                moved["price"] = round(price * got / 100.0, 6)
        with cols[2]:
            # From nil: a seamless Phase 2/3 oncology asset sits at 11% and an asset
            # whose Phase 3 failed at 0, and a floor above either throws the page.
            got = st.slider("PoS", 0.0, 1.00, base_pos, 0.025, key=key("pos"))
        keys.append(key("pos"))
        if abs(got - base_pos) > 1e-9:
            moved["pos"] = got
        wacc_slider(cols[3])
        reset_col = cols[-1]
    with reset_col:
        st.markdown('<div class="fc-reset"></div>', unsafe_allow_html=True)
        if st.button("Reset", key=f"fc_wi_reset_{ticker}_{sel}",
                     help="back to the assumptions on file"):
            for k in keys:
                st.session_state.pop(k, None)
            _rerun_here()
    return moved


def _revenue_path(name: str, result: dict, varied, base_slim, actuals: list,
                  moved: dict, scenario: str, revenue_span) -> None:
    """The path: what the product reported, running into what the model draws.

    The reported years are dots, not a line, because they are a different kind of
    number from the forecast and joining them would claim a continuity nobody modelled.
    The year exclusivity ends is a rule with the years after it shaded, so the cliff is
    read off the chart rather than off a byline. A moved lever redraws the path in the
    flag colour over the base in grey, and a moved LOE moves the rule with it.
    """
    years = result["years"]
    hist = [(a["fiscal_year"], a["value"]) for a in actuals
            if a.get("fiscal_year") is not None and a["fiscal_year"] < years[0]][-4:]
    all_years = [y for y, _ in hist] + list(years)
    labels = [str(y) for y in all_years]
    pad = [None] * len(hist)
    if varied:
        series = [{"name": "varied", "values": pad + list(varied["revenue"]),
                   "colour": TK.FLAG},
                  {"name": "base", "values": pad + list(base_slim["revenue"]),
                   "colour": TK.MUTED}]
    else:
        series = [{"name": "modelled", "values": pad + list(result["revenue_after_loe"]),
                   "colour": TK.UP}]
        if result["revenue_after_loe"] != result["revenue"]:
            series.append({"name": "pre-LOE", "values": pad + list(result["revenue"]),
                           "colour": TK.MUTED})
    points = ([{"name": "reported", "colour": TK.TEXT,
                "values": [v for _, v in hist] + [None] * len(years)}] if hist else [])
    markers, shade = [], None
    loe = (varied or {}).get("loe_year") if varied else result.get("loe_year")
    if loe in all_years:
        idx = all_years.index(loe)
        markers.append({"index": idx, "label": f"LOE {loe}",
                        "colour": TK.FLAG if "loe_year" in moved else TK.MUTED})
        shade = (idx, len(all_years) - 1)
    if varied and "loe_year" in moved and result.get("loe_year") in all_years:
        markers.append({"index": all_years.index(result["loe_year"]),
                        "label": f"base {result['loe_year']}", "colour": TK.MUTED})
    section(f"{name} revenue", basis=f"{_mm()} · {scenario}" + (" · varied" if varied else ""))
    R.show(CH.line_chart(series, labels, 780, 236, y_fmt=lambda v: f"{v:,.0f}",
                         y_span=revenue_span, markers=markers, points=points,
                         shade=shade, zero=True), css_class="chart-mount stretch")


def _value_bridge(shown: dict, verdict: dict, varied: bool) -> None:
    """How the path becomes a figure, as a bridge.

    Cash flows inside the horizon, the terminal value after it, the PoS haircut and the
    partner's share, each a bar, so the two things an analyst most needs to see about an
    rNPV are visible rather than stated: how much of it is terminal value, and how much
    the probability took off. Then the divisor, in words, because a figure per share is
    the only form in which any of this is a view.
    """
    pv, tv = shown.get("pv_fcff") or 0.0, shown.get("terminal_pv") or 0.0
    npv, rnpv = shown.get("npv") or 0.0, shown.get("rnpv") or 0.0
    pos = shown.get("pos")
    share = verdict.get("economics_share")
    steps = [{"label": "cash flows", "value": pv, "kind": "start"},
             {"label": "terminal", "value": tv, "kind": "step"},
             {"label": "NPV", "kind": "end"}]
    if pos is not None and pos < 1.0 - 1e-9:
        steps += [{"label": f"PoS {pos:.0%}", "value": rnpv - npv, "kind": "step"},
                  {"label": "rNPV", "kind": "end"}]
    if share is not None and shown.get("partner_rnpv") is not None:
        steps += [{"label": f"partner {1 - share:.0%}", "value": -shown["partner_rnpv"],
                   "kind": "step"},
                  {"label": "owner", "kind": "end"}]
    section("Where the value sits", basis=_mm() + (" · varied" if varied else ""))
    R.show(CH.waterfall(steps, 470, 236, value_fmt=lambda x: f"{x:,.0f}"),
           css_class="chart-mount stretch")
    shares = verdict.get("diluted_shares")
    owner = shown.get("owner_rnpv") if share is not None else rnpv
    bits = []
    if shares and owner is not None:
        bits.append(f"÷ {shares / 1e6:,.0f}mm diluted shares = "
                    f"${owner * 1e6 / shares:,.2f} a share")
    if npv:
        bits.append(f"terminal value is {tv / npv:.0%} of NPV")
    if bits:
        st.markdown(f'<div class="byline">{html_escape(" · ".join(bits))}</div>',
                    unsafe_allow_html=True)


def _drivers_layer(verdict: dict, scenario: str) -> None:
    """What the answer rests on, ranked, and the range where one exists.

    A tornado rather than a grid: the question an analyst is asked is not how two
    variables cross but what would have to be wrong for the number to be wrong. Each
    bar runs from the downside to the upside of one lever, and the label says how far
    it was pushed, because a date and a rate are not pushed the same way.
    """
    left, right = st.columns([1.45, 1], gap="medium")
    levers = verdict.get("levers") or []
    with left:
        if levers:
            section("What it rests on", basis=f"rNPV swing, {_mm()}")
            rows = [{"label": f"{l['lever']}, "
                              f"{'±2y' if l.get('step', '').startswith('two') else '±20%'}",
                     "low": l["down"], "high": l["up"]} for l in levers]
            R.show(CH.tornado(rows, 620, 40 + 34 * len(rows), label_width=190,
                              value_fmt=lambda x: f"{x:,.0f}"), css_class="chart-mount")
    with right:
        spread = verdict.get("spread") or {}
        base_ps = (spread.get("base") or {}).get("per_share")
        low = (spread.get("bear") or {}).get("per_share")
        high = (spread.get("bull") or {}).get("per_share")
        gate_rows = _gate_range_rows(verdict)
        if (verdict.get("has_range") and low is not None and high is not None
                and base_ps is not None):
            # The hand bear and bull first, the next gate's legs under them, derived.
            section("The range", basis="bear · base · bull")
            rows = [{"label": "bear · bull, stated" if gate_rows else "per share",
                     "low": low, "high": high}] + gate_rows
            R.show(CH.tornado(rows, 440, 86 if len(rows) == 1 else 40 + 34 * len(rows),
                              centre=base_ps,
                              value_fmt=lambda x: f"${x:,.2f}"), css_class="chart-mount")
        elif gate_rows:
            # No hand range, so the next gate sets it: nil if it fails to the success
            # value, centred on today, with the PoS band as its own narrower row.
            gate = verdict.get("gate") or {}
            section("The range", basis="next gate · "
                    + ("stated legs" if gate.get("legs_basis") == "stated" else "derived"))
            R.show(CH.tornado(gate_rows, 440, 86 if len(gate_rows) == 1
                              else 40 + 34 * len(gate_rows),
                              centre=gate.get("per_share_now") or 0.0,
                              value_fmt=lambda x: f"${x:,.2f}"), css_class="chart-mount")
        else:
            section("The range", basis="one case")
            state("No bear or bull on file",
                  "a scenario inherits the base and restates only what it changes; "
                  "nothing has been restated, so this is one set of assumptions "
                  "rather than a range. Pick bear or bull above and edit under "
                  "Assumptions to define one.")
    for paragraph in (verdict.get("note") or {}).get("body") or []:
        st.markdown(f'<div class="byline">{html_escape(paragraph)}</div>',
                    unsafe_allow_html=True)


_POS_STAGES = {"reading_out": "readout due", "positive": "NDA/BLA gate",
               "filed": "filed", "mixed": "one Phase 3 negative", "negative": "nil"}
_POS_GATES = {"p2_to_p3": "Phase 2 gate", "p3_to_nda": "Phase 3 entry",
              "nda_to_approval": "NDA/BLA gate"}


def _pos_stage(granular: dict) -> str:
    """The gate in words. An asset entering is named by the first transition still
    ahead of it, so a seamless Phase 2/3 reads as the Phase 2 gate it stands at."""
    stage = granular.get("stage") or ""
    if stage == "entering":
        chain = granular.get("chain") or []
        return _POS_GATES.get(chain[0]["gate"] if chain else "", "entry")
    return _POS_STAGES.get(stage, stage)


def _pos_caption(granular: dict | None) -> str | None:
    """The PoS tile's caption where the figure was placed at a gate: the gate and the
    band, which is what a reader wants under a probability before the source."""
    if not granular:
        return None
    stage = _pos_stage(granular)
    low, high = granular.get("low"), granular.get("high")
    if low is None or high is None or abs(high - low) < 0.005:
        return stage
    return f"{stage}, band {low * 100:.0f} to {high * 100:.0f}%"


def _pos_layer(granular: dict) -> None:
    """Where the probability was placed and what it rests on.

    The chain is the published transitions still ahead of the asset, the band is the
    same chain under every other cut the asset qualifies for, and the design of its
    largest Phase 3 is shown as fact beside the number: no free source publishes
    success rates by enrolment or masking, so nothing here multiplies them.
    """
    stage = _pos_stage(granular)
    section("Probability of success", basis=f"{stage}, {granular.get('area') or ''}")
    rows = ""
    for step in granular.get("chain") or []:
        rows += (f'<tr><td class="pol-d">{html_escape(step["gate"].replace("_", " "))}</td>'
                 f'<td class="pol-l">{step["pos"] * 100:.1f}%</td>'
                 f'<td class="pol-k">n={step["n"]:,}</td>'
                 f'<td class="pol-t">{html_escape(step.get("source") or "")}</td></tr>')
    for cut in granular.get("cuts") or []:
        rows += (f'<tr><td class="pol-d">band</td>'
                 f'<td class="pol-l">{cut["pos"] * 100:.0f}%</td>'
                 f'<td class="pol-k">{html_escape(cut.get("group") or "")}</td>'
                 f'<td class="pol-t">{html_escape(cut.get("how") or "")}</td></tr>')
    for cut in granular.get("refused") or []:
        rows += (f'<tr><td class="pol-d">not applied</td><td class="pol-l"></td>'
                 f'<td class="pol-k">{html_escape(cut.get("group") or cut.get("cut") or "")}'
                 f'</td><td class="pol-t">{html_escape(cut.get("why") or "")}</td></tr>')
    filing = granular.get("filing")
    if filing:
        verdict = ("at the approval gate" if filing.get("lifts")
                   else "not applied")
        rows += (f'<tr><td class="pol-d">filed</td>'
                 f'<td class="pol-l">{html_escape(filing.get("date") or "")}</td>'
                 f'<td class="pol-k">{html_escape(verdict)}</td>'
                 f'<td class="pol-t">{html_escape(filing.get("why") or "")}</td></tr>')
    if granular.get("stage") == "mixed":
        rows += ('<tr><td class="pol-d">band</td><td class="pol-l">0%</td>'
                 '<td class="pol-k">downside</td><td class="pol-t">if the open studies '
                 'read out the way the first did</td></tr>')
    if rows:
        st.markdown(f'<table class="pol"><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)
    design = granular.get("design") or {}
    if design.get("nct_id"):
        facts = [design["nct_id"]]
        if design.get("enrollment"):
            facts.append(f"{design['enrollment']:,} enrolled")
        for key in ("allocation", "masking"):
            if design.get(key) and design[key].lower() not in ("na", "none"):
                facts.append(f"{design[key].lower()} {key}" if key == "masking"
                             else design[key].lower())
        if design.get("status"):
            facts.append(design["status"].lower())
        if design.get("primary_completion"):
            facts.append(f"primary completion {design['primary_completion']}")
        st.markdown(f'<div class="byline">largest Phase 3 on the registry: '
                    f'{html_escape(", ".join(facts))}. Shown, not multiplied: no free '
                    f'source publishes success rates by design.</div>',
                    unsafe_allow_html=True)
    if filing and filing.get("quote"):
        st.markdown(f'<div class="byline">The filing, verbatim: '
                    f'{html_escape(filing["quote"][:400])}</div>',
                    unsafe_allow_html=True)
    st.markdown(f'<div class="byline">{html_escape(granular.get("evidence") or "")}. '
                f'Biomarker preselection is the report\'s strongest cut and is applied '
                f'only where a biomarker_selected row is recorded on the asset by hand, '
                f'never read off a title.</div>', unsafe_allow_html=True)


# --- The launch floor's flag (build 3: docs/pipeline_coverage.md, launch years) ---------
# Red where the model launches before the earliest approval the registry and the FDA
# review clock allow, amber where the seed cites a filing or a readout that is not on file.
# A part year is information, not a flag, and a clear floor carries nothing. The same
# mark on the Pipeline tab's value, a Key insights pipeline row and the Next gate block.
_LAUNCH_TONES = {"before_floor": "red", "before_floor_cited": "amber"}


def _launch_flag(launch) -> str:
    """The flag's tone, "red" or "amber", or "" where the line carries none."""
    if not isinstance(launch, dict):
        return ""
    tone = launch.get("flag") or _LAUNCH_TONES.get(launch.get("status"), "")
    return tone if tone in ("red", "amber") else ""


def _launch_flagged(markup: str, launch, tip: bool = True) -> str:
    """``markup`` underlined in the flag's tone, the floor's message as its tooltip where
    ``tip`` (a row that carries one tooltip for everything passes False), or unchanged
    where nothing is flagged."""
    tone = _launch_flag(launch)
    if not tone:
        return markup
    message = str(launch.get("message") or "") if tip else ""
    quoted = html_escape(message).replace('"', "&quot;")
    title = f' title="{quoted}"' if message else ""
    return f'<span class="u-flagged {tone}"{title}>{markup}</span>'


def _prog_value_cell(asset_id, valued: dict, held: dict, blocked: dict,
                     launch: dict = None) -> str:
    """The Pipeline tab's rightmost column: what the compound is worth a share, or why not.

    Four states, and the difference between the last two is the point. "no forecast"
    means nobody has written the assumptions. The refused row means they were written,
    the engine read them and stopped on a named gap, which is a piece of work with a next
    step attached rather than an absence. A valued figure whose launch year falls before
    the earliest approval the evidence allows is underlined, red or amber, with the
    floor's message as its tooltip; a part year is information and carries nothing.
    """
    if asset_id in valued:
        figure = _launch_flagged(T.num(valued[asset_id] or 0, 2), launch)
        return (f'<span class="prog-v" title="rNPV a share, counted in the '
                f'company total">{figure}</span>')
    if asset_id in held:
        figure = T.num(held[asset_id] or 0, 2) if held[asset_id] else "held"
        return (f'<span class="prog-v off" title="built on a placeholder curve, '
                f'so it is shown and not counted">{figure} *</span>')
    if asset_id in blocked:
        want = ", ".join(str(x) for x in blocked[asset_id][:6]) or "inputs"
        return (f'<span class="prog-v off" title="the engine stopped on: '
                f'{html_escape(want)}">needs</span>')
    return '<span class="prog-v off" title="no assumptions on file">&mdash;</span>'


# --- Catalysts: At stake (comps-valuation.md section 12) -------------------------------
# One builder per piece, so the tab's redesign can reuse them: the row, whether it takes
# the met and missed buttons, the fold, and what a resolve said. A derived row says so on
# every line it is drawn on, and only a row the back end marks resolvable gets buttons:
# a derived Phase 2 or FDA gate resolves through the registry or openFDA, never by hand.
_STAKE_SHOWN = 6
_STAKE_TITLE_CHARS = 64


def _stake_leg(pos) -> str:
    """A leg's probability as the row prints it: "nil" for none, never "0.00"."""
    if pos is None or pos != pos:
        return "·"
    return "nil" if pos < 0.005 else f"{pos:.2f}"


def _stake_resolvable(row) -> bool:
    """Met and missed are drawn only on a priced row the back end marks resolvable."""
    return (isinstance(row, dict) and row.get("priced", True) is not False
            and row.get("resolvable") is True)


def _stake_title(title, event: str = "") -> str:
    """The catalyst's title, cut to fit, without its leading phase only where the row's
    event already names that phase: a Phase 2/3 study priced as a Phase 2 gate, or a
    stated row whose event is "data readout", keeps it."""
    title = str(title or "").strip()
    phase = re.match(r"^(Phase [0-9/]+),\s*", title)
    if phase and str(event or "").startswith(f"{phase.group(1)} readout"):
        title = title[phase.end():]
    limit = _STAKE_TITLE_CHARS
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _stake_row_html(row: dict) -> str:
    """One priced catalyst: what it is and when, its swing at this company's share, and
    the legs, with a derived row tagged (the basis in the tag's tooltip). Under it in
    muted text: what the model holds after a miss, why a different study is priced, and
    why there is no button where a resolve is not taken by hand."""
    r = row if isinstance(row, dict) else {}
    derived = r.get("legs_basis") == "derived"
    tag = (f' <span class="u-tag" title="{_gate_attr(r.get("basis"))}">derived</span>'
           if derived else "")
    event = r.get("gate_label") if derived and r.get("gate_label") else r.get("catalyst_type")
    per_share = (f" · {r['per_share']:+,.2f}/sh" if r.get("per_share") is not None else "")
    lines = [f'<b>{html_escape(r.get("asset_name") or "")}</b> '
             f'{html_escape(r.get("expected_date") or "")} · {html_escape(event or "")} · '
             f'{html_escape(_stake_title(r.get("title"), event))}{tag}',
             f'swing <b>{(r.get("swing") or 0):,.0f}mm</b> · this company '
             f'{(r.get("share") or 0):.0%}: <b>{(r.get("share_swing") or 0):,.0f}mm</b>'
             f'{per_share} · PoS {_stake_leg(r.get("pos_now"))} now, '
             f'{_stake_leg(r.get("pos_success"))} met, {_stake_leg(r.get("pos_failure"))} missed']
    held = r.get("held") if isinstance(r.get("held"), dict) else {}
    notes = [held.get("note"), r.get("gate_note")]
    if not _stake_resolvable(r):
        notes.append(r.get("resolve_note") or "Not resolved by hand.")
    muted = " ".join(str(x).strip() for x in notes if x)
    if muted:
        lines.append(f'<span class="u-muted">{html_escape(muted)}</span>')
    return '<div class="byline">' + "<br>".join(lines) + "</div>"


def _stake_split(rows: list, shown: int = _STAKE_SHOWN) -> tuple:
    """The rows drawn open and the rest, folded: the largest swings first, as ranked."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    return rows[:shown], rows[shown:]


def _stake_resolved_note(result) -> str:
    """What a resolve said, where the page has to say it: a stated PoS still governs."""
    r = result if isinstance(result, dict) else {}
    if r.get("route") != "gate evidence" or not r.get("stated_pos_governs"):
        return ""
    pos = r.get("pos_applied")
    held = f" of {pos:.0%}" if isinstance(pos, (int, float)) else ""
    return (f"Recorded as gate evidence. The stated PoS{held} still governs; clear it "
            "under Assumptions to let the gate move it.")


def _stake_row(box, api_base: str, ticker: str, row: dict) -> None:
    """One At stake row in ``box``: the text, and met and missed only where the back end
    takes a resolve. Two clicks, not one: resolving steps the live PoS and writes
    history, and a stray click should never do that. The first click arms; the second,
    on the same outcome, commits."""
    info_col, act_col = box.columns([6, 1], vertical_alignment="center")
    with info_col:
        st.markdown(_stake_row_html(row), unsafe_allow_html=True)
    if not _stake_resolvable(row):
        return
    with act_col:
        armed_key = f"cat_arm_{ticker}_{row['id']}"
        armed = st.session_state.get(armed_key)
        met_col, miss_col = st.columns(2, gap="small")
        clicked = None
        with met_col:
            label = "sure?" if armed == "met" else "met"
            if st.button(label, key=f"cat_met_{ticker}_{row['id']}", width="stretch"):
                clicked = "met"
        with miss_col:
            label = "sure?" if armed == "missed" else "missed"
            if st.button(label, key=f"cat_miss_{ticker}_{row['id']}", width="stretch"):
                clicked = "missed"
        if clicked:
            if armed == clicked:
                try:
                    result = api_post_json(
                        api_base, f"/companies/{ticker}/catalysts/{row['id']}/resolve",
                        {"outcome": clicked})
                    st.session_state.pop(armed_key, None)
                    st.session_state[f"cat_resolved_{ticker}"] = result
                    api_get.clear()
                    st.rerun()
                except (urllib.error.URLError, OSError) as exc:
                    st.error(f"resolve failed: {exc}")
            else:
                st.session_state[armed_key] = clicked
                st.rerun()


# --- The next gate: builds 1 to 3 in one block -------------------------------------------
# docs/design/development-cost.md, comps-valuation.md section 12, and the launch section
# of docs/pipeline_coverage.md. One layer on an unmarketed asset: the gate and its date,
# its chance, what passing and failing are worth and what the model holds after a miss,
# what reaching it costs from published trial costs and what that nets, and the earliest
# approval from it. None of it is in the value: the legs average back to the rNPV, the
# trial cost is already paid inside the R&D ratio, and the launch floor is a flag.
_GATE_EVIDENCE = {"published": "published", "implied": "implied by the stated PoS"}
_GATE_PRICES = "2018 prices, not restated"
_GATE_FAILED = "The trial costs did not load: {error}. Reload in a minute."
_GATE_LADDER = "After later trial costs"


def _gate_attr(text) -> str:
    """A value for a double-quoted attribute."""
    return html_escape(str(text or "")).replace('"', "&quot;")


def _gate_ps(value, nil: bool = False) -> str:
    """A figure a share: "8.23", "−0.05", "nil" for a leg of nothing where ``nil``, and
    "·" where there is no figure."""
    if value is None or value != value:
        return "·"
    if nil and abs(value) < 0.005:
        return "nil"
    text = f"{abs(value):,.2f}"
    return ("−" + text) if value < 0 and round(abs(value), 2) else text


def _gate_mm(value, currency: str = "USD") -> str:
    """Millions in the payload's currency: "138mm", "2.1mm", "725mm DKK"."""
    if value is None or value != value:
        return "·"
    text = f"{value:,.1f}" if abs(value) < 10 else f"{value:,.0f}"
    return f"{text}mm" + ("" if (currency or "USD") == "USD" else f" {currency}")


def _gate_pct(p) -> str:
    """A chance as it reads: "61%", "1.9%" under ten, "0.22%" under one."""
    if p is None or p != p:
        return "·"
    pct = p * 100
    return f"{pct:.0f}%" if pct >= 9.5 else f"{pct:.1f}%" if pct >= 0.95 else f"{pct:.2f}%"


def _gate_when(gate: dict) -> str:
    """When the gate falls: "est. Jan 2028", "due since Oct 2024", "decision due 10 Oct
    2026", "no date on file"."""
    date = str((gate or {}).get("date") or "")
    if not date:
        return "no date on file"
    if (gate or {}).get("gate") == "nda_to_approval":
        return f"decision due {_ki_day(date)}"
    return (f"due since {_ki_month(date)}" if (gate or {}).get("due")
            else f"est. {_ki_month(date)}")


def _gate_programme(label: str) -> str:
    """The stage a cost to reach covers, by the gate it reaches: the Phase 3 programme for
    a Phase 3 readout, never the gate study alone."""
    phase = re.match(r"^(Phase [0-9/]+) readout", str(label or ""))
    return f"the {phase.group(1)} programme in the modelled disease" if phase else ""


def _gate_summary(verdict: dict, dev: dict = None, dev_error: str = None) -> dict:
    """What the Next gate block draws, or {} where the asset has no gate.

    The legs come from the development payload where it read, else from the verdict: its
    success leg and risked value are the rollup gate's (base case), so the cost and the
    net sit on the same figures as the legs. A refusal or a failed read keeps the legs
    and says why there is no cost; an unread cost is "no free data", never nil.

    The failure leg is nil, the model's convention, for derived legs; where success and
    failure legs are stated on file it is the stated one, which the cost view refuses, so
    it comes from the verdict."""
    v = verdict if isinstance(verdict, dict) else {}
    vg = v.get("gate") if isinstance(v.get("gate"), dict) else {}
    d = dev if isinstance(dev, dict) else {}
    dg = d.get("gate") if d.get("ok") and isinstance(d.get("gate"), dict) else {}
    if not vg and not dg:
        return {}
    g = dg or vg
    trial = g.get("trial") if isinstance(g.get("trial"), dict) else {}
    held = g.get("held") if isinstance(g.get("held"), dict) else {}
    out = {
        "gate": g.get("gate"), "label": g.get("label") or "next gate",
        "nct": trial.get("nct_id"), "when": _gate_when(g), "due": bool(g.get("due")),
        "p": g.get("p") if dg else g.get("p_gate"),
        "evidence": (g.get("p_evidence") if dg
                     else (g.get("evidence") or {}).get("p_gate")),
        "placed": g.get("placed"),
        "now": g.get("rnpv_per_share") if dg else g.get("per_share_now"),
        "success": g.get("success_leg_per_share") if dg else g.get("per_share_success"),
        "pos_success": g.get("pos_success"),
        "held": held, "legs": vg.get("basis") or g.get("legs_basis") or "",
        "stated": vg.get("legs_basis") == "stated",
        "failure": (vg.get("per_share_failure") if vg.get("legs_basis") == "stated"
                    else 0.0),
        "currency": d.get("currency") or "USD", "base_case": bool(dg),
        "launch": v.get("launch") if isinstance(v.get("launch"), dict) else {},
        "cost": None, "problem": None}
    if dev_error:
        out["problem"] = _GATE_FAILED.format(error=str(dev_error).rstrip("."))
    elif d and not d.get("ok"):
        out["problem"] = d.get("why") or "No cost is read for this asset."
    if dg:
        high = dg.get("high") if isinstance(dg.get("high"), dict) else {}
        out["cost"] = {
            "unread": bool(dg.get("unread")) or dg.get("cost_per_share") is None,
            "per_share": dg.get("cost_per_share"), "mm": dg.get("cost"),
            "net": dg.get("net_per_share"), "breakeven": dg.get("breakeven_p"),
            "funds": dg.get("funds"), "basis": dg.get("basis") or "",
            "grade": dg.get("grade"), "high": high.get("cost_per_share"),
            "high_net": high.get("net_per_share"), "high_label": high.get("label") or "",
            "paid": d.get("paid_note") or "", "tax": d.get("tax_basis") or ""}
    return out


def _gate_breakeven(s: dict) -> str:
    """The net row's note: the chance at which reaching the gate pays for itself."""
    c = s.get("cost") or {}
    be = c.get("breakeven")
    if be is None:
        return ""
    if be > 1:
        return "would not pay for itself at a certain pass"
    if c.get("funds") is False:
        return f"needs a {_gate_pct(be)} chance against the {_gate_pct(s.get('p'))} on file"
    return f"breaks even at a {_gate_pct(be)} chance"


def _gate_rows(s: dict) -> list:
    """The facts beside the picture, one row each: {k, v, note, tone, tip}. A cost that
    could not be read is "no free data"; a refused or failed one has no row, and the
    lines under the table say why."""
    if not s:
        return []
    rows = []
    evidence = _GATE_EVIDENCE.get(s.get("evidence"), s.get("evidence") or "")
    rows.append({"k": "chance", "v": _gate_pct(s.get("p")),
                 "note": (s.get("placed") or evidence
                          or ("stated legs carry no gate odds" if s.get("stated") else "")),
                 "tip": s.get("legs")})
    now = s.get("now")
    rows.append({"k": "if it passes", "v": _gate_ps(s.get("success")),
                 "note": f"a share, against {_gate_ps(now)} now" if now is not None else "a share",
                 "tip": (f"{s['pos_success']:.1%} chance of approval once it passes"
                         if s.get("pos_success") is not None and s["pos_success"] < 0.9995
                         else "")})
    if s.get("stated"):
        # The analyst's own failure leg, never the convention's nil.
        rows.append({"k": "if it fails", "v": _gate_ps(s.get("failure"), nil=True),
                     "note": "a share, the stated leg on file", "tip": s.get("legs") or ""})
    else:
        rows.append({"k": "if it fails", "v": "nil",
                     "note": "the model's convention for a failed programme", "tip": ""})
    held = s.get("held") or {}
    if held.get("open") and held.get("pos") is not None:
        n = held["open"]
        rows.append({"k": "held", "v": _gate_pct(held["pos"]),
                     "note": (f"{n} other Phase 3{'' if n == 1 else 's'} open"
                              + ("; the stated PoS governs" if held.get("stated_governs")
                                 else "")),
                     "tip": held.get("note") or ""})
    c = s.get("cost")
    if c:
        if c.get("unread"):
            rows.append({"k": "cost to reach", "v": "no free data", "tone": "none",
                         "note": "", "tip": c.get("basis")})
        else:
            rows.append({"k": "cost to reach", "v": _gate_ps(c.get("per_share")),
                         "note": f"{_gate_mm(c.get('mm'), s.get('currency'))} after tax, "
                                 f"{_GATE_PRICES}",
                         "tip": " ".join(x for x in (c.get("basis"), c.get("tax")) if x)})
            rows.append({"k": "net", "v": _gate_ps(c.get("net")),
                         "tone": "down" if c.get("funds") is False else "",
                         "note": _gate_breakeven(s),
                         "tip": "the chance times what passing is worth, less the cost "
                                "to reach it"})
            if c.get("high") is not None:
                rows.append({"k": "at DiMasi's level", "v": _gate_ps(c["high"]),
                             "tone": "muted",
                             "note": f"net {_gate_ps(c.get('high_net'))}, a high bound",
                             "tip": c.get("high_label")})
    launch = s.get("launch") or {}
    lg = launch.get("gate") if isinstance(launch.get("gate"), dict) else {}
    seed = launch.get("seed_year")
    if lg.get("decision_date"):
        rows.append({"k": "earliest approval",
                     "v": _launch_flagged(html_escape(_ki_month(lg["decision_date"])),
                                          launch),
                     "html": True,
                     "note": "from this gate" + (f"; model {seed}" if seed else ""),
                     "tip": launch.get("message") or ""})
    elif launch.get("decision_date") and _launch_flag(launch):
        rows.append({"k": "earliest approval",
                     "v": _launch_flagged(html_escape(_ki_month(launch["decision_date"])),
                                          launch),
                     "html": True,
                     "note": "from the registry" + (f"; model {seed}" if seed else ""),
                     "tip": launch.get("message") or ""})
    return rows


def _gate_table_html(rows: list) -> str:
    """The facts as a table: what, the figure, and a few words; the rest in the tooltip."""
    out = []
    for r in rows:
        value = r["v"] if r.get("html") else html_escape(r["v"])
        tone = f' {r["tone"]}' if r.get("tone") else ""
        tip = r.get("tip") or ""
        attrs = f' title="{_gate_attr(tip)}"' if tip else ""
        out.append(f'<tr{attrs}><td class="k">{html_escape(r["k"])}</td>'
                   f'<td class="v{tone}">{value}</td>'
                   f'<td class="t">{html_escape(r.get("note") or "")}</td></tr>')
    return f'<table class="u-gate"><tbody>{"".join(out)}</tbody></table>' if out else ""


def _gate_steps(s: dict) -> list:
    """The headline as a waterfall, a share: what passing is worth, less the chance it
    fails, is today's risked value; less the cost to reach the gate is the net. An unread
    cost is a hatched step with no net after it, never a nil one. Stated legs carry no
    gate odds, so they draw no picture and the table says what they are."""
    success, p = (s or {}).get("success"), (s or {}).get("p")
    if success is None or p is None:
        return []
    steps = [{"label": "if it passes", "value": success, "kind": "start",
              "tip": f"{s.get('label')} passes"},
             {"label": f"{1 - p:.0%} it fails", "value": -(1 - p) * success,
              "kind": "step", "tip": "failure is taken at nil"},
             {"label": "risked now", "kind": "end"}]
    c = s.get("cost")
    if c and c.get("unread"):
        steps.append({"label": "cost to reach", "value": None, "kind": "step",
                      "tip": c.get("basis")})
    elif c and c.get("per_share") is not None:
        steps += [{"label": "cost to reach", "value": -c["per_share"], "kind": "step",
                   "tip": f"{_GATE_PRICES}, after tax"},
                  {"label": "net", "kind": "end"}]
    return steps


def _gate_head(s: dict) -> str:
    """The section's chip: the gate, when it falls, its study, and where its legs come
    from, "derived" or "stated legs", as the range's chip says it."""
    legs = "stated legs" if s.get("stated") else "derived"
    return " · ".join(x for x in (s.get("label"), s.get("when"), s.get("nct"), legs) if x)


def _gate_lines(s: dict) -> list:
    """The sentences under the table, few and in the order a reader asks: what the cost
    covers, what is not read and why, where the money already sits, and a flag."""
    if not s:
        return []
    out = []
    c = s.get("cost") or {}
    if s.get("problem"):
        out.append(s["problem"])
    elif c.get("unread"):
        out.append(f"No free data for the cost to reach: {c.get('basis')}.")
    elif c:
        programme = _gate_programme(s.get("label"))
        out.append(f"The cost to reach is {programme}, not the gate study alone: "
                   f"{c.get('basis')}." if programme else
                   f"The cost to reach is {c.get('basis')}.")
    if c.get("paid"):
        out.append(f"{c['paid']} Trial costs are at {_GATE_PRICES}.")
    if _launch_flag(s.get("launch")):
        out.append(str((s.get("launch") or {}).get("message") or ""))
    return [x for x in out if x]


def _gate_ladder_html(dev: dict) -> str:
    """The ladder to approval after later trial costs, a share, one row a gate, and what
    today is worth once every later cost is paid. Unread values are "no free data"."""
    d = dev if isinstance(dev, dict) else {}
    lad = d.get("ladder") if isinstance(d.get("ladder"), dict) else {}
    rows = lad.get("rows") or []
    if not d.get("ok") or not rows:
        return ""

    def cell(value, nil=False):
        return ('<td class="v none">no free data</td>' if value is None
                else f'<td class="v">{_gate_ps(value, nil)}</td>')
    out = ['<table class="u-gate ladder"><thead><tr><td class="k">gate</td>'
           '<td class="k">date</td><td class="k v">chance</td>'
           '<td class="k v">cost to reach</td><td class="k v">if it passes</td>'
           '<td class="k v">net</td><td class="k v">breaks even</td></tr></thead><tbody>']
    for r in rows:
        be = r.get("breakeven_p")
        floored = " floored at nil" if r.get("floored") else ""
        out.append(f'<tr><td class="t">{html_escape(r.get("label") or "")}</td>'
                   f'<td class="t">{html_escape(_ki_month(r.get("date")) or "no date")}</td>'
                   f'<td class="v">{_gate_pct(r.get("p"))}</td>'
                   + cell(r.get("cost_per_share")) + cell(r.get("value_if_passed_per_share"))
                   + cell(r.get("net_per_share"))
                   + f'<td class="v{" none" if be is None else ""}">'
                     f'{"no free data" if be is None else _gate_pct(be)}{floored}</td></tr>')
    out.append("</tbody></table>")
    today, cost = lad.get("value_today_per_share"), lad.get("risked_cost_per_share")
    rnpv = ((d.get("gate") or {}).get("rnpv_per_share"))
    if today is not None and rnpv is not None:
        out.append(f'<div class="byline">Today, with every later trial cost paid: '
                   f'{_gate_ps(today)} a share against {_gate_ps(rnpv)} risked before cost, '
                   f'so the risked cost to approval is {_gate_ps(cost)}. Each "if it '
                   f'passes" here is net of the costs after it, so it sits below the '
                   f'success leg above.</div>')
    else:
        out.append('<div class="byline">A later stage has no free data for its cost, so '
                   'what rests on it is not read.</div>')
    return "".join(out)


def _gate_studies_html(dev: dict) -> str:
    """The studies behind each cost, the programme outside the headline as one figure,
    and the sources. Costs here are before tax and in 2018 dollars, whatever currency
    the headline is in, so each says "$": a Danish filer's cost to reach reads in kroner
    after tax above them."""
    d = dev if isinstance(dev, dict) else {}
    if not d.get("ok"):
        return ""
    out = ['<table class="u-gate studies"><thead><tr><td class="k">study</td>'
           '<td class="k">phase</td><td class="k v">enrolled</td>'
           '<td class="k v">a patient</td><td class="k v">still ahead</td>'
           '<td class="k v">cost ahead, before tax</td></tr></thead><tbody>']
    for stage in d.get("stages") or []:
        out.append(f'<tr><td class="t" colspan="6">{html_escape(stage.get("label") or "")}'
                   f'{": no free data" if stage.get("unread") else ""}</td></tr>')
        for st_ in stage.get("studies") or []:
            nct = html_escape(st_.get("nct_id") or "")
            enrolled, pp = st_.get("enrollment"), st_.get("per_patient_usd")
            share, ahead = st_.get("share_ahead"), st_.get("ahead_usd_mm")
            out.append(
                f'<tr title="{_gate_attr(st_.get("title"))}">'
                f'<td class="t"><a href="https://clinicaltrials.gov/study/{nct}" '
                f'target="_blank" rel="noopener">{nct}</a></td>'
                f'<td class="t">{html_escape(st_.get("phase") or "")}</td>'
                + ('<td class="v">·</td>' if enrolled is None
                   else f'<td class="v">{enrolled:,}</td>')
                + ('<td class="v">·</td>' if pp is None
                   else f'<td class="v">${pp / 1e3:,.0f}k</td>')
                + ('<td class="v">·</td>' if share is None
                   else f'<td class="v">{share:.0%}</td>')
                + ('<td class="v none">no free data</td>' if ahead is None
                   else f'<td class="v">${_gate_mm(ahead)}</td>') + '</tr>')
    out.append("</tbody></table>")
    o = d.get("outside") if isinstance(d.get("outside"), dict) else {}
    n = len(o.get("studies") or [])
    if n:
        left = o.get("cost_usd_mm")
        ahead = (f"${_gate_mm(left)} ahead before tax" if left else
                 "its cost already spent" if n == 1 else "their cost already spent")
        out.append(f'<div class="byline">Outside the headline: {n} other open '
                   f'{"study" if n == 1 else "studies"}, {ahead}. '
                   f'{html_escape(o.get("note") or "")}</div>')
    if d.get("sources"):
        out.append('<div class="byline">' + html_escape("; ".join(d["sources"])) + ".</div>")
    return "".join(out)


def _gate_book_rows(payload: dict) -> list:
    """The company's next gates as table rows: failing first, then by net a share, then
    the gates whose cost is not read. Each {name, asset_id, label, when, p, cost, success,
    net, breakeven, grade, tone}."""
    pay = payload if isinstance(payload, dict) else {}
    out = []
    for part, tone in (("failing", "down"), ("rows", ""), ("uncosted", "none")):
        for r in pay.get(part) or []:
            g = r.get("gate") if isinstance(r.get("gate"), dict) else {}
            out.append({"name": r.get("name") or "", "asset_id": r.get("asset_id"),
                        "label": g.get("label") or "", "when": _gate_when(g),
                        "p": g.get("p"), "cost": g.get("cost_per_share"),
                        "success": g.get("success_leg_per_share"),
                        "net": g.get("net_per_share"), "breakeven": g.get("breakeven_p"),
                        "grade": g.get("grade") or "", "tone": tone,
                        "tip": g.get("basis") or ""})
    return out


def _gate_book_html(payload: dict) -> str:
    """The Forecast tab's company view: every counted pipeline line's next gate, what
    reaching it costs and nets a share, and the reconciliation with the book's R&D."""
    rows = _gate_book_rows(payload)
    if not rows:
        return ('<div class="byline">No counted pipeline line has a gate to cost, so there '
                'is nothing to set against the R&amp;D the book charges.</div>')
    out = ['<table class="u-gate book"><thead><tr><td class="k">compound</td>'
           '<td class="k">next gate</td><td class="k">when</td><td class="k v">chance</td>'
           '<td class="k v">cost to reach</td><td class="k v">if it passes</td>'
           '<td class="k v">net</td><td class="k v">breaks even</td>'
           '<td class="k">grade</td></tr></thead><tbody>']
    for r in rows:
        tip = _gate_attr(r.get("tip"))
        unread = r["cost"] is None
        be = r.get("breakeven")
        out.append(
            f'<tr title="{tip}"><td class="t n pipeline">{html_escape(r["name"])}</td>'
            f'<td class="t">{html_escape(r["label"])}</td>'
            f'<td class="t">{html_escape(r["when"])}</td>'
            f'<td class="v">{_gate_pct(r["p"])}</td>'
            + ('<td class="v none">no free data</td>' if unread
               else f'<td class="v">{_gate_ps(r["cost"])}</td>')
            + f'<td class="v">{_gate_ps(r["success"])}</td>'
            + ('<td class="v none">·</td>' if unread
               else f'<td class="v{" down" if r["tone"] == "down" else ""}">'
                    f'{_gate_ps(r["net"])}</td>')
            + f'<td class="v">{"·" if be is None else "never" if be > 1 else _gate_pct(be)}'
              f'</td><td class="t">{html_escape(r["grade"])}</td></tr>')
    out.append("</tbody></table>")
    pay = payload if isinstance(payload, dict) else {}
    refused = [r for r in pay.get("refused") or [] if isinstance(r, dict)]
    lines = []
    sentence = (pay.get("reconciliation") or {}).get("sentence")
    if sentence:
        lines.append(sentence)
    if refused:
        why = [str(r.get("why") or r.get("reason") or "").rstrip(".") for r in refused]
        lines.append("Not read: " + "; ".join(
            f"{r.get('name')} ({w[:1].lower() + w[1:]})" for r, w in zip(refused, why))
            + ".")
    lines.append(f"A share, after tax at the company's share of each programme, at "
                 f"{_GATE_PRICES}. What passing is worth is derived from published "
                 f"transition rates and a failure is nil; a view beside the value, never "
                 f"in it.")
    out += [f'<div class="byline">{html_escape(x)}</div>' for x in lines]
    return "".join(out)


def _gate_range_rows(verdict: dict) -> list:
    """The Drivers range's gate rows: nil if the gate fails to its success value, and the
    PoS band beneath where one is on file, so outcome and estimate are never one bar.
    Below a hand bear and bull, labelled as derived."""
    v = verdict if isinstance(verdict, dict) else {}
    g = v.get("gate") if isinstance(v.get("gate"), dict) else {}
    if not v.get("gate_range") or g.get("per_share_success") is None:
        return []
    tag = "stated legs" if g.get("legs_basis") == "stated" else "derived"
    rows = [{"label": f"{g.get('label') or 'next gate'}, {tag}",
             "low": g.get("per_share_failure") or 0.0, "high": g["per_share_success"]}]
    band = g.get("band") if isinstance(g.get("band"), dict) else {}
    if band.get("per_share_low") is not None and band.get("per_share_high") is not None:
        rows.append({"label": "PoS band", "low": band["per_share_low"],
                     "high": band["per_share_high"]})
    return rows


def _next_gate_layer(verdict: dict, dev, dev_error, scenario: str) -> None:
    """The Next gate block: the headline as a picture first, the facts beside it, then
    the ladder after later trial costs and the studies behind the cost on demand."""
    s = _gate_summary(verdict, dev, dev_error)
    if not s:
        return
    base = " · base case" if scenario != "base" and s.get("base_case") else ""
    section("Next gate", basis=_gate_head(s) + base)
    steps = _gate_steps(s)
    if steps:
        picture, facts = st.columns([1.1, 1], gap="medium")
        with picture:
            R.show(CH.waterfall(steps, 470, 220, value_fmt=lambda x: f"{x:,.2f}"),
                   css_class="chart-mount stretch")
    else:
        facts = st.container()
    with facts:
        st.markdown(_gate_table_html(_gate_rows(s)), unsafe_allow_html=True)
    for line in _gate_lines(s):
        st.markdown(f'<div class="byline">{html_escape(line)}</div>',
                    unsafe_allow_html=True)
    ladder = _gate_ladder_html(dev)
    if ladder:
        with st.expander(_GATE_LADDER, expanded=False):
            st.markdown(ladder, unsafe_allow_html=True)
    studies = _gate_studies_html(dev)
    if studies:
        with st.expander("Trials and sources", expanded=False):
            st.markdown(studies, unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def _export_blob(url: str) -> bytes | None:
    """The xlsx, fetched once a minute rather than on every rerun of the page."""
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError):
        return None


def _curve_shaper(api_base: str, ticker: str, asset_id: int, scenario: str,
                  missing: list) -> bool:
    """The two numbers no source settles, given something to be judged against.

    Steepness comes out of a launch's early growth and incidence out of a cohort study,
    but a ceiling cannot be read off a curve that has not reached one, and the midpoint is
    coupled to the ceiling. So the hardest judgement in the model was the one made with
    the least feedback: a blocked asset drew nothing at all.

    Here the two are handles. The engine runs on every move, against the same assumptions
    as the real forecast, and nothing is written until the numbers are committed. Returns
    True when it drew, so the caller knows the dead end has been replaced.
    """
    # The test is not what the error message says. build() reports one generic line when
    # no indication has a series, and names the individual pool inputs in its notes, which
    # do not survive the exception. So ask the question directly: does supplying these two
    # make it compute? If it does, they are what is missing.
    probe_peak, probe_mid = 0.05, 4
    try:
        probe = api_get(
            api_base,
            f"/companies/{ticker}/forecast/{asset_id}/shape"
            f"?scenario={scenario}&peak={probe_peak}&midpoint={probe_mid}")
    except (urllib.error.URLError, OSError):
        return False
    if not probe.get("ok"):
        return False

    section("Shape the uptake curve",
            basis="nothing is saved until you commit it")
    note("Every other input is on file and sourced. These two are the analyst's: the "
         "ceiling cannot be read off a curve that has not reached one, and the midpoint "
         "moves with it. Set them here and watch what they do.")

    left, right = st.columns([1, 1.6])
    with left:
        # In percent, because that is how the number is spoken. The engine wants a
        # fraction, and formatting a fraction with %% printed 0.05 as "0.1%".
        peak_pct = st.slider("peak penetration, %", 0.5, 30.0, 5.0, 0.5,
                             format="%.1f%%", key=f"shape_peak_{ticker}_{asset_id}",
                             help="share of the eligible pool treated at the plateau")
        peak = peak_pct / 100.0
        midpoint = st.slider("years to half of peak", 1, 12, 4, 1,
                             key=f"shape_mid_{ticker}_{asset_id}",
                             help="how long the ramp takes to get halfway there")
    try:
        shaped = api_get(
            api_base,
            f"/companies/{ticker}/forecast/{asset_id}/shape"
            f"?scenario={scenario}&peak={peak}&midpoint={midpoint}")
    except (urllib.error.URLError, OSError) as exc:
        st.error(f"preview failed: {exc}")
        return True

    if not shaped.get("ok"):
        with right:
            state("Still short of something else",
                  "missing: " + ", ".join(shaped.get("missing") or []))
        return True

    years = [str(y) for y in shaped["years"]]
    revenue = shaped["revenue"]
    treated = (shaped.get("patients") or {}).get("treated") or []
    starts = (shaped.get("patients") or {}).get("total") or []
    with right:
        R.show(CH.line_chart(
            [{"name": "revenue", "values": revenue, "colour": TK.UP}],
            years, 560, 200, y_fmt=lambda v: f"{v:,.0f}"), css_class="chart-mount")
        peak_year = shaped["years"][revenue.index(max(revenue))] if revenue else None
        st.markdown(metric_tiles([
            ("rNPV", T.num(shaped["rnpv"]), _mm(), None, "", "risk-adjusted"),
            ("peak revenue", T.num(max(revenue) if revenue else None), _mm(), None, "",
             f"in {peak_year}" if peak_year else ""),
            ("peak treated", T.num(max(treated) if treated else None), "patients",
             None, "", "on therapy at the top"),
            ("peak starts", T.num(max(starts) if starts else None), "patients",
             None, "", "in a single year"),
        ], one_row=True), unsafe_allow_html=True)

    pooled = shaped.get("pooled") or []
    if pooled and st.button(f"Commit {peak:.1%} and {midpoint} years",
                            key=f"shape_save_{ticker}_{asset_id}",
                            help="writes both against "
                                 + ", ".join(p["name"] for p in pooled)):
        rows = []
        for entry in pooled:
            rows.append({"key": "penetration_peak_pct", "indication_id": entry["id"],
                         "value": peak, "unit": "share of the eligible pool",
                         "source": "analyst judgement, set in the curve shaper",
                         "note": "the ceiling no launch curve can yet show"})
            rows.append({"key": "ramp_midpoint_year", "indication_id": entry["id"],
                         "value": float(midpoint), "unit": "years from the start",
                         "source": "analyst judgement, set in the curve shaper",
                         "note": "years to half the ceiling above"})
        try:
            api_post_json(api_base,
                          f"/companies/{ticker}/forecast/{asset_id}/assumptions",
                          {"rows": rows, "scenario": scenario})
        except (urllib.error.URLError, OSError) as exc:
            st.error(f"save failed: {exc}")
            return True
        api_get.clear()
        st.rerun()
    return True



def _forecast_editor(api_base: str, ticker: str, asset_id: int, scenario: str,
                     rows: list[dict]):
    """The assumptions grid: every number the forecast rests on, editable in place.

    Each row carries its source, and a row without one is the analyst's own risk: it is
    listed above the grid rather than silently equal to a sourced line. Removing a row
    deletes it; the save round-trips through the API and the forecast reflows.
    """
    frame = pd.DataFrame([{
        "indication": row.get("indication") or "",
        "key": row["key"], "year": row.get("year"),
        "value": row.get("value"), "text": row.get("text_value") or "",
        "unit": row.get("unit") or "", "source": row.get("source") or "",
        "note": row.get("note") or "",
        # Read off the source by the rules until an analyst confirms it, and said so.
        "evidence": (row.get("evidence") or "ungraded")
                    + ("" if row.get("evidence_reviewed") else " · auto"),
        "_indication_id": row.get("indication_id"),
    } for row in rows]) if rows else pd.DataFrame(
        columns=["indication", "key", "year", "value", "text", "unit", "source",
                 "note", "evidence", "_indication_id"])
    known = {row.get("indication") or "": row.get("indication_id") for row in rows}
    edited = st.data_editor(
        frame, num_rows="dynamic", hide_index=True, width="stretch", height=420,
        key=f"fc_editor_{ticker}_{asset_id}_{scenario}",
        column_config={
            "_indication_id": None,
            "indication": st.column_config.TextColumn(
                "indication", help="blank for an asset-level number"),
            "value": st.column_config.NumberColumn("value", format="%g"),
            "evidence": st.column_config.TextColumn(
                "evidence", disabled=True,
                help="filed, measured, published, analogue, convention or judgement; "
                     "auto until reviewed"),
        })
    if not st.button("Save assumptions", key=f"fc_save_{ticker}_{asset_id}_{scenario}"):
        return
    payload = []
    kept = set()
    for _, row in edited.iterrows():
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        indication_id = row.get("_indication_id")
        if pd.isna(indication_id):
            indication_id = known.get(str(row.get("indication") or "").strip())
        year = None if pd.isna(row.get("year")) else int(row["year"])
        value = None if pd.isna(row.get("value")) else float(row["value"])
        text = str(row.get("text") or "").strip() or None
        kept.add((indication_id, key, year))
        payload.append({
            "key": key, "indication_id": indication_id, "scenario": scenario,
            "year": year, "value": value, "text_value": text,
            "unit": str(row.get("unit") or "").strip() or None,
            "source": str(row.get("source") or "").strip() or None,
            "note": str(row.get("note") or "").strip() or None,
        })
    # A row removed from the grid is a deletion, sent as an empty value.
    for row in rows:
        identity = (row.get("indication_id"), row["key"], row.get("year"))
        if identity not in kept and row.get("scenario", scenario) == scenario:
            payload.append({"key": row["key"], "indication_id": row.get("indication_id"),
                            "scenario": scenario, "year": row.get("year"),
                            "value": None, "text_value": None})
    try:
        api_post_json(api_base,
                      f"/companies/{ticker}/forecast/{asset_id}/assumptions",
                      {"rows": payload, "scenario": scenario})
    except (urllib.error.URLError, OSError) as exc:
        st.error(f"save failed: {exc}")
        return
    api_get.clear()
    st.rerun()


def _forecast_import(api_base: str, ticker: str, asset_id: int, scenario: str,
                     rows: list[dict]):
    """The Excel round trip's return leg: the exported sheet, vetted, comes back in.

    Parsed client side and posted as rows, so the API needs no upload plumbing. An
    indication is matched by name against the rows already on file; a name the asset
    does not carry is reported, not guessed at.
    """
    uploaded = st.file_uploader("Import assumptions (CSV, the exported sheet's columns)",
                                type=["csv"], key=f"fc_up_{ticker}_{asset_id}")
    if uploaded is None:
        return
    import csv as _csv
    import io as _io
    known = {(row.get("indication") or "").strip().lower(): row.get("indication_id")
             for row in rows}
    known[""] = None
    reader = _csv.DictReader(
        line for line in _io.TextIOWrapper(uploaded, encoding="utf-8")
        if not line.lstrip().startswith("#"))
    payload, unknown = [], set()
    for row in reader:
        name = (row.get("indication") or "").strip().lower()
        if name not in known:
            unknown.add(row["indication"])
            continue
        payload.append({
            "key": (row.get("key") or "").strip(),
            "indication_id": known[name],
            "scenario": (row.get("scenario") or scenario).strip() or scenario,
            "year": int(row["year"]) if (row.get("year") or "").strip() else None,
            "value": float(row["value"]) if (row.get("value") or "").strip() else None,
            "text_value": (row.get("text_value") or "").strip() or None,
            "unit": (row.get("unit") or "").strip() or None,
            "source": (row.get("source") or "").strip() or None,
            "note": (row.get("note") or "").strip() or None,
        })
    if unknown:
        st.warning("skipped rows for indications not on this asset: "
                   + ", ".join(sorted(unknown)))
    if payload and st.button("Apply imported rows",
                             key=f"fc_apply_{ticker}_{asset_id}"):
        api_post_json(api_base,
                      f"/companies/{ticker}/forecast/{asset_id}/assumptions",
                      {"rows": payload, "scenario": scenario})
        api_get.clear()
        st.rerun()


def _render_patient_chart(result, years, x_labels, volume_scale, patients_span):
    """The patient curve, for the modes that have one.

    Lifted out of the tab so the revenue-anchored modes can skip it wholesale. Every
    series here multiplies a patient count, and marketed and franchise mode report those
    as nulls, so there is nothing to scale and nothing to draw.
    """
    section("New patients", basis="per year"
        + (f" · {volume_scale:.2f}x" if volume_scale != 1.0 else ""))
    by_ind = result["patients"]["by_indication"]
    explicit_all = [ind["explicit"] for ind in by_ind.values()
                    if ind.get("explicit")]
    derived_all = [ind["derived"] for ind in by_ind.values()
                   if ind.get("derived")]
    patient_series = [{"name": "entered" if explicit_all else "used",
                       "values": [v * volume_scale
                                  for v in result["patients"]["total"]],
                       "colour": TK.UP}]
    if derived_all:
        derived_total = [sum(series[i] for series in derived_all) * volume_scale
                         for i in range(len(years))]
        patient_series.append({"name": "derived", "values": derived_total,
                               "colour": TK.FLAG})
    # The stock still on therapy, which is the line revenue actually meets. For a
    # one-time therapy it sits exactly on the starts and is left off rather than
    # drawn twice; for a chronic one it is the larger number and the whole point.
    treated = result["patients"].get("treated") or []
    if treated and treated != result["patients"]["total"]:
        patient_series.append({"name": "on therapy",
                               "values": [v * volume_scale for v in treated],
                               "colour": TK.DOWN})
    R.show(CH.line_chart(patient_series, x_labels, 620, 220,
                         y_fmt=lambda v: f"{v:,.0f}", y_span=patients_span, zero=True),
           css_class="chart-mount")
    if treated and treated != result["patients"]["total"]:
        note("two lines, two quantities. Starts are who begins in a year; on therapy "
             "is who is still taking it, carried forward at the persistence rate and "
             "the series the annual price is charged against. The gap between them "
             "is the whole economics of a chronic drug.")
    else:
        note("the pool identity derives the curve from prevalence, incidence and "
             "penetration: the hump is arithmetic, the tail is the incidence run "
             "rate, and it can be argued against the hand series above it")


def _pnl_section(result: dict, varied) -> None:
    """The P&L that produces the FCFF, which the engine computed and nothing showed.

    Revenue, COGS, SG&A, R&D, EBIT, tax and FCFF by year, with the margins beside them,
    because a valuation nobody can trace to a margin is a number rather than a view.
    The allocation is said aloud: every asset is charged the company's own ratios on its
    own revenue. That nets out across a fully covered company and is wrong per asset, a
    marketed product does not spend a third of its sales on R&D, so the ratios are
    editable per asset below and the default is named as a default here.
    """
    rows = (varied or {}).get("pnl") if isinstance(varied, dict) else None
    rows = rows or result.get("pnl") or []
    years = result.get("years") or []
    if not rows or not years:
        return
    section("P&L", basis=f"mm {_BOOK_UNIT['currency']}" + (" · varied" if varied else "")
            + " · company ratios applied to this revenue")
    last = rows[-1]
    first = rows[0]
    st.markdown(metric_tiles([
        ("FCFF margin, year one", T.pct(first["fcff"] / first["revenue"] * 100, 1)
         if first.get("revenue") else "—", "", None, "", f"{years[0]}"),
        ("FCFF margin, final year", T.pct(last["fcff"] / last["revenue"] * 100, 1)
         if last.get("revenue") else "—", "", None, "", f"{years[-1]}"),
        ("R&D charged", T.pct(first["rd"] / first["revenue"] * 100, 1)
         if first.get("revenue") else "—", "", None, "",
         "the company ratio, on this product's revenue"),
        ("cumulative FCFF", T.num(sum(r["fcff"] for r in rows)), _mm(), None, "",
         "undiscounted, before PoS"),
    ], one_row=True), unsafe_allow_html=True)
    table = pd.DataFrame([{
        "year": y, "revenue": r["revenue"], "COGS": -r["cogs"], "SG&A": -r["sga"],
        "R&D": -r["rd"], "other": -r.get("other", 0.0), "EBIT": r["ebit"],
        "tax": -r["tax"], "FCFF": r["fcff"],
        "FCFF margin": (r["fcff"] / r["revenue"]) if r["revenue"] else None,
    } for y, r in zip(years, rows)])
    st.dataframe(
        table.style.format({c: "{:,.0f}" for c in
                            ("revenue", "COGS", "SG&A", "R&D", "other", "EBIT", "tax",
                             "FCFF")}
                           | {"FCFF margin": "{:.1%}"}),
        width="stretch", hide_index=True, height=min(60 + 36 * len(rows), 420))
    note("COGS, SG&A, R&D and tax are the company's FY ratios from the 10-K, applied to "
         "this product's revenue. Across a company the model covers in full they sum to "
         "the company's own P&L; on any one product they are an allocation, not a cost.")


def _share_shaper(api_base: str, ticker: str, asset_id: int, scenario: str,
                  result: dict) -> None:
    """The one judgement in a franchise: where the share settles.

    Every other number on a franchise member is read off a filing. The pool is reported,
    its growth comes out of guidance, the current share is arithmetic on two figures in
    the same table, and the ramp is the rate that carries one to the other. What nobody
    can source is the end state, so that is the handle, and it is the only one.

    Moving it leaves the first forecast year alone, because that year is guided and half
    reported already. The ramp re-solves around it instead.
    """
    franchise = result.get("franchise")
    if not franchise:
        return
    section("Where the share settles",
            basis="nothing is saved until you commit it")
    note("The pool, its growth and today's share are all read off the filings. This is "
         "the number that is not: the share this product holds once the switch is done. "
         "The first year does not move with it, because guidance already sets that.")

    left, right = st.columns([1, 1.6])
    with left:
        plateau_pct = st.slider(
            "settling share of the franchise, %", 20.0, 99.0, 90.0, 1.0,
            format="%.0f%%", key=f"share_plateau_{ticker}_{asset_id}",
            help="what this product holds once the switch has run its course")
    try:
        shaped = api_get(
            api_base,
            f"/companies/{ticker}/forecast/{asset_id}/shape"
            f"?scenario={scenario}&plateau={plateau_pct / 100.0}")
    except (urllib.error.URLError, OSError) as exc:
        st.error(f"preview failed: {exc}")
        return
    if not shaped.get("ok"):
        with right:
            state("Out of reach", "; ".join(shaped.get("missing") or []))
        return

    years = [str(y) for y in shaped["years"]]
    share = (shaped.get("franchise") or {}).get("share") or []
    base_share = franchise.get("share") or []
    with right:
        R.show(CH.line_chart(
            [{"name": "share", "values": [s * 100 for s in share], "colour": TK.UP},
             {"name": "as seeded", "values": [s * 100 for s in base_share],
              "colour": TK.MUTED}],
            years, 560, 200, y_fmt=lambda v: f"{v:,.0f}%"), css_class="chart-mount")
        peak = max(shaped["revenue"]) if shaped["revenue"] else None
        st.markdown(metric_tiles([
            ("rNPV", T.num(shaped["rnpv"]), _mm(), None, "", "risk-adjusted"),
            ("share by " + years[-1], T.num(share[-1] * 100 if share else None), "%",
             None, "", f"against a {plateau_pct:.0f}% plateau"),
            ("peak revenue", T.num(peak), _mm(), None, "",
             f"in {shaped['years'][shaped['revenue'].index(peak)]}" if peak else ""),
            ("first year", T.num(shaped["revenue"][0] if shaped["revenue"] else None),
             _mm(), None, "", "guided, so it does not move"),
        ], one_row=True), unsafe_allow_html=True)


# --- Medicare: the growth split (docs/design/medicare-demand-split.md) -----------------
# Pure builders over the /forecast/{id}/demand and /demand/split payloads, tested by
# extraction like the Key insights builders. Medicare only, never the US market: each
# view carries the label the API sends, and a figure the payload lacks is a dash.
# A figure the payload lacks: a dot, as the forecast levers show one.
_MC_NONE = "·"


def _mc_pct(x, decimals: int = 1) -> str:
    """A growth fraction as a signed percent with a true minus; missing is a dot,
    never a zero."""
    if x is None:
        return _MC_NONE
    v = x * 100
    if round(v, decimals) == 0:
        return f"{0:.{decimals}f}%"
    return ("+" if v > 0 else "−") + f"{abs(v):.{decimals}f}%"


def _mc_pts(x) -> str:
    if x is None:
        return _MC_NONE
    v = x * 100
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.1f}"


def _mc_cell(value, median=None, sub: str = "") -> str:
    """One figure, with the tracked median for the same years under it."""
    extra = []
    if median is not None:
        extra.append(f"median {_mc_pct(median)}")
    if sub:
        extra.append(sub)
    under = (f'<span class="mc-sub">{html_escape(" · ".join(extra))}</span>'
             if extra else "")
    return f'<td class="n">{_mc_pct(value)}{under}</td>'


def _mc_footnotes(steps) -> dict:
    """{(code, words): n}, numbered in the order the table meets them."""
    out: dict = {}
    for st in steps:
        for f in st.get("flags") or []:
            key = (f.get("code"), f.get("words"))
            if key not in out:
                out[key] = len(out) + 1
    return out


def _mc_table(part, model, notes) -> str:
    """One row per year pair for one Medicare part: the split, the tracked median of
    each factor, then reported growth for the same fiscal year and the gap."""
    labels = part.get("factor_labels") or {}
    head = ["Years", "Spend", labels.get("patients", "Patients"),
            labels.get("intensity", "Use per patient"), labels.get("price", "Cost per claim"),
            labels.get("price_per_unit", "Cost per unit"), "US reported", "Worldwide",
            "Gap, pts"]
    rows = []
    for st in part.get("steps") or []:
        base = st.get("baseline") or {}
        marks = "".join(
            f'<sup>{notes[(f.get("code"), f.get("words"))]}</sup>'
            for f in st.get("flags") or [] if (f.get("code"), f.get("words")) in notes)
        years = (str(st["to"]) if (st.get("to") or 0) - (st.get("from") or 0) == 1
                 else f'{st.get("from")} to {st.get("to")}')
        cells = [f'<td>{html_escape(years)}{marks}</td>', _mc_cell(st.get("spend"),
                                                                     base.get("spend"))]
        if st.get("patients") is None and st.get("claims") is not None:
            # CMS gave no patient count: claims and price are the split.
            cells.append(_mc_cell(st.get("claims"), base.get("claims"),
                                  f'{labels.get("claims", "claims").lower()}, '
                                  "no patient count"))
            cells.append('<td class="n m">·</td>')
        else:
            cells.append(_mc_cell(st.get("patients"), base.get("patients")))
            cells.append(_mc_cell(st.get("intensity"), base.get("intensity")))
        cells.append(_mc_cell(st.get("price"), base.get("price")))
        cells.append(_mc_cell(st.get("price_per_unit"), base.get("price_per_unit")))
        cells.append(_mc_cell(st.get("us_growth"), None, st.get("us_note") or ""))
        cells.append(_mc_cell(st.get("global_growth"), None, st.get("global_note") or ""))
        cells.append(f'<td class="n">{_mc_pts(st.get("gap_pts"))}</td>')
        cls = ' class="nlfl"' if st.get("like_for_like") is False else ""
        rows.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
    sp = part.get("span")
    if sp:
        rows.append(
            '<tr class="grp"><td>'
            f'{sp["from"]} to {sp["to"]}, a year</td>'
            + _mc_cell(sp.get("spend")) + _mc_cell(sp.get("patients"))
            + _mc_cell(sp.get("intensity")) + _mc_cell(sp.get("price"))
            + _mc_cell(sp.get("price_per_unit"))
            + '<td class="n m">·</td><td class="n m">·</td><td class="n m">·</td></tr>')
    if model and model.get("value") is not None:
        what = ("growth" if model.get("key") == "revenue_growth_pct"
                else "franchise pool growth")
        fade = ""
        if model.get("fade_to") is not None and model.get("fade_years"):
            n = model["fade_years"]
            fade = (f" fading to {_mc_pct(model['fade_to'])} over "
                    f"{int(n) if float(n).is_integer() else n} years")
        rows.append(
            f'<tr class="grp mc-model"><td colspan="{len(head)}">Model from '
            f'FY{model.get("from_fy") or "?"}: {html_escape(what)} '
            f'{_mc_pct(model["value"])} a year{html_escape(fade)}</td></tr>')
    return ('<div class="land-wrap"><table class="land sc-table mc-table"><thead><tr>'
            + "".join(f"<th>{html_escape(h)}</th>" for h in head)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _mc_chart(part: dict, width: int = 760, height: int = 240) -> str:
    base = [{**s["baseline"], "from": s.get("from"), "to": s.get("to")}
            for s in part.get("steps") or [] if s.get("baseline")]
    return CH.growth_split(part.get("steps") or [], width, height, baseline=base,
                           factor_labels=part.get("factor_labels"))


def _medicare_layer_html(split: dict) -> str:
    """The Forecast tab's Medicare layer for one asset: the label, the sentence, the
    split drawn for the main part (a second, smaller chart only when two parts are
    material), the table by year pair with the model's row last, the flags as
    numbered notes, and which record holds the brand. Empty when there is no series."""
    if not split or not split.get("ok"):
        return ""
    parts = [p for p in split.get("parts") or [] if p.get("steps")]
    material = [p for p in parts if p.get("material")]
    if not material:
        return ""
    model = (split.get("beside") or {}).get("model_growth")
    out = ['<div class="mc">',
           f'<div class="byline mc-label">{html_escape(split.get("label") or "")}</div>']
    if split.get("sentence"):
        out.append(f'<p class="mc-sentence">{html_escape(split["sentence"])}</p>')
    # The flag reads the main part's latest step, as the sentence does: patients, or
    # claims where CMS gives no patient count or changed the containers, named by part
    # when there are two.
    two_parts = len(split.get("parts") or []) > 1
    if (split.get("beside") or {}).get("direction_disagrees"):
        last = material[0]["steps"][-1]
        what = ("patients" if last.get("patients") is not None
                and last.get("like_for_like") is not False else
                ((material[0].get("factor_labels") or {}).get("claims") or "claims").lower())
        scope = f'Medicare Part {material[0].get("part")}' if two_parts else "Medicare"
        out.append(f'<div class="mc-flag">The model and {html_escape(scope)} '
                   f'{html_escape(what)} point opposite ways. A flag only: nothing in the '
                   "model moves.</div>")
    notes = _mc_footnotes([s for p in material for s in p["steps"]])
    for i, part in enumerate(material):
        title = f'{part.get("part_label") or part.get("part")}'
        share = part.get("spend_share")
        if share is not None and len(parts) > 1:
            title += f", {share * 100:.0f}% of the brand's Medicare spend"
        out.append(f'<div class="subhead">{html_escape(title)}'
                   f'<span>{html_escape(part.get("source_file") or "")}</span></div>')
        svg = _mc_chart(part, 760 if i == 0 else 520, 240 if i == 0 else 180)
        if svg:
            out.append(f'<div class="chart-mount">{svg}</div>')
        out.append(_mc_table(part, model if i == 0 else None, notes))
    for part in parts:
        if not part.get("material"):
            last = part["steps"][-1]
            out.append(
                f'<div class="byline">{html_escape(part.get("part_label") or "")}: '
                f'{_mc_pct(part.get("spend_share"), 1).lstrip("+")} of the brand\'s '
                f'Medicare spend, {_mc_pct(last.get("spend"))} in {last.get("to")}, '
                "reported, not split.</div>")
    if split.get("brand_total"):
        bt = split["brand_total"][-1]
        pts = bt.get("points") or {}
        # One name for both parts: a Part D fill and a Part B claim are not the same
        # thing, so the total takes neither part's word for use or price.
        labels = {"patients": "patients", "intensity": "use per patient",
                  "price": "price", "claims": "claims", "unsplit": "not split"}
        bits = ", ".join(f'{html_escape(labels.get(k, k))} {_mc_pts(v)}'
                         for k, v in pts.items())
        out.append(f'<div class="byline">Both parts, {bt["to"]}: spend '
                   f'{_mc_pct(bt.get("spend"))}, in points {bits}. Patients are not '
                   "added across parts, since one patient can be in both.</div>")
    out.append(f'<div class="byline">{html_escape(split.get("patients_note") or "")} '
               "Gap: US reported growth less the brand's Medicare spend growth"
               f'{", all parts" if two_parts else ""}, '
               f'{html_escape(split.get("gap_label") or "")}; shown in dollars only.</div>')
    if notes:
        out.append('<ol class="mc-notes">' + "".join(
            f"<li>{html_escape(words or code)}</li>"
            for (code, words), _n in sorted(notes.items(), key=lambda kv: kv[1]))
            + "</ol>")
    held = split.get("held_on")
    if held:
        out.append('<div class="byline">Medicare reports the brand, held on '
                   f'{html_escape(held.get("ticker") or "another")}\'s record.</div>')
    if split.get("shared_with"):
        out.append('<div class="byline">The brand is also modelled by '
                   f'{html_escape(", ".join(split["shared_with"]))}; Medicare cannot say '
                   "which company books the US sales.</div>")
    out.append("</div>")
    return "".join(out)


def _medicare_book_html(split: dict, top: int = 15) -> str:
    """The Portfolio's Medicare demand layer: one row per brand and part, by latest
    spend, the first fifteen shown and the rest folded, with the tracked median last."""
    if not split or not split.get("brands"):
        return ""
    labels_d = (split.get("factor_labels") or {}).get("D") or {}
    year = split.get("latest_year")
    # Dollar signs as an entity: Streamlit's markdown reads two of them as maths.
    head = ["Brand", "Part", f"{year} Medicare spend, &#36;bn", "Spend", "Patients",
            "Use per patient", "Price", "Model growth", f"US reported FY{year}"]

    def row(r):
        part = r.get("part") or ""
        spend_bn = (f'{r["spending"] / 1e9:,.2f}' if r.get("spending") is not None
                    else _MC_NONE)
        brand = html_escape(r.get("brand") or "")
        if r.get("held_on"):
            brand += (f' <span class="mc-sub">held on '
                      f'{html_escape(r["held_on"].get("ticker") or "")}</span>')
        cells = [f"<td>{brand}</td>", f'<td class="m">{html_escape(part)}</td>',
                 f'<td class="n">{spend_bn}</td>', _mc_cell(r.get("spend"))]
        if not r.get("material"):
            cells.append('<td class="m" colspan="5">under 5% of the brand\'s Medicare '
                         "spend, not split</td>")
            return '<tr class="mc-minor">' + "".join(cells) + "</tr>"
        if r.get("patients") is None and r.get("claims") is not None:
            cells.append(_mc_cell(r.get("claims"), None, "claims, no patient count"))
            cells.append('<td class="n m">·</td>')
        else:
            # A container change makes the patient count not like for like, as the
            # Forecast layer hatches it.
            cells.append(_mc_cell(r.get("patients"), None,
                                  "not like for like" if r.get("like_for_like") is False
                                  else ""))
            cells.append(_mc_cell(r.get("intensity")))
        cells.append(_mc_cell(r.get("price")))
        mark = (' <span class="mc-dis" title="the model and Medicare patients point '
                'opposite ways">opposite</span>' if r.get("direction_disagrees") else "")
        cells.append(f'<td class="n">{_mc_pct(r.get("model_growth"))}{mark}</td>')
        cells.append(_mc_cell(r.get("us_growth"), None, r.get("us_note") or ""))
        return "<tr>" + "".join(cells) + "</tr>"

    brands = split["brands"]
    def table(rows):
        return ('<div class="land-wrap"><table class="land sc-table mc-table"><thead><tr>'
                + "".join(f"<th>{h}</th>" for h in head)
                + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")

    out = ['<div class="mc">',
           f'<div class="byline mc-label">{html_escape(split.get("label") or "")} '
           f'Use per patient is fills per patient in Part D and claims per patient in '
           "Part B; price is cost per fill or per claim.</div>",
           table([row(r) for r in brands[:top]])]
    if len(brands) > top:
        out.append(f'<details class="mc-more"><summary>{len(brands) - top} more</summary>'
                   + table([row(r) for r in brands[top:]]) + "</details>")
    for part in ("D", "B"):
        med = (split.get("baseline") or {}).get(part)
        if not med:
            continue
        labels = (split.get("factor_labels") or {}).get(part) or labels_d
        floor = med.get("min_spend") or 50e6
        out.append(
            f'<div class="byline">Tracked Part {part} median {med.get("to")}: patients '
            f'{_mc_pct(med.get("patients"))}, {labels.get("intensity", "use").lower()} '
            f'{_mc_pct(med.get("intensity"))}, {labels.get("price", "price").lower()} '
            f'{_mc_pct(med.get("price"))}, {med.get("n")} brands over '
            f'&#36;{floor / 1e6:,.0f}mm</div>')
    out.append(f'<div class="byline">{html_escape(split.get("patients_note") or "")}</div>')
    out.append("</div>")
    return "".join(out)


def _medicare_tile_sub(dem) -> str:
    """The fact profile's Medicare spend subtitle: the year, spend growth and, where
    the main part's patient count is like for like, its patient growth."""
    if not dem:
        return "not in Part D/B"
    out = f'US {dem["year"]}'
    if dem.get("spend_growth") is not None:
        out += f', {_mc_pct(dem["spend_growth"])} YoY'
    parts = dem.get("parts") or []
    main = parts[0] if parts else None
    if main and main.get("patient_growth") is not None and main.get("like_for_like"):
        out += f', patients {_mc_pct(main["patient_growth"])}'
        if len(parts) > 1:
            out += f' in Part {main["part"]}'
    return out


# A fragment: picking a product, a scenario or a lever reruns this tab alone. The page
# renders every tab on every rerun, so a click here used to redraw all of them and refetch
# whatever their cache had let go, which is where a product click spent its time. A save
# still reruns the page, since the other tabs read what it wrote.
@st.fragment
def _render_forecast_tab(api_base: str, ticker: str):
    """The forecast: the book above, the product beneath, the levers under both.

    Two zones on one screen. The book is the company: what every modelled asset is
    worth a share, ranked, with the revenue that makes it drawn against what the
    company reported. The workbench is one product: the path, the bridge from path to
    figure, and the levers that move both. The list in the book is the picker, so
    reading it and choosing from it are one act. Everything deeper is a layer under
    the workbench, answering a question the figures above provoke.
    """
    st.markdown('<span class="no-rail fc-anchor"></span>', unsafe_allow_html=True)
    try:
        overview = api_get(api_base, f"/companies/{ticker}/forecast")
    except (urllib.error.URLError, OSError) as exc:
        state("Forecast unavailable", f"the API did not answer: {exc}", error=True)
        return
    options = [(a["asset_id"], a["name"] or f"Unnamed asset {a['asset_id']}",
                a["assumption_rows"])
               for a in overview.get("pickable") or []]
    options += [(a["asset_id"], f"{a['name'] or 'Unnamed asset'} (via {a['owner']})",
                 a["assumption_rows"])
                for a in overview.get("partnered") or []]
    if not options:
        state("No forecastable products",
              "a forecast starts from a marketed product or an assumption seed under "
              "data/assumptions/")
        _peer_value_section(api_base, ticker)
        return
    labels = {aid: name + ("" if n else "  (start one)") for aid, name, n in options}
    ordered = sorted(options, key=lambda o: (o[2] == 0, o[1]))
    ids = [aid for aid, _n, _r in ordered]
    pick_key = f"fc_pick_{ticker}"
    selected = st.session_state.get(pick_key)
    if selected not in ids:
        # Nothing chosen yet: open on the largest line in the book rather than on the
        # first name in the alphabet, which is what a reader would click first anyway.
        top = _book_top(api_base, ticker)
        selected = top if top in ids else ids[0]
        st.session_state[pick_key] = selected

    # The book. A click on a row is a request to read that product: the picker's
    # value is set before the picker reads its key, and the page reruns onto it.
    _company, clicked, slots = _book(api_base, ticker, selected)
    if clicked is not None and clicked in ids and clicked != selected:
        st.session_state[pick_key] = clicked
        _rerun_here()
    bench = (slots or {}).get("bench") or st.container()
    below = (slots or {}).get("below") or st.container()

    with bench:
        st.markdown('<div class="fc-bench"></div>', unsafe_allow_html=True)
        # Beside the asset list the bench is half the page, so the scenario control gets
        # room for its three choices on one line.
        pick_col, scenario_col, id_col = st.columns([1.2, 1.05, 2.2], gap="small")
        with pick_col:
            sel = st.selectbox("Product", ids, format_func=lambda aid: labels[aid],
                               key=pick_key, label_visibility="collapsed")
        with scenario_col:
            scenario = st.segmented_control(
                "Scenario", ["base", "bear", "bull"], default="base",
                key=f"fc_scenario_{ticker}_{sel}", label_visibility="collapsed") or "base"

        try:
            data = api_get(api_base,
                           f"/companies/{ticker}/forecast/{sel}?scenario={scenario}")
        except (urllib.error.URLError, OSError) as exc:
            state("Forecast unavailable", str(exc), error=True)
            return

        if not data.get("ok"):
            missing = ", ".join(data.get("missing") or [])
            drew = _curve_shaper(api_base, ticker, sel, scenario,
                                 data.get("missing") or [])
            if not drew:
                state("No forecast yet", f"missing: {missing}")
                template = data.get("template") or []
                if template:
                    note("required keys: " + "; ".join(
                        f"{row['key']} ({row['hint']})" for row in template))
            _forecast_editor(api_base, ticker, sel, scenario,
                             data.get("assumptions") or [])
            _forecast_import(api_base, ticker, sel, scenario,
                             data.get("assumptions") or [])
            return

        result = data["result"]
        years = result["years"]
        x_labels = [str(y) for y in years]
        unsourced = data.get("unsourced") or []
        scalars = data.get("scalars") or {}
        try:
            verdict = api_get(api_base, f"/companies/{ticker}/forecast/{sel}/verdict"
                                        f"?scenario={scenario}")
        except (urllib.error.URLError, OSError):
            verdict = {}
        if not verdict.get("ok"):
            verdict = {}
        # The Medicare split is its own read, so a failure empties this layer alone.
        try:
            medicare = api_get(api_base, f"/companies/{ticker}/forecast/{sel}/demand")
            medicare_error = None
        except (urllib.error.URLError, OSError) as exc:
            medicare, medicare_error = None, str(exc)
        medicare_html = _medicare_layer_html(medicare) if medicare else ""
        # The next gate's cost is its own read too, and only an asset with a gate asks.
        dev, dev_error = None, None
        if verdict.get("gate"):
            try:
                dev = api_get(api_base, f"/companies/{ticker}/forecast/{sel}/development")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                dev_error = str(exc)
        with id_col:
            st.markdown(_identity(data, result), unsafe_allow_html=True)

        # The figures and the charts are filled after the levers are read, because a moved
        # lever is what they show. Containers hold their place above the slider row.
        head_slot = st.container()
        charts_slot = st.container()
    with below:
        section("Levers", basis="same engine · base stays as the grey line")
        moved = _lever_controls(ticker, sel, result, scalars)
        varied = base_slim = None
        if moved:
            query = "&".join(f"{k}={v}" for k, v in moved.items())
            try:
                wi = api_get(api_base, f"/companies/{ticker}/forecast/{sel}/whatif"
                                       f"?scenario={scenario}&{query}")
            except (urllib.error.URLError, OSError) as exc:
                wi = None
                st.error(f"variation failed: {exc}")
            if wi and wi.get("ok"):
                varied, base_slim = wi["varied"], wi["base"]
        volume_scale = moved.get("volume", 1.0) if varied else 1.0

        # One frame for the whole scenario family where one exists, so switching bear to
        # bull moves the line rather than the scale.
        span_values = list(result["revenue_after_loe"])
        if verdict.get("has_range"):
            for scenario_name in ("base", "bear", "bull"):
                if scenario_name == scenario:
                    continue
                try:
                    other = api_get(api_base, f"/companies/{ticker}/forecast/{sel}"
                                              f"?scenario={scenario_name}")
                except (urllib.error.URLError, OSError):
                    continue
                if other.get("ok"):
                    span_values += other["result"]["revenue_after_loe"]
        revenue_span = (min(span_values), max(span_values)) if span_values else None
        _pat = [v for v in (list(result["patients"]["total"] or [])
                            + list(result["patients"].get("treated") or []))
                if v is not None]
        patients_span = (min(_pat), max(_pat)) if _pat else None
        placeholder = (result.get("curve_basis") or "").startswith("placeholder")

        shown = varied or result
        share = result.get("economics_share")
        shares = verdict.get("diluted_shares")
        close = verdict.get("close")
        owner_now = shown["owner_rnpv"] if share is not None else shown["rnpv"]
        owner_base = result["owner_rnpv"] if share is not None else result["rnpv"]
        per_share = (owner_now * 1e6 / shares) if shares else None
        per_share_base = (owner_base * 1e6 / shares) if shares else None

        with head_slot:
            headline = (verdict.get("note") or {}).get("headline")
            if headline:
                st.markdown(f'<div class="call-lead">{html_escape(headline)}</div>',
                            unsafe_allow_html=True)
            if varied:
                delta = shown["rnpv"] - result["rnpv"]
                change = f"{delta:+,.0f}{_mm()} vs base"
                tone = " up" if delta >= 0 else " down"
                ps_change = (f"{per_share - per_share_base:+,.2f} vs base"
                             if per_share is not None else None)
            else:
                change, tone, ps_change = None, "", None
            revenue = shown["revenue"] if varied else result["revenue_after_loe"]
            peak = max(revenue) if revenue else None
            peak_year = years[revenue.index(peak)] if peak is not None else None
            clause = _short
            # Wider than the 40 the other captions take, so the date survives the cut.
            # The whole point of the discount rate naming a vintage is that a reader sees
            # how old it is without opening anything, and "CAPM from components on rates
            # to 2026-09-18" is 43 characters.
            wacc_note = ("slider" if "wacc" in moved and varied
                         else clause(result.get("wacc_basis"), 48))
            pos_note = ("slider" if "pos" in moved and varied
                        else _pos_caption(result.get("pos_granular"))
                        or clause(result.get("pos_basis")))
            tiles = [("per share", T.num(per_share, 2) if per_share is not None else None,
                      "", ps_change, tone, "risk-adjusted, this asset only"),
                     ("share of price",
                      T.pct(per_share / close * 100, 1) if (per_share and close) else None,
                      "", None, "", f"of ${close:,.2f}" if close else "no price on file"),
                     ("rNPV", T.num(shown["rnpv"]), _mm(), change, tone,
                      f"base {T.num(result['rnpv'])}{_mm()}" if varied
                      else f"owner {share:.0%} of economics" if share is not None
                      else f"NPV {T.num(shown['npv'])}{_mm()} before PoS"
                      if shown["pos"] < 1.0 - 1e-9 else "risk-adjusted"),
                     ("peak revenue", T.num(peak), _mm(), None, "",
                      f"in {peak_year}" if peak_year else ""),
                     ("WACC", f"{shown['wacc'] * 100:.2f}", "%", None, "", wacc_note),
                     ("PoS", f"{shown['pos'] * 100:.0f}", "%", None, "", pos_note)]
            loe_shown = shown.get("loe_year") if varied else result.get("loe_year")
            # "none" rather than a dash: the tiles read a dash as data that is missing,
            # and an asset with no exclusivity on file is a fact, not a gap in a source.
            tiles.append(("LOE", str(loe_shown) if loe_shown
                          else "past" if result.get("loe_in_base") else "none", "", None, "",
                          "slider" if "loe_year" in moved and varied
                          else clause(result.get("loe_basis")) if loe_shown
                          else "date not on file" if result.get("loe_in_base")
                          else "no exclusivity on file"))
            st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)
            if unsourced:
                st.markdown(f'<div class="byline">unsourced assumptions: '
                            f'{html_escape(", ".join(unsourced))}</div>',
                            unsafe_allow_html=True)
            if placeholder:
                state("Drawn on a placeholder curve, and not counted",
                      "the uptake ceiling and midpoint are the shaper's probe values. This "
                      "asset is left out of the company per-share figure until real values "
                      "are committed, under Uptake below.")

        with charts_slot:
            path_col, bridge_col = st.columns([1.6, 1], gap="medium")
            with path_col:
                _revenue_path(data["name"], result, varied, base_slim,
                              data.get("actuals") or [], moved, scenario, revenue_span)
            with bridge_col:
                _value_bridge(shown, verdict, bool(varied))

        # Everything under the levers is a layer, not a step. Each answers a question the
        # figures above provoke, and only one is asked at a time, so they share one screen.
        st.markdown('<span class="fc-layers"></span>', unsafe_allow_html=True)
        has_uptake = (patients_span is not None or placeholder
                      or result.get("mode") == "franchise")
        n_rows = len(data.get("assumptions") or [])
        # Medicare sits after Drivers, only where CMS has a series for the brand. The next
        # gate sits beside it, only where the asset has one: a pipeline asset reads the
        # one and a marketed brand the other.
        has_medicare = bool(medicare_html) or bool(medicare_error)
        has_gate = bool(verdict.get("gate"))
        layer_names = (["Drivers"] + (["Next gate"] if has_gate else [])
                       + (["Medicare"] if has_medicare else [])
                       + (["Uptake"] if has_uptake else [])
                       + ["P&L", "Sensitivity", f"Assumptions · {n_rows}"])
        panels = dict(zip(layer_names, st.tabs(layer_names)))

        with panels["Drivers"]:
            if verdict:
                _drivers_layer(verdict, scenario)
            else:
                state("No verdict", "the API did not return one for this product")
            # The granular success rate is its own layer, and a marketed product has none,
            # which is not a missing verdict: the else once hung off this test and printed
            # "No verdict" under every approved product's drivers.
            if result.get("pos_granular"):
                _pos_layer(result["pos_granular"])

        if has_gate:
            with panels["Next gate"]:
                _next_gate_layer(verdict, dev, dev_error, scenario)

        if has_medicare:
            with panels["Medicare"]:
                if medicare_error:
                    state("Medicare split unavailable",
                          f"the API did not answer: {medicare_error}", error=True)
                else:
                    st.markdown(medicare_html, unsafe_allow_html=True)

        if has_uptake:
            with panels["Uptake"]:
                if patients_span is None:
                    note("no patient curve: this product is anchored on revenue rather than "
                         "built from patients, so the funnel is not rebuilt for it.")
                else:
                    _render_patient_chart(result, years, x_labels, volume_scale,
                                          patients_span)
                if placeholder:
                    _curve_shaper(api_base, ticker, sel, scenario, [])
                if result.get("mode") == "franchise":
                    _share_shaper(api_base, ticker, sel, scenario, result)

        with panels["P&L"]:
            _pnl_section(result, varied)

        with panels["Sensitivity"]:
            # The second axis is the input the mode builds revenue from (grid_axis).
            price_grid = {"marketed": "WACC x growth", "franchise": "WACC x pool growth",
                          "launch": "WACC x peak"}.get(result.get("mode"),
                                                       "WACC x net price")
            preset = st.segmented_control(
                "Grid", ["price", "loe"], default="price",
                format_func=lambda p: price_grid
                if p == "price" else "LOE year x year-one erosion",
                key=f"fc_grid_{ticker}_{sel}") or "price"
            try:
                grid = api_get(api_base, f"/companies/{ticker}/forecast/{sel}/sensitivity"
                                         f"?scenario={scenario}&preset={preset}")
            except (urllib.error.URLError, OSError):
                grid = None
            _sensitivity_grid(grid, result.get("rnpv"))

        with panels[layer_names[-1]]:
            _forecast_editor(api_base, ticker, sel, scenario,
                             data.get("assumptions") or [])
            blob = _export_blob(api_base.rstrip("/") + f"/companies/{ticker}/forecast/{sel}"
                                f"/export.xlsx?scenario={scenario}")
            if blob:
                st.download_button("Export to Excel", data=blob,
                                   file_name=f"{data['name'].lower()}_forecast.xlsx",
                                   key=f"fc_dl_{ticker}_{sel}")
            _forecast_import(api_base, ticker, sel, scenario,
                             data.get("assumptions") or [])


def _sensitivity_grid(grid, base_rnpv=None) -> None:
    """The rNPV grid, or nothing where the engine could not build one. The cell the
    live assumptions sit in is flagged, so the grid reads outward from where the
    model is rather than as twenty-five unanchored figures."""
    if grid and grid.get("ok"):
        values = [v for row in grid["grid"] for v in row if v is not None]
        low, high = (min(values), max(values)) if values else (0, 1)
        span = (high - low) or 1.0
        def axis(key, value):
            # Rates read as percents, years as years, a price as the figure it is.
            if key in ("wacc", "revenue_growth_pct", "franchise_growth_pct",
                       "erosion_year1_pct"):
                return f"{value * 100:.1f}%"
            if key == "loe_year":
                return f"{int(value)}"
            if key == "peak_revenue_musd":
                return f"{value:,.0f}"
            return f"{value:g}"
        row_labels = [axis(grid["y_key"], y) for y in grid["y_values"]]
        col_labels = [axis(grid["x_key"], x) for x in grid["x_values"]]
        cells = {}
        for i, row_label in enumerate(row_labels):
            for j, col_label in enumerate(col_labels):
                value = grid["grid"][i][j]
                if value is None:
                    continue
                cells[(row_label, col_label)] = {
                    "count": int(round(value)),
                    "weight": (value - low) / span,
                    "flagged": (base_rnpv is not None
                                and abs(value - base_rnpv) < 0.5)}
        R.show(CH.heatmap_grid(row_labels, col_labels, cells, 940, 60 + 44
                               * len(row_labels), flag_note="the live assumptions"),
               css_class="chart-mount stretch")
        labels = grid.get("labels") or {}
        note(f"columns: {labels.get('x') or grid['x_key']} ({grid['bases']['x']}) · "
             f"rows: {labels.get('y') or grid['y_key']} ({grid['bases']['y']}) · "
             f"the ticked cell is where the model stands")
    else:
        state("No grid", "; ".join((grid or {}).get("missing") or ["the engine could not build one"]))


def snapshot_meta(snapshot: dict) -> str:
    """The closing date, and only that.

    The period label is the chip beside the heading now and every tile carries its own
    unit, so a rule that also said both wrapped onto a second line and over its own
    figures once the block moved into half a page.
    """
    return f'to {snapshot["period_end"]}'


def snapshot_strip(snapshot: dict) -> str:
    """The latest reported period, as tiles. The currency is named in the heading."""

    def money(value):
        return T.num(value / 1e9, 1) if value is not None else None

    def growth(value):
        if value is None:
            return "", ""
        # The sign is explicit. A bare "55.5%" beside a level reads as a share of
        # something until you get to the words.
        sign = "+" if value > 0 else ""
        return (f"{sign}{T.pct(value * 100, 1)} yoy",
                " up" if value > 0 else " down" if value < 0 else "")

    revenue_note, revenue_tone = growth(snapshot["revenue_growth"])
    income_note, income_tone = growth(snapshot["net_income_growth"])
    return metric_tiles([
        ("Revenue", money(snapshot["revenue"]), "bn", revenue_note, revenue_tone, ""),
        ("Net income", money(snapshot["net_income"]), "bn", income_note, income_tone, ""),
        ("EPS, diluted", T.num(snapshot["eps_diluted"], 2), "", "", "", ""),
        # Net margin is not a tile. It is the second series in the panel below, where it
        # has the history that makes a level mean something, and a lone 37.4% here would
        # be the same figure said twice.
        ("R&D", T.pct(snapshot["rd_intensity"] * 100
                      if snapshot["rd_intensity"] is not None else None, 1),
         "", "", "", "share of sales"),
    ], one_row=True)


def _quoted(text) -> str:
    """Text lifted out of a filing, ready to put back into a page.

    Decoded once before it is escaped again. The evidence sentences are cut out of filing
    HTML and a fifth of them still carry its entities, so GSK's Nuvalent terms read
    "estimated to be $9.4 billion (&#xA3;7.1 billion)" on the page: escaping alone turns
    the ampersand into &amp; and prints the entity as itself instead of a pound sign.
    """
    return html_escape(html.unescape(str(text or "")))


def _lead_box(item) -> str:
    """One headline as a box that opens onto its own detail.

    A native disclosure rather than a widget: the summary is already in the payload, so
    opening one costs no rerun and no round trip, and four of them open at once without
    the page rebuilding itself four times.
    """
    rows = "".join(
        f'<div class="lead-r"><span class="lead-rk">{html_escape(pair["label"])}</span>'
        f'<span class="lead-rv">{_quoted(pair["value"])}</span></div>'
        for pair in (item.get("summary") or []))
    quote = (f'<div class="lead-q">{_quoted(item["evidence"])}</div>'
             if item.get("evidence") else "")
    link = (f'<a class="lead-l" href="{html_escape(item["url"])}" target="_blank" '
            f'rel="noopener">source</a>' if item.get("url") else "")
    kind = html_escape((item.get("kind") or "").replace(" ", "_"))
    # The ticker leads the line in its own weight, so a reader scans the column of
    # companies first and reads the sentence second. It is already the first word of the
    # headline, so it is split off rather than repeated.
    # Where an item names two covered companies, both lead the line in their own weight
    # rather than one being the box's ticker and the other a word in the sentence. A
    # merger of two of your companies is not one company's news.
    parties = item.get("tickers") or [item.get("ticker") or ""]
    ticker = " and ".join(html_escape(p) for p in parties if p)
    text = item.get("headline") or ""
    lead = html_escape(item.get("ticker") or "")
    if lead and text.startswith(lead + " "):
        text = text[len(lead) + 1:]
    # A registry title runs to two hundred characters and would set the height of every
    # box beside it. Cut here rather than in the payload: the whole title is the first
    # row of the detail, so opening the box loses nothing.
    if len(text) > _LEAD_CHARS:
        text = text[:_LEAD_CHARS - 1].rstrip() + "…"
    # A money figure is a measurement, not a label, so it keeps its own case: the chip's
    # uppercase rule turned "$2.58bn" into "$2.58BN".
    figure = item.get("figure") or ""
    chip = "lead-f lead-f-num" if figure.startswith("$") else "lead-f"
    return (f'<details class="lead lead-{kind}"><summary>'
            f'<span class="lead-chev"></span>'
            f'<span class="{chip}">{html_escape(figure)}</span>'
            f'<span class="lead-h"><span class="lead-tk">{ticker}</span> '
            f'{html_escape(text)}</span>'
            f'<span class="lead-d">{html_escape(item.get("date") or "")}</span>'
            f'</summary><div class="lead-body">{rows}{quote}{link}</div></details>')


def _lead_columns(count: int, per_row: int) -> int:
    """Columns for ``count`` boxes: as few rows as the width takes, then split evenly.

    Six boxes across a six-wide space is one row of six. Where only four fit it is two
    rows of three, not four and a stray two, because a row that ends early reads as a
    box missing rather than as the shape of the week.
    """
    if count <= 0:
        return 1
    rows = -(-count // max(per_row, 1))
    return -(-count // rows)


def _coverage_columns(count: int, max_rows: int = 2, widest: int = 12) -> int:
    """Columns for the coverage grid: every company drawn, in as few rows as fit.

    Dropping companies to hold the height was the wrong trade. A panel is a shape, not a
    figure, and a shape stays readable at half the width, so the grid gets wider rather
    than shorter and the whole cohort is on the screen at once.
    """
    if count <= 0:
        return 1
    return min(max(-(-count // max(max_rows, 1)), 1), widest)


# --- the market level ------------------------------------------------------------
# What the book is discounted against, above what moved. The four rate series and the
# ECB crosses have been fetched since the terminal was built and read by two functions
# between them, so the level a valuation was struck at was never on a screen.

_RATE_LABELS = {"DGS10": "10-year Treasury", "DFII10": "10-year real",
                "T10YIE": "breakeven", "BAMLC0A3CAEY": "single-A yield"}
# The owner is named on the cell so the level is never read as ours, and named in full
# in the note below. In full on the cell it wrapped the date onto a second line and
# made one tile taller than the eight beside it.
_OWNER_SHORT = {"ICE Data Indices, LLC": "ICE"}
# A ticker is what the endpoint is keyed on. A reader wants the index.
_BENCHMARK_NAMES = {"^GSPC": "S&P 500", "^VIX": "VIX", "XLV": "XLV health",
                    "XBI": "XBI biotech"}
# A month, because it is long enough for a rate to have moved and short enough that the
# move is still the one a reader is carrying in their head.
_MARKETS_DAYS = 30


def _day(iso) -> str:
    """18 Sep, from an ISO date. The year is dropped: every cell is within the month."""
    if not iso:
        return ""
    try:
        return dt.date.fromisoformat(str(iso)[:10]).strftime("%-d %b")
    except ValueError:
        return str(iso)[:10]


# The span the Prices tab draws, mapped to the window the relative figure is measured
# over, and only where the two are the same window. Mapping 5Y onto the one-year figure
# put "-60.2% vs XLV" under a "5Y CHANGE" label, which is a one-year number wearing a
# five-year heading. A span with no exact match shows nothing.
_VS_SPANS = {"1M": "1m", "3M": "3m", "1Y": "1y"}


def _vs_sector(api_base: str, ticker: str, span: str) -> str:
    """The move against the sector, folded into the change cell rather than beside it.

    A sixth stat in that strip wraps at the app's narrower width, and the Prices tab is
    built to fit one screen. It also belongs here: a relative figure qualifies the
    absolute move it sits next to and reads as noise on its own.

    Absent rather than zero where the benchmark does not cover the window, because a
    company that listed last year has no one-year relative move and saying nil would
    be a claim.
    """
    want = _VS_SPANS.get((span or "").upper())
    if not want:
        return ""
    try:
        got = (api_get(api_base, f"/companies/{ticker}/relative")
               .get("windows") or {}).get(want)
    except Exception:
        return ""
    if not got or got.get("relative_pct") is None:
        return ""
    # A company that listed last year has no one-year relative move. The backend
    # returns what it measured with the dates it used; printing it under the longer
    # label is the caller's mistake to avoid, so it is avoided here.
    if not got.get("covers_window"):
        return ""
    move = got["relative_pct"] * 100
    tone = " risk" if move < 0 else ""
    return (f'<span class="rel{tone}">{"+" if move > 0 else ""}'
            f'{T.num(move, 1)}% vs XLV</span>')


# How the two lanes read on the page. The key is the lane and the value is what it is
# about, short enough to sit in a chip beside the date.
_POLICY_LANES = {"bis_pharma": "Section 232 tariffs",
                 "cms_ira": "Medicare negotiation"}
_POLICY_DAYS = 730


def _china_bd(api_base: str, ticker: str) -> None:
    """China-linked business development, counted and shown, with no direction claimed.

    One cell rather than a section, because the answer is usually a small number and
    the interesting part is the sentences behind it. The direction is deliberately
    absent: a headline does not state it reliably, and two of the stored rows read as
    agreements with a Chinese party while being the company licensing out and selling.

    Folded, like the morning note above it: open, it put about 90 words of verbatim
    headlines on Key insights' first screen for PFE at 1440 x 810, over 8.7's budget.
    """
    try:
        got = api_get(api_base, f"/companies/{ticker}/china-bd")
    except Exception:
        return
    if not got.get("count"):
        return
    with st.expander(f"China-linked business development · {got['count']} on file",
                     expanded=False):
        _china_bd_body(got)


def _china_bd_body(got: dict) -> None:
    """The deals behind ``_china_bd``'s fold: the two tiles, the rows, the method."""
    total = got.get("announced_value_total")
    st.markdown('<div class="byline">From the companies\' own words, direction not '
                'claimed.</div>', unsafe_allow_html=True)
    tiles = [
        ("deals", str(got["count"]), "", None, "",
         f"{got['priced']} state a figure" if got["priced"] else
         "none states a figure"),
        ("announced value", T.num(total / 1e6, 0) if total else None, "mm", None, "",
         "summed only where every deal states one"),
    ]
    st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)
    rows = ""
    for deal in got["deals"][:6]:
        rows += (f'<tr><td class="pol-d">{html_escape(deal.get("event_date") or "")}</td>'
                 f'<td class="pol-l">{html_escape(deal.get("deal_type") or "")}</td>'
                 f'<td class="pol-k">{html_escape(deal.get("evidence") or "")}</td>'
                 f'<td class="pol-t">{html_escape((deal.get("quote") or "")[:220])}</td></tr>')
    st.markdown(f'<table class="pol"><tbody>{rows}</tbody></table>',
                unsafe_allow_html=True)
    note("Counted from deals already stored, where the company's own quote or the "
         "counterparty names China and the row is genuinely this company's: a filing "
         "already is, and a headline has to name the company. Of twenty-one rows "
         "mentioning China across the universe, six are about somebody else, including "
         "two copies of one acquisition filed under BioMarin and Regenxbio. Two "
         "headlines on one day about one company are one deal, and the priced one "
         "survives. Which way the rights went is not claimed, because a headline does "
         "not state it: Alnylam's agreement for commercialisation in China is Alnylam "
         "licensing out, and Arrowhead's is Arrowhead selling, yet both read as "
         "agreements with a Chinese party. The value is announced consideration, "
         "milestones included, and is summed only where every deal on the list states "
         "one, since a partial sum reads as a total and is not one.")


# --- Key insights: the company on one page (company-scorecard.md 1.3 and 5.3) -------
# Every number on the tab is a scorecard object, a figure the strip has always read, or a
# catalyst or change row, and each is said once: the strip holds what the bars and the
# lines do not, the sentence names pillars without their numbers, and Next is the head
# of the Catalysts list rather than a second ranking. The builders below are pure string
# functions, so the tab's tests run them on the sample scorecard without the API.
_KI_LEFT_TO_NEWS = ("revenue_restatement", "rate_move")
# Dated ahead rather than changed: the strip and Next hold them.
_KI_AHEAD_KINDS = ("catalyst", "loe")
_KI_CHANGE_DAYS = 30
# Three, like Next. Five (the spec's count) put every block on the screen at 1440 x 810
# and the tab at 232 words for AZN and 241 for LLY against a budget of 220
# (company-scorecard.md 8.7); News has every row.
_KI_CHANGES_SHOWN = 3
# A headline is cut at a word to about this length, the whole of it on hover. A diff row
# ("slips 2027-05-14 -> 2028-01-10") is kept whole, since its meaning is in its tail.
_KI_HEADLINE_CHARS = 56
_KI_EMPTY = "·"
_KI_MINUS = "−"
_KI_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
              "Nov", "Dec")
_KI_FAILED = "The scorecard did not load: {error}."
_KI_NO_CHANGES = "Nothing rated high in 30 days."
# Revision 4 (docs/design/key-insights.md): the call beside the price, then three columns.
_KI_BREAKS_SHOWN = 2
_KI_NOT_MODELLED = ("Nothing is modelled for {T} yet, so there is no 12-month value. "
                    "Forecast starts one.")
_KI_NO_BRIDGE = "The bridge does not add up here; Forecast has it in full."
# The note's news, the kinds likeliest to bear on a price first. A slip is counted, not
# listed: it moves a date far more often than a price.
_KI_NEWS_ORDER = {"press_data_readout": 0, "press_deal": 1, "ira_selected": 1,
                  "ira_deselected": 1, "press_approval": 2, "new_approval": 2,
                  "efficacy_supplement": 3, "new_filing": 4, "material event": 4}
_KI_NEWS_SAID = 2
_KI_NOTE_WORDS = 180
_KI_NEWS_CHARS = 72
# A month with nothing rated high still says its press releases and FDA news: rated medium,
# they are company news all the same, and "none on file" would be false.
_KI_NEWS_MEDIUM = ("press_", "new_approval", "efficacy_supplement", "ira_")
# A headline's company preamble ("AstraZeneca announces", "Incyte and X Announce") goes, so
# what happened survives the cut.
_KI_PREAMBLE = re.compile(
    r"^(?:[A-Z][\w&.'’\-]*,?\s+){1,6}?(?:announces?|reports?|receives?|presents?|unveils?|"
    r"shares?|provides?)\s+(?:that\s+)?", re.I)
# An appositive that holds the result back ("Remigromig, a tri-specific agonist of ...,
# met its primary endpoint") is dropped before a cut.
_KI_APPOSITIVE = re.compile(
    r",\s+an?\s+.+?,\s+(?=(?:met|meets|achiev|show|demonstrat|receiv|grant|approv|fail|"
    r"did|delivers?)\w*\b)", re.I)
# A trial of these kinds or this far out is not the next test of anything.
_KI_NOT_A_TEST = re.compile(r"follow[- ]?up|long[- ]term|extension|rollover|continued access|"
                            r"expanded access", re.I)
_KI_NOT_A_COMPOUND = re.compile(r"regimen|lymphodepletion|standard of care|placebo|"
                                r"best supportive|chemotherapy alone", re.I)
_KI_READOUT_YEARS = 8
# The note names the first loss of exclusivity worth this share of revenue, and a larger
# one after it only inside this many years: past that it is not this year's question.
_KI_LOSS_MATERIAL = 0.05
_KI_LOSS_YEARS = 5
# A release's long names, as a reader says them.
_KI_SHORT_WORDS = (("Biologics License Application", "BLA"), ("New Drug Application", "NDA"),
                   ("Marketing Authorization Application", "MAA"),
                   ("Food and Drug Administration", "FDA"), ("U.S. FDA", "FDA"))
# A figure carries its currency's sign where it has a short one; the key names any other.
_KI_CURRENCY_SIGNS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_KI_COUNT_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight",
                   "nine", "ten")
# Key assets, readouts and expiries: five rows each, so the three columns end together.
_KI_ASSETS_SHOWN = 5
_KI_READOUTS_SHOWN = 5
_KI_EXPIRIES_SHOWN = 5
_KI_STAGE_RANK = {"Phase 3": 0, "Phase 2/3": 1, "Phase 2": 2, "Phase 1/2": 3, "Phase 1": 4}
_KI_PHASE_SHORT = {"Phase 1": "Ph 1", "Phase 1/2": "Ph 1/2", "Phase 2": "Ph 2",
                   "Phase 2/3": "Ph 2/3", "Phase 3": "Ph 3", "Phase 4": "Ph 4"}
_KI_REG_EVENTS = {"pdufa": "PDUFA", "regulatory decision": "decision", "adcom": "AdCom",
                  "ema decision": "EMA"}
_KI_SHORT = {"rev_growth": "Revenue growth", "op_margin": "Operating margin", "pretax_margin": "Pre-tax margin",
             "fcf_margin": "FCF margin", "nd_ocf": "Net debt / cash flow",
             "net_cash_rev": "Net cash / revenue", "runway": "Cash runway",
             "late_per_rev": "Late-stage per $10bn", "fresh_share": "New-launch revenue",
             "top_product": "Top product share", "trial_conc": "Trial concentration",
             "share_change": "Share count change", "late_compounds": "Late-stage compounds",
             "mid_late_compounds": "Phase 2 or later", "loe_years": "Exclusivity left"}


def _ki_attr(text) -> str:
    """A value for a double-quoted HTML attribute."""
    return html.escape(str(text or ""), quote=True)


def _ki_signed_pct(fraction, decimals: int = 1) -> str:
    """"+13.2%" or "−1.7%" from a fraction; "" when there is none."""
    if fraction is None or fraction != fraction:
        return ""
    pct = abs(fraction) * 100
    text = f"{pct:,.{decimals}f}%"
    if round(pct, decimals) == 0:
        return text
    return ("+" if fraction > 0 else _KI_MINUS) + text


def _ki_month(iso) -> str:
    """"Sep 2027" from "2027-09-08"; "" when it is not a date."""
    m = re.match(r"^(\d{4})-(\d{2})", str(iso or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return ""
    return f"{_KI_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def _ki_day(iso) -> str:
    """"22 Sep 2026" from "2026-09-22 19:50:51"; the month alone without a day."""
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", str(iso or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return ""
    month = f"{_KI_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return f"{int(m.group(3))} {month}" if m.group(3) else month


def _ki_product(name) -> str:
    """A product's name with anything in brackets dropped, as the lines print it, and a
    brand the source shouts ("VYJUVEK") in the title case every other name has. A code
    with a digit in it ("ABBV-400") stays as it is."""
    name = re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip()
    if name.isupper() and len(name) > 4 and not re.search(r"\d", name):
        return name.title()
    return name


def _ki_money(v, decimals: int = 2) -> str:
    """"1,149.85", "−19.44", "·" for None."""
    if v is None or v != v:
        return _KI_EMPTY
    text = f"{abs(v):,.{decimals}f}"
    return (_KI_MINUS + text) if v < 0 and round(abs(v), decimals) else text


def _ki_ord(n) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _ki_tone(x) -> str:
    return "" if x is None else "up" if x > 0 else "down" if x < 0 else ""


def _ki_year_series(points: list, days: int = 365) -> dict:
    """The last ``days`` of daily closes and what the call reads off them: the close,
    the day's move, the move over the year (only on a full year of prices) and the range."""
    rows = [(str(p.get("as_of") or "")[:10], p.get("close")) for p in points or []
            if isinstance(p, dict) and p.get("close") is not None]
    rows = [r for r in rows if re.match(r"^\d{4}-\d{2}-\d{2}$", r[0])]
    rows.sort()
    if not rows:
        return {"closes": [], "dates": [], "close": None, "as_of": None, "day_move": None,
                "year_move": None, "low": None, "high": None}
    last = dt.date.fromisoformat(rows[-1][0])
    since = (last - dt.timedelta(days=days)).isoformat()
    year = [r for r in rows if r[0] >= since]
    closes = [c for _, c in year]
    day_move = rows[-1][1] / rows[-2][1] - 1 if len(rows) > 1 and rows[-2][1] else None
    first = dt.date.fromisoformat(year[0][0])
    year_move = (closes[-1] / closes[0] - 1
                 if (last - first).days >= 358 and closes[0] else None)
    return {"closes": closes, "dates": [d for d, _ in year], "close": closes[-1],
            "as_of": rows[-1][0], "day_move": day_move, "year_move": year_move,
            "low": min(closes), "high": max(closes)}


def _ki_range_fmt(v, low) -> str:
    """A range end: whole figures where the range's low end is 100 or more, two places
    below it, so a range far under the price ("18.82 to 19.12") never reads "19 to 19"."""
    if v is None:
        return _KI_EMPTY
    return f"{v:,.0f}" if low is not None and low >= 100 else f"{v:,.2f}"


def _ki_call(rated: dict, fv_reason, series: dict, street: dict = None) -> dict:
    """The lead of the page: the model's twelve-month value with its rating, else the
    street's target, else a dot with the reason. The move is against the close."""
    rated = rated if isinstance(rated, dict) else {}
    close = series.get("close") if isinstance(series, dict) else None
    target = (street or {}).get("value") if isinstance(street, dict) else None
    if rated.get("ok") and rated.get("forward_12m") is not None:
        fwd = rated["forward_12m"]
        word = rated.get("rating") or _KI_EMPTY
        tone = {"Strong buy": "up", "Buy": "up", "Sell": "down", "Strong sell": "down"}.get(
            word, "neutral")
        move = rated.get("upside_12m")
        if move is None and close:
            move = fwd / close - 1
        sub = f"against {_ki_money(close)}" if close is not None else ""
        if rated.get("forward_low") is not None and rated.get("forward_high") is not None:
            low = min(rated["forward_low"], rated["forward_high"])
            sub += (f" · {_ki_range_fmt(rated['forward_low'], low)} to "
                    f"{_ki_range_fmt(rated['forward_high'], low)} in 12 months")
        coe, dps = rated.get("cost_of_equity"), rated.get("dps")
        tip = "rolled a year"
        if coe is not None:
            tip += f" at the {coe:.1%} cost of equity"
        if dps:
            tip += f", less the {_ki_money(dps)} dividend"
        return {"source": "model", "key": "12-month value · model", "word": word,
                "word_tone": tone, "word_tip": rated.get("basis") or rated.get("reason") or "",
                "value": _ki_money(fwd), "tip": tip, "move": _ki_signed_pct(move),
                "move_tone": _ki_tone(move), "sub": sub.strip(" ·"), "note": ""}
    reason = (rated.get("reason") or fv_reason or "no sum of the parts on file")
    if target is not None:
        move = target / close - 1 if close else None
        return {"source": "street", "key": "12-month street target", "word": "",
                "word_tone": "neutral", "word_tip": "", "value": _ki_money(target),
                "tip": "the street's mean price target", "move": _ki_signed_pct(move),
                "move_tone": _ki_tone(move),
                "sub": f"against {_ki_money(close)}" if close is not None else "",
                "note": "not rated", "note_tip": reason}
    return {"source": None, "key": "12-month value", "word": "", "word_tone": "neutral",
            "word_tip": "", "value": "", "tip": f"{reason}; no consensus on file",
            "move": "", "move_tone": "", "sub": "Not modelled, and no consensus on file.",
            "note": ""}


def _ki_call_failed(error) -> dict:
    """The call when the rating could not be read: a dot that says so, never the street."""
    return {"source": None, "key": "12-month value", "word": "", "word_tone": "neutral",
            "word_tip": "", "value": "", "tip": str(error or ""), "move": "",
            "move_tone": "", "sub": "The rating did not load; reload in a minute.", "note": ""}


def _ki_figures(series: dict, call: dict, momentum: dict = None, street: dict = None,
                multiple: dict = None, multiple_place: dict = None) -> list:
    """The market row under the call, five cells of (value, key, tone, tip): the close,
    the day, the year against the sector, the street, the multiple against peers."""
    series = series if isinstance(series, dict) else {}
    out = []
    close = series.get("close")
    if close is None:
        out.append((_KI_EMPTY, "close · no price on file", "none", "no price on file"))
    else:
        out.append((_ki_money(close), "close", "", f"as of {series.get('as_of') or ''}".strip()))
    day = series.get("day_move")
    if day is None:
        out.append((_KI_EMPTY, "24 hours · no prior close", "none", "no prior close on file"))
    else:
        out.append((_ki_signed_pct(day), "24 hours",
                    _ki_tone(day) if round(abs(day) * 100, 1) else "",
                    "the close against the close before it"))
    year = series.get("year_move")
    mom = momentum if isinstance(momentum, dict) else {}
    if year is None:
        out.append((_KI_EMPTY, "1 year · under a year of prices", "none",
                    "less than a year of prices on file"))
    else:
        key = "1 year" + (f" · {re.sub(r'(?<![0-9])1 points', '1 point', str(mom['text']))} vs XLV"
                          if mom.get("text") else "")
        tip = (f"{mom['place']} of {mom['n']} against XLV" if mom.get("place") and mom.get("n")
               else _ki_reason(mom))
        out.append((_ki_signed_pct(year), key,
                    _ki_tone(year) if round(abs(year) * 100, 1) else "", tip))
    st_ = street if isinstance(street, dict) else {}
    if (call or {}).get("source") == "street":
        if series.get("low") is not None:
            out.append((f"{_ki_range_fmt(series['low'], series['low'])} to "
                        f"{_ki_range_fmt(series['high'], series['low'])}", "52 weeks", "small",
                        "the year's lowest and highest close"))
        else:
            out.append((_KI_EMPTY, "52 weeks · no price on file", "none", "no price on file"))
    elif st_.get("value") is not None:
        ratings = st_.get("ratings") or {}
        counts = ", ".join(f"{ratings[k]} {k}" for k in ("buy", "hold", "sell")
                           if ratings.get(k))
        tip = " · ".join(part for part in (
            f"{_ki_money(st_.get('low'))} to {_ki_money(st_.get('high'))}"
            if st_.get("low") is not None and st_.get("high") is not None else "",
            counts, str(st_.get("as_of") or "")) if part)
        out.append((_ki_money(st_["value"]), "street target", "", tip))
    else:
        out.append((_KI_EMPTY, "street · no consensus on file", "none", "no consensus on file"))
    mult = multiple if isinstance(multiple, dict) else {}
    if mult.get("text"):
        key = mult.get("label") or "multiple"
        if mult.get("median_text"):
            key += f" · median {mult['median_text']}"
        place = multiple_place if isinstance(multiple_place, dict) else {}
        tip = f"{place['place']} of {place['n']}" if place.get("place") and place.get("n") else ""
        out.append((mult["text"], key, "", tip))
    else:
        out.append((_KI_EMPTY, "multiple · none on file", "none", "no multiple on file"))
    return out


def _ki_revenue(verdict: dict, record: dict) -> dict:
    """The latest year's revenue as filed: {"figure": "58.7bn", "currency", "fy", "growth"}
    from the forecast's reported rows in the currency they are filed in, else the payload's
    FY0 in dollars; {} with neither."""
    ver = verdict if isinstance(verdict, dict) else {}
    rec = record if isinstance(record, dict) else {}
    reported = [r for r in ver.get("reported_revenue") or [] if isinstance(r, dict)
                and r.get("value") is not None and r.get("fiscal_year") is not None]
    fy0 = (rec.get("periods") or {}).get("FY0") or {}
    fy0_year = re.search(r"(\d{4})", str(fy0.get("label") or ""))
    if reported and fy0_year and int(reported[-1]["fiscal_year"]) < int(fy0_year.group(1)):
        # The last revenue filed is older than the latest year on file: that year had none.
        return {"figure": "", "currency": "", "fy": f"FY{fy0_year.group(1)}", "growth": None,
                "stale": f"FY{reported[-1]['fiscal_year']}"}
    if reported:
        last = reported[-1]
        prev = reported[-2] if len(reported) > 1 else None
        fig, unit = _ki_level(last["value"])
        growth = None
        # Growth off a base under a million is noise, not a rate a reader can use.
        if prev and prev.get("value") and int(last["fiscal_year"]) - int(prev["fiscal_year"]) == 1 \
                and abs(prev["value"]) >= 1 and abs(last["value"]) >= 1:
            growth = last["value"] / prev["value"] - 1
        return {"figure": f"{fig}{unit}",
                "currency": rec.get("row_currency") or rec.get("reporting_currency") or "",
                "fy": f"FY{last['fiscal_year']}", "growth": growth}
    if fy0.get("revenue_usd_m"):
        fig, unit = _ki_level(fy0["revenue_usd_m"])
        return {"figure": f"{fig}{unit}", "currency": "USD", "fy": str(fy0.get("label") or ""),
                "growth": None}
    return {}


def _ki_business_figures(record: dict, verdict: dict, company: dict, modelled: bool,
                         exclusivities: list = None, failed: str = "") -> list:
    """The business row under the market row, five cells of (value, key, tone, tip): the
    market value, the year's revenue and its growth, the products on sale, the late-stage
    compounds and every compound in trials."""
    rec = record if isinstance(record, dict) else {}
    ver = verdict if isinstance(verdict, dict) else {}
    out = []
    mkt = rec.get("market") or {}
    cap = mkt.get("market_cap_usd_m")
    # A failed read is said to have failed, never taken for a company with nothing on file.
    lost = (lambda field: (_KI_EMPTY, f"{field} · did not load", "none", str(failed))) \
        if failed and not rec else None
    if lost and not cap:
        out.append(lost("market cap"))
    elif cap:
        fig, unit = _ki_level(cap)
        out.append((f"${fig}{unit}", "market cap", "",
                    str(mkt.get("market_cap_basis_text") or "")))
    else:
        out.append((_KI_EMPTY, "market cap", "none", "no share count on file"))
    rev = _ki_revenue(ver, rec)
    if rev.get("stale"):
        out.append((_KI_EMPTY, f"{rev['fy']} revenue", "none",
                    f"no revenue filed for {rev['fy']}; the last filed is {rev['stale']}"))
    elif rev:
        sign = _KI_CURRENCY_SIGNS.get(rev.get("currency") or "")
        key = " ".join(x for x in (rev.get("fy"), "revenue",
                                   "" if sign else rev.get("currency")) if x)
        if rev.get("growth") is not None:
            key += f" · {_ki_signed_pct(rev['growth'])}"
        tip = f"{rev.get('fy')} revenue as filed" + (
            f", in {rev['currency']}" if rev.get("currency") else "")
        out.append(((sign or "") + rev["figure"], key, "", tip))
    else:
        out.append((_KI_EMPTY, "revenue", "none", "no revenue on file"))
    m = (ver.get("sotp") or {}).get("marketed") or {}
    if modelled and m.get("n"):
        out.append((f"{m['n']:,}", "product on sale" if m["n"] == 1 else "products on sale",
                    "", "the products on sale the model counts"))
    else:
        names = {_ki_product(a.get("generic_name") or a.get("brand_name")).lower()
                 for a in exclusivities or [] if isinstance(a, dict)
                 and (a.get("brand_name") or a.get("generic_name"))}
        if names:
            out.append((f"{len(names):,}",
                        "approved product" if len(names) == 1 else "approved products", "",
                        "molecules with an FDA approval and an exclusivity record on file, "
                        "a new formulation counted once"))
        elif lost:
            out.append(lost("products on sale"))
        else:
            out.append((_KI_EMPTY, "products on sale", "none",
                        "no approved product on file"))
    pipe = ((rec.get("detail") or {}).get("pipeline") or {}).get("compounds") or {}
    if pipe:
        late = (pipe.get("Phase 3") or 0) + (pipe.get("Phase 2/3") or 0)
        # Phase 4 compounds are approved products, counted under the products on sale.
        total = sum(v for k, v in pipe.items() if isinstance(v, (int, float))
                    and k in _KI_STAGE_RANK)
        metric = _ki_metric(company, ("late_compounds",)) if company else None
        out.append((f"{late:,}", "late-stage", "",
                    " · ".join(x for x in ("compounds in Phase 3 or Phase 2/3",
                                           _ki_place(metric)) if x)))
        out.append((f"{total:,}", "in trials", "",
                    "every compound in Phase 1 to Phase 3 with a trial on file"))
    elif lost:
        out += [lost("late-stage"), lost("in trials")]
    else:
        out.append((_KI_EMPTY, "late-stage", "none", "no trials on file"))
        out.append((_KI_EMPTY, "in trials", "none", "no trials on file"))
    return out


def _ki_call_html(call: dict, figures: list, business: list = None) -> str:
    """The call: key, then the rating word, the value and the move on one baseline, the
    range under them, then two rows of five figure cells, the market and the business.
    Keeps the page's .pos class."""
    word = (f'<span class="ki-word {call.get("word_tone") or "neutral"}" '
            f'title="{_ki_attr(call.get("word_tip"))}">{html_escape(call["word"])}</span>'
            if call.get("word") else "")
    fig_cls = "ki-fig none" if call.get("value") == _KI_EMPTY else "ki-fig"
    fig = (f'<span class="{fig_cls}" title="{_ki_attr(call.get("tip"))}">'
           f'{html_escape(call["value"])}</span>' if call.get("value") else "")
    move = (f'<span class="ki-move {call.get("move_tone") or ""}">'
            f'{html_escape(call["move"])}</span>' if call.get("move") else "")
    note = (f'<span class="ki-note-tag" title="{_ki_attr(call.get("note_tip"))}">'
            f'{html_escape(call["note"])}</span>' if call.get("note") else "")
    # With a value the sub line sits on the lead's baseline, which keeps the call level
    # with the chart beside it; without one it is the lead.
    sub_cls = "ki-sub" if call.get("value") else "ki-sub ki-sub-lead"
    sub_tag = "span" if call.get("value") else "div"
    sub = (f'<{sub_tag} class="{sub_cls}" title="{_ki_attr(call.get("tip"))}">'
           f'{html_escape(call["sub"])}</{sub_tag}>' if call.get("sub") else "")
    def cells(rows):
        return "".join(
            f'<div class="ki-f" title="{_ki_attr(tip)}"><span class="v {tone}">'
            f'{html_escape(value)}</span><span class="k">{html_escape(key)}</span></div>'
            for value, key, tone, tip in rows)
    biz = f'<div class="ki-figs ki-biz">{cells(business)}</div>' if business else ""
    return (f'<div class="pos ki-call"><div class="ki-k">{html_escape(call["key"])}</div>'
            f'<div class="ki-lead">{word}{fig}{move}{note}'
            f'{sub if sub_tag == "span" else ""}</div>{"" if sub_tag == "span" else sub}'
            f'<div class="ki-figs">{cells(figures)}</div>{biz}</div>')


def _ki_plural(n, one: str, many: str = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _ki_bridge(sotp: dict, forward_check=None) -> dict:
    """The twelve-month value as a bridge, from what is sold to the twelve-month figure,
    each step named by what it is and its sign: growth capital always takes off, net cash
    adds and net debt takes off, other claims folded into the second. It is drawn only
    where it adds up: today's end to the equity (or, with no debt on file, the enterprise
    value), the end to the twelve-month value and that to the rating's, each to the cent.
    {ok, steps, end, reason}."""
    s = sotp if isinstance(sotp, dict) else {}
    m = (s.get("marketed") or {}).get("per_share")
    if m is None:
        return {"ok": False, "steps": [], "end": None, "reason": "no sum of the parts"}
    n_m = (s.get("marketed") or {}).get("n") or 0
    steps = [{"label": "marketed", "value": m, "kind": "start",
              "tip": f"{_ki_plural(n_m, 'product')} on the market"}]
    run = m
    p = s.get("pipeline") or {}
    if p.get("n"):
        v = p.get("per_share") or 0.0
        steps.append({"label": "pipeline", "value": v, "kind": "step",
                      "tip": f"{_ki_plural(p['n'], 'candidate')} after their chance of "
                             "approval"})
        run += v
    ln = s.get("lines") or {}
    if ln.get("n"):
        v = ln.get("per_share") or 0.0
        steps.append({"label": "lines", "value": v, "kind": "step",
                      "tip": f"{_ki_plural(ln['n'], 'revenue line')} no product model holds"})
        run += v
    fut = (s.get("future") or {}).get("per_share")
    steps.append({"label": "launches", "value": fut, "kind": "step",
                  "tip": "launches past the modelled pipeline, from R&D"})
    run += fut or 0.0
    carry = s.get("carry_per_share")
    if carry:
        tip = "carried to the close"
        if s.get("valuation_anchor") and s.get("years_to_price") is not None:
            tip = (f"valued at {s['valuation_anchor']}, carried {s['years_to_price']:.2f}y "
                   f"to the {s.get('price_date') or ''} close").replace("  ", " ")
        steps.append({"label": "to today", "value": carry, "kind": "step", "tip": tip})
        run += carry
    growth = (s.get("growth_investment") or {}).get("per_share")
    if growth:
        steps.append({"label": "growth capital", "value": -abs(growth), "kind": "step",
                      "tip": "plant and working capital the growth needs"})
        run -= abs(growth)
    claims = s.get("other_claims_per_share") or 0.0
    net = s.get("net_cash_per_share")
    if net is None:
        if claims:
            steps.append({"label": "other claims", "value": claims, "kind": "step",
                          "tip": "other claims on the business"})
            run += claims
        steps.append({"label": "EV today", "kind": "end"})
        ev = s.get("enterprise_today_per_share")
        if ev is None or abs(run - ev) > 0.01:
            return {"ok": False, "steps": [], "end": None,
                    "reason": "the enterprise value does not reconcile"}
        return {"ok": True, "steps": steps, "end": run, "reason": None}
    balance = net + claims
    label = "net cash" if balance >= 0 else "net debt"
    tip = f"{'net cash' if net >= 0 else 'net debt'} {_ki_money(net)}"
    if claims:
        tip += f", other claims {_ki_money(claims)}"
    steps.append({"label": label, "value": balance, "kind": "step", "tip": tip})
    run += balance
    steps.append({"label": "today", "kind": "end"})
    eq = s.get("equity_per_share")
    if eq is None or abs(run - eq) > 0.01:
        return {"ok": False, "steps": [], "end": None, "reason": "today does not reconcile"}
    fwd = s.get("forward_12m")
    coe, dps = s.get("cost_of_equity"), s.get("dps") or 0.0
    if fwd is None or coe is None:
        return {"ok": True, "steps": steps, "end": eq, "reason": None}
    year = eq * coe - dps
    if abs(eq + year - fwd) > 0.01 or (forward_check is not None
                                       and abs(fwd - forward_check) > 0.01):
        return {"ok": False, "steps": [], "end": None,
                "reason": "the twelve-month value does not reconcile"}
    tip = f"{coe:.1%} cost of equity {_ki_money(eq * coe)}"
    if dps:
        tip += f", less the {_ki_money(dps)} dividend"
    steps += [{"label": "a year on", "value": year, "kind": "step", "tip": tip},
              {"label": "12 months", "kind": "end"}]
    return {"ok": True, "steps": steps, "end": fwd, "reason": None}


def _ki_lever_text(kind: str, value, key: str = "") -> str:
    """A lever's setting as the breaks print it: a rate to two places of a percent, launch
    productivity as a ratio, years with a y."""
    if value is None:
        return _KI_EMPTY
    if value < 0:
        return _KI_MINUS + _ki_lever_text(kind, abs(value), key)
    if key == "launch_rate":
        return f"{value:.3f} per R&D $"
    if kind == "year":
        return f"{int(value)}"
    if kind == "years":
        return f"{int(value)}y" if float(value).is_integer() else f"{value:.1f}y"
    if kind == "level":
        return f"${value:,.0f}mm"
    if kind == "scale":
        return f"×{value:.2f}"
    if kind == "price":
        return f"${value * 1e6:,.0f}"
    return f"{value:.2%}"


def _ki_breaks(bp: dict, shown: int = _KI_BREAKS_SHOWN) -> dict:
    """The nearest levers that alone take today's value to the price: {head, rows, tip}."""
    bp = bp if isinstance(bp, dict) else {}
    if not bp.get("ok"):
        return {}
    levers = [l for l in bp.get("levers") or [] if isinstance(l, dict)
              and l.get("reachable") and l.get("break") is not None
              and l.get("model") is not None]
    levers.sort(key=lambda l: l.get("distance") if l.get("distance") is not None else 1e9)
    if not levers:
        return {}
    eq, close = bp.get("equity_per_share"), bp.get("close")
    head = (f"Today's {_ki_money(eq)} meets the {_ki_money(close)} price at"
            if bp.get("direction") == "down" else f"The {_ki_money(close)} price needs")
    rows = []
    for l in levers[:shown]:
        name = (l.get("lever") if l.get("scope") == "company"
                else f"{_ki_product(l.get('name'))}'s {l.get('lever')}")
        rows.append({"glyph": "▼" if l["break"] < l["model"] else "▲", "name": name,
                     "model": _ki_lever_text(l.get("kind"), l["model"], l.get("key") or ""),
                     "brk": _ki_lever_text(l.get("kind"), l["break"], l.get("key") or ""),
                     "tip": " · ".join(str(x) for x in (l.get("evidence"),
                                                       l.get("evidence_class")) if x)})
    body = (bp.get("sentence") or {}).get("body") or []
    return {"head": head, "rows": rows, "tip": " ".join(str(b) for b in body)}


def _ki_street_expects(record: dict) -> list:
    """The street's EPS for the next two years, when there is no model: (value, key)."""
    eps = ((record or {}).get("street") or {}).get("eps_first") or {}
    out = []
    for key in ("FY1", "FY2"):
        e = eps.get(key) if isinstance(eps.get(key), dict) else {}
        if e.get("value") is not None:
            label = ((record or {}).get("periods") or {}).get(key, {}).get("label") or key
            out.append((_ki_money(e["value"]), f"{label} EPS, street"))
    return out


def _ki_metric(company: dict, ids: tuple) -> dict:
    """The first of ``ids`` with a value, searched across every pillar and then the
    measures a cohort reports without scoring (a commercial biotech's exclusivity), else the
    first of them present (with its reason), else None."""
    found = {}
    for p in ((company or {}).get("pillars") or {}).values():
        for m in (p or {}).get("metrics") or []:
            if isinstance(m, dict) and m.get("id") in ids:
                found.setdefault(m["id"], m)
    for m in (((company or {}).get("facts") or {}).get("other_metrics") or []):
        if isinstance(m, dict) and m.get("id") in ids:
            found.setdefault(m["id"], m)
    for i in ids:
        if found.get(i) and found[i].get("value") is not None:
            return found[i]
    return next((found[i] for i in ids if i in found), None)


def _ki_reason(metric: dict, reasons: dict = None) -> str:
    """Why a measure has no value, in words: the metric's own filled sentence, else the
    method's where it is not a template, else its key."""
    m = metric or {}
    if m.get("reason_text"):
        return str(m["reason_text"])
    r = m.get("reason")
    text = (reasons or {}).get(r) if r else None
    if text and "{" not in str(text):
        return str(text)
    return str(r or "no value on file").replace("_", " ")


def _ki_place(metric: dict) -> str:
    m = metric or {}
    return f"{m['place']} of {m['n']}" if m.get("place") and m.get("n") else ""


def _ki_peer_row(board: dict, ticker: str, metric: dict) -> dict:
    """One measure across the cohort: the company's value and place, every peer's value
    for the dot strip, the median and the tone of the company's dot."""
    board = board if isinstance(board, dict) else {}
    method = (board.get("method") or {}).get("metrics") or {}
    reasons = (board.get("method") or {}).get("reasons") or {}
    companies = board.get("companies") or {}
    me = companies.get(ticker) or {}
    mid = (metric or {}).get("id")
    meta = method.get(mid) or {}
    peers = []
    for t, c in companies.items():
        if not isinstance(c, dict) or c.get("cohort") != me.get("cohort") or t == ticker:
            continue
        m = _ki_metric(c, (mid,))
        if m and m.get("value") is not None:
            peers.append({"ticker": t, "value": m["value"], "text": m.get("text") or ""})
    cohort = (board.get("cohorts") or {}).get(me.get("cohort")) or {}
    score = (metric or {}).get("score")
    tone = "up" if score is not None and score >= 75 else (
        "down" if score is not None and score <= 25 else "neutral")
    reason = _ki_reason(metric, reasons) if (metric or {}).get("value") is None else None
    return {"id": mid, "label": _KI_SHORT.get(mid) or meta.get("label") or mid,
            "full_label": meta.get("label") or mid, "text": (metric or {}).get("text"),
            "place_text": _ki_place(metric), "value": (metric or {}).get("value"),
            "better": meta.get("better") or "higher",
            "median": (cohort.get("metric_medians") or {}).get(mid), "tone": tone,
            "peers": peers, "reason": reason}


def _ki_mix_segments(products: dict, fy0: dict, shown: int = 5) -> list:
    """The top products' shares of revenue and the rest, on the Portfolio donut's basis."""
    p = products if isinstance(products, dict) else {}
    seen: dict = {}
    for r in p.get("rows") or []:
        if isinstance(r, dict) and r.get("value_usd_m"):
            name = _ki_product(r.get("name")).lower()
            if name not in seen or r["value_usd_m"] > seen[name]["value_usd_m"]:
                seen[name] = r          # LNTH filed Definity twice: one row a product
    rows = sorted(seen.values(), key=lambda r: -r["value_usd_m"])
    if not rows:
        return []
    product_total = sum(r["value_usd_m"] for r in rows) + (p.get("unattributed_usd_m") or 0.0)
    total = (fy0 or {}).get("revenue_usd_m")
    label = str((fy0 or {}).get("label") or "")
    if (not total or str(p.get("fiscal_year")) not in label
            or sum(r["value_usd_m"] for r in rows[:shown]) > total):
        total = product_total
    out = []
    for i, r in enumerate(rows[:shown]):
        share = r["value_usd_m"] / total
        name = _ki_product(r.get("name"))
        out.append({"value": r["value_usd_m"], "key": f"m{i}", "label": name,
                    "sub": f"{share:.0%}", "tip": f"{name} {share:.1%} of revenue"})
    rest = total - sum(r["value_usd_m"] for r in rows[:shown])
    if rest > 0:
        out.append({"value": rest, "key": "rest", "label": "rest",
                    "sub": f"{rest / total:.0%}", "tip": f"the rest {rest / total:.1%}"})
    return out


def _ki_level(value_mm) -> tuple:
    """(figure, unit) for revenue in millions: ("58.7", "bn") or ("940", "mm")."""
    if value_mm is None:
        return _KI_EMPTY, ""
    if abs(value_mm) >= 1000:
        return f"{value_mm / 1000:,.1f}", "bn"
    if value_mm == 0:
        return "0", ""
    if abs(value_mm) < 1:
        return f"{value_mm * 1000:,.0f}", "k"
    return f"{value_mm:,.0f}", "mm"


def _ki_pct_words(x, up: str = "up", down: str = "down") -> str:
    """"down 2.3%" / "up 0.4%" / "flat"."""
    if x is None:
        return ""
    if round(abs(x) * 100, 1) == 0:
        return "flat"
    return f"{up if x > 0 else down} {abs(x) * 100:.1f}%"


def _ki_month_move(series: dict, days: int = 30):
    """The move over the last ``days`` of the year series, or None."""
    dates, closes = (series or {}).get("dates") or [], (series or {}).get("closes") or []
    if len(dates) < 2:
        return None
    last = dt.date.fromisoformat(dates[-1])
    since = (last - dt.timedelta(days=days)).isoformat()
    for d, c in zip(dates, closes):
        if d >= since and c:
            return closes[-1] / c - 1 if d < dates[-1] else None
    return None


def _ki_rel_words(metric: dict) -> str:
    """"24 points behind the sector (XLV)" from the scorecard's relative measure."""
    m = metric or {}
    if m.get("value") is None:
        return ""
    pts = round(abs(m["value"]) * 100)
    if pts == 0:
        return "in line with the sector (XLV)"
    return f"{_ki_points(pts)} {'ahead of' if m['value'] > 0 else 'behind'} the sector (XLV)"


def _ki_points(n) -> str:
    """"1 point", "24 points"."""
    return f"{n} point" if n == 1 else f"{n} points"


def _ki_unit_once(model, brk) -> str:
    """The model's figure without the unit the break-point beside it already says:
    "0.362" beside "0.307 per R&D $"."""
    m, b = str(model or ""), str(brk or "")
    unit = re.sub(r"^[−\-+]?[\d.,]+", "", b)
    if unit.strip() and not unit.startswith(("%", "y")) and m.endswith(unit):
        return m[:-len(unit)]
    return m


def _ki_span_words(days) -> str:
    """"98 days", "14 months", "4 years": a slip at the scale a reader thinks in."""
    if days is None:
        return ""
    if days < 60:
        return _ki_plural(days, "day")
    if days < 730:
        return _ki_plural(round(days / 30.44), "month")
    years = days / 365.25
    return _ki_plural(round(years), "year") if abs(years - round(years)) < 0.15 \
        else f"{years:.1f} years"


def _ki_event_words(item: dict, ticker: str, cut: bool = True) -> str:
    """A change as a clause of prose with its day: a press headline as published, less a
    bracketed preamble, the company's own "announces", trademark signs and an appositive
    that holds the result back, then cut at a clause or a word; "a new FDA indication for
    Truqap"; "FDA approval of Etcamah"; "an 8-K filing (material agreement signed)"; "CMS
    chose Botox for Medicare price negotiation (IPAY 2028)"; "a trial (NCT…) moved from
    Phase 2 to Phase 2/3". ``cut`` False keeps the headline whole, as the note model's facts
    need it, less any review note the feed carries for the analyst."""
    head = re.sub(r"^\[[^\]]*\]\s*", "", _ki_headline(item, ticker))
    head = re.sub(r"\.?\s*Review:.*$", "", head).strip()
    head = re.sub(r"\s*[®™©]", "", head)
    for long, short in _KI_SHORT_WORDS:
        head = head.replace(long, short)
    head = re.sub(r"\b[Pp]ivotal\s+", "", head)        # a word house style never uses
    when = _ki_short_day(item.get("date"))
    m_sup = re.match(r"^Efficacy supplement: (.+?) approved(?: (\d{4}-\d{2}-\d{2}))?", head)
    m_new = re.match(r"^FDA approval: (.+?)(?: \([A-Z]{2,4}\s?\d+\))?$", head)
    m_form = re.match(r"^(8-K|6-K|10-Q|10-K|20-F): (.+)$", head)
    m_phase = re.match(r"^Trial (NCT\d{8}): (Phase [^>]+?) -> (Phase .+)$", head)
    m_end = re.match(r"^Trial (NCT\d{8}): endpoint_change$", head)
    m_slip = re.search(r"(NCT\d{8}).*?slips", head)
    m_sel = re.match(r"^CMS selects? .*?price negotiation\W*(IPAY \d{4})?\W*:\s*(.+)$", head, re.I)
    m_desel = re.match(r"^CMS has deselected (.+?) from Medicare", head, re.I)
    if m_sup:
        text = f"a new FDA indication for {m_sup.group(1)}"
        when = _ki_short_day(m_sup.group(2)) or when
    elif m_new:
        text = f"FDA approval of {m_new.group(1)}"
    elif m_form:
        items = [x.strip() for x in m_form.group(2).split(",") if x.strip()]
        extra = 0
        tail = re.match(r"^and (\d+) more$", items[-1]) if items else None
        if tail:
            extra, items = int(tail.group(1)), items[:-1]
        listed = [x[:1].lower() + x[1:] for x in items] or ["no item named"]
        others = len(listed) - 1 + extra
        if others == 1 and not extra:         # two items are both said
            inner = f"{listed[0]} and {listed[1]}"
        elif others:
            inner = f"{listed[0]}, {_ki_plural(others, 'other item')}"
        else:
            inner = listed[0]
        article = "an" if m_form.group(1)[0] == "8" else "a"
        text = f"{article} {m_form.group(1)} filing ({inner})"
        if cut and len(text) > _KI_NEWS_CHARS + 18:
            # The items are the news: they are cut, never the filing they are in.
            room = _KI_NEWS_CHARS + 18 - len(f"{article} {m_form.group(1)} filing ()") - 1
            inner = inner[:room]
            inner = inner[:inner.rfind(" ")] if " " in inner else inner
            text = f"{article} {m_form.group(1)} filing ({inner.rstrip(' ,;:')}…)"
    elif m_sel:
        names = _ki_join([_ki_soft_caps(x) for x in re.split(r";\s*|,\s*", m_sel.group(2))
                          if x.strip()])
        text = (f"CMS chose {names} for Medicare price negotiation"
                + (f", with prices from {m_sel.group(1)[-4:]}" if m_sel.group(1) else ""))
    elif m_desel:
        names = _ki_join(list(dict.fromkeys(
            _ki_soft_caps(x) for x in re.split(r";\s*", m_desel.group(1)) if x.strip())))
        text = f"CMS dropped {names} from Medicare price negotiation"
    elif m_phase:
        text = f"a trial ({m_phase.group(1)}) moved from {m_phase.group(2)} to {m_phase.group(3)}"
    elif m_end:
        text = f"a trial ({m_end.group(1)}) changed its primary endpoint"
    elif m_slip and _ki_slip_days(item) is not None:
        text = f"a readout ({m_slip.group(1)}) slipped {_ki_slip_days(item)} days"
    else:
        text = head
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) > 0.7 * len(letters):
            text = re.sub(r"\b(fda|ema|eu|cms|bla|nda|snda|sbla|maa|us|uk|glp-1|gip|adc|"
                          r"chmp|mhra|nice|pdufa|ii|iii)\b",
                          lambda m: m.group(1).upper(), text.lower())
            text = text[:1].upper() + text[1:]
        if cut:
            short = _KI_PREAMBLE.sub("", text, count=1)
            if short != text and len(short) > 12:
                text = short[:1].upper() + short[1:]
            text = _KI_APPOSITIVE.sub(" ", text, count=1)
    if cut and len(text) > _KI_NEWS_CHARS and not (m_form or m_sel or m_desel):
        room = text[:_KI_NEWS_CHARS - 1]
        clause = max(room.rfind(", "), room.rfind(" to "), room.rfind(" and "))
        stop = clause if clause > _KI_NEWS_CHARS * 0.6 else room.rfind(" ")
        text = (room[:stop] if stop > 0 else room).rstrip(" ,;:")
        if text.count("(") > text.count(")"):          # never end inside brackets
            text = text[:text.rfind("(")].rstrip(" ,;:")
        text += "…"
    return f"{text} ({when})" if when else text


def _ki_soft_caps(name) -> str:
    """A name the feed shouts ("ENTRESTO SPRINKLE") as a name ("Entresto Sprinkle")."""
    name = str(name or "").strip()
    return name.title() if name.isupper() and len(name) > 3 else name


def _ki_short_day(iso) -> str:
    """"28 Sep" from "2026-09-28 07:37:14": inside the month the year goes without saying."""
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})", str(iso or ""))
    if not m or not 1 <= int(m.group(1)) <= 12:
        return ""
    return f"{int(m.group(2))} {_KI_MONTHS[int(m.group(1)) - 1]}"


def _ki_slip_days(item: dict):
    """The days a slip moved its readout, from the headline's two dates, or None."""
    m = re.search(r"slips (\d{4}-\d{2}(?:-\d{2})?) -> (\d{4}-\d{2}(?:-\d{2})?)",
                  str((item or {}).get("headline") or ""))
    if not m:
        return None
    try:
        a, b = (dt.date.fromisoformat(x if len(x) == 10 else x + "-01") for x in m.groups())
    except ValueError:
        return None
    return (b - a).days


def _ki_count_word(n: int) -> str:
    return _KI_COUNT_WORDS[n] if 0 <= n < len(_KI_COUNT_WORDS) else str(n)


def _ki_news_tone(item: dict) -> str:
    """"up", "down" or "": how a change reads for the holder, from its kind and, for a
    readout, its own words. A judgement on the news, never on what the price did."""
    ct = (item or {}).get("change_type") or ""
    head = str((item or {}).get("headline") or "")
    if ct == "press_data_readout":
        if re.search(r"did not|not meet|fail|discontinu|halt|futil|negative|unlikely to",
                     head, re.I):
            return "down"
        if re.search(r"\bmet\b|positive|significant|improv|superior|success", head, re.I):
            return "up"
        return ""
    if ct == "press_approval" and not _ki_is_approval(head):
        return ""
    # A deselection follows a generic's entry: a loss of exclusivity, not good news.
    return {"press_approval": "up", "new_approval": "up", "efficacy_supplement": "up",
            "ira_selected": "down", "date_slip": "down"}.get(ct, "")


def _ki_is_approval(headline) -> bool:
    """A release the feed files as an approval that reports one: not a board appointment
    "toward potential FDA approval", nor an approval still ahead."""
    head = str(headline or "")
    if re.search(r"\bappoints?\b|board of directors|toward potential|potential (?:FDA )?"
                 r"approval|seeks? approval|accepts? .*(?:application|filing)", head, re.I):
        return False
    return bool(re.search(r"approv|authori[sz]|clearance|cleared", head, re.I))


def _ki_join(parts: list) -> str:
    parts = [p for p in parts if p]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _ki_month_news(changes: list, ticker: str, limit: int = _KI_NEWS_SAID) -> dict:
    """The month's company news for the note: {"said": [clauses as shown], "full": [the
    same, headlines whole], "tones": [how each reads for the holder], "more", "slips": n,
    "longest": days, "quiet": n}. The kinds likeliest to bear on a price come first
    (results, deals and policy, then approvals), at most _KI_NEWS_SAID; new indications
    are said in one clause; an FDA approval the company's own release already says, and a
    filing the feed carries twice, are said once. Changes rated high come first; a month
    with none says its press releases and FDA news rated medium. "quiet" counts the news
    on file that is said in neither, so the note never calls a month without news.

    Slips are counted, not listed, since they move a date far more often than a price:
    one a trial, from its earliest date to its latest, and only where the readout was
    still ahead when it moved. A correction to a date already past is not a slip."""
    news = [it for it in changes or [] if isinstance(it, dict) and it.get("kind") != "market"]
    level = lambda it: it.get("significance") or "high"
    high = [it for it in news if level(it) == "high"]
    slips = [it for it in high if it.get("change_type") == "date_slip"]
    rest = [it for it in high if it.get("change_type") != "date_slip"]
    if not rest:
        rest = [it for it in news if level(it) == "medium" and any(
            str(it.get("change_type") or "").startswith(k) for k in _KI_NEWS_MEDIUM)]
    sups, ranked, seen, press = [], [], set(), []
    for it in rest:
        if it.get("change_type") == "press_approval" and _ki_is_approval(it.get("headline")):
            press.append(_ki_event_words(it, ticker).lower())
    for it in rest:
        ct = it.get("change_type") or ""
        if ct == "efficacy_supplement":
            m = re.match(r"^Efficacy supplement: (.+?) approved(?: (\d{4}-\d{2}-\d{2}))?",
                         _ki_headline(it, ticker))
            if m:
                sups.append((m.group(1), m.group(2) or str(it.get("date") or "")[:10]))
                continue
        if ct == "new_approval":
            m = re.match(r"^FDA approval: (.+?)(?: \(|$)", _ki_headline(it, ticker))
            if m and any(m.group(1).lower() in p for p in press):
                continue
        said = _ki_event_words(it, ticker)
        key = re.sub(r" \(\d{1,2} [A-Z][a-z]{2}\)$", "", said)
        if key in seen:
            continue
        seen.add(key)
        order = _KI_NEWS_ORDER.get(ct, 5)
        if ct == "press_approval" and not _ki_is_approval(it.get("headline")):
            order = 5
        ranked.append((order, str(it.get("date") or "")[:10], said,
                       _ki_event_words(it, ticker, cut=False), _ki_news_tone(it)))
    if sups:
        names = list(dict.fromkeys(name for name, _ in sups))
        days = sorted(d for _, d in sups if d)
        span = ""
        if days:
            lo, hi = _ki_short_day(days[0]), _ki_short_day(days[-1])
            if lo == hi:
                span = lo
            elif lo.split(" ")[1] == hi.split(" ")[1]:
                span = f"{lo.split(' ')[0]} to {hi}"
            else:
                span = f"{lo} to {hi}"
        said = (f"a new FDA indication for {names[0]}" if len(names) == 1 else
                f"new FDA indications for {_ki_join(names)}")
        said = f"{said} ({span})" if span else said
        ranked.append((_KI_NEWS_ORDER["efficacy_supplement"], days[-1] if days else "",
                       said, said, "up"))
    ranked.sort(key=lambda r: r[1], reverse=True)
    ranked.sort(key=lambda r: r[0])
    trials = {}
    for it in slips:
        m = re.search(r"(NCT\d{8}).*?slips (\d{4}-\d{2}(?:-\d{2})?) -> "
                      r"(\d{4}-\d{2}(?:-\d{2})?)", str(it.get("headline") or ""))
        if not m:
            trials.setdefault(id(it), None)
            continue
        nct, old, new = m.groups()
        seen_on = str(it.get("date") or "")[:10]
        if seen_on and old[:len(seen_on)] < seen_on[:len(old)]:
            continue                        # the date had passed: a correction, not a slip
        lo, hi = trials.get(nct) or (old, new)
        trials[nct] = (min(lo, old), max(hi, new))

    def span_days(pair):
        if not pair:
            return None
        try:
            a, b = (dt.date.fromisoformat(x if len(x) == 10 else x + "-01") for x in pair)
        except ValueError:
            return None
        return (b - a).days
    longest = max((d for d in (span_days(p) for p in trials.values()) if d is not None),
                  default=None)
    top = ranked[:limit]
    quiet = 0 if ranked else sum(1 for it in news if it.get("change_type") != "date_slip")
    return {"said": [r[2] for r in top], "full": [r[3] for r in top],
            "tones": [r[4] for r in top], "more": max(0, len(ranked) - limit),
            "slips": len(trials), "longest": longest, "quiet": quiet}


def _ki_brief(ticker: str, series: dict, rated: dict, call: dict, rel_3m: dict,
              rel_1y: dict, changes: list, sotp: dict, assets: dict, breaks: dict,
              events: list, risks: list, company: dict, cohort: dict, street: dict = None,
              modelled: bool = True, unrated: str = "", failed: str = "",
              rel_1m: float = None, expiries: dict = None,
              rating_failed: str = "", coverage: dict = None,
              business: list = None, news_said: int = _KI_NEWS_SAID) -> dict:
    """The morning note, reasoned from the figures the tab shows, in three paragraphs.
    1. The call, and what the price pays for against the model. 2. The trading, with the
    month's news set beside the move. 3. What the value rests on and what would break
    it, what the next readouts test, the nearest loss of exclusivity (the first row of the
    list beside it), and the standing against the cohort. {"paragraphs", "lead" (the
    opening sentence), "facts" (labelled lines for the note model, headlines whole)}.

    Judgement is drawn only from the figures: what the price pays for, whether a readout
    tests the pipeline or a product already sold, whether growth costs margin. A move is
    never given a cause: news is set beside it. ``coverage`` is the forecast's share of
    revenue it models; ``business`` the business row, read where nothing else is said."""
    series = series or {}
    rated = rated if isinstance(rated, dict) else {}
    s = sotp or {}
    paras, facts = [], []
    close = series.get("close") if series.get("close") is not None else rated.get("close")
    rated_ok = bool(rated.get("ok")) and rated.get("forward_12m") is not None
    tgt = (street or {}).get("value") if isinstance(street, dict) else None
    m, p, fut = (s.get("marketed") or {}), (s.get("pipeline") or {}), (s.get("future") or {})
    net = s.get("net_cash_per_share")

    def street_line():
        return (f"The street's mean target is {_ki_money(tgt)}, "
                f"{_ki_pct_words(tgt / close - 1)} on the {_ki_money(close)} close.")

    # 1. The call, and what the price pays for.
    p1 = []
    if modelled and rated_ok:
        fwd, up, word = rated["forward_12m"], rated.get("upside_12m") or 0.0, rated.get("rating")
        lead = (f"{word + ', with a' if word else 'A'} 12-month value of {_ki_money(fwd)}, "
                f"{abs(up) * 100:.1f}% {'above' if up >= 0 else 'below'} the "
                f"{_ki_money(close)} close.")
        p1.append(lead)
        facts.append(f"rating: {word or 'none'}; 12-month value {_ki_money(fwd)}, "
                     f"{_ki_signed_pct(up)} on the close {_ki_money(close)}")
        mid = rated.get("value_today")
        ahead = (fut.get("per_share") or 0.0) + (p.get("per_share") or 0.0)
        if m.get("n") == 0:
            # Nothing on sale is valued: a price-implied split would set the price against
            # net cash and the pipeline alone, which says nothing about the business.
            parts = [f"{what} ({_ki_money(v)}{' a share' if i == 0 else ''})"
                     for i, (v, what) in enumerate((x for x in (
                         (net if (net or 0) > 0 else None, "net cash"),
                         (p.get("per_share"), "the pipeline"),
                         (fut.get("per_share"), "future launches")) if x[0]))]
            debt = (f", less net debt of {_ki_money(-net)} a share" if net and net < 0 else "")
            p1.append("The model values none of the products on sale"
                      + (f": its value is {_ki_join(parts)}{debt}." if parts else "."))
            facts.append("the model values none of the products on sale")
        elif mid is not None and close and ahead > 0:
            base = mid - ahead
            implied = close - base
            what = ("the products on sale and net cash" if (net or 0) >= 0
                    else "the products on sale net of debt")
            if base <= 0:
                p1.append(f"Debt outweighs the products on sale, so the price is a bet on the "
                          f"pipeline and future launches, which the model puts at "
                          f"{_ki_money(ahead)} a share.")
            elif implied <= 0:
                p1.append(f"The price is below the {_ki_money(base)} of {what}, so it gives "
                          f"nothing for the {_ki_money(ahead)} the model puts on the pipeline "
                          "and future launches.")
            elif implied < ahead:
                p1.append(f"The price pays for {what} ({_ki_money(base)}) and "
                          f"{implied / ahead:.0%} of the model's {_ki_money(ahead)} for the "
                          f"pipeline and future launches, leaving {_ki_money(ahead - implied)} "
                          "a share unpriced.")
            else:
                p1.append(f"After {_ki_money(base)} for {what}, the price asks "
                          f"{_ki_money(implied)} for the pipeline and future launches, "
                          f"{implied / ahead:.1f} times the model's {_ki_money(ahead)}.")
            facts.append(f"today's value {_ki_money(mid)}: {what} "
                         f"{_ki_money(base)}, pipeline and future launches {_ki_money(ahead)}; "
                         f"the price implies {_ki_money(implied)} for the pipeline and launches")
        cover = (coverage or {}).get("share") if isinstance(coverage, dict) else None
        if cover is not None and m.get("n") and cover < 0.9:
            p1.append(f"The model covers {cover:.0%} of revenue, so {1 - cover:.0%} of it is "
                      "not in the value.")
            facts.append(f"the model covers {cover:.0%} of revenue")
    elif modelled and rating_failed:
        lead = (f"The rating did not load ({str(rating_failed).rstrip('.')}), so the note has "
                "no 12-month value to set against the price.")
        p1.append(lead)
        facts.append("rating: did not load")
    elif modelled:
        why = str(rated.get("reason") or unrated or "no value against the price is on file")
        lead = f"The model gives {ticker} no 12-month value ({why.rstrip('.')})."
        p1.append(lead)
        facts.append(f"no 12-month value: {why.rstrip('.')}")
        if tgt is not None and close:
            p1.append(street_line())
            facts.append(f"street target {_ki_money(tgt)}")
    elif failed:
        lead = (f"The forecast did not load ({str(failed).rstrip('.')}), so the note has no "
                "value to set against the price.")
        p1.append(lead)
        facts.append("forecast: did not load")
    elif tgt is not None:
        lead = f"{ticker} is not modelled."
        p1 += [lead, street_line() if close else
               f"The street's mean target is {_ki_money(tgt)}."]
        facts.append(f"not modelled; street target {_ki_money(tgt)}")
    else:
        biz_line = _ki_business_line(business)
        lead = (f"{ticker} is not modelled and no consensus is on file"
                + (", so the note reads the price and the business only." if biz_line else "."))
        p1.append(lead)
        facts.append("not modelled; no consensus on file")
    paras.append(" ".join(p1))

    # 2. The trading, with the month's news beside it.
    p2 = []
    day, month, year = series.get("day_move"), _ki_month_move(series), series.get("year_move")
    for label, v in (("day move", day), ("one-month move", month), ("one-year move", year)):
        if v is not None:
            facts.append(f"{label} {_ki_signed_pct(v)}")
    rel = _ki_rel_words(rel_1y)
    if rel:
        facts.append(f"one year against the sector: {rel}")
    if _ki_rel_words(rel_3m):
        facts.append(f"three months against the sector: {_ki_rel_words(rel_3m)}")
    if rel_1m is not None:
        facts.append(f"one month against the sector: {_ki_signed_pct(rel_1m)}")
    moves = []
    if month is not None:
        moves.append(f"{_ki_pct_words(month)} this month")
    if year is not None:
        words = _ki_pct_words(year)
        if month is not None and words.split(" ")[0] == _ki_pct_words(month).split(" ")[0] \
                != "flat":
            words = words.split(" ", 1)[1]
        moves.append(f"{words} over the year")
    news = _ki_month_news(changes, ticker, news_said)
    said, tones = news["said"], news.get("tones") or []
    items = "; ".join(said)
    if year is None:
        rel = ""                  # the year's relative is never set beside the month's move
    trade = (f"The shares are {_ki_join(moves)}" + (f", {rel}" if rel else "")) if moves else ""
    if trade:
        p2.append(trade + ".")
    if said:
        # "Despite" only where the shares also fell behind the sector: a fall the sector
        # shared is not one the news failed to stop.
        behind = rel_1m is None or rel_1m < -0.01
        ahead_of = rel_1m is None or rel_1m > -0.01
        good, bad = "up" in tones and "down" not in tones, "down" in tones
        if month is not None and month < -0.01 and good and behind:
            p2.append(f"The fall came despite the month's news: {items}.")
        elif month is not None and month > 0.01 and good and ahead_of:
            p2.append(f"The rise came with the month's news: {items}.")
        elif month is not None and month < -0.01 and bad:
            p2.append(f"The fall came alongside the month's news: {items}.")
        else:
            p2.append(f"The month's news: {items}.")
        facts += [f"news: {x}" for x in news["full"]]
    elif news.get("quiet"):
        if rel_1m is not None and round(abs(rel_1m) * 100) <= 2:
            p2.append("None of the month's company news is rated high, and the month's move "
                      "is the sector's.")
        elif rel_1m is not None:
            p2.append(f"None of the month's company news is rated high, in a month "
                      f"{_ki_points(round(abs(rel_1m) * 100))} "
                      f"{'ahead of' if rel_1m > 0 else 'behind'} the sector.")
        else:
            p2.append("None of the month's company news is rated high.")
        facts.append("news: none rated high this month")
    else:
        if rel_1m is not None and round(abs(rel_1m) * 100) <= 2:
            p2.append("With no company news on file, the month's move is the sector's.")
            facts.append("news: none on file; the month in line with the sector")
        elif rel_1m is not None:
            p2.append(f"No company news is on file for a month "
                      f"{_ki_points(round(abs(rel_1m) * 100))} "
                      f"{'ahead of' if rel_1m > 0 else 'behind'} the sector.")
            facts.append("news: none on file for the month")
        else:
            p2.append("No company news is on file for the month.")
            facts.append("news: none on file for the month")
    if news["slips"]:
        n, longest = news["slips"], news["longest"]
        first = _ki_count_word(n)
        span = _ki_span_words(longest)
        far = (f", by {span}" if n == 1 else f", the longest by {span}") if span else ""
        p2.append(f"{first[:1].upper() + first[1:]} late-stage "
                  f"{'readout' if n == 1 else 'readouts'} slipped{far}.")
        facts.append(f"late-stage readouts that slipped this month: {n}"
                     + (f", longest {span}" if span else ""))
    paras.append(" ".join(p2))

    # 3. What the value rests on and what breaks it, what comes next, where it stands.
    p3 = []
    loss = _ki_loss_words(expiries, risks, series.get("as_of") or "")
    named_loss = {r["asset"].lower() for r in loss.get("rows") or []}
    legs = []
    if modelled:
        rows_m = ((assets or {}).get("marketed") or {}).get("rows") or []
        rows_p = ((assets or {}).get("pipeline") or {}).get("rows") or []
        once = set()
        for r in rows_m[:2] + rows_p[:2]:
            if r.get("value") and r["name"].lower() not in once:
                once.add(r["name"].lower())
                legs.append(dict(r, leg="asset"))
        if fut.get("per_share"):
            legs.append({"leg": "launches", "value": fut["per_share"]})
        if net and net > 0:
            legs.append({"leg": "cash", "value": net})
        legs.sort(key=lambda r: -r["value"])
        parts = []
        for r in legs[:3]:
            if r["leg"] == "launches":
                parts.append(f"{_ki_money(r['value'])} a share of launches past the pipeline")
            elif r["leg"] == "cash":
                parts.append(f"{_ki_money(r['value'])} a share of net cash")
            elif r.get("kind") == "pipeline":
                parts.append(f"{r['name']} ({_ki_money(r['value'])} after its chance of "
                             "approval)")
            else:
                meta = r.get("meta") or ""
                # The loss of exclusivity said below is not said here too.
                held = ("" if r["name"].lower() in named_loss else
                        "past its LOE" if meta == "lapsed" else
                        f"protected to {meta}" if meta else "")
                parts.append(f"{r['name']} ({_ki_money(r['value'])}"
                             + (f", {held})" if held else ")"))
        rows = ((breaks or {}).get("rows") or [])[:1] if rated_ok else []
        clause = ""
        if rows and "meets" in (breaks or {}).get("head", ""):
            clause = "; the call holds while " + " and ".join(
                f"{r['name']} stays {'below' if r['glyph'] == '▲' else 'above'} {r['brk']} "
                f"({_ki_unit_once(r['model'], r['brk'])} now)" for r in rows)
        elif rows:
            clause = "; to justify the price the model would need " + " or ".join(
                f"{r['name']} at {r['brk']} against {_ki_unit_once(r['model'], r['brk'])} now"
                for r in rows)
        if parts and m.get("n") != 0:
            p3.append(f"The value rests on {_ki_join(parts)}{clause}.")
        elif clause:
            p3.append(clause[2:3].upper() + clause[3:] + ".")
        facts += [f"value rests on: {r.get('name') or r['leg']} {_ki_money(r['value'])}"
                  + (f", {r.get('meta')}" if r.get("meta") else "") for r in legs[:3]]
        facts += [f"break lever: {r['name']} {r['model']} now, breaks at {r['brk']}"
                  for r in rows]
    nxt = ""
    ahead_ev = [e for e in events or []
                if re.match(r"^\d{4}(-\d{2}){0,2}$", str(e.get("date") or ""))][:3]
    if ahead_ev:
        pipe_next = [e for e in ahead_ev if e.get("pipeline")]
        if not pipe_next:
            names = list(dict.fromkeys(e["asset"] for e in ahead_ev))
            by = ahead_ev[-1].get("date_text") or ahead_ev[-1].get("when")
            nxt = (f"the next readouts, {_ki_join(names)} (by {by}), extend products already "
                   "sold rather than test the pipeline" if len(names) > 1 else
                   f"the next readout, {names[0]} ({by}), extends a product already sold "
                   "rather than testing the pipeline")
        else:
            # Within the soonest month, the furthest phase: the one the value turns on.
            first = min(str(e.get("date"))[:7] for e in pipe_next)
            e = min((x for x in pipe_next if str(x.get("date"))[:7] == first),
                    key=lambda x: -1 if x.get("short") in _KI_REG_EVENTS.values() else
                    _KI_STAGE_RANK.get(re.sub(r" readout$", "", str(x.get("event") or "")), 5))
            row = next((r for r in ((assets or {}).get("pipeline") or {}).get("rows") or []
                        if r.get("name") == e["asset"]), {})
            value = row.get("value")
            in_legs = any(r.get("name") == e["asset"] for r in legs[:3])
            worth = ""
            if value and not in_legs:
                # Where this event is the compound's next gate, what passing it is worth.
                lost = _ki_money(row["failure"]) if row.get("failure") else "nil"
                worth = (f", worth {_ki_money(row['success'])} a share if it passes and {lost} "
                         f"if it fails, against {_ki_money(value)} now"
                         if row.get("success") is not None and _ki_gate_is(row, e)
                         else f", {_ki_money(value)} a share in the model")
            nxt = (f"the {e.get('event') or 'readout'} for {e['asset']} ({e.get('date_text')}) "
                   f"is the next test of the pipeline{worth}")
        facts += [f"readout: {e['asset']} {e.get('event')}"
                  + (f" in {e['indication']}" if e.get("indication") else "")
                  + f" ({e.get('date_text')})" + (", pipeline" if e.get("pipeline") else "")
                  for e in ahead_ev]
    lose = loss.get("text") or ""
    facts += loss.get("facts") or []
    if nxt and lose:
        p3.append(f"{nxt[:1].upper() + nxt[1:]}; {lose}.")
    elif nxt or lose:
        text = nxt or lose
        p3.append(text[:1].upper() + text[1:] + ".")
    co = company or {}
    if co.get("rank") is not None and (cohort or {}).get("noun"):
        g = _ki_metric(co, ("rev_growth",))
        om = _ki_metric(co, ("op_margin", "pretax_margin"))
        gp, mp = (g or {}).get("place"), (om or {}).get("place")
        mname = _KI_SHORT.get((om or {}).get("id"), "margin").lower()
        of = co.get("ranked_of") or cohort.get("n")
        runway = _ki_metric(co, ("runway",)) if co.get("cohort") == "clinical" else None
        tail, read = ", ".join(x for x in (f"growth {gp}" if gp else "",
                                           f"{mname} {mp}" if mp else "") if x), ""
        sg, sm = _ki_standing(g), _ki_standing(om, margin=True)
        if mp and "best" in mp and (om or {}).get("value") is not None and om["value"] < 0:
            mp = "negative"                 # a loss is never said as a "best" place
            tail = ", ".join(x for x in (f"growth {gp}" if gp else "", f"{mname} {mp}") if x)
        if gp and mp and sg and sm:
            if sg != sm:
                tail = f"growth {gp} but {mname} {mp}"
            read = {("good", "bad"): "growth bought at the cost of margin",
                    ("bad", "good"): "margin without the growth",
                    ("good", "good"): "strong on both",
                    ("bad", "bad"): "weak on both"}[(sg, sm)]
        if runway and runway.get("text") and not tail:
            tail = f"cash runway {runway['text']}" + (
                f", {runway['place']}" if runway.get("place") else "")
        p3.append(f"It ranks {_ki_ord(co['rank'])} of {of} {cohort['noun']}"
                  + (f": {tail}" if tail else "") + (f", {read}" if read else "") + ".")
        facts.append(f"peer rank: {_ki_ord(co['rank'])} of {of} {cohort['noun']}"
                     + (f"; {tail}" if tail else ""))
    if not p3:
        biz = _ki_business_line(business)
        if biz:
            p3.append(biz)
            facts.append(f"business: {biz.rstrip('.')}")
    if p3:
        paras.append(" ".join(p3))
    # A note past its length says one piece of news, not two: the rest is on News.
    if news_said > 1 and len(said) > 1 and \
            sum(len(x.split()) for x in paras) > _KI_NOTE_WORDS:
        return _ki_brief(ticker, series, rated, call, rel_3m, rel_1y, changes, sotp, assets,
                         breaks, events, risks, company, cohort, street, modelled, unrated,
                         failed, rel_1m, expiries, rating_failed, coverage, business,
                         news_said=1)
    return {"paragraphs": paras, "lead": lead, "facts": "\n".join(facts)}


def _ki_standing(metric: dict, margin: bool = False) -> str:
    """"good", "bad" or "" for a place in the cohort: the top third or the bottom third by
    the scorecard's own score, the middle third saying nothing. A loss is never a good
    margin, whatever its place."""
    m = metric or {}
    score = m.get("score")
    if margin and m.get("value") is not None and m["value"] < 0:
        return "bad"
    if score is None:
        return ""
    return "good" if score >= 200 / 3 else "bad" if score <= 100 / 3 else ""


def _ki_loss_words(expiries: dict, risks: list, as_of: str = "") -> dict:
    """The note's loss of exclusivity: the nearest, every product lost that day together,
    and the largest in the list where it is another and 10% of revenue or more.
    {"text", "facts", "rows": the products named}."""
    rows = list((expiries or {}).get("all") or (expiries or {}).get("rows") or []) \
        if expiries is not None else [
        dict(r, when=_ki_month(r.get("date"))) for r in risks or []
        if r.get("kind") == "exclusivity"][:1]
    if not rows:
        return {}

    def share_of(r):
        if r.get("share") is not None:
            return r["share"]
        try:
            return float(str(r.get("share_text")).rstrip("%")) / 100
        except (TypeError, ValueError):
            return None

    def when_of(r):
        when = str(r.get("when") or "")
        return ("on " if re.match(r"^\d{1,2} ", when) else "in ") + when

    def group(at):
        # Products lost the same day, each with a share: "together" adds what is known.
        same = [r for r in rows if r.get("date") == at.get("date") and r.get("when")
                and share_of(r) is not None]
        return same if at in same else [at] + same if share_of(at) is None else same or [at]

    def total_of(same):
        shares = [share_of(r) for r in same]
        return sum(x for x in shares if x is not None) \
            if any(x is not None for x in shares) else None

    # The first loss worth 5% of revenue, every product lost that day with it; where none
    # is, the nearest.
    first, same, lead = rows[0], group(rows[0]), "the nearest loss of exclusivity"
    for r in rows:
        g = group(r)
        if (total_of(g) or 0) >= _KI_LOSS_MATERIAL:
            if r is not rows[0] and g[0] is not same[0]:
                lead = (f"the first loss of exclusivity over "
                        f"{_KI_LOSS_MATERIAL:.0%} of revenue")
            first, same = g[0], g
            break
    names = _ki_join([_ki_soft_caps(r["asset"]) for r in same])
    total = total_of(same)
    pct = f"{total * 100:.1f}%" if total is not None else (first.get("share_text") or "")
    joint = " together" if len(same) > 1 else ""
    what = f"{names} {when_of(first)}"
    if total is not None and total >= 0.10:
        text = f"{lead}, {what}, is {pct} of revenue{joint}, the largest risk"
    elif pct:
        text = f"{lead}, {what}, is {pct} of revenue{joint}"
    else:
        text = f"{lead} is {what}"
    named = list(same)
    base = str(as_of or rows[0].get("date") or "")[:4]
    horizon = str(int(base) + _KI_LOSS_YEARS) if base.isdigit() else "9999"
    rest = [r for r in rows if r not in same and share_of(r) is not None
            and str(r.get("date") or "")[:4] <= horizon and r.get("date", "") > first.get("date", "")]
    big = max(rest, key=share_of, default=None)
    if big is not None and share_of(big) >= 0.15 and (total is None or share_of(big) > total):
        text = text.replace(", the largest risk", "")
        text += (f"; the largest, {_ki_soft_caps(big['asset'])} {when_of(big)}, is "
                 f"{share_of(big) * 100:.1f}%")
        named.append(big)
    facts = [f"risk: {r.get('asset')} loses exclusivity {r.get('when')}"
             + (f", {r.get('share_text')} of revenue" if r.get("share_text") else "")
             for r in named]
    return {"text": text, "facts": facts, "rows": named}


def _ki_business_line(business: list) -> str:
    """The business row as a sentence, for a note with nothing else to say of it:
    "It reports $2.3bn of revenue for FY2025, has 4 approved products and 12 compounds in
    trials, 3 of them late-stage." "" when the row holds nothing."""
    cells = {}
    for value, key, tone, _tip in business or []:
        if tone == "none":
            continue
        k = str(key)
        if "revenue" in k:
            cells["revenue"] = (value, k)
        elif "products on sale" in k or "approved products" in k:
            cells["products"] = (value, k)
        elif k.startswith("late-stage"):
            cells["late"] = value
        elif k.startswith("in trials"):
            cells["trials"] = value
    bits = []
    if "revenue" in cells:
        value, k = cells["revenue"]
        fy = re.match(r"^(FY\d{4})", k)
        growth = re.search(r"· ([+−-][\d.,]+%)", k)
        bits.append(f"reports {value} of revenue" + (f" for {fy.group(1)}" if fy else "")
                    + (f" ({growth.group(1)})" if growth else ""))
    has = []
    if "products" in cells:
        value, k = cells["products"]
        noun = "approved product" if "approved" in k else "product on sale"
        n = str(value).replace(",", "")
        has.append(f"{value} {noun if n == '1' else noun.replace('product', 'products')}")
    if cells.get("trials") and cells["trials"] != "0":
        late = cells.get("late")
        n = str(cells["trials"]).replace(",", "")
        has.append(f"{cells['trials']} {'compound' if n == '1' else 'compounds'} in trials"
                   + (f", {late} of them late-stage" if late and late != "0" else ""))
    if bits and has:
        return f"It {bits[0]}, with {_ki_join(has)}."
    if has:
        return f"It has {_ki_join(has)}."
    return f"It {bits[0]}." if bits else ""


def _ki_brief_html(brief: dict, label: str, model_body: str = None) -> str:
    """The note as it opens: the rewrite where one matches today's figures, a paragraph a
    line of it, else the briefing as built with its opening sentence in bold."""
    if model_body:
        paras = [html_escape(p.strip()) for p in re.split(r"\n+", model_body) if p.strip()]
    else:
        raw = (brief or {}).get("paragraphs") or []
        lead = (brief or {}).get("lead") or ""
        paras = [html_escape(p) for p in raw]
        if paras and lead and raw[0].startswith(lead):
            paras[0] = f"<b>{html_escape(lead)}</b>{html_escape(raw[0][len(lead):])}"
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (_ki_section_html("Morning note", label)
            + f'<div class="ki-brief">{body}</div>')


def _ki_loe_text(iso, basis: str = "", day: bool = False) -> str:
    """An exclusivity date to the precision its source gave. A filing's or the statute's
    year ("U.S. compound patent (2031)", "statutory floor (12y)", "10-K disclosure") stands
    in a year's last day for the year, so prints the year; a month's last day standing in
    for a month ("(2029-03)") prints the month; a filing that names the day, or a register
    date (Orange Book, Purple Book), prints the day with ``day``, else the month."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    if not m:
        return ""
    basis = str(basis or "")
    year, month = m.group(1), f"{m.group(1)}-{m.group(2)}"
    stated = re.search(r"statutory floor|10-K|10-Q|20-F|annual report|disclosure", basis, re.I)
    if f"({m.group(0)})" in basis:
        return _ki_day(iso) if day else _ki_month(iso)
    if (m.group(2), m.group(3)) == ("12", "31") and (f"({year})" in basis or stated):
        return year
    if f"({month})" in basis or stated or not day:
        return _ki_month(iso)
    return _ki_day(iso)


def _ki_due_ahead(due, today) -> bool:
    """A due date is still ahead: a month-only date by its month, a day by its day."""
    due = str(due or "")
    if not re.match(r"^\d{4}-\d{2}", due):
        return False
    return due[:7] >= today.isoformat()[:7] if len(due) < 10 else due[:10] >= today.isoformat()


def _ki_next_readout(programme: dict, today) -> dict:
    """A compound's next readout at the furthest phase it still has to read out, since that
    is the one its value turns on, else nothing: {"phase", "date", "text"}. Every such date
    is the registry's estimate of primary completion."""
    if _KI_NOT_A_COMPOUND.search(str((programme or {}).get("name") or "")):
        return {}
    until = f"{today.year + _KI_READOUT_YEARS}{today.isoformat()[4:]}"
    # A follow-up, extension or access study reads out nothing the value turns on, and a
    # date years past any launch the model holds is not a next test.
    studies = [s for s in (programme or {}).get("studies") or [] if isinstance(s, dict)
               and _ki_due_ahead(s.get("due"), today) and s.get("phase") in _KI_STAGE_RANK
               and str(s.get("due"))[:10] <= until
               and not _KI_NOT_A_TEST.search(str(s.get("title") or ""))
               and re.sub(r"[\s_]", "", str(s.get("status") or "")).lower()
               != "enrollingbyinvitation"]
    if not studies:
        return {}
    top = min(_KI_STAGE_RANK[s["phase"]] for s in studies)
    pick = min((s for s in studies if _KI_STAGE_RANK[s["phase"]] == top),
               key=lambda s: str(s["due"]))
    return {"phase": pick["phase"], "date": str(pick["due"])[:10], "nct_id": pick.get("nct_id"),
            "text": f"{_KI_PHASE_SHORT[pick['phase']]} · {_ki_month(pick['due'])}"}


def _ki_product_mix(record: dict) -> list:
    """[(product, share of the company's revenue)], largest first, measured against the
    year's reported revenue. Product rows of another year than the revenue, or adding to
    more than it, give no shares: a share of something else is not printed as one of the
    company's revenue."""
    rec = record if isinstance(record, dict) else {}
    products = (rec.get("detail") or {}).get("products") or {}
    fy0 = (rec.get("periods") or {}).get("FY0") or {}
    total = fy0.get("revenue_usd_m")
    if not total or str(products.get("fiscal_year")) not in str(fy0.get("label") or ""):
        return []
    mix = _ki_mix_segments(products, fy0, shown=10 ** 6)
    named = [x for x in mix if x["key"] != "rest"]
    if sum(x["value"] for x in named) > total:
        return []
    return [(x["label"], x["value"] / total) for x in named]


def _ki_product_shares(record: dict) -> dict:
    """Each product's share of the company's revenue, by lower-case name."""
    return {name.lower(): share for name, share in _ki_product_mix(record)}


def _ki_key_assets(verdict: dict, record: dict, programmes: list, exclusivities: list,
                   today, modelled: bool, shown: int = _KI_ASSETS_SHOWN,
                   development: dict = None) -> dict:
    """The five marketed products and the five pipeline compounds the value rests on most,
    with when each is decided: a product's loss of exclusivity, a compound's next readout.

    Modelled, both are ranked by value a share (a compound's after its chance of approval)
    on one scale, and the rest of each is one row whose count includes the ones valued at
    nothing. Not modelled, products are ranked by share of revenue, the rest of revenue one
    row, and compounds by furthest phase, then the readout nearest.

    A modelled compound with a next gate carries ``success``, what passing it is worth a
    share (the whisker), and its launch floor's ``flag`` (the underline). The gate, a gate
    that costs more to reach than it is worth (``development``, the company's next-gate
    costs) and the floor's message go in the row's one tooltip, and nowhere else."""
    v = verdict if isinstance(verdict, dict) else {}
    excl_id, excl_name = {}, {}
    for a in exclusivities or []:
        if isinstance(a, dict) and a.get("loe"):
            excl_id.setdefault(a.get("asset_id"), a)
            excl_name.setdefault(_ki_product(a.get("brand_name")).lower(), a)
    progs = {p.get("asset_id"): p for p in programmes or [] if isinstance(p, dict)}
    failing = {r.get("asset_id"): r for r in (development or {}).get("failing") or []
               if isinstance(r, dict)} if isinstance(development, dict) else {}
    shares = _ki_product_shares(record)
    since = today.isoformat()

    def loe_of(asset_id, name, lapsed=False, year=None):
        e = excl_id.get(asset_id) or excl_name.get(name.lower())
        if lapsed or (e and str(e["loe"])[:10] < since) or (
                not e and year and int(year) < today.year):
            return "lapsed", (e or {}).get("loe_basis") or ""
        if e:
            return _ki_loe_text(e["loe"], e.get("loe_basis")), e.get("loe_basis") or ""
        return (str(year) if year else ""), ("the model's LOE year" if year else "")

    marketed, pipeline = [], []
    rest_share = None
    if modelled:
        for a in v.get("modelled") or []:
            if not isinstance(a, dict) or not a.get("counted", True) \
                    or a.get("per_share") is None:
                continue
            name = _ki_product(a.get("name"))
            if a.get("is_marketed"):
                meta, basis = loe_of(a.get("asset_id"), name, a.get("loe_in_base"),
                                     a.get("loe_year"))
                share = shares.get(name.lower())
                tip = " · ".join(x for x in (
                    name, f"{share:.1%} of revenue" if share is not None else "",
                    f"exclusivity: {basis}" if basis else "") if x)
                marketed.append({"name": name, "value": a["per_share"], "meta": meta,
                                 "text": _ki_money(a["per_share"]), "tip": tip,
                                 "kind": "marketed"})
            else:
                nxt = _ki_next_readout(progs.get(a.get("asset_id")), today)
                gate = _ki_gate(a, failing.get(a.get("asset_id")))
                flag = _launch_flag(a.get("launch"))
                tip = " · ".join(x for x in (
                    name, f"chance of approval {a['pos']:.0%}" if a.get("pos") is not None
                    else "", f"next readout {nxt['nct_id']}, registry estimate"
                    if nxt.get("nct_id") else "", gate.get("tip"),
                    (a.get("launch") or {}).get("message") if flag else "") if x)
                pipeline.append({"name": name, "value": a["per_share"],
                                 "meta": nxt.get("text") or "", "text": _ki_money(a["per_share"]),
                                 "tip": tip, "kind": "pipeline", "success": gate.get("success"),
                                 "failure": gate.get("failure"), "gate": gate.get("event"),
                                 "flag": flag})
        marketed.sort(key=lambda r: -r["value"])
        pipeline.sort(key=lambda r: -r["value"])
        if not pipeline:
            pipeline = _ki_programme_rows(programmes, today)
        s = v.get("sotp") or {}
        totals = {"marketed": (s.get("marketed") or {}).get("per_share"),
                  "pipeline": (s.get("pipeline") or {}).get("per_share")}
    else:
        for name, share in _ki_product_mix(record):
            meta, basis = loe_of(None, name)
            marketed.append({"name": name, "value": share, "meta": meta,
                             "text": f"{share:.0%}" if share >= 0.01 else "<1%",
                             "kind": "marketed",
                             "tip": " · ".join(x for x in (
                                 name, f"{share:.1%} of revenue",
                                 f"exclusivity: {basis}" if basis else "") if x)})
        if marketed:
            rest_share = max(0.0, 1.0 - sum(r["value"] for r in marketed[:shown]))
        else:
            # No revenue split by product on file: the approved products and their losses
            # of exclusivity, soonest first, rather than a table that says there are none.
            seen = set()
            for e in sorted((x for x in exclusivities or [] if isinstance(x, dict)
                             and x.get("brand_name")), key=lambda x: str(x.get("loe") or "9")):
                name = _ki_product(e["brand_name"])
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                meta, basis = loe_of(e.get("asset_id"), name)
                marketed.append({"name": name, "value": None, "meta": meta, "text": "",
                                 "kind": "marketed", "tip": " · ".join(
                                     x for x in (name, "no revenue split by product on file",
                                                 f"exclusivity: {basis}" if basis else "")
                                     if x)})
        pipeline = _ki_programme_rows(programmes, today)
        totals = {"marketed": None, "pipeline": None}

    def part(rows, kind):
        top = rows[:shown]
        more_n = len(rows) - len(top)
        more_value = None
        if more_n and totals.get(kind) is not None and all(
                r.get("value") is not None for r in top):
            more_value = totals[kind] - sum(r["value"] for r in top)
        out = {"rows": top, "more_n": more_n, "more_value": more_value}
        if kind == "marketed" and rest_share is not None:
            out.update(more_n=0, more_value=None, rest=rest_share)
        return out

    shown_rows = marketed[:shown] + pipeline[:shown]
    # The scale takes the whiskers too, so a success value is never clipped at the edge.
    return {"modelled": modelled, "marketed": part(marketed, "marketed"),
            "pipeline": part(pipeline, "pipeline"),
            "top": max([r["value"] for r in shown_rows if r.get("value")]
                       + [r["success"] for r in shown_rows if r.get("success")] or [1.0])}


def _ki_gate(line: dict, failing: dict = None) -> dict:
    """A pipeline line's next gate as Key assets reads it: ``success``, its value a share
    if the gate passes; ``event``, the gate's label and month, so the note names the same
    event; and ``tip``, the gate in words, then the cost fact where reaching it costs more
    than it is worth risked (``failing``, the line's row in the company's next-gate
    costs). ``failure`` is nil unless stated legs on file say otherwise. {} where the
    line has no gate."""
    g = (line or {}).get("gate") if isinstance((line or {}).get("gate"), dict) else {}
    success = (line or {}).get("per_share_success")
    if success is None:
        success = g.get("per_share_success")
    if not g or success is None:
        return {}
    failure = 0.0
    if g.get("legs_basis") == "stated":
        failure = (line or {}).get("per_share_failure")
        failure = g.get("per_share_failure") if failure is None else failure
        failure = failure if failure is not None and failure >= 0.005 else 0.0
    lost = _ki_money(failure) if failure else "nil"
    label = g.get("label") or "next gate"
    date = str(g.get("date") or "")
    if g.get("gate") == "nda_to_approval":
        when = f" (decision due {_ki_day(date)})" if date else ""
        words = (f"{label}{when}: {_ki_money(success)} a share if the FDA approves it, "
                 f"{lost} if it does not")
    else:
        when = ("" if not date else f" due since {_ki_month(date)}" if g.get("due")
                else f" est. {_ki_month(date)}")
        words = f"{label}{when}: {_ki_money(success)} a share if it passes, {lost} if it fails"
    words += (", from the success and failure legs on file" if g.get("legs_basis") == "stated"
              else ", on gate odds implied by the stated PoS"
              if (g.get("evidence") or {}).get("p_gate") == "implied"
              else ", derived from published transition rates")
    fg = (failing or {}).get("gate") if isinstance((failing or {}).get("gate"), dict) else {}
    if fg.get("funds") is False and fg.get("breakeven_p") is not None:
        be, p = fg["breakeven_p"], fg.get("p")
        reach = f"reaching the {fg.get('label') or label}"
        words += (f" · {reach} costs more than passing it is worth" if be > 1 or p is None
                  else f" · {reach} costs more than it is worth risked: it needs a "
                       f"{be:.0%} chance against the {p:.0%} on file")
        words += ", at published trial costs in 2018 prices"
    # The month the note's event has to fall in to be this gate; none for an FDA decision
    # with no date on file, which any decision on the compound is.
    return {"success": success, "failure": failure, "tip": words,
            "event": {"label": label, "month": date[:7]}}


def _ki_gate_is(row: dict, event: dict) -> bool:
    """Whether a readout or decision in the note is the compound's next gate: the same kind
    of event, in the gate's month. An FDA decision with no date on file is any decision on
    the compound; a readout gate with no date has no study dated at it, so a dated readout
    is another study and never the gate. A gate already due is never an event ahead, so
    its legs are never said of a later study."""
    gate = (row or {}).get("gate") or {}
    label, what = gate.get("label"), str((event or {}).get("event") or "")
    kinds = {"Phase 3 readout": ("Phase 3 readout", "Phase 2/3 readout"),
             "Phase 2 readout": ("Phase 2 readout", "Phase 2/3 readout"),
             "FDA decision": ("PDUFA date", "regulatory decision")}.get(label, ())
    if what not in kinds:
        return False
    month = gate.get("month") or ""
    if not month:
        return label == "FDA decision"
    return str((event or {}).get("date") or "")[:7] == month


def _ki_programme_rows(programmes: list, today) -> list:
    """Compounds in trials with no value on file, furthest phase first, then the readout
    nearest: what Key assets lists where the model counts none."""
    rows = []
    for p in programmes or []:
        if not isinstance(p, dict) or p.get("stage") not in _KI_STAGE_RANK \
                or _KI_NOT_A_COMPOUND.search(str(p.get("name") or "")):
            continue
        nxt = _ki_next_readout(p, today)
        rows.append({"name": _ki_product(p.get("name")), "value": None,
                     "text": _KI_PHASE_SHORT[p["stage"]],
                     "meta": _ki_month(nxt["date"]) if nxt else "",
                     "rank": (_KI_STAGE_RANK[p["stage"]], nxt.get("date") or "9999"),
                     "tip": " · ".join(x for x in (
                         p.get("name"), p.get("area"),
                         f"{p.get('trials')} trials" if p.get("trials") else "",
                         "readout a registry estimate" if nxt else "") if x),
                     "kind": "pipeline"})
    rows.sort(key=lambda r: r["rank"])
    return rows


def _ki_key_assets_html(assets: dict, failed: str = "") -> str:
    """Two short tables on one scale: what each holds, and when it is decided. ``failed``
    is the comps read's error, said in place of an empty product table."""
    a = assets or {}
    modelled = a.get("modelled")
    top = a.get("top") or 1.0
    out = []
    for kind in ("marketed", "pipeline"):
        part = a.get(kind) or {}
        rows = part.get("rows") or []
        valued = any(r.get("value") is not None for r in rows)
        title = ("Marketed" if kind == "marketed" else
                 "Pipeline, risked" if modelled and valued else "Pipeline")
        if not rows:
            none = (f"The scorecard did not load: {str(failed).rstrip('.')}."
                    if failed and kind == "marketed" and not modelled else
                    "No product revenue on file." if kind == "marketed"
                    else "No compound in trials on file.")
            out.append(f'<div class="ki-ka-h"><span>{html_escape(title)}</span></div>'
                       f'<div class="ki-ka none">{html_escape(none)}</div>')
            continue
        value_head = ("value" if modelled and valued else
                      "" if not any(r.get("text") for r in rows) else
                      "of revenue" if kind == "marketed" else "phase")
        meta_head = "LOE" if kind == "marketed" else "readout, est."
        out.append(f'<div class="ki-ka-h"><span>{html_escape(title)}</span><span></span>'
                   f'<span class="v">{html_escape(value_head)}</span>'
                   f'<span>{html_escape(meta_head)}</span></div>')
        for r in rows:
            bar = ""
            if r.get("value") is not None:
                w = max(r["value"] / top * 100, 1.5)
                bar = f'<i class="{kind}" style="width:{w:.1f}%"></i>'
                # A hairline from the bar's end to what the compound is worth if its next
                # gate passes, in the row's own height.
                if r.get("success") is not None and r["success"] > r["value"]:
                    end = min(r["success"] / top * 100, 100.0)
                    bar += (f'<i class="whisker" style="left:{w:.1f}%;'
                            f'width:{max(end - w, 0.5):.1f}%"></i>')
            # The launch floor's flag underlines the figure; its words are in the tooltip.
            text = _launch_flagged(html_escape(r.get("text") or ""),
                                   {"flag": r.get("flag")}, tip=False)
            out.append(f'<div class="ki-ka" title="{_ki_attr(r.get("tip"))}">'
                       f'<span class="n {kind}">{html_escape(r["name"])}</span>'
                       f'<span class="b">{bar}</span>'
                       f'<span class="v">{text}</span>'
                       f'<span class="m">{html_escape(r.get("meta") or _KI_EMPTY)}</span></div>')
        if part.get("rest") is not None:
            out.append(f'<div class="ki-ka more"><span class="n">rest of revenue</span>'
                       f'<span class="b"></span><span class="v">{part["rest"]:.0%}</span>'
                       f'<span class="m"></span></div>')
        elif part.get("more_n"):
            more = part.get("more_value")
            more_text = "" if more is None else _ki_money(more)
            out.append(f'<div class="ki-ka more"><span class="n">{part["more_n"]} more</span>'
                       f'<span class="b"></span><span class="v">{more_text}</span>'
                       f'<span class="m"></span></div>')
    return '<div class="ki-assets">' + "".join(out) + "</div>"


def _ki_readouts(items: list, today, prose=None, shown: int = _KI_READOUTS_SHOWN,
                 min_pct: float = 0.01, programmes: list = None) -> dict:
    """The dated events that can move the value, soonest first: regulatory dates, late-
    stage readouts, a Phase 2 or later readout of an unapproved compound the model does
    not value, and any readout of one worth ``min_pct`` of the price. {"rows", "more",
    "total"}; each row says what reads out, for what, and when, and marks every date the
    company has not stated or confirmed as an estimate."""
    prose = prose or (lambda s: s)
    rows = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        iso = str(it.get("date") or "")
        if not _ki_due_ahead(iso, today):
            continue
        kind = str(it.get("kind") or "").lower()
        asset = it.get("asset") if isinstance(it.get("asset"), dict) else {}
        val = it.get("asset_value") if isinstance(it.get("asset_value"), dict) else {}
        reg = it.get("regulatory") is True or kind in _KI_REG_EVENTS
        late = "readout" in kind and it.get("phase") in ("Phase 3", "Phase 2/3")
        unapproved = (not asset.get("is_marketed")) if asset else reg
        unvalued_mid = (unapproved and not val and "readout" in kind
                        and _KI_STAGE_RANK.get(it.get("phase"), 9) <= _KI_STAGE_RANK["Phase 2"])
        big = unapproved and (val.get("pct_of_price") or 0) >= min_pct
        if not (reg or late or big or unvalued_mid):
            continue
        name = _ki_product(asset.get("name"))
        if _KI_NOT_A_COMPOUND.search(name):
            continue
        if not name:
            title = re.sub(r"^Phase [0-9/]+,\s*", "", str(it.get("title") or ""))
            name = _ki_product(re.split(r",|\s(?:PDUFA|AdCom|EMA|BLA|NDA)\b",
                                        title)[0].strip(" ,.;:")[:40])
        if reg:
            short = _KI_REG_EVENTS.get(kind, "decision")
            event = {"PDUFA": "PDUFA date", "AdCom": "advisory committee",
                     "EMA": "EMA decision"}.get(short, "regulatory decision")
        else:
            short = _KI_PHASE_SHORT.get(it.get("phase"), "readout")
            event = f"{it['phase']} readout" if it.get("phase") else "data readout"
        ind = (it.get("indication") or {}).get("name") if isinstance(
            it.get("indication"), dict) else None
        est = it.get("date_confidence") not in ("confirmed", "stated")
        prec = it.get("date_precision")
        mo = int(iso[5:7])
        if prec == "quarter":
            when = f"Q{(mo + 2) // 3} {iso[:4]}"
        elif prec == "half":
            when = f"H{1 if mo <= 6 else 2} {iso[:4]}"
        elif prec == "day" and not est and len(iso) >= 10:
            when = _ki_day(iso[:10])
        else:
            when = _ki_month(iso)
        rows.append({"date": iso[:10], "when": when, "estimated": est,
                     "date_text": f"est. {when}" if est else when,
                     "asset": name, "pipeline": unapproved, "short": short,
                     "event": event, "indication": prose(ind) if ind else None,
                     "tip": " · ".join(x for x in (it.get("title"), it.get("nct_id"))
                                       if x)})
    rows.sort(key=lambda r: (r["date"], r["asset"]))
    # Two trials of one compound reading out in a month are one row, its indications
    # joined: "Ph 3 · excessive somnolence, binge-eating disorder".
    once, kept = {}, []
    for r in rows:
        key = (r["asset"].lower(), r["date"][:7], r["short"])
        if key not in once:
            once[key] = r
            kept.append(r)
        elif r.get("indication") and r["indication"] not in str(once[key].get("indication")):
            first = once[key]
            first["indication"] = (f"{first['indication']}, {r['indication']}"
                                   if first.get("indication") else r["indication"])
            first["estimated"] = first["estimated"] or r["estimated"]
    rows = kept
    # Short of a full list inside the catalysts' twelve months, the registry's next readout
    # of each compound past them, so a company with its readouts further out still has some.
    if len(rows) < shown and programmes:
        last = max([r["date"] for r in rows] + [today.isoformat()])
        named = {r["asset"].lower() for r in rows}
        nexts = [(p, _ki_next_readout(p, today) if isinstance(p, dict) else {})
                 for p in programmes]
        # A Phase 1 study reads out nothing the value turns on where a later one exists,
        # and a study in healthy volunteers tests no disease.
        later = any(n and _KI_STAGE_RANK[n["phase"]] <= _KI_STAGE_RANK["Phase 2"]
                    for _, n in nexts)
        extra = []
        for p, nxt in nexts:
            name = _ki_product((p or {}).get("name"))
            if not nxt or nxt["date"] <= last or name.lower() in named:
                continue
            if (later and _KI_STAGE_RANK[nxt["phase"]] > _KI_STAGE_RANK["Phase 2"]) \
                    or "healthy volunteer" in str((p or {}).get("area") or "").lower():
                continue
            when = _ki_month(nxt["date"])
            extra.append({"date": nxt["date"], "when": when, "estimated": True,
                          "date_text": f"est. {when}", "asset": name, "pipeline": True,
                          "short": _KI_PHASE_SHORT[nxt["phase"]],
                          "event": f"{nxt['phase']} readout", "indication": None,
                          "area": (str(p.get("area") or "").lower()
                                   if p.get("area") not in (None, "", "Other") else None),
                          "tip": " · ".join(x for x in (p.get("name"), nxt.get("nct_id"),
                                                        "primary completion, registry estimate")
                                            if x)})
        extra.sort(key=lambda r: (r["date"], r["asset"]))
        rows += extra[:shown - len(rows)]
    return {"rows": rows[:shown], "more": max(0, len(rows) - shown), "total": len(rows)}


def _ki_readouts_html(readouts: dict) -> str:
    rows = (readouts or {}).get("rows") or []
    if not rows:
        return ('<div class="ki-empty">No late-stage readout or regulatory date is on file '
                'for the next 12 months.</div>')
    out = []
    for r in rows:
        mark = "○" if r.get("estimated") else "●"
        what = " · ".join(x for x in (r.get("short"), r.get("indication") or r.get("area"))
                          if x)
        out.append(f'<div class="ki-ro" title="{_ki_attr(r.get("tip"))}">'
                   f'<span class="d"><i>{mark}</i>{html_escape(r["when"])}</span>'
                   f'<span class="n{" pipeline" if r.get("pipeline") else ""}">'
                   f'{html_escape(r["asset"])}</span>'
                   f'<span class="w">{html_escape(what)}</span></div>')
    if (readouts or {}).get("more"):
        out.append(f'<div class="ki-ro more">{readouts["more"]} more on Catalysts</div>')
    return '<div class="ki-list">' + "".join(out) + "</div>"


def _ki_expiry_kind(basis: str) -> str:
    """What an exclusivity date is, in two words: a patent, the 12-year biologic term, an
    orphan term, a settlement, or the model's own year."""
    b = str(basis or "").lower()
    if "model" in b:
        return "model year"
    if "settle" in b:
        return "settlement"
    if "orphan" in b:
        return "orphan"
    if "12y" in b or "reference product" in b or "biologic" in b or "floor" in b:
        return "12y biologic"
    if "patent" in b:
        return "patent"
    return "exclusivity"


def _ki_expiries(exclusivities: list, verdict: dict, record: dict, losses: list, today,
                 modelled: bool, shown: int = _KI_EXPIRIES_SHOWN) -> dict:
    """The next losses of exclusivity, soonest first, of the products that matter: one the
    model values or one with revenue on file. A company with neither lists every one.

    The scorecard's own loss date wins where it has the product, so the list and the
    scorecard agree. A product the model already carries past its LOE is never listed, and
    an orphan term is never taken for the product's loss of exclusivity: it guards one
    indication, not the molecule. {"rows", "more"}; each row: the date at its source's
    precision, product, kind, share of revenue (text and number), value a share."""
    since = today.isoformat()
    values, gone, model_year = {}, set(), {}
    if modelled:
        for a in (verdict or {}).get("modelled") or []:
            if not isinstance(a, dict) or not a.get("is_marketed"):
                continue
            if a.get("loe_in_base") or (a.get("loe_year") and int(a["loe_year"]) < today.year):
                gone.add(a.get("asset_id"))
            if a.get("counted", True) and a.get("per_share"):
                values[a.get("asset_id")] = a["per_share"]
    shares = _ki_product_shares(record)
    lost = {r.get("asset_id"): r for r in losses or [] if isinstance(r, dict) and r.get("date")}
    cands, seen = [], set()
    rows_in = []
    for e in exclusivities or []:
        if not isinstance(e, dict) or not e.get("loe"):
            continue
        sc = lost.get(e.get("asset_id"))
        iso, basis = ((str(sc["date"])[:10], sc.get("basis") or e.get("loe_basis"))
                      if sc else (str(e["loe"])[:10], e.get("loe_basis")))
        rows_in.append((iso, basis, e))
    # A loss the scorecard holds that the exclusivity file does not (a product whose
    # exclusivity is read from its filer) is listed all the same.
    held = {e.get("asset_id") for e in exclusivities or [] if isinstance(e, dict)}
    for aid, sc in lost.items():
        if aid not in held and sc.get("asset"):
            rows_in.append((str(sc["date"])[:10], sc.get("basis") or "",
                            {"asset_id": aid, "brand_name": sc["asset"]}))
    for iso, basis, e in sorted(rows_in, key=lambda x: x[0]):
        name = _ki_soft_caps(_ki_product(e.get("brand_name") or e.get("generic_name")))
        if not name or name.lower() in seen:
            continue
        if e.get("asset_id") in gone:
            seen.add(name.lower())      # a lapsed product is never listed, not even later
            continue
        # A date already gone, or an orphan term (it guards one indication, not the
        # molecule), says nothing of the product's own loss: a later row still can.
        if iso < since or _ki_expiry_kind(basis) == "orphan":
            continue
        seen.add(name.lower())
        share = shares.get(name.lower())
        sc = lost.get(e.get("asset_id")) or {}
        share_text = sc.get("share_text") or (f"{share * 100:.1f}%" if share is not None else "")
        share_num = sc.get("share_of_revenue") if sc.get("share_of_revenue") is not None \
            else share
        cands.append({"date": iso, "when": _ki_loe_text(iso, basis, day=True),
                      "asset": name, "kind": _ki_expiry_kind(basis),
                      "share_text": share_text, "share": share_num,
                      "value": values.get(e.get("asset_id")),
                      "tip": " · ".join(x for x in (name, basis) if x)})
    # A modelled product the exclusivity file does not hold (a CBER biologic) keeps the
    # model's own LOE year.
    for a in (verdict or {}).get("modelled") or [] if modelled else []:
        if not isinstance(a, dict) or not a.get("is_marketed") or a.get("loe_in_base") \
                or not a.get("loe_year") or not a.get("per_share"):
            continue
        name = _ki_product(a.get("name"))
        # A year alone is past for this year too: it cannot say whether the day has gone.
        if name.lower() in seen or int(a["loe_year"]) <= today.year:
            continue
        seen.add(name.lower())
        share = shares.get(name.lower())
        cands.append({"date": f"{a['loe_year']}-12-31", "when": str(a["loe_year"]),
                      "asset": name, "kind": "model year", "value": a["per_share"],
                      "share_text": f"{share * 100:.1f}%" if share is not None else "",
                      "share": share, "tip": f"{name} · the model's LOE year"})
    cands.sort(key=lambda c: c["date"])
    material = [c for c in cands if c["value"] is not None or c["share_text"]]
    rows = material or cands
    return {"rows": rows[:shown], "more": max(0, len(rows) - shown), "all": rows}


def _ki_expiries_html(expiries: dict, today=None) -> str:
    rows = (expiries or {}).get("rows") or []
    # A loss inside two years is the one to watch: only its date is in the down colour.
    near = (f"{today.year + 2}{today.isoformat()[4:]}" if today else "")
    if not rows:
        return '<div class="ki-empty">No loss of exclusivity ahead is on file.</div>'
    out = []
    for r in rows:
        what = " · ".join(x for x in (r.get("kind"),
                                      f"{r['share_text']} of revenue" if r.get("share_text")
                                      else "") if x)
        value = _ki_money(r["value"]) if r.get("value") is not None else ""
        out.append(f'<div class="ki-ex" title="{_ki_attr(r.get("tip"))}">'
                   f'<span class="d{" near" if near and r.get("date", "") <= near else ""}">'
                   f'{html_escape(r["when"])}</span>'
                   f'<span class="n">{html_escape(r["asset"])}</span>'
                   f'<span class="w">{html_escape(what)}</span>'
                   f'<span class="v">{html_escape(value)}</span></div>')
    if (expiries or {}).get("more"):
        out.append(f'<div class="ki-ex more">{expiries["more"]} more on Portfolio</div>')
    return '<div class="ki-list">' + "".join(out) + "</div>"


def _ki_cohort_table(board: dict, ticker: str, record: dict, verdict: dict) -> list:
    """The business against its cohort as one table, in three groups: each measure's value,
    its place, and every peer on a strip where right is better. [{"title", "rows"}]."""
    board = board if isinstance(board, dict) else {}
    me = (board.get("companies") or {}).get(ticker) or {}
    rec = record if isinstance(record, dict) else {}
    ver = verdict if isinstance(verdict, dict) else {}
    if me.get("cohort") == "clinical":
        groups = (("Funding", (("runway",), ("share_change",))),
                  ("Pipeline", (("mid_late_compounds",), ("trial_conc",))))
    else:
        bal = (("runway",) if me.get("cohort") == "commercial" and not _ki_metric(
            me, ("nd_ocf", "net_cash_rev")) else ("nd_ocf", "net_cash_rev"))
        groups = (("Financials", (("rev_growth",), ("op_margin", "pretax_margin", "fcf_margin"),
                                  bal)),
                  ("Pipeline", (("late_compounds",), ("late_per_rev",))),
                  ("Marketed", (("loe_years",), ("top_product",), ("fresh_share",))))
    # What a group leaves unsaid: the revenue the measures are of, the compounds in trials.
    sub = {}
    reported = ver.get("reported_revenue") or []
    last = reported[-1] if reported else None
    if last and last.get("value"):
        fig, unit = _ki_level(last["value"])
        cur = rec.get("row_currency") or rec.get("reporting_currency") or ""
        sub["Financials"] = f"{fig}{unit} {cur} revenue, FY{last['fiscal_year']}".replace(
            "  ", " ")
    else:
        fy0 = (rec.get("periods") or {}).get("FY0") or {}
        if fy0.get("revenue_usd_m"):
            fig, unit = _ki_level(fy0["revenue_usd_m"])
            sub["Financials"] = f"{fig}{unit} USD revenue, {fy0.get('label') or ''}".strip(" ,")
    pipe = ((rec.get("detail") or {}).get("pipeline") or {}).get("compounds") or {}
    count = sum(v for k, v in pipe.items() if isinstance(v, (int, float)) and k in _KI_STAGE_RANK)
    if count:
        sub["Pipeline"] = f"{count:,.0f} {'compound' if count == 1 else 'compounds'} in trials"
    out = []
    for title, ids_list in groups:
        rows = []
        for ids in ids_list:
            m = _ki_metric(me, ids)
            if m:
                row = _ki_peer_row(board, ticker, m)
                if row.get("text"):
                    row["text"] = (str(row["text"]).replace(" years", "y")
                                   .replace(" year", "y").replace(" months", "mo"))
                rows.append(row)
        if rows:
            out.append({"title": title, "sub": sub.get(title, ""), "rows": rows})
    return out


def _ki_cohort_html(groups: list, strips: dict) -> str:
    """The table: a caps group label, then a row a measure, its strip from ``strips`` by id."""
    out = []
    for i, g in enumerate(groups or []):
        sub = f'<i>{html_escape(g["sub"])}</i>' if g.get("sub") else ""
        # Said once, at the top right of the table: the chip above has no room for it.
        key = '<b class="rb">right is better</b>' if i == 0 else ""
        out.append(f'<div class="ki-ct-g">{html_escape(g["title"])}{sub}{key}</div>')
        if all(r.get("value") is None for r in g["rows"]):
            # A group with no measure on file is one line saying why, not rows of dots.
            out.append(f'<div class="ki-ct none">'
                       f'{html_escape(g["rows"][0].get("reason") or "no value on file")}'
                       f'</div>')
            continue
        for r in g["rows"]:
            name = (f'<span class="l" title="{_ki_attr(r["full_label"])}">'
                    f'{html_escape(r["label"])}</span>')
            if r.get("value") is None:
                out.append(f'<div class="ki-ct" title="{_ki_attr(r.get("reason"))}">{name}'
                           f'<span class="s"></span><span class="v none">{_KI_EMPTY}</span>'
                           f'<span class="p"></span></div>')
                continue
            out.append(f'<div class="ki-ct">{name}<span class="s">{strips.get(r["id"]) or ""}'
                       f'</span><span class="v">{html_escape(r.get("text") or "")}</span>'
                       f'<span class="p {r.get("tone") or ""}">'
                       f'{html_escape(r.get("place_text") or "")}</span></div>')
    return '<div class="ki-cohort">' + "".join(out) + "</div>"


def _ki_forecast_state(verdict, error=None) -> str:
    """"modelled", "not_modelled" or "failed": a read that failed is never said to be a
    company with nothing modelled."""
    if error:
        return "failed"
    v = verdict if isinstance(verdict, dict) else {}
    if (v.get("ok") and (v.get("per_share") or v.get("streams") or v.get("placeholders"))
            and ((v.get("sotp") or {}).get("marketed") or {}).get("per_share") is not None):
        return "modelled"
    return "not_modelled"


def _ki_section_html(label: str, basis: str = "") -> str:
    """The same markup section() writes, for a section inside a band."""
    chip = f'<span class="sec-basis">{html_escape(basis)}</span>' if basis else ""
    return f'<div class="sec ki-sec"><span class="sec-label">{html_escape(label)}</span>{chip}</div>'


def _ki_band_html(cells: list, layout: str = "c2") -> str:
    """A band: one grid, each cell its own block of markup. No blank lines, so markdown
    cannot break the HTML."""
    inner = "".join(f'<div class="ki-cell">{c}</div>' for c in cells)
    return re.sub(r"\n\s*", "", f'<div class="ki-band {layout}">{inner}</div>')


def _ki_changes(feed, ticker: str, today, levels: tuple = ("high",)) -> list:
    """The company's changes rated high (or of ``levels``) in the last 30 days, newest
    first. Restatements and rate moves are left to News, and what is dated ahead
    (catalysts, exclusivity) to the readouts and the expiries."""
    since = (today - dt.timedelta(days=_KI_CHANGE_DAYS)).isoformat()
    until = today.isoformat()
    rows = [it for it in feed or [] if isinstance(it, dict)
            and it.get("significance") in levels
            and it.get("kind") not in _KI_AHEAD_KINDS
            and it.get("change_type") not in _KI_LEFT_TO_NEWS
            and (it.get("ticker") or "") == ticker
            and since <= str(it.get("date") or "")[:10] <= until]
    rows.sort(key=lambda it: (str(it.get("date") or "")[:10],
                              str(it.get("detected_at") or it.get("date") or "")),
              reverse=True)
    once, kept = set(), []
    for it in rows:                 # the feed can carry one change twice
        key = (str(it.get("date") or "")[:10], str(it.get("headline") or "").strip().lower())
        if key not in once:
            once.add(key)
            kept.append(it)
    return kept


def _ki_headline(item, ticker: str) -> str:
    """The change's headline without the leading ticker, which the page already names."""
    text = re.sub(r"\s+", " ", str(item.get("headline") or "")).strip()
    if ticker and text.startswith(ticker + " "):
        text = text[len(ticker) + 1:]
    return text[:1].upper() + text[1:]


def _ki_change_row(item, ticker: str) -> str:
    """The feed's own row markup, as the drawing has it: the date and the headline, the
    ticker taken off it and the headline held to one line. The severity and the reason
    columns go to the hover, with the whole headline: every row here is high and the
    section's basis says so, and the reason repeats the headline ("efficacy supplement"
    beside "Efficacy supplement: Truqap approved"), so on the line each said a thing twice."""
    full = _ki_headline(item, ticker)
    short = full
    if len(full) > _KI_HEADLINE_CHARS and " -> " not in full:
        cut = full[:_KI_HEADLINE_CHARS - 1]
        # At a word where there is one in the last third, so no word is left half shown.
        space = cut.rfind(" ")
        if space > _KI_HEADLINE_CHARS * 2 // 3:
            cut = cut[:space]
        short = cut.rstrip(" ,;:") + "…"
    markup = change_row(dict(item, headline=short, reason=""))
    markup = re.sub(r'<span class="why">[^<]*</span><span class="s [a-z]+">[^<]*</span>', "",
                    markup, count=1)
    hover = " · ".join(part for part in (full, item.get("reason")) if part)
    return markup.replace('class="fitem', f'title="{_ki_attr(hover)}" class="fitem', 1)


def _ki_changes_basis(total: int) -> str:
    """"3 of 10 in 30 days": the rest are on News."""
    return f"{min(_KI_CHANGES_SHOWN, total)} of {total} in {_KI_CHANGE_DAYS} days"


def _key_insights_tab(api_base: str, ticker: str, feed: list, prices: dict) -> None:
    """Key insights, the company on one screen (docs/design/key-insights.md, revision 4):
    the call beside the price, with a market row and a business row of figures under it;
    then three columns that end together, the morning note and the readouts and decisions
    ahead, the key assets and their losses of exclusivity, the bridge to the 12-month value
    and the business against its cohort; then what changed and the note's controls.

    Each object is one the page or a neighbouring tab already reads through the same
    cached call, read once here and passed down. Every read has its own try, so a failure
    costs a module, never the tab, and says it did not load."""
    import drivers as DRV
    if getattr(DRV, "REVISION", 0) < 4:
        DRV = importlib.reload(DRV)

    problem = None
    try:
        payload = _comps_valuation_payload(api_base) or {}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        payload, problem = {}, str(exc).rstrip(".")
    record = next((c for c in payload.get("companies") or []
                   if isinstance(c, dict) and c.get("ticker") == ticker), None) or {}
    board = payload.get("scorecard") if isinstance(payload.get("scorecard"), dict) else {}
    company = (board.get("companies") or {}).get(ticker) if board else None
    if problem is None and not isinstance(company, dict):
        problem = (str(board.get("error")).rstrip(".") if board.get("error")
                   else f"no record for {ticker}")
    company = company if isinstance(company, dict) else None
    cohort = ((board.get("cohorts") or {}).get((company or {}).get("cohort")) or {}) \
        if board else {}

    # Band 1. The call beside the price. A read that fails is said to have failed: falling
    # back to the street there would print a street target beside the model's own bridge.
    fv, fv_failed = {}, None
    for _attempt in range(2):
        try:
            # The rating is the page's lead, and under a refresh it takes over a minute.
            fv = api_get(api_base, f"/companies/{ticker}/fair-value", timeout=120) or {}
            fv_failed = None
            break
        except Exception as exc:  # noqa: BLE001
            fv_failed = str(exc).rstrip(".")
    rated = fv.get("rating") if isinstance(fv.get("rating"), dict) else {}
    series = _ki_year_series(prices.get("points") or [])
    street = ((record.get("street") or {}).get("price_target")
              if isinstance(record.get("street"), dict) else None)
    call = (_ki_call_failed(fv_failed) if fv_failed
            else _ki_call(rated, fv.get("reason"), series, street))
    momentum = _ki_metric(company, ("rel_1y",)) if company else None
    multiple = ((company or {}).get("facts") or {}).get("multiple")
    mplace = _ki_metric(company, ((multiple or {}).get("metric"),)) if company and multiple \
        else None
    figures = _ki_figures(series, call, momentum, street, multiple, mplace)
    tone = call.get("word_tone") if call.get("source") == "model" else "neutral"
    model_mark = ({"mid": rated.get("forward_12m"), "low": rated.get("forward_low"),
                   "high": rated.get("forward_high"), "tone": tone,
                   "tip": (f"Model in 12 months {_ki_money(rated.get('forward_12m'))}, "
                           f"{_ki_money(rated.get('forward_low'))} to "
                           f"{_ki_money(rated.get('forward_high'))}")}
                  if call.get("source") == "model" else None)
    street_mark = ({"value": street["value"],
                    "tip": f"Street target {_ki_money(street['value'])}"}
                   if isinstance(street, dict) and street.get("value") is not None else None)
    money_fmt = (lambda v: f"{v:,.0f}") if (series.get("close") or 0) >= 100 else \
        (lambda v: f"{v:,.2f}")
    chart = CH.price_call(series["closes"], series["dates"], series.get("close"),
                          model=model_mark, street=street_mark, width=800, height=196,
                          value_fmt=money_fmt)
    chart_cell = (f'<div class="chart-mount stretch ki-price">{chart}</div>' if chart else
                  f'<div class="ki-empty" title="no price on file; Refresh on Prices">'
                  f'{_KI_EMPTY}</div>')

    # The reads below the call, before anything is drawn: the business row, the note and
    # the three columns are written from them.
    verdict, verdict_error = None, None
    try:
        verdict = api_get(api_base, f"/companies/{ticker}/forecast-verdict")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        verdict_error = str(exc).rstrip(".")
    fstate = _ki_forecast_state(verdict, verdict_error)
    modelled = fstate == "modelled"
    sotp = (verdict or {}).get("sotp") or {} if modelled else {}
    bp = None
    if modelled:
        try:
            bp = _breakpoints(api_base, ticker)
        except Exception:  # noqa: BLE001
            bp = None
    breaks = _ki_breaks(bp) if modelled else {}
    try:
        context = _comps_context(api_base, ticker)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        context = {"ticker": ticker, "error": str(exc)}
    today = dt.date.today()
    try:
        today = dt.date.fromisoformat(str(board.get("today"))[:10])
    except (TypeError, ValueError):
        pass
    programmes, exclusivities, read_errors = [], [], {}
    try:
        programmes = (api_get(api_base, f"/companies/{ticker}/programmes") or {}).get(
            "programmes") or []
    except (urllib.error.URLError, OSError, ValueError) as exc:
        read_errors["programmes"] = str(exc).rstrip(".")
    try:
        exclusivities = (api_get(api_base, f"/companies/{ticker}/exclusivities") or {}).get(
            "assets") or []
    except (urllib.error.URLError, OSError, ValueError) as exc:
        read_errors["exclusivities"] = str(exc).rstrip(".")
    # The next gates' costs, for the one fact Key assets puts in a row's tooltip: a gate
    # that costs more to reach than it is worth. Its own try, like the two reads above.
    development = None
    if modelled:
        try:
            development = api_get(api_base, f"/companies/{ticker}/development")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            read_errors["trial costs"] = str(exc).rstrip(".")
    assets = _ki_key_assets(verdict, record, programmes, exclusivities, today, modelled,
                            development=development)
    expiries = _ki_expiries(exclusivities, verdict, record,
                            (company or {}).get("exclusivity_losses"), today, modelled)
    # When the events read fails the list says so and is not filled from the registry,
    # which would lead it with Phase 1 studies the events would have outranked.
    events_ok = DRV.context_error(context) is None
    readout_items = ((context.get("catalysts") or {}).get("items") or []) if events_ok else []
    readouts = _ki_readouts(readout_items, today, prose=DRV.indication_prose,
                            min_pct=DRV.DRIVER_MIN_PCT,
                            programmes=programmes if events_ok else None)
    business = _ki_business_figures(record, verdict, company, modelled, exclusivities,
                                    failed=problem or "")
    st.markdown(_ki_band_html([_ki_call_html(call, figures, business), chart_cell], "c2"),
                unsafe_allow_html=True)

    month_news = _ki_changes(feed, ticker, today, levels=("high", "medium", "low"))
    rel_1m = (((record.get("detail") or {}).get("relative") or {}).get("1m")
              or {}).get("relative_pct")
    brief = _ki_brief(ticker, series, rated, call, _ki_metric(company, ("rel_3m",)),
                      _ki_metric(company, ("rel_1y",)), month_news, sotp, assets, breaks,
                      readouts["rows"], [], company, cohort, street, modelled,
                      unrated=str(fv.get("reason") or ""), failed=verdict_error or "",
                      rel_1m=rel_1m, expiries=expiries, rating_failed=fv_failed or "",
                      coverage=(verdict or {}).get("coverage") if modelled else None,
                      business=business)

    # The note's rewrite: Rewrite note (in the foot) asks the note model to rewrite the
    # briefing from exactly these facts; a rewrite is shown only while they still hold.
    # The answer to the click is used as it comes back, since the read below is cached.
    import hashlib
    facts_hash = hashlib.sha1(brief["facts"].strip().encode("utf-8")).hexdigest()[:12]
    if st.session_state.get("gen_note"):
        with st.spinner(f"Writing the {ticker} note"):
            try:
                st.session_state["brief_result"] = dict(api_post_json(
                    api_base, f"/companies/{ticker}/brief", {"facts": brief["facts"]},
                    timeout=120), ticker=ticker)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                st.session_state["brief_result"] = {"error": str(exc), "ticker": ticker}
    written = {}
    fresh = st.session_state.get("brief_result")
    if isinstance(fresh, dict) and fresh.get("ticker") == ticker \
            and fresh.get("hash") == facts_hash and fresh.get("body"):
        written = fresh
    else:
        try:
            written = api_get(api_base, f"/companies/{ticker}/brief?hash={facts_hash}") or {}
        except (urllib.error.URLError, OSError, ValueError):
            written = {}
    if written.get("body"):
        label = " · ".join(x for x in (written.get("model"),
                                       _ki_day(written.get("generated_at")),
                                       (written.get("generated_at") or "")[11:16]) if x)
    else:
        label = "from the figures on this page"
    note_cell = _ki_brief_html(brief, label, written.get("body"))
    # A short note leaves its column room for two more readouts, so the three columns end
    # together rather than column one stopping a hundred pixels early.
    if sum(len(p.split()) for p in brief["paragraphs"]) < 120 and readouts.get("more"):
        readouts = _ki_readouts(readout_items, today, prose=DRV.indication_prose,
                                min_pct=DRV.DRIVER_MIN_PCT, shown=_KI_READOUTS_SHOWN + 2,
                                programmes=programmes if events_ok else None)

    # Band 2, three columns that end together. The note, then the dated events that can
    # move the value. What the value rests on, asset by asset, then the exclusivity it
    # loses next. Where the 12-month value comes from, then the business against its
    # cohort. A read that failed says so, never that nothing is on file.
    def did_not_load(what):
        return (f'<div class="ki-empty">The {what} did not load: '
                f'{html_escape(read_errors[what])}. Reload in a minute.</div>')

    col_a = (note_cell
             + _ki_section_html("Readouts and decisions", "soonest first · ○ estimated date")
             + _ki_readouts_html(readouts))
    ctx_problem = DRV.context_error(context)
    if ctx_problem is not None:
        col_a += (f'<div class="ki-empty">'
                  f'{html_escape(DRV.CONTEXT_FAILED.format(T=ticker, error=ctx_problem))}</div>')
    chip = ("$ a share" if modelled else
            "the forecast did not load" if fstate == "failed" else "not modelled")
    col_b = (_ki_section_html("Key assets", chip)
             + (did_not_load("programmes") if "programmes" in read_errors else "")
             + (did_not_load("trial costs") if "trial costs" in read_errors else "")
             + _ki_key_assets_html(assets, problem or "")
             + _ki_section_html("Loss of exclusivity", "next five · $ a share")
             + (did_not_load("exclusivities") if "exclusivities" in read_errors
                else _ki_expiries_html(expiries, today)))

    if modelled:
        bridge = _ki_bridge(sotp, rated.get("forward_12m") if rated.get("ok") else None)
        end = _ki_money(bridge["end"]) if bridge.get("end") is not None else None
        if bridge["ok"] and end:
            # Built at the column's width with no axis margin, so its figures are drawn
            # at their size. A price far above every bar is named in the chip, not drawn:
            # on the bridge's scale it would crush the bars into the lower half.
            level, tallest = 0.0, 0.0
            for st_ in bridge["steps"]:
                if st_.get("kind") == "start":
                    level = st_.get("value") or 0.0
                elif st_.get("kind") == "step" and st_.get("value") is not None:
                    level += st_["value"]
                tallest = max(tallest, level)
            far = bool(sotp.get("close") and tallest and sotp["close"] > 1.4 * tallest)
            svg = CH.waterfall(bridge["steps"], 430, 176,
                               value_fmt=lambda x: f"{x:,.2f}", pad_l=8,
                               reference=({"label": None, "value": sotp["close"]}
                                          if sotp.get("close") and not far else None))
            top = (_ki_section_html(f"Where {end} comes from",
                                    f"$ a share · price {_ki_money(sotp.get('close'))}, "
                                    + ("above the chart" if far else "dashed"))
                   + f'<div class="chart-mount stretch ki-bridge">{svg}</div>')
        else:
            top = (_ki_section_html("Where the value comes from")
                   + f'<div class="ki-empty">{html_escape(_KI_NO_BRIDGE)}</div>')
    elif fstate == "failed":
        top = (_ki_section_html("Where the value comes from")
               + f'<div class="ki-empty">The forecast did not load: '
                 f'{html_escape(verdict_error)}. Reload in a minute.</div>')
    else:
        expects = _ki_street_expects(record)
        top = ""
        if expects:
            cells = "".join(f'<div class="ki-f"><span class="v">{html_escape(v)}</span>'
                            f'<span class="k">{html_escape(k)}</span></div>'
                            for v, k in expects)
            top = (_ki_section_html("What the street expects")
                   + f'<div class="ki-figs ki-expects">{cells}</div>')
    if company is None:
        cohort_html = (_ki_section_html("Against its cohort")
                       + f'<div class="ki-empty">'
                         f'{html_escape(_KI_FAILED.format(error=problem))}</div>')
    else:
        chip = (f"{_ki_ord(company['rank'])} of {company.get('ranked_of')}"
                if company.get("rank") is not None else (company.get("reason_text") or ""))
        title = (f"Against {cohort.get('n')} {cohort.get('noun')}"
                 if cohort.get("n") and cohort.get("noun") else "Against its cohort")
        groups = _ki_cohort_table(board, ticker, record,
                                  verdict if isinstance(verdict, dict) else {})
        strips = {r["id"]: CH.peer_dots(r["peers"], {"ticker": ticker, "value": r["value"],
                                                     "text": r.get("text")},
                                        better=r["better"], width=68, height=16,
                                        median=r.get("median"), tone=r["tone"],
                                        label=r["full_label"])
                  for g in groups for r in g["rows"] if r.get("value") is not None}
        cohort_html = _ki_section_html(title, chip) + _ki_cohort_html(groups, strips)
    col_c = (f'<div class="ki-top">{top}</div>' if top else "") + cohort_html
    st.markdown(_ki_band_html([col_a, col_b, col_c], "c3e"), unsafe_allow_html=True)

    # Foot. What changed, then the note's controls.
    changes = _ki_changes(feed, ticker, today)
    changed_col, note_col = st.columns([7, 5], gap="medium")
    with changed_col:
        section("What changed", basis=_ki_changes_basis(len(changes)) if changes else "")
        if changes:
            st.markdown('<div class="feed ki-changes">'
                        + "".join(_ki_change_row(it, ticker)
                                  for it in changes[:_KI_CHANGES_SHOWN])
                        + "</div>", unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="ki-empty">{html_escape(_KI_NO_CHANGES)}</div>',
                        unsafe_allow_html=True)
    with note_col:
        section("Note")
        b1, b2, _pad = st.container(key="ki_note_buttons").columns([1.2, 1, 2], gap="small")
        with b1:
            st.button("Rewrite note", key="gen_note", width="stretch",
                      help="Have the note model rewrite the morning note from the figures "
                           "on this page")
        with b2:
            write_sheet = st.button("Tearsheet", key="gen_sheet", width="stretch")
        result = st.session_state.get("brief_result")
        if isinstance(result, dict) and result.get("ticker") == ticker and result.get("error"):
            st.markdown(f'<div class="byline">The rewrite did not run: '
                        f'{html_escape(result["error"])}. The note above is the one built '
                        'from the figures.</div>', unsafe_allow_html=True)
        if write_sheet:
            with st.spinner(f"Writing the {ticker} tearsheet"):
                st.session_state["tearsheet"] = api_post(
                    api_base, f"/companies/{ticker}/tearsheet")
        made = st.session_state.get("tearsheet")
        if made and made.get("ticker") == ticker:
            st.markdown(
                f'<div class="byline">Tearsheet written to '
                f'<span class="mono">exports/{html_escape(made["filename"])}</span>. '
                'Open it and print to A4, or save as PDF.</div>',
                unsafe_allow_html=True)

    _china_bd(api_base, ticker)


def _universe_overview(api_base, engine, _engine_name, _covered, _all_changes,
                       universe_feed) -> None:
    """What moved across coverage: headlines, approvals, the map, what is ahead.

    The tab's default view, and the one a reader opens the terminal for. The feed
    is passed in rather than fetched again, because the view switcher above has
    already read it once to decide what to show.
    """
    leads = api_get(api_base, f"/headlines?engine={urllib.parse.quote(engine or '')}")
    section("Headlines this week", f"{len(leads)} across {_engine_name}" if leads
            else _engine_name)
    if not leads:
        state(f"Nothing material on {_engine_name} in the last week",
              "A headline is a deal with stated terms, an approval, an FDA notice, a "
              "senior change or a trial stopping. Quiet is an answer.")
    else:
        st.markdown(_leads(leads, 6, 3), unsafe_allow_html=True)
    # The universe view leads with FDA approvals, the cleanest cross-coverage signal,
    # drawn on a date axis rather than a jargon-heavy list; the full change feed with
    # filings, trial moves and risk-factor edits lives on each company's Key insights.
    # Year to date, read from the approvals themselves rather than from the change
    # feed, which is bounded by how far back the diff engine looks and so gave a
    # window that moved with the refresh rather than one a reader chose.
    #
    # The year bounds what is fetched; the axis still opens on the first approval in
    # it. Nothing cleared before 17 March this year, so the tape starts in March, and
    # a January approval next year will pull it back to January on its own.
    _ytd = dt.date(dt.date.today().year, 1, 1)
    approvals = [
        {"ticker": a["ticker"],
         "label": a["label"],
         "date": a["date"],
         # The application number is what identifies the product on the Portfolio
         # tab, so it rides along as the click key and a mark opens its fact sheet.
         "key": (f'{a["ticker"]}|{(a["application_number"] or "").replace(" ", "")}'
                 if a.get("application_number") and a.get("ticker") else ""),
         "full": f'{a["label"]} ({a["application_number"] or "no number"})'
                 f' — {(a["date"] or "")[:10]}'}
        for a in api_get(api_base, f"/approvals?since={_ytd.isoformat()}")["approvals"]
        if a["ticker"] in _covered]
    section(f"FDA approvals across {_engine_name}",
            f"{len(approvals)} year to date")
    if not approvals:
        # An empty tape means two different things, and pointing at the refresh button
        # for both of them reads as a broken fetcher when it is a quiet cohort. If the
        # universe has approvals and this engine has none, that is the answer.
        _elsewhere = sum(1 for it in _all_changes
                         if it.get("change_type") == "new_approval")
        state(f"No approvals flagged across {_engine_name}",
              (f"{_elsewhere} landed elsewhere in the universe over the same window, "
               "so this is the cohort rather than the source." if _elsewhere else
               "New approvals are read from openFDA on refresh. Press Refresh all in "
               "the top bar to pull the sources."))
    else:
        approvnav.approvals_nav(
            CH.approvals_timeline(approvals, 1360, 84, dt.date.today()),
            muted=TK.MUTED, key="appr_nav")

    # The two summary views side by side: where the money is on this engine, and
    # what is dated on it. Both are read at a glance and neither needs the full
    # width, so pairing them puts the answer to "how does it look" and the answer to
    # "what is coming" in one screen instead of two scrolls.
    #
    # Three to two, not one to one. They are not the same kind of view and an equal
    # split served neither: the map is spatial and every pixel of width buys area for
    # the small companies, while the forward list is text that wraps at any width and
    # was running half empty down its last two rows.
    _map_col, _ahead_col = st.columns([3, 2], gap="medium")
    # The map states the window it colours. Held here so the coverage note
    # below can name it without a second copy of a number owned by the API.
    _map_days = MARKETMAP_FALLBACK_DAYS
    with _map_col:
        # The group at a glance before the ninety panels that show each shape. Area is
        # what the engine runs on and colour is the move, read independently: a large box
        # that is deep red is the thing this view exists to show.
        mmap = api_get(api_base,
                       f"/marketmap?engine={urllib.parse.quote(engine or '')}")
        _map_days = mmap.get("window_days") or _map_days
        if mmap.get("rows"):
            unsized = len(mmap.get("unsized") or [])
            # Short, because the column is half a page wide; the byline below
            # carries what area and colour mean.
            section("Map", f"{len(mmap['rows'])} by {mmap['metric']}"
                    + (f" · {unsized} unsized" if unsized else ""))
            R.show(treemap.build(mmap["rows"]), css_class="chart-mount")
            note(f'Area is {html_escape(mmap["label"])}, colour the price move '
                 f'over {mmap["window_days"]} days, green up and red down, each read '
                 'on its own: a large box that is deep red is what the view is '
                 'for. Hover a box for the company and its move. Not market '
                'capitalisation, which would need shares outstanding against the last '
                'close, and for a company quoted as an ADR the share count is in ordinary '
                'shares while the price is per receipt: GSK computes to 223bn against a '
                'real ninety. A company the metric cannot size is counted above rather '
                'than drawn at nothing.')

    with _ahead_col:
        # One forward view. A readout and a panel vote were two sections asking the same
        # question, what is coming, split only by which table the date came out of. The
        # answer to both is a date with a company against it, so they read as one list in
        # the same boxes the headlines use: what happened, then what is about to.
        soon = api_get(api_base,
                       f"/lookahead?engine={urllib.parse.quote(engine or '')}")
        # Firm against derived, because they are not the same kind of date. A PDUFA or a
        # panel vote is stated; a readout is a registry completion date, which slips.
        firm = [i for i in soon if i.get("curated")]
        section("Looking ahead",
                (f"{len(soon)} in 30 days"
                 + (f" · {len(firm)} firm" if firm else ""))
                if soon else "nothing inside 30 days")
        if not soon:
            state("Nothing dated inside 30 days",
                  "Readouts derive from registry completion dates on refresh, panel votes "
                  "from the Federal Register, and PDUFA dates are read from 8-Ks when a "
                  "model key is set. Quiet is an answer.")
        else:
            # Two across at both widths: the narrow rule is keyed to the page, and
            # this block is already in half of it, so collapsing again stacked six
            # boxes into a column taller than the map beside it.
            st.markdown(_leads(soon[:_AHEAD_SHOWN], 2, 2),
                        unsafe_allow_html=True)


    # A year, where the map above reads a quarter. The two were the same window and
    # so the same fact drawn twice, once as colour and once as a line: nothing on the
    # page said anything the other did not. Set a year apart they answer different
    # questions, and the interesting companies are the ones where the answers differ.
    # Bayer is up 29% on the quarter and 70% on the year; Merck is up 15% and 64%.
    section(f"Coverage, {COVERAGE_MONTHS} months",
            f"{len(_covered)} companies, one scale")
    panels = [p for p in api_get(api_base, f"/price-grid?days={COVERAGE_DAYS}")
              if p["ticker"] in _covered]
    if any(p["closes"] for p in panels):
        shown = sorted(panels, key=lambda p: p["ticker"])
        covnav.coverage_nav(
            CH.small_multiples(
                [{"label": p["ticker"],
                  "values": _pct_from_start(p["closes"] or []),
                  "sub": T.pct(p["change"] * 100) if p["change"] is not None else ""}
                 for p in shown], 1360, 112, cols=_coverage_columns(len(shown)),
                link_base="?ticker="),
            muted=TK.MUTED, key="cov_nav")
        note(f"Each panel is {COVERAGE_MONTHS} months of closes indexed to its own "
             "start, all on one scale, so a flat line means flat rather than "
             f"autoscaled noise. The map above colours the last {_map_days} "
             "days: a company green there and flat here had a good quarter in a "
             "dull year, and the reverse is a year that has finished running. "
             "Click a panel to jump straight to that company's Key insights.")
    else:
        state("No price history yet",
              "Press Refresh all in the top bar to pull daily closes.")

def _markets_view(api_base: str, feed: list) -> None:
    """The standing level, and any move already flagged against it.

    On its own view rather than above the headlines. It is the level everything else
    is read against, which made it a reasonable thing to lead with and a poor thing to
    lead with every day: it changes slowly and the page it sat on answers what moved.
    """
    _markets_strip(api_base)
    moves = [it for it in feed if it.get("kind") == "market"]
    if moves:
        section("Flagged moves", f"{len(moves)}",
                "measured against the level the book last priced at")
        st.markdown(_leads([_feed_lead(it) for it in moves], 3, 2),
                    unsafe_allow_html=True)
    else:
        section("Flagged moves", "none", "nothing has crossed its bar")
        state("No rate or currency move is flagged",
              "A bar is crossed against the level the last flag was written from, not "
              "against yesterday: the ten-year writes a row at 10bp and a note at "
              "25bp, the breakeven at 10bp, single-A at 25bp, and a reporting cross "
              "at 2%. Quiet is an answer.")


def _docket(docket: str | None) -> str:
    """The docket number alone, for the column a ticker would occupy.

    It plays the ticker's part here: the short, fixed-width thing a reader runs an eye
    down before reading any title. The agencies write it differently, "CMS-4219-N"
    against "Docket No. 250414-0065", so the prose comes off and the number stays. A
    row naming two dockets keeps the first and says so with an ellipsis.
    """
    text = (docket or "").strip()
    if not text:
        return ""
    text = re.sub(r"^Docket\s+No\.?\s*", "", text, flags=re.I)
    if " and " in text:
        text = text.split(" and ")[0].strip() + "…"
    return text[:18]


def _policy_lead(item: dict) -> dict:
    """One policy document as the same box a headline gets.

    The rail was a four-column table, which read as a database dump next to boxes
    everywhere else on the page. Nothing about the content wanted its own component:
    a dated thing with a title, a source and a few fields is what the lead box is.

    The lane goes in the slot a ticker would take, because it plays the same part: the
    scannable left column a reader reads down before reading any sentence.
    """
    title = item.get("title") or ""
    rows = []
    if len(title) > _FEED_LEAD_CHARS:
        rows.append({"label": "Full title", "value": title})
    if item.get("docket_id"):
        rows.append({"label": "Docket", "value": item["docket_id"]})
    if item.get("doc_type"):
        rows.append({"label": "Document", "value": item["doc_type"]})
    if item.get("effective_on"):
        rows.append({"label": "Effective", "value": item["effective_on"]})
    if item.get("comments_close_on"):
        rows.append({"label": "Comments close", "value": item["comments_close_on"]})
    rows.append({"label": "Published", "value": item.get("published_on") or ""})
    # The chip carries the one thing a reader can act on where there is one, and what
    # kind of document it is where there is not. Not the lane: these are grouped under
    # a lane heading, and repeating it put the same three words in the heading, the
    # chip and the left column of every card.
    today = dt.date.today().isoformat()
    due = item.get("comments_close_on")
    figure = (f"closes {_day(due)}" if due and due >= today
              else (item.get("doc_type") or "Document"))
    return {"kind": "policy", "figure": figure,
            "ticker": _docket(item.get("docket_id")),
            "headline": (title if len(title) <= _FEED_LEAD_CHARS
                         else title[:_FEED_LEAD_CHARS - 1].rstrip() + "…"),
            "date": (item.get("published_on") or "")[:10],
            "summary": rows, "evidence": "", "url": item.get("url") or ""}


def _policy_view(api_base: str) -> None:
    """The policy documents, on their own view rather than above the headlines.

    It is context and it reads as context: a weaker claim than anything else on the
    tab, carrying no modelled number. Putting it first said the opposite.
    """
    try:
        got = api_get(api_base, f"/policy?days={_POLICY_DAYS}")
    except Exception:
        state("Policy is not available",
              "The API did not answer /policy. Start the backend, or run a refresh to "
              "fill the lane.")
        return
    items = got.get("items") or []
    if not items:
        state("No policy documents on file",
              "Two lanes are fetched: Section 232 tariffs on pharmaceuticals, and "
              "Medicare drug price negotiation rulemaking. A refresh fills them.")
        return

    today = dt.date.today().isoformat()
    open_now = [i for i in items
                if (i.get("comments_close_on") or "") >= today]
    if open_now:
        section("Open for comment", f"{len(open_now)}",
                "a deadline a reader can still act on")
        st.markdown(_leads([_policy_lead(i) for i in open_now], 3, 2),
                    unsafe_allow_html=True)

    for lane, about in (got.get("lanes") or {}).items():
        mine = [i for i in items if i.get("lane") == lane and i not in open_now]
        if not mine:
            continue
        section(_POLICY_LANES.get(lane, lane), f"{len(mine)}", about)
        st.markdown(_leads([_policy_lead(i) for i in mine], 3, 2),
                    unsafe_allow_html=True)

    note("Two lanes, each gated on what was measured rather than on an agency and a "
         "search term. Without the gates a Framework for Artificial Intelligence "
         "Diffusion lands in the pharmaceutical tariff lane, and six recurring agency "
         "information collection notices land in the drug pricing one carrying real "
         "comment deadlines. Nothing here is a modelled number and nothing here is "
         "multiplied into a value: the imported share of cost of goods is not free "
         "data and the terms of a pricing deal are undisclosed, so an applied figure "
         "would be invention with a citation attached. Dates are the documents' own.")


def _ira_strip(api_base: str, ticker: str) -> None:
    """Medicare price negotiation for this company, where CMS has selected anything.

    The ceiling cut and the exposure sit beside each other and are never multiplied.
    Both are built from gross figures, so their product would read as a loss estimate
    that free data cannot support, and the note under the strip says so.
    """
    try:
        got = api_get(api_base, f"/companies/{ticker}/ira")
    except Exception:
        return
    drugs = got.get("selected") or []
    if not drugs:
        return
    exposure = got.get("exposure") or {}
    cuts = [d["ceiling_cut"] for d in drugs if d.get("ceiling_cut") is not None]
    section("Medicare price negotiation", f"{got['count']} selected",
            "CMS names the brand, so this binds to the asset")
    tiles = [
        ("drugs selected", str(got["count"]), "", None, "",
         ", ".join(sorted({d["brand"] for d in drugs}))[:60]),
        ("earliest price year", str(got["earliest_ipay"]), "", None, "",
         "initial price applicability year"),
        ("MFP per 30-day supply",
         T.num(got["mfp_30des_low"], 2) if got.get("mfp_30des_low") else None, "",
         None, "",
         (f"to {T.num(got['mfp_30des_high'], 2)}"
          if got.get("mfp_30des_high") != got.get("mfp_30des_low") else "one price")),
        ("Part D gross spending",
         T.num((exposure.get("part_d_spending") or 0) / 1e9, 1)
         if exposure.get("part_d_spending") else None, "bn", None, "",
         f"{exposure['share']:.1%} of revenue" if exposure.get("share") else
         (exposure.get("reason") or "")),
        ("ceiling cut", T.pct(max(cuts) * 100, 0) if cuts else None, "", None, "",
         "the most a list price could fall" if cuts else "no price on file"),
    ]
    st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)
    note("Gross Part D spending is what Medicare and its beneficiaries paid at list, "
         "not what the company booked, so the share of revenue is a scale of the "
         "franchise CMS has selected rather than revenue at risk. The ceiling cut is "
         "the most a list price could fall and is not the realised cut: the rebates a "
         "maximum fair price replaces are confidential, so the true fall is smaller by "
         "an amount free data cannot show. The two are shown side by side and never "
         "multiplied, because their product would be a loss estimate built from two "
         "gross figures.")


def _markets_strip(api_base: str) -> None:
    """The standing level, one tile per series, each dated to its own publication day.

    Rates carry no colour. The app's convention is green up and red down as pure
    direction, and on this book a rate rising is value-negative, so a green ten-year
    would read as good news for the opposite of the reason it is here. The crosses and
    the index keep the colour, because a stronger euro and a higher market both do lift
    what this book is worth.
    """
    try:
        built = api_get(api_base, f"/markets?days={_MARKETS_DAYS}")
    except Exception:
        return                                   # a strip is context, never a blocker
    rates = [r for r in (built.get("rates") or []) if r.get("value") is not None]
    crosses = [f for f in (built.get("fx") or []) if f.get("rate") is not None]
    marks = [b for b in (built.get("benchmarks") or []) if b.get("close") is not None]
    if not (rates or crosses or marks):
        return

    days = built.get("days") or _MARKETS_DAYS
    section("Markets", f"{days}-day change", "the level the book is discounted at")

    tiles = []
    for r in rates:
        move = (f"{T.num(r['change_bp'], 0)}bp" if r.get("change_bp") is not None
                else "")
        if move and (r.get("change_bp") or 0) > 0:
            move = "+" + move
        owner = r.get("restricted_to")
        short = _OWNER_SHORT.get(owner, owner)
        tiles.append((_RATE_LABELS.get(r["series"], r["series"]),
                      T.pct(r["value"] * 100, 2), "", move, "",
                      " · ".join(x for x in (_day(r.get("as_of")), short) if x)))
    for f in crosses:
        pct_move = f.get("change_pct")
        tiles.append((f"{f['base']}/USD", T.num(f["rate"], 4), "",
                      f"{'+' if (pct_move or 0) > 0 else ''}{T.pct(pct_move * 100, 2)}"
                      if pct_move is not None else "",
                      " up" if (pct_move or 0) > 0 else " down" if pct_move else "",
                      _day(f.get("as_of"))))
    for b in marks:
        pct_move = b.get("change_pct")
        tiles.append((_BENCHMARK_NAMES.get(b["symbol"], b["symbol"].lstrip("^")),
                      T.num(b["close"], 0), "",
                      f"{'+' if (pct_move or 0) > 0 else ''}{T.pct(pct_move * 100, 2)}"
                      if pct_move is not None else "",
                      " up" if (pct_move or 0) > 0 else " down" if pct_move else "",
                      _day(b.get("as_of"))))
    st.markdown(metric_tiles(tiles, one_row=True), unsafe_allow_html=True)

    # Every date on the strip is the day that series last published, and they differ:
    # the indexed Treasury lags two days, the ECB keeps TARGET days and the index the
    # NYSE calendar. Saying so is the point of putting the date on the cell.
    dates = {t[5].split(" · ")[0] for t in tiles if t[5]}
    bits = ["Each cell is dated to the day its own source last published, so the dates "
            "differ: the indexed Treasury series lags two days, the ECB publishes on "
            "TARGET days and the index on NYSE days."
            if len(dates) > 1 else
            "Every series last published on the same day."]
    refused = [r for r in (built.get("rates") or []) if r.get("no_change_reason")]
    if refused:
        bits.append("No change is shown for "
                    + ", ".join(_RATE_LABELS.get(r["series"], r["series"])
                                for r in refused)
                    + ": " + refused[0]["no_change_reason"] + ".")
    stale = [b for b in marks if b.get("as_of") and rates
             and b["as_of"] < max(r["as_of"] for r in rates if r.get("as_of"))]
    if stale:
        bits.append("The index closes are a one-off backfill and are not on the "
                    "refresh, so they sit behind the rates beside them.")
    owners = sorted({r["restricted_to"] for r in rates if r.get("restricted_to")})
    if owners:
        bits.append("The corporate yield is " + " and ".join(owners)
                    + ", read here to set a cost of debt and not redistributed.")
    bits.append("A rate rising lowers what the book is worth, which is why the rate "
                "cells carry no colour.")
    note(" ".join(bits))


def _leads(items, per_row: int, narrow_per_row: int) -> str:
    """A row of headline boxes, evenly divided at the page's two widths."""
    return (f'<div class="leads" '
            f'style="--lead-cols: {_lead_columns(len(items), per_row)}; '
            f'--lead-cols-narrow: {_lead_columns(len(items), narrow_per_row)}">'
            + "".join(_lead_box(i) for i in items) + "</div>")


def note_html(body: str, fit: bool = False) -> str:
    """Render the note, giving its section labels the heading treatment.

    The rules layer emits plain lines like "Catalysts inside 60 days (2)" followed by
    dashed items. Left as prose they read as a run-on, so labels become headings and
    dashed lines become a list.

    ``fit`` bounds the height and scrolls inside it. Key insights has to fit one screen
    and the note is the only thing on it whose length is set by how much happened rather
    than by the layout, so it gets its own scroll rather than pushing the rest of the tab
    below the fold. Nothing is cut: the whole note is still there to scroll through.
    """
    out, bullets = [], []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            bullets.append(line[2:])
        elif line.endswith(")") and "(" in line.rsplit(" ", 1)[-1]:
            flush()
            out.append(f"<h4>{line}</h4>")
        else:
            flush()
            out.append(f"<p>{line}</p>")
    flush()
    return (f'<div class="note{" note-fit" if fit else ""}">'
            f'{"".join(out)}</div>')


st.set_page_config(page_title="Equity research terminal", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(T.css(), unsafe_allow_html=True)

st.sidebar.markdown("#### Settings")
api_base = st.sidebar.text_input("API base URL", DEFAULT_API)

# --- Connection: the first designed error state -------------------------
try:
    companies = api_get(api_base, "/companies")
except (urllib.error.URLError, OSError) as exc:
    st.markdown('<div class="ident"><span class="tk">Pharma research</span></div>',
                unsafe_allow_html=True)
    state("The API is not answering on " + api_base,
          f"{exc}. Start it with <code>uvicorn main:app --app-dir backend --reload "
          "--port 8000</code> from the project root, then reload this page. Change the "
          "base URL in the sidebar if the API runs elsewhere.", error=True)
    st.stop()

if not companies:
    state("No companies loaded",
          "The database has no universe yet. Run <code>python seed.py</code> from the "
          "backend directory to load the 18 companies and resolve their CIKs.")
    st.stop()

# --- Engines: which terminal is open --------------------------------------
# Three engines over one universe, because the questions differ rather than the companies
# do. A major is read on where its revenue comes from and when it stops; a platform
# developer on which platform, how far it has got and how long the cash lasts. Asking
# both the same questions is what left half the answers blank.
#
# The landing page shows only on a visit that names neither an engine nor a company, so a
# shared ?ticker= link still opens straight onto that company and a returning session
# keeps the engine it was last on.
ENGINES = ("pharma", "biotech", "cellgene")
engine = (st.query_params.get("engine") or "").lower()
if engine not in ENGINES:
    engine = ""
if not engine and st.session_state.get("engine") in ENGINES:
    engine = st.session_state["engine"]

if not engine and not (st.query_params.get("ticker") or ""):
    # Names only. The front door selects an engine and shows no figures, so it has no
    # reason to compute three cohorts to render a poster.
    catalogue = api_get(api_base, "/engines/catalogue")["engines"]
    picked = enginepick.engine_pick(
        [{"engine": entry["key"], "label": entry["label"],
          "tagline": entry["tagline"]} for entry in catalogue],
        tokens=LANDING_TOKENS, key="engine_pick")
    st.caption(
        "An engine decides which companies the picker offers and which tabs a company "
        "page can fill. Search always reaches the whole universe.")
    # A click is acted on once. The nonce changes per click, so a rerun caused by
    # anything else does not send the visit somewhere it has already been.
    if isinstance(picked, dict) and picked.get("nonce") != st.session_state.get(
            "_engine_nonce"):
        st.session_state["_engine_nonce"] = picked.get("nonce")
        if picked.get("engine") in ENGINES:
            st.query_params["engine"] = picked["engine"]
            st.session_state["engine"] = picked["engine"]
            st.rerun()
        wanted = (picked.get("ticker") or "").upper()
        if wanted:
            # A signal opens its company on that company's own engine, so the page it
            # lands on is the one built for the question the signal raises.
            home_engine = next(
                (c.get("engine") for c in companies if c["ticker"] == wanted), None)
            st.query_params["ticker"] = wanted
            if home_engine in ENGINES:
                st.query_params["engine"] = home_engine
                st.session_state["engine"] = home_engine
            st.rerun()
    st.stop()

# A shared ?ticker= link names no engine, so it adopts the company's own. Without this the
# page opened on the whole universe while the sidebar called it big pharma, and the tabs
# were decided by a stage test the engines were built to replace.
_shared = (st.query_params.get("ticker") or "").upper()
if not engine and _shared:
    engine = next((c.get("engine") for c in companies
                   if c["ticker"] == _shared and c.get("engine") in ENGINES), "")

# The Comps valuation view can make any company in the universe focal, since a peer may
# come from another engine. The picker below lists only the open engine's companies, so a
# focal company from another engine opens its own engine first, the way a shared link
# does, and the hook before the picker then selects it.
_cv_focus = _compsval_focus()
if engine and _cv_focus:
    _cv_home = next((c.get("engine") for c in companies if c["ticker"] == _cv_focus), None)
    if _cv_home in ENGINES and _cv_home != engine:
        engine = _cv_home
        st.query_params["engine"] = _cv_home

st.session_state["engine"] = engine or st.session_state.get("engine") or "pharma"
# An engine narrows the picker to the companies it covers. Search is the escape hatch and
# still reaches everything, so narrowing costs nothing that cannot be undone. The home
# engine arrives on the company list, so this needs no second request.
if engine:
    companies = [c for c in companies if c.get("engine") == engine] or companies

tickers = [c["ticker"] for c in companies]
names = {c["ticker"]: c["name"] for c in companies}

# --- Top bar --------------------------------------------------------------
# Fixed strip: ticker selector, identity, global search, last refresh, refresh.
# The jump runs as the search input's on_change callback, which is the one place
# Streamlit allows another widget's state to be written: a mid-script write left
# the select's displayed label behind its actual state.
# ?ticker= reopens the terminal on a specific company, and the pick is written back to
# the URL after the selector below, so the address bar is always shareable.
#
# The URL is read on the session's first run only. It cannot be re-read every run to
# follow the address bar: the pick is written to the URL at the end of a run, so when a
# search or a coverage click changes the company mid-run the URL still holds the previous
# one, and treating it as authoritative would immediately undo the change the analyst
# just made. Reopening on a different company is a fresh page, which is a fresh session,
# and that is handled here.
_url_ticker = (st.query_params.get("ticker") or "").upper()
if "company_pick" not in st.session_state:
    st.session_state["company_pick"] = (
        _url_ticker if _url_ticker in tickers
        else DEFAULT_TICKER if DEFAULT_TICKER in tickers else tickers[0])

# A click on a coverage panel (the covnav component) returns the ticker and switches to
# Key insights client-side; apply the ticker here, before the selectbox reads its key, so
# there is no widget-after-set conflict. The nonce makes each click a fresh change, so a
# repeat click still applies and the sidebar can still change the company between clicks.
_cov = st.session_state.get("cov_nav")
if (isinstance(_cov, dict) and _cov.get("ticker") in tickers
        and _cov.get("nonce") != st.session_state.get("_cov_nonce")):
    st.session_state["company_pick"] = _cov["ticker"]
    st.session_state["_cov_nonce"] = _cov.get("nonce")

# The same for the Comps valuation view: a new focal company picked inside it (its
# company selector, "Make focal" or the palette) is applied here, before the selector
# reads its key. The nonce is recorded either way, so an unknown ticker is dropped once
# rather than retried on every rerun.
if _cv_focus is not None:
    if _cv_focus in tickers:
        st.session_state["company_pick"] = _cv_focus
    st.session_state["_compsval_nonce"] = (st.session_state.get("compsval") or {}).get("nonce")

# A click on the approvals timeline names a company and an application number. The
# company is applied here, before the selector reads its key; the application number is
# A wedge on the revenue mix links to ?product=<asset id>. Read once, held in session
# and cleared from the URL, so the selection survives the reruns that follow and the
# address bar does not pin a product the reader has since clicked away from.
_url_product = (st.query_params.get("product") or "").strip()
if _url_product.isdigit():
    st.session_state["profile_asset"] = int(_url_product)
    del st.query_params["product"]

# held for the Portfolio tab, which is the only place that knows which product it is.
_appr = st.session_state.get("appr_nav")
if (isinstance(_appr, dict) and _appr.get("key")
        and _appr.get("nonce") != st.session_state.get("_appr_nonce")):
    _appr_ticker, _, _appr_appno = str(_appr["key"]).partition("|")
    if _appr_ticker in tickers:
        st.session_state["company_pick"] = _appr_ticker
        st.session_state["pending_product"] = _appr_appno
    st.session_state["_appr_nonce"] = _appr.get("nonce")


def _jump_to_search():
    wanted = (st.session_state.get("global_search") or "").strip().upper()
    if not wanted:
        return
    match = (next((t for t in tickers if t == wanted or t.startswith(wanted)), None)
             or next((t for t in tickers if wanted in names[t].upper()), None))
    if match:
        st.session_state["company_pick"] = match
        st.session_state["global_search"] = ""


# A button in the Universe tab's company dialog opens that company on another tab; the
# company is applied here, before the selector reads its key.
universe_page.apply_goto(tickers)

bar = st.columns([0.085, 0.40, 0.20, 0.20, 0.115], gap="small")
with bar[0]:
    st.markdown('<span class="topbar-anchor"></span><div class="pick">',
                unsafe_allow_html=True)
    ticker = st.selectbox("Company", tickers, key="company_pick",
                          label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
company = next((c for c in companies if c["ticker"] == ticker), {})
st.query_params["ticker"] = ticker

# The way back out. An engine is a filter on the picker, so without this a narrowed
# universe would be a one-way door.
_ENGINE_LABELS = {"pharma": "Big pharma", "biotech": "Biotech",
                  "cellgene": "Cell and gene"}
st.sidebar.markdown("#### Engine")
st.sidebar.caption(_ENGINE_LABELS.get(engine, "The whole universe")
                   + f" · {len(tickers)} companies")
if st.sidebar.button("Change engine", key="engine_reset"):
    st.query_params.pop("engine", None)
    st.query_params.pop("ticker", None)
    st.session_state.pop("engine", None)
    st.rerun()

# --- Per-company data ---------------------------------------------------
feed = api_get(api_base, f"/changes?ticker={urllib.parse.quote(ticker)}")
prices = api_get(api_base, f"/companies/{ticker}/prices")
exclusivities = api_get(api_base, f"/companies/{ticker}/exclusivities")["assets"]

# --- Identity ------------------------------------------------------------
# The form is named rather than the nationality. GSK files with the SEC as a foreign
# private issuer, so "US filer" was wrong, and the currency here is the one the shares
# are quoted in, which for an ADR is not the one the accounts are reported in: GSK
# quoted in USD reports in GBP, and the two sat side by side reading as a contradiction.
if not company.get("is_sec_filer"):
    # Bayer files its annual report in the European Single Electronic Format, which is
    # where its financials come from. Roche's come from its own workbook instead.
    filer = "ESEF filer" if company.get("lei") else "not an SEC filer"
elif company.get("is_foreign_private_issuer"):
    filer = "20-F filer"
else:
    filer = "10-K filer"
quote = prices.get("currency")
meta = " · ".join(x for x in [company.get("primary_exchange"), filer,
                              f"quoted in {quote}" if quote else None] if x)
with bar[1]:
    st.markdown(
        f'<div class="topbar-name"><span class="nm">{names.get(ticker, ticker)}</span>'
        f'<span class="meta">{meta}</span></div>', unsafe_allow_html=True)
with bar[2]:
    st.markdown('<div class="topsearch">', unsafe_allow_html=True)
    st.text_input("Search", key="global_search", label_visibility="collapsed",
                  placeholder="jump to ticker or name", on_change=_jump_to_search)
    st.markdown("</div>", unsafe_allow_html=True)
with bar[3]:
    latest_run = api_get(api_base, "/runs/latest")
    if latest_run.get("finished_at"):
        cls = "ok" if latest_run.get("status") == "complete" else "bad"
        st.markdown(
            f'<div class="topbar-run">last refresh {latest_run["finished_at"]} UTC'
            f' · <span class="{cls}">{latest_run.get("status")}</span></div>',
            unsafe_allow_html=True)
    elif latest_run.get("started_at"):
        # A run with no finish is one still going, or one whose process died holding the
        # row open. Both read as "no refresh run yet" before, which told a reader their
        # data had never been pulled when in fact it had been pulled minutes ago.
        st.markdown(
            f'<div class="topbar-run">refresh {html_escape(latest_run.get("status") or "running")}'
            f' since {html_escape(str(latest_run["started_at"]))} UTC</div>',
            unsafe_allow_html=True)
    else:
        st.markdown('<div class="topbar-run">no refresh run yet</div>',
                    unsafe_allow_html=True)
with bar[4]:
    if st.button("Refresh all", key="topbar_refresh", width="stretch"):
        run_refresh(api_base, "/refresh?scope=all", "all_run",
                    "Refreshing the universe")
        st.rerun()

# The per-source freshness strip is gone. A partial run still announces itself below,
# since a run that half failed is an event rather than standing reference.
last_run = st.session_state.get("last_run") or {}
run_sources = {s["source"]: s for s in last_run.get("detail", {}).get("sources", [])}

if last_run and last_run.get("status") == "partial":
    # What actually failed, in the source's own words. A summary had to guess at both
    # the cause and the consequence, and guessed wrong: it named a source that had
    # written every one of its rows, and told the analyst to retry something that was
    # not a fault. The error text is the only thing that says what to do next, so it is
    # what gets shown. Rows fetched sits beside it, since a source can report a problem
    # and still return most of its data.
    failed = [s for s in run_sources.values() if s.get("errors")]
    lines = []
    for s in failed:
        for err in s["errors"][:4]:
            lines.append(f'<div class="runerr"><span class="s">'
                         f'{html_escape(s["source"])}</span>'
                         f'<span class="e">{html_escape(str(err))}</span></div>')
        extra = len(s["errors"]) - 4
        if extra > 0:
            lines.append(f'<div class="runerr"><span class="s"></span>'
                         f'<span class="e">and {extra} more from '
                         f'{html_escape(s["source"])}</span></div>')
    detail = "".join(lines) or (
        '<div class="runerr"><span class="e">No source reported an error, so the run '
        'was marked partial by something outside the fetchers.</span></div>')
    kept = ", ".join(f'{s["source"]} kept {s.get("rows_fetched", 0)}'
                     for s in failed if s.get("rows_fetched"))
    st.markdown(
        f'<div class="state err"><div class="t">Run {last_run["id"]} finished partial'
        f'</div><div class="d">{detail}'
        + (f'<div class="runkept">{html_escape(kept)} rows despite the above.</div>'
           if kept else "")
        + '</div></div>', unsafe_allow_html=True)

def _spine_label(headline: str) -> str:
    """A spine row is a glance, not a sentence: the ticker prefix and the date
    tail go, the substance stays."""
    text = (headline or "").split(": ", 1)[-1]
    for tail in (" loses exclusivity", "):"):
        text = text.split(tail)[0]
    return text


def _spine_key(item) -> str:
    """A stable, URL-safe id for a forward-dated item, so a click on the spine can
    round-trip through the URL and be matched back to the same item on rerun. The
    feed is deterministic per company, so a content hash is stable across reruns."""
    seed = f"{item.get('kind')}|{(item.get('date') or '')}|{item.get('headline') or ''}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]


def _cat_short_date(value) -> str:
    """A compact date for a catalyst box. A full date reads "Jul 27"; a month-only date,
    the coarser confidence the derivation stores, reads "Aug"; anything else is left as
    written rather than guessed at."""
    text = str(value or "")
    try:
        if len(text) >= 10:
            return dt.date.fromisoformat(text[:10]).strftime("%b %-d")
        if len(text) == 7:
            return dt.date.fromisoformat(text + "-01").strftime("%b")
    except ValueError:
        pass
    return text


def _cat_phase_study(title: str) -> tuple[str, str]:
    """Split a derived readout title, stored as "Phase 3, <study>", into the phase tag and
    the study text, so the box can grey the phase and lead with what distinguishes the
    trial. A title without that shape returns no phase and the whole string."""
    text = (title or "").strip()
    if text.startswith("Phase ") and ", " in text:
        phase, study = text.split(", ", 1)
        return phase, study
    return "", text


# --- Catalysts: Drivers and risks ------------------------------------------------------
# Scoped to the two lists and carried with their markup. A list is one grid, so every
# lead in it takes the width of the longest and the texts start on one line; a row is
# display: contents, so it can be a link to its registry page without breaking the grid.
# Each block pads its foot by the rem Streamlit's markdown pulls back up, so a fold drawn
# under a list never sits on its last row.
_DR_CSS = """<style>
.dr-wrap { padding-bottom: 1rem; }
/* At stake, drawn under this section on the same tab: a columns block is not an element
   container, so the section rule's spacing missed it and the met and missed buttons sat
   5 px over the rule. Each row centres its buttons on its two lines. */
.st-key-cat_stakes { margin-top: 0.55rem; }
.st-key-cat_stakes .stButton button { min-height: 28px; padding: 0.1rem 0.5rem; }
.dr-h { display: flex; align-items: baseline; gap: 0.6rem; margin: 0.75rem 0 0.45rem; }
.dr-h .k { font-size: 11px; font-weight: 700; letter-spacing: 0.07em;
           text-transform: uppercase; color: var(--text); }
.dr-h .b { font-size: 11px; color: var(--muted); }
.dr-list { display: grid; grid-template-columns: max-content minmax(0, 1fr);
           column-gap: 0.9rem; row-gap: 0.34rem; align-items: baseline; }
.dr-row { display: contents; color: inherit; text-decoration: none; }
.dr-lead { font-family: var(--font-mono); font-size: 11.5px; color: var(--text);
           white-space: nowrap; }
.dr-lead.date { color: var(--muted); }
.dr-m { font-family: var(--font-mono); font-size: 9.5px; font-weight: 600;
        color: var(--muted); margin-left: 4px; cursor: help; }
.dr-text { font-size: 12.5px; line-height: 1.4; color: var(--text); min-width: 0; }
a.dr-row:hover .dr-text { color: var(--up); }
.dr-note { font-size: 11px; color: var(--muted); margin-top: 0.45rem; }
.dr-empty { font-size: 12px; color: var(--muted); }
</style>"""


def _dr_href(row: dict):
    """The registry page a row opens: the event's own source, or the trial a slip names.
    Only a web address is linked, never another scheme a stored value might carry."""
    url = row.get("source") or (f"https://clinicaltrials.gov/study/{row['nct_id']}"
                                if row.get("nct_id") else None)
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def _dr_tip(kind: str, row: dict) -> str:
    """The hover text behind a row: what the number is and where it comes from. Words a
    reader can ask for, so they cost nothing on the screen."""
    if kind == "driver":
        if row.get("model") and row.get("value_kind") == "stake":
            # A derived stake says so: its legs are published transition rates, not a
            # success and failure case anyone wrote down.
            lead = (f"Model output, {row['lead_note']}" if row.get("lead_note")
                    else "Model output")
            return (f"{lead}: the swing between the met and missed cases, a share, "
                    f"{(row.get('pct_of_price') or 0):.1%} of the price. "
                    + (row.get("title") or ""))
        if row.get("model"):
            return (f"Model output: {row['asset']}'s risk-adjusted value a share, "
                    f"{(row.get('pct_of_price') or 0):.1%} of the price. "
                    + (row.get("title") or ""))
        return row.get("title") or ""
    if row.get("kind") == "exclusivity":
        # The row's own share text, so the hover never reads a tenth off the lead.
        share = row.get("share_text") or (f"{row['share_of_revenue']:.1%}"
                                          if row.get("share_of_revenue") is not None else None)
        return " · ".join(x for x in (
            f"{share} of the latest year's revenue" if share else None,
            row.get("basis")) if x)
    if row.get("kind") == "slip":
        return (f"Primary completion moved from {row.get('old')} to {row.get('new')}, "
                f"seen {row.get('detected')}")
    if row.get("kind") == "pool":
        kept = str(row.get("lead") or "").replace(" kept", "")
        ind = str(row.get("indication") or "")
        if ind[1:2].islower():           # "Obesity" mid-sentence, but "HIV infections" kept
            ind = ind[:1].lower() + ind[1:]
        return (f"Model output: with {row.get('pool_drugs')} drugs sharing the {ind} pool, "
                f"the company's forecast keeps {kept} of the patients it would reach alone.")
    return ""


def _dr_attr(text) -> str:
    """A value for a double-quoted attribute. Not ``html.escape``: by the time the
    Catalysts tab draws, the page's own code has bound ``html`` to a list of markup."""
    return html_escape(str(text or "")).replace('"', "&quot;")


def _dr_list(rows: list, kind: str) -> str:
    """One list as markup: the lead (a number, else the month), then the row's text."""
    out = []
    for r in rows:
        dated = kind == "driver" and not r.get("model")
        marker = ""
        if kind == "driver" and r.get("model"):
            # A stake's marker says what kind of stake it is, derived or stated, as the
            # row's tooltip does, since the marker's own title is what shows over it.
            said = (f"Model output, {r['lead_note']}" if r.get("lead_note")
                    else "Model output")
            marker = f'<span class="dr-m" title="{_dr_attr(said)}">M</span>'
        tip = _dr_tip(kind, r)
        href = _dr_href(r)
        attrs = f' title="{_dr_attr(tip)}"' if tip else ""
        if href:
            tag, attrs = "a", (f' href="{_dr_attr(href)}" target="_blank"'
                               f' rel="noopener"{attrs}')
        else:
            tag = "div"
        out.append(
            f'<{tag} class="dr-row" data-kind="{_dr_attr(r.get("kind") or kind)}"'
            f'{attrs}><span class="dr-lead{" date" if dated else ""}">'
            f'{html_escape(r["lead"])}{marker}</span>'
            f'<span class="dr-text">{html_escape(r["text"])}</span></{tag}>')
    return f'<div class="dr-list {kind}">{"".join(out)}</div>'


def _drivers_and_risks(api_base: str, ticker: str, feed_rows=None) -> None:
    """Drivers and risks, the first section of the Catalysts tab (company-scorecard.md 1.5
    and 5.4): Drivers, the events of the next 12 months, value-bearing first, beside Risks,
    the exclusivity losses of the next 24 months, readouts that slipped and crowded
    patient pools.

    It reads only what the page already holds for the minute: the scorecard inside the
    Comps payload for the exclusivity losses, the focal company's comps-context for the
    events and the pools, and the change feed for the slips. ``drivers.section`` ranks
    and words every row, the same function Key insights takes its Next from, so the two
    tabs cannot disagree about what comes first."""
    import drivers as DRV
    if getattr(DRV, "REVISION", 0) < 4:
        DRV = importlib.reload(DRV)

    company, today, board_problem = None, None, None
    try:
        board = (_comps_valuation_payload(api_base) or {}).get("scorecard")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        board, board_problem = None, str(exc)
    if isinstance(board, dict) and not board.get("error"):
        company = (board.get("companies") or {}).get(ticker)
        today = board.get("today")
    elif board_problem is None:
        board_problem = (str(board.get("error")) if isinstance(board, dict)
                         else "no scorecard in the answer")
    try:
        context = _comps_context(api_base, ticker)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        context = {"error": str(exc)}

    part = DRV.section(ticker, context, company, feed_rows or [], today)
    drivers_part, risks_part = part["drivers"], part["risks"]
    notes = []
    if part["state"] == "ok" and part.get("message"):
        notes.append(part["message"])
    if isinstance(context, dict) and context.get("complete") is False:
        # The API answers before the model's values are warm and says so. The ranking
        # then has no value to lead with, so the reader is told rather than shown a list
        # that will reorder in a minute. Key insights reads the same answer.
        notes.append("Model values are still being computed. Reload in a minute.")
    if board_problem:
        notes.append(f"The scorecard did not load: {board_problem.rstrip('.')}. "
                     "Exclusivity losses are left out.")

    def _notes_html(skip=None) -> str:
        return "".join(f'<div class="dr-note">{html_escape(n)}</div>'
                       for n in notes if n != skip)

    section(html_escape(part["title"]), basis=part["basis"])
    if part["state"] != "ok":
        st.markdown(_DR_CSS + '<div class="dr-wrap"><div class="dr-empty">'
                    f'{html_escape(part["message"])}</div>{_notes_html(part["message"])}'
                    "</div>", unsafe_allow_html=True)
        return

    # A list with no row is not drawn and the other takes the width (1.5).
    shown = [k for k, rows in (("drivers", drivers_part["rows"]),
                               ("risks", risks_part["rows"])) if rows]
    slots = (dict(zip(shown, st.columns([1.25, 1], gap="large")))
             if len(shown) == 2 else {shown[0]: st.container()})
    if "drivers" in slots:
        with slots["drivers"]:
            st.markdown(
                _DR_CSS + '<div class="dr-wrap"><div class="dr-h"><span class="k">'
                f'{html_escape(drivers_part["title"])}</span><span class="b">'
                f'{html_escape(drivers_part["basis"])}</span></div>'
                + _dr_list(drivers_part["shown"], "driver") + "</div>",
                unsafe_allow_html=True)
            if drivers_part["more"]:
                with st.expander(drivers_part["more_label"], expanded=False):
                    st.markdown(_dr_list(drivers_part["more"], "driver"),
                                unsafe_allow_html=True)
    if "risks" in slots:
        with slots["risks"]:
            st.markdown(
                _DR_CSS + '<div class="dr-wrap"><div class="dr-h"><span class="k">'
                f'{html_escape(risks_part["title"])}</span></div>'
                + _dr_list(risks_part["rows"], "risk") + "</div>",
                unsafe_allow_html=True)
            # The exclusivity losses left out for slips and pools, as Drivers folds its rest.
            if risks_part.get("more"):
                with st.expander(risks_part["more_label"], expanded=False):
                    st.markdown(_dr_list(risks_part["more"], "risk"),
                                unsafe_allow_html=True)
    if notes:
        st.markdown(f'<div class="dr-wrap">{_notes_html()}</div>', unsafe_allow_html=True)


def _catalyst_spine_item(cat) -> dict:
    """A catalyst row for the spine, built from the fuller catalyst list rather than the
    60-day feed, so the horizon shows every upcoming readout out to two years, not only
    the ones inside the note window. Carries the study URL and the full title, so on the
    rail a hover previews the trial and a click opens its page."""
    regulatory = cat.get("catalyst_type") in ("PDUFA", "EMA decision", "AdCom")
    headline = (f'{cat.get("ticker", "")} {cat.get("catalyst_type", "")}: '
                f'{cat.get("title", "")} ({cat.get("expected_date", "")})')
    nct = cat.get("description") or ""
    full = f'{cat.get("title", "")} ({cat.get("expected_date", "")})'
    full = f"{full} · {nct}" if nct.startswith("NCT") else full
    item = {"kind": "catalyst", "date": cat.get("expected_date"), "headline": headline}
    return {"key": _spine_key(item), "date": cat.get("expected_date"),
            "label": _spine_label(headline), "headline": headline, "kind": "catalyst",
            "significance": "medium", "reason": None, "detail": cat.get("description"),
            "full": full, "url": cat.get("source_url"),
            "colour": TK.FLAG if regulatory else TK.UP, "flagged": regulatory}


def _spine_items(feed_items: list, catalysts: list | None = None) -> list:
    """Forward-dated items for the horizon rail: exclusivity from the feed, and catalysts
    from the fuller two-year list so the rail is not capped at the note's 60-day window."""
    items = []
    for it in feed_items:
        if it.get("kind") != "loe":
            continue                   # catalysts come from the fuller list below; the
                                       # rest already happened and the spine is ahead
        modality = (it.get("modality") or "").lower()
        colour = (TK.ORANGE_BOOK if modality.startswith("small")
                  else TK.PURPLE_BOOK if modality.startswith("bio") else TK.MUTED)
        items.append({"key": _spine_key(it), "date": it.get("date"),
                      "label": _spine_label(it.get("headline")),
                      "headline": it.get("headline"), "kind": "loe",
                      "significance": it.get("significance"),
                      "reason": it.get("reason"), "detail": it.get("detail"),
                      "colour": colour, "flagged": False})
    items += [_catalyst_spine_item(cat) for cat in (catalysts or [])]
    return items


def _spine_cliff(assets: list) -> dict:
    """Per-year counts beyond 24 months, orphan excluded: the same convention as
    the LOE tab, so the two views cannot disagree."""
    cliff: dict[int, int] = {}
    two_years_out = dt.date.today().year + 2
    for asset in assets:
        if (asset.get("loe_basis") or "") == "orphan exclusivity":
            continue
        year = int((asset.get("loe") or "0000")[:4] or 0)
        if year > two_years_out:
            cliff[year] = cliff.get(year, 0) + 1
    return cliff


# The horizon rail draws catalysts out to two years, so it reads the fuller catalyst
# list rather than the 60-day feed the note sections use.
spine_cats = api_get(api_base, f"/catalysts?within_days=760&"
                     f"ticker={urllib.parse.quote(ticker)}")
spine_items = _spine_items(feed, spine_cats if isinstance(spine_cats, list) else [])
selected_key = (st.query_params.get("sel") or "") or None
pinned = next((it for it in spine_items if it["key"] == selected_key), None)

# The pinned item sits above the tabs, so selecting a point on the spine cross-links
# to a panel visible on every tab. Clicking a tick navigates to ?…&sel=key (a pure
# SVG anchor, no script); this reads it back and draws the hairline to it.
if pinned:
    detail = html_escape(pinned.get("detail") or "") if pinned.get("detail") else ""
    reason = (f'<span class="why">{html_escape(pinned["reason"])}</span>'
              if pinned.get("reason") else "")
    st.markdown(
        f'<div class="pinned"><div class="pin-head"><span class="pin-tag">pinned '
        f'from spine</span> <a class="pin-clear" href="?ticker='
        f'{urllib.parse.quote(ticker)}">clear</a></div>'
        f'<div class="pin-body"><span class="d">{(pinned.get("date") or "")[:10]}'
        f'</span> {html_escape(pinned.get("headline") or "")} {reason}</div>'
        + (f'<div class="pin-detail">{detail}</div>' if detail else "")
        + "</div>", unsafe_allow_html=True)

# The rail is a reference column, not a view: dates and one line of what each is. Every
# point of width it takes comes off the tab beside it, where the charts and statements
# are, so it is sized to the longest date plus a readable clause and no more.
main, rail_col = st.columns([1, 0.27], gap="medium")

with rail_col:
    # Marker so the theme can find and drop this column on the Universe tab, where the
    # single-company rail is out of place against a cross-coverage view.
    st.markdown('<span class="rail-anchor"></span>', unsafe_allow_html=True)
    R.show(CH.timeline_spine(
        spine_items, dt.date.today(), 300, 920,
        cliff_years=_spine_cliff(exclusivities), selected_key=selected_key,
        link_base=f"?ticker={urllib.parse.quote(ticker)}&sel="), css_class="rail")
    st.markdown('<div class="byline">Forward-dated only. Click a point to pin it '
                'above the tabs. Amber is a regulatory date needing review; orange '
                'and purple are the two FDA books.</div>', unsafe_allow_html=True)

# --- Time machine ---------------------------------------------------------
# A date in the sidebar puts the terminal into a clearly marked historical mode:
# the banner renders on every tab, and the Universe tab carries the reconstructed
# state. Read-only throughout; clearing the box returns to live.
st.sidebar.markdown("#### Time machine")
asof_text = st.sidebar.text_input(
    "State as of (YYYY-MM-DD)", key="asof_date",
    help="Reconstructs tracked state from the snapshot history. Blank = live.")
asof_state = None
if (asof_text or "").strip():
    asof_state = api_get(api_base, f"/as-of?date={urllib.parse.quote(asof_text.strip())}") \
        if len(asof_text.strip()) >= 8 else None
    if asof_state is None:
        st.sidebar.markdown('<div class="byline">Not an ISO date yet.</div>',
                            unsafe_allow_html=True)

if asof_state:
    st.markdown(
        f'<div class="asof-banner">HISTORICAL MODE — tracked state as of '
        f'{asof_state["as_of"]} · read only · snapshot history begins '
        f'{(asof_state.get("history_begins") or "—")[:10]} · clear the sidebar date '
        'to return to live</div>', unsafe_allow_html=True)

with main:
    # Which tabs a company has depends on the engine it is read on, and then on whether it
    # sells anything. Portfolio is revenue mix and loss of exclusivity: a major always has
    # both, a mid-cap has them once it markets something, and a platform developer with no
    # approved product has neither, which used to render as three empty charts. Runway is
    # cash against burn, which says nothing about a company earning 60bn a year. A company
    # the engine cannot place keeps both, since an absent engine is not evidence either
    # way.
    _engine = (company or {}).get("engine") or ""
    _stage = (company or {}).get("stage") or "unknown"
    _sells = _stage != "clinical"
    _wanted = [("universe", "Universe"), ("insights", "Key insights"),
               ("prices", "Prices"), ("financials", "Financials"),
               ("pipeline", "Pipeline")]
    if _engine == "pharma" or (_engine != "cellgene" and _sells):
        _wanted.append(("portfolio", "Portfolio"))
    _wanted.append(("catalysts", "Catalysts"))
    _wanted.append(("forecast", "Forecast"))
    # Themes reads coverage by modality rather than by ticker, which is the question the
    # biotech and cell and gene engines exist to ask. Every big pharma company spans every
    # modality, so on that engine the tab grouped all eighteen under most headings and
    # answered nothing a reader came for.
    if _engine != "pharma":
        _wanted.append(("themes", "Themes"))
    if _engine == "cellgene" or not _sells or _engine not in ("pharma", "biotech"):
        _wanted.append(("runway", "Runway"))
    _wanted += [("comps", "Comps"), ("news", "News")]
    _panels = dict(zip([name for name, _label in _wanted],
                       st.tabs([label for _name, label in _wanted])))
    universe_tab = _panels["universe"]
    insights_tab = _panels["insights"]
    prices_tab = _panels["prices"]
    financials_tab = _panels["financials"]
    pipeline_tab = _panels["pipeline"]
    catalysts_tab = _panels["catalysts"]
    forecast_tab = _panels["forecast"]
    themes_tab = _panels.get("themes")
    comps_tab = _panels["comps"]
    news_tab = _panels["news"]
    portfolio_tab = _panels.get("portfolio")
    runway_tab = _panels.get("runway")
    universe_page.click_pending_tab()

    # --- Universe: what moved across coverage since you last looked -------
    with universe_tab:
        if asof_state:
            section(f"Universe as of {asof_state['as_of']}", "reconstructed")
            by_ticker = asof_state.get("by_ticker") or {}
            if not by_ticker:
                state("Nothing tracked at that date",
                      "The snapshot history begins "
                      f"{(asof_state.get('history_begins') or 'later')[:10]}; pick a "
                      "date on or after it to see reconstructed state.")
            else:
                fin = asof_state.get("financials") or {}
                st.dataframe(pd.DataFrame([
                    {"Ticker": tk,
                     "Trials tracked": entry.get("trials", 0),
                     "Approvals known": entry.get("approvals_known", 0),
                     "Revenue then, bn": (fin[tk]["revenue"] / 1e9
                                          if fin.get(tk) and fin[tk].get("revenue")
                                          is not None else None),
                     "FY": (str(fin[tk]["fiscal_year"])
                            if fin.get(tk) and fin[tk].get("fiscal_year") else "—"),
                     "Statuses": ", ".join(f"{status} {count}" for status, count
                                           in sorted((entry.get("statuses") or {}).items()))}
                    for tk, entry in sorted(by_ticker.items())]),
                    width="stretch", hide_index=True,
                    column_config={"Revenue then, bn": st.column_config.NumberColumn(
                        format="%.1f")})
                note('Reconstructed from the append-only snapshot table at field '
                     'grain: trial status, phase and completion date as they stood; the '
                     'financial report in force at the date; and the approvals whose '
                     'first sighting was on or before it. Everything else in the app '
                     'stays live.')
                approvals_then = asof_state.get("approvals") or []
                if approvals_then:
                    section("Approvals known by then", len(approvals_then))
                    st.dataframe(pd.DataFrame([
                        {"Ticker": a["ticker"], "Application": a["application_number"],
                         "Brand": a.get("brand_name") or "—",
                         "Approved": a.get("approval_date") or "—",
                         "First seen": (a.get("first_seen") or "")[:10]}
                        for a in approvals_then]),
                        width="stretch", hide_index=True)

        # Coverage means this engine's coverage. A grid of seventy panels is a wall
        # rather than a view, and two thirds of it answers a different question from the
        # one the open engine is asking: an approval at Merck is not a signal a reader on
        # the cell and gene engine came for. The API returns the universe, so the engine's
        # own ticker set narrows it here.
        _covered = set(tickers)
        _engine_name = _ENGINE_LABELS.get(engine, "coverage").lower()

        # The front page of the engine: the few things ranked by how much they matter
        # rather than by when they happened. The feed below answers "what moved" and
        # answers it four hundred times; this answers "what would you be embarrassed not
        # to know", which is a different question and has to be asked first.
        # Three views under one tab. Markets and policy used to sit above the
        # headlines, which put the two slowest-moving things on the page first and
        # pushed what actually moved this week below them. They are still one click
        # away and they still belong to the universe rather than to a company, so
        # they are views here rather than tabs of their own.
        _view = st.segmented_control(
            "Universe view", ["Overview", "Markets", "Policy"], default="Overview",
            key="universe_view", label_visibility="collapsed") or "Overview"

        _all_changes = api_get(api_base, "/changes")
        universe_feed = [it for it in _all_changes
                         if (it.get("ticker") or "") in _covered
                         or it.get("kind") == "market"]

        if _view == "Markets":
            _markets_view(api_base, universe_feed)
        elif _view == "Policy":
            _policy_view(api_base)
        elif (_universe_redesigned(ticker, _view)
              and universe_page.render(api_base, ticker)):
            pass
        else:
            _universe_overview(api_base, engine, _engine_name, _covered,
                               _all_changes, universe_feed)

    with insights_tab:
        # The company on one page (company-scorecard.md 1.3): where it stands against its
        # cohort and what changed. The sparkline, What happened and Dated ahead are gone:
        # Prices owns the price, deals and readouts reach What changed through the feed,
        # and Next is the head of the Catalysts list.
        _key_insights_tab(api_base, ticker, feed, prices)

    # --- Prices ----------------------------------------------------------
    with prices_tab:
        # Everything above the chart on one line. The tab used to stack a heading, a
        # refresh button, an interval row, a window row, a stats strip and a row of
        # toggles before the chart began, which put the chart itself below the fold on
        # the tab whose whole subject is the chart.
        section("Price", prices.get("currency") or "")
        ctrl_int, ctrl_view, ctrl_events, ctrl_grid, ctrl_refresh = st.columns(
            [3.2, 1.3, 0.8, 0.7, 1.0], vertical_alignment="center")
        with ctrl_events:
            show_events = st.toggle("Events", value=True, key=f"events_{ticker}")
        with ctrl_grid:
            show_grid = st.toggle("Grid", value=True, key=f"grid_{ticker}")
        with ctrl_refresh:
            if st.button("Refresh", key="refresh_prices", width="stretch"):
                run_refresh(api_base, f"/refresh?ticker={urllib.parse.quote(ticker)}",
                            "price_run", f"Refreshing {ticker} from Yahoo")
                st.rerun()

        # The bar interval and the line/candle view. The window radio comes after the base
        # series loads, since which windows can be filled depends on how far it reaches.
        with ctrl_int:
            interval = st.segmented_control(
                "Interval", PRICE_INTERVALS, default="1D", key="price_interval_v2",
                label_visibility="collapsed") or "1D"
        with ctrl_view:
            view = st.segmented_control(
                "View", [price_chart.LINE, price_chart.CANDLE],
                default=price_chart.CANDLE, key="price_view",
                label_visibility="collapsed") or price_chart.CANDLE

        # 1D/1W/1M read the 5y daily already fetched; sub-daily reads the intraday base.
        base, rule, intraday = _INTERVAL_BASE[interval]
        base_resp = (prices if base == "1d" else
                     api_get(api_base, f"/companies/{ticker}/prices?interval={base}"))
        base_points = base_resp.get("points") or []
        if not base_points:
            state(f"No {interval} history yet",
                  "Press Refresh prices to pull the history from Yahoo. Prices expire "
                  "after 15 minutes, so a second press inside that window is a no-op."
                  if base == "1d" else
                  f"No {interval} bars on file yet. Intraday is a rolling window the free "
                  "feed caps at about two months for minutes and two years for hours; "
                  "press Refresh prices to fill it.")
        else:
            frame = pd.DataFrame(base_points)
            frame["as_of"] = pd.to_datetime(frame["as_of"])
            # Resample the base into the asked bar: open first, high max, low min, close
            # last, volume sum. 5m, 1H and 1D pass through as their own base.
            if rule:
                agg = (frame.set_index("as_of").resample(rule)
                       .agg({"open": "first", "high": "max", "low": "min",
                             "close": "last", "volume": "sum"})
                       .dropna(subset=["close"]).reset_index())
                bar_frame = agg
                out = agg.copy()
                out["as_of"] = agg["as_of"].dt.strftime(
                    "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d")
                chart_rows = out.to_dict("records")
            else:
                bar_frame = frame
                chart_rows = base_points
            held = (bar_frame["as_of"].max() - bar_frame["as_of"].min()).days

            # Only offer windows the loaded base can fill. The window sets the chart's
            # opening view; pan and zoom (two-finger scroll) refine it from there.
            choices = [(label, days) for label, days in PRICE_WINDOWS
                       if days is None or days <= held + 45]
            labels = [label for label, _ in choices]
            # Open on 5Y rather than Max, so the daily chart does not start fully zoomed
            # out over ten years; Max and pan reach the older bars.
            default_win = labels.index("5Y") if "5Y" in labels else len(labels) - 1
            # The window picker and the figures it describes share a row. Stacked they
            # were two bands of chrome between the controls and the chart, and the
            # figures are a reading of the window rather than a separate subject.
            win_col, stat_col = st.columns([2.1, 3.4], vertical_alignment="center")
            with win_col:
                span = st.radio("Window", labels, index=default_win, horizontal=True,
                                key="price_window", label_visibility="collapsed")
            days = dict(choices)[span]

            windowed = (bar_frame if days is None else
                        bar_frame[bar_frame["as_of"]
                                  >= bar_frame["as_of"].max() - pd.Timedelta(days=days)])
            opened, latest_close = windowed["close"].iloc[0], windowed["close"].iloc[-1]
            change = (latest_close - opened) / opened * 100 if opened else None
            low, high = windowed["low"].min(), windowed["high"].max()
            low = windowed["close"].min() if pd.isna(low) else low
            high = windowed["close"].max() if pd.isna(high) else high
            with stat_col:
                st.markdown(
                    '<div class="stats stats-tight">'
                    f'<span class="stat"><span class="k">last</span>'
                    f'<span class="v">{T.num(latest_close, 2)}</span></span>'
                    f'<span class="stat"><span class="k">as of</span>'
                    f'<span class="v">{str(chart_rows[-1]["as_of"])}</span></span>'
                    f'<span class="stat"><span class="k">{span} change</span>'
                    f'<span class="v {"risk" if (change or 0) < 0 else ""}">'
                    f'{T.pct(change)}</span>{_vs_sector(api_base, ticker, span)}</span>'
                    f'<span class="stat"><span class="k">{span} range</span>'
                    f'<span class="v">{T.num(low, 2)} to {T.num(high, 2)}</span></span>'
                    f'<span class="stat"><span class="k">bars</span>'
                    f'<span class="v">{len(windowed)}</span></span></div>',
                    unsafe_allow_html=True)

            # Major events on the chart, from the data rather than typed in: FDA approvals
            # (up arrow, below the bar) and any loss-of-exclusivity date inside the window
            # (down arrow, above it). Both come from the approvals endpoint. Future LOE
            # dates sit years past the price history, so they fall outside the window and
            # are left to the LOE tab and the horizon rail.
            approvals = api_get(
                api_base, f"/companies/{ticker}/approvals").get("approvals") or []
            events = []
            for appr in approvals:
                name = appr.get("brand_name") or appr.get("generic_name")
                if appr.get("approval_date") and name:
                    events.append({"date": appr["approval_date"], "label": name,
                                   "kind": "approval"})
                if appr.get("loe") and name:
                    events.append({"date": appr["loe"], "label": f"{name} LOE",
                                   "kind": "loe"})

            # A lightweight-charts component with native two-finger zoom that stretches
            # the sticks and auto-fits the y-axis. Drawing trendlines on it is gone: it
            # did not work, and the toggle, its Clear button and the annotation
            # round-trip cost a control row on a tab that has to fit one screen.
            data = price_chart.series_data(chart_rows, view, intraday)
            # "rule" draws the chart's gridlines only, so it takes the faint token: a
            # price chart draws far more lines than a table draws borders, and at the
            # hairline weight the mesh competes with the series it is there to measure.
            theme = {"ground": TK.GROUND, "muted": TK.MUTED, "rule": TK.RULE_FAINT,
                     "rule_strong": TK.RULE_STRONG, "up": TK.UP, "down": TK.DOWN,
                     "flag": TK.FLAG}

            # Gridlines off is the background colour rather than a transparent value,
            # which the chart library would fall back to its own default for.
            theme = dict(theme, rule=TK.RULE_FAINT if show_grid else TK.GROUND)

            # Approval and LOE markers only when the toggle is on, so the price can be read
            # clean.
            markers = price_chart.event_markers(
                chart_rows, events if show_events else [], intraday)
            drawchart.draw_chart(
                data=data, markers=markers, mode=view, intraday=intraday,
                lines=[], draw_mode=False, theme=theme,
                view_key=f"{ticker}|{interval}|{view}", height=PRICE_CHART_HEIGHT,
                key=f"drawchart_{ticker}")

            legend = ('<span style="color:var(--up)">▲</span> FDA approval'
                      '&nbsp;&nbsp;<span style="color:var(--down)">▼</span> loss of '
                      f'exclusivity &nbsp;·&nbsp; {len(markers)} on this view')
            detail = ("Markers are read from the approvals and exclusivity data; a date "
                      "outside the loaded window is not drawn. ")
            if intraday:
                detail += ("Intraday is a rolling window from the free feed: minutes "
                           "reach back about two months, hours about two years. Older "
                           "bars are unavailable, not missing.")
            # Legend visible, the caveats folded. Two stacked bylines under the chart were
            # sixty pixels of the height the chart wanted.
            st.markdown(f'<div class="byline chart-legend">{legend}</div>',
                        unsafe_allow_html=True)
            note(detail)

    # --- Financials ------------------------------------------------------
    with financials_tab:
        # The widget key is the source of truth, read before the widget renders. Keeping
        # a second copy of the choice would fetch on the previous basis for one rerun,
        # so the grid would lag a click behind the control.
        basis_key = f"fin_basis_{ticker}"
        wanted = st.session_state.get(basis_key, "Quarterly")

        def fetch(basis):
            # Twelve columns, not six. A pharma quarter carries stocking and launch
            # timing, so a year and a half of them cannot show what is seasonal and what
            # is the trend, and the growth lens needs a year of history behind the oldest
            # column it prints.
            return api_get(api_base, f"/companies/{ticker}/statements"
                                     f"?basis={basis}&periods={STATEMENT_PERIODS}")

        built = fetch("annual" if wanted == "Annual" else "quarterly")
        if built["basis"] == "quarterly" and not built["has_interim"]:
            built = fetch("annual")     # a 20-F filer has no quarters to show
        snapshot = built.get("snapshot")

        # --- The two readings, side by side -------------------------------
        # A quarter's income statement and a year's cash flow are different bases,
        # and stacking them put 25.3bn of quarterly revenue directly above 19.7bn of
        # annual free cash flow in the same tiles at the same weight. Two columns
        # separate them structurally rather than by a label, and the page loses the
        # height it was spending saying so twice.
        # Two full-width rows rather than two half-width columns. Each block's figures
        # then fit on one line: at half a page the period strip wrapped R&D onto a second
        # row and the cash strip wrapped acquisitions, so a four-figure block stood two
        # deep and the two blocks disagreed about where their own baseline was.
        left, right = st.container(), st.container()

        if snapshot:
            with left:
                section("The quarter" if built["basis"] == "quarterly" else "The year",
                        snapshot_meta(snapshot), basis=snapshot.get("label") or "")
                st.markdown(snapshot_strip(snapshot), unsafe_allow_html=True)
            with right:
                _cash_block(api_base, ticker)
        elif built["is_sec_filer"]:
            # A company with no revenue is not a company with no financials. Dyne has
            # thirty-one quarters of equity and twenty-three of net loss on file, and
            # this tab told it there were none, because the snapshot leads on revenue
            # and returns nothing without it. Seven companies in the universe read that
            # way, all of them in the two engines built for companies that have no
            # product yet.
            _pre_revenue_blocks(api_base, ticker, left, right)
        else:
            state(f"{ticker} does not file with the SEC",
                  "EDGAR holds no company facts for a company the SEC does not "
                  "register. Roche and Bayer each publish a workbook of their own, "
                  f"which the refresh reads, and {ticker}'s has not loaded yet.")

        # The reported period, then the year it is guiding to. Consensus belongs here
        # rather than on the forecast tab: this is where the reported number it is being
        # compared against already sits.
        _street_block(api_base, ticker)

        if snapshot or built["is_sec_filer"]:
            # Every period the API returns, which is every period on file: forty quarters
            # or seventeen years. This used to cut the quarterly panel to the last four,
            # and four points cannot show a cycle, a margin compressing or a cliff
            # arriving, which is the entire reason to draw a trend rather than print the
            # latest number twice.
            #
            # Built as SVG rather than through Altair. A chart made inside a hidden tab
            # is measured at a few pixels and draws about 160px wide for good (see the
            # chart helper), and this panel has to hold its width on this tab.
            panel = trend_module.render(built.get("trend") or [], built["basis"])
            # The two histories share a row. One is how the business has performed and
            # the other is what it chose to spend on, both read across the same years,
            # and stacked they were three hundred pixels between the period figures at
            # the top of the tab and the statements at the foot of it.
            _trend_col, _alloc_col = st.columns(2, gap="medium")
            with _trend_col:
                if panel:
                    section("Growth against margin",
                            f'{len(built["trend"])} periods on file')
                    st.markdown(f'<div class="trend">{panel}</div>',
                                unsafe_allow_html=True)
                else:
                    # No revenue, so no growth and no margin. What a developer is judged
                    # on instead is whether the cash lasts, which is the same question
                    # the Runway tab answers at length and this says in one line.
                    _cash_panel(built)
            with _alloc_col:
                if snapshot:
                    _allocation_band(api_base, ticker)

        if snapshot or built["is_sec_filer"]:
            section("Statements")
            # Segmented controls rather than radios, the same as the prices tab. Three
            # horizontal radio groups carry three sets of radio dots and their labels
            # wrapped at this width, so the row stood at 67px; as segments it is one
            # line and the statements grid starts that much higher up the page.
            controls = st.columns([0.85, 1.9, 1.6], vertical_alignment="center")
            with controls[0]:
                # An annual-only filer gets no toggle at all. Offering a control that
                # can only produce an empty grid is worse than not offering it.
                if built["has_interim"]:
                    st.segmented_control(
                        "Basis", ["Quarterly", "Annual"], default="Quarterly",
                        label_visibility="collapsed", key=basis_key)
            with controls[1]:
                _labels = [label for _, label in STATEMENT_ORDER]
                which = st.segmented_control(
                    "Statement", _labels, default=_labels[0],
                    label_visibility="collapsed", key=f"stmt_{ticker}") or _labels[0]
            with controls[2]:
                lens = st.segmented_control(
                    "Lens", LENSES, default=ABSOLUTE, label_visibility="collapsed",
                    key=f"lens_{ticker}") or ABSOLUTE

            key = next(k for k, label in STATEMENT_ORDER if label == which)
            block = built["statements"][key]
            if not block["periods"]:
                state(f"No {which.lower()} for this basis",
                      "The filer tags nothing here for the periods selected.")
            else:
                st.markdown(
                    statement_table(block, built["currency"], lens),
                    unsafe_allow_html=True)
                footnotes = []
                if not built["has_interim"]:
                    footnotes.append(
                        f"{ticker} files a 20-F and tags no interim periods, so this "
                        "is annual only.")
                if key == "cashflow" and built["basis"] == "quarterly":
                    footnotes.append(
                        "Cash flow columns are cumulative from the year start, which "
                        "is how a 10-Q reports them.")
                if footnotes:
                    st.markdown(f'<div class="fin-note">{" ".join(footnotes)}</div>',
                                unsafe_allow_html=True)

    # --- Comps -----------------------------------------------------------
    with comps_tab:
        # Two markers: one lets the theme size this tab's charts against the screen, the
        # other drops the horizon rail. The rail is one company's forward calendar and
        # this tab is every company at once, so its width belongs to the comparison.
        st.markdown('<span class="comps-anchor"></span><span class="no-rail"></span>',
                    unsafe_allow_html=True)
        # The Indications and Pipelines views stay cut to the open engine's own cohort:
        # ranking Lilly's pipeline against a clinical-stage biotech with no revenue is not
        # a comparison. The engine's ticker list is already resolved above for the picker,
        # so this needs no second request. The Companies view takes the whole universe:
        # its scorecard ranks each fixed cohort, and its Table view chooses its own peers,
        # so a peer from another engine can be added in it.
        _peers = set(tickers)
        _peer_rows = lambda rows: [r for r in rows if r.get("ticker") in _peers]

        # Three questions, three views. Companies opens first because it is the one an
        # analyst comes to the tab for: how the company compares with its peers, as one
        # chart of its cohort with the ranked table beside it, and the comparables table
        # one click away. The two cohort views keep their own tabs.
        _views = ["Companies"] + (["Indications"] if _engine == "pharma" else []) + [
            "Pipelines"]
        _vt = dict(zip(_views, st.tabs(_views, default="Companies")))
        with _vt["Companies"]:
            _comps_valuation_view(api_base, ticker, engine, not asof_state)
        if "Indications" in _vt:
            with _vt["Indications"]:
                _intro("Every drug the big pharma companies hold for one disease, whatever "
                       "its modality or mechanism: what it is, what its trials posted "
                       "against their comparators, its safety record, and what the model "
                       "says it is worth.")
                _indication_landscape(api_base, ticker)

        # --- R&D productivity and the phase matrix ----------------------------
        # Every frame the Pipelines view draws is fetched first, in one place, and the
        # charts below then sit wherever the layout wants them.
        board = api_get(api_base, "/productivity/scorecard")
        placed = _peer_rows(board["placed"])
        rows = _peer_rows(api_get(api_base, "/pipeline"))
        unattributed = sum(r.get("unattributed", 0) for r in rows)

        with _vt["Pipelines"]:
            _intro("Every company at once: where each sits on research productivity "
                   "against commercial performance, and how many compounds each has "
                   "in each phase of development.")
            # Everyone at once: where each company sits on research against commercial, and
            # the shape of every pipeline in one matrix.
            _score_col, _phase_col = st.columns(2, gap="medium")
            with _score_col:
                if placed:
                    section("R&D against commercial performance", f"{len(placed)} placed")
                    st.markdown(scorecard_chart.build(placed, highlight=ticker), unsafe_allow_html=True)
                    note(f"Right of the dashed line, R&D output above the cohort's; above "
                         f"it, commercial performance above the cohort's. Green is ahead on "
                         f"both, {ticker} is ringed, and a triangle on the edge sits beyond "
                         f"the plotted range. Hover a point for its scores.")


                # The R&D productivity table is gone and its captions with it: a fourteen
                # column grid and two hundred words of caveat were the tallest thing on a
                # tab whose subject is comparison, and every figure in it is a ratio the

            with _phase_col:
                # charts below already draw. This tab is read as charts.
                section("Compounds in development by phase",
                        "lead sponsored" + (f" · {unattributed} trials unattributed"
                                            if unattributed else ""))
                # No total column: it counts every phase, and carrying an all-phases figure
                # beside development-only columns is the disagreement this view just lost.
                grid = pd.DataFrame([{"Ticker": r["ticker"], **r["compounds"]} for r in rows])
                if grid[DISPLAY_PHASES].to_numpy().sum() == 0:
                    state("No compounds mapped",
                          "Press Refresh all in the top bar to pull trials from "
                          "ClinicalTrials.gov and bind each to the compound it studies.")
                else:
                    charted = [p for p in PIPELINE_PHASES if p not in POST_APPROVAL]
                    long = grid.melt(id_vars="Ticker", value_vars=charted,
                                     var_name="Phase", value_name="Compounds")
                    long["Phase"] = long["Phase"].replace(PHASE_MERGE)
                    long = long.groupby(["Ticker", "Phase"], as_index=False)["Compounds"].sum()
                    # The count is printed in the cell, so colour is a second reading of the
                    # same number, never the only one. Sqrt weight keeps the largest pipeline
                    # from flattening everyone else into one tone.
                    peak = max(int(long["Compounds"].max()), 1)
                    cells = {(row.Ticker, row.Phase): {
                                "count": int(row.Compounds),
                                "weight": (row.Compounds / peak) ** 0.5}
                             for row in long.itertuples() if row.Compounds}
                    # Eighteen rows of three: the matrix wants height, and its width was
                    # making it render short in a half-page column.
                    R.show(CH.heatmap_grid(list(grid["Ticker"]), DISPLAY_PHASES, cells,
                                           700, 600, highlight=ticker))



    with pipeline_tab:
        # --- Therapeutic areas: click a band to reveal its trials ---
        # Development trials drive the bars and the "in development" count. Two kinds of
        # work carry a development phase but are not new development, so they are pulled
        # out and flagged rather than counted in it: Phase 4, which runs after approval,
        # and long-term follow-up, extension and rollover studies, which follow a product
        # through the rest of its life. Each is a distinct muted cap on the bar and a
        # tagged pill, so they can be read without inflating the pipeline.
        every = api_get(api_base, f"/companies/{ticker}/trials")["trials"]
        LIFECYCLE = {"Phase 4": "post-approval", "Follow-up": "follow-up"}

        def _bucket(t):
            """The pill and segment a trial belongs to: its development phase, or the
            lifecycle bucket that takes it out of development."""
            if t["phase"] in POST_APPROVAL:
                return "Phase 4"
            if t.get("follow_up"):
                return "Follow-up"
            return PHASE_MERGE.get(t["phase"], t["phase"])

        # A marketed product running a new-indication trial is not a compound in
        # development: Zepbound and Verzenio are products, and counting them here made
        # the chart say 91 where the programme list below said 78. Their trials belong
        # to the product, and the Portfolio tab is where they read.
        # A marketed product running a new-indication trial is not a compound in
        # development: Zepbound and Verzenio are products, and counting their studies
        # here made the chart say 91 compounds where the programme list below said 78.
        # Their trials belong to the product, and the product fact sheet is where they
        # read. One set of compounds now drives the bars, the pills and the list.
        every = [t for t in every if not t.get("asset_is_marketed")]
        dev = [t for t in every if _bucket(t) in DISPLAY_PHASES]
        post = [t for t in every if _bucket(t) == "Phase 4"]
        followup = [t for t in every if _bucket(t) == "Follow-up"]

        # The count lives under the programme list, which is where it can be checked
        # against the compounds it counts. Saying it twice invited the two to disagree.
        # The chart is built here and drawn under "By area" below. It is a summary of
        # the list, and a summary that costs three quarters of the first screen buys
        # its space from the thing it summarises.
        _area_chart = None
        # Defined before the branch: the programme list below reads these, and a company
        # with no trials draws no pills to set them.
        area_pick: list = []
        phase_pick: list = []
        if not every:
            state(f"No trials on file for {ticker}",
                  "Press Refresh all in the top bar to pull ClinicalTrials.gov, "
                  "or pick another company in the sidebar.")
        else:
            # A compound is placed once per area, at the furthest phase it has reached
            # there, which is how a pipeline is read: a molecule in Phase 3 and still
            # running its Phase 1 work is a Phase 3 asset, counted once. Counting every
            # study instead made an area look larger for being run in more pieces.
            PHASE_RANK = {ph: i for i, ph in enumerate(
                list(DISPLAY_PHASES) + list(LIFECYCLE))}

            furthest: dict = {}
            for t in every:
                if not t.get("asset_id"):
                    continue           # no compound to attribute it to
                key = (t["area"], t["asset_id"])
                bucket = _bucket(t)
                if key not in furthest or PHASE_RANK.get(bucket, -1) > PHASE_RANK.get(
                        furthest[key], -1):
                    furthest[key] = bucket

            bucket_area = Counter((area, bucket)
                                  for (area, _asset), bucket in furthest.items())
            all_area = Counter(area for (area, _asset) in furthest)
            dev_area = Counter(area for (area, _asset), bucket in furthest.items()
                               if bucket in DISPLAY_PHASES)
            # Bars keep development order and shape; an area with only lifecycle work
            # falls to the end, so an approved product with no active development is
            # still on the chart and selectable.
            order = [a for a, _ in dev_area.most_common()]
            order += [a for a in all_area if a not in dev_area]
            counts = dict(all_area)

            # The selection is read before the chart is drawn, so the bars can dim,
            # but the chips are rendered after it: the chart is what tells you which
            # area to pick, so it comes first and the controls sit under it with the
            # phase pills, as one band of filters rather than two split around it.
            chosen = st.session_state.get(f"area_pills_{ticker}") or []

            # Stacked by phase so the shape of an area reads at a glance: one that is
            # all Phase 1 is a different proposition from one carrying Phase 3, even
            # at the same trial count. The phase ramp brightens toward market, so an
            # area's proximity to approval reads directly. Past the ramp, Phase 4 and
            # follow-up sit in the muted colour, flagged as lifecycle rather than
            # coloured as the next rung. Selecting dims the rest to the hairline colour
            # rather than fading opacity, which kept the segments legible.
            stack_rows = []
            for area in order:
                dimmed = bool(chosen) and area not in chosen
                segments = []
                for ph in DISPLAY_PHASES:
                    count = bucket_area.get((area, ph), 0)
                    if not count:
                        continue
                    segments.append({
                        "name": f"{ph}, {count} compound{'s' if count != 1 else ''}",
                        "value": count,
                        "colour": TK.RULE if dimmed else TK.PHASE_RAMP[ph]})
                for life, tag in LIFECYCLE.items():
                    count = bucket_area.get((area, life), 0)
                    if not count:
                        continue
                    segments.append({
                        "name": f"{life}, {count} compound{'s' if count != 1 else ''}, {tag}",
                        "value": count,
                        "colour": TK.RULE if dimmed else TK.MUTED})
                stack_rows.append({"label": area_label(area), "segments": segments})
            legend = [(p, TK.PHASE_RAMP[p]) for p in DISPLAY_PHASES]
            tags = [t for t, has in (("Phase 4", post), ("follow-up", followup)) if has]
            if tags:
                legend.append((" and ".join(tags) + ", post-development", TK.MUTED))
            # Sized for the column it sits in rather than the page it used to span.
            _area_chart = CH.stacked_bar(
                stack_rows, 560, max(170, 30 * len(order) + 30),
                value_fmt=lambda v: f"{v:.0f}", legend=legend)

            # Pills stay plain labels: rewriting a pill's own label as it is selected made
            # its highlight take two clicks. The count for what is selected shows in a line
            # beneath instead, so a number still appears only once something is highlighted.
            # The return value is captured, not just the session key, so the programmes
            # list below filters on the same pick in the same run rather than a rerun
            # behind. Keyed per company, since one company's areas are not another's.
            area_pick = st.pills(
                "Therapeutic area", order, selection_mode="multi",
                key=f"area_pills_{ticker}", label_visibility="collapsed") or []

            # Phase narrows the compound list the same way area does, so both pill rows
            # act on one thing. Phase 4 and Follow-up join the pills only when the company
            # has any. Labels stay plain for the same reason as the areas; the count for
            # what is picked shows beneath.
            bucket_counts = Counter(_bucket(t) for t in every)
            phase_options = list(DISPLAY_PHASES)
            if post:
                phase_options.append("Phase 4")
            if followup:
                phase_options.append("Follow-up")
            phase_pick = st.pills(
                "Phase", phase_options, selection_mode="multi",
                key=f"phase_pills_{ticker}", label_visibility="collapsed") or []


        # Side by side, because the chart is read against the list rather than instead
        # of it: the areas say what the company is, the rows say what it holds, and an
        # analyst scanning one wants the other in view. Stacked, the chart pushed the
        # first compound three quarters of the way down the screen; behind a tab it was
        # out of sight exactly when it was useful. In a column it is neither.
        _chart_col, _list_col = st.columns([1, 1.6], gap="medium")
        if _area_chart:
            with _chart_col:
                section(f"{ticker} by therapeutic area")
                R.show(_area_chart)
        with _list_col:
            # --- Programmes: the compounds behind the studies -------------------
            # A trial list answers what is running; this answers what is being developed.
            # Each row is a compound the company is trialling but does not yet sell, bound to
            # its studies through the intervention names the registry publishes.
            programmes = api_get(api_base,
                                 f"/companies/{ticker}/programmes").get("programmes") or []
            phase_order = ["Phase 3", "Phase 2/3", "Phase 2", "Phase 1/2", "Phase 1",
                           "Phase 4", "unphased"]

            # The pills above drive this list, so the spotlight on the chart and the compounds
            # underneath are one selection rather than two controls saying different things.
            # Area matches every area a compound is studied in, not just the one most of its
            # trials sit in; phase matches the furthest it has reached, which is the heading
            # it sits under. What the filter left shows in the section count, so clicking a
            # pill adds no line of its own.
            # What each compound is worth, so the pipeline reads as a book of value and not
            # only a list of studies. The forecast tab already computes this; without it here
            # a compound modelled at two dollars a share and one nobody has valued look the
            # same, which is the opposite of what the list is for. Cached for thirty seconds
            # like every other call, so opening both tabs computes it once. A forecast that
            # cannot be built must never take the pipeline down with it.
            try:
                _v = api_get(api_base, f"/companies/{ticker}/forecast-verdict")
            except Exception:
                _v = {}
            _shares = _v.get("diluted_shares") or 0
            valued = {m["asset_id"]: m.get("per_share")
                      for m in (_v.get("modelled") or []) if m.get("asset_id")}
            # Shown and not counted: the engine ran it on a placeholder curve, so the figure
            # exists but the company total deliberately excludes it. Marked, never hidden.
            held = {m["asset_id"]: (m.get("rnpv_share") or 0) * 1e6 / _shares if _shares
                    else None for m in (_v.get("placeholders") or []) if m.get("asset_id")}
            blocked = {m["asset_id"]: (m.get("missing") or [])
                       for m in (_v.get("refused") or []) if m.get("asset_id")}

            # The launch floor of each valued line, so a launch year the registry and the
            # FDA clock rule out is flagged on the figure it feeds.
            launches = {m["asset_id"]: m.get("launch")
                        for m in (_v.get("modelled") or []) if m.get("asset_id")}

            def _value_cell(asset_id) -> str:
                return _prog_value_cell(asset_id, valued, held, blocked,
                                        launches.get(asset_id))

            total_programmes = len(programmes)
            if area_pick:
                programmes = [p for p in programmes
                              if set(p.get("areas") or []) & set(area_pick)]
            if phase_pick:
                programmes = [p for p in programmes if p.get("phase") in phase_pick]

            def _group_of(p):
                if p.get("source") == "filing":
                    return p.get("stage") or "named in the filing"
                return p.get("phase") or "unphased"

            shown_counts = " · ".join(
                f'{n} {ph}' for ph, n in
                ((ph, sum(1 for p in programmes if _group_of(p) == ph))
                 for ph in phase_order + FILING_STAGES + ["named in the filing"]) if n)
            count = (f"{len(programmes)} of {total_programmes} compounds"
                     if len(programmes) != total_programmes
                     else f"{total_programmes} compounds")
            # The value of what is shown, not of the whole pipeline, so the figure agrees
            # with the rows under it when a pill is filtering the list.
            _shown_value = sum(valued.get(p.get("asset_id")) or 0 for p in programmes)
            _shown_n = sum(1 for p in programmes if valued.get(p.get("asset_id")))
            value_txt = (f" · {_shown_n} valued at {T.num(_shown_value, 2)} a share"
                         if _shown_n else "")
            section("Programmes in development",
                    count + (f" · {shown_counts}" if shown_counts else "") + value_txt)

            # Grouped by the furthest phase each compound has reached, most advanced first,
            # and every phase is shown: early work is most of a pipeline by count, and a
            # Phase 1 programme is the part an analyst is being paid to find early.
            # A programme with no registered trial is grouped by the stage its filing states,
            # under a heading of its own. Never mixed in with a phase: a phase is a study that
            # exists and a stage is a sentence, and putting "IND cleared" in the Phase 1 group
            # would be reading the sentence as the study.
            by_phase: dict = {}
            for p in programmes:
                by_phase.setdefault(_group_of(p), []).append(p)
            phase_order = phase_order + [s for s in FILING_STAGES if s in by_phase] + [
                "named in the filing"]
            if not programmes:
                state(f"No unapproved compounds mapped for {ticker}",
                      "Programmes are derived from the drug each trial names. Press Refresh "
                      "all to pull the registry and bind them.")
            else:
                html = ['<div class="progs">']
                for ph in phase_order:
                    group = by_phase.get(ph)
                    if not group:
                        continue
                    # Late phase open, early phase folded. Most of a pipeline by count is
                    # Phase 1, and for Lilly that is 43 rows of internal codes between the
                    # reader and the end of the list. The count stays on every heading, so
                    # a folded group still says how large it is, and opening one is a click
                    # against the browser rather than a rerun. A phase the pills asked for
                    # is open whatever its stage, because asking for it is the request to
                    # read it, and a short list is left open in full.
                    _worth_here = [valued[p["asset_id"]] for p in group
                                   if p.get("asset_id") in valued
                                   and valued[p["asset_id"]] is not None]
                    # Open where there is money in it. Folding is for the bulk nobody
                    # reads, and a compound carrying a forecast is the opposite of that:
                    # hiding its figure behind a click is hiding the one number on the
                    # row worth crossing the page for.
                    opened = " open" if (ph in ("Phase 3", "Phase 2/3")
                                         or ph in phase_pick
                                         or _worth_here
                                         or len(programmes) <= 12) else ""
                    # What the group is worth, on the heading. Folding hid the value
                    # column behind a click, which is the one thing on the row nobody
                    # should have to ask for twice: a folded phase now says how many
                    # compounds it holds, how many of them carry a forecast, and what
                    # they come to a share, so the money is readable shut.
                    _sum = (f'<span class="prog-gv">&middot; {len(_worth_here)} valued '
                            f'&middot; {T.num(sum(_worth_here), 2)}</span>'
                            if _worth_here else "")
                    html.append(f'<details class="prog-g"{opened}>'
                                f'<summary class="prog-h">{html_escape(ph)}'
                                f'<span>{len(group)}{_sum}</span></summary>')
                    for p in group:
                        due = (p.get("next_readout") or "")[:10]
                        # A native disclosure, so a programme opens onto its own studies
                        # without a widget and without a rerun.
                        studies = []
                        for s in p.get("studies") or []:
                            title = (s.get("title") or "").strip()
                            title = title if len(title) <= 84 else title[:83].rstrip() + "…"
                            studies.append(
                                f'<div class="prog-s" title="{html_escape(s.get("title") or "")}">'
                                f'<span class="d">{html_escape((s.get("due") or "")[:10] or "no date")}</span>'
                                f'<span class="ph">{html_escape(s.get("phase") or "")}</span>'
                                f'<a href="https://clinicaltrials.gov/study/{html_escape(s.get("nct_id") or "")}"'
                                f' target="_blank" rel="noopener">{html_escape(title)}</a>'
                                f'<span class="st">{html_escape(s.get("area") or "")}'
                                f' · {html_escape(s.get("status") or "")}</span>'
                                f'</div>')
                        # The lead area, with a count when the compound spans more, so a
                        # programme being developed across indications reads as one.
                        areas = p.get("areas") or []
                        area_txt = (f'{areas[0]}' if areas else "")
                        if len(areas) > 1:
                            area_txt += f' +{len(areas) - 1}'
                        if p.get("source") == "filing":
                            # No study to open, so the disclosure holds the sentence it was
                            # read from and the filing that carried it. A reader who doubts
                            # the row can check it without leaving the page.
                            studies = [
                                f'<div class="prog-s prog-ev">'
                                f'<span class="d">{html_escape(p.get("form_type") or "")} '
                                f'{html_escape((p.get("filed_date") or "")[:10])}</span>'
                                f'<span class="q">{html_escape(p.get("evidence") or "")}</span>'
                                f'</div>']
                            area_txt = p.get("indication") or ""
                        html.append(
                            f'<details class="prog"><summary>'
                            f'<span class="prog-n">{html_escape(p.get("name") or "")}</span>'
                            f'<span class="prog-a" title="{html_escape(", ".join(areas))}">'
                            f'{html_escape(area_txt)}</span>'
                            f'<span class="prog-t">'
                            f'{"filing" if p.get("source") == "filing" else str(p.get("trials", 0)) + " trials"}'
                            f'</span>'
                            f'<span class="prog-d">{html_escape(due or "no date")}</span>'
                            f'{_value_cell(p.get("asset_id"))}'
                            f'</summary>{"".join(studies)}</details>')
                    html.append("</details>")
                html.append("</div>")
                st.markdown("".join(html), unsafe_allow_html=True)
                st.markdown(
                    '<div class="byline">One row per compound in trials that the company does '
                    'not yet sell, grouped by the furthest phase it has reached, with the '
                    'number of studies behind it and the next primary completion date due. '
                    'Open a compound for its own studies, each linking to the registry. '
                    'Derived from the drug each registry entry names, so a compound appears '
                    'only where a trial names it. A comparator, a shared chemotherapy '
                    'backbone and another company\'s marketed drug are excluded, so this is '
                    'the sponsor\'s own work rather than everything its studies '
                    'mention. Below the phases sit the programmes the company describes in '
                    'its own filing and the registry has never seen, at the stage the filing '
                    'states and never at a phase, each opening onto the sentence it was read '
                    'from. The last column is what the compound is worth a share on the '
                    'forecast tab: a figure where the engine builds it, "needs" where it '
                    'read the assumptions and stopped on a gap the tooltip names, a starred '
                    'figure where it ran on a placeholder curve and is shown without being '
                    'counted, and a dash where no assumptions are on file at all. A figure '
                    'underlined red launches in the model before the earliest approval the '
                    'registry and the FDA review clock allow, amber where its seed cites a '
                    'filing or readout not on file; its tooltip says which.</div>',
                    unsafe_allow_html=True)


    # --- Portfolio -------------------------------------------------------
    if portfolio_tab is not None:
        with portfolio_tab:
            # A fragment: a product card, an area pill or the profile's close button
            # reruns this tab alone rather than the whole page, which renders every
            # tab on every rerun. Everything it reads is set above it on the page.
            @st.fragment
            def _portfolio_tab():
                # The rail is a forward calendar and this tab is a record of what is
                # already sold, so the marker tells the theme to hand its width back.
                st.markdown('<span class="no-rail"></span>', unsafe_allow_html=True)
                approvals = api_get(api_base, f"/companies/{ticker}/approvals")["approvals"]
                # Revenue-mix data fetched once here: the donut renders above the product cards
                # (inside the else), and the product-revenue list below reuses these rows.
                revenue_payload = api_get(api_base, f"/companies/{ticker}/revenue")
                curated = revenue_payload["rows"]
                mix_year = max((r["fiscal_year"] for r in curated), default=None)
                mix_rows = [r for r in curated if r["fiscal_year"] == mix_year]
                mix_ccy = next((r["unit"] for r in mix_rows if r.get("unit")), None)
                mix_reported = (revenue_payload.get("company_revenue") or {}).get(
                    str(mix_year)) or {}
                mix_drivers, mix_tail = revenue_mix.split(mix_rows)
                if not approvals:
                    state(f"No approvals on file for {ticker}",
                          "openFDA files an approval under the legal entity that holds the "
                          "application, which for an acquired product is the company that was "
                          "bought. Press Refresh all in the top bar to pull it again.")
                else:
                    today = dt.date.today()

                    def _loe_year(p):
                        try:
                            return int(str(p["loe"])[:4]) if p.get("loe") else None
                        except (ValueError, TypeError):
                            return None

                    # One card per product: approvals repeat per indication, but revenue and
                    # exclusivity are per asset and shared, so collapse to the product and keep
                    # the earliest approval date.
                    products: dict = {}
                    for a in approvals:
                        key = a.get("brand_name") or a.get("application_number")
                        p = products.get(key)
                        if p is None:
                            products[key] = dict(
                                asset_id=a.get("asset_id"),
                                application_number=a.get("application_number"),
                                brand=a.get("brand_name") or a.get("generic_name") or "unnamed",
                                generic=a.get("generic_name"), modality=a.get("modality"),
                                approved=a.get("approval_date"), loe=a.get("loe"),
                                loe_basis=a.get("loe_basis"),
                                loe_earliest_year=(int(a["loe_earliest"][:4])
                                                   if a.get("loe_earliest") else None),
                                revenue=a.get("revenue"),
                                revenue_unit=a.get("revenue_unit"),
                                area=a.get("area"))
                        elif a.get("approval_date") and (
                                not p["approved"] or a["approval_date"] < p["approved"]):
                            p["approved"] = a["approval_date"]
                    # openFDA drugsfda is CDER only, so a CBER cell or gene therapy (Casgevy) has
                    # no approval row there. Fold in Purple Book biologics from the exclusivities
                    # data, keyed by brand and only when not already present, so they still appear.
                    for ex in (api_get(api_base, f"/companies/{ticker}/exclusivities")
                               .get("assets") or []):
                        brand = ex.get("brand_name")
                        if not brand or brand in products:
                            continue
                        products[brand] = dict(
                            asset_id=ex.get("asset_id"),
                            brand=brand, generic=ex.get("generic_name"),
                            modality=ex.get("modality"), approved=None,
                            loe=ex.get("loe"), loe_basis=ex.get("loe_basis"),
                            loe_earliest_year=ex.get("loe_earliest_year"),
                            revenue=None, revenue_unit=None,
                            # A Purple Book biologic has no drugsfda row, so no label to read an
                            # area off; it groups under the unstated heading until one arrives.
                            area=ex.get("area"))
                    prods = list(products.values())
                    rev_unit = next((p["revenue_unit"] for p in prods if p.get("revenue_unit")), "")

                    total_rev = sum(p["revenue"] for p in prods if p.get("revenue"))
                    horizon = today.year + 5
                    at_risk = sum(p["revenue"] for p in prods if p.get("revenue")
                                  and (_loe_year(p) or 9999) <= horizon)

                    # The charts on one side, the products on the other. Stacked, the two
                    # donuts and the cliff filled a screen before a single product card
                    # appeared; side by side each half is read at a glance and the tab stops
                    # being a scroll. The charts keep the wider half: two donuts need the
                    # room for their outside labels, and the cliff shares their x axis of
                    # years.
                    # Near enough equal. Three to two left the charts with air they did not
                    # use and pushed the cards into a strip against the right edge.
                    _charts_col, _products_col = st.columns([1.08, 1], gap="medium")

                    with _charts_col:
                        # The heading and its three figures lead the left column, so
                        # the products column starts level with them and the space
                        # that sat empty beside the figures is the cards.
                        section(f"{ticker} portfolio")
                        st.markdown(
                            '<div class="pos">'
                            f'<div><span class="k">products</span>'
                            f'<span class="v">{len(prods)}</span>'
                            f'<span class="sub">approved or protected</span></div>'
                            f'<div><span class="k">tagged revenue</span>'
                            f'<span class="v{"" if total_rev else " none"}">'
                            f'{T.num(total_rev / 1e9, 1) if total_rev else "none"}</span>'
                            f'<span class="sub">{rev_unit} bn, latest FY</span></div>'
                            f'<div><span class="k">rolling off by {horizon}</span>'
                            f'<span class="v {"down" if at_risk else "none"}">'
                            f'{T.num(at_risk / 1e9, 1) if at_risk else "none"}</span>'
                            f'<span class="sub">'
                            f'{str(round(at_risk / total_rev * 100)) + "% of tagged" if total_rev and at_risk else "loses exclusivity"}'
                            f'</span></div>'
                            '</div>', unsafe_allow_html=True)


                        # The left column stacked four panels and the last of them was a
                        # placeholder until a card was clicked. The two charts are layers
                        # now, and the fact sheet sits above them rather than among them: a
                        # card click is a request to read that product, and st.tabs keeps
                        # the selected label across a rerun, so adding a "Fact sheet" tab
                        # left the reader looking at the revenue mix they had already seen.
                        # Filled after the cards are drawn, since the click that selects a
                        # product happens in the column beside this one.
                        _profile_slot = st.container()
                        st.markdown('<span class="fc-layers"></span>', unsafe_allow_html=True)
                        # Medicare demand is a layer only where CMS has a brand of this
                        # company's, and a failed read leaves it out rather than the tab.
                        try:
                            _mc_book = api_get(api_base, f"/companies/{ticker}/demand/split")
                        except (urllib.error.URLError, OSError):
                            _mc_book = None
                        _mc_book_html = _medicare_book_html(_mc_book) if _mc_book else ""
                        _pf_names = ["Revenue mix", "By area", "Exclusivity"] + (
                            ["Medicare demand"] if _mc_book_html else [])
                        _pf = dict(zip(_pf_names, st.tabs(_pf_names)))

                        with _pf["Revenue mix"]:
                            # The layer leads the tab: what the company earns, by product, before
                            # the cliff charts say what is at risk.
                            if mix_drivers:
                                # The build first, the ring under it. The build says where the
                                # revenue goes, the same products as bands out to the horizon
                                # with the reported line over them; the ring says where one year
                                # of it comes from. It is the forecast tab's chart, drawn here
                                # because this is the tab about the book that produces it.
                                try:
                                    _bv = api_get(api_base,
                                                  f"/companies/{ticker}/forecast-verdict")
                                except (urllib.error.URLError, OSError):
                                    _bv = None
                                if _bv and _bv.get("ok"):
                                    _revenue_build(_bv)

                                section("Revenue mix", f"FY{mix_year}")
                                ramp = list(reversed(T.ordinal_ramp(max(len(mix_drivers), 2))))

                                def _slice_href(row):
                                    """The fact sheet for the product a wedge measures.

                                    A bracketed tail, a reported segment line and revenue the
                                    filing attributes to nothing are not products, hold no asset
                                    and so open nothing."""
                                    aid = row.get("asset_id")
                                    if not aid:
                                        return None
                                    return (f"?ticker={urllib.parse.quote(ticker)}"
                                            f"&product={aid}")

                                slices = [{"label": p["brand_name"] or p["generic_name"] or "unnamed",
                                           "value": p["value"], "colour": ramp[i % len(ramp)],
                                           "href": _slice_href(p)}
                                          for i, p in enumerate(mix_drivers)]
                                if mix_tail:
                                    slices.append({"label": f"{len(mix_tail)} smaller products",
                                                   "value": sum(p["value"] for p in mix_tail),
                                                   "colour": TK.RULE_STRONG, "muted": True})
                                # The money no product carries used to be one anonymous wedge.
                                # Where the company reports it as a line and the app carries that
                                # line, it has a name, and the name is worth more than the grey.
                                # The composition is in revenue_mix, which is pure and tested;
                                # this is only the colouring.
                                rest = revenue_mix.residual(mix_rows, mix_reported.get("value"))
                                named_lines, remainder, over = revenue_mix.line_slices(
                                    revenue_payload.get("lines"), rest, mix_year,
                                    mix_reported.get("value"))
                                named_lines = [{"label": ln["line"], "value": ln["value"],
                                                "colour": TK.MUTED, "muted": True}
                                               for ln in named_lines]
                                slices.extend(named_lines)
                                if remainder:
                                    slices.append({"label": "not attributed by product",
                                                   "value": remainder, "colour": TK.PANEL,
                                                   "muted": True})
                                # The same revenue twice: by product, and by the disease the label says
                                # each product treats. One says which drugs carry the company, the other
                                # says which franchise does, and a portfolio held in one area reads very
                                # differently from the same revenue spread across four.
                                # The revenue rows carry their own area, so a product that earns under
                                # this company but is approved to another still lands in a franchise.
                                area_by_asset = {p.get("asset_id"): p.get("area") for p in prods
                                                 if p.get("asset_id")}
                                by_area: dict = {}
                                for row in mix_rows:
                                    area = (row.get("area")
                                            or area_by_asset.get(row.get("asset_id"))
                                            or "area not stated")
                                    by_area[area] = by_area.get(area, 0) + (row.get("value") or 0)
                                area_order = sorted(by_area, key=lambda a: (a == "area not stated",
                                                                            -by_area[a]))
                                # A donut half the width cannot carry "Immunology and inflammation" as
                                # a leader label, so the long areas go by their head word here. The
                                # product grid below keeps the full names.
                                short = AREA_SHORT
                                # Categories, not magnitudes: a lightness ramp would say oncology is
                                # more than neuroscience. Hue carries the area, each area keeps its own
                                # colour across companies, and the two donuts stop looking like one
                                # chart drawn twice.
                                area_colour = area_colours(
                                    [a for a in area_order if a != "area not stated"])
                                area_slices = [
                                    {"label": short.get(area, area), "value": by_area[area],
                                     "colour": (TK.RULE_STRONG if area == "area not stated"
                                                else area_colour[area]),
                                     "muted": area == "area not stated"}
                                    for area in area_order]
                                # A segment line has no disease area, so it lands here under its
                                # own name too. "MedTech" is a truer answer to which area carries
                                # the revenue than "not attributed" was.
                                area_slices.extend(named_lines)
                                if remainder:
                                    area_slices.append({"label": "not attributed by product",
                                                        "value": remainder, "colour": TK.PANEL,
                                                        "muted": True})

                                # One ring, the width of the column. Two of them side by side
                                # inside half a page left each about 390 pixels for a chart
                                # drawn at 470 with labels on leader lines outside it, so the
                                # names crushed into the middle and the cut nobody was reading
                                # took half the room from the cut they were. The disease-area
                                # cut is the same revenue and gets its own layer.
                                total_mix = sum(sl["value"] for sl in slices) / 1e9
                                named = len([a for a in area_order if a != "area not stated"])
                                R.show(CH.donut(
                                    slices, 840, 330, centre_label=T.num(total_mix, 1),
                                    centre_sub=f"{mix_ccy or ''} bn FY{mix_year}",
                                    value_fmt=lambda v: T.num(v / 1e9, 2)),
                                    css_class="chart-mount mix-donut")
                                if named_lines:
                                    note("The grey wedges are revenue the company reports as a "
                                         "line rather than a product: "
                                         + ", ".join(f"{sl['label']} at "
                                                     f"{T.num(sl['value'] / 1e9, 2)}bn"
                                                     for sl in named_lines)
                                         + ". They are carried in the forecast as streams, which "
                                           "is why the model reconciles to the reported total "
                                           "rather than to the products alone.")
                                if over:
                                    note(f"The lines on file come to {T.num(over / 1e9, 2)}bn more "
                                         "than the revenue no product carries, so they are drawn "
                                         "as one wedge instead of by name. A line worth more than "
                                         "the gap is counting a product twice, which is a defect "
                                         "in the line rather than in the chart.")

                        # The same revenue, cut by the disease each label names. Its own
                        # layer rather than a second ring beside the first: they are the
                        # same total and only one is being read at a time.
                        if mix_drivers:
                            with _pf["By area"]:
                                st.markdown(
                                    f'<div class="subhead">By disease area<span>{named} areas'
                                    '</span></div>', unsafe_allow_html=True)
                                R.show(CH.donut(
                                    area_slices, 840, 330, centre_label=T.num(total_mix, 1),
                                    centre_sub=f"{mix_ccy or ''} bn FY{mix_year}",
                                    value_fmt=lambda v: T.num(v / 1e9, 2)),
                                    css_class="chart-mount mix-donut")


                        with _pf["Exclusivity"]:
                            # Loss of exclusivity by year. Two cuts of the same expiries. The count
                            # cliff shows every product with a published expiry, so nothing is hidden by
                            # the free-data revenue gap. The revenue chart below weights only the few
                            # products with tagged revenue, which is sparse and must not read as the
                            # whole cliff.
                            count_by_year: dict = {}
                            rev_by_year: dict = {}
                            for p in prods:
                                y, r = _loe_year(p), p.get("revenue")
                                if y and today.year <= y <= today.year + 10:
                                    count_by_year[y] = count_by_year.get(y, 0) + 1
                                    if r:
                                        rev_by_year[y] = rev_by_year.get(y, 0) + r
                            # The cliff, full width. The revenue-at-risk chart that used to sit
                            # beside it is gone: it weighted only the products whose revenue the
                            # filer happens to tag, which for Lilly is four of the fourteen expiring
                            # in the window, and a bar chart of a quarter of the truth read as the
                            # whole of it. The count below hides nothing, because it draws every
                            # product with a published expiry whether or not its revenue is known.
                            if count_by_year:
                                years = list(range(today.year, today.year + 11))
                                section("Loss of exclusivity by year", "products, next 10 years")
                                bars = [{"label": f"'{y % 100:02d}",
                                         "value": count_by_year.get(y, 0), "colour": TK.DOWN,
                                         "show_value": count_by_year.get(y, 0) > 0}
                                        for y in years]
                                R.show(CH.bar_chart(bars, 1100, 118,
                                                    value_fmt=lambda v: str(int(v))),
                                       css_class="chart-mount stretch")
                                note("Every marketed product losing US exclusivity that year, "
                                     "expiries from the Orange and Purple Books, counted whether or "
                                     "not its revenue is tagged. A small molecule is placed at its "
                                     "latest patent, a biologic at the later of its listed expiry "
                                     "and the 12-year floor. A product with no published expiry "
                                     "cannot be placed and is left out, never estimated: open its "
                                     "card to see whether that is protection already lapsed or "
                                     "nothing published yet.")

                            # The fact sheet, under the cliff rather than inside the card grid.
                            # Opening above the cards pushed them down the page on every click;
                            # here it fills the column the charts leave, and the cards it is
                            # about stay where they were.

                        if _mc_book_html:
                            with _pf["Medicare demand"]:
                                section("Medicare demand", len(_mc_book["brands"]),
                                        f"CMS calendar {_mc_book.get('latest_year')}")
                                st.markdown(_mc_book_html, unsafe_allow_html=True)



                    with _products_col:
                        section("Products",
                                f"{len(prods)} &middot; click one for its fact sheet")

                        def _product_card_html(p):
                            mod = (p.get("modality") or "").lower()
                            cls = "bio" if "bio" in mod else "small" if mod else ""
                            y = _loe_year(p)
                            near = y is not None and y <= today.year + 3
                            rev_txt = (f'{T.num(p["revenue"] / 1e9, 2)} {p.get("revenue_unit") or ""} bn'
                                       if p.get("revenue") is not None else "no free data")
                            to_loe = f' · {y - today.year}y' if y else ""
                            # A small molecule usually has several Orange Book patents; the latest
                            # overstates the real cliff since generics can challenge the earlier ones.
                            # Show the earliest-to-latest range so the wall reads as a window, not a
                            # single hard date. Biologics keep the single merged floor.
                            ey = p.get("loe_earliest_year")
                            is_range = cls == "small" and ey and y and ey != y
                            loe_label = "exclusivity" if is_range else "exclusivity to"
                            loe_txt = f'{ey}–{y}' if is_range else (f'{y}{to_loe}' if y else "—")
                            # Past means the event has happened, so the card says so rather
                            # than counting down to a date that has gone.
                            if p.get("loe_past") and y:
                                loe_label, loe_txt, is_range = "exclusivity", f"lapsed {y}", False
                            # The patent that sets the date, named on the card. Which of a
                            # product's twenty patents is the cliff is the question the stack
                            # exists to answer, and the answer belongs where the date is.
                            patent_txt = (f' &middot; {html_escape(str(p["loe_identifier"]))}'
                                          if p.get("loe_identifier") else "")
                            # Where there is no expiry, say which kind of nothing it is. The
                            # Orange Book lists only unexpired patents and unexpired
                            # exclusivities, so no rows means either every one of them has run
                            # out or none was ever listed, and those are opposite facts. Age
                            # separates them: a small molecule's protection cannot outlast its
                            # approval by more than about fourteen years, so an older product
                            # with nothing listed has lost it, and a recent one has simply not
                            # had anything published. Neither is a date and neither is guessed.
                            status, status_why = "", ""
                            if not y:
                                approved_year = int((p.get("approved") or "0000")[:4] or 0)
                                age = today.year - approved_year if approved_year else 0
                                if approved_year and age >= _LOE_LAPSED_AFTER_YEARS:
                                    status = "protection lapsed"
                                    status_why = (f"Approved {age} years ago and no unexpired "
                                                  "patent or exclusivity is listed, so the "
                                                  "protection it had has run out. Generics or "
                                                  "biosimilars may already be on sale. Not a "
                                                  "date: the register says only that nothing "
                                                  "unexpired remains.")
                                else:
                                    status = "none listed"
                                    status_why = ("No patent or exclusivity is published for "
                                                  "this product yet. Recently approved products "
                                                  "are often listed late, so this is an absence "
                                                  "of data rather than an absence of protection.")
                            basis = (f'<div class="pf-row" title="{html_escape(_WHY_BASIS)}">'
                                     f'<span class="pf-k"></span>'
                                     f'<span class="pf-v none" style="font-size:9px">'
                                     f'{html_escape(p.get("loe_basis") or "")}</span></div>'
                                     if p.get("loe_basis") else "")
                            if status:
                                basis = (f'<div class="pf-row" title="{html_escape(status_why)}">'
                                         f'<span class="pf-k"></span>'
                                         f'<span class="pf-v none" style="font-size:9px">'
                                         f'{status}</span></div>')
                            return (
                                f'<div class="pf-card {cls}">'
                                f'<div class="pf-head">'
                                f'<span class="pf-brand">{html_escape(p["brand"])}</span>'
                                f'<span class="pf-mod" title="{html_escape(_WHY_MODALITY)}">'
                                f'{html_escape(p.get("modality") or "")}</span></div>'
                                f'<div class="pf-generic">{html_escape(p.get("generic") or "")}</div>'
                                f'<div class="pf-row" title="{html_escape(_WHY_APPROVED)}">'
                                f'<span class="pf-k">approved</span>'
                                f'<span class="pf-v">{(p.get("approved") or "—")[:10]}</span></div>'
                                f'<div class="pf-row" title="{html_escape(_WHY_REVENUE)}">'
                                f'<span class="pf-k">revenue</span>'
                                f'<span class="pf-v{"" if p.get("revenue") is not None else " none"}">'
                                f'{rev_txt}</span></div>'
                                f'<div class="pf-row" title="{html_escape(_WHY_LAPSED if p.get("loe_past") else (_WHY_RANGE if is_range else _WHY_LOE))}">'
                                f'<span class="pf-k">{loe_label}</span>'
                                f'<span class="pf-v {"near" if near else ""}">'
                                f'{loe_txt}<span class="pf-pat">{patent_txt}</span>'
                                f'</span></div>'
                                f'{basis}</div>')

                        prods_sorted = sorted(prods, key=lambda p: (-(p.get("revenue") or 0),
                                                                    _loe_year(p) or 9999))
                        # The card itself is the hit area: the grid renders inside a component that
                        # returns the clicked asset id, so there is no separate button and hovering a
                        # card shows it is live. The selection lives in session state and a native
                        # rerun keeps the Portfolio tab active, so the profile opens in place.
                        # An approval clicked on the Universe timeline arrives as an application
                        # number, which is the only product identifier that survives the change feed.
                        # Resolve it here, where the products are known, and consume it so a later
                        # rerun does not keep reopening the same sheet.
                        pending = st.session_state.pop("pending_product", None)
                        if pending:
                            match = next((p for p in prods
                                          if str(p.get("application_number") or "").replace(" ", "")
                                          == pending), None)
                            if match and match.get("asset_id"):
                                st.session_state["profile_asset"] = match["asset_id"]
                        sel_aid = st.session_state.get("profile_asset")
                        # The profile sits above the grid, so a click does not push it below a long
                        # card list. Guarded to this company's products, so switching ticker drops a
                        # stale selection rather than asking the API for another company's asset.
                        sel = next((p for p in prods_sorted if p.get("asset_id") == sel_aid), None)
                        # Grouped by the disease the label says the product treats, biggest area
                        # first and biggest product inside it. A portfolio is held by franchise, so
                        # a flat list by revenue hid the shape of it: four metabolic drugs reading
                        # as one bet is the fact, not their order. A product whose label is not on
                        # file sits under its own heading rather than being filed under a guess.
                        groups: dict = {}
                        for p in prods_sorted:
                            if p.get("asset_id") is None:
                                continue
                            groups.setdefault(p.get("area") or "Area not stated", []).append(p)

                        def _area_revenue(area):
                            return sum(p.get("revenue") or 0 for p in groups[area])

                        order = sorted(groups, key=lambda a: (a == "Area not stated",
                                                              -_area_revenue(a)))
                        card_tokens = {"panel": TK.PANEL, "panel-hi": TK.RULE,
                                       "rule": TK.RULE, "rule-strong": TK.RULE_STRONG,
                                       "muted": TK.MUTED, "text": TK.TEXT, "up": TK.UP,
                                       "down": TK.DOWN, "orange-book": TK.ORANGE_BOOK,
                                       "purple-book": TK.PURPLE_BOOK, "font-mono": TK.FONT_MONO,
                                       "font-ui": TK.FONT_UI}
                        # One area at a time, picked from a row of pills. Six areas stacked as six
                        # card grids was most of this tab's height and pushed the tables under it
                        # two screens down, and a reader looks at one franchise at a time anyway.
                        # Each pill carries its own count, so the shape of the portfolio is still
                        # readable without opening any of them.
                        _labels = {a: f"{a} ({len(groups[a])})" for a in order}
                        _picked = st.pills(
                            "Disease area", [_labels[a] for a in order],
                            default=_labels[order[0]] if order else None,
                            key=f"prod_area_{ticker}", label_visibility="collapsed")
                        _chosen = next((a for a in order if _labels[a] == _picked),
                                       order[0] if order else None)
                        for area in [a for a in order if a == _chosen]:
                            revenue = _area_revenue(area)
                            section(area, f"{len(groups[area])} &middot; {T.num(revenue / 1e9, 1)}bn"
                                    if revenue else len(groups[area]))
                            clicked = prodcards.product_cards(
                                [{"asset_id": p.get("asset_id"), "html": _product_card_html(p)}
                                 for p in groups[area]],
                                tokens=card_tokens,
                                # Keyed per company and area: a fixed key would carry one grid's
                                # last click into the next.
                                selected=sel_aid,
                                key=f"prod_cards_{ticker}_{re.sub(r'[^a-z0-9]+', '_', area.lower())}")
                            # A click is only acted on once: the nonce changes per click, so a rerun
                            # triggered by anything else does not reopen a closed profile.
                            if isinstance(clicked, dict) and clicked.get("nonce") != \
                                    st.session_state.get("prod_click_nonce"):
                                st.session_state["prod_click_nonce"] = clicked.get("nonce")
                                st.session_state["profile_asset"] = clicked.get("asset_id")
                                _rerun_here()

                    # Nothing where no card has been clicked. The panel used to hold a
                    # placeholder saying to click one, which spent a quarter of the column on
                    # an instruction; the hint now sits on the Products heading, next to the
                    # cards it is about.
                    if sel is not None:
                        with _profile_slot:
                            _render_product_profile(api_base, ticker, sel, today)

            _portfolio_tab()

        # --- Catalysts -------------------------------------------------------
    with catalysts_tab:
        # What could move the company next, as one list (company-scorecard.md 1.5): the
        # events of the next twelve months, value-bearing first, beside what could cost
        # it. The Comps view used to carry this; the comparison with peers stays there.
        _drivers_and_risks(api_base, ticker, feed)

        # What each event is worth before when it lands: the modelled swing between the
        # success and failure legs, at this company's share of the economics, ranked by
        # size rather than by date. Drawn only when a catalyst is priced. The unpriced
        # lines named two database keys and no number, six to a screen for big pharma,
        # and every one of those events is in Drivers or the calendar already.
        try:
            stakes = api_get(api_base, f"/companies/{ticker}/catalysts/stakes")
        except (urllib.error.URLError, OSError):
            stakes = None
        if stakes and stakes.get("priced"):
            section("At stake", basis="rNPV swing, ranked by size")
            # Keyed for the spacing in _DR_CSS: clear of the rule, buttons centred.
            stake_box = st.container(key="cat_stakes")
            # Said once, on the rerun after the resolve that called for it.
            said = _stake_resolved_note(st.session_state.pop(f"cat_resolved_{ticker}", None))
            if said:
                stake_box.info(said)
            shown, rest = _stake_split(stakes["priced"])
            for row in shown:
                _stake_row(stake_box, api_base, ticker, row)
            if rest:
                with stake_box.expander(f"{len(rest)} more at stake", expanded=False):
                    for row in rest:
                        _stake_row(st.container(), api_base, ticker, row)

        # Derived only, and for the selected company alone, rebuilt on every refresh
        # rather than maintained. Folded: open, it shows the Drivers' events a second
        # time by month, and a grid of registry titles was most of the tab's words. The
        # rows sit under the grid in the same fold, since a fold cannot hold another.
        # One window, so no control. Two years is the span a readout calendar is read
        # over, and a shorter one hid the far half of what is already known.
        if getattr(calendar_view, "REVISION", 0) < 2:
            importlib.reload(calendar_view)
        window = CALENDAR_MONTHS
        try:
            calendar = api_get(
                api_base,
                f"/catalysts?within_days={window * 31}"
                f"&ticker={urllib.parse.quote(ticker)}") or []
            calendar_problem = None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            calendar, calendar_problem = [], str(exc)
        in_grid = calendar_view.within(calendar, window)
        with st.expander(calendar_view.expander_label(calendar, window), expanded=False):
            if calendar_problem:
                state("The calendar did not load", html_escape(calendar_problem),
                      error=True)
            elif not in_grid:
                state(f"Nothing dated for {ticker} in the next {window} months",
                      calendar_view.SOURCES)
            else:
                st.markdown(calendar_view.render(calendar, months=window),
                            unsafe_allow_html=True)
                # Padded by the rem Streamlit's markdown pulls back, or the rows under
                # the caption sit on its last line.
                st.markdown(f'<div class="byline" style="padding-bottom: 1rem">'
                            f'{calendar_view.caption(calendar, window)}</div>',
                            unsafe_allow_html=True)
                # The link shows the trial's id: the pattern needs a group, or the cell
                # prints the pattern itself.
                st.dataframe(pd.DataFrame([{
                    "Date": c["expected_date"], "Type": c["catalyst_type"],
                    "Precision": c["date_confidence"], "Title": c["title"],
                    "Evidence": c["source_url"] or None} for c in in_grid]),
                    width="stretch", hide_index=True,
                    column_config={"Evidence": st.column_config.LinkColumn(
                        "Evidence", display_text=r"(NCT\d{8})")})

    # --- Labels ----------------------------------------------------------
    # --- News ------------------------------------------------------------
    with forecast_tab:
        _render_forecast_tab(api_base, ticker)

    with news_tab:
        news = api_get(api_base, f"/companies/{ticker}/news")["news"]
        section(f"News and announcements for {ticker}", len(news))
        if not news:
            state(f"No news on file for {ticker}",
                  "Press Refresh all to pull EDGAR 8-K and 6-K material events and the "
                  "FDA press, drug and safety feeds matched to this company. European "
                  "filers submit 6-K, not 8-K.")
        else:
            # The same list the rest of the app uses, not a spreadsheet. A grid widget
            # gave a headline the same weight as a cell of a table, put the link in its
            # own column as the word "Link", and looked like a different application from
            # the tab beside it. Each row is now the anchor itself.
            st.markdown('<div class="feed news">' + "".join(
                news_row(n) for n in news[:_NEWS_SHOWN]) + "</div>",
                unsafe_allow_html=True)
            note("EDGAR 8-K and 6-K material events, plus the FDA press, drug and "
                 "MedWatch feeds matched to this company by name or brand. The full FDA "
                 "feed is on the Universe tab."
                 + (f" Showing the {_NEWS_SHOWN} most recent of {len(news)}."
                    if len(news) > _NEWS_SHOWN else ""))

        # --- Filing text changes ---
        # The numbers in a 10-K change on their own schedule; the words change once a
        # year. A rewritten risk factors section is a real signal with no structured
        # field, so it is diffed against the last filing of the same form.
        section("Filing text changes", "risk factors, latest filings")
        ftext = api_get(api_base, f"/companies/{ticker}/filing-text").get("sections") or []
        risk = [s for s in ftext
                if s["section"] == "risk_factors" and s.get("added") is not None]
        if not risk:
            state(f"No filing text comparison for {ticker}",
                  "Two filings of the same form are needed to diff the words. US filers "
                  "get a 10-K and 10-Q comparison on refresh; a foreign 20-F filer lays "
                  "its sections out under different item numbers and is a labelled future "
                  "add. Press Refresh all if this looks empty.")
        else:
            for s in risk:
                changed = (f" · {round((1 - s['ratio']) * 100)}% changed"
                           if s.get("ratio") is not None else "")
                st.markdown(
                    f'<div class="byline"><b>{s["form"]} risk factors</b> · '
                    f'{s["added"]} added, {s["removed"]} removed vs {s["prior_date"]}'
                    f'{changed}</div>', unsafe_allow_html=True)
                if s.get("added_passages"):
                    st.markdown("".join(
                        f'<div class="rf-add">{html_escape(p[:400])}'
                        f'{"…" if len(p) > 400 else ""}</div>'
                        for p in s["added_passages"][:5]), unsafe_allow_html=True)

    # --- Themes: the universe read by modality rather than by ticker ------
    # Absent on big pharma: see the tab list above.
    if themes_tab is not None:
        with themes_tab:
            payload = api_get(api_base, "/themes")
            rows, cover = payload["themes"], payload["coverage"]
            section("Modality themes across coverage", len(rows))
            if not rows:
                state("No themes derived yet",
                      "Press Refresh all. Themes are read from what each drug is called, "
                      "the stems in its INN, and the class statement its label opens with.")
            else:
                # The coverage line sits above the table, not below it. The counts are
                # floors, and a reader who takes them for totals concludes that companies
                # absent from a theme do not work in it, which is the one wrong reading
                # this view can produce.
                st.caption(
                    f"Two axes, never added. {cover['tagged']} of {cover['assets']} "
                    "programmes state what they are, read from the drug's own name or "
                    f"label. {cover['companies_on_platform']} of {cover['companies']} "
                    "companies describe a platform in their own annual filing, which "
                    "reaches the ones whose drugs are code numbers: Beam and Editas run "
                    "gene editing and hold no programme any free source classifies. "
                    "Programme counts are a floor; the platform column is the better "
                    "guide to who is in a modality"
                    + (f". {len(cover['companies_unreached'])} companies are reached by "
                       "neither: " + ", ".join(cover["companies_unreached"])
                       if cover["companies_unreached"] else "."))
                st.dataframe(pd.DataFrame([{
                    "Theme": r["theme"],
                    "Companies": r["companies"],
                    "Programmes": r["assets"],
                    "Marketed": r["marketed"],
                    # The four most advanced stages. The full mix runs to seven entries
                    # and its column then crowds out the companies, which are the point.
                    "Stage mix": ", ".join(
                        [f"{k.lower()} {v}" for k, v in list(r["stage_mix"].items())[:4]]
                        + ([f"+{len(r['stage_mix']) - 4} more"]
                           if len(r["stage_mix"]) > 4 else [])),
                    "Changes, 90d": r["changes"],
                    "Most exposed": ", ".join(f"{c['ticker']} {c['assets']}"
                                              for c in r["top_companies"][:4]),
                    # The second axis. Companies whose own filing describes the platform,
                    # which is the only way the editors appear at all.
                    "On platform": len(r["platform_companies"]),
                    "Platform only": ", ".join(r["platform_only"][:6]),
                } for r in rows]), width="stretch", hide_index=True)

                chosen = st.selectbox("Theme", [r["theme"] for r in rows],
                                      key="theme_pick")
                slug = urllib.parse.quote(chosen, safe="")
                detail = api_get(api_base, f"/themes/{slug}")
                marketed = [a for a in detail["assets"] if a["is_marketed"]]
                clinical = [a for a in detail["assets"] if not a["is_marketed"]]

                section(f"{chosen} programmes", len(detail["assets"]))
                st.dataframe(pd.DataFrame([{
                    "Ticker": a["ticker"],
                    "Programme": a["name"],
                    "Stage": "Marketed" if a["is_marketed"] else (a["phase"] or "—"),
                    "Trials": a["trials"],
                    # The phrase the tag was read from. A modality tag is a judgement made
                    # from text, so the evidence travels with it rather than living in a
                    # log: "why is this a radioligand" is answerable in the row.
                    "Read from": a["evidence"],
                    "Source": a["source"],
                } for a in marketed + clinical]), width="stretch", hide_index=True)

                if detail.get("platform"):
                    section(f"Companies whose filing describes this platform",
                            len(detail["platform"]))
                    st.caption(
                        "Read from each company's own annual filing, in the first person, "
                        "so a competitor paragraph cannot claim a platform. A company with "
                        "0 classified programmes appears here and nowhere else in the tab.")
                    st.dataframe(pd.DataFrame([{
                        "Ticker": r["ticker"],
                        "Company": r["company"],
                        "Classified programmes": r["assets"],
                        "Read from": r["evidence"],
                    } for r in detail["platform"]]), width="stretch", hide_index=True)

                section(f"Brief on {chosen}")
                existing = api_get(api_base, f"/themes/{slug}/brief")
                if st.button("Write the brief", key=f"brief_{chosen}"):
                    with st.spinner(f"Reading {chosen} across coverage"):
                        existing = api_post(api_base, f"/themes/{slug}/brief")
                if existing.get("body"):
                    st.markdown(note_html(existing["body"]), unsafe_allow_html=True)
                    st.caption(f"{existing.get('model') or 'rules'}"
                               + (f" · {existing['generated_at'][:16]} UTC"
                                  if existing.get("generated_at") else ""))
                else:
                    state("No brief written yet",
                          "Press the button to read this modality across every company in "
                          "coverage. Without a model key this is the rules layer, which "
                          "states the shape rather than a view, and says so.")


    # --- Runway: the clinical-stage cohort, where revenue analysis says nothing ---
    if runway_tab is not None:
        with runway_tab:
            rows = api_get(api_base, "/runway")
            section("Cash runway, clinical-stage companies", len(rows))
            st.caption(
                "Companies with no product revenue, which is where the revenue, exclusivity "
                "and demand tabs are empty by construction. Runway is cash and marketable "
                "securities over the trailing twelve-month operating burn, in months at the "
                "current rate, counting anything raised since the balance sheet date: a "
                "July raise is money in the bank three months before any XBRL fact carries "
                "it. It is not a forecast: a company that raises, cuts or partners moves "
                "this the day it does.")
            if not rows:
                state("No clinical-stage companies resolved",
                      "Press Refresh all to pull cash and cash-flow lines from EDGAR. A "
                      "company is read as clinical-stage when it reports neither inventory "
                      "nor a cost of revenue.")
            else:
                st.dataframe(pd.DataFrame([{
                    "Ticker": r["ticker"],
                    "Company": r["name"],
                    "Cash and investments, m": (r["cash"] / 1e6) if r["cash"] else None,
                    # Money raised after the balance sheet date, which no XBRL fact
                    # carries until the next quarter. Its own column rather than folded
                    # into cash, so the tagged figure and the read one stay separable.
                    "Raised since, m": ((r.get("raised_since") or 0) / 1e6) or None,
                    "Burn, m/yr": (abs(r["burn_annual"]) / 1e6) if r["burn_annual"] else None,
                    "Runway, months": r["runway_months"],
                    "Catalysts in runway": r["catalyst_count"],
                    "Next readout": (r["next_catalyst"]["expected_date"]
                                     if r["next_catalyst"] else None),
                    "Funded to it": ("yes" if r["funded_to_readout"] else
                                     "no" if r["funded_to_readout"] is False else
                                     "none scheduled"),
                    # Two ways the figure can mislead, said on the row rather than in a
                    # footnote: a burn paid for by a licence receipt, and a cash figure
                    # missing the securities the company actually holds its runway in.
                    "Read with care": ", ".join(filter(None, [
                        "burn offset by a receipt" if r["burn_flattered"] else "",
                        "cash line only" if not r["includes_investments"] else ""])),
                    "As of": r["cash_as_of"],
                } for r in rows]), width="stretch", hide_index=True,
                    column_config={
                        "Cash and investments, m": st.column_config.NumberColumn(format="%.0f"),
                        "Raised since, m": st.column_config.NumberColumn(format="%.0f"),
                        "Burn, m/yr": st.column_config.NumberColumn(format="%.0f"),
                        "Runway, months": st.column_config.NumberColumn(format="%.0f")})

                # The sharpest thing this page knows. A company whose next readout lands
                # after its cash does has to finance on no new data, which is the weakest
                # position a clinical-stage company can raise from. It is a different
                # situation from having no readout scheduled, and the two were previously
                # both printed as a zero.
                unfunded = [r for r in rows if r["funded_to_readout"] is False
                            and not r["burn_flattered"]]
                if unfunded:
                    section("Next readout lands after the cash", len(unfunded))
                    st.caption(
                        "At the current burn these run out of money before their next dated "
                        "readout, so they have to finance on no new data. Registry dates are "
                        "estimates and they slip, which moves this the wrong way.")
                    for r in unfunded:
                        nxt = r["next_catalyst"]
                        st.markdown(
                            f'<div class="state err"><div class="t">{r["ticker"]} · '
                            f'{r["runway_months"]:.0f} months, cash out {r["cash_out"][:7]}'
                            f'</div><div class="d">'
                            f'{r["cash"] / 1e6:,.0f}m against a '
                            f'{abs(r["burn_annual"]) / 1e6:,.0f}m annual burn. Next readout '
                            f'{html_escape(nxt["expected_date"][:7])}: '
                            f'{html_escape(nxt["title"][:90])}.</div></div>',
                            unsafe_allow_html=True)

                silent = [r for r in rows if r["funded_to_readout"] is None
                          and r["runway_months"] and r["runway_months"] < 24]
                if silent:
                    section("No dated readout on file", len(silent))
                    st.caption(
                        "Under two years of cash and nothing scheduled that the registry "
                        "dates. That is usually a gap in what has been registered rather "
                        "than a company with no plans, so it reads as unknown, not as no "
                        "catalyst.")
                    st.markdown(
                        '<div class="state"><div class="d">'
                        + html_escape(", ".join(
                            f"{r['ticker']} ({r['runway_months']:.0f}mo)" for r in silent))
                        + '</div></div>', unsafe_allow_html=True)
