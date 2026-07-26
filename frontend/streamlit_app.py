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
import theme as T
import trend as trend_module
from components import charts as CH
from components import covnav
from components import drawchart
from components import render as R
from components import tokens as TK

# Overridable so run.sh can point a frontend at whichever API port it started.
DEFAULT_API = os.getenv("ER_API_BASE", "http://localhost:8000")
DEFAULT_TICKER = "LLY"
PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]
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
CTGOV_STUDY = "https://clinicaltrials.gov/study/"
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
    # The reason cell is always present so every row has four children and the
    # severity column stays flush right whether or not a rule is named.
    return (f'<div class="fitem"><span class="d">{date}</span>'
            f'<span class="t">{headline}</span><span class="why">{reason}</span>'
            f'<span class="s {sev}">{sev}</span></div>')


def html_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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
    rev = prof["revenue"][-1] if prof.get("revenue") else None
    loe_txt = (f'{loe.get("loe_year")}' if loe.get("loe_year") else "—")
    if loe.get("loe_earliest_year") and loe.get("loe_year") \
            and loe["loe_earliest_year"] != loe["loe_year"] \
            and "molecule" in (prof.get("modality") or "").lower():
        loe_txt = f'{loe["loe_earliest_year"]}–{loe["loe_year"]}'
    stats = (
        '<div class="pos">'
        f'<div><span class="k">latest revenue</span>'
        f'<span class="v{"" if rev else " none"}">'
        f'{T.num(rev["value"] / 1e9, 2) + " " + (rev["unit"] or "") + " bn" if rev else "no free data"}'
        f'</span><span class="sub">{"FY" + str(rev["fiscal_year"]) if rev else "SEC tags few products"}</span></div>'
        f'<div><span class="k">exclusivity</span>'
        f'<span class="v{"" if loe.get("loe_year") else " none"}">{loe_txt}</span>'
        f'<span class="sub">{html_escape(loe.get("basis") or "no expiry on file")}</span></div>'
        f'<div><span class="k">Medicare spend</span>'
        f'<span class="v{"" if dem else " none"}">'
        f'{"$" + T.num(dem["spend"] / 1e9, 2) + " bn" if dem else "no free data"}</span>'
        f'<span class="sub">{("US " + str(dem["year"]) + ", " + T.pct(dem["spend_growth"] * 100) + " YoY") if dem and dem.get("spend_growth") is not None else ("US " + str(dem["year"]) if dem else "not in Part D/B")}</span></div>'
        f'<div><span class="k">first approval</span>'
        f'<span class="v{"" if prof.get("first_approval") else " none"}">'
        f'{(prof.get("first_approval") or "—")[:10]}</span>'
        f'<span class="sub">{html_escape((prof.get("generic") or "").lower())}</span></div>'
        '</div>')
    st.markdown(stats, unsafe_allow_html=True)

    left, right = st.columns([1.3, 1])
    with left:
        html = ['<div class="prof">']
        # Revenue history, when the SEC tags more than the latest year.
        if len(prof.get("revenue") or []) > 1:
            html.append('<div class="prof-sub">revenue, tagged years</div>')
            html.append(_prof_rows(
                [(f'FY{r["fiscal_year"]}', f'{T.num(r["value"] / 1e9, 2)} {r.get("unit") or ""} bn')
                 for r in prof["revenue"]]))
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
    with right:
        notes = prof.get("notes") or {}
        st.markdown('<div class="prof-sub">your view, curated</div>', unsafe_allow_html=True)
        with st.form(f"pf_notes_{aid}"):
            ms = st.text_area("Market size", value=notes.get("market_size") or "",
                              key=f"pf_ms_{aid}", height=70,
                              placeholder="e.g. ~$25bn US by 2030, high-single-digit growth")
            ps = st.text_area("Peak sales", value=notes.get("peak_sales") or "",
                              key=f"pf_ps_{aid}", height=70,
                              placeholder="e.g. ~$8bn peak, 2029, risk-adjusted")
            cp = st.text_area("Competitors", value=notes.get("competitors") or "",
                              key=f"pf_cp_{aid}", height=70,
                              placeholder="competing drugs or programmes")
            th = st.text_area("Thesis", value=notes.get("thesis") or "",
                              key=f"pf_th_{aid}", height=90,
                              placeholder="one paragraph, why it matters")
            if st.form_submit_button("Save", use_container_width=True):
                api_post_json(api_base, f"/companies/{ticker}/product/{aid}/notes",
                              {"market_size": ms, "peak_sales": ps,
                               "competitors": cp, "thesis": th})
                st.rerun()
        saved = f'Saved {notes["updated_at"][:10]}. ' if notes.get("updated_at") else ""
        st.markdown(
            f'<div class="byline">{saved}Market size, peak sales and the competitor set '
            'are in no free source, so these are your own inputs, stored and shown as '
            'yours, never fetched or estimated.</div>', unsafe_allow_html=True)


