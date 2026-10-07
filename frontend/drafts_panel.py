"""Drafts waiting: the Forecast tab's review of rows drafted from a closed acquisition.

``GET /companies/{t}/drafts`` holds every closing the acquirer filed and the rows drafted
from the target's own filings (backend/input_drafts.py). Nothing in it is in a valuation
until a row is accepted. This draws the queue as one line with its count, opening onto
the closings, each with its rows: the product, the key, the drafted value with its unit
and year, the book's own value beside it, the quoted sentence or cells with the source,
the evidence grade and the status. A row is accepted, edited then accepted, or rejected;
an incomplete row says why and takes an edit before it can be accepted.

The builders are pure functions of the payload, so they are tested without Streamlit;
``render`` is the glue, with the app's transport passed in.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error

import streamlit as st

OPEN = ("draft", "incomplete")
# The assumption keys in words. A key not here is shown as it is stored.
KEY_WORDS = {
    "base_revenue": "base revenue", "revenue_ceiling_musd": "revenue ceiling",
    "revenue_growth_pct": "revenue growth", "peak_revenue_musd": "peak revenue",
    "years_to_peak": "years to peak", "therapy_mode": "forecast mode",
    "pos": "probability of success", "cogs_pct": "cost of goods",
    "sga_pct": "selling and admin", "rd_pct": "research and development",
    "other_costs_pct": "other costs", "tax_rate": "tax rate", "risk_free": "risk-free rate",
    "erp": "equity risk premium", "beta": "beta", "cost_of_debt": "cost of debt",
    "debt_weight": "debt weight", "forecast_start_year": "first forecast year",
    "forecast_years": "forecast years"}
_RATES = ("_pct", "tax_rate", "risk_free", "erp", "cost_of_debt", "debt_weight", "pos")
_YEAR = re.compile(r"\b(20\d\d)\b")


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def open_rows(queue: dict | None) -> int:
    return int((queue or {}).get("open") or 0)


def label(queue: dict | None) -> str | None:
    """The panel's one line, or None where nothing waits."""
    rows = open_rows(queue)
    if not rows:
        return None
    closings = sum(1 for c in (queue or {}).get("closings") or [] if c.get("open"))
    return (f"Drafts waiting · {rows} row{'s' if rows != 1 else ''} from {closings} "
            f"closing{'s' if closings != 1 else ''}")


def key_words(key: str, destination: str = "assumptions") -> str:
    if destination == "other_claims":
        return "cash paid, held as a claim"
    return KEY_WORDS.get(key, key)


def value_text(row: dict) -> str:
    """The drafted value as a reader takes it: a rate as a percentage, money with its
    unit, a text value as written. None is "no free data", never a zero."""
    return _value(row.get("key") or "", row.get("value"), row.get("text_value"),
                  row.get("unit"))


def _value(key: str, value, text, unit) -> str:
    if value is None:
        return str(text) if text else "no free data"
    if key == "beta":
        return f"{value:.2f}"
    if key in ("forecast_start_year",):
        return f"{value:.0f}"
    if key.endswith(_RATES) or key in _RATES:
        return f"{value * 100:.1f}%"
    number = f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.3g}"
    return f"{number} {unit}" if unit and not unit.startswith("annual") else number


def years_text(row: dict) -> str:
    """The year a value is for: the row's own year, else the years its quote names."""
    if row.get("year"):
        return str(row["year"])
    found = list(dict.fromkeys(_YEAR.findall(row.get("quote") or "")))
    if not found:
        return ""
    return found[0] if len(found) == 1 else f"{found[0]} to {found[-1]}"


def book_text(row: dict) -> str:
    """The book's own value for the same key, beside the drafted one."""
    if row.get("existing_value") is None and not row.get("existing_text"):
        return "not in the book"
    return "book: " + _value(row.get("key") or "", row.get("existing_value"),
                             row.get("existing_text"), row.get("unit"))


def money(usd) -> str:
    if not usd:
        return ""
    return f"${usd / 1e9:,.1f}bn" if usd >= 1e9 else f"${usd / 1e6:,.0f}m"


def closing_head_html(c: dict) -> str:
    """The closing: the target, the date with its filing, and what was paid."""
    paid = (c.get("context") or {}).get("consideration") or {}
    cash = money(paid.get("cash"))
    terms = (f"{cash} cash" if cash else "cash paid not stated")
    if paid.get("cvr_quote"):
        terms += " and a contingent value right"
    filing = esc(c.get("trigger_kind") or "filing")
    if c.get("trigger_url"):
        filing = (f'<a href="{esc(c["trigger_url"])}" target="_blank" rel="noopener">'
                  f'{filing}</a>')
    status = c.get("target_status")
    who = f'<span class="dr-tag">{esc(status)} target</span>' if status else ""
    note = (f'<details class="note-d"><summary>notes</summary><div class="byline">'
            f'{esc(c["note"])}</div></details>' if c.get("note") else "")
    date = c.get("closing_date") or "date not stated"
    return (f'<div class="dr-close"><span class="dr-target">{esc(c.get("target"))}</span>'
            f'{who}<span class="dr-meta">closed {esc(date)} · {filing} · {esc(terms)}'
            f'</span>{note}</div>')


