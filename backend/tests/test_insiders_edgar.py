"""Insider transactions from Form 4: the parser, the idempotent store and the summary.

Fixtures are live EDGAR payloads captured on 2026-11-23, no network here:

  edgar_form4_vktx_award_option.xml    a director's award: one share line, one option line
  edgar_form4_dyn_sale_10b5_1.xml      an officer's sale with the Rule 10b5-1 box ticked
  edgar_form4_azn_purchase.xml         a foreign issuer's officer; flags printed 1 and 0
  edgar_form4_lly_award.xml            a form that was later amended
  edgar_form4a_lly_award_amended.xml   the 4/A that amended it
  edgar_form4_gsk_holder_of_wve.xml    on GSK's filing list, about Wave's shares
  edgar_submissions_dyn_form4.json     the first 30 rows of Dyne's filing list
"""

import json
import pathlib

import pytest

import db
import insiders
from fetchers import insiders_edgar as IE

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DYN_CIK = "0001818794"


def _xml(name):
    return (FIXTURES / name).read_text()


def _filing(accession, filed="2026-11-16", form="4", accepted=None):
    return {"accession": accession, "form_type": form, "filed_date": filed,
            "accepted_at": accepted, "url": f"https://example.test/{accession}.xml"}


def _database(tmp_path, *companies):
    path = str(tmp_path / "insiders.db")
    db.init(path)
    conn = db.get_connection(path)
    for company_id, ticker, cik in companies:
        conn.execute("INSERT INTO companies (id, ticker, name, cik) VALUES (?, ?, ?, ?)",
                     (company_id, ticker, ticker, cik))
    conn.commit()
    conn.close()
    return path


def _count(path, sql, *args):
    conn = db.get_connection(path)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


# --- the filing list ------------------------------------------------------------------
def test_the_raw_xml_is_the_listed_document_without_its_stylesheet_directory():
    assert IE.raw_document("xslF345X06/ownership.xml") == "ownership.xml"
    assert IE.raw_document("xslF345X05/wk-form4a_1770931366.xml") == "wk-form4a_1770931366.xml"
    assert IE.raw_document("xslF345X03/doc4.xml") == "doc4.xml"
    assert IE.raw_document("primary_doc.xml") == "primary_doc.xml"
    # Nothing a parser can read: a paper filing lists no document, an old one a text file.
    assert IE.raw_document("") is None and IE.raw_document("form4.txt") is None
    assert IE.document_url(DYN_CIK, "0001915598-26-000007", "xslF345X06/ownership.xml") == (
        "https://www.sec.gov/Archives/edgar/data/1818794/000191559826000007/ownership.xml")


def test_the_list_keeps_the_form_4s_newest_first_and_stops_at_the_lookback():
    payload = json.loads(_xml("edgar_submissions_dyn_form4.json"))
    rows = IE.list_form4s(payload, payload["cik"])
    # 30 filings on the list: 14 Form 4s among the 144s, the 8-Ks, a 10-Q and a 13G.
    assert len(rows) == 14 and {r["form_type"] for r in rows} == {"4"}
    assert rows[0]["accession"] == "0001915598-26-000007"
    assert rows[0]["filed_date"] == "2026-11-16"
    assert rows[0]["accepted_at"] == "2026-11-16T21:11:03.000Z"
    assert rows[0]["url"].endswith("/1818794/000191559826000007/ownership.xml")
    assert [r["filed_date"] for r in rows] == sorted(
        (r["filed_date"] for r in rows), reverse=True)
    recent = IE.list_form4s(payload, payload["cik"], since="2026-11-01")
    assert [r["filed_date"] for r in recent] == ["2026-11-16"] * 4
    assert IE.list_form4s({}, DYN_CIK) == []


