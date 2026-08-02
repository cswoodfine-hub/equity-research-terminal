"""Reading a priority review voucher sale out of the filing that reports it.

Every sentence here is from a filing in the universe. The hard part is not finding the
word: a cash flow statement names the voucher beside four other figures, and a company
restates one sale in three consecutive reports.
"""

import pytest

import db
import vouchers

ABEONA = ("Abeona closed the sale of its Rare Pediatric Disease priority review voucher "
          "(PRV) for gross proceeds of $155 million.")
BIOGEN = ("We received a net cash payment of $88.6 million from the sale of our rare "
          "pediatric disease PRV in December 2024.")
KRYSTAL = ("The proceeds of $100.0 million from the sale of the PRV were recorded as a "
           "gain in August 2023.")
# The trap. One sentence, a voucher, a sale, and four figures none of which is the price.
CASHFLOW = ("Net cash provided by investing activities for the year ended December 31, "
            "2023 was $82.6 million and consisted of $503.2 million received from "
            "maturities of investments and the gain on sale of priority review voucher "
            "of $100.0 million.")


def test_reads_the_sale_that_started_this():
    got = vouchers.sales(ABEONA, "2025-08")
    assert len(got) == 1
    assert got[0]["gross_usd"] == pytest.approx(155e6)
    assert got[0]["net_usd"] is None      # the filing said gross, so only gross is stored


def test_a_net_payment_is_stored_as_net():
    got = vouchers.sales(BIOGEN, "2025-02")
    assert len(got) == 1
    assert got[0]["net_usd"] == pytest.approx(88.6e6)
    assert got[0]["gross_usd"] is None


def test_a_bare_price_is_read_as_gross():
    """"proceeds of $100.0 million" says nothing about fees, and a figure a seller
    announces is before them."""
    got = vouchers.sales(KRYSTAL, "2023-09")
    assert got[0]["gross_usd"] == pytest.approx(100e6)


def test_a_cash_flow_roll_up_is_not_a_sale():
    """It names the voucher and says "sale" and carries the right figure among three
    wrong ones. The press release reports the same sale plainly, so this is left alone
    rather than parsed at odds of one in four."""
    assert vouchers.sales(CASHFLOW, "2024-02") == []


def test_a_voucher_merely_held_is_not_a_sale():
    text = ("Upon approval the Company was awarded a rare pediatric disease priority "
            "review voucher. Cash and equivalents were $226.0 million.")
    assert vouchers.sales(text, "2025-08") == []


def test_a_figure_outside_what_a_voucher_sells_for_is_refused():
    """The guard against reading the quarter's cash as the price."""
    text = ("The Company sold its priority review voucher and reported proceeds of "
            "$14.3 billion for the period.")
    assert vouchers.sales(text, "2026-08") == []


def test_a_sale_with_no_figure_is_not_stored():
    text = "In April 2026 the Company entered into an agreement to sell the PRV."
    assert vouchers.sales(text, "2026-05") == []


def test_one_sale_restated_three_times_is_one_sale():
    """Abeona announced 155.0m gross in May, then restated a 152.4m net gain in the
    September and December reports. One voucher, three statements, both figures."""
    merged = vouchers.merge([
        {"month": "2025-05", "gross_usd": 155e6, "net_usd": None, "evidence": "a"},
        {"month": "2025-09", "gross_usd": None, "net_usd": 152.4e6, "evidence": "b"},
        {"month": "2025-12", "gross_usd": None, "net_usd": 152.4e6, "evidence": "c"},
    ])
    assert len(merged) == 1
    assert merged[0]["gross_usd"] == pytest.approx(155e6)
    assert merged[0]["net_usd"] == pytest.approx(152.4e6)
    assert merged[0]["month"] == "2025-05"      # when the money arrived


def test_two_vouchers_years_apart_stay_two():
    """Sarepta has sold more than one. Same price, different sale."""
    merged = vouchers.merge([
        {"month": "2020-02", "gross_usd": 102e6, "net_usd": None, "evidence": "a"},
        {"month": "2023-06", "gross_usd": 102e6, "net_usd": None, "evidence": "b"},
    ])
    assert len(merged) == 2


def _seed(tmp_path, text, filed="2026-06-30"):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'RCKT', 'Rocket')")
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "                             section, char_count, text)"
        " VALUES (1, 'acc', '8-K', ?, 'exhibit', ?, ?)", (filed, len(text), text))
    conn.commit()
    conn.close()
    return path


def test_build_writes_and_is_rebuilt_not_appended(tmp_path):
    path = _seed(tmp_path, "In June 2026 the Company closed the sale of its priority "
                           "review voucher for gross proceeds of $180.0 million.")
    assert vouchers.build(path)["written"] == 1
    assert vouchers.build(path)["written"] == 1        # not two
    conn = db.get_connection(path)
    row = conn.execute("SELECT sold_month, gross_usd FROM priority_review_vouchers"
                       ).fetchone()
    assert row["sold_month"] == "2026-06"
    assert row["gross_usd"] == pytest.approx(180e6)
    conn.close()


def test_a_sale_before_the_balance_sheet_is_not_added_to_it(tmp_path):
    """Abeona's voucher closed in May 2025 and its March 2026 cash figure already
    contains it. Adding it again would count the same money twice."""
    path = _seed(tmp_path, "In May 2025 the Company closed the sale of its priority "
                           "review voucher for gross proceeds of $155 million.")
    vouchers.build(path)
    conn = db.get_connection(path)
    assert vouchers.since_balance_sheet(conn, 1, "2026-03-31")["total"] is None
    assert vouchers.since_balance_sheet(conn, 1, "2025-03-31")["total"] == pytest.approx(155e6)
    conn.close()


def test_the_net_figure_is_preferred_where_both_are_known(tmp_path):
    """What reached the bank is the net one."""
    path = _seed(tmp_path, "In June 2026 the Company sold its priority review voucher "
                           "for gross proceeds of $180.0 million. The Company received "
                           "net proceeds of $174.0 million from the sale of the PRV.")
    vouchers.build(path)
    conn = db.get_connection(path)
    assert vouchers.since_balance_sheet(conn, 1, "2026-03-31")["total"] == pytest.approx(174e6)
    conn.close()
