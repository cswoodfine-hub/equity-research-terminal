"""The Part D coverage lane of the diff (diff._diff_payer_access).

A brand's share of Part D formularies listing it, requiring prior authorisation and
requiring step therapy is anchored in market_signal_state; a change is written only when
a share moves 10 points from where it was last flagged. The coverage snapshots are the
ones the formulary fetcher writes, one per asset per release; Mounjaro's prior
authorisation count of 310 of 312 is its row in the 2026-09-16 release.
"""

from __future__ import annotations

import json

import db
import diff
import market_signals as MS
import materiality
import whatchanged


def _book(tmp_path):
    path = str(tmp_path / "payer_diff.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Eli Lilly'),"
                 " (2, 'BMY', 'Bristol-Myers Squibb')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (31, 1, 'Mounjaro', 'Tirzepatide', 1),"
                 " (198, 2, 'Eliquis', 'Apixaban', 1)")
    conn.commit()
    return conn


def _release(conn, release, contract_year, rows):
    """One release's coverage snapshots, as the formulary fetcher writes them."""
    for asset_id, (total, listing, pa, st) in rows.items():
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
            " VALUES ('partd_formulary', 'payer_access', ?, ?)",
            (str(asset_id), json.dumps({
                "release_date": release, "contract_year": contract_year,
                "formularies_total": total, "formularies_listing": listing,
                "pa_formularies": pa, "st_formularies": st, "fetch_kind": "live"})))
    conn.commit()


def _changes(conn):
    return [dict(r) for r in conn.execute(
        "SELECT entity_type, entity_key, field, old_value, new_value, change_type,"
        " significance FROM changes ORDER BY id")]


def test_the_first_pass_anchors_and_says_nothing_beside_other_lanes_anchors(tmp_path):
    conn = _book(tmp_path)
    # The rate and IRA lanes already hold anchors in the shared table.
    MS.set_anchor(conn, "DGS10:25", 0.0425, "2026-09-18")
    MS.set_anchor(conn, "IRA:LLY:2027", 2027.0, "2027")
    _release(conn, "2026-08-19", 2026, {31: (312, 312, 270, 0), 198: (328, 328, 0, 0)})
    assert diff._diff_payer_access(conn, None) == 0
    held = MS.anchors(conn)
    assert held["PARTD_ACCESS:31:pa"]["anchor_value"] == 100.0 * 270 / 312
    assert {k for k in held if k.startswith("PARTD_ACCESS:")} == {
        f"PARTD_ACCESS:{a}:{m}" for a in (31, 198) for m in ("listed", "pa", "st")}
    assert _changes(conn) == []


def test_a_twelve_point_move_writes_once_and_three_more_points_nothing(tmp_path):
    conn = _book(tmp_path)
    _release(conn, "2026-08-19", 2026, {31: (312, 312, 272, 0)})    # 87.2%
    diff._diff_payer_access(conn, None)
    _release(conn, "2026-09-16", 2026, {31: (312, 312, 310, 0)})    # 99.4%
    assert diff._diff_payer_access(conn, None) == 1
    [row] = _changes(conn)
    assert row["entity_type"] == "payer" and row["change_type"] == "payer_access"
    assert row["significance"] == "medium"
    assert row["entity_key"] == "LLY|31|pa|2026-09-16"
    assert row["new_value"] == (
        "LLY Mounjaro: prior authorisation on 310 of 312 Medicare Part D formularies "
        "(99%), from 87% at the 2026-08-19 release; contract year 2026")
    # The same snapshot again, then a further 3 points: nothing either time.
    assert diff._diff_payer_access(conn, None) == 0
    _release(conn, "2026-10-21", 2027, {31: (300, 300, 300, 0)})    # 100%
    assert diff._diff_payer_access(conn, None) == 0
    assert len(_changes(conn)) == 1


def test_the_anchor_moves_only_when_a_change_is_written(tmp_path):
    """A share that walks 4 points a release is caught on the third, not lost."""
    conn = _book(tmp_path)
    for release, listing in (("2026-07-15", 250), ("2026-08-19", 263), ("2026-09-16", 276),
                             ("2026-10-21", 289)):
        _release(conn, release, 2026, {198: (328, listing, 0, 0)})
        diff._diff_payer_access(conn, None)
    rows = _changes(conn)
    assert len(rows) == 1 and rows[0]["entity_key"].endswith("|listed|2026-10-21")
    assert "listed on 289 of 328" in rows[0]["new_value"]
    assert MS.anchors(conn)["PARTD_ACCESS:198:listed"]["anchor_as_of"] == "2026-10-21"


def test_a_new_contract_year_is_compared_on_its_own_formulary_count(tmp_path):
    conn = _book(tmp_path)
    _release(conn, "2026-09-16", 2026, {198: (328, 328, 0, 0)})
    diff._diff_payer_access(conn, None)
    _release(conn, "2026-10-21", 2027, {198: (300, 300, 0, 0)})     # still everywhere
    assert diff._diff_payer_access(conn, None) == 0


def test_detect_changes_runs_the_lane_and_the_feed_dates_it_by_release(tmp_path):
    conn = _book(tmp_path)
    path = str(tmp_path / "payer_diff.db")
    _release(conn, "2026-08-19", 2026, {31: (312, 312, 0, 0)})
    conn.close()
    assert diff.detect_changes(path)["payer_access_moves"] == 0
    conn = db.get_connection(path)
    _release(conn, "2026-09-16", 2026, {31: (312, 312, 0, 40)})     # step therapy 12.8%
    conn.close()
    assert diff.detect_changes(path)["payer_access_moves"] == 1
    conn = db.get_connection(path)
    try:
        [item] = [i for i in whatchanged._recent_changes(conn, 30)
                  if i["change_type"] == "payer_access"]
    finally:
        conn.close()
    assert item["ticker"] == "LLY" and item["date"] == "2026-09-16"
    assert item["headline"].startswith("LLY Mounjaro: step therapy on 40 of 312")
    assert item["reason"] == (f"Part D coverage moved "
                              f"{materiality.PAYER_ACCESS_POINTS:.0f} points or more")
    assert item["significance"] == "medium"