# --- the ownership document -----------------------------------------------------------
def test_an_award_reads_as_a_share_line_then_an_option_line():
    doc = IE.parse_ownership(_xml("edgar_form4_vktx_award_option.xml"))
    assert doc["form_type"] == "4" and doc["issuer_cik"] == "0001607678"
    assert doc["owner_name"] == "Kelly-Gemmell Dorothy Elizabeth"
    assert doc["owner_cik"] == "0002144542" and doc["other_owners"] is None
    # This agent prints the boxes as true and false.
    assert (doc["is_director"], doc["is_officer"], doc["is_ten_percent_owner"]) == (1, 0, 0)
    assert doc["officer_title"] is None and doc["plan_10b5_1"] == 0

    rows = IE.transaction_rows(doc, _filing("0002144542-26-000004", "2026-08-07"))
    assert [(r["row_index"], r["is_derivative"]) for r in rows] == [(0, 0), (1, 1)]
    share, option = rows
    assert share["security_title"] == "Common Stock, par value $0.00001 per share"
    assert (share["transaction_date"], share["transaction_code"]) == ("2026-08-01", "A")
    # The form states a price of nothing for an award. That is a stated zero, kept.
    assert (share["shares"], share["price_per_share"]) == (6333.0, 0.0)
    assert (share["acquired_disposed"], share["ownership"]) == ("A", "D")
    assert share["shares_owned_after"] == 6333.0
    assert share["exercise_price"] is None and share["underlying_shares"] is None
    assert share["footnotes"].startswith("F1: Represents a restricted stock unit award")

    assert option["security_title"] == "Stock Option (Right to Buy)"
    assert (option["shares"], option["exercise_price"]) == (40800.0, 31.74)
    assert (option["underlying_title"], option["underlying_shares"]) == (
        "Common Stock", 40800.0)
    # A row carries only the footnotes it cites: F2 hangs off the option's vesting date.
    assert option["footnotes"].startswith("F2: One-third") and "F1" not in option["footnotes"]
    assert option["filed_date"] == "2026-08-07" and option["form_type"] == "4"


def test_a_sale_carries_the_forms_10b5_1_box_and_the_footnotes_behind_its_price():
    doc = IE.parse_ownership(_xml("edgar_form4_dyn_sale_10b5_1.xml"))
    assert doc["plan_10b5_1"] == 1 and doc["is_officer"] == 1
    (row,) = IE.transaction_rows(doc, _filing("0001915598-26-000007"))
    assert (row["transaction_code"], row["acquired_disposed"]) == ("S", "D")
    assert (row["shares"], row["price_per_share"]) == (231.0, 16.82)
    assert row["shares_owned_after"] == 152666.0 and row["plan_10b5_1"] == 1
    assert "weighted average price" in row["footnotes"]
    assert row["footnotes"].count("\n") == 2          # F1, F2 and F3, each once


def test_a_foreign_issuers_form_reads_the_same_with_its_boxes_printed_as_digits():
    doc = IE.parse_ownership(_xml("edgar_form4_azn_purchase.xml"))
    assert doc["issuer_cik"] == "0000901832" and doc["issuer_symbol"] == "AZN"
    assert (doc["is_director"], doc["is_officer"], doc["plan_10b5_1"]) == (0, 1, 0)
    # The title box says "See Remarks", and the remarks are where the title is.
    assert doc["officer_title"] == "SVP, Group Controller and Head of Global Finance Services"
    rows = IE.transaction_rows(doc, _filing("0001104659-26-107055", "2026-09-11"))
    assert [(r["transaction_code"], r["shares"], r["price_per_share"]) for r in rows] == [
        ("P", 20.233, 160.57), ("A", 1.0, 162.6)]
    assert rows[0]["security_title"] == "Ordinary Shares"
    assert rows[0]["shares_owned_after"] == 19287.6989


def test_an_amendment_says_so_and_names_the_filing_it_amends():
    doc = IE.parse_ownership(_xml("edgar_form4a_lly_award_amended.xml"))
    assert doc["form_type"] == "4/A" and doc["original_filed_date"] == "2026-02-11"
    assert doc["officer_title"] == "EVP & CIDO"
    # The filing list is not asked what the form is; the document is.
    (row,) = IE.transaction_rows(doc, _filing("0001860253-26-000006", "2026-02-12", "4"))
    assert row["form_type"] == "4/A" and row["original_filed_date"] == "2026-02-11"
    assert IE.parse_ownership(_xml("edgar_form4_lly_award.xml"))["original_filed_date"] is None


