"""Product revenue before the latest three years, from earlier annual reports, no network.

The history read only adds: a year already on file keeps its figure, a hand-entered one
is never touched, and a product the book does not hold is not made an asset from its old
revenue. Lilly's earlier reports name Trulicity as TrulicityMember and tag Endocrinology
beside its products; both are read as they should be.
"""

import db
from fetchers import product_revenue_sec as P


def _book(tmp_path):
    path = str(tmp_path / "h.db")
    db.init(path)
    c = db.get_connection(path)
    c.execute("INSERT INTO companies (id, ticker, name, cik, is_sec_filer)"
              " VALUES (1, 'LLY', 'Eli Lilly', '59478', 1)")
    c.executemany("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                  " VALUES (?, 1, ?, 1)", [(632, "Trulicity"), (616, "Taltz")])
    c.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source,"
              " is_curated) VALUES (616, 2022, 'FY', 2.5e9, 'USD', 'sec_fsds', 0)")
    c.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source,"
              " is_curated) VALUES (632, 2021, 'FY', 6.0e9, 'USD', 'hand', 1)")
    c.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
              " period_end, value) VALUES (1, 'Revenues', 'FY', 2022, '2022-12-31', 28.5e9)")
    c.commit()
    c.close()
    return path


def _row(member, year, value):
    return {"ticker": "LLY", "member": member, "value": value, "unit": "USD",
            "geography": {}, "fiscal_year": year, "form": "10-K", "adsh": "0000059478-23-000007"}


def test_the_history_adds_years_and_never_overwrites_or_creates(tmp_path):
    path = _book(tmp_path)
    got = P.ProductRevenueHistoryFetcher(path).upsert([
        _row("TrulicityMember", 2022, 7.44e9),      # matched with the suffix taken off
        _row("TrulicityMember", 2021, 6.47e9),      # a hand-entered year stands
        _row("Taltz", 2022, 2.48e9),                # a year on file keeps its figure
        _row("Taltz", 2021, 2.21e9),
        _row("Cymbalta", 2022, 0.28e9)])            # no such product in the book
    c = db.get_connection(path)
    on_file = {(r["asset_id"], r["fiscal_year"]): (r["value"], r["note"]) for r in c.execute(
        "SELECT asset_id, fiscal_year, value, note FROM asset_revenue")}
    assert on_file[(632, 2022)][0] == 7.44e9 and P.HISTORY_NOTE in on_file[(632, 2022)][1]
    assert on_file[(632, 2021)][0] == 6.0e9
    assert on_file[(616, 2022)][0] == 2.5e9 and on_file[(616, 2021)][0] == 2.21e9
    assert c.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2
    assert got.rows_fetched == 2


def test_a_member_suffix_and_a_therapeutic_area_are_read_for_what_they_are():
    assert P.display_name("TrulicityMember") == "Trulicity"
    assert P.display_name("Member") == "Member"
    assert P.is_aggregate("Endocrinology") and P.is_aggregate("Oncology")
    assert not P.is_aggregate("Trulicity")


def test_the_history_reads_the_reports_filed_in_three_years_newest_first():
    assert P.HISTORY_FILED == (2023, 2020, 2017)
    asked = []

    class Spy(P.ProductRevenueHistoryFetcher):
        def _annual_rows(self, quarters):
            asked.append(quarters)
            return []
    Spy(None).fetch()
    assert asked == [["2023q2", "2023q1"], ["2020q2", "2020q1"], ["2017q2", "2017q1"]]
