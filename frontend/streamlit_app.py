"""Streamlit terminal: key insights, prices, financials, and the comps table.

A thin client over the FastAPI JSON endpoints. One company is selected in the sidebar
and drives every per-company tab, so the Key insights feed and the note it summarises
always describe the same company.

Valuation ratios resolve only for US filers (shares outstanding and USD reporting);
other cells show as blank, which the captions explain as "no free data" rather than an
estimate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

DEFAULT_API = "http://localhost:8000"
DEFAULT_TICKER = "LLY"
FY_METRICS = ["Revenues", "NetIncomeLoss", "ResearchAndDevelopmentExpense"]
FY_LABELS = {
    "Revenues": "Revenue",
    "NetIncomeLoss": "Net income",
    "ResearchAndDevelopmentExpense": "R&D",
}


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


st.set_page_config(page_title="Equity research terminal", layout="wide")
st.title("Pharma equity research terminal")
st.caption("Key insights per company, plus prices, financials, comps, pipeline, LOE, "
           "approvals, catalysts, and news.")

st.sidebar.header("Settings")
api_base = st.sidebar.text_input("API base URL", DEFAULT_API)

try:
    companies = api_get(api_base, "/companies")
except (urllib.error.URLError, OSError) as exc:
    st.error(f"Cannot reach the API at {api_base}. Is uvicorn running? ({exc})")
    st.stop()

if not companies:
    st.warning("No companies loaded. Run seed.py against the backend database.")
    st.stop()

tickers = [c["ticker"] for c in companies]
names = {c["ticker"]: c["name"] for c in companies}
default_index = tickers.index(DEFAULT_TICKER) if DEFAULT_TICKER in tickers else 0
ticker = st.sidebar.selectbox("Company", tickers, index=default_index)
st.sidebar.caption(f"{names.get(ticker, ticker)}. This selection drives every "
                   "per-company tab, including Key insights.")

PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]

(insights_tab, prices_tab, financials_tab, comps_tab, pipeline_tab, loe_tab,
 approvals_tab, catalysts_tab, news_tab) = st.tabs(
    ["Key insights", "Prices", "Financials", "Comps", "Pipeline", "LOE", "Approvals",
     "Catalysts", "News"]
)
CATALYST_TYPES = ["PDUFA", "data readout", "EMA decision", "AdCom", "conference", "other"]
_SEV_COLOR = {"high": "#c0392b", "medium": "#c07d17", "low": "#7f8c8d"}
_SEV_DOT = {"high": "🔴", "medium": "🟠", "low": "⚪"}

# One section per feed kind, in reading order: what changed, what is coming, what expires.
_FEED_SECTIONS = (
    ("change", "Changes since the last refresh", "Detected",
     "Snapshot diffs: trial status and date moves, new 8-K/6-K filings, new approvals."),
    ("catalyst", "Catalysts inside 60 days", "Expected",
     "Curated dates from the Catalysts tab. No free PDUFA calendar exists."),
    ("loe", "Loss of exclusivity ahead", "Expiry",
     "Latest patent or exclusivity expiry per marketed product, next 24 months."),
)


# --- Prices -------------------------------------------------------------
with prices_tab:
    st.subheader(f"{names.get(ticker, ticker)} ({ticker})")
    if st.button("Refresh prices", type="primary", key="refresh_prices"):
        with st.spinner(f"Refreshing {ticker} from Yahoo"):
            try:
                st.session_state["price_run"] = api_post(
                    api_base, f"/refresh?ticker={urllib.parse.quote(ticker)}"
                )
            except (urllib.error.URLError, OSError) as exc:
                st.error(f"Refresh failed: {exc}")

    run = st.session_state.get("price_run")
    if run and run["detail"].get("ticker") == ticker:
        price_src = next((s for s in run["detail"]["sources"] if s["source"] == "prices"), None)
        if price_src:
            note = f"Run {run['id']} {run['status']}: {price_src['rows_fetched']} rows"
            (st.info if price_src["skipped_ttl"] else st.success)(
                note + (" (skipped, within TTL)" if price_src["skipped_ttl"] else "")
            )

    data = api_get(api_base, f"/companies/{ticker}/prices")
    points = data["points"]
    if not points:
        st.info("No price data yet. Click Refresh prices to pull the last six months.")
    else:
        currency = data.get("currency") or ""
        latest = data["latest"]
        cols = st.columns(3)
        cols[0].metric(f"Latest close ({currency})", f"{latest['close']:,.2f}")
        cols[1].metric("As of", latest["as_of"])
        cols[2].metric("Market cap", "see Comps tab")
        frame = pd.DataFrame(points)
        frame["as_of"] = pd.to_datetime(frame["as_of"])
        st.line_chart(frame.set_index("as_of")["close"], height=360)
        st.caption(f"{len(points)} trading days. Last live fetch: {data['last_fetch_at']}.")


# --- Financials ---------------------------------------------------------
with financials_tab:
    st.subheader(f"{names.get(ticker, ticker)} reported financials")
    fin = api_get(api_base, f"/companies/{ticker}/financials")
    fy_rows = [r for r in fin["rows"] if r["period_type"] == "FY" and r["metric"] in FY_METRICS]
    if not fy_rows:
        st.info(
            "No financials yet. Use Refresh all on the Comps tab. Roche and Bayer are "
            "not SEC filers, so EDGAR has nothing for them."
        )
    else:
        currency = fy_rows[0]["unit"]
        years = sorted({r["fiscal_year"] for r in fy_rows})
        table = {}
        for metric in FY_METRICS:
            by_year = {r["fiscal_year"]: r["value"] for r in fy_rows if r["metric"] == metric}
            table[FY_LABELS[metric]] = [by_year.get(y) for y in years]
        frame = pd.DataFrame(table, index=[str(y) for y in years]).transpose()
        st.caption(f"Values in {currency} billions.")
        st.dataframe((frame / 1e9).round(2), use_container_width=True)
        revenue_by_year = {
            str(r["fiscal_year"]): r["value"] / 1e9
            for r in fy_rows
            if r["metric"] == "Revenues"
        }
        if revenue_by_year:
            st.bar_chart(pd.Series(revenue_by_year, name=f"Revenue ({currency} bn)"))


# --- Comps --------------------------------------------------------------
with comps_tab:
    st.subheader("Comparables")
    if st.button("Refresh all", type="primary", key="refresh_all"):
        with st.spinner("Refreshing the universe (prices for all, EDGAR for filers)"):
            try:
                st.session_state["all_run"] = api_post(api_base, "/refresh?scope=all")
            except (urllib.error.URLError, OSError) as exc:
                st.error(f"Refresh all failed: {exc}")

    all_run = st.session_state.get("all_run")
    if all_run:
        parts = [
            f"{s['source']} {s['rows_fetched']} rows ({s['skipped_ttl']} skipped)"
            for s in all_run["detail"]["sources"]
        ]
        (st.success if all_run["status"] == "complete" else st.warning)(
            f"Run {all_run['id']} {all_run['status']}: " + ", ".join(parts)
        )

    comps = api_get(api_base, "/comps")
    display = pd.DataFrame(
        [
            {
                "Ticker": c["ticker"],
                "Name": c["name"],
                "FY": c["fiscal_year"],
                "Cur": c["currency"],
                "Revenue (bn)": c["revenue"] / 1e9 if c["revenue"] else None,
                "Growth %": c["revenue_growth"] * 100 if c["revenue_growth"] is not None else None,
                "Net margin %": c["net_margin"] * 100 if c["net_margin"] is not None else None,
                "R&D %": c["rd_pct"] * 100 if c["rd_pct"] is not None else None,
                "Mkt cap ($bn)": c["market_cap"] / 1e9 if c["market_cap"] else None,
                "P/E": c["pe"],
                "EV/Sales": c["ev_sales"],
            }
            for c in comps
        ]
    )
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Revenue (bn)": st.column_config.NumberColumn(format="%.1f"),
            "Growth %": st.column_config.NumberColumn(format="%.1f%%"),
            "Net margin %": st.column_config.NumberColumn(format="%.1f%%"),
            "R&D %": st.column_config.NumberColumn(format="%.1f%%"),
            "Mkt cap ($bn)": st.column_config.NumberColumn(format="%.0f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "EV/Sales": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    st.caption(
        "Revenue, growth, net margin, and R&D are in each filer's reporting currency. "
        "Market cap, P/E, and EV/Sales need shares outstanding and USD reporting, so they "
        "resolve for US filers only; blank cells are no free data, not zero. Click Refresh "
        "all to populate. Roche and Bayer are not SEC filers."
    )


# --- Pipeline -----------------------------------------------------------
with pipeline_tab:
    st.subheader("Clinical pipeline")
    if st.button("Refresh all", type="primary", key="refresh_all_pipeline"):
        with st.spinner("Refreshing the universe (this also pulls ClinicalTrials)"):
            try:
                st.session_state["all_run"] = api_post(api_base, "/refresh?scope=all")
            except (urllib.error.URLError, OSError) as exc:
                st.error(f"Refresh all failed: {exc}")

    rows = api_get(api_base, "/pipeline")
    grid = pd.DataFrame(
        [{"Ticker": r["ticker"], **r["phases"], "Total": r["total"]} for r in rows]
    ).set_index("Ticker")

    if grid[PIPELINE_PHASES].to_numpy().sum() == 0:
        st.info("No trials yet. Click Refresh all to pull active trials from ClinicalTrials.")
    else:
        phase_max = max(1, int(grid[PIPELINE_PHASES].to_numpy().max()))

        def _shade(value):
            # Manual blue gradient so no matplotlib dependency is needed.
            count = int(value) if value else 0
            if count <= 0:
                return ""
            alpha = 0.12 + 0.6 * (count / phase_max)
            text = "white" if alpha > 0.55 else "inherit"
            return f"background-color: rgba(33, 102, 172, {alpha:.3f}); color: {text}"

        styled = grid.style.applymap(_shade, subset=PIPELINE_PHASES).format("{:d}")
        st.dataframe(styled, use_container_width=True)
        st.caption(
            "Active, lead-sponsored interventional drug trials by phase. Counts are "
            "trials, not deduplicated assets, so combination trials count once per phase."
        )

        st.markdown("**Trials behind a cell**")
        cols = st.columns(2)
        drill_ticker = cols[0].selectbox("Company", tickers, index=default_index, key="pipe_ticker")
        phase_choice = cols[1].selectbox("Phase", ["All"] + PIPELINE_PHASES, key="pipe_phase")
        query = "" if phase_choice == "All" else f"?phase={urllib.parse.quote(phase_choice)}"
        detail = api_get(api_base, f"/companies/{drill_ticker}/trials{query}")["trials"]
        if not detail:
            st.write("No trials for this selection.")
        else:
            table = pd.DataFrame(
                [
                    {
                        "NCT": t["nct_id"],
                        "Phase": t["phase"],
                        "Status": t["overall_status"],
                        "Primary completion": t["primary_completion_date"],
                        "Conditions": ", ".join(t["conditions"][:3]),
                        "Title": t["title"],
                    }
                    for t in detail
                ]
            )
            st.caption(f"{len(detail)} trials for {drill_ticker}"
                       + ("" if phase_choice == "All" else f" in {phase_choice}"))
            st.dataframe(table, use_container_width=True, hide_index=True)


# --- LOE ----------------------------------------------------------------
with loe_tab:
    st.subheader("Loss of exclusivity")
    if st.button("Refresh all", type="primary", key="refresh_all_loe"):
        with st.spinner("Refreshing the universe (this also downloads FDA data)"):
            try:
                st.session_state["all_run"] = api_post(api_base, "/refresh?scope=all")
            except (urllib.error.URLError, OSError) as exc:
                st.error(f"Refresh all failed: {exc}")

    data = api_get(api_base, "/loe")
    year_cols = [str(y) for y in data["years"]] + [data["later_label"]]
    grid = pd.DataFrame(
        [
            {"Ticker": r["ticker"],
             **{str(y): r["years"].get(str(y), 0) for y in data["years"]},
             data["later_label"]: r["later"]}
            for r in data["rows"]
        ]
    ).set_index("Ticker")

    if grid[year_cols].to_numpy().sum() == 0:
        st.info("No exclusivity data yet. Click Refresh all to download the Orange and Purple Book.")
    else:
        phase_max = max(1, int(grid[year_cols].to_numpy().max()))

        def _shade_loe(value):
            count = int(value) if value else 0
            if count <= 0:
                return ""
            alpha = 0.12 + 0.6 * (count / phase_max)
            return f"background-color: rgba(197, 90, 17, {alpha:.3f}); color: {'white' if alpha > 0.55 else 'inherit'}"

        st.dataframe(grid.style.applymap(_shade_loe, subset=year_cols).format("{:d}"),
                     use_container_width=True)
        st.caption(
            "Count of marketed products losing exclusivity per year (latest patent or "
            "exclusivity expiry). No free product revenue, so this is not revenue-weighted; "
            "biologics coverage (Purple Book) is partial. Blank/0 is no upcoming LOE on file."
        )

        st.markdown(f"**Upcoming LOE for {names.get(ticker, ticker)} ({ticker})**")
        assets = api_get(api_base, f"/companies/{ticker}/exclusivities")["assets"]
        if not assets:
            st.write("No products with upcoming loss of exclusivity on file.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"LOE date": a["loe"], "Modality": a["modality"],
                         "Brand": a["brand_name"], "Generic": a["generic_name"],
                         "Application": a["internal_code"]}
                        for a in assets
                    ]
                ),
                use_container_width=True, hide_index=True,
            )


# --- Approvals ----------------------------------------------------------
with approvals_tab:
    st.subheader(f"FDA approvals: {names.get(ticker, ticker)} ({ticker})")
    approvals = api_get(api_base, f"/companies/{ticker}/approvals")["approvals"]
    if not approvals:
        st.info("No approvals on file. Click Refresh all on the LOE tab to pull openFDA data.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Approved": a["approval_date"], "Application": a["application_number"],
                     "Brand": a["brand_name"], "Modality": a["modality"]}
                    for a in approvals
                ]
            ),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Original FDA approvals (NDAs and BLAs) from openFDA. Coverage depends on "
            "openFDA's manufacturer tagging and is not exhaustive."
        )


# --- Key insights -------------------------------------------------------
with insights_tab:
    st.subheader(f"Key insights: {names.get(ticker, ticker)} ({ticker})")
    st.caption("Everything below is for the company selected in the sidebar.")

    feed = api_get(api_base, f"/changes?ticker={urllib.parse.quote(ticker)}")
    by_kind = {kind: [it for it in feed if it["kind"] == kind]
               for kind, _, _, _ in _FEED_SECTIONS}

    def _next_date(kind):
        dates = sorted((it["date"] or "")[:10] for it in by_kind.get(kind, []) if it["date"])
        return dates[0] if dates else None

    high = sum(1 for it in feed if it["significance"] == "high")
    cols = st.columns(4)
    cols[0].metric("Flagged items", len(feed))
    cols[1].metric("High severity", high)
    cols[2].metric("Next catalyst", _next_date("catalyst") or "None")
    cols[3].metric("Next LOE", _next_date("loe") or "None")

    # --- Morning note ---
    with st.container(border=True):
        head, action = st.columns([4, 1])
        head.markdown("#### Morning note")
        regenerate = action.button("Generate", key="gen_note", use_container_width=True)

        if regenerate:
            with st.spinner(f"Writing the {ticker} note"):
                st.session_state["note"] = api_get(
                    api_base, f"/companies/{ticker}/note?refresh=true")
        elif st.session_state.get("note", {}).get("ticker") != ticker:
            st.session_state["note"] = api_get(api_base, f"/companies/{ticker}/note")

        note = st.session_state.get("note") or {}
        if not note.get("body"):
            st.info(f"No note for {ticker} yet. Press generate.")
        else:
            st.markdown(note["body"])
            layer = ("rules layer, no Anthropic key set"
                     if note.get("model") == "rules" else f"written by {note.get('model')}")
            # The stored note is a snapshot of the feed at the time it was written, so it
            # can disagree with the counts above. Say so rather than let them contradict.
            st.caption(f"{layer}. Written {note.get('generated_at')} from the feed as it "
                       "stood then. Press Generate to rebuild it from the feed above.")
        if note.get("error"):
            st.warning(f"Note fell back to the rules layer: {note['error']}")

    # --- The feed, one section per kind ---
    if not feed:
        st.info(
            f"Nothing flagged for {ticker}. The feed compares snapshots between "
            "refreshes, so it fills in once a refresh detects a trial status/date "
            "change, a new 8-K/6-K, or a new approval; it also surfaces catalysts "
            "within 60 days and near-term LOE."
        )
    for kind, heading, date_label, blurb in _FEED_SECTIONS:
        items = by_kind.get(kind, [])
        if not items:
            continue
        with st.container(border=True):
            st.markdown(f"#### {heading}  `{len(items)}`")
            rows = []
            for it in items:
                row = {"": _SEV_DOT.get(it["significance"], "⚪"),
                       "Severity": it["significance"],
                       date_label: (it["date"] or "")[:10]}
                # The type column repeats the heading for LOE, so only changes and
                # catalysts carry it.
                if kind != "loe":
                    row["Type"] = it.get("change_type") or kind
                row["Headline"] = it["headline"]
                rows.append(row)
            frame = pd.DataFrame(rows)
            styled = frame.style.apply(
                lambda col: [f"color: {_SEV_COLOR.get(v, 'inherit')}; font-weight: 600"
                             for v in col], subset=["Severity"])
            st.dataframe(
                styled, use_container_width=True, hide_index=True,
                column_config={"": st.column_config.TextColumn(width="small"),
                               "Headline": st.column_config.TextColumn(width="large")},
            )
            st.caption(blurb)


# --- Catalysts ----------------------------------------------------------
with catalysts_tab:
    st.subheader("Catalyst calendar")
    with st.form("add_catalyst", clear_on_submit=True):
        cols = st.columns([1, 1, 1, 3])
        cat_ticker = cols[0].selectbox("Company", tickers,
                                       index=default_index, key="cat_ticker")
        cat_type = cols[1].selectbox("Type", CATALYST_TYPES, key="cat_type")
        cat_date = cols[2].date_input("Expected date", key="cat_date")
        cat_title = cols[3].text_input("Title", key="cat_title")
        if st.form_submit_button("Add catalyst", type="primary"):
            if cat_title.strip():
                try:
                    api_post_json(api_base, "/catalysts", {
                        "ticker": cat_ticker, "catalyst_type": cat_type,
                        "expected_date": str(cat_date), "title": cat_title.strip()})
                    st.success(f"Added {cat_ticker} {cat_type} on {cat_date}")
                except (urllib.error.URLError, OSError) as exc:
                    st.error(f"Add failed: {exc}")
            else:
                st.warning("Give the catalyst a title.")

    calendar = api_get(api_base, "/catalysts?within_days=90")
    if not calendar:
        st.info("No upcoming catalysts. Add one above; the table is curated (no free "
                "PDUFA calendar exists).")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {"id": c["id"], "Company": c["ticker"], "Type": c["catalyst_type"],
                     "Date": c["expected_date"], "Confidence": c["date_confidence"],
                     "Title": c["title"], "Status": c["status"]}
                    for c in calendar
                ]
            ),
            use_container_width=True, hide_index=True,
        )
        del_cols = st.columns([1, 4])
        del_id = del_cols[0].number_input("Delete id", min_value=0, step=1, value=0)
        if del_cols[0].button("Delete") and del_id:
            try:
                api_delete(api_base, f"/catalysts/{int(del_id)}")
                st.success(f"Deleted catalyst {int(del_id)}")
            except (urllib.error.URLError, OSError) as exc:
                st.error(f"Delete failed: {exc}")
    st.caption("Curated table (is_curated=1). Auto-extraction of PDUFA dates from 8-K "
               "is a labelled future add.")


# --- News ---------------------------------------------------------------
with news_tab:
    st.subheader(f"News: {names.get(ticker, ticker)} ({ticker})")
    news = api_get(api_base, f"/companies/{ticker}/news")["news"]
    if not news:
        st.info("No news yet. Click Refresh all (LOE tab) to pull EDGAR 8-K/6-K filings.")
    else:
        st.dataframe(
            pd.DataFrame(
                [{"Published": n["published_at"], "Title": n["title"], "Link": n["url"]}
                 for n in news]
            ),
            use_container_width=True, hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Link")},
        )
        st.caption("From EDGAR 8-K/6-K material events. IR RSS is a labelled future add.")