def _pct_from_start(closes) -> list:
    """A price series as percent change from its first value, so many companies plot on
    one comparable scale: every line starts at zero and its height is the move, not the
    share price. LLY near 1200 and PFE near 25 become comparable."""
    real = [c for c in closes if c is not None]
    base = real[0] if real else None
    if not base:
        return list(closes)
    return [((c / base - 1) * 100) if c is not None else None for c in closes]


_DEAL_BADGE = {"acquisition": "Acquisition", "licensing": "Licence",
               "collaboration": "Collaboration", "divestiture": "Divestiture"}


def deal_card(deal) -> str:
    """One deal: a type badge, a body of counterparty, value and area, and the date."""
    badge = _DEAL_BADGE.get(deal.get("deal_type"), "Deal")
    body = [f'<span class="dp">{html_escape(deal.get("counterparty") or "")}</span>']
    if deal.get("value"):
        body.append(f'<span class="dv">{html_escape(deal["value"])}</span>')
    if deal.get("area"):
        body.append(f'<span class="da">{html_escape(deal["area"])}</span>')
    return (f'<div class="deal dt-{html_escape(deal.get("deal_type") or "")}">'
            f'<span class="db">{badge}</span>'
            f'<span class="dbody">{" &middot; ".join(body)}</span>'
            f'<span class="dd">{(deal.get("event_date") or "")[:10]}</span></div>')


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


def _completion_note(trial) -> str:
    """What a primary completion date means, which depends on its registry type.

    An actual date in the past is the normal state of a long oncology trial: the primary
    endpoint was reached and the study continues for overall survival, which routinely
    runs years and keeps the status at active, not recruiting. An estimated date in the
    past is the opposite, a forecast that was missed and never revised.
    """
    kind = (trial.get("primary_completion_type") or "").lower()
    date = trial.get("primary_completion_date") or ""
    if not date:
        return "—"
    if kind == "actual":
        return "reached"
    if kind == "estimated":
        return "overdue" if date < dt.date.today().isoformat() else "forecast"
    return "—"


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


def snapshot_strip(snapshot: dict) -> str:
    """The latest reported period, as the position strip used on Key insights."""
    currency = snapshot.get("currency") or ""

    def money(value):
        return T.num(value / 1e9, 2) if value is not None else None

    items = [
        ("Revenue", money(snapshot["revenue"]), f"{currency} bn",
         snapshot["revenue_growth"]),
        ("Net income", money(snapshot["net_income"]), f"{currency} bn",
         snapshot["net_income_growth"]),
        ("EPS, diluted", T.num(snapshot["eps_diluted"], 2), "per share", None),
        # Net margin is not a tile. It is the second series in the panel below, where it
        # has the history that makes a level mean something, and a lone 37.4% here would
        # be the same figure said twice.
        ("R&D", T.pct(snapshot["rd_intensity"] * 100
                      if snapshot["rd_intensity"] is not None else None, 1),
         "of sales", None),
    ]
    out = []
    for label, value, sub, growth in items:
        missing = value is None or value == T.num(None)
        tone = ""
        if growth is not None:
            tone = " up" if growth > 0 else " down" if growth < 0 else ""
            sub = f"{T.pct(growth * 100, 1)} year on year"
        out.append(f'<div><span class="k">{label}</span>'
                   f'<span class="v{" none" if missing else tone}">'
                   f'{value if not missing else "no free data"}</span>'
                   f'<span class="sub">{sub}</span></div>')
    return f'<div class="pos">{"".join(out)}</div>'


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

tickers = [c["ticker"] for c in companies]
names = {c["ticker"]: c["name"] for c in companies}

