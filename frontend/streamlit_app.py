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
import json
import urllib.error
import urllib.parse
import urllib.request

import altair as alt
import pandas as pd
import streamlit as st

import calendar_view
import rail as rail_module
import revenue_mix
import theme as T
import trend as trend_module

DEFAULT_API = "http://localhost:8000"
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


def chart(spec, height: int = 250):
    """Every chart goes through here, so the five views stay siblings.

    Axis, padding, and tooltip treatment all come from the registered theme.

    Known limitation: Streamlit sizes the chart from its container at render time, and
    for a chart built inside a hidden tab that container measures a few pixels. The
    width is then fixed, so every chart outside the opening tab draws about 160px wide
    and its axis labels crowd. Setting width in the spec does not help because
    Streamlit overrides it, and neither use_container_width nor autosize.resize
    re-measures on reveal. The fix is to stop building charts inside hidden tabs.
    """
    st.altair_chart(spec.properties(height=height, width="container"))


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


def feed_row(item) -> str:
    """One feed line as type, not as a table row.

    Two or three items in a grid widget is all chrome and no content, so the feed is a
    date, a headline, and a severity, aligned on a grid.
    """
    date = (item.get("date") or "")[:10]
    sev = item.get("significance") or "low"
    modality = (item.get("modality") or "").lower()
    css = "small" if modality.startswith("small") else "bio" if modality.startswith("bio") else ""
    headline = html_escape(item.get("headline") or "")
    if css:
        headline = f'<span class="m {css}">{headline}</span>'
    return (f'<div class="fitem"><span class="d">{date}</span>'
            f'<span class="t">{headline}</span>'
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
default_index = tickers.index(DEFAULT_TICKER) if DEFAULT_TICKER in tickers else 0

pick_col, ident_col = st.columns([0.085, 0.915], gap="small")
with pick_col:
    st.markdown('<div class="pick">', unsafe_allow_html=True)
    ticker = st.selectbox("Company", tickers, index=default_index,
                          label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
company = next((c for c in companies if c["ticker"] == ticker), {})

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
with ident_col:
    st.markdown(
        f'<div class="ident"><span class="nm">{names.get(ticker, ticker)}</span>'
        f'<span class="meta">{meta}</span></div>', unsafe_allow_html=True)

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

main, rail_col = st.columns([1, 0.27], gap="medium")

with rail_col:
    st.markdown('<div class="sec"><span class="sec-label">Horizon</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="rail">{rail_module.render(feed, exclusivities)}</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="byline">Forward-dated items only. Ticks take the '
                'modality colour: orange for small molecules, purple for biologics.'
                '</div>', unsafe_allow_html=True)

with main:
    (insights_tab, prices_tab, financials_tab, pipeline_tab, loe_tab,
     approvals_tab, catalysts_tab, comps_tab, news_tab) = st.tabs(
        ["Key insights", "Prices", "Financials", "Pipeline", "LOE",
         "Approvals", "Catalysts", "Comps", "News"])

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
        # market. The Prices tab keeps the five year daily view.
        if bars:
            spark = pd.DataFrame(bars)
            spark["as_of"] = pd.to_datetime(spark["as_of"])
            # A continuous time axis would draw a flat line across every overnight gap,
            # inventing prices that never traded. Ordering by bar keeps the sessions
            # butted together, and the tooltip carries the real timestamp.
            spark = spark.reset_index().rename(columns={"index": "bar"})
            spark["session"] = spark["as_of"].dt.strftime("%Y-%m-%d")
            base = alt.Chart(spark).encode(
                x=alt.X("bar:Q", title=None, axis=None),
                y=alt.Y("close:Q", title=None, axis=None,
                        scale=alt.Scale(zero=False, nice=False, padding=6)),
                tooltip=[alt.Tooltip("as_of:T", title="", format="%a %d %b %H:%M"),
                         alt.Tooltip("close:Q", title="Close", format=",.2f")])
            chart(base.mark_line(strokeWidth=1.3, interpolate="monotone")
                  # A rule per session start shows where each trading day begins.
                  + alt.Chart(spark[spark["session"] != spark["session"].shift()])
                  .mark_rule(color=T.P.rule_strong, strokeDash=[2, 3])
                  .encode(x=alt.X("bar:Q", axis=None)), 72)
            move = ((bars[-1]["close"] - bars[0]["close"]) / bars[0]["close"] * 100
                    if bars[0]["close"] else None)
            st.markdown(
                f'<div class="byline">{len(bars)} fifteen minute bars over '
                f'{len(intraday.get("sessions") or [])} sessions, '
                f'{bars[0]["as_of"]} to {bars[-1]["as_of"]}: {T.pct(move)}. Dashed '
                'rules mark each session open; overnight gaps are closed up rather '
                'than drawn as a flat line through hours that never traded.</div>',
                unsafe_allow_html=True)

        head, action = st.columns([5, 1])
        with head:
            section("Morning note")
        with action:
            regenerate = st.button("Generate", key="gen_note", width="stretch")

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
            st.markdown('<div class="feed">' + "".join(feed_row(it) for it in items)
                        + "</div>", unsafe_allow_html=True)
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
            hover = alt.selection_point(fields=["as_of"], nearest=True, on="pointerover",
                                        empty=False, clear="pointerout")
            base = alt.Chart(frame).encode(alt.X("as_of:T", title=None))
            line = base.mark_line().encode(
                alt.Y("close:Q", title=f"Close, {currency}",
                      scale=alt.Scale(zero=False, nice=True)))
            # A wide transparent mark is what actually catches the pointer; the visible
            # rule, dot, and tooltip all key off the same selection.
            catcher = base.mark_rule(opacity=0).encode(
                tooltip=[alt.Tooltip("as_of:T", title="Date", format="%Y-%m-%d"),
                         alt.Tooltip("close:Q", title=f"Close, {currency}",
                                     format=",.2f")]).add_params(hover)
            crosshair = base.mark_rule(color=T.P.stale, strokeDash=[2, 2]).encode(
                opacity=alt.condition(hover, alt.value(0.9), alt.value(0)))
            dot = base.mark_point(filled=True, size=52, color=T.P.oxblood).encode(
                alt.Y("close:Q"),
                opacity=alt.condition(hover, alt.value(1), alt.value(0)))
            # Scales bound to drag and wheel, so the window buttons are the coarse
            # control and zoom is the fine one.
            chart((line + crosshair + dot + catcher).interactive(), 300)
            st.markdown(
                '<div class="byline">Hover for the close on any session. Drag to zoom '
                'and double click to reset. Five years of daily closes are stored, so '
                'the window buttons re-scale rather than refetch.</div>',
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

            # Built as SVG rather than through Altair. A chart made inside a hidden tab
            # is measured at a few pixels and draws about 160px wide for good (see the
            # chart helper), and this panel has to hold its width on this tab.
            panel = trend_module.render(built.get("trend") or [], built["basis"])
            if panel:
                section("Growth against margin")
                st.markdown(f'<div class="trend">{panel}</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="byline">'
                    f'{trend_module.caption(built.get("trend") or [], built["basis"])}'
                    '</div>', unsafe_allow_html=True)
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
                if any(cell["derived"] for line in block["lines"]
                       for cell in line["cells"]):
                    # Fourth quarters only exist on the quarterly income statement, so
                    # the sentence explaining them is only shown where they appear.
                    derived_note = ("Dotted figures are computed from two reported "
                                    "lines rather than tagged by the filer")
                    if key == "income" and built["basis"] == "quarterly":
                        derived_note += (": a subtotal it leaves out, or a fourth "
                                         "quarter, which is the reported year less the "
                                         "reported nine months.")
                    else:
                        derived_note += ", which is a subtotal the filer leaves out."
                    footnotes.append(derived_note)
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
        # Units live in the header, never repeated in the cells. Precision is fixed per
        # column so decimals align down the column and figures hold their width.
        # Field names stay clean so Altair can reference them; the units are added to
        # the headers at display time only.
        cols = {"Revenue": 1, "Growth": 1, "Net margin": 1, "R&D": 1,
                "Mkt cap": 0, "P/E": 1, "EV/Sales": 1}
        units = {"Revenue": "Revenue, bn", "Growth": "Growth, %",
                 "Net margin": "Net margin, %", "R&D": "R&D, %",
                 "Mkt cap": "Mkt cap, $bn"}
        display = pd.DataFrame([{
            "Ticker": c["ticker"], "Name": c["name"], "FY": c["fiscal_year"],
            "Cur": c["currency"],
            "Revenue": c["revenue"] / 1e9 if c["revenue"] else None,
            "Growth": c["revenue_growth"] * 100 if c["revenue_growth"] is not None else None,
            "Net margin": c["net_margin"] * 100 if c["net_margin"] is not None else None,
            "R&D": c["rd_pct"] * 100 if c["rd_pct"] is not None else None,
            "Mkt cap": c["market_cap"] / 1e9 if c["market_cap"] else None,
            "P/E": c["pe"], "EV/Sales": c["ev_sales"]} for c in comps])
        # Streamlit reads the frame's own column names, so the units go on the frame
        # rather than through the Styler. The scatter keeps the clean-named original.
        table = display.rename(columns=units)
        formats = {units.get(name, name): (lambda dp: lambda v: T.num(v, dp))(dp)
                   for name, dp in cols.items()}
        formats["FY"] = lambda v: "—" if pd.isna(v) else f"{int(v)}"
        styled = (table.style
                  .format(formats, na_rep="—")
                  .map(lambda v: f"color:{T.P.oxblood}"
                       if isinstance(v, (int, float)) and not pd.isna(v) and v < 0
                       else "", subset=[units.get(c, c) for c in cols]))
        st.dataframe(styled, width="stretch", hide_index=True)
        st.markdown(
            '<div class="byline">Units are in the header, not the cells. Revenue, '
            'growth, margin, and R&D are in each filer\'s reporting currency. Market '
            'cap, P/E, and EV/Sales need shares outstanding and USD reporting, so they '
            'resolve for US filers only. A dash is no free data, not zero.</div>',
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
            # One hue, shaded by count. A matrix cell answers "how many", so colour
            # carries the number and the phase is read off the axis it already sits on.
            # Colouring by phase instead made every cell in a column identical and threw
            # the count away, which is the one thing this chart is for.
            chart(alt.Chart(long).mark_rect(stroke=T.P.ground, strokeWidth=1).encode(
                x=alt.X("Phase:N", title=None, sort=DISPLAY_PHASES),
                y=alt.Y("Ticker:N", title=None, sort=list(grid["Ticker"])),
                # Sqrt, not linear: one company runs three figures of trials and a
                # linear ramp collapses everyone else into the same pale tint.
                color=alt.Color("Trials:Q", legend=alt.Legend(title="Trials"),
                                scale=alt.Scale(range=list(T.P.phase_tints), type="sqrt")),
                tooltip=["Ticker:N", "Phase:N", "Trials:Q"]), 420)
            st.markdown('<div class="byline">Phase is ordinal, so it takes an ink tint '
                        'rather than a hue. Counts are trials, not deduplicated assets, '
                        'so a combination trial counts once per phase. Seamless trials '
                        'count at the phase they reach: Phase 1/2 with Phase 2, '
                        'Phase 2/3 with Phase 3. Phase 4 is left out, being work on '
                        'products already approved rather than anything in '
                        'development.</div>',
                        unsafe_allow_html=True)

        scatter = display.dropna(subset=["Growth", "Net margin"])
        if not scatter.empty:
            section("Growth against margin", f"{ticker} in oxblood")
            scatter = scatter.assign(sel=scatter["Ticker"].eq(ticker))
            chart(alt.Chart(scatter).mark_point(filled=True, size=70).encode(
                x=alt.X("Growth:Q", title="Revenue growth, %"),
                y=alt.Y("Net margin:Q", title="Net margin, %"),
                color=alt.Color("sel:N", scale=alt.Scale(
                    domain=[False, True], range=[T.P.stale, T.P.oxblood]), legend=None),
                tooltip=["Ticker:N", alt.Tooltip("Growth:Q", format=".1f"),
                         alt.Tooltip("Net margin:Q", format=".1f")]), 230)

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
            # at the same trial count. Selecting dims everything else.
            #
            # Counted here rather than with sum(n) in Vega, which is what made every
            # bar render at quarter opacity. The dimming test reads datum.picked, and
            # an aggregate drops every field it does not group by, so picked came
            # back undefined and the condition fell to its false branch for all of
            # them. The bars carried the right colours the whole time at a quarter of
            # their strength, which is why they never matched the key.
            seg = areas.groupby(["Area", "Phase"], as_index=False)["n"].sum()
            seg["picked"] = seg["Area"].isin(chosen) if chosen else True
            # No fixed bar height. A pixel height set against a band derived from the
            # chart height overlaps as soon as the band is the smaller of the two,
            # which it was: 18px bars in 16.7px bands ran 1 to 2px into each other.
            # Letting the bar fill its band makes that impossible at any height, and
            # the scale padding is what puts a visible gap between them.
            # The range is taken from the length of the domain rather than from a
            # fixed tuple, so the two cannot drift apart. They had: six phases were
            # declared against five tints, and Phase 4 fell off the end of the scale
            # with no colour of its own.
            bars = (alt.Chart(seg).mark_bar()
                    .encode(
                        y=alt.Y("Area:N", title=None, sort=order,
                                scale=alt.Scale(paddingInner=0.3, paddingOuter=0.2)),
                        x=alt.X("n:Q", title="Trials"),
                        color=alt.Color(
                            "Phase:N", sort=DISPLAY_PHASES,
                            scale=alt.Scale(domain=DISPLAY_PHASES,
                                            range=T.ordinal_ramp(len(DISPLAY_PHASES))),
                            legend=alt.Legend(title=None)),
                        order=alt.Order("Phase:N", sort="ascending"),
                        opacity=alt.condition("datum.picked", alt.value(1),
                                              alt.value(0.25)),
                        tooltip=[alt.Tooltip("Area:N"), alt.Tooltip("Phase:N"),
                                 alt.Tooltip("n:Q", title="Trials")]))
            # 34px per area leaves a readable bar once scale padding is taken out,
            # and the axis and legend get their own room rather than eating a band.
            chart(bars, max(170, 34 * len(order)))

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
                st.dataframe(pd.DataFrame([{
                    "NCT": t["nct_id"], "Phase": t["phase"], "Area": t["area"],
                    "Status": t["overall_status"],
                    "Primary completion": t["primary_completion_date"],
                    # A date that has passed means opposite things depending on
                    # this. Actual: the endpoint was reached and the trial runs on
                    # for survival follow-up, sometimes for a decade. Estimated and
                    # past: the forecast was missed and nobody updated the record.
                    "Date": _completion_note(t),
                    "Conditions": ", ".join(t["conditions"][:3]),
                    "Title": t["title"]}
                    for t in shown]), width="stretch", hide_index=True)
                st.markdown(
                    '<div class="byline">Areas are matched from the registry '
                    'condition text by keyword, so the rule that placed a trial is '
                    'readable rather than guessed. Reached means the primary '
                    'endpoint was met and the study continues for follow-up; '
                    'overdue means an estimated date has passed without being '
                    'revised.</div>', unsafe_allow_html=True)

    # --- LOE -------------------------------------------------------------
    with loe_tab:
        section("Exclusivity cliff", "US products per year")
        data = api_get(api_base, "/loe")
        year_cols = [str(y) for y in data["years"]] + [data["later_label"]]
        grid = pd.DataFrame([{"Ticker": r["ticker"],
                              **{str(y): r["years"].get(str(y), 0) for y in data["years"]},
                              data["later_label"]: r["later"]} for r in data["rows"]])
        if grid[year_cols].to_numpy().sum() == 0:
            state("No exclusivity data yet",
                  "Press Refresh all on the Comps tab to download the FDA Orange Book "
                  "and Purple Book. They refresh weekly.")
        else:
            totals = pd.DataFrame({"Year": year_cols,
                                   "Products": [int(grid[c].sum()) for c in year_cols]})
            chart(alt.Chart(totals).mark_bar(size=22).encode(
                x=alt.X("Year:N", title=None, sort=year_cols),
                y=alt.Y("Products:Q", title="Products losing exclusivity"),
                tooltip=["Year:N", "Products:Q"]), 220)

            section(f"Upcoming for {ticker}", len(exclusivities))
            if not exclusivities:
                state(f"No upcoming loss of exclusivity for {ticker}",
                      "Either nothing expires inside the window or the books carry no "
                      "entry for this company. Biologics coverage is partial.")
            else:
                frame = pd.DataFrame([{
                    "Expiry": a["loe"], "Basis": a.get("loe_basis") or "—",
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
                         if v == "orphan exclusivity" else "", subset=["Basis"]),
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
                    'books.</div>', unsafe_allow_html=True)

    # --- Approvals -------------------------------------------------------
    with approvals_tab:
        approvals = api_get(api_base, f"/companies/{ticker}/approvals")["approvals"]
        section(f"FDA approvals for {ticker}", len(approvals))
        if not approvals:
            state(f"No approvals on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull openFDA. Coverage depends "
                  "on openFDA manufacturer tagging and is not exhaustive.")
        else:
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
            st.markdown(
                '<div class="byline">Protection is the latest expiry the Orange or '
                'Purple Book carries for the product, so several approvals of one '
                'product share it. A dash is no entry in the books rather than no '
                'protection. Revenue is the worldwide figure the filing tags per product, from the '
                'SEC data sets, in billions of the reporting currency. Products the filing '
                'does not break out are blank.</div>', unsafe_allow_html=True)

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
            mix = revenue_mix.render(mix_rows, mix_currency, latest_year,
                                     reported.get("value"))
            if mix:
                section("Revenue mix", f"FY{latest_year}")
                st.markdown(f'<div class="trend">{mix}</div>', unsafe_allow_html=True)
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

    # --- News ------------------------------------------------------------
    with news_tab:
        news = api_get(api_base, f"/companies/{ticker}/news")["news"]
        section(f"Material events for {ticker}", len(news))
        if not news:
            state(f"No filings on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull 8-K and 6-K material "
                  "events from EDGAR. European filers submit 6-K, not 8-K.")
        else:
            st.dataframe(
                pd.DataFrame([{"Published": n["published_at"], "Title": n["title"],
                               "Link": n["url"]} for n in news]),
                width="stretch", hide_index=True,
                column_config={"Link": st.column_config.LinkColumn("Link")})
            st.markdown('<div class="byline">From EDGAR 8-K and 6-K material events. '
                        'IR RSS is a labelled future add.</div>', unsafe_allow_html=True)
