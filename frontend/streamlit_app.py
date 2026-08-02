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
import engine_strip
import price_chart
import revenue_mix
import scorecard_chart
import treemap
import theme as T
import trend as trend_module
from components import charts as CH
from components import approvnav
from components import covnav
from components import enginepick
from components import prodcards
from components import drawchart
from components import render as R
from components import tokens as TK

# Overridable so run.sh can point a frontend at whichever API port it started.
DEFAULT_API = os.getenv("ER_API_BASE", "http://localhost:8000")
DEFAULT_TICKER = "LLY"

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
PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]
# How long a headline runs before it is cut, chosen to hold the box to two lines at the
# width six of them take. The full text is always the first row of the box's own detail,
# so the cut costs a click rather than the fact.
_LEAD_CHARS = 76

# How many forward-dated boxes fit before the list stops being a view and starts being a
# table. The rest are on each company's own Catalysts tab. Two across in half the page,
# so an even count fills its last row.
_AHEAD_SHOWN = 6


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
TREND_QUARTERS = 4
# The registry page for a trial, keyed by its NCT id.
# Months of catalyst calendar. Two years covers the readout horizon without a control
# to set it: the dates inside it are estimates anyway, so a tighter window would be
# false precision about which of them matter.
CALENDAR_MONTHS = 24


