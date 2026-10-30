"""The PMDA's list of approved new drugs, read into first Japanese approvals and the
re-examination floor under a Japanese region. Fixtures are cut from the list's page and
from the PDF's text as ``jp_approvals.text_of`` extracts it, both styles of date; no
network."""

from pathlib import Path

import db
import jp_approvals
import regional_loe as R
from fetchers.approvals_pmda import PmdaApprovalsFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _rows():
    return jp_approvals.parse((FIXTURES / "pmda_approved_list.txt").read_text())


def test_the_page_links_the_list_and_the_span_it_covers():
    got = jp_approvals.release_link((FIXTURES / "pmda_list_page.html").read_text())
    assert got == ("https://www.pmda.go.jp/files/000281190.pdf",
                   "April 2004 to February 2026")
    assert jp_approvals.release_link("<p>no list today</p>") is None


def test_rows_carry_their_date_and_what_the_note_says():
    rows = _rows()
    assert len(rows) == 11
    nexium = next(r for r in rows if "Nexium" in r["entry"])
    assert nexium["approved_on"] == "2024-06-24" and nexium["is_new_ingredient"] == 0
    # Fabhalta: a new active ingredient in June 2024, then a new indication in May 2025
    # that is an orphan drug, which says nothing about the ingredient.
    fabhalta = [r for r in rows if "Fabhalta" in r["entry"]]
    assert [(r["approved_on"], r["is_new_ingredient"], r["is_orphan"]) for r in fabhalta] \
        == [("2025-05-19", 0, 1), ("2024-06-24", 1, 0)]
    # The 2005 table writes its dates day first and short.
    actemra = next(r for r in rows if "Actemra" in r["entry"])
    assert actemra["approved_on"] == "2005-04-11"
    assert actemra["is_new_ingredient"] == 1 and actemra["is_orphan"] == 1
    # A heading ends the row before it, so no row runs into the next table.
    assert not any("Table-18" in r["entry"] for r in rows)


def _db(tmp_path):
    path = str(tmp_path / "jp.db")
    db.init(path)
    fetcher = PmdaApprovalsFetcher(path)
    fetcher._release = {"url": "https://www.pmda.go.jp/files/000281190.pdf",
                        "label": "April 2004 to February 2026", "new": True}
    fetcher.upsert(_rows())
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ROG', 'Roche')")
    conn.executemany(
        "INSERT INTO assets (id, owner_company_id, brand_name, generic_name, is_marketed)"
        " VALUES (?, 1, ?, ?, 1)",
        [(1, "Vabysmo", "Faricimab-Svoa"), (2, "Actemra", "Tocilizumab"),
         (3, "Zefix", "Lamivudine"), (4, "Ocrevus", "Ocrelizumab")])
    conn.commit()
    return path, conn


def test_a_release_once_read_is_recorded_and_rows_are_never_doubled(tmp_path):
    path, conn = _db(tmp_path)
    assert conn.execute("SELECT entries FROM jp_approval_releases").fetchone()[0] == 11
    PmdaApprovalsFetcher(path).upsert(_rows())
    assert conn.execute("SELECT COUNT(*) FROM jp_approvals").fetchone()[0] == 11


def test_the_first_approval_is_the_earliest_row_and_must_be_the_new_ingredient(tmp_path):
    _, conn = _db(tmp_path)
    # Faricimab: the FDA's suffix is dropped, and the 2022 approval is its first.
    assert R.first_jp_approval(conn, 1) == {"date": "2022-03-28", "orphan": False}
    assert R.first_jp_approval(conn, 2) == {"date": "2005-04-11", "orphan": True}
    # Lamivudine's only row is a new indication: its first approval predates the list.
    assert R.first_jp_approval(conn, 3) is None
    assert R.first_jp_approval(conn, 4) is None


def test_a_japanese_region_carries_the_re_examination_floor(tmp_path):
    _, conn = _db(tmp_path)
    for asset_id, value in ((1, 4000e6), (2, 3000e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                     " is_curated) VALUES (?, 2025, 'FY', ?, 'CHF', 0)", (asset_id, value))
        for member, region, share in (("US", "US", 0.6), ("Japan", "JP", 0.1),
                                      ("Europe", "EU", 0.3)):
            conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member,"
                         " region, value, unit, source) VALUES (?, 2025, ?, ?, ?, 'CHF', 'x')",
                         (asset_id, member, region, value * share))
    conn.commit()
    empty = tmp_path / "none.csv"
    empty.write_text("ticker,brand,region,loe,basis,accession,quote,note\n")
    regions = {r["region"]: r for r in R.for_asset(conn, 1, disclosed_path=empty)}
    assert regions["JP"]["floor_year"] == 2030
    assert "8 years from first approval as a new active ingredient on 2022-03-28" \
        in regions["JP"]["floor_basis"]
    assert "cap_year" not in regions["JP"]
    # Ten years for an orphan drug.
    regions = {r["region"]: r for r in R.for_asset(conn, 2, disclosed_path=empty)}
    assert regions["JP"]["floor_year"] == 2015 and "(orphan drug)" in regions["JP"]["floor_basis"]
    # A stated Japanese date before the floor is pushed to it, as Europe's is.
    stated = tmp_path / "stated.csv"
    stated.write_text("ticker,brand,region,loe,basis,accession,quote,note\n"
                      "ROG,Vabysmo,JP,2028,compound patent,a,\"q\",\n")
    regions = {r["region"]: r for r in R.for_asset(conn, 1, disclosed_path=stated)}
    assert regions["JP"]["year"] == 2030
