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
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

import calendar_view
import revenue_mix
import theme as T
import trend as trend_module
from components import charts as CH
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
PRICE_WINDOWS = [("1M", 31), ("3M", 92), ("6M", 183), ("1Y", 365), ("5Y", None)]
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


def _spine_items(feed_items: list) -> list:
    items = []
    for it in feed_items:
        kind = it.get("kind")
        if kind == "catalyst":
            regulatory = it.get("change_type") in ("PDUFA", "EMA decision", "AdCom")
            colour = TK.FLAG if regulatory else TK.UP
            flagged = regulatory       # machine-read dates carry the review mark
        elif kind == "loe":
            modality = (it.get("modality") or "").lower()
            colour = (TK.ORANGE_BOOK if modality.startswith("small")
                      else TK.PURPLE_BOOK if modality.startswith("bio") else TK.MUTED)
            flagged = False
        else:
            continue                   # changes already happened; the spine is ahead
        items.append({"key": _spine_key(it), "date": it.get("date"),
                      "label": _spine_label(it.get("headline")),
                      "headline": it.get("headline"), "kind": kind,
                      "significance": it.get("significance"),
                      "reason": it.get("reason"), "detail": it.get("detail"),
                      "colour": colour, "flagged": flagged})
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


spine_items = _spine_items(feed)
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

main, rail_col = st.columns([1, 0.27], gap="medium")

