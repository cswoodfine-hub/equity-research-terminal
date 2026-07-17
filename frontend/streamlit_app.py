"""Streamlit vertical slice: pick a company, refresh its prices, see the chart.

A thin client over the FastAPI JSON endpoints. This is the fast-path UI; a React
frontend replaces it in a later phase without any backend change.
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


def api_get(base: str, path: str):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(base: str, path: str):
    request = urllib.request.Request(base.rstrip("/") + path, method="POST")
    with urllib.request.urlopen(request, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


st.set_page_config(page_title="Equity research terminal", layout="wide")
st.title("Pharma equity research terminal")
st.caption("Phase 2 vertical slice: prices, chart, and refresh for one company.")

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
st.subheader(f"{names.get(ticker, ticker)} ({ticker})")

if st.button("Refresh prices", type="primary"):
    with st.spinner(f"Refreshing {ticker} from Yahoo"):
        try:
            st.session_state["last_run"] = api_post(
                api_base, f"/refresh?ticker={urllib.parse.quote(ticker)}"
            )
        except (urllib.error.URLError, OSError) as exc:
            st.error(f"Refresh failed: {exc}")

run = st.session_state.get("last_run")
if run and run["detail"].get("ticker") == ticker:
    source = run["detail"]["sources"][0]
    line = (
        f"Run {run['id']} {run['status']} at {run['finished_at']}: "
        f"{source['rows_fetched']} rows, {source['elapsed_ms']} ms"
    )
    if source["skipped_ttl"]:
        st.info(line + " (skipped, within 15-minute TTL)")
    elif source["errors"]:
        st.warning(line + f" with errors: {'; '.join(source['errors'])}")
    else:
        st.success(line)

# --- price chart ---------------------------------------------------------
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
    cols[2].metric("Market cap", "no free data")

    frame = pd.DataFrame(points)
    frame["as_of"] = pd.to_datetime(frame["as_of"])
    st.line_chart(frame.set_index("as_of")["close"], height=380)
    st.caption(
        f"{len(points)} trading days. Last live fetch: {data['last_fetch_at']}. "
        "Market cap has no free source this phase and is left blank rather than estimated."
    )