def row_html(r: dict) -> str:
    """One drafted row: what it is, the value against the book's, where it came from,
    its grade and its status, and for an incomplete row why it is held."""
    status = r.get("status") or "draft"
    product = r.get("asset_name") or ("" if r.get("destination") == "other_claims"
                                      else "product not named")
    new = '<span class="dr-tag dr-new">new to the book</span>' if r.get("new_product") else ""
    year = years_text(r)
    source = esc(r.get("source") or "no source")
    if r.get("source_url"):
        source = (f'<a href="{esc(r["source_url"])}" target="_blank" rel="noopener">'
                  f'{source}</a>')
    quote = (f'<div class="dr-quote">&#8220;{esc(r["quote"])}&#8221;</div>'
             if r.get("quote") else "")
    why = ""
    if status == "incomplete":
        reason = re.sub(r"^Incomplete:\s*", "", r.get("note") or "no source or quote")
        why = f'<div class="dr-why">Held: {esc(reason.split(". ")[0].rstrip("."))}.</div>'
    elif r.get("note"):
        why = f'<div class="dr-note">{esc(r["note"])}</div>'
    return (f'<div class="dr-row s-{esc(status)}"><div class="dr-line">'
            f'<span class="dr-st">{esc(status)}</span>'
            f'<span class="dr-prod">{esc(product)}</span>{new}'
            f'<span class="dr-key">{esc(key_words(r.get("key") or "", r.get("destination")))}'
            f'</span><span class="dr-val">{esc(value_text(r))}</span>'
            f'<span class="dr-yr">{esc(year)}</span>'
            f'<span class="dr-book">{esc(book_text(r))}</span>'
            f'<span class="dr-grade">{esc(r.get("evidence") or "ungraded")}</span></div>'
            f'{quote}<div class="dr-src">{source}</div>{why}</div>')


# --- Streamlit -------------------------------------------------------------------------

def _post(post_json, api_base: str, path: str, payload: dict | None) -> str | None:
    """The POST, or the API's reason it refused."""
    try:
        post_json(api_base, path, payload or {})
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8")).get("detail") or str(exc)
        except Exception:
            return str(exc)
    except (urllib.error.URLError, OSError) as exc:
        return str(exc)
    return None


def _edit_form(api_base: str, ticker: str, r: dict, post_json, done) -> None:
    with st.form(f"dr_form_{r['id']}", border=False):
        a, b, c = st.columns([1, 0.7, 2.3], gap="small")
        value = a.number_input("Value", value=r.get("value"), format="%g",
                               key=f"dr_v_{r['id']}")
        year = b.number_input("Year", value=r.get("year"), step=1, format="%d",
                              key=f"dr_y_{r['id']}")
        note = c.text_input("Note", value=re.sub(r"^Incomplete:[^.]*\.\s*", "",
                                                 r.get("note") or ""),
                            key=f"dr_n_{r['id']}")
        if st.form_submit_button("Accept as edited"):
            body = {"value": value, "note": note or None}
            if year is not None:
                body["year"] = int(year)
            error = _post(post_json, api_base,
                          f"/companies/{ticker}/drafts/{r['id']}/accept", body)
            if error:
                st.error(error)
            else:
                st.session_state.pop(f"dr_editing_{ticker}", None)
                done()


def render(api_base: str, ticker: str, get, post_json, done) -> None:
    """The panel, or nothing where no draft waits. ``get`` and ``post_json`` are the
    app's transport; ``done`` clears the caches and reruns the page after a decision,
    since the book and every tab that reads it have changed."""
    try:
        queue = get(api_base, f"/companies/{ticker}/drafts")
    except (urllib.error.URLError, OSError, ValueError):
        return
    head = label(queue)
    if head is None:
        return
    editing = st.session_state.get(f"dr_editing_{ticker}")
    with st.expander(head, expanded=editing is not None):
        for c in queue.get("closings") or []:
            if not c.get("open"):
                continue
            st.markdown(closing_head_html(c), unsafe_allow_html=True)
            for r in c.get("rows") or []:
                body, act = st.columns([5.2, 1.3], gap="small",
                                       vertical_alignment="center")
                body.markdown(row_html(r), unsafe_allow_html=True)
                if r.get("status") not in OPEN:
                    continue
                with act:
                    yes, edit, no = st.columns(3, gap="small")
                    if yes.button("Accept", key=f"dr_a_{r['id']}",
                                  disabled=r.get("status") == "incomplete",
                                  help="an incomplete row needs an edit first"
                                  if r.get("status") == "incomplete" else None):
                        error = _post(post_json, api_base,
                                      f"/companies/{ticker}/drafts/{r['id']}/accept", None)
                        if error:
                            st.error(error)
                        else:
                            done()
                    if edit.button("Edit", key=f"dr_e_{r['id']}"):
                        st.session_state[f"dr_editing_{ticker}"] = (
                            None if editing == r["id"] else r["id"])
                        st.rerun()
                    if no.button("Reject", key=f"dr_r_{r['id']}"):
                        error = _post(post_json, api_base,
                                      f"/companies/{ticker}/drafts/{r['id']}/reject", None)
                        if error:
                            st.error(error)
                        else:
                            done()
                if editing == r["id"]:
                    _edit_form(api_base, ticker, r, post_json, done)
