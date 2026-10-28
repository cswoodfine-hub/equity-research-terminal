"""Re-pointing the history tables at the rows this build gave out.

asset_id is a surrogate. history.rebuild restores the history before seed.py recreates
the assets, so an id a restored row carries was issued by an earlier build. On the cloud
book after one rebuild, 545 of 1,815 gate_calls rows pointed at no asset at all.
"""

import db
import relink


def _book(tmp_path, assets=(("LLY", "Verzenio", "Abemaciclib"),)):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    seen = {}
    for n, (ticker, brand, generic) in enumerate(assets, start=1):
        if ticker not in seen:
            seen[ticker] = len(seen) + 1
            conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                         (seen[ticker], ticker, ticker))
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name,"
                     " generic_name, modality) VALUES (?, ?, ?, ?, 'small molecule')",
                     (n, seen[ticker], brand, generic))
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Prostatic Neoplasms')")
    conn.commit()
    return path, conn


def _gate(conn, asset_id, ticker="LLY", name="Verzenio", cid=1):
    conn.execute("""INSERT INTO gate_calls (as_of, ticker, catalyst_id, asset_id,
                        asset_name, gate) VALUES ('2026-10-26', ?, ?, ?, ?, 'p3_to_nda')""",
                 (ticker, cid, asset_id, name))
    conn.commit()


def _edit(conn, asset_id, ticker="LLY", name="Verzenio", indication_id=None,
          indication_name=None, key="pos"):
    conn.execute("""INSERT INTO assumption_edits (asset_id, indication_id, region,
                        scenario, key, op, ticker, asset_name, indication_name, reason)
                    VALUES (?, ?, 'US', 'base', ?, 'create', ?, ?, ?, 'correction')""",
                 (asset_id, indication_id, key, ticker, name, indication_name))
    conn.commit()


def test_a_stale_id_is_repointed_from_the_names(tmp_path):
    path, conn = _book(tmp_path)
    _gate(conn, asset_id=9999)                 # an id an earlier build gave out
    conn.close()
    out = relink.run(path)
    assert out["gate_calls"]["relinked"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT asset_id FROM gate_calls").fetchone()[0] == 1
    conn.close()


def test_a_working_id_is_left_alone(tmp_path):
    """A correct pointer is not improved by being recomputed."""
    path, conn = _book(tmp_path)
    _gate(conn, asset_id=1)
    conn.close()
    out = relink.run(path)
    assert out["gate_calls"]["relinked"] == 0 and out["gate_calls"]["unresolved"] == 0


def test_a_name_no_asset_carries_is_left_unresolved_not_guessed(tmp_path):
    """A ledger row pointing at the wrong product is worse than one pointing at none."""
    path, conn = _book(tmp_path)
    _gate(conn, asset_id=9999, name="Zorevunersen")
    conn.close()
    out = relink.run(path)
    assert out["gate_calls"] == {"checked": 1, "relinked": 0, "unresolved": 1}


def test_the_ticker_is_part_of_the_key(tmp_path):
    """Two companies can sell a product under the same name; the row names its own."""
    path, conn = _book(tmp_path, assets=(("LLY", "Verzenio", "Abemaciclib"),
                                         ("AMGN", "Verzenio", "Other")))
    _gate(conn, asset_id=9999, ticker="AMGN", name="Verzenio")
    conn.close()
    relink.run(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT asset_id FROM gate_calls").fetchone()[0] == 2
    conn.close()


def test_a_name_two_assets_of_one_company_share_gives_no_answer(tmp_path):
    """No safe answer, so no answer rather than whichever row sorted first."""
    path, conn = _book(tmp_path, assets=(("LLY", "Verzenio", "Abemaciclib"),
                                         ("LLY", "Verzenio", "Something else")))
    _gate(conn, asset_id=9999)
    conn.close()
    assert relink.run(path)["gate_calls"]["unresolved"] == 1


def test_the_generic_name_resolves_too(tmp_path):
    path, conn = _book(tmp_path)
    _gate(conn, asset_id=9999, name="Abemaciclib")
    conn.close()
    assert relink.run(path)["gate_calls"]["relinked"] == 1


def test_the_ledger_is_repaired_the_same_way(tmp_path):
    path, conn = _book(tmp_path)
    _edit(conn, asset_id=9999)
    conn.close()
    assert relink.run(path)["assumption_edits"]["relinked"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT asset_id FROM assumption_edits").fetchone()[0] == 1
    conn.close()


def test_a_stale_indication_is_repaired_from_its_name(tmp_path):
    path, conn = _book(tmp_path)
    _edit(conn, asset_id=1, indication_id=8888,
          indication_name="Prostatic Neoplasms")
    conn.close()
    assert relink.run(path)["assumption_edits"]["indications"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT indication_id FROM assumption_edits").fetchone()[0] == 1
    conn.close()


def test_nothing_about_the_record_itself_is_touched(tmp_path):
    """Repairing a pointer is not rewriting a record."""
    path, conn = _book(tmp_path)
    conn.execute("""INSERT INTO assumption_edits (asset_id, region, scenario, key, op,
                        ticker, asset_name, reason, rationale, changed_by, new_value,
                        changed_at)
                    VALUES (9999, 'US', 'base', 'pos', 'update', 'LLY', 'Verzenio',
                        'readout', 'CYCLONE 3 read out', 'charles', 0.92,
                        '2026-10-01 09:00:00')""")
    conn.commit(); conn.close()
    relink.run(path)
    conn = db.get_connection(path)
    r = conn.execute("SELECT * FROM assumption_edits").fetchone()
    conn.close()
    assert r["asset_id"] == 1, "the pointer moved"
    assert (r["reason"], r["rationale"], r["changed_by"], r["new_value"],
            r["changed_at"]) == ("readout", "CYCLONE 3 read out", "charles", 0.92,
                                 "2026-10-01 09:00:00"), "and nothing else did"
