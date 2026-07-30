"""Money raised after the balance sheet date, and the six things that are not that.

Every sentence here is taken from a filing in the universe. The false positives are the
point: this figure is added to a company's cash, so a wrong row lengthens a runway, and a
runway that is too long is the one direction the error must never run.
"""

import db
import financings
import runway

# Dyne, 10-Q filed 2026-07-29, balance sheet 30 June 2026.
DYNE = ("Recent Events In July 2026, we completed an underwritten public offering, "
        "pursuant to which we issued and sold 21,045,000 shares of our common stock. "
        "We estimate that the net proceeds from the offering were approximately $405.0 "
        "million, after deducting underwriting discounts and commissions and offering "
        "expenses payable by us.")


def test_a_raise_after_the_period_end_is_read():
    rows = financings.raises(DYNE, "2026-06-30", "2026-07-29")
    assert len(rows) == 1
    assert rows[0]["amount"] == 405e6
    assert rows[0]["month"] == "2026-07"
    assert rows[0]["kind"] == "public offering"


def test_a_raise_inside_the_balance_sheet_is_not_added():
    """June money is in a June balance sheet. Adding it would count it twice."""
    assert financings.raises(DYNE, "2026-07-31", "2026-08-15") == []


def test_the_month_of_the_raise_beats_the_month_of_the_balance_sheet():
    """Cabaletta's liquidity sentence names both, and the nearest date to the words "net
    proceeds" is the one the money was not there on."""
    text = ("Our cash and cash equivalents balance of $116.6 million as of March 31, "
            "2026, along with net proceeds of approximately $141.0 million from our May "
            "2026 financing, should enable us to fund our operations into mid-2027.")
    rows = financings.raises(text, "2026-03-31", "2026-05-14")
    assert len(rows) == 1 and rows[0]["month"] == "2026-05"
    assert rows[0]["amount"] == 141e6


def test_a_figure_before_the_phrase_is_read_too():
    """Altimmune writes it the other way round."""
    text = ("In April 2026, we raised approximately $211.2 million in net proceeds from "
            "the issuance of common stock and warrants.")
    assert financings.raises(text, "2026-03-31", "2026-05-13")[0]["amount"] == 211.2e6


def test_gross_proceeds_are_not_net_proceeds():
    """Dyne's raise was 431m gross and 405m net. The difference is real money, and there
    is no free way to know the fee, so a gross-only statement is skipped."""
    text = ("In July 2026, we completed an underwritten public offering. The gross "
            "proceeds from the offering were approximately $431 million.")
    assert financings.raises(text, "2026-06-30", "2026-07-29") == []


def test_a_figure_far_from_the_phrase_is_some_other_number():
    """Dyne's quarterly R&D expense sat in the same two sentences as its proceeds and was
    read as a raise."""
    text = ("Research and development expenses were $152.2 million for the three months "
            "ended June 30, 2026, an increase driven by manufacturing activity and "
            "clinical costs across our programmes in July 2026 and beyond. "
            "We describe the net proceeds elsewhere in this report.")
    assert financings.raises(text, "2026-06-30", "2026-07-29") == []


def test_a_plan_to_spend_the_proceeds_is_not_a_raise():
    """Allogene's "we expect to use the net proceeds" paired with an unrelated figure."""
    text = ("We expect to use the net proceeds from the April 2026 Public Offering for "
            "general corporate purposes, including $12.9 million of clinical expenses.")
    assert financings.raises(text, "2026-03-31", "2026-05-13") == []


def test_a_closed_quarter_is_already_on_the_balance_sheet():
    """Cabaletta's ATM sales in Q1 are inside its 31 March cash, and the sentence after
    them named May, which is what let them through."""
    text = ("During the first quarter of 2026, we sold 8,055,260 shares pursuant to the "
            "2025 ATM Program for net proceeds of $22.6 million. May 2026 Financing In "
            "May 2026 we did other things.")
    assert financings.raises(text, "2026-03-31", "2026-05-14") == []


def test_an_aggregate_since_inception_is_not_a_raise():
    text = ("Since our inception through March 31, 2026, we have raised an aggregate net "
            "proceeds of $852.8 million, most recently in April 2026.")
    assert financings.raises(text, "2026-03-31", "2026-05-07") == []


def test_nothing_closes_after_the_filing_that_reports_it():
    """Sanofi's bond tranches mature between 2028 and 2032, and the maturity read as a
    closing date until the filing date bounded it."""
    text = ("On October 28, 2025, we placed a bond issue and received net proceeds of "
            "$3,000.0 million across five tranches maturing in November 2032.")
    assert financings.raises(text, "2025-12-31", "2026-03-20") == []


def test_one_raise_stated_twice_is_one_row():
    """An 8-K states the proceeds before the underwriters' option is exercised and after.
    Both are true and only one of them is the money."""
    text = ("In July 2026, we completed an offering with net proceeds of approximately "
            "$352.1 million. The net proceeds were approximately $405.0 million if the "
            "underwriters exercise their option in full, in July 2026.")
    rows = financings.raises(text, "2026-06-30", "2026-07-29")
    assert len(rows) == 1


def test_no_balance_sheet_date_reads_nothing():
    assert financings.raises(DYNE, "") == []


# --- against the database --------------------------------------------------------------

def _company(tmp_path, text, cash_date="2026-06-30", filed="2026-07-29"):
    path = str(tmp_path / "f.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('DYN', 'Dyne')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, unit) VALUES (?, 'CashAndEquivalents', 898475000,"
                 "  ?, 'instant', 'USD')", (cid, cash_date))
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, fiscal_year, unit) VALUES (?, 'CashFlowOperating',"
                 "  -477819000, ?, 'FY', 2025, 'USD')", (cid, cash_date))
    conn.execute("INSERT INTO filing_sections (company_id, accession, form_type,"
                 "  filed_date, section, char_count, text)"
                 "  VALUES (?, '0001-1', '10-Q', ?, 'mdna', ?, ?)",
                 (cid, filed, len(text), text))
    conn.commit()
    return path, conn, cid


def test_build_writes_the_raise_and_runway_counts_it(tmp_path):
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()

    assert financings.build(path)["written"] == 1

    conn = db.get_connection(path)
    money = runway.liquidity(conn, cid)
    conn.close()
    assert money["cash"] == 898475000            # the balance sheet is untouched
    assert money["raised_since"] == 405e6
    assert money["available"] == 898475000 + 405e6
    assert money["raises"][0]["kind"] == "public offering"


def test_the_raise_drops_out_once_the_balance_sheet_catches_up(tmp_path):
    """The Q3 statements will include the July raise. Counting it again would double it,
    so the stored row is checked against the balance sheet date rather than trusted."""
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()
    financings.build(path)

    conn = db.get_connection(path)
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, unit) VALUES (?, 'CashAndEquivalents', 1200000000,"
                 "  '2026-09-30', 'instant', 'USD')", (cid,))
    conn.commit()
    money = runway.liquidity(conn, cid)
    conn.close()
    assert money["as_of"] == "2026-09-30"
    assert money["raised_since"] is None
    assert money["available"] == 1200000000


def test_build_replaces_rather_than_accumulates(tmp_path):
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()
    financings.build(path)
    financings.build(path)

    conn = db.get_connection(path)
    count = conn.execute("SELECT COUNT(*) FROM financings").fetchone()[0]
    conn.close()
    assert count == 1


def test_a_company_with_no_cash_line_reads_nothing(tmp_path):
    path = str(tmp_path / "n.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('X', 'X')")
    conn.commit()
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    money = runway.liquidity(conn, cid)
    conn.close()
    assert money["available"] is None and money["raises"] == []