def test_a_field_the_form_leaves_empty_is_null_and_never_a_zero():
    xml = _xml("edgar_form4_dyn_sale_10b5_1.xml")
    priced = "<value>16.82</value>"
    assert priced in xml
    # A price given only in a footnote: the field holds the reference and no value.
    (row,) = IE.parse_ownership(xml.replace(priced, ""))["transactions"]
    assert row["price_per_share"] is None and row["shares"] == 231.0
    assert "weighted average price" in row["footnotes"]
    # A form from before April 2023 has no 10b5-1 box at all.
    old = xml.replace("<aff10b5One>true</aff10b5One>", "")
    assert IE.parse_ownership(old)["plan_10b5_1"] is None


def test_anything_that_is_not_an_ownership_document_is_refused():
    for junk in ("", "<html><body>Rate limit</body></html>", "not xml at all",
                 '<!DOCTYPE x [<!ENTITY a "b">]><ownershipDocument/>'):
        with pytest.raises(ValueError):
            IE.parse_ownership(junk)


# --- the store ------------------------------------------------------------------------
def test_reading_a_filing_twice_writes_the_same_rows_once(tmp_path):
    path = _database(tmp_path, (1, "DYN", DYN_CIK), (2, "VKTX", "0001607678"))
    raw = {"filings": [
        {**_filing("0001915598-26-000007"), "xml": _xml("edgar_form4_dyn_sale_10b5_1.xml")}]}
    fetcher = IE.InsidersEdgarFetcher("DYN", path)
    fetcher._cik = DYN_CIK
    for _ in range(2):
        rows = fetcher.normalise(raw)
        fetcher.snapshot(rows)
        result = fetcher.upsert(rows)
        assert result.rows_fetched == 1 and result.errors == []
    assert _count(path, "SELECT COUNT(*) FROM insider_transactions") == 1
    assert _count(path, "SELECT COUNT(*) FROM insider_filings") == 1
    assert _count(path, "SELECT outcome FROM insider_filings") == "stored"
    assert _count(path, "SELECT plan_10b5_1 FROM insider_transactions") == 1

    # Two lines of one filing are two rows, keyed by their position.
    other = IE.InsidersEdgarFetcher("VKTX", path)
    other._cik = "0001607678"
    award = {"filings": [{**_filing("0002144542-26-000004", "2026-08-07"),
                          "xml": _xml("edgar_form4_vktx_award_option.xml")}]}
    other.upsert(other.normalise(award))
    other.upsert(other.normalise(award))
    assert _count(path, "SELECT COUNT(*) FROM insider_transactions WHERE company_id = 2") == 2
    assert _count(path, "SELECT MIN(row_index) || ',' || MAX(row_index)"
                        " FROM insider_transactions WHERE company_id = 2") == "0,1"


def test_a_form_about_somebody_elses_shares_leaves_a_record_and_no_rows(tmp_path):
    path = _database(tmp_path, (1, "GSK", "0001131399"))
    fetcher = IE.InsidersEdgarFetcher("GSK", path)
    fetcher._cik = "0001131399"
    raw = {"filings": [
        {**_filing("0001999371-25-020336", "2025-12-15"),
         "xml": _xml("edgar_form4_gsk_holder_of_wve.xml")},
        {**_filing("0000000000-26-000001"), "xml": "<html>not a form</html>"},
        {**_filing("0000000000-26-000002"), "xml": None, "missing": "HTTP 404"}]}
    rows = fetcher.normalise(raw)
    assert rows == []
    result = fetcher.upsert(rows)
    assert result.rows_fetched == 0 and len(result.errors) == 2
    assert _count(path, "SELECT COUNT(*) FROM insider_transactions") == 0
    conn = db.get_connection(path)
    held = {r["accession"]: (r["outcome"], r["issuer_cik"]) for r in conn.execute(
        "SELECT accession, outcome, issuer_cik FROM insider_filings")}
    seen = fetcher._already_read(conn, 1)
    conn.close()
    assert held["0001999371-25-020336"] == ("not_issuer", "0001631574")   # Wave
    assert held["0000000000-26-000001"][0] == "unreadable"
    assert held["0000000000-26-000002"][0] == "unreadable"
    # All three are settled: none is asked for again.
    assert seen == set(held)