# --- Top bar --------------------------------------------------------------
# Fixed strip: ticker selector, identity, global search, last refresh, refresh.
# The jump runs as the search input's on_change callback, which is the one place
# Streamlit allows another widget's state to be written: a mid-script write left
# the select's displayed label behind its actual state.
if "company_pick" not in st.session_state:
    # ?ticker= reopens the terminal on a specific company; the pick is written
    # back to the URL below, so the address bar is always shareable.
    wanted = (st.query_params.get("ticker") or "").upper()
    st.session_state["company_pick"] = (
        wanted if wanted in tickers
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
    failed = [s["source"] for s in run_sources.values() if s["errors"]]
    state(f"Run {last_run['id']} finished partial",
          f"{', '.join(failed) or 'one or more sources'} did not return. The rest of the "
          "data on this page is from that run and is good. Retry from the tab that owns "
          "the failing source.", error=True)

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
    (universe_tab, insights_tab, prices_tab, financials_tab, pipeline_tab,
     portfolio_tab, catalysts_tab, comps_tab, news_tab) = st.tabs(
        ["Universe", "Key insights", "Prices", "Financials", "Pipeline",
         "Portfolio", "Catalysts", "Comps", "News"])

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
                st.markdown(
                    '<div class="byline">Reconstructed from the append-only snapshot '
                    'table at field grain: trial status, phase and completion date as '
                    'they stood; the financial report in force at the date; and the '
                    'approvals whose first sighting was on or before it. Everything '
                    'else in the app stays live.</div>', unsafe_allow_html=True)
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

        universe_feed = api_get(api_base, "/changes")
        # The universe view leads with FDA approvals, the cleanest cross-coverage signal,
        # drawn on a date axis rather than a jargon-heavy list; the full change feed with
        # filings, trial moves and risk-factor edits lives on each company's Key insights.
        approvals = []
        for it in universe_feed:
            if it.get("change_type") != "new_approval":
                continue
            drug = (it.get("headline") or "").split("FDA approval:", 1)[-1].strip()
            approvals.append({"ticker": it.get("ticker") or "",
                              "label": drug.split(" (")[0].strip(),
                              "date": it.get("date"),
                              "full": f"{drug} — {(it.get('date') or '')[:10]}"})
        section("FDA approvals across coverage", f"{len(approvals)} on the tape")
        if not approvals:
            state("No approvals flagged across the universe",
                  "New approvals are read from openFDA on refresh. Press Refresh all in "
                  "the top bar to pull the sources.")
        else:
            R.show(CH.approvals_timeline(approvals, 1360, 152, dt.date.today()))
            st.markdown(
                '<div class="byline">Each dot is an FDA approval among covered companies '
                'at its date; hover for the drug and application number. The detailed '
                'change feed, filings, trial moves and risk-factor edits, sits on each '
                "company's Key insights tab.</div>", unsafe_allow_html=True)

        section("Coverage, 90 days", "indexed to the start, one scale")
        panels = api_get(api_base, "/price-grid?days=90")
        if any(p["closes"] for p in panels):
            covnav.coverage_nav(
                CH.small_multiples(
                    [{"label": p["ticker"],
                      "values": _pct_from_start(p["closes"] or []),
                      "sub": T.pct(p["change"] * 100) if p["change"] is not None else ""}
                     for p in panels], 1360, 430, cols=6, link_base="?ticker="),
                muted=TK.MUTED, key="cov_nav")
            st.markdown('<div class="byline">Click a panel to jump straight to that '
                        'company\'s Key insights.</div>', unsafe_allow_html=True)
        else:
            state("No price history yet",
                  "Press Refresh all in the top bar to pull daily closes.")

        soon_cats = [c for c in api_get(api_base, "/catalysts?within_days=30")
                     if c.get("expected_date")]
        # Group by company, keeping the soonest-first order the API returns; a company's
        # first appearance is its nearest catalyst, so the boxes read most-imminent first.
        cat_by_company: dict = {}
        for c in soon_cats:
            cat_by_company.setdefault(c["ticker"], []).append(c)
        section("Next 30 days",
                f"{len(cat_by_company)} companies with a readout" if cat_by_company
                else "all companies")
        if not cat_by_company:
            state("Nothing dated inside 30 days",
                  "Readouts derive from registry completion dates on refresh; PDUFA "
                  "dates are read from 8-Ks when a model key is set.")
        else:
            _CAT_PER_BOX = 5
            boxes = []
            for ticker, cats in cat_by_company.items():
                items = []
                for c in cats[:_CAT_PER_BOX]:
                    phase, study = _cat_phase_study(c.get("title") or "")
                    study = study if len(study) <= 60 else study[:59].rstrip() + "…"
                    ph = (f'<span class="cat-ph">{html_escape(phase)} </span>'
                          if phase else "")
                    review = ("" if c.get("is_curated")
                              else '<span class="rv">review</span>')
                    items.append(
                        f'<div class="cat-item">'
                        f'<span class="cat-d">{html_escape(_cat_short_date(c["expected_date"]))}</span>'
                        f'<span class="cat-t">{ph}{html_escape(study)}{review}</span>'
                        f'</div>')
                extra = len(cats) - _CAT_PER_BOX
                more = (f'<div class="cat-more">+{extra} more</div>'
                        if extra > 0 else "")
                boxes.append(
                    f'<div class="cat-box"><div class="cat-box-head">'
                    f'<span class="cat-tk">{html_escape(ticker)}</span>'
                    f'<span class="cat-n">{len(cats)} in 30d</span></div>'
                    f'{"".join(items)}{more}</div>')
            st.markdown('<div class="cat-grid">' + "".join(boxes) + "</div>",
                        unsafe_allow_html=True)
            st.markdown(
                '<div class="byline">One box per company with a trial readout inside 30 '
                'days, soonest company first, dated by the registry primary completion '
                'date. Every one is derived, not curated, so each is a candidate to review '
                'rather than a confirmed event, and registry dates slip. No free PDUFA '
                'calendar exists, so regulatory decision dates are not here unless hand '
                'entered.</div>', unsafe_allow_html=True)

        section("FDA announcements", "press, drugs, safety")
        reg_news = api_get(api_base, "/regulatory-news").get("news") or []
        if not reg_news:
            state("No FDA announcements on file",
                  "The FDA press, drug and MedWatch feeds are read on refresh and "
                  "matched to a company by name or brand. Press Refresh all.")
        else:
            # A company-matched item is the signal; a general FDA notice is context.
            # Show the matched ones first, then fill with the most recent unmatched, so
            # a bound approval never falls below the fold behind agency housekeeping.
            matched = [n for n in reg_news if n.get("ticker")]
            unmatched = [n for n in reg_news if not n.get("ticker")]
            shown = matched + unmatched[: max(0, 18 - len(matched))]
            st.markdown('<div class="feed">' + "".join(
                f'<div class="fitem"><span class="d">{(n.get("published_at") or "")[:10]}'
                f'</span><span class="t">'
                f'{("<b>" + n["ticker"] + "</b> ") if n.get("ticker") else ""}'
                f'{html_escape(n["title"])}</span>'
                f'<span class="why"></span>'
                f'<span class="s">{html_escape((n.get("source") or "").replace("fda_", ""))}'
                f'</span></div>' for n in shown) + "</div>",
                unsafe_allow_html=True)
            st.markdown(
                '<div class="byline">FDA press, drug and MedWatch safety feeds, the '
                'announcement layer around approvals and label changes. A bold ticker '
                'is a matched company; it reaches CBER products too, so a gene-therapy '
                'approval shows here even when drugsfda does not carry it. EMA retired '
                'its news feed, so the EU indication-extension signal comes from the '
                'EPAR data instead.</div>', unsafe_allow_html=True)

        section("FDA advisory committee calendar", "panel votes ahead")
        adcomm = api_get(api_base, "/adcomm-calendar").get("meetings") or []
        if not adcomm:
            state("No advisory committee meetings on file",
                  "The FDA files each meeting in the Federal Register; the calendar is "
                  "read on refresh and matched to a company by application number or "
                  "sponsor. Press Refresh all.")
        else:
            st.markdown('<div class="feed">' + "".join(
                f'<div class="fitem"><span class="d">{(m.get("meeting_date") or "")[:10]}'
                f'</span><span class="t">'
                f'{("<b>" + m["ticker"] + "</b> ") if m.get("ticker") else ""}'
                f'{html_escape(m.get("product") or m.get("committee") or "")}</span>'
                f'<span class="why">{html_escape((m.get("committee") or "").replace(" Advisory Committee", ""))}</span>'
                f'<span class="s">{html_escape(m.get("application_label") or "")}</span>'
                f'</div>' for m in adcomm[:12]) + "</div>",
                unsafe_allow_html=True)
            st.markdown(
                '<div class="byline">FDA advisory committee meetings from the Federal '
                'Register, the panel vote that leads a decision by weeks. A bold ticker '
                'is a matched company, and that meeting is also in the catalyst '
                'calendar; the rest are agency context, kept rather than dropped. No '
                'free PDUFA calendar exists, so this is the one firm regulatory date '
                'the universe gets without hand entry.</div>', unsafe_allow_html=True)

        section("Catalyst grid, 18 months", "count per company month")
        grid_data = api_get(api_base, "/catalyst-grid")
        cells = {}
        for tk, months in (grid_data.get("cells") or {}).items():
            for month, cell in months.items():
                cells[(tk, month[2:])] = {
                    "count": cell["count"], "weight": cell["weight"],
                    "flagged": cell.get("uncurated_pdufa")}
        if cells:
            R.show(CH.heatmap_grid(
                grid_data["tickers"], [m[2:] for m in grid_data["months"]], cells,
                1360, 480, flag_note="uncurated PDUFA, review"))
            # An SVG cell cannot round-trip a click without scripts, so the drill
            # is two quiet selects that answer the same question.
            drill = st.columns([0.2, 0.25, 0.55])
            with drill[0]:
                drill_ticker = st.selectbox("Company", grid_data["tickers"],
                                            key="grid_drill_ticker")
            with drill[1]:
                drill_month = st.selectbox("Month", grid_data["months"],
                                           key="grid_drill_month")
            month_cats = [c for c in api_get(api_base,
                          f"/catalysts?within_days=600&ticker={drill_ticker}")
                          if (c.get("expected_date") or "")[:7] == drill_month]
            with drill[2]:
                if not month_cats:
                    st.markdown('<div class="byline">Nothing in that cell.</div>',
                                unsafe_allow_html=True)
            for c in month_cats:
                line = st.columns([0.8, 0.2])
                with line[0]:
                    tag = "" if c.get("is_curated") else " · uncurated"
                    st.markdown(
                        f'<div class="fitem"><span class="d">{c["expected_date"]}'
                        f'</span><span class="t">{html_escape(c["catalyst_type"])}: '
                        f'{html_escape((c.get("title") or "")[:90])}{tag}</span>'
                        f'<span class="why"></span><span class="s">'
                        f'{"curated" if c.get("is_curated") else "derived"}</span></div>',
                        unsafe_allow_html=True)
                with line[1]:
                    if not c.get("is_curated"):
                        if st.button("Accept", key=f"accept_{c['id']}",
                                     width="stretch"):
                            api_post(api_base, f"/catalysts/{c['id']}/accept")
                            api_get.clear()
                            st.rerun()
        else:
            state("No pending catalysts on file",
                  "The grid fills from derived readouts and extracted PDUFA dates "
                  "after a refresh.")

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
            st.markdown('<div class="byline">Phase 3 readouts derived from registry '
                        'completion dates, plus curated PDUFA and regulatory dates. An '
                        'estimated date moves; a refresh updates it.</div>',
                        unsafe_allow_html=True)

        if deals_data:
            section("Deals", len(deals_data))
            st.markdown('<div class="deals">' + "".join(
                deal_card(d) for d in deals_data) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="byline">M&amp;A, licensing and collaborations read '
                        'from the filings that announced them. Value where the filing '
                        'stated it; dated to when the market first saw it.</div>',
                        unsafe_allow_html=True)

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
            st.markdown('<div class="byline">Latest protection per marketed product, next '
                        '24 months. Orphan exclusivity is not a cliff.</div>',
                        unsafe_allow_html=True)

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
            theme = {"ground": TK.GROUND, "muted": TK.MUTED, "rule": TK.RULE,
                     "rule_strong": TK.RULE_STRONG, "up": TK.UP, "down": TK.DOWN,
                     "flag": TK.FLAG}

            saved = api_get(api_base, f"/annotations?ticker={urllib.parse.quote(ticker)}"
                                      "&entity_type=price_line")
            stored_id = saved[0]["id"] if saved else None
            try:
                stored_lines = json.loads(saved[0]["body"]) if saved else []
            except (ValueError, TypeError):
                stored_lines = []

            draw_row = st.columns([1.4, 1.6, 1.2, 2.8])
            with draw_row[0]:
                show_events = st.toggle("Events", value=True, key=f"events_{ticker}")
            with draw_row[1]:
                draw_mode = st.toggle("Draw trendlines", key=f"drawtoggle_{ticker}")
            with draw_row[2]:
                if stored_lines and st.button("Clear lines", key=f"clearlines_{ticker}"):
                    if stored_id is not None:
                        api_delete(api_base, f"/annotations/{stored_id}")
                    st.rerun()

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

        section("Latest reported", snapshot["label"] if snapshot else None)
        if snapshot:
            st.markdown(snapshot_strip(snapshot), unsafe_allow_html=True)
            st.markdown(
                f'<div class="byline">Period ending {snapshot["period_end"]}. '
                'Growth compares the same period a year earlier, never the period '
                'before it.</div>', unsafe_allow_html=True)

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
            metric_label = st.radio(
                "Metric", ["Revenue growth", "Net margin"], horizontal=True,
                key="comps_metric", label_visibility="collapsed")
            metric_key = ("revenue_growth" if metric_label == "Revenue growth"
                          else "net_margin")
            default_sel = [t for t in (ticker, "LLY", "NVO", "MRK", "PFE")
                           if t in ct_by][:5]
            picked = st.multiselect(
                "Companies", sorted(ct_by), default=default_sel,
                key="comps_pick", label_visibility="collapsed")
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
            "Revenue, bn": row["Revenue"],
            "Growth, %": row["Growth"],
            "Margin, %": row["Net margin"],
            "R&D, %": row["R&D"],
            "Late trials": _sc(row["Ticker"], "late_trials"),
            "Rev/late trial, bn": _sc(row["Ticker"], "revenue_per_late_trial", 1e-9),
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
            '<div class="byline">Derived columns: late trials are lead-sponsored '
            'Phase 3 and Phase 2/3; revenue per late trial divides the reported year '
            'by that count; LOE 5y is the share of tagged product revenue whose US '
            'protection expires inside five years, with the unpriced product count '
            'beside it. A dash is a missing input, never zero.</div>',
            unsafe_allow_html=True)

        # A matrix of every company against every phase, so it belongs with the
        # other cross-sectional views rather than in a tab that is otherwise one
        # company at a time.
        section("Trials in development by phase", "lead sponsored")
        rows = api_get(api_base, "/pipeline")
        # No total column: it counts every phase, and carrying an all-phases figure
        # beside development-only columns is the disagreement this view just lost.
        grid = pd.DataFrame([{"Ticker": r["ticker"], **r["phases"]} for r in rows])
        if grid[DISPLAY_PHASES].to_numpy().sum() == 0:
            state("No trials on file",
                  "Press Refresh all on the Comps tab to pull active lead-sponsored "
                  "interventional trials from ClinicalTrials.gov.")
        else:
            charted = [p for p in PIPELINE_PHASES if p not in POST_APPROVAL]
            long = grid.melt(id_vars="Ticker", value_vars=charted,
                             var_name="Phase", value_name="Trials")
            long["Phase"] = long["Phase"].replace(PHASE_MERGE)
            long = long.groupby(["Ticker", "Phase"], as_index=False)["Trials"].sum()
            # The count is printed in the cell, so colour is a second reading of the
            # same number, never the only one. Sqrt weight: one company runs three
            # figures of trials and a linear ramp collapses everyone else.
            peak = max(int(long["Trials"].max()), 1)
            cells = {(row.Ticker, row.Phase): {
                        "count": int(row.Trials),
                        "weight": (row.Trials / peak) ** 0.5}
                     for row in long.itertuples() if row.Trials}
            R.show(CH.heatmap_grid(list(grid["Ticker"]), DISPLAY_PHASES, cells,
                                   860, 460))

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

        dev = [t for t in every if _bucket(t) in DISPLAY_PHASES]
        post = [t for t in every if _bucket(t) == "Phase 4"]
        followup = [t for t in every if _bucket(t) == "Follow-up"]
        head = f"{len(dev)} in development"
        if post:
            head += f" · {len(post)} post-approval"
        if followup:
            head += f" · {len(followup)} follow-up"
        section(f"{ticker} by therapeutic area", head)
        if not every:
            state(f"No trials on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull ClinicalTrials.gov, "
                  "or pick another company in the sidebar.")
        else:
            all_area = Counter(t["area"] for t in every)
            dev_area = Counter(t["area"] for t in dev)
            # Bars keep development order and shape; an area with only lifecycle work
            # falls to the end, so an approved product with no active development is
            # still on the chart and selectable.
            order = [a for a, _ in dev_area.most_common()]
            order += [a for a in all_area if a not in dev_area]
            counts = dict(all_area)
            bucket_area = Counter((t["area"], _bucket(t)) for t in every)

            # The selection is read before the chart is drawn, so the bars can dim,
            # but the chips are rendered after it: the chart is what tells you which
            # area to pick, so it comes first and the controls sit under it with the
            # phase pills, as one band of filters rather than two split around it.
            chosen = st.session_state.get("area_pills") or []

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
                        "name": f"{ph}, {count} trials",
                        "value": count,
                        "colour": TK.RULE if dimmed else TK.PHASE_RAMP[ph]})
                for life, tag in LIFECYCLE.items():
                    count = bucket_area.get((area, life), 0)
                    if not count:
                        continue
                    segments.append({
                        "name": f"{life}, {count} trials, {tag}",
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
            st.pills("Therapeutic area", order, selection_mode="multi",
                     key="area_pills", label_visibility="collapsed")
            if chosen:
                st.markdown(
                    '<div class="byline">'
                    + "  ·  ".join(f"{html_escape(str(a))} {counts.get(a, 0)}"
                                   for a in chosen)
                    + "</div>", unsafe_allow_html=True)

            # The table is what you open once the chart has told you where to look. Phase 4
            # and Follow-up join the pills only when the company has any. Labels stay plain
            # for the same reason as the areas; the count for what is picked shows beneath.
            bucket_counts = Counter(_bucket(t) for t in every)
            phase_options = list(DISPLAY_PHASES)
            if post:
                phase_options.append("Phase 4")
            if followup:
                phase_options.append("Follow-up")
            phase_pick = st.pills(
                "Phase", phase_options, selection_mode="multi",
                key=f"phase_pills_{ticker}", label_visibility="collapsed") or []
            if phase_pick:
                st.markdown(
                    '<div class="byline">'
                    + "  ·  ".join(f"{p} {bucket_counts.get(p, 0)}" for p in phase_pick)
                    + "</div>", unsafe_allow_html=True)

            # The table opens on either filter: an area alone lists every phase in it, a
            # phase alone lists that phase across all diseases, and together they
            # intersect. It stays shut only while nothing is picked, so it never opens on
            # the whole list at once.
            if not chosen and not phase_pick:
                state("Pick an area or a phase to list the trials",
                      "The bars answer how much and where; the table answers which. "
                      "Pick a disease, a phase, or both, rather than opening on "
                      f"{len(every)} rows of everything.")
            else:
                shown = [t for t in every
                         if (not chosen or t["area"] in chosen)
                         and (not phase_pick or _bucket(t) in phase_pick)]
                title = ", ".join(chosen) if chosen else "All diseases"
                sub = ", ".join(phase_pick) if phase_pick else "all phases"
                section(title, f"{len(shown)} trials, {sub}")
                # A follow-up study keeps its registry phase but is labelled as one, so a
                # Phase 3 long-term follow-up no longer reads as a Phase 3 development trial.
                table = pd.DataFrame([{
                    "NCT": t["nct_id"],
                    "Phase": (f"{t['phase']} follow-up" if _bucket(t) == "Follow-up"
                              else t["phase"]),
                    "Area": t["area"],
                    "Status": t["overall_status"],
                    "Primary completion": t["primary_completion_date"],
                    # A date that has passed means opposite things depending on
                    # this. Actual: the endpoint was reached and the trial runs on
                    # for survival follow-up, sometimes for a decade. Estimated and
                    # past: the forecast was missed and nobody updated the record.
                    "Date": _completion_note(t),
                    "Conditions": ", ".join(t["conditions"][:3]),
                    # The registry title is the description, and it runs long, so the
                    # grid crops it. A click on the row prints it in full below.
                    "Description": t["title"],
                    "Trial": CTGOV_STUDY + (t["nct_id"] or "")}
                    for t in shown])
                # A key tied to the selection resets it when the filter changes, so a
                # stale row index never points into a different trial list.
                grid_key = f"pipe_{ticker}_{'-'.join(chosen)}_{'-'.join(phase_pick)}"
                event = st.dataframe(
                    table, width="stretch", hide_index=True,
                    on_select="rerun", selection_mode="single-row", key=grid_key,
                    column_config={
                        "Description": st.column_config.TextColumn(
                            "Description", width="large"),
                        "Trial": st.column_config.LinkColumn(
                            "Trial", display_text="Open ↗"),
                    })
                picked = event.selection.rows
                if picked and picked[0] < len(shown):
                    chosen_trial = shown[picked[0]]
                    st.markdown(
                        f'<div class="trial-detail">'
                        f'<span class="nct">{html.escape(chosen_trial["nct_id"] or "")}'
                        f'</span>{html.escape(chosen_trial["title"] or "")}</div>',
                        unsafe_allow_html=True)
                st.markdown(
                    '<div class="byline">Click a row to read the full description; the '
                    'Trial column opens the study on ClinicalTrials.gov. Areas are '
                    'matched from the registry condition text by keyword, so the rule '
                    'that placed a trial is readable rather than guessed. Reached means '
                    'the primary endpoint was met and the study continues for follow-up; '
                    'overdue means an estimated date has passed without being revised. '
                    'Phase 4 and long-term follow-up, extension and rollover studies are '
                    'lifecycle work, tagged apart from the development pipeline and left '
                    'out of the in-development count. Follow-up studies are recognised '
                    'from the registry title, so a few may be missed or over-caught.</div>',
                    unsafe_allow_html=True)

        # --- Completion-date slips for this company, folded from the old Slippage tab ---
        # Only this company's trials whose primary completion date has moved since we began
        # tracking. Scarce by nature: it accrues from snapshot diffs and cannot be
        # backfilled from any source.
        slip = api_get(api_base, "/slippage")
        mine_slips = [r for r in (slip.get("rows") or [])
                      if r.get("ticker") == ticker and r.get("days_moved") is not None]
        section("Completion date slips", f"{len(mine_slips)} for {ticker}")
        if not mine_slips:
            state(f"No completion date moves observed for {ticker} yet",
                  "This accrues from snapshot diffs across refreshes and cannot be "
                  "backfilled; it fills as the registry moves dates under the trials "
                  "tracked here.")
        else:
            top = mine_slips[:20]
            R.show(CH.dumbbell(
                [{"label": r["nct_id"], "start": 0.0, "end": float(r["days_moved"])}
                 for r in top],
                832, max(120, 26 * len(top) + 40), tick_fmt=lambda v: f"{v:.0f}d"))
            st.markdown(
                '<div class="byline">Net days the primary completion date moved from the '
                'first time we saw it to now. Red slips later, green pulls in. Only trials '
                'whose date actually changed appear.</div>', unsafe_allow_html=True)

    # --- Portfolio -------------------------------------------------------
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
                        brand=a.get("brand_name") or a.get("generic_name") or "unnamed",
                        generic=a.get("generic_name"), modality=a.get("modality"),
                        approved=a.get("approval_date"), loe=a.get("loe"),
                        loe_basis=a.get("loe_basis"),
                        loe_earliest_year=(int(a["loe_earliest"][:4])
                                           if a.get("loe_earliest") else None),
                        revenue=a.get("revenue"),
                        revenue_unit=a.get("revenue_unit"))
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
                    revenue=None, revenue_unit=None)
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

            # Revenue mix, above the product cards: what the company earns, by product.
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
                R.show(CH.donut(
                    slices, 832, 320,
                    centre_label=T.num(sum(s["value"] for s in slices) / 1e9, 1),
                    centre_sub=f"{mix_ccy or ''} bn FY{mix_year}",
                    value_fmt=lambda v: T.num(v / 1e9, 2)))
                st.markdown(
                    '<div class="byline">'
                    f'{revenue_mix.caption(mix_rows, mix_ccy, mix_year, mix_reported.get("value"))}'
                    '</div>', unsafe_allow_html=True)

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
            # A click sets the selected asset in session state; a native rerun keeps the
            # Portfolio tab active (a link reload would bounce back to the first tab), so
            # the profile opens in place. Guarded to this company's products, so switching
            # ticker drops a stale selection rather than 404-ing.
            sel_aid = st.session_state.get("profile_asset")
            sel = next((p for p in prods_sorted if p.get("asset_id") == sel_aid), None)
            if sel is not None:
                _render_product_profile(api_base, ticker, sel, today)

            COLS = 4
            for start in range(0, len(prods_sorted), COLS):
                cols = st.columns(COLS)
                for col, p in zip(cols, prods_sorted[start:start + COLS]):
                    with col:
                        st.markdown(_product_card_html(p), unsafe_allow_html=True)
                        aid = p.get("asset_id")
                        if aid is not None and st.button(
                                "view profile", key=f"pf_open_{aid}",
                                use_container_width=True):
                            st.session_state["profile_asset"] = aid
                            st.rerun()
            st.markdown(
                '<div class="byline">One card per product, biggest revenue first. Click '
                'view profile for the full fact sheet. Approval from openFDA drugsfda '
                '(CDER), exclusivity from the Orange Book (small molecule) or Purple Book '
                '(biologic), revenue from the SEC data sets where the filer tags it. A '
                'small molecule shows a range from its earliest to its latest listed '
                'patent, since a generic can challenge the earlier ones, so the cliff is a '
                'window not one date. A biologic shows the later of its listed expiry and '
                'the 12-year statutory floor. A cell or gene therapy is CBER-regulated and '
                'absent from drugsfda, so it shows from the Purple Book with a dash for the '
                'approval date. An exclusivity date within three years reads red.</div>',
                unsafe_allow_html=True)

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
            st.markdown(
                '<div class="byline">Risk factors are prose that turns over slowly, so '
                'what is added or removed against the last filing of the same form is the '
                'signal, and the added passages read in full above. The diff is '
                'structural, sentence by sentence, with no model in the loop.' + note
                + '</div>', unsafe_allow_html=True)