with rail_col:
    R.show(CH.timeline_spine(
        spine_items, dt.date.today(), 200, 720,
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
    (universe_tab, insights_tab, prices_tab, financials_tab, pipeline_tab, loe_tab,
     risk_tab, slippage_tab, approvals_tab, labels_tab, catalysts_tab, comps_tab,
     news_tab) = st.tabs(
        ["Universe", "Key insights", "Prices", "Financials", "Pipeline", "LOE",
         "Revenue at risk", "Slippage", "Approvals", "Labels", "Catalysts", "Comps",
         "News"])

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
        flagged = [it for it in universe_feed if it.get("significance") == "high"]
        section("What moved across coverage",
                f"{len(universe_feed)} items, {len(flagged)} high")
        if not universe_feed:
            state("Nothing flagged across the universe",
                  "The feed compares snapshots between refreshes. Press Refresh all "
                  "in the top bar to pull the sources and compute a diff.")
        else:
            ordered = flagged + [it for it in universe_feed
                                 if it.get("significance") != "high"]
            st.markdown('<div class="feed">' + "".join(
                feed_row(it, show_reason=True) for it in ordered[:30])
                + "</div>", unsafe_allow_html=True)

        section("Coverage, 90 days", "shared scale")
        panels = api_get(api_base, "/price-grid?days=90")
        if any(p["closes"] for p in panels):
            R.show(CH.small_multiples(
                [{"label": p["ticker"],
                  "values": p["closes"] or [],
                  "sub": T.pct(p["change"] * 100) if p["change"] is not None else ""}
                 for p in panels], 1040, 420, cols=6))
        else:
            state("No price history yet",
                  "Press Refresh all in the top bar to pull daily closes.")

        section("Next 30 days", "all companies")
        soon_cats = [c for c in api_get(api_base, "/catalysts?within_days=30")
                     if c.get("expected_date")]
        if not soon_cats:
            state("Nothing dated inside 30 days",
                  "Readouts derive from registry completion dates on refresh; PDUFA "
                  "dates are read from 8-Ks when a model key is set.")
        else:
            st.markdown('<div class="feed">' + "".join(
                feed_row({
                    "date": c["expected_date"],
                    "headline": f"{c['ticker']} {c['catalyst_type']}: {c['title'][:90]}",
                    "significance": "high" if not c.get("is_curated")
                                    and c.get("catalyst_type") == "PDUFA" else "medium",
                    "reason": None if c.get("is_curated") else "uncurated, review",
                }, show_reason=True) for c in soon_cats[:20]) + "</div>",
                unsafe_allow_html=True)

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
                1040, 480, flag_note="uncurated PDUFA, review"))
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
        # Phase 4 is work on approved products, so it is not development; Phase 2/3 is,
        # and lands in late phase, which is the rule this strip already applied.
        in_development = sum(count for phase, count in phases.items()
                             if phase not in POST_APPROVAL)
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
        st.markdown(
            '<div class="pos">' + "".join(
                f'<span><span class="k">{k}</span>'
                f'<span class="v {cls}">{v}</span>'
                f'<span class="sub">{sub}</span></span>' for k, v, cls, sub in cells)
            + "</div>", unsafe_allow_html=True)

        # Fifteen minute bars over the last five sessions. A briefing wants the shape of
        # the week, which daily closes cannot show: five points is a zigzag, not a
        # market. Bars are butted together in order, never on a time axis that would
        # draw a flat line through overnight hours that never traded; the session
        # marks say where each trading day begins.
        if bars:
            closes = [b["close"] for b in bars]
            session_starts = [i for i, b in enumerate(bars)
                              if i and b["as_of"][:10] != bars[i - 1]["as_of"][:10]]
            R.show(CH.sparkline(closes, 832, 72, label_last=True,
                                marks=session_starts))

        head, action, sheet = st.columns([4, 1, 1])
        with head:
            section("Morning note")
        with action:
            regenerate = st.button("Generate", key="gen_note", width="stretch")
        with sheet:
            if st.button("Tearsheet", key="gen_sheet", width="stretch"):
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

        # --- Annotations: the analyst's own lines on this company ---------
        all_notes = api_get(api_base, f"/annotations?ticker={ticker}")
        company_notes = [a for a in all_notes if a["entity_type"] == "company"]
        change_notes: dict[str, list] = {}
        for a in all_notes:
            if a["entity_type"] == "change" and a.get("entity_id"):
                change_notes.setdefault(str(a["entity_id"]), []).append(a)
        if company_notes:
            section("Annotations", len(company_notes))
            for a in company_notes:
                st.markdown(
                    f'<div class="anno"><span class="who">{a["created_at"][:10]}'
                    f'</span>{html_escape(a["body"])}</div>',
                    unsafe_allow_html=True)
        anno_cols = st.columns([0.85, 0.15])
        with anno_cols[0]:
            st.text_input("Annotation", key=f"anno_body_{ticker}",
                          label_visibility="collapsed",
                          placeholder=f"your line on {ticker}")
        with anno_cols[1]:
            if st.button("Save note", key=f"anno_save_{ticker}", width="stretch"):
                body = (st.session_state.get(f"anno_body_{ticker}") or "").strip()
                if body:
                    api_post_json(api_base, "/annotations",
                                  {"ticker": ticker, "entity_type": "company",
                                   "entity_id": None, "body": body})
                    api_get.clear()
                    st.rerun()

        if not feed:
            section("Nothing flagged")
            state(f"No changes detected for {ticker}",
                  "The position above is current either way. The feed compares "
                  "snapshots between refreshes, so it needs two runs before the first "
                  "diff appears. Run one from the Prices tab.")

        for kind, label, blurb in FEED_SECTIONS:
            items = [it for it in feed if it["kind"] == kind]
            if not items:
                continue
            section(label, len(items))
            pieces = []
            for it in items:
                pieces.append(feed_row(it, show_reason=True))
                # An annotation renders inline, directly under the item it
                # belongs to, in the analyst's own voice.
                for a in change_notes.get(str(it.get("change_id")), []):
                    pieces.append(
                        f'<div class="anno"><span class="who">'
                        f'{a["created_at"][:10]}</span>'
                        f'{html_escape(a["body"])}</div>')
            st.markdown('<div class="feed">' + "".join(pieces) + "</div>",
                        unsafe_allow_html=True)
            st.markdown(f'<div class="byline">{blurb}</div>', unsafe_allow_html=True)

    # --- Prices ----------------------------------------------------------
    with prices_tab:
        section("Close", prices.get("currency") or "")
        if st.button("Refresh prices", key="refresh_prices"):
            run_refresh(api_base, f"/refresh?ticker={urllib.parse.quote(ticker)}",
                        "price_run", f"Refreshing {ticker} from Yahoo")
            st.rerun()

        points = prices["points"]
        if not points:
            state("No price history yet",
                  "Press Refresh prices to pull five years of daily closes from Yahoo. "
                  "Prices expire after 15 minutes, so a second press inside that window "
                  "is a no-op and says so.")
        else:
            frame = pd.DataFrame(points)
            frame["as_of"] = pd.to_datetime(frame["as_of"])
            held = (frame["as_of"].max() - frame["as_of"].min()).days

            # Only offer windows the stored history can actually fill. A 5Y button on
            # six months of data draws the same chart and quietly lies about the span.
            choices = [(label, days) for label, days in PRICE_WINDOWS
                       if days is None or days <= held + 45]
            labels = [label for label, _ in choices]
            span = st.radio("Window", labels, index=len(labels) - 1, horizontal=True,
                            key="price_window", label_visibility="collapsed")
            days = dict(choices)[span]
            if days is not None:
                cutoff = frame["as_of"].max() - pd.Timedelta(days=days)
                frame = frame[frame["as_of"] >= cutoff]

            opened, latest_close = frame["close"].iloc[0], frame["close"].iloc[-1]
            change = (latest_close - opened) / opened * 100 if opened else None
            low, high = frame["close"].min(), frame["close"].max()
            st.markdown(
                '<div class="stats">'
                f'<span class="stat"><span class="k">last close</span>'
                f'<span class="v">{T.num(latest_close, 2)}</span></span>'
                f'<span class="stat"><span class="k">as of</span>'
                f'<span class="v">{prices["latest"]["as_of"]}</span></span>'
                f'<span class="stat"><span class="k">{span} change</span>'
                f'<span class="v {"risk" if (change or 0) < 0 else ""}">'
                f'{T.pct(change)}</span></span>'
                f'<span class="stat"><span class="k">{span} range</span>'
                f'<span class="v">{T.num(low, 2)} to {T.num(high, 2)}</span></span>'
                f'<span class="stat"><span class="k">sessions</span>'
                f'<span class="v">{len(frame)}</span></span></div>',
                unsafe_allow_html=True)

            currency = prices.get("currency") or ""
            # The window buttons are the coarse control; hover carries the exact
            # close per slot, pure CSS with no server round trip. Display is
            # thinned to keep the SVG light; the newest close always survives.
            closes, labels = _downsample(
                list(frame["close"]),
                [d.strftime("%Y-%m-%d") for d in frame["as_of"]])
            R.show(CH.line_chart(
                [{"name": ticker, "values": closes, "colour": TK.UP}],
                labels, 900, 300, y_fmt=lambda v: T.num(v, 2)))

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
        # Post-approval trials are dropped once, here, so the bars, the chips, and
        # the table underneath all describe the same set. Filtering only the chart
        # would leave a chip claiming a count its bar does not show.
        every = api_get(api_base, f"/companies/{ticker}/trials")["trials"]
        detail = [t for t in every if t["phase"] not in POST_APPROVAL]
        marketed = len(every) - len(detail)
        section(f"{ticker} by therapeutic area", f"{len(detail)} in development")
        if not detail:
            state(f"No trials in development for {ticker}",
                  "Press Refresh all on the Comps tab to pull ClinicalTrials.gov, "
                  "or pick another company in the sidebar."
                  + (f" {marketed} Phase 4 trials are on file but sit outside the "
                     "pipeline." if marketed else ""))
        else:
            areas = pd.DataFrame([{"Area": t["area"],
                                   "Phase": PHASE_MERGE.get(t["phase"], t["phase"]),
                                   "n": 1} for t in detail])
            totals = (areas.groupby("Area", as_index=False)["n"].sum()
                      .sort_values("n", ascending=False))
            order = list(totals["Area"])
            counts = dict(zip(totals["Area"], totals["n"]))
            phase_counts = areas.groupby("Phase")["n"].sum().to_dict()

            # The selection is read before the chart is drawn, so the bars can dim,
            # but the chips are rendered after it: the chart is what tells you which
            # area to pick, so it comes first and the controls sit under it with the
            # phase pills, as one band of filters rather than two split around it.
            chosen = st.session_state.get("area_pills") or []

            # Stacked by phase so the shape of an area reads at a glance: one that is
            # all Phase 1 is a different proposition from one carrying Phase 3, even
            # at the same trial count. The phase ramp brightens toward market, so an
            # area's proximity to approval reads directly. Selecting dims the rest
            # to the hairline colour rather than fading opacity, which kept the
            # segments legible against the ground.
            seg = areas.groupby(["Area", "Phase"], as_index=False)["n"].sum()
            seg_counts = {(row.Area, row.Phase): int(row.n)
                          for row in seg.itertuples()}
            stack_rows = []
            for area in order:
                dimmed = bool(chosen) and area not in chosen
                segments = []
                for ph in DISPLAY_PHASES:
                    count = seg_counts.get((area, ph), 0)
                    if not count:
                        continue
                    segments.append({
                        "name": f"{ph}, {count} trials",
                        "value": count,
                        "colour": TK.RULE if dimmed else TK.PHASE_RAMP[ph]})
                stack_rows.append({"label": area, "segments": segments})
            R.show(CH.stacked_bar(
                stack_rows, 832, max(170, 34 * len(order) + 22),
                value_fmt=lambda v: f"{v:.0f}",
                legend=[(p, TK.PHASE_RAMP[p]) for p in DISPLAY_PHASES]))

            st.pills("Therapeutic area", order, selection_mode="multi",
                     format_func=lambda a: f"{a}  {counts[a]}",
                     key="area_pills", label_visibility="collapsed")

            # The table stays shut until an area and a phase are picked. Two
            # hundred rows of every trial is not a starting point anyone reads; the
            # chart above is, and the table is what you open once it has told you
            # where to look.
            phase_pick = st.pills(
                "Phase", DISPLAY_PHASES, selection_mode="multi",
                format_func=lambda p: f"{p}  {phase_counts.get(p, 0)}",
                key=f"phase_pills_{ticker}", label_visibility="collapsed") or []

            shown = [t for t in detail
                     if t["area"] in chosen and t["phase"] in phase_pick]
            if not chosen or not phase_pick:
                missing = ("an area" if not chosen else "a phase")
                marketed_note = (
                    f" {marketed} Phase 4 trials are excluded throughout: they run "
                    "after approval, so they are lifecycle work rather than "
                    "pipeline." if marketed else "")
                state(f"Pick {missing} to list the trials",
                      "The bars answer how much and where; the table answers which. "
                      "It opens once an area and a phase are both selected, rather "
                      f"than opening on {len(detail)} rows of everything."
                      + marketed_note)
            else:
                section(", ".join(chosen), f"{len(shown)} trials, "
                        + ", ".join(phase_pick))
                table = pd.DataFrame([{
                    "NCT": t["nct_id"], "Phase": t["phase"], "Area": t["area"],
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
                    'overdue means an estimated date has passed without being '
                    'revised.</div>', unsafe_allow_html=True)

    # --- LOE -------------------------------------------------------------
    with loe_tab:
        data = api_get(api_base, "/loe")
        # One company, to match the rest of the tab and the horizon rail. build_loe
        # already returns a per-company row bucketed by year, so the selected ticker's
        # row is the chart; summing every row would be the whole universe instead.
        mine = next((r for r in data["rows"] if r["ticker"] == ticker), None)
        section(f"Exclusivity cliff for {ticker}", "US products per year")
        year_cols = [str(y) for y in data["years"]] + [data["later_label"]]
        counts = {}
        if mine:
            counts = {str(y): mine["years"].get(str(y), 0) for y in data["years"]}
            counts[data["later_label"]] = mine["later"]
        if sum(counts.values()) == 0:
            state(f"No US loss of exclusivity on file for {ticker}",
                  "The Orange Book and Purple Book cover US products only and refresh "
                  "weekly. Press Refresh all on the Comps tab if this looks empty.")
        else:
            R.show(CH.bar_chart(
                [{"label": c, "value": counts[c], "show_value": counts[c] > 0}
                 for c in year_cols],
                832, 220, value_fmt=lambda v: f"{v:.0f}"))

            section(f"Upcoming for {ticker}", len(exclusivities))
            if not exclusivities:
                state(f"No upcoming loss of exclusivity for {ticker}",
                      "Either nothing expires inside the window or the books carry no "
                      "entry for this company. Biologics coverage is partial.")
            else:
                def _challenge(a):
                    if not a.get("challenged"):
                        return "—"
                    when = a.get("challenge_date")
                    return f"Para IV, {when}" if when else "Para IV"
                frame = pd.DataFrame([{
                    "Expiry": a["loe"], "Basis": a.get("loe_basis") or "—",
                    "Challenged": _challenge(a),
                    "Modality": a["modality"] or "—",
                    "Brand": a["brand_name"], "Generic": a["generic_name"],
                    "Application": a["internal_code"]} for a in exclusivities])
                st.dataframe(
                    frame.style.map(
                        lambda v: f"color:{T.P.modality.get(v, T.P.stale)};"
                                  "font-weight:600", subset=["Modality"])
                    # Orphan exclusivity is not a loss of exclusivity, so it is muted
                    # rather than reading with the same weight as a patent expiry.
                    .map(lambda v: f"color:{T.P.stale}"
                         if v == "orphan exclusivity" else "", subset=["Basis"])
                    # A filed Paragraph IV challenge is the one thing here that can pull
                    # the expiry in, so it reads in oxblood rather than muted.
                    .map(lambda v: f"color:{T.P.oxblood};font-weight:600"
                         if v != "—" else f"color:{T.P.stale}", subset=["Challenged"]),
                    width="stretch", hide_index=True)
                st.markdown(
                    '<div class="byline"><b>United States only.</b> The Orange Book and '
                    'the Purple Book are FDA publications, so every date here is a US '
                    'date. A product protected in the US to 2035 can face a generic in '
                    'Europe or Japan years earlier, and no free source publishes those '
                    'dates, so this app does not know them.<br>'
                    '<b>Biologics carry no patent dates.</b> The Purple Book publishes '
                    'regulatory exclusivity and nothing else, so all 109 biologics in '
                    'the universe show an exclusivity date rather than the patent that '
                    'actually gates a biosimilar. Keytruda reads 2031 here on an orphan '
                    'exclusivity while its US patent cliff is earlier. Small molecule '
                    'dates come from Orange Book patents and are sound.<br>'
                    'Basis is what sets the date. Orphan exclusivity covers one orphan '
                    'indication and lapses without the product losing anything, so it is '
                    'muted here and excluded from the cliff above. Orange for small '
                    'molecules, purple for biologics, the colours of the two source '
                    'books.<br>'
                    '<b>Challenged</b> is a Paragraph IV certification on the FDA list, a '
                    'generic filer telling the agency the patent is invalid or not '
                    'infringed. It is filed years before expiry and is the reason the '
                    'expiry date may not hold, so a challenged small molecule is a real '
                    'LOE risk ahead of the date next to it.</div>', unsafe_allow_html=True)

    # --- Revenue at risk -------------------------------------------------
    with risk_tab:
        at_risk = api_get(api_base, f"/companies/{ticker}/revenue-at-risk")
        section(f"Revenue at risk for {ticker}", "US protection, tagged revenue")
        priced_total = at_risk.get("priced_total")
        reported_fy = at_risk.get("company_reported") or {}
        tagged_share = (priced_total / reported_fy["value"]
                        if priced_total and reported_fy.get("value") else None)
        st.markdown(
            '<div class="pos">'
            f'<div><span class="k">tagged product revenue</span>'
            f'<span class="v{"" if priced_total is not None else " none"}">'
            f'{T.num(priced_total / 1e9, 1) if priced_total is not None else "no free data"}'
            f'</span><span class="sub">{at_risk.get("currency") or ""} bn, '
            f'{at_risk.get("priced_products")} products</span></div>'
            f'<div><span class="k">of reported revenue</span>'
            f'<span class="v{"" if tagged_share is not None else " none"}">'
            f'{T.pct(tagged_share * 100) if tagged_share is not None else "—"}'
            f'</span><span class="sub">the filing attributes by product</span></div>'
            f'<div><span class="k">at risk inside 5y</span>'
            f'<span class="v{"" if at_risk.get("share_5y") is not None else " none"}">'
            f'{T.pct(at_risk["share_5y"] * 100) if at_risk.get("share_5y") is not None else "no free data"}'
            f'</span><span class="sub">of tagged revenue, US only</span></div>'
            f'<div><span class="k">unpriced products at risk</span>'
            f'<span class="v">{at_risk.get("products_uncovered") or 0}</span>'
            f'<span class="sub">known expiry, no tagged figure</span></div>'
            "</div>", unsafe_allow_html=True)

        if priced_total:
            # The cliff as a waterfall: tagged revenue down through each year's
            # expiries to what stays protected past the horizon. The unpriced
            # band hatches; its size is unknown by construction.
            steps = [{"label": "tagged", "value": priced_total / 1e9,
                      "kind": "start"}]
            for bucket in at_risk["buckets"]:
                if bucket["covered"]:
                    steps.append({"label": str(bucket["year"]),
                                  "value": -bucket["revenue"] / 1e9,
                                  "kind": "step"})
            if at_risk.get("products_uncovered"):
                steps.append({"label": f"unpriced ×{at_risk['products_uncovered']}",
                              "value": None, "kind": "step"})
            steps.append({"label": "protected", "kind": "end"})
            section("Cliff waterfall", f"{at_risk.get('currency') or ''} bn")
            R.show(CH.waterfall(steps, 832, 280,
                                value_fmt=lambda v: T.num(v, 1)))

            years_with_products = [b for b in at_risk["buckets"]
                                   if b["covered"] or b["uncovered"]]
            if years_with_products:
                section("What expires when")
                year_pick = st.selectbox(
                    "Year", [str(b["year"]) for b in years_with_products],
                    key=f"risk_year_{ticker}", label_visibility="collapsed")
                bucket = next(b for b in years_with_products
                              if str(b["year"]) == year_pick)
                rows = [{"Brand": p["brand_name"], "Generic": p["generic_name"],
                         "Modality": p["modality"], "LOE": p["loe"],
                         "Basis": p["basis"],
                         "Revenue, bn": (T.num(p["revenue"] / 1e9, 2)
                                         if p.get("revenue") is not None else "—")}
                        for p in bucket["covered"] + bucket["uncovered"]]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            state(f"No tagged product revenue for {ticker}",
                  "The SEC data sets carry revenue per product only where the filer "
                  "tags a product axis. The exposure is drawn as counts on the LOE "
                  "tab instead; nothing here is imputed.")

        uni = api_get(api_base, "/revenue-at-risk")
        uni_rows = uni["rows"]
        fx_as_of = uni.get("fx_as_of")
        risk_view = st.radio(
            "Universe view", ["Share of tagged revenue", "Absolute, USD converted"],
            horizontal=True, key="risk_universe_view", label_visibility="collapsed")

        if risk_view.startswith("Share"):
            section("Universe, share of tagged revenue at risk inside 5 years",
                    "shares, comparable across currencies")
            R.show(CH.bar_chart(
                [{"label": r["ticker"],
                  "value": (r["share_5y"] * 100 if r["share_5y"] is not None else None)}
                 for r in uni_rows],
                832, 420, horizontal=True, value_fmt=lambda v: T.pct(v, 1)))
            st.markdown(
                '<div class="byline"><b>United States only.</b> Shares are of each '
                "company's own tagged product revenue, so they compare across "
                'reporting currencies directly. A hatched band is a company whose '
                'filing tags no product revenue.</div>', unsafe_allow_html=True)
        else:
            section("Universe, tagged revenue at risk inside 5 years",
                    f"USD bn, ECB rate {fx_as_of or 'not on file'}")
            # Sorted so the biggest exposure reads first. A company whose currency has
            # no rate lands as a hatched null band, never converted at an invented rate.
            usd_rows = sorted(
                [{"label": r["ticker"],
                  "value": (r["at_risk_5y_usd"] / 1e9
                            if r.get("at_risk_5y_usd") is not None else None)}
                 for r in uni_rows],
                key=lambda d: (d["value"] is None, -(d["value"] or 0)))
            R.show(CH.bar_chart(usd_rows, 832, 420, horizontal=True,
                                value_fmt=lambda v: T.num(v, 2)))
            st.markdown(
                '<div class="byline"><b>United States only.</b> Tagged product revenue '
                'expiring inside five years, converted to USD at the ECB reference rate '
                f'on {fx_as_of or "no date on file"}. Novo reports in DKK and Roche in '
                'CHF; the rate makes them comparable. A hatched band is a company with '
                'no exposure priced, or whose reporting currency has no rate on file, '
                'so it is left unconverted rather than shown as zero.</div>',
                unsafe_allow_html=True)

    # --- Slippage --------------------------------------------------------
    with slippage_tab:
        section("Completion date slippage", "from our own snapshot history")
        slip = api_get(api_base, "/slippage")
        summary = {s["ticker"]: s for s in slip.get("summary") or []}
        mine_slip = summary.get(ticker)
        st.markdown(
            '<div class="pos">'
            f'<div><span class="k">trials moved, universe</span>'
            f'<span class="v">{len(slip.get("rows") or [])}</span>'
            f'<span class="sub">since tracking began</span></div>'
            f'<div><span class="k">{ticker} moved</span>'
            f'<span class="v">{mine_slip["trials_moved"] if mine_slip else 0}</span>'
            f'<span class="sub">'
            f'{("median " + T.num(mine_slip["median_days"], 0) + "d") if mine_slip else "no moves observed"}'
            f'</span></div>'
            "</div>", unsafe_allow_html=True)

        if not slip.get("rows"):
            state("No completion date moves observed yet",
                  "Slippage accumulates from snapshot diffs across refreshes; it "
                  "cannot be backfilled from any source. It fills as the registry "
                  "moves under the trials this terminal tracks.")
        else:
            p3_only = st.checkbox("Phase 3 only", key="slip_p3")
            rows = [r for r in slip["rows"]
                    if r.get("days_moved") is not None
                    and (not p3_only or (r.get("phase") or "").startswith("Phase 3"))]
            shown = rows[:25]
            if shown:
                R.show(CH.dumbbell(
                    [{"label": f"{r['ticker'] or '—'} {r['nct_id']}",
                      "start": 0.0, "end": float(r["days_moved"])}
                     for r in shown],
                    900, max(120, 26 * len(shown) + 40),
                    tick_fmt=lambda v: f"{v:.0f}d"))
                st.markdown(
                    '<div class="byline">Net days moved from the first observed '
                    'primary completion date to the current one. Red slips later, '
                    'green pulls in.</div>', unsafe_allow_html=True)
                st.dataframe(
                    pd.DataFrame([{
                        "Ticker": r["ticker"], "NCT": r["nct_id"],
                        "Phase": r["phase"], "Status": r["overall_status"],
                        "First seen": r["first_date"], "Now": r["current_date"],
                        "Days": r["days_moved"], "Moves": r["observations"],
                        "Trial": CTGOV_STUDY + (r["nct_id"] or "")}
                        for r in shown]),
                    width="stretch", hide_index=True,
                    column_config={"Trial": st.column_config.LinkColumn(
                        "Trial", display_text="Open ↗")})
            else:
                state("Nothing matches the filter",
                      "Clear Phase 3 only to see every moved trial.")

    # --- Approvals -------------------------------------------------------
    with approvals_tab:
        approvals = api_get(api_base, f"/companies/{ticker}/approvals")["approvals"]
        section(f"FDA approvals for {ticker}", len(approvals))
        if not approvals:
            state(f"No approvals on file for {ticker}",
                  "openFDA files an approval under the legal entity that holds the "
                  "application, which for an acquired product is the company that was "
                  "bought. Press Refresh all on the Comps tab to pull it again.")
        if approvals:
            protected = [a for a in approvals if a.get("loe")]
            priced = [a for a in approvals if a.get("revenue") is not None]
            st.markdown(
                f'<div class="pos">'
                f'<div><span class="k">approvals</span>'
                f'<span class="v">{len(approvals)}</span>'
                f'<span class="sub">on file from openFDA</span></div>'
                f'<div><span class="k">with an expiry</span>'
                f'<span class="v{"" if protected else " none"}">'
                f'{len(protected) or "none"}</span>'
                f'<span class="sub">from the Orange and Purple Books</span></div>'
                f'<div><span class="k">with revenue</span>'
                f'<span class="v{"" if priced else " none"}">'
                f'{len(priced) or "none"}</span>'
                f'<span class="sub">from the SEC data sets</span></div>'
                f'</div>', unsafe_allow_html=True)

            frame = pd.DataFrame([{
                "Approved": a["approval_date"], "Modality": a["modality"] or "—",
                "Brand": a["brand_name"], "Generic": a.get("generic_name") or "—",
                "Application": a["application_number"],
                # Protection is per asset, so every approval of one product shows the
                # same expiry. An approval with none is blank rather than zero: the
                # books simply carry no entry, which is not the same as unprotected.
                "Protected to": a.get("loe") or "—",
                "Basis": a.get("loe_basis") or "—",
                "Revenue": (T.num(a["revenue"] / 1e9, 2)
                            if a.get("revenue") is not None else "—"),
                # str, not int: a mixed int and dash column fails Arrow conversion.
                "FY": str(a.get("revenue_year") or "—")}
                for a in approvals])
            st.dataframe(
                frame.style.map(
                    lambda v: f"color:{T.P.modality.get(v, T.P.stale)};font-weight:600",
                    subset=["Modality"])
                .map(lambda v: f"color:{T.P.stale}"
                     if v == "orphan exclusivity" else "", subset=["Basis"]),
                width="stretch", hide_index=True)

            # --- Overriding a revenue figure ---
            # Revenue arrives from the SEC bulk data sets. This is the correction path,
            # and the place a 20-F filer that tags no product axis can be filled in by
            # hand, so it sits behind a disclosure rather than in front of the table.
        revenue_payload = api_get(api_base, f"/companies/{ticker}/revenue")
        curated = revenue_payload["rows"]

        # --- Where the revenue comes from ---
        latest_year = max((r["fiscal_year"] for r in curated), default=None)
        mix_rows = [r for r in curated if r["fiscal_year"] == latest_year]
        mix_currency = next((r["unit"] for r in mix_rows if r.get("unit")), None)
        # The company total is what lets the chart show what it cannot attribute.
        # Without it the donut would total the tagged products and imply Lilly
        # earned 50bn rather than 65bn.
        reported = (revenue_payload.get("company_revenue") or {}).get(
            str(latest_year)) or {}
        drivers, tail = revenue_mix.split(mix_rows)
        if drivers:
            section("Revenue mix", f"FY{latest_year}")
            # Brightest slice first, in the phase-free data ramp; the bracketed
            # tail and the unattributed remainder take the muted surfaces that
            # mean "not itemised" everywhere else.
            ramp = list(reversed(T.ordinal_ramp(max(len(drivers), 2))))
            slices = [{"label": p["brand_name"] or p["generic_name"] or "unnamed",
                       "value": p["value"], "colour": ramp[i % len(ramp)]}
                      for i, p in enumerate(drivers)]
            if tail:
                slices.append({"label": f"{len(tail)} smaller products",
                               "value": sum(p["value"] for p in tail),
                               "colour": TK.RULE_STRONG, "muted": True})
            rest = revenue_mix.residual(mix_rows, reported.get("value"))
            if rest:
                slices.append({"label": "not attributed by product",
                               "value": rest, "colour": TK.PANEL, "muted": True})
            shown_total = sum(s["value"] for s in slices)
            R.show(CH.donut(slices, 832, 320,
                            centre_label=T.num(shown_total / 1e9, 1),
                            centre_sub=f"{mix_currency or ''} bn FY{latest_year}",
                            value_fmt=lambda v: T.num(v / 1e9, 2)))
            st.markdown(
                '<div class="byline">'
                f'{revenue_mix.caption(mix_rows, mix_currency, latest_year, reported.get("value"))}'
                '</div>', unsafe_allow_html=True)

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
    with labels_tab:
        label_data = api_get(api_base, f"/companies/{ticker}/label-changes")
        detected = label_data.get("changes") or []
        current = label_data.get("current") or []
        supplements = label_data.get("supplements") or []
        section(f"Label changes for {ticker}", len(detected))
        if not detected:
            state(f"No label changes detected for {ticker} yet",
                  "A change appears when a product's DailyMed label version increments "
                  "between two refreshes. The tracked labels below are the baseline the "
                  "next revision is measured against; this fills as labels revise.")
        else:
            # A widened population or a new indication is what an analyst reads first,
            # so the detected changes lead, with the rule that flagged each.
            st.markdown('<div class="feed">' + "".join(
                feed_row({
                    "date": (c.get("detected_at") or "")[:10],
                    "headline": c.get("headline"),
                    "significance": c.get("significance"),
                    "reason": {"population_expansion": "population widened",
                               "new_indication": "new indication",
                               "label_change": "label revised"}.get(c["change_type"]),
                }, show_reason=True) for c in detected) + "</div>",
                unsafe_allow_html=True)

        section("Tracked labels", f"{len(current)} products")
        if not current:
            state(f"No labels on file for {ticker}",
                  "Labels are matched to marketed products by name on DailyMed and "
                  "read on refresh. Press Refresh all, or a product may simply carry "
                  "no DailyMed label.")
        else:
            priced = [c for c in current if c.get("indication_count") is not None]
            st.markdown(
                '<div class="pos">'
                f'<div><span class="k">products tracked</span>'
                f'<span class="v">{len(current)}</span>'
                f'<span class="sub">matched on DailyMed</span></div>'
                f'<div><span class="k">population resolved</span>'
                f'<span class="v{"" if priced else " none"}">'
                f'{len(priced) or "none"}</span>'
                f'<span class="sub">indications extracted from the label</span></div>'
                "</div>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Product": c["drug_name"], "SPL version": c["spl_version"],
                "Effective": c.get("effective_time") or "—",
                "Indications": (c["indication_count"]
                                if c.get("indication_count") is not None else None),
                "Age floor": (c["age_floor_years"]
                              if c.get("age_floor_years") is not None else None),
                "Population": c.get("population_text") or "—"}
                for c in current]),
                width="stretch", hide_index=True,
                column_config={
                    "Indications": st.column_config.NumberColumn(format="%d"),
                    "Age floor": st.column_config.NumberColumn(format="%g")})
            st.markdown(
                '<div class="byline">Labels come from DailyMed, the NIH structured '
                'product label service, free and versioned. The population is '
                'extracted from the indications section by the model when a key is '
                'set; a dash is a label the extraction did not resolve, never a zero. '
                'A version increment between refreshes becomes a change above.</div>',
                unsafe_allow_html=True)

        section(f"Approved efficacy supplements for {ticker}", len(supplements))
        if not supplements:
            state(f"No efficacy supplements on file for {ticker}",
                  "An approved efficacy supplement is a label expansion, read from the "
                  "drugsfda submissions. It fills on refresh. drugsfda is US CDER only, "
                  "so a cell or gene therapy carries none here and is tracked through "
                  "the DailyMed labels above and the Purple Book instead.")
        else:
            st.dataframe(pd.DataFrame([{
                "Approved": s.get("approval_date") or "—",
                "Product": s.get("brand_name") or "—",
                "Application": s["application_number"],
                "Supplement": s["submission_number"],
                "Class": s.get("description") or "Efficacy"}
                for s in supplements]),
                width="stretch", hide_index=True)
            st.markdown(
                '<div class="byline">An approved efficacy supplement is a label '
                'expansion by definition, from openFDA drugsfda, and it often arrives '
                'before the DailyMed version bump. <b>US CDER only:</b> cell and gene '
                'therapies are CBER-regulated and absent from drugsfda, so those '
                'modalities are covered by the labels above and the Purple Book, not '
                'here.</div>', unsafe_allow_html=True)

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