# --- Transport ----------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def api_get(base: str, path: str):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(base: str, path: str, timeout: int = 300):
    request = urllib.request.Request(base.rstrip("/") + path, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_json(base: str, path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_delete(base: str, path: str):
    request = urllib.request.Request(base.rstrip("/") + path, method="DELETE")
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- Presentation helpers -----------------------------------------------
def section(label: str, count=None):
    tail = f'<span class="sec-count">{count}</span>' if count is not None else ""
    st.markdown(f'<div class="sec"><span class="sec-label">{label}</span>{tail}</div>',
                unsafe_allow_html=True)


def note(text: str):
    """A byline folded away, for a view that has to fit a screen.

    The Universe tab is read at a glance and its explanations are long, because most of
    what they say is what a figure is not: area is not market capitalisation, a readout
    date is not a commitment. Deleting them would buy the height by making the page less
    honest, so they collapse to one line instead and open where a reader wants them.
    """
    st.markdown(f'<details class="note-d"><summary>notes</summary>'
                f'<div class="byline">{text}</div></details>', unsafe_allow_html=True)


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


def feed_row(item, show_reason: bool = False) -> str:
    """One feed line as type, not as a table row.

    Two or three items in a grid widget is all chrome and no content, so the feed is a
    date, a headline, and a severity, aligned on a grid. ``show_reason`` prints the
    materiality rule that flagged the item, which is what the universe brief leads with.
    """
    date = (item.get("date") or "")[:10]
    sev = item.get("significance") or "low"
    modality = (item.get("modality") or "").lower()
    css = "small" if modality.startswith("small") else "bio" if modality.startswith("bio") else ""
    headline = html_escape(item.get("headline") or "")
    if css:
        headline = f'<span class="m {css}">{headline}</span>'
    reason = (html_escape(item["reason"])
              if show_reason and item.get("reason") else "")
    # A row that has a source is the anchor itself rather than a div wrapping one, so
    # the whole line is the target and the grid it lays out in is untouched.
    url = item.get("url")
    open_tag = (f'<a class="fitem link" href="{html_escape(url)}" target="_blank" '
                'rel="noopener noreferrer">' if url else '<div class="fitem">')
    # The reason cell is always present so every row has four children and the
    # severity column stays flush right whether or not a rule is named.
    return (f'{open_tag}<span class="d">{date}</span>'
            f'<span class="t">{headline}</span><span class="why">{reason}</span>'
            f'<span class="s {sev}">{sev}</span>{"</a>" if url else "</div>"}')


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
            st.rerun()

    loe = prof.get("loe") or {}
    dem = prof.get("demand")
    rev = _headline_revenue(prof)
    loe_txt = (f'{loe.get("loe_year")}' if loe.get("loe_year") else "—")
    if loe.get("loe_earliest_year") and loe.get("loe_year") \
            and loe["loe_earliest_year"] != loe["loe_year"] \
            and "molecule" in (prof.get("modality") or "").lower():
        loe_txt = f'{loe["loe_earliest_year"]}–{loe["loe_year"]}'
    # The use patents sit beside the date rather than inside it: they run later and do
    # not hold the market, since a generic can carve the indication out of its label.
    loe_note = html_escape(loe.get("basis") or "no expiry on file")
    if loe.get("use_patent_year") and loe.get("loe_year") \
            and loe["use_patent_year"] > loe["loe_year"]:
        loe_note += f' &middot; use patents to {loe["use_patent_year"]}'
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
        f'<span class="sub">{("US " + str(dem["year"]) + ", " + T.pct(dem["spend_growth"] * 100) + " YoY") if dem and dem.get("spend_growth") is not None else ("US " + str(dem["year"]) if dem else "not in Part D/B")}</span></div>'
        f'<div><span class="k">first approval</span>'
        f'<span class="v{"" if prof.get("first_approval") else " none"}">'
        f'{(prof.get("first_approval") or "—")[:10]}</span>'
        f'<span class="sub">{html_escape((prof.get("generic") or "").lower())}</span></div>'
        '</div>')
    if prof.get("summary"):
        # The label's own first sentence, which says what the drug is and what it
        # treats. Not written here, so a product with no label carries no summary.
        st.markdown(f'<div class="prof-summary">{html_escape(prof["summary"])}</div>',
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
    st.markdown(
        '<div class="byline">Every field here is sourced: approval and supplements '
        'from openFDA, revenue from the SEC data sets, exclusivity from the Orange and '
        'Purple Books, demand from CMS, the label from DailyMed. A field with no free '
        'data is left out rather than filled.</div>', unsafe_allow_html=True)


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


def deal_card(deal) -> str:
    """One deal: a type badge, a body of counterparty, size and area, and the date."""
    badge = _DEAL_BADGE.get(deal.get("deal_type"), "Deal")
    body = [f'<span class="dp">{html_escape(deal.get("counterparty") or "")}</span>']
    if deal.get("terms_summary"):
        # The structure the press release stated, which is four commitments rather than
        # one figure: what is paid now, how much of it is equity, what is contingent on
        # data, and what only happens if an option is exercised. A single headline number
        # is wrong whichever of them it picks.
        body.append(f'<span class="dv dterms" title="{html_escape(deal.get("terms_evidence") or "")}">'
                    f'{html_escape(deal["terms_summary"])}</span>')
    elif deal.get("announced_value"):
        # Announced consideration, and the tooltip names the source that stated it,
        # since a figure a filing gives and one a headline gives are not equally firm.
        origin = {"filing": "as the filing states it",
                  "news": "as the announcing headline states it"}.get(
                      deal.get("announced_value_source"), "as announced")
        body.append(f'<span class="dv" title="Announced value, {origin}. '
                    'Consideration including milestones, not cash paid.">'
                    f'{html_escape(deal["announced_value"])}</span>')
    # A deal with no figure says nothing where the figure would go. Most pharma business
    # development is announced without terms, so "size not stated" was the commonest
    # thing on the panel and told a reader nothing they could not see. The count in the
    # section header still says how many of them carry one.
    if deal.get("area"):
        body.append(f'<span class="da">{html_escape(deal["area"])}</span>')
    # The announcing article first: a press report of a deal reads in a way a 10-Q
    # does not. The filing is the fallback, for a deal no headline has been matched to.
    url = deal.get("article_url") or deal.get("source_url")
    classes = f'deal dt-{html_escape(deal.get("deal_type") or "")}{" link" if url else ""}'
    open_tag = (f'<a class="{classes}" href="{html_escape(url)}" target="_blank" '
                'rel="noopener noreferrer">' if url
                else f'<div class="{classes}">')
    return (f'{open_tag}'
            f'<span class="db">{badge}</span>'
            f'<span class="dbody">{" &middot; ".join(body)}</span>'
            f'<span class="dd" title="{_DEAL_DATE_NOTE.get(deal.get("event_date_source"), "The date on file.")}">'
            f'{(deal.get("event_date") or "")[:10]}</span>'
            + ("</a>" if url else "</div>"))


def readout_card(readout) -> str:
    """One signed readout: a mark and the sign, the phase, the drug, the quoted sentence."""
    positive = readout.get("outcome") == "positive"
    mark = "&#10003;" if positive else "&#10007;"          # check or cross
    cls = "rd-pos" if positive else "rd-neg"
    return (f'<div class="readout {cls}"><span class="rm">{mark}</span>'
            f'<span class="rh">Ph {readout.get("phase")} {readout.get("outcome")}</span>'
            f'<span class="rbody"><span class="rp">'
            f'{html_escape(readout.get("drug") or "")}</span> '
            f'<span class="rq">{html_escape(readout.get("quote") or "")}</span></span>'
            f'<span class="rd">{(readout.get("event_date") or "")[:10]}</span></div>')


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


def statement_table(block: dict, currency: str | None,
                    common_size: bool = False) -> str:
    """One statement as a table: lines down, periods across, most recent first.

    The common-size base comes from the API, read at each column's own period. Taking
    it from a line in this grid would work for the balance sheet and silently fail for
    cash flow, whose base is revenue, which is not one of its lines and whose columns
    are cumulative where the income statement's are discrete.
    """
    periods, lines = block["periods"], block["lines"]
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
        if not common_size and unit_label not in (f"{currency} bn", "bn"):
            label += f'<span class="lu">, {html_escape(unit_label)}</span>'
        if line.get("note"):
            label = f'<span title="{html_escape(line["note"])}">{label}</span>'
        body.append(f'<tr class="{line["role"]}"><td class="l">{label}</td>'
                    + "".join(cells) + "</tr>")

    # The unit belongs in the header of the grid it describes, and it changes with the
    # mode: putting it on the section rule instead left "USD bn" standing over a table
    # of percentages.
    unit = (f'% of {block["base"]["label"].lower()}' if common_size
            else f'{currency or ""} bn'.strip())
    return (f'<div class="fin-wrap"><table class="fin">'
            f'<thead><tr><th class="l">{html_escape(unit)}</th>'
            f'{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def metric_tiles(items) -> str:
    """A row of headline figures, in one language every block can use.

    Each item is (label, value, unit, change, tone, note). The unit rides with the
    number, since a scale stated three lines away has to be worked out. The change sits
    on the same baseline as the number, because it is part of the figure rather than a
    line of its own: stacked underneath, four figures read as twelve unrelated lines.
    A note appears only where the number cannot be read without it.
    """
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
    return f'<div class="tiles">{"".join(out)}</div>'


def snapshot_meta(snapshot: dict) -> str:
    """The period and the scale, said once in the heading so no tile repeats them."""
    return " &middot; ".join(part for part in (
        snapshot.get("label"), f'ending {snapshot["period_end"]}',
        f'{snapshot.get("currency") or ""} bn unless stated') if part)


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
    ])


def _lead_box(item) -> str:
    """One headline as a box that opens onto its own detail.

    A native disclosure rather than a widget: the summary is already in the payload, so
    opening one costs no rerun and no round trip, and four of them open at once without
    the page rebuilding itself four times.
    """
    rows = "".join(
        f'<div class="lead-r"><span class="lead-rk">{html_escape(pair["label"])}</span>'
        f'<span class="lead-rv">{html_escape(pair["value"])}</span></div>'
        for pair in (item.get("summary") or []))
    quote = (f'<div class="lead-q">{html_escape(item["evidence"])}</div>'
             if item.get("evidence") else "")
    link = (f'<a class="lead-l" href="{html_escape(item["url"])}" target="_blank" '
            f'rel="noopener">source</a>' if item.get("url") else "")
    kind = html_escape((item.get("kind") or "").replace(" ", "_"))
    # The ticker leads the line in its own weight, so a reader scans the column of
    # companies first and reads the sentence second. It is already the first word of the
    # headline, so it is split off rather than repeated.
    ticker = html_escape(item.get("ticker") or "")
    text = item.get("headline") or ""
    if ticker and text.startswith(ticker + " "):
        text = text[len(ticker) + 1:]
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


def _leads(items, per_row: int, narrow_per_row: int) -> str:
    """A row of headline boxes, evenly divided at the page's two widths."""
    return (f'<div class="leads" '
            f'style="--lead-cols: {_lead_columns(len(items), per_row)}; '
            f'--lead-cols-narrow: {_lead_columns(len(items), narrow_per_row)}">'
            + "".join(_lead_box(i) for i in items) + "</div>")


def note_html(body: str) -> str:
    """Render the note, giving its section labels the heading treatment.

    The rules layer emits plain lines like "Catalysts inside 60 days (2)" followed by
    dashed items. Left as prose they read as a run-on, so labels become headings and
    dashed lines become a list.
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
    return f'<div class="note">{"".join(out)}</div>'


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

# The hero says what the terminal is before it asks which part of it you want. Kept here
# rather than in the API: it is the one string on the page that is not a measurement.
HERO_LINE = "Where the money is, where the cash runs out, and where the science is new."
HERO_SUB = (
    "Three engines over one universe of {universe} companies. Each one asks only what its "
    "cohort can answer, and each figure below is computed by the same function the engine "
    "behind it renders. Nothing is estimated to fill a gap: a company with no figure is "
    "drawn as an empty slot, never as an average.")


def _engine_panel(entry: dict) -> str:
    """One engine as a clickable panel: the spread, the sentence, the three names."""
    leaders = "".join(
        f'<div class="e-row"><span class="e-tk">{html_escape(leader["ticker"])}</span>'
        f'<span class="e-val">{html_escape(leader["display"])}</span></div>'
        for leader in entry["leaders"])
    return (
        f'<div class="engine {html_escape(entry["key"])}">'
        f'<div class="e-head"><span class="e-name">{html_escape(entry["label"])}</span>'
        f'<span class="e-count">{entry["count"]} '
        f'{html_escape(entry["count_label"])}</span></div>'
        f'<div class="e-tag">{html_escape(entry["tagline"])}</div>'
        f'<div class="e-strip">{engine_strip.build(entry["strip"])}</div>'
        f'<div class="e-metric">{html_escape(entry["metric"])}</div>'
        f'<div class="e-headline">{html_escape(entry["headline"] or "")}</div>'
        f'<div class="e-leaders">{leaders}</div>'
        f'<div class="e-foot"><span class="e-detail">'
        f'{html_escape(entry["detail"])}</span>'
        f'<span class="go">Open <span class="arrow">&rarr;</span></span></div>'
        f'</div>')


def _signal_rows(board: dict) -> str:
    """The week's most material changes, one per company, each a link to that company."""
    rows = "".join(
        f'<div class="sig" data-ticker="{html_escape(item["ticker"])}" tabindex="0"'
        f' role="button"><span class="s-date">{html_escape(item["date"])}</span>'
        f'<span class="s-tk {html_escape(item["engine"] or "")}">'
        f'{html_escape(item["ticker"])}</span>'
        f'<span class="s-kind">{html_escape(item["kind"])}</span>'
        f'<span class="s-text">{html_escape(item["headline"] or "")}</span>'
        f'<span class="s-go">&rarr;</span></div>'
        for item in board["signals"])
    if not rows:
        return ""
    return ('<div class="sig-head"><span class="sig-label">Signals</span>'
            f'<span class="sig-note">the {len(board["signals"])} that matter most in '
            f'{board["signal_days"]} days</span></div>' + rows)


if not engine and not (st.query_params.get("ticker") or ""):
    board = api_get(api_base, "/engines")
    hero = (
        '<div class="hero"><div class="hero-top">'
        '<span class="wordmark">Novatalis</span>'
        f'<span class="hero-count">{board["universe"]} companies</span></div>'
        f'<div class="hero-line">{HERO_LINE}</div>'
        f'<div class="hero-sub">{HERO_SUB.format(universe=board["universe"])}</div></div>')
    picked = enginepick.engine_pick(
        [{"engine": entry["key"], "html": _engine_panel(entry)}
         for entry in board["engines"]],
        hero=hero, signals_html=_signal_rows(board),
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

# A click on the approvals timeline names a company and an application number. The
# company is applied here, before the selector reads its key; the application number is
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
    filer = "not an SEC filer"
elif company.get("is_foreign_private_issuer"):
    filer = "20-F filer"
else:
    filer = "10-K filer"
quote = prices.get("currency")
meta = " · ".join(x for x in [company.get("exchange"), filer,
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

main, rail_col = st.columns([1, 0.34], gap="medium")

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
    _wanted += [("catalysts", "Catalysts"), ("themes", "Themes")]
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
    themes_tab = _panels["themes"]
    comps_tab = _panels["comps"]
    news_tab = _panels["news"]
    portfolio_tab = _panels.get("portfolio")
    runway_tab = _panels.get("runway")

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
        leads = api_get(api_base, f"/headlines?engine={urllib.parse.quote(engine or '')}")
        section("Headlines this week", f"{len(leads)} across {_engine_name}" if leads
                else _engine_name)
        if not leads:
            state(f"Nothing material on {_engine_name} in the last week",
                  "A headline is a deal with stated terms, an approval, an FDA notice, a "
                  "senior change or a trial stopping. Quiet is an answer.")
        else:
            st.markdown(_leads(leads, 6, 3), unsafe_allow_html=True)
        _all_changes = api_get(api_base, "/changes")
        universe_feed = [it for it in _all_changes
                         if (it.get("ticker") or "") in _covered]
        # The universe view leads with FDA approvals, the cleanest cross-coverage signal,
        # drawn on a date axis rather than a jargon-heavy list; the full change feed with
        # filings, trial moves and risk-factor edits lives on each company's Key insights.
        approvals = []
        for it in universe_feed:
            if it.get("change_type") != "new_approval":
                continue
            drug = (it.get("headline") or "").split("FDA approval:", 1)[-1].strip()
            # The headline carries the application number in brackets, which is what
            # identifies the product on the Portfolio tab; it rides along as the click
            # key so a mark can open its own fact sheet.
            appno = re.search(r"\(([A-Za-z]{2,4}\s?\d+)\)", drug)
            tk = it.get("ticker") or ""
            approvals.append({"ticker": tk,
                              "label": drug.split(" (")[0].strip(),
                              "date": it.get("date"),
                              "key": (f"{tk}|{appno.group(1).replace(' ', '')}"
                                      if appno and tk else ""),
                              "full": f"{drug} — {(it.get('date') or '')[:10]}"})
        section(f"FDA approvals across {_engine_name}", f"{len(approvals)} on the tape")
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
        _map_col, _ahead_col = st.columns(2, gap="medium")
        with _map_col:
            # The group at a glance before the ninety panels that show each shape. Area is
            # what the engine runs on and colour is the move, read independently: a large box
            # that is deep red is the thing this view exists to show.
            mmap = api_get(api_base,
                           f"/marketmap?engine={urllib.parse.quote(engine or '')}")
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


        section("Coverage, 90 days", f"{len(_covered)} companies, one scale")
        panels = [p for p in api_get(api_base, "/price-grid?days=90")
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
            note("Click a panel to jump straight to that company's Key insights.")
        else:
            state("No price history yet",
                  "Press Refresh all in the top bar to pull daily closes.")

    # --- Key insights: the feed is the most important view ---------------
    with insights_tab:
        # A briefing opens with where the company stands, then layers on what moved.
        # Built only from diffs it read as empty for most companies: LLY showed zero.
        pipeline_rows = api_get(api_base, "/pipeline")
        mine = next((r for r in pipeline_rows if r["ticker"] == ticker), {})
        phases = mine.get("phases") or {}
        # Counted the same way the Pipeline tab counts, so the two tabs cannot disagree.
        # Phase 4 is work on approved products, so it is not development; long-term
        # follow-up and extension studies carry a development phase but are lifecycle
        # work, counted from the title by /pipeline and subtracted here too.
        in_development = (sum(count for phase, count in phases.items()
                              if phase not in POST_APPROVAL)
                          - (mine.get("follow_up") or 0))
        late = sum(phases.get(p, 0) for p in ("Phase 3", "Phase 2/3"))

        def _next(kind):
            dates = sorted((it["date"] or "")[:10] for it in feed
                           if it["kind"] == kind and it["date"])
            return dates[0] if dates else None

        points = prices.get("points") or []

        def _move(series):
            if len(series) < 2 or not series[0]["close"]:
                return None
            return (series[-1]["close"] - series[0]["close"]) / series[0]["close"] * 100

        intraday = api_get(api_base, f"/companies/{ticker}/intraday")
        bars = intraday.get("points") or []
        change = _move(points)   # whole stored history
        # From the intraday bars, so the headline number and the sparkline beneath it
        # describe the same window rather than two nearly-equal ones.
        recent = _move(bars) if bars else _move(points[-SPARK_SESSIONS:])
        high = sum(1 for it in feed if it["significance"] == "high")

        cells = [
            ("last close", T.num(prices["latest"]["close"], 2) if points else "—",
             "" if points else "none", prices.get("currency") or ""),
            # The headline move matches the sparkline beneath it; the long run is the
            # context under it rather than a second number competing with it.
            (f'{len(intraday.get("sessions") or []) or SPARK_SESSIONS} day', T.pct(recent),
             "up" if (recent or 0) >= 0 else "down",
             f"5y {T.pct(change)}" if change is not None else ""),
            ("in development", str(in_development) if mine else "—",
             "" if mine else "none", f"{late} in late phase" if mine else ""),
            ("next catalyst", _next("catalyst") or "none", "" if _next("catalyst") else "none",
             "readouts and PDUFA"),
            ("next loe", _next("loe") or "none", "" if _next("loe") else "none",
             "inside 24 months"),
            ("flagged", str(len(feed)), "down" if high else "", f"{high} high" if high else "nothing high"),
        ]
        # The position strip and the two note actions share the top row: the strip fills
        # the width, and Generate and Tearsheet stack small on the right at the same level.
        strip_col, btn_col = st.columns([6, 0.75])
        with strip_col:
            st.markdown(
                '<div class="pos">' + "".join(
                    f'<span><span class="k">{k}</span>'
                    f'<span class="v {cls}">{v}</span>'
                    f'<span class="sub">{sub}</span></span>' for k, v, cls, sub in cells)
                + "</div>", unsafe_allow_html=True)
        with btn_col:
            regenerate = st.button("Generate", key="gen_note", width="stretch")
            write_sheet = st.button("Tearsheet", key="gen_sheet", width="stretch")

        # Fifteen minute bars over the last five sessions, spanning the column above the
        # note. A briefing wants the shape of the week, which daily closes cannot show:
        # five points is a zigzag, not a market. Bars are butted together in order, never
        # on a time axis that would draw a flat line through overnight hours that never
        # traded; the session marks say where each trading day begins.
        if bars:
            closes = [b["close"] for b in bars]
            session_starts = [i for i, b in enumerate(bars)
                              if i and b["as_of"][:10] != bars[i - 1]["as_of"][:10]]
            R.show(CH.sparkline(closes, 832, 72, label_last=True, marks=session_starts),
                   css_class="chart-mount stretch")

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

        section("Morning note")

        if regenerate:
            with st.spinner(f"Writing the {ticker} note"):
                st.session_state["note"] = api_get(
                    api_base, f"/companies/{ticker}/note?refresh=true")
        elif st.session_state.get("note", {}).get("ticker") != ticker:
            st.session_state["note"] = api_get(api_base, f"/companies/{ticker}/note")

        note = st.session_state.get("note") or {}
        if not note.get("body"):
            state(f"No note for {ticker} yet",
                  "Press Generate. Without an Anthropic key the note is the rules "
                  "layer, which lists the flagged items grouped by kind.")
        else:
            st.markdown(note_html(note["body"]), unsafe_allow_html=True)
            layer = ("rules layer, no Anthropic key set" if note.get("model") == "rules"
                     else f"written by {note.get('model')}")
            st.markdown(
                f'<div class="byline">{layer} · written {note.get("generated_at")} '
                'from the feed as it stood then. Press Generate to rebuild it.</div>',
                unsafe_allow_html=True)
        if note.get("error"):
            state("The note fell back to the rules layer", note["error"], error=True)

        # --- What matters now, in structured sections --------------------
        # Broken out by the thing that moves a case, not by the snapshot-diff mechanics.
        # Catalysts, exclusivity and material filings come from the feed; deals and
        # readouts are read from their own endpoints. The raw "changes since the last
        # refresh" list, trial status and date wording, is dropped from this view: it read
        # as jargon and the events that matter surface in the sections below instead.
        deals_data = api_get(api_base, f"/companies/{ticker}/deals").get("deals") or []
        readouts_data = api_get(api_base, f"/companies/{ticker}/readouts").get("readouts") or []
        catalyst_items = [it for it in feed if it["kind"] == "catalyst"]
        loe_items = [it for it in feed if it["kind"] == "loe"]
        filing_items = [it for it in feed if it["kind"] == "filing"]

        if not (deals_data or readouts_data or catalyst_items or loe_items or filing_items):
            section("Nothing flagged")
            state(f"Nothing coming up for {ticker}",
                  "The position above is current either way. Catalysts, deals, readouts "
                  "and exclusivity fill in as refreshes run; a refresh from the Prices "
                  "tab pulls the latest.")

        if catalyst_items:
            section("Catalysts inside 60 days", len(catalyst_items))
            st.markdown('<div class="feed">' + "".join(
                feed_row(it, show_reason=True) for it in catalyst_items) + "</div>",
                unsafe_allow_html=True)

        if deals_data:
            size = deal_size(deals_data)
            section("Deals", f"{len(deals_data)} &middot; {size}" if size
                    else len(deals_data))
            st.markdown('<div class="deals">' + "".join(
                deal_card(d) for d in deals_data) + "</div>", unsafe_allow_html=True)

        if readouts_data:
            section("Trial readouts", len(readouts_data))
            st.markdown('<div class="readouts">' + "".join(
                readout_card(r) for r in readouts_data) + "</div>",
                unsafe_allow_html=True)
            st.markdown('<div class="byline">Phase 2 and 3 topline results classified '
                        'from the press releases, each with the sentence that carried it. '
                        'A check met the endpoint, a cross missed.</div>',
                        unsafe_allow_html=True)

        if loe_items:
            section("Loss of exclusivity ahead", len(loe_items))
            st.markdown('<div class="feed">' + "".join(
                feed_row(it) for it in loe_items) + "</div>", unsafe_allow_html=True)

        if filing_items:
            section("Recent material filings", len(filing_items))
            st.markdown('<div class="feed">' + "".join(
                feed_row(it) for it in filing_items) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="byline">Material 8-K items beyond the deals above: '
                        'impairments, terminations and other agreements.</div>',
                        unsafe_allow_html=True)

    # --- Prices ----------------------------------------------------------
    with prices_tab:
        section("Price", prices.get("currency") or "")
        if st.button("Refresh prices", key="refresh_prices"):
            run_refresh(api_base, f"/refresh?ticker={urllib.parse.quote(ticker)}",
                        "price_run", f"Refreshing {ticker} from Yahoo")
            st.rerun()

        # The bar interval and the line/candle view. The window radio comes after the base
        # series loads, since which windows can be filled depends on how far it reaches.
        ctrl_int, ctrl_view = st.columns([3.6, 1.4])
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
            st.markdown(
                '<div class="stats">'
                f'<span class="stat"><span class="k">last</span>'
                f'<span class="v">{T.num(latest_close, 2)}</span></span>'
                f'<span class="stat"><span class="k">as of</span>'
                f'<span class="v">{str(chart_rows[-1]["as_of"])}</span></span>'
                f'<span class="stat"><span class="k">{span} change</span>'
                f'<span class="v {"risk" if (change or 0) < 0 else ""}">'
                f'{T.pct(change)}</span></span>'
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

            # A bidirectional lightweight-charts component: native two-finger zoom that
            # stretches the sticks and auto-fits the y-axis, plus trendlines you can draw,
            # drag and delete. The line set round-trips back and is persisted as one
            # annotation row per ticker, so drawings survive a refresh.
            data = price_chart.series_data(chart_rows, view, intraday)
            # "rule" draws the chart's gridlines only, so it takes the faint token: a
            # price chart draws far more lines than a table draws borders, and at the
            # hairline weight the mesh competes with the series it is there to measure.
            theme = {"ground": TK.GROUND, "muted": TK.MUTED, "rule": TK.RULE_FAINT,
                     "rule_strong": TK.RULE_STRONG, "up": TK.UP, "down": TK.DOWN,
                     "flag": TK.FLAG}

            saved = api_get(api_base, f"/annotations?ticker={urllib.parse.quote(ticker)}"
                                      "&entity_type=price_line")
            stored_id = saved[0]["id"] if saved else None
            try:
                stored_lines = json.loads(saved[0]["body"]) if saved else []
            except (ValueError, TypeError):
                stored_lines = []

            draw_row = st.columns([1.2, 1.1, 1.6, 1.2, 2.4])
            with draw_row[0]:
                show_events = st.toggle("Events", value=True, key=f"events_{ticker}")
            with draw_row[1]:
                show_grid = st.toggle("Grid", value=True, key=f"grid_{ticker}")
            with draw_row[2]:
                draw_mode = st.toggle("Draw trendlines", key=f"drawtoggle_{ticker}")
            with draw_row[3]:
                if stored_lines and st.button("Clear lines", key=f"clearlines_{ticker}"):
                    if stored_id is not None:
                        api_delete(api_base, f"/annotations/{stored_id}")
                    st.rerun()

            # Gridlines off is the background colour rather than a transparent value,
            # which the chart library would fall back to its own default for.
            theme = dict(theme, rule=TK.RULE_FAINT if show_grid else TK.GROUND)

            # Approval and LOE markers only when the toggle is on, so the price can be read
            # clean.
            markers = price_chart.event_markers(
                chart_rows, events if show_events else [], intraday)
            result = drawchart.draw_chart(
                data=data, markers=markers, mode=view, intraday=intraday,
                lines=stored_lines, draw_mode=bool(draw_mode), theme=theme,
                view_key=f"{ticker}|{interval}|{view}", height=560,
                key=f"drawchart_{ticker}")
            # The component returns the current line set; persist it only when it changes,
            # replacing the single stored row (a converging round-trip, no loop).
            if result is not None and result != stored_lines:
                if stored_id is not None:
                    api_delete(api_base, f"/annotations/{stored_id}")
                if result:
                    api_post_json(api_base, "/annotations", {
                        "ticker": ticker, "entity_type": "price_line",
                        "entity_id": None, "body": json.dumps(result)})
                st.rerun()

            shown = len(markers)
            st.markdown(
                '<div class="byline">'
                '<span style="color:var(--up)">▲</span> FDA approval'
                '&nbsp;&nbsp;<span style="color:var(--down)">▼</span> loss of '
                f'exclusivity &nbsp;·&nbsp; {shown} on this view. Read from the '
                'approvals and exclusivity data; a date outside the loaded window is not '
                'marked here.</div>', unsafe_allow_html=True)
            if intraday:
                st.markdown('<div class="byline">Intraday is a rolling window from the free '
                            'feed: minutes reach back about two months, hours about two '
                            'years. Older bars are unavailable, not missing.</div>',
                            unsafe_allow_html=True)

    # --- Financials ------------------------------------------------------
    with financials_tab:
        # The widget key is the source of truth, read before the widget renders. Keeping
        # a second copy of the choice would fetch on the previous basis for one rerun,
        # so the grid would lag a click behind the control.
        basis_key = f"fin_basis_{ticker}"
        wanted = st.session_state.get(basis_key, "Quarterly")

        def fetch(basis):
            return api_get(api_base,
                           f"/companies/{ticker}/statements?basis={basis}")

        built = fetch("annual" if wanted == "Annual" else "quarterly")
        if built["basis"] == "quarterly" and not built["has_interim"]:
            built = fetch("annual")     # a 20-F filer has no quarters to show
        snapshot = built.get("snapshot")

        section("Latest reported", snapshot_meta(snapshot) if snapshot else None)
        if snapshot:
            st.markdown(snapshot_strip(snapshot), unsafe_allow_html=True)

            # --- Cash generation and leverage ---------------------------------
            # What the company kept, not what it earned. Both are computed from lines
            # already filed; a figure missing an input is a dash naming the line it wanted.
            cash = api_get(api_base, f"/companies/{ticker}/cashflow")
            cf_cur = cash.get("currency") or ""
            # No second heading: the quarter above and the year here are one reading of
            # the company, and two headers stacked made it read as two walls of figures.
            # A rule and the period label carry the change of basis instead.
            section("Cash and leverage",
                    f'{("FY" + str(cash["fiscal_year"])) if cash.get("fiscal_year") else "latest year"}'
                    f' &middot; {cf_cur} bn unless stated')

            def _cf_bn(value, dp=1):
                return T.num(value / 1e9, dp) if value is not None else None

            def _cf_x(value, dp=2):
                return f"{value:.{dp}f}x" if value is not None else None

            # Two tiers, in the same language as the period above. The cash a year
            # produced leads as tiles; leverage and deal spend support it and sit in one
            # quiet line, so the tab reads as a page with a point rather than a wall.
            st.markdown(metric_tiles([
                ("Free cash flow", _cf_bn(cash.get("fcf")), "bn", "", "", ""),
                ("FCF margin", (T.pct(cash["fcf_margin"] * 100, 1)
                                if cash.get("fcf_margin") is not None else None),
                 "", "", "", "of revenue"),
                ("Cash conversion", _cf_x(cash.get("cash_conversion")), "", "", "",
                 "FCF over net income"),
                # Cash paid is not the announced value on the deals, and the two figures
                # are one click apart, so this one says which it is.
                ("Acquisitions", _cf_bn((cash.get("inputs") or {}).get(
                    "acquisitions")), "bn", "", "", "cash paid"),
            ]), unsafe_allow_html=True)

            # The same scale as the tiles above, said on each figure, since this line
            # is read across rather than down and a bare 38.0 beside a 1.20x does not
            # say which of the two is money.
            cf_second = [
                ("net debt", _cf_bn(cash.get("net_debt")), "bn"),
                ("net debt / EBITDA", _cf_x(cash.get("net_debt_ebitda")), ""),
                ("EBITDA", _cf_bn(cash.get("ebitda")), "bn"),
                ("businesses", _cf_bn((cash.get("inputs") or {}).get(
                    "acquisitions_businesses"), 2), "bn"),
                ("assets", _cf_bn((cash.get("inputs") or {}).get(
                    "acquisitions_assets"), 2), "bn"),
            ]
            st.markdown(
                '<div class="metricbar">' + "".join(
                    f'<div><span class="k">{html_escape(label)}</span>'
                    f'<span class="v{"" if value else " none"}">'
                    + (f'{html_escape(value)}<span class="u">{unit}</span>'
                       if value else "—")
                    + '</span></div>'
                    for label, value, unit in cf_second) + '</div>',
                unsafe_allow_html=True)
            cf_inputs = cash.get("inputs") or {}
            cf_missing = [name.replace("_", " ") for name, value in cf_inputs.items()
                          if value is None and name not in
                          ("cash_lines", "debt_as_of", "operating_income_basis")]
            cf_derived = str(cf_inputs.get("operating_income_basis") or "")
            cash_notes = "".join((
                ('Operating income is not tagged by this filer, so EBITDA takes the '
                 'subtraction its income statement already shows: revenue less cost of '
                 'sales, R&D and SG&A. ' if cf_derived.startswith("derived") else ''),
                (f'Nothing is computed from a line the filer did not tag: this company '
                 f'is missing {html_escape(", ".join(cf_missing))}.'
                 if cf_missing else ''),
            ))
            if cash_notes:
                st.markdown(f'<div class="byline">{cash_notes}</div>',
                            unsafe_allow_html=True)

            # The quarterly panel shows the most recent year, one bar per quarter. Growth
            # is year-over-year on the whole series, so the last four keep their real
            # comparison; the older quarters are dropped from the view, not the maths.
            # Annual is left whole, since a four-year panel is too short to read a trend.
            trend_points = built.get("trend") or []
            if built["basis"] == "quarterly":
                trend_points = trend_points[-TREND_QUARTERS:]

            # Built as SVG rather than through Altair. A chart made inside a hidden tab
            # is measured at a few pixels and draws about 160px wide for good (see the
            # chart helper), and this panel has to hold its width on this tab.
            panel = trend_module.render(trend_points, built["basis"])
            if panel:
                section("Growth against margin")
                st.markdown(f'<div class="trend">{panel}</div>', unsafe_allow_html=True)
        elif not built["is_sec_filer"]:
            state(f"{ticker} does not file with the SEC",
                  "Roche and Bayer are not SEC registrants, so EDGAR holds no company "
                  "facts for them. Their financials come from investor relations, "
                  "which this build does not read.")
        else:
            state(f"No financials on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull EDGAR company facts.")

        if snapshot:
            section("Statements")
            controls = st.columns([1.1, 1.3, 1.4])
            with controls[0]:
                # An annual-only filer gets no toggle at all. Offering a control that
                # can only produce an empty grid is worse than not offering it.
                if built["has_interim"]:
                    st.radio("Basis", ["Quarterly", "Annual"], horizontal=True,
                             label_visibility="collapsed", key=basis_key)
            with controls[1]:
                which = st.radio(
                    "Statement", [label for _, label in STATEMENT_ORDER],
                    horizontal=True, label_visibility="collapsed",
                    key=f"stmt_{ticker}")
            with controls[2]:
                common_size = st.checkbox("Common size", key=f"cs_{ticker}")

            key = next(k for k, label in STATEMENT_ORDER if label == which)
            block = built["statements"][key]
            if not block["periods"]:
                state(f"No {which.lower()} for this basis",
                      "The filer tags nothing here for the periods selected.")
            else:
                st.markdown(
                    statement_table(block, built["currency"], common_size),
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
        # --- R&D productivity, before the valuation comps ---------------------
        board = api_get(api_base, "/productivity/scorecard")
        placed = board["placed"]
        if placed:
            section("R&D against commercial performance", f"{len(placed)} placed")
            st.caption(
                "Each axis is a weighted score against the companies on the chart, so "
                "the lines cross at their average rather than at any absolute standard. "
                "Research is portfolio freshness at half weight, approvals in five "
                "years at three tenths, and the share of the pipeline in Phase 3 at two "
                "tenths. Commercial is revenue growth at six tenths and net margin at "
                "four. A company ahead on both is picked out in colour.")
            st.markdown(scorecard_chart.build(placed), unsafe_allow_html=True)

            both = [r["ticker"] for r in placed if r["quadrant"] == "Both"]
            if both:
                st.caption(
                    "Ahead of these peers on both axes: " + ", ".join(both) + ". "
                    + (f"{len(board['gaps'])} companies are not placed, because a "
                       "composite built over whatever inputs happened to exist would "
                       "rank one company on two measures against another on five."
                       if board["gaps"] else ""))

        prod = api_get(api_base, "/productivity")
        measured = [r for r in prod if r["fresh_share"] is not None]
        section("R&D productivity", f"{len(measured)} of {len(prod)} measurable")
        st.caption(
            "Portfolio freshness is the share of product revenue earned by drugs "
            "approved in the last five years. It is the productivity question that "
            "lands on the income statement: spend per approval divides this year's "
            "research budget by an output it did not buy, so it sits beside as the "
            "reference point rather than the answer. Freshness is refused, with the "
            "reason, where too little of a company's revenue maps to a dated drug. "
            "A filing that discloses a franchise rather than a drug, as GSK does with "
            "Shingles and Meningitis, is resolved through a curated membership map in "
            "data/franchise_map.csv. Only the membership is curated: the dates still "
            "come from the register, and a franchise whose products straddle the "
            "five-year line is left unresolved rather than assigned to whichever one "
            "suits.")
        if prod:
            st.dataframe(pd.DataFrame([{
                "Ticker": r["ticker"],
                "Fresh revenue, %": (r["fresh_share"] * 100
                                     if r["fresh_share"] is not None else None),
                "Revenue dated, %": r["fresh_coverage"] * 100,
                "Revenue, bn": (r["revenue_latest"] / 1e9
                                if r["revenue_latest"] else None),
                "R&D, bn": r["rd_latest"] / 1e9 if r["rd_latest"] else None,
                "R&D, % of revenue": (r["rd_intensity"] * 100
                                      if r["rd_intensity"] else None),
                "Approvals, 5y": r["approvals_window"],
                "R&D per approval, bn": (r["rd_per_approval"] / 1e9
                                         if r["rd_per_approval"] else None),
                "Phase 3 share, %": (r["late_share"] * 100
                                     if r["late_share"] is not None else None),
                # Empty rather than None: a measured company has no reason to give,
                # and the word "None" in that column reads as a value.
                "Why not measured": r["fresh_reason"] or "",
            } for r in prod]), width="stretch", hide_index=True,
                column_config={
                    "Fresh revenue, %": st.column_config.NumberColumn(format="%.0f"),
                    "Revenue dated, %": st.column_config.NumberColumn(format="%.0f"),
                    "Revenue, bn": st.column_config.NumberColumn(format="%.0f"),
                    "R&D, bn": st.column_config.NumberColumn(format="%.1f"),
                    "R&D, % of revenue": st.column_config.NumberColumn(format="%.0f"),
                    "R&D per approval, bn": st.column_config.NumberColumn(format="%.1f"),
                    "Phase 3 share, %": st.column_config.NumberColumn(format="%.0f")})

            if measured:
                lead, lag = measured[0], measured[-1]
                st.markdown(
                    f'<div class="state"><div class="t">Portfolio renewal splits the '
                    f'group</div><div class="d">'
                    f'{lead["ticker"]} earns {lead["fresh_share"]:.0%} of its identified '
                    f'product revenue from drugs approved since '
                    f'{dt.date.today().year - 5}, against {lag["fresh_share"]:.0%} at '
                    f'{lag["ticker"]}. Spending does not explain it: '
                    f'{lead["ticker"]} runs R&amp;D at '
                    f'{lead["rd_intensity"]:.0%} of revenue and {lag["ticker"]} at '
                    f'{lag["rd_intensity"]:.0%}.</div></div>',
                    unsafe_allow_html=True)

            # Said plainly rather than left for the reader to infer from blanks. Three
            # of the P3i measures have no free route at all, and a panel that quietly
            # omitted them would read as though these were the whole picture.
            st.caption(
                "Not shown, because no free source carries them: market access and "
                "prior-authorisation rates, which come from payer claims; multi-year "
                "launch revenue curves, since the revenue table holds one year; and "
                "probability of technical success, which needs a cohort followed "
                "forward rather than the single cross-section stored here. Development "
                "timelines are absent for the same reason the pipeline trend is: the "
                "trials table keeps studies that are still running, so the early work "
                "behind an approved drug has already left it.")

        section("Comparables", "18 companies")
        if st.button("Refresh all", key="refresh_all"):
            run_refresh(api_base, "/refresh?scope=all", "all_run",
                        "Refreshing the universe")
            st.rerun()

        # Multi-company comparison: pick a metric and the companies, one coloured line
        # each over the fiscal years. Both ratios are currency-internal, so filers who
        # report in different currencies still compare.
        ct = api_get(api_base, "/comps/trend")
        ct_labels = ct.get("labels") or []
        ct_by = {c["ticker"]: c for c in ct.get("companies") or []}
        if ct_labels and ct_by:
            section("Compare over time", "revenue growth or net margin")
            # Pills, not a radio and a dropdown: every company is one click away and the
            # selection is readable without opening anything. A dropdown hid which
            # companies were on the chart behind a closed control.
            metric_label = st.pills(
                "Metric", ["Revenue growth", "Net margin"],
                default="Revenue growth", key="comps_metric",
                label_visibility="collapsed") or "Revenue growth"
            metric_key = ("revenue_growth" if metric_label == "Revenue growth"
                          else "net_margin")
            default_sel = [t for t in (ticker, "LLY", "NVO", "MRK", "PFE")
                           if t in ct_by][:5]
            picked = st.pills(
                "Companies", sorted(ct_by), selection_mode="multi",
                default=default_sel, key="comps_pick",
                label_visibility="collapsed") or []
            palette = [TK.UP, TK.ORANGE_BOOK, TK.PURPLE_BOOK, TK.DOWN, TK.FLAG, TK.MUTED]
            series = [{"name": tk,
                       "values": [v * 100 if v is not None else None
                                  for v in ct_by[tk][metric_key]],
                       "colour": palette[i % len(palette)]}
                      for i, tk in enumerate(picked)]
            if series:
                R.show(CH.line_chart(series, ct_labels, 1040, 360,
                                     y_fmt=lambda v: f"{v:.0f}%"),
                       css_class="chart-mount stretch")
                st.markdown(
                    '<div class="byline">Year-over-year revenue growth or net margin per '
                    'fiscal year, one line per company; a line breaks where a year is '
                    'missing rather than bridging it. Both are currency-internal, so a '
                    'euro filer and a dollar filer compare directly.</div>',
                    unsafe_allow_html=True)
            else:
                state("Pick companies to compare",
                      "Choose one or more from the control above.")

        comps = api_get(api_base, "/comps")
        screen_rows = {r["ticker"]: r for r in api_get(api_base, "/screen")}
        spark_rows = {p["ticker"]: p["closes"] for p in
                      api_get(api_base, "/price-grid?days=90")}
        # The scatter and heatmap below keep reading this clean-named frame.
        display = pd.DataFrame([{
            "Ticker": c["ticker"], "Name": c["name"], "FY": c["fiscal_year"],
            "Cur": c["currency"],
            "Revenue": c["revenue"] / 1e9 if c["revenue"] else None,
            "Growth": c["revenue_growth"] * 100 if c["revenue_growth"] is not None else None,
            "Net margin": c["net_margin"] * 100 if c["net_margin"] is not None else None,
            "R&D": c["rd_pct"] * 100 if c["rd_pct"] is not None else None,
            "Mkt cap": c["market_cap"] / 1e9 if c["market_cap"] else None,
            "P/E": c["pe"], "EV/Sales": c["ev_sales"]} for c in comps])

        # The screen: comparables plus the derived analyst columns, one row per
        # company, an inline 90-day sparkline per row. Any column missing an
        # input is a dash, never a computed placeholder.
        def _sc(tk, field, scale=1.0):
            value = (screen_rows.get(tk) or {}).get(field)
            return value * scale if value is not None else None

        screen_table = pd.DataFrame([{
            "Ticker": row["Ticker"],
            "90d": spark_rows.get(row["Ticker"]) or None,
            "Cur": row["Cur"],
            # The converted figure, not the filed one: a column that ranks companies
            # cannot hold kroner beside dollars. Cur still names what was filed.
            "Revenue, $bn": _sc(row["Ticker"], "revenue", 1e-9),
            "Growth, %": row["Growth"],
            "Margin, %": row["Net margin"],
            "R&D, %": row["R&D"],
            "Late trials": _sc(row["Ticker"], "late_trials"),
            "Rev/late trial, $bn": _sc(row["Ticker"], "revenue_per_late_trial", 1e-9),
            "LOE 5y, %": _sc(row["Ticker"], "loe_share_5y", 100),
            "Unpriced 5y": _sc(row["Ticker"], "loe_unpriced_5y"),
            "Cat 12m": _sc(row["Ticker"], "catalysts_12m"),
            "TTM px, %": _sc(row["Ticker"], "ttm_price_change", 100),
            "Mkt cap, $bn": row["Mkt cap"],
            "P/E": row["P/E"]} for _, row in display.iterrows()])
        numeric_cols = [c for c in screen_table.columns
                        if c not in ("Ticker", "Cur", "90d")]
        int_cols = ("Late trials", "Unpriced 5y", "Cat 12m")
        formats = {c: (lambda v, ic=(c in int_cols):
                       T.num(v, 0 if ic else 1)) for c in numeric_cols}
        styled = (screen_table.style
                  .format(formats, na_rep="—", subset=numeric_cols)
                  .map(lambda v: f"color:{T.P.oxblood}"
                       if isinstance(v, (int, float)) and not pd.isna(v) and v < 0
                       else "", subset=numeric_cols))
        st.dataframe(styled, width="stretch", hide_index=True,
                     column_config={"90d": st.column_config.LineChartColumn(
                         "90d", width="small")})
        st.markdown(
            '<div class="byline">Revenue is converted to dollars at the ECB daily '
            'reference rate so the column ranks, and Cur names the currency the company '
            'actually files in; a currency with no rate on file shows a dash rather than '
            'being counted at par. Derived columns: late trials are lead-sponsored '
            'Phase 3 and Phase 2/3; revenue per late trial divides that converted '
            'revenue by the count; LOE 5y is the share of tagged product revenue whose '
            'US protection expires inside five years, with the unpriced product count '
            'beside it. A dash is a missing input, never zero.</div>',
            unsafe_allow_html=True)

        # A matrix of every company against every phase, so it belongs with the
        # other cross-sectional views rather than in a tab that is otherwise one
        # company at a time.
        rows = api_get(api_base, "/pipeline")
        unattributed = sum(r.get("unattributed", 0) for r in rows)
        section("Compounds in development by phase",
                "lead sponsored" + (f" · {unattributed} trials unattributed"
                                    if unattributed else ""))
        # No total column: it counts every phase, and carrying an all-phases figure
        # beside development-only columns is the disagreement this view just lost.
        grid = pd.DataFrame([{"Ticker": r["ticker"], **r["compounds"]} for r in rows])
        if grid[DISPLAY_PHASES].to_numpy().sum() == 0:
            state("No compounds mapped",
                  "Press Refresh all on the Comps tab to pull trials from "
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
            R.show(CH.heatmap_grid(list(grid["Ticker"]), DISPLAY_PHASES, cells,
                                   860, 460))
            st.markdown(
                '<div class="byline">Each compound is counted once, at the furthest '
                'phase it has reached, so a row is the number of candidates a company '
                'has rather than the number of protocols it has registered. Counting '
                'studies measured how finely a programme was split: on trials '
                'AstraZeneca ran more than twice Pfizer\'s Phase 3, where on compounds '
                'the two are level. A trial whose intervention names nothing on file has '
                'no compound to attribute and is counted nowhere; the figure above says '
                'how many.</div>', unsafe_allow_html=True)

        scatter_rows = display.dropna(subset=["Growth", "Net margin"])
        if not scatter_rows.empty:
            section("Growth against margin", f"{ticker} marked")
            R.show(CH.scatter(
                [{"label": row["Ticker"], "x": row["Growth"],
                  "y": row["Net margin"], "selected": row["Ticker"] == ticker}
                 for _, row in scatter_rows.iterrows()],
                832, 300, x_label="Revenue growth, %", y_label="Net margin, %"))

    # --- Pipeline --------------------------------------------------------
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
        section(f"{ticker} by therapeutic area")
        # Defined before the branch: the programme list below reads these, and a company
        # with no trials draws no pills to set them.
        area_pick: list = []
        phase_pick: list = []
        if not every:
            state(f"No trials on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull ClinicalTrials.gov, "
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
                stack_rows.append({"label": area, "segments": segments})
            legend = [(p, TK.PHASE_RAMP[p]) for p in DISPLAY_PHASES]
            tags = [t for t, has in (("Phase 4", post), ("follow-up", followup)) if has]
            if tags:
                legend.append((" and ".join(tags) + ", post-development", TK.MUTED))
            R.show(CH.stacked_bar(
                stack_rows, 832, max(170, 34 * len(order) + 22),
                value_fmt=lambda v: f"{v:.0f}", legend=legend))

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
        section("Programmes in development",
                count + (f" · {shown_counts}" if shown_counts else ""))

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
                html.append(f'<div class="prog-h">{html_escape(ph)}'
                            f'<span>{len(group)}</span></div>')
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
                        f'</summary>{"".join(studies)}</details>')
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
                'from.</div>', unsafe_allow_html=True)


    # --- Portfolio -------------------------------------------------------
    if portfolio_tab is not None:
        with portfolio_tab:
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
            section(f"{ticker} portfolio")
            if not approvals:
                state(f"No approvals on file for {ticker}",
                      "openFDA files an approval under the legal entity that holds the "
                      "application, which for an acquired product is the company that was "
                      "bought. Press Refresh all on the Comps tab to pull it again.")
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

                # Revenue mix leads: what the company earns today, by product, before the
                # cliff charts say what is at risk. The mix is the base the rest is read
                # against, so it comes first.
                if mix_drivers:
                    section("Revenue mix", f"FY{mix_year}")
                    ramp = list(reversed(T.ordinal_ramp(max(len(mix_drivers), 2))))
                    slices = [{"label": p["brand_name"] or p["generic_name"] or "unnamed",
                               "value": p["value"], "colour": ramp[i % len(ramp)]}
                              for i, p in enumerate(mix_drivers)]
                    if mix_tail:
                        slices.append({"label": f"{len(mix_tail)} smaller products",
                                       "value": sum(p["value"] for p in mix_tail),
                                       "colour": TK.RULE_STRONG, "muted": True})
                    rest = revenue_mix.residual(mix_rows, mix_reported.get("value"))
                    if rest:
                        slices.append({"label": "not attributed by product",
                                       "value": rest, "colour": TK.PANEL, "muted": True})
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
                    short = {"Immunology and inflammation": "Immunology",
                             "Renal and hepatic": "Renal and hepatic",
                             "Infectious disease": "Infectious",
                             "Healthy volunteers": "Healthy volunteers"}
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
                    if rest:
                        area_slices.append({"label": "not attributed by product",
                                            "value": rest, "colour": TK.PANEL,
                                            "muted": True})

                    # The same total in both centres, because it is the same revenue cut
                    # two ways; the heading over each says which cut it is.
                    total_mix = sum(sl["value"] for sl in slices) / 1e9
                    named = len([a for a in area_order if a != "area not stated"])
                    left, right = st.columns(2, gap="small")
                    with left:
                        st.markdown('<div class="subhead">By product</div>',
                                    unsafe_allow_html=True)
                        R.show(CH.donut(
                            slices, 470, 360, centre_label=T.num(total_mix, 1),
                            centre_sub=f"{mix_ccy or ''} bn FY{mix_year}",
                            value_fmt=lambda v: T.num(v / 1e9, 2)))
                    with right:
                        st.markdown(
                            f'<div class="subhead">By disease area<span>{named} areas'
                            '</span></div>', unsafe_allow_html=True)
                        R.show(CH.donut(
                            area_slices, 470, 360, centre_label=T.num(total_mix, 1),
                            centre_sub=f"{mix_ccy or ''} bn FY{mix_year}",
                            value_fmt=lambda v: T.num(v / 1e9, 2)))

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
                if count_by_year:
                    years = list(range(today.year, today.year + 11))
                    section("Loss of exclusivity by year", "products, next 10 years")
                    bars = [{"label": f"'{y % 100:02d}",
                             "value": count_by_year.get(y, 0),
                             "colour": TK.DOWN, "show_value": count_by_year.get(y, 0) > 0}
                            for y in years]
                    R.show(CH.bar_chart(bars, 900, 190, value_fmt=lambda v: str(int(v))))
                    st.markdown(
                        '<div class="byline">Every marketed product losing US exclusivity '
                        'that year, expiries from the Orange and Purple Books, counted whether '
                        'or not its revenue is tagged. A small molecule is placed at its latest '
                        'patent, a biologic at the later of its listed expiry and the 12-year '
                        'floor. A product with no published expiry cannot be placed and is left '
                        'out, never estimated.</div>',
                        unsafe_allow_html=True)
                if rev_by_year:
                    section("Revenue at risk by year", f"tagged products only, {rev_unit} bn")
                    bars = [{"label": f"'{y % 100:02d}", "value": rev_by_year[y] / 1e9}
                            for y in sorted(rev_by_year)]
                    R.show(CH.bar_chart(bars, 900, 190, value_fmt=lambda v: T.num(v, 1)))
                    st.markdown(
                        '<div class="byline">The subset of the cliff above whose product '
                        'revenue is tagged in the SEC data sets, latest reported held flat. '
                        'Free data tags revenue for only a few products, so this understates '
                        'the money at risk and is a floor, not the total.</div>',
                        unsafe_allow_html=True)

                section("Products", f"{len(prods)}")

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
                    basis = (f'<div class="pf-row"><span class="pf-k"></span>'
                             f'<span class="pf-v none" style="font-size:9px">'
                             f'{html_escape(p.get("loe_basis") or "")}</span></div>'
                             if p.get("loe_basis") else "")
                    return (
                        f'<div class="pf-card {cls}">'
                        f'<div class="pf-head">'
                        f'<span class="pf-brand">{html_escape(p["brand"])}</span>'
                        f'<span class="pf-mod">{html_escape(p.get("modality") or "")}</span></div>'
                        f'<div class="pf-generic">{html_escape(p.get("generic") or "")}</div>'
                        f'<div class="pf-row"><span class="pf-k">approved</span>'
                        f'<span class="pf-v">{(p.get("approved") or "—")[:10]}</span></div>'
                        f'<div class="pf-row"><span class="pf-k">revenue</span>'
                        f'<span class="pf-v{"" if p.get("revenue") is not None else " none"}">'
                        f'{rev_txt}</span></div>'
                        f'<div class="pf-row"><span class="pf-k">{loe_label}</span>'
                        f'<span class="pf-v {"near" if near else ""}">'
                        f'{loe_txt}</span></div>'
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
                if sel is not None:
                    _render_product_profile(api_base, ticker, sel, today)
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
                for area in order:
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
                        st.rerun()

            # --- Medicare demand ---
            # Revenue is what a drug earned; this is how many people took it. CMS Part D and
            # Part B spending, matched to a marketed product by brand, is the real-world US
            # demand the revenue line cannot show.
            med = api_get(api_base, f"/companies/{ticker}/demand").get("drugs") or []
            section("Medicare demand", "US Part D and Part B")
            if not med:
                state(f"No Medicare demand on file for {ticker}",
                      "CMS publishes Part D and Part B spending by drug once a year, matched "
                      "to a marketed product by brand on refresh. It covers US Medicare only, "
                      "so a drug used mostly outside it or by under-65s reads low or absent. "
                      "Press Refresh all if this looks empty.")
            else:
                def _yoy(d):
                    cur, prior = d.get("spending"), d.get("prior_spending")
                    if not cur or not prior:
                        return "—"
                    return f"{(cur / prior - 1) * 100:+.0f}%"
                med_year = max((d["latest_year"] for d in med), default="")
                frame = pd.DataFrame([{
                    "Drug": d["brand"], "Where": d["part_label"],
                    "Beneficiaries": (f"{d['beneficiaries']:,}"
                                      if d.get("beneficiaries") is not None else "—"),
                    "Claims": (f"{d['claims']:,}" if d.get("claims") is not None else "—"),
                    "Spending $m": (T.num(d["spending"] / 1e6, 1)
                                    if d.get("spending") is not None else "—"),
                    "vs prior": _yoy(d), "Year": str(d["latest_year"])}
                    for d in med[:25]])
                st.dataframe(
                    # Direction reads in colour: growth up, decline in oxblood, flat muted.
                    frame.style.map(
                        lambda v: (f"color:{T.P.data};font-weight:600" if v.startswith("+")
                                   else f"color:{T.P.oxblood};font-weight:600"
                                   if v.startswith("-") else f"color:{T.P.stale}"),
                        subset=["vs prior"]),
                    width="stretch", hide_index=True)
                st.markdown(
                    f'<div class="byline"><b>US Medicare only.</b> CMS Part D (retail '
                    f'pharmacy) and Part B (given in a clinic) spending by drug, {med_year} '
                    f'the latest year published, matched to a marketed product by brand. '
                    f'Beneficiaries is distinct people, not prescriptions; a count CMS '
                    f'suppressed for privacy reads as a dash, never zero. This is real-world '
                    f'demand, a different lens from the reported revenue above, and it misses '
                    f'commercial and ex-US volume entirely.</div>', unsafe_allow_html=True)

            section("Product revenue", f"{len(curated)} from the filings")
            if not curated:
                state(f"No product revenue on file for {ticker}",
                      "The SEC data sets carry revenue per product only where the "
                      "filer tags a product axis. AbbVie tags none at all, and GSK and "
                      "Regeneron spread theirs across segments in a way that cannot be "
                      "resolved without adding them together.")
            else:
                for row in curated:
                    st.markdown(
                        f'<div class="fitem"><span class="d">FY{row["fiscal_year"]}'
                        f'</span><span class="t">{html_escape(row["brand_name"])} '
                        f'<span class="mono">{html_escape(row["internal_code"] or "")}'
                        f'</span></span><span class="s">'
                        f'{T.num(row["value"] / 1e9, 2)} {row["unit"] or ""}</span>'
                        f'</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="byline">Worldwide, as the filing tags it, from the SEC '
                    'Financial Statement Data Sets. Nothing here is typed in: a figure '
                    'is what the company reported or it is absent.</div>',
                    unsafe_allow_html=True)

        # --- Catalysts -------------------------------------------------------
    with catalysts_tab:
        # Derived only, and for the selected company alone. Readouts come from Phase 3
        # primary completion dates on every refresh, so the calendar is rebuilt rather
        # than maintained. The add form is gone: a date typed in once goes stale
        # silently and nothing tells you.
        section(f"Catalyst calendar for {ticker}", "derived on refresh")
        # One window, so no control. Two years is the span a readout calendar is read
        # over, and a shorter one hid the far half of what is already known.
        window = CALENDAR_MONTHS
        calendar = api_get(
            api_base,
            f"/catalysts?within_days={window * 31}"
            f"&ticker={urllib.parse.quote(ticker)}")
        if not calendar:
            state(f"Nothing dated for {ticker} in the next {window} months",
                  "Readouts are derived from Phase 3 primary completion dates on every "
                  "refresh, so this fills once trials are fetched. PDUFA dates are read "
                  "out of the 8-K that announces the acceptance, which needs "
                  "ANTHROPIC_API_KEY set; without it that half stays empty.")
        else:
            st.markdown(calendar_view.render(calendar, months=window),
                        unsafe_allow_html=True)
            st.markdown(f'<div class="byline">{calendar_view.caption(calendar, window)}'
                        ' A readout date is an estimate and moves, so a refresh updates '
                        'it in place and withdraws the row if the trial stops. A PDUFA '
                        'date is only written when the date, the product name and a '
                        'verbatim quote all appear in the filing.</div>',
                        unsafe_allow_html=True)

            with st.expander("The rows behind the calendar"):
                st.dataframe(pd.DataFrame([{
                    "Date": c["expected_date"], "Type": c["catalyst_type"],
                    "Precision": c["date_confidence"], "Title": c["title"],
                    "Evidence": c["source_url"] or "—"} for c in calendar]),
                    width="stretch", hide_index=True,
                    column_config={"Evidence": st.column_config.LinkColumn(
                        "Evidence", display_text=r"NCT\w+")})

    # --- Labels ----------------------------------------------------------
    # --- News ------------------------------------------------------------
    with news_tab:
        news = api_get(api_base, f"/companies/{ticker}/news")["news"]
        section(f"News and announcements for {ticker}", len(news))
        if not news:
            state(f"No news on file for {ticker}",
                  "Press Refresh all to pull EDGAR 8-K and 6-K material events and the "
                  "FDA press, drug and safety feeds matched to this company. European "
                  "filers submit 6-K, not 8-K.")
        else:
            _src = {"fda_press": "FDA press", "fda_drugs": "FDA drug",
                    "fda_safety": "FDA safety"}
            st.dataframe(
                pd.DataFrame([{
                    "Published": n["published_at"],
                    "Source": _src.get(n.get("source"), "EDGAR"),
                    "Title": n["title"], "Link": n["url"]} for n in news]),
                width="stretch", hide_index=True,
                column_config={"Link": st.column_config.LinkColumn("Link")})
            st.markdown('<div class="byline">EDGAR 8-K and 6-K material events, plus '
                        'the FDA press, drug and MedWatch feeds matched to this company '
                        'by name or brand. The full FDA feed is on the Universe '
                        'tab.</div>', unsafe_allow_html=True)

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
            mdna = next((s for s in ftext if s["section"] == "mdna"
                         and s.get("ratio") is not None), None)
            note = ("" if not mdna else
                    f" MD&A is rewritten each period, {round((1 - mdna['ratio']) * 100)}% "
                    f"changed in the latest {mdna['form']}, so it is kept but not flagged "
                    f"as an event.")

    # --- Themes: the universe read by modality rather than by ticker ------
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
