"""Drafts waiting on the Forecast tab (frontend/drafts_panel.py) and the Universe tab's
"not in the model" tag on an acquisition story (frontend/universe_cc.py).

The builders are pure functions of ``GET /companies/{t}/drafts`` and ``GET /drafts``, so
they are run on payloads shaped as the API returns them: the panel is absent where no row
waits and one line with the count where some do; a row shows its value with its unit and
year against the book's, its quote and source, its grade and its status, and an
incomplete row says why it is held. The tag goes on a deal story that names a target with
rows still open, and on nothing else. Every string a reader sees keeps the house style.
"""

from __future__ import annotations

import pathlib
import re
import sys

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import drafts_panel as DP  # noqa: E402
import universe_cc as UC  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


def _queue(**row):
    base = {"id": 7, "destination": "assumptions", "asset_id": 10, "key":
            "revenue_ceiling_musd", "value": 1100.0, "text_value": None, "unit": "mm USD",
            "year": None, "source": "Soleno Therapeutics, Inc. SC 14D9, accession "
            "0001193125-26-162853, management projections",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1484565/x.htm",
            "quote": "Revenue, 2034: 1,100 (amounts in millions)", "evidence": "filed",
            "note": "management's peak, 2034.", "existing_value": None,
            "existing_text": None, "status": "draft", "asset_name": "Vykat Xr",
            "new_product": False}
    base.update(row)
    closing = {"id": 1, "target": "Soleno Therapeutics, Inc.", "closing_date": "2026-05-18",
               "trigger_kind": "8-K item 2.01",
               "trigger_url": "https://www.sec.gov/Archives/edgar/data/914475/d8k.htm",
               "target_status": "public", "note": None,
               "context": {"consideration": {"cash": 2.9e9,
                                             "cvr_quote": "one contingent value right"}},
               "rows": [base], "open": 1 if base["status"] in DP.OPEN else 0}
    return {"ticker": "NBIX", "closings": [closing], "open": closing["open"]}


def _style(text: str) -> None:
    low = re.sub(r"<[^>]+>", " ", text).lower()
    assert "—" not in text
    assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)]


def test_the_panel_is_absent_without_drafts_and_one_line_with_them():
    assert DP.label({"ticker": "NBIX", "closings": [], "open": 0}) is None
    assert DP.label(None) is None
    assert DP.label(_queue()) == "Drafts waiting · 1 row from 1 closing"
    q = _queue()
    q["closings"][0]["rows"].append(dict(q["closings"][0]["rows"][0], id=8))
    q["open"] = q["closings"][0]["open"] = 2
    assert DP.label(q) == "Drafts waiting · 2 rows from 1 closing"


def test_a_row_shows_value_year_book_quote_source_grade_and_status():
    row = _queue(existing_value=950.0)["closings"][0]["rows"][0]
    out = DP.row_html(row)
    assert "1,100 mm USD" in out and ">2034<" in out and "book: 950 mm USD" in out
    assert "&#8220;Revenue, 2034: 1,100 (amounts in millions)&#8221;" in out
    assert 'href="https://www.sec.gov/Archives/edgar/data/1484565/x.htm"' in out
    assert ">filed<" in out and ">draft<" in out and "revenue ceiling" in out
    assert DP.book_text({"key": "pos"}) == "not in the book"
    _style(out)


def test_values_read_as_a_reader_takes_them_and_nothing_missing_is_a_zero():
    assert DP.value_text({"key": "cogs_pct", "value": 0.04}) == "4.0%"
    assert DP.value_text({"key": "pos", "value": 1.0}) == "100.0%"
    assert DP.value_text({"key": "beta", "value": 0.734}) == "0.73"
    assert DP.value_text({"key": "therapy_mode", "text_value": "launch"}) == "launch"
    assert DP.value_text({"key": "base_revenue", "value": None}) == "no free data"
    assert DP.value_text({"key": "revenue_growth_pct", "value": 0.215,
                          "unit": "annual, near term"}) == "21.5%"


def test_an_incomplete_row_says_why_it_is_held():
    row = _queue(status="incomplete", note="Incomplete: the filed figure is Soleno's "
                 "whole business, not Vykat Xr alone. management's peak, 2034.")
    out = DP.row_html(row["closings"][0]["rows"][0])
    assert "Held: the filed figure is Soleno&#x27;s whole business, not Vykat Xr alone." in out
    assert "s-incomplete" in out
    _style(out)


def test_a_new_product_is_marked_and_a_claim_row_reads_as_cash_paid():
    out = DP.row_html(_queue(asset_id=None, new_product=True)["closings"][0]["rows"][0])
    assert "new to the book" in out
    claim = DP.row_html(_queue(destination="other_claims", key="pending_acquisition_x",
                               value=2900.0, asset_name=None)["closings"][0]["rows"][0])
    assert "cash paid, held as a claim" in claim and "2,900 mm USD" in claim


def test_the_closing_line_carries_its_filing_and_what_was_paid():
    out = DP.closing_head_html(_queue()["closings"][0])
    assert "Soleno Therapeutics, Inc." in out and "closed 2026-05-18" in out
    assert 'href="https://www.sec.gov/Archives/edgar/data/914475/d8k.htm"' in out
    assert "$2.9bn cash and a contingent value right" in out
    _style(out)


def _drafts(open_rows=3):
    return [{"ticker": "NBIX", "deals": [
        {"id": 1, "target": "Soleno Therapeutics, Inc.", "target_key": "soleno therapeutics",
         "closing_date": "2026-05-18", "open_rows": open_rows}]}]


def _deal(head, tickers=("NBIX",), kind="deal"):
    return {"kind": kind, "tickers": list(tickers), "head": head, "date": "2026-05-18"}


def test_an_acquisition_story_with_open_drafts_is_tagged():
    p = {"drafts": _drafts()}
    assert UC.not_in_model(p, _deal("Neurocrine completes acquisition of Soleno"))
    assert UC.NOT_IN_MODEL in UC._nim(p, _deal("Neurocrine completes acquisition of Soleno"))


def test_no_tag_without_open_rows_another_target_another_company_or_another_kind():
    story = _deal("Neurocrine completes acquisition of Soleno")
    assert not UC.not_in_model({"drafts": _drafts(0)}, story)
    assert not UC.not_in_model({"drafts": _drafts()}, _deal("Neurocrine licenses a drug"))
    assert not UC.not_in_model({"drafts": _drafts()}, dict(story, tickers=["INCY"]))
    assert not UC.not_in_model({"drafts": _drafts()}, dict(story, kind="filing"))
    assert not UC.not_in_model({}, story)
    assert UC._nim({}, story) == ""
