"""Streamlit terminal: key insights, prices, financials, comps, pipeline, and LOE.

A thin client over the FastAPI JSON endpoints. One company is selected in the sidebar
and drives every per-company view, so the feed, the note, and the horizon rail always
describe the same company.

Presentation rules live in ``theme`` and the horizon rail in ``rail``. Valuation ratios
resolve only for US filers (shares outstanding and USD reporting); those cells show a
dash, which means no free data rather than zero.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import altair as alt
import pandas as pd
import streamlit as st

import rail as rail_module
import theme as T

DEFAULT_API = "http://localhost:8000"
DEFAULT_TICKER = "LLY"
FY_METRICS = ["Revenues", "NetIncomeLoss", "ResearchAndDevelopmentExpense"]
FY_LABELS = {"Revenues": "Revenue", "NetIncomeLoss": "Net income",
             "ResearchAndDevelopmentExpense": "R&D"}
PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]
# Price chart windows, widest last. None means every session held. Windows wider than
# the stored history are hidden rather than drawn short.
PRICE_WINDOWS = [("1M", 31), ("3M", 92), ("6M", 183), ("1Y", 365), ("5Y", None)]
CATALYST_TYPES = ["PDUFA", "data readout", "EMA decision", "AdCom", "conference", "other"]


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
filer = "US filer" if company.get("is_sec_filer") else "not an SEC filer"
meta = " · ".join(x for x in [company.get("exchange"), filer,
                              prices.get("currency") or None] if x)
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
    (insights_tab, prices_tab, financials_tab, comps_tab, pipeline_tab, loe_tab,
     approvals_tab, catalysts_tab, news_tab) = st.tabs(
        ["Key insights", "Prices", "Financials", "Comps", "Pipeline", "LOE",
         "Approvals", "Catalysts", "News"])

    # --- Key insights: the feed is the most important view ---------------
    with insights_tab:
        high = sum(1 for it in feed if it["significance"] == "high")

        def _next(kind):
            dates = sorted((it["date"] or "")[:10] for it in feed
                           if it["kind"] == kind and it["date"])
            return dates[0] if dates else None

        cells = [("flagged", str(len(feed)), "" if feed else "none"),
                 ("high severity", str(high), "risk" if high else "none"),
                 ("next catalyst", _next("catalyst") or "—",
                  "" if _next("catalyst") else "none"),
                 ("next loe", _next("loe") or "—", "" if _next("loe") else "none")]
        st.markdown(
            '<div class="stats">' + "".join(
                f'<span class="stat"><span class="k">{k}</span>'
                f'<span class="v {cls}">{v}</span></span>' for k, v, cls in cells)
            + "</div>", unsafe_allow_html=True)

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
                  "The feed compares snapshots between refreshes, so it needs two runs "
                  "before the first diff appears. Run one from the Prices tab, then run "
                  "it again after the next data update.")

        for kind, label, date_col, blurb in (
            ("change", "Changes since the last refresh", "Detected",
             "Snapshot diffs: trial status and date moves, new 8-K and 6-K filings, "
             "new approvals."),
            ("catalyst", "Catalysts inside 60 days", "Expected",
             "Curated dates from the Catalysts tab. No free PDUFA calendar exists."),
            ("loe", "Loss of exclusivity ahead", "Expiry",
             "Latest patent or exclusivity expiry per marketed product, next 24 months."),
        ):
            items = [it for it in feed if it["kind"] == kind]
            if not items:
                continue
            section(label, len(items))
            rows = []
            for it in items:
                # Severity is carried by the colour of the word alone. An extra dot
                # would encode the same thing twice, in a glyph outside the palette.
                row = {"Sev": it["significance"], date_col: (it["date"] or "")[:10]}
                if kind != "loe":
                    row["Type"] = it.get("change_type") or kind
                if kind == "loe":
                    row["Modality"] = it.get("modality") or "—"
                row["Item"] = it["headline"]
                rows.append(row)
            frame = pd.DataFrame(rows)
            styled = frame.style.map(
                lambda v: f"color:{T.P.severity.get(v, T.P.ink)};font-weight:600",
                subset=["Sev"])
            if "Modality" in frame:
                styled = styled.map(
                    lambda v: f"color:{T.P.modality.get(v, T.P.stale)};font-weight:600",
                    subset=["Modality"])
            st.dataframe(styled, width="stretch", hide_index=True)
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
        fin = api_get(api_base, f"/companies/{ticker}/financials")
        fy_rows = [r for r in fin["rows"]
                   if r["period_type"] == "FY" and r["metric"] in FY_METRICS]
        currency = fy_rows[0]["unit"] if fy_rows else ""
        section("Reported financials", f"{currency} bn" if currency else "")
        if not fy_rows:
            state(f"No financials on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull EDGAR company facts. "
                  "Roche and Bayer do not file with the SEC, so EDGAR has nothing for "
                  "them and this stays empty by design.")
        else:
            years = sorted({r["fiscal_year"] for r in fy_rows})
            table = {}
            for metric in FY_METRICS:
                by_year = {r["fiscal_year"]: r["value"]
                           for r in fy_rows if r["metric"] == metric}
                table[FY_LABELS[metric]] = [by_year.get(y) for y in years]
            frame = pd.DataFrame(table, index=[str(y) for y in years]).transpose() / 1e9
            st.dataframe(
                frame.style.format(lambda v: T.num(v, 2)).map(
                    lambda v: f"color:{T.P.oxblood}" if isinstance(v, (int, float))
                    and v < 0 else ""),
                width="stretch")
            revenue = [{"year": str(y),
                        "value": next((r["value"] / 1e9 for r in fy_rows
                                       if r["metric"] == "Revenues"
                                       and r["fiscal_year"] == y), None)}
                       for y in years]
            chart(alt.Chart(pd.DataFrame(revenue)).mark_bar(size=26).encode(
                x=alt.X("year:N", title=None),
                y=alt.Y("value:Q", title=f"Revenue, {currency} bn"),
                tooltip=[alt.Tooltip("year:N", title="FY"),
                         alt.Tooltip("value:Q", title="Revenue", format=",.2f")]), 210)

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
        section("Active trials by phase", "lead sponsored")
        rows = api_get(api_base, "/pipeline")
        grid = pd.DataFrame([{"Ticker": r["ticker"], **r["phases"], "Total": r["total"]}
                             for r in rows])
        if grid[PIPELINE_PHASES].to_numpy().sum() == 0:
            state("No trials on file",
                  "Press Refresh all on the Comps tab to pull active lead-sponsored "
                  "interventional trials from ClinicalTrials.gov.")
        else:
            long = grid.melt(id_vars="Ticker", value_vars=PIPELINE_PHASES,
                             var_name="Phase", value_name="Trials")
            chart(alt.Chart(long).mark_rect(stroke=T.P.ground, strokeWidth=1).encode(
                x=alt.X("Phase:N", title=None, sort=PIPELINE_PHASES),
                y=alt.Y("Ticker:N", title=None, sort=list(grid["Ticker"])),
                # Sqrt, not linear: one company runs three figures of trials and a
                # linear ramp collapses everyone else into the same pale tint.
                color=alt.Color("Trials:Q", legend=alt.Legend(title="Trials"),
                                scale=alt.Scale(range=list(T.P.phase_tints), type="sqrt")),
                tooltip=["Ticker:N", "Phase:N", "Trials:Q"]), 420)
            st.markdown('<div class="byline">Phase is ordinal, so it takes an ink tint '
                        'rather than a hue. Counts are trials, not deduplicated assets, '
                        'so a combination trial counts once per phase.</div>',
                        unsafe_allow_html=True)

            section("Trials behind a cell")
            phase_choice = st.selectbox("Phase", ["All"] + PIPELINE_PHASES,
                                        key="pipe_phase", label_visibility="collapsed")
            query = "" if phase_choice == "All" else f"?phase={urllib.parse.quote(phase_choice)}"
            detail = api_get(api_base, f"/companies/{ticker}/trials{query}")["trials"]
            if not detail:
                state(f"No {phase_choice.lower()} trials for {ticker}",
                      "Pick another phase, or another company in the sidebar.")
            else:
                st.dataframe(pd.DataFrame([{
                    "NCT": t["nct_id"], "Phase": t["phase"], "Status": t["overall_status"],
                    "Primary completion": t["primary_completion_date"],
                    "Conditions": ", ".join(t["conditions"][:3]), "Title": t["title"]}
                    for t in detail]), width="stretch", hide_index=True)

    # --- LOE -------------------------------------------------------------
    with loe_tab:
        section("Exclusivity cliff", "products per year")
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
                    "Expiry": a["loe"], "Modality": a["modality"] or "—",
                    "Brand": a["brand_name"], "Generic": a["generic_name"],
                    "Application": a["internal_code"]} for a in exclusivities])
                st.dataframe(
                    frame.style.map(
                        lambda v: f"color:{T.P.modality.get(v, T.P.stale)};"
                                  "font-weight:600", subset=["Modality"]),
                    width="stretch", hide_index=True)
                st.markdown('<div class="byline">Orange for small molecules, purple for '
                            'biologics, the colours of the two source books. Not revenue '
                            'weighted: no free product revenue exists.</div>',
                            unsafe_allow_html=True)

    # --- Approvals -------------------------------------------------------
    with approvals_tab:
        approvals = api_get(api_base, f"/companies/{ticker}/approvals")["approvals"]
        section(f"FDA approvals for {ticker}", len(approvals))
        if not approvals:
            state(f"No approvals on file for {ticker}",
                  "Press Refresh all on the Comps tab to pull openFDA. Coverage depends "
                  "on openFDA manufacturer tagging and is not exhaustive.")
        else:
            frame = pd.DataFrame([{
                "Approved": a["approval_date"], "Modality": a["modality"] or "—",
                "Brand": a["brand_name"], "Application": a["application_number"]}
                for a in approvals])
            st.dataframe(
                frame.style.map(
                    lambda v: f"color:{T.P.modality.get(v, T.P.stale)};font-weight:600",
                    subset=["Modality"]),
                width="stretch", hide_index=True)

    # --- Catalysts -------------------------------------------------------
    with catalysts_tab:
        section("Catalyst calendar", "curated")
        with st.form("add_catalyst", clear_on_submit=True):
            cols = st.columns([1, 1, 1, 3])
            cat_ticker = cols[0].selectbox("Company", tickers, index=default_index,
                                           key="cat_ticker")
            cat_type = cols[1].selectbox("Type", CATALYST_TYPES, key="cat_type")
            cat_date = cols[2].date_input("Expected date", key="cat_date")
            cat_title = cols[3].text_input("Title", key="cat_title")
            if st.form_submit_button("Add catalyst"):
                if cat_title.strip():
                    try:
                        api_post_json(api_base, "/catalysts", {
                            "ticker": cat_ticker, "catalyst_type": cat_type,
                            "expected_date": str(cat_date), "title": cat_title.strip()})
                        api_get.clear()
                        st.rerun()
                    except (urllib.error.URLError, OSError) as exc:
                        state("The catalyst was not saved", str(exc), error=True)
                else:
                    state("A catalyst needs a title",
                          "Give it the event name, for example Winrevair sBLA decision.")

        window = st.radio("Window", [90, 180, 365], index=0, horizontal=True,
                          format_func=lambda d: f"{d} days", key="cat_window",
                          label_visibility="collapsed")
        calendar = api_get(api_base, f"/catalysts?within_days={window}")
        mine = [c for c in calendar if c["is_curated"]]
        derived = [c for c in calendar if not c["is_curated"]]

        if not calendar:
            state(f"No catalysts in the next {window} days",
                  "Readouts are derived from Phase 3 primary completion dates on every "
                  "refresh, so this fills once trials are fetched. PDUFA dates have no "
                  "free source and are added by hand above.")
        else:
            section("Calendar", f"{len(mine)} yours · {len(derived)} derived")
            frame = pd.DataFrame([{
                "id": c["id"],
                "Source": "yours" if c["is_curated"] else "derived",
                "Date": c["expected_date"], "Company": c["ticker"],
                "Type": c["catalyst_type"], "Confidence": c["date_confidence"],
                "Title": c["title"], "Evidence": c["source_url"] or "—"}
                for c in calendar])
            st.dataframe(
                frame.style.map(
                    lambda v: f"color:{T.P.ink if v == 'yours' else T.P.stale};"
                              "font-weight:600", subset=["Source"]),
                width="stretch", hide_index=True,
                column_config={"Evidence": st.column_config.LinkColumn(
                    "Evidence", display_text=r"NCT\w+")})
            st.markdown(
                '<div class="byline">Derived rows come from Phase 3 primary completion '
                'dates on ClinicalTrials.gov, which are estimates and move. A refresh '
                'updates a derived date in place and withdraws the row if the trial '
                'stops. Accept one to make it yours, after which no refresh will touch '
                'it.</div>', unsafe_allow_html=True)

            act = st.columns([1, 1, 1, 4])
            target = act[0].number_input("Row id", min_value=0, step=1, value=0,
                                         key="cat_target")
            if act[1].button("Accept", key="cat_accept") and target:
                try:
                    api_post(api_base, f"/catalysts/{int(target)}/accept", timeout=30)
                    api_get.clear()
                    st.rerun()
                except (urllib.error.URLError, OSError) as exc:
                    state("That row was not accepted",
                          f"{exc}. Only a derived row can be accepted; a row that is "
                          "already yours has nothing to promote.", error=True)
            if act[2].button("Delete", key="cat_delete") and target:
                try:
                    api_delete(api_base, f"/catalysts/{int(target)}")
                    api_get.clear()
                    st.rerun()
                except (urllib.error.URLError, OSError) as exc:
                    state("That row was not deleted", str(exc), error=True)

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