def test_a_run_reads_up_to_the_cap_and_never_asks_for_a_filing_twice(tmp_path, monkeypatch):
    path = _database(tmp_path, (1, "DYN", DYN_CIK))
    monkeypatch.setenv("SEC_USER_AGENT", "Novatalis Research test@example.com")
    monkeypatch.setattr(IE, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(IE, "LOOKBACK_DAYS", 100000)    # the fixture does not age
    monkeypatch.setattr(IE, "MAX_NEW_FILINGS", 6)
    listing = _xml("edgar_submissions_dyn_form4.json")
    form = _xml("edgar_form4_dyn_sale_10b5_1.xml")
    asked = []

    def serve(self, url, user_agent, limit=None):
        asked.append(url)
        return listing if "submissions" in url else form

    monkeypatch.setattr(IE.InsidersEdgarFetcher, "_get", serve)

    def run(force=True):
        del asked[:]
        fetcher = IE.InsidersEdgarFetcher("DYN", path)
        fetcher.force = force
        return fetcher.run()

    first = run()
    # The list and six forms, newest first, with the rest reported as waiting.
    assert len(asked) == 7 and first.rows_fetched == 6 and first.errors == []
    assert asked[1].endswith("/000191559826000007/ownership.xml")
    assert first.notes and first.notes[0].startswith("DYN: 8 Form 4s")
    assert len(run().notes) == 1 and len(asked) == 7       # six more, two waiting
    third = run()
    assert len(asked) == 3 and third.rows_fetched == 2 and third.notes == []
    # Everything on the list is held: a further run asks for the list and nothing else.
    fourth = run()
    assert asked == [IE.SUBMISSIONS_URL.format(cik=DYN_CIK)]
    assert fourth.rows_fetched == 0 and fourth.errors == []
    assert _count(path, "SELECT COUNT(*) FROM insider_transactions") == 14
    assert _count(path, "SELECT COUNT(*) FROM insider_filings") == 14
    # Inside the TTL nothing is asked at all.
    inside = run(force=False)
    assert inside.skipped_ttl and asked == []


def test_one_form_that_will_not_download_does_not_cost_the_others(tmp_path, monkeypatch):
    path = _database(tmp_path, (1, "DYN", DYN_CIK))
    monkeypatch.setenv("SEC_USER_AGENT", "Novatalis Research test@example.com")
    monkeypatch.setattr(IE, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(IE, "LOOKBACK_DAYS", 100000)
    listing = _xml("edgar_submissions_dyn_form4.json")
    form = _xml("edgar_form4_dyn_sale_10b5_1.xml")

    def serve(self, url, user_agent, limit=None):
        if "submissions" in url:
            return listing
        if "000181418926000009" in url:
            raise TimeoutError("timed out")
        return form

    monkeypatch.setattr(IE.InsidersEdgarFetcher, "_get", serve)
    fetcher = IE.InsidersEdgarFetcher("DYN", path)
    result = fetcher.run()
    assert result.rows_fetched == 13
    assert len(result.errors) == 1 and "0001814189-26-000009" in result.errors[0]
    # Not recorded, so the next run tries it again.
    assert _count(path, "SELECT COUNT(*) FROM insider_filings"
                        " WHERE accession = '0001814189-26-000009'") == 0


# --- the summary ----------------------------------------------------------------------
def _row(owner, code, shares, price, plan=0, director=0, officer=0, ten=0,
         derivative=0, date="2026-10-01", **extra):
    row = {"owner_cik": owner, "owner_name": owner, "transaction_code": code,
           "shares": shares, "price_per_share": price, "plan_10b5_1": plan,
           "is_director": director, "is_officer": officer, "is_ten_percent_owner": ten,
           "is_derivative": derivative, "transaction_date": date, "filed_date": date,
           "security_title": "Common Stock", "form_type": "4", "accession": "a",
           "row_index": 0}
    row.update(extra)
    row["value"] = insiders._value(shares, price)
    return row


def test_purchases_and_sales_are_netted_and_everything_else_is_kept_apart():
    rows = [
        _row("one", "P", 1000, 10.0, director=1),
        _row("one", "P", 500, 12.0, director=1),
        _row("two", "P", 200, None, officer=1),              # no price on the form
        _row("three", "S", 300, 20.0, plan=1, officer=1),
        _row("four", "S", 5000, 21.0, ten=1),                # a holder, not a manager
        _row("three", "S", 100, 19.0, plan=None, officer=1),  # a form with no box
        _row("two", "A", 4000, 0.0, officer=1),
        _row("two", "F", 1500, 20.0, officer=1),
        _row("five", "P", 50, 2.0, derivative=1),            # a warrant, not a share
    ]
    insiders.mark_superseded(rows)
    summary = insiders.summarise(rows)
    market = summary["open_market"]

    bought = market["purchases"]
    assert (bought["transactions"], bought["buyers"]) == (3, 2)
    assert (bought["shares"], bought["value"], bought["unpriced"]) == (1700.0, 16000.0, 1)

    sold = market["sales"]
    assert (sold["transactions"], sold["sellers"]) == (3, 2)
    assert (sold["shares"], sold["value"], sold["unpriced"]) == (5400.0, 112900.0, 0)
    assert (sold["under_10b5_1"]["transactions"], sold["under_10b5_1"]["shares"],
            sold["under_10b5_1"]["value"]) == (1, 300.0, 6000.0)
    assert (sold["not_under_plan"]["transactions"], sold["not_under_plan"]["value"]) == (
        1, 105000.0)
    assert sold["plan_not_stated"] == 1

    assert market["net_shares"] == -3700.0
    assert market["net_value"] == -96900.0

    # Without the ten per cent holder the same window is a net purchase.
    managers = summary["open_market_directors_and_officers"]
    assert (managers["sales"]["transactions"], managers["sales"]["sellers"]) == (2, 1)
    assert (managers["sales"]["shares"], managers["sales"]["value"]) == (400.0, 7900.0)
    assert (managers["net_shares"], managers["net_value"]) == (1300.0, 8100.0)

    other = summary["other"]
    assert other["transactions"] == 3
    assert {(o["code"], o["table"]): (o["transactions"], o["shares"])
            for o in other["by_code"]} == {
        ("A", "non-derivative"): (1, 4000.0), ("F", "non-derivative"): (1, 1500.0),
        ("P", "derivative"): (1, 50.0)}


def test_a_total_with_no_stated_price_is_null_and_a_total_of_nothing_is_zero():
    rows = [_row("two", "P", 200, None, officer=1)]
    assert rows[0]["value"] is None
    market = insiders.summarise(rows)["open_market"]
    assert market["purchases"]["shares"] == 200.0
    assert market["purchases"]["value"] is None and market["purchases"]["unpriced"] == 1
    assert market["sales"]["value"] == 0.0 and market["sales"]["transactions"] == 0
    # Purchases of unknown value less sales of nothing is unknown, not zero.
    assert market["net_value"] is None and market["net_shares"] == 200.0
    empty = insiders.summarise([])["open_market"]
    assert (empty["net_shares"], empty["net_value"]) == (0.0, 0.0)


def test_an_amended_line_is_counted_once_as_the_amendment_states_it():
    first = IE.transaction_rows(
        IE.parse_ownership(_xml("edgar_form4_lly_award.xml")),
        _filing("0001860253-26-000004", "2026-02-11", accepted="2026-02-11T21:22:17.000Z"))
    second = IE.transaction_rows(
        IE.parse_ownership(_xml("edgar_form4a_lly_award_amended.xml")),
        _filing("0001860253-26-000006", "2026-02-12", accepted="2026-02-12T21:22:48.000Z"))
    rows = second + first
    for row in rows:
        row["value"] = insiders._value(row["shares"], row["price_per_share"])
    insiders.mark_superseded(rows)
    assert first[0]["superseded_by"] == "0001860253-26-000006"
    assert second[0]["superseded_by"] is None
    summary = insiders.summarise(rows)
    assert summary["superseded_by_amendment"] == 1
    (award,) = summary["other"]["by_code"]
    assert (award["code"], award["transactions"], award["shares"]) == ("A", 1, 4599.164)

    # An amendment replaces one line each, not every line that looks like it, and
    # nothing in a filing it does not name.
    twin = dict(first[0], row_index=1, superseded_by=None)
    stranger = dict(first[0], accession="x", filed_date="2026-02-05", superseded_by=None)
    rows = second + [dict(first[0], superseded_by=None), twin, stranger]
    insiders.mark_superseded(rows)
    assert [r["superseded_by"] is not None for r in rows] == [False, True, False, False]


def test_the_reading_is_what_was_filed_by_the_day_asked_about(tmp_path):
    path = _database(tmp_path, (1, "DYN", DYN_CIK))
    fetcher = IE.InsidersEdgarFetcher("DYN", path)
    fetcher._cik = DYN_CIK
    raw = {"filings": [{**_filing("0001915598-26-000007", "2026-11-16"),
                        "xml": _xml("edgar_form4_dyn_sale_10b5_1.xml")}]}
    rows = fetcher.normalise(raw)
    fetcher.snapshot(rows)
    fetcher.upsert(rows)

    reading = insiders.for_company(path, "dyn", days=30, as_of="2026-11-20")
    assert reading["ticker"] == "DYN" and reading["window_start"] == "2026-10-21"
    (line,) = reading["transactions"]
    assert (line["transaction_date"], line["filed_date"]) == ("2026-11-13", "2026-11-16")
    assert (line["code"], line["shares"], line["price"], line["value"]) == (
        "S", 231.0, 16.82, 3885.42)
    assert line["role"] == "Officer (Chief Commercial Officer)"
    assert line["plan_10b5_1"] is True and line["derivative"] is False
    sales = reading["summary"]["open_market"]["sales"]
    assert (sales["transactions"], sales["sellers"], sales["value"]) == (1, 1, 3885.42)
    assert sales["under_10b5_1"]["transactions"] == 1
    assert reading["codes"] == {"S": "Open market or private sale"}
    assert reading["coverage"]["filings_with_transactions"] == 1
    assert reading["coverage"]["filings_not_read_yet"] == 0
    assert reading["not_covered"] and not reading["truncated"]

    # Sold on the 13th, filed on the 16th: on the 14th nobody outside could know.
    early = insiders.for_company(path, "DYN", days=30, as_of="2026-11-14")
    assert early["transactions"] == []
    assert early["summary"]["open_market"]["sales"]["transactions"] == 0
    # Outside the window, and a ticker the book does not hold.
    assert insiders.for_company(path, "DYN", days=30, as_of="2027-06-01")["transactions"] == []
    assert insiders.for_company(path, "ZZZZ") is None


def test_each_side_names_who_it_is_biggest_first():
    """Two directors selling for an investor and four officers covering a tax bill are
    different facts, and a single total states neither."""
    rows = [_row("Fund Director", "S", 4_000_000, 24.0, plan=1, director=1),
            _row("Fund Director", "S", 100_000, 25.0, plan=1, director=1),
            _row("Finance Officer", "S", 2_000, 17.0, plan=1, officer=1),
            _row("Board Member", "P", 7_000, 16.8, director=1)]
    rows[0]["ownership"] = "I"
    market = insiders.summarise(rows)["open_market"]
    first, second = market["sales"]["largest"]
    assert first["owner"] == "Fund Director" and first["transactions"] == 2
    assert first["value"] == 98_500_000.0 and first["indirect_shares"] == 4_000_000
    assert first["under_10b5_1"] == 2
    assert second["owner"] == "Finance Officer" and second["indirect_shares"] == 0.0
    (buyer,) = market["purchases"]["largest"]
    assert buyer["owner"] == "Board Member" and buyer["value"] == 117_600.0
    assert insiders.summarise([])["open_market"]["sales"]["largest"] == []
