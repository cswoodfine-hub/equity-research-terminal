"""A curated biologic LOE row survives a refresh.

The table has carried an is_curated column since it was created and the writer never
consulted it: every run re-derived the row and overwrote whatever an analyst had set.
Keytruda's 10-K names 2029 patent expiries in the same sentence that says biosimilar
competition could begin in December 2028, and the reader took the patents. The curated
row says 2028, and it has to still say 2028 after the next daily refresh.
"""

import biologic_loe
import db


def _seed(tmp_path):
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'MRK', 'Merck')")
    for asset_id, brand in ((1, "Curated"), (2, "Derived")):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                     " is_marketed) VALUES (?, 1, ?, 'biologic', 1)", (asset_id, brand))
        conn.execute("INSERT INTO approvals (asset_id, approval_date) VALUES (?, '2014-09-04')",
                     (asset_id,))
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value)"
                     " VALUES (?, 2025, 'FY', 1e9)", (asset_id,))
    conn.execute("""INSERT INTO biologic_loe (asset_id, loe_year, loe_date, basis, floor_year,
                    disclosed_year, evidence, is_curated)
                    VALUES (1, 2028, '2028-12-31', '10-K disclosure', 2026, 2028,
                            'biosimilar competition could begin in December 2028', 1)""")
    # A wrong year on a row nobody curated, so the writer can be seen to run.
    conn.execute("""INSERT INTO biologic_loe (asset_id, loe_year, loe_date, basis, floor_year,
                    is_curated) VALUES (2, 2099, '2099-06-30', 'statutory floor', 2099, 0)""")
    conn.commit()
    conn.close()
    return path


def test_a_refresh_leaves_the_curated_row_and_rewrites_the_other(tmp_path):
    path = _seed(tmp_path)
    biologic_loe.derive(path, complete=lambda system, user, max_tokens: '{"findings": []}')
    conn = db.get_connection(path)
    rows = {r["asset_id"]: dict(r) for r in conn.execute(
        "SELECT asset_id, loe_year, loe_date, basis, is_curated FROM biologic_loe")}
    conn.close()
    assert rows[1]["loe_year"] == 2028 and rows[1]["loe_date"] == "2028-12-31"
    assert rows[1]["basis"] == "10-K disclosure" and rows[1]["is_curated"] == 1
    assert rows[2]["loe_year"] == 2026                 # 2014 plus the 12-year floor
    assert rows[2]["basis"] == "statutory floor"
