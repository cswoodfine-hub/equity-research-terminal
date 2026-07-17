"""Streamlit terminal: prices, financials, and the comps table.

A thin client over the FastAPI JSON endpoints. Valuation ratios resolve only for US
filers (shares outstanding and USD reporting); other cells show as blank, which the
captions explain as "no free data" rather than an estimate.
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


st.set_page_config(page_title="Equity research terminal", layout="wide")
st.title("Pharma equity research terminal")
st.caption("Phase 3: prices, EDGAR financials, and the comps table.")

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

PIPELINE_PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]

prices_tab, financials_tab, comps_tab, pipeline_tab = st.tabs(
    ["Prices", "Financials", "Comps", "Pipeline"]
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
        styled = grid.style.background_gradient(
            cmap="Blues", subset=PIPELINE_PHASES, axis=None
        ).format("{:d}")
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
