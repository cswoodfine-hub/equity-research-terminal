"""Names a trial lists that are not a drug programme, and that no rule can reject."""

import db
import trial_mapping as TM


def _db(tmp_path, monkeypatch, body="REGN,Ravulizumab,Alexion's Ultomiris as a comparator\n"):
    listed = tmp_path / "not_a_programme.csv"
    listed.write_text("# a comment line\nticker,name,basis\n" + body)
    monkeypatch.setattr(TM, "NOT_A_PROGRAMME_CSV", listed)
    path = str(tmp_path / "nap.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.executescript("""
        INSERT INTO companies (id, ticker, name) VALUES (1, 'REGN', 'Regeneron'),
                                                         (2, 'AZN', 'AstraZeneca');
        INSERT INTO trials (nct_id, sponsor_company_id, phase, overall_status) VALUES
               ('NCT05133531', 1, 'Phase 3', 'Recruiting');
        INSERT INTO trial_interventions (nct_id, name, kind) VALUES
               ('NCT05133531', 'Pozelimab', 'BIOLOGICAL'),
               ('NCT05133531', 'Ravulizumab', 'BIOLOGICAL');
    """)
    conn.commit()
    return path, conn


def _names(conn, company_id):
    return sorted(r[0] for r in conn.execute(
        "SELECT generic_name FROM assets WHERE owner_company_id = ?", (company_id,)))


def test_a_listed_name_resolves_to_its_sponsor_and_canonical_key(tmp_path, monkeypatch):
    _path, conn = _db(tmp_path, monkeypatch)
    got = TM.curated_not_programmes(conn)
    conn.close()
    assert got == {(1, TM.canonical("Ravulizumab"))}


def test_a_listed_comparator_is_never_derived_as_the_sponsors_programme(tmp_path,
                                                                         monkeypatch):
    """Pozelimab is Regeneron's; ravulizumab in the same trial is Alexion's comparator."""
    path, conn = _db(tmp_path, monkeypatch)
    TM.derive_pipeline_assets(path)
    names = _names(conn, 1)
    conn.close()
    assert names == ["Pozelimab"]


def test_without_the_row_the_comparator_would_have_been_a_programme(tmp_path, monkeypatch):
    """The guard is the file, not a rule: nothing else in the module rejects the name."""
    path, conn = _db(tmp_path, monkeypatch, body="")
    TM.derive_pipeline_assets(path)
    names = _names(conn, 1)
    conn.close()
    assert names == ["Pozelimab", "Ravulizumab"]


def test_a_row_already_derived_is_removed_and_its_trial_released(tmp_path, monkeypatch):
    path, conn = _db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (9, 1, 'Ravulizumab', 0)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Hemoglobinuria')")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase)"
                 " VALUES (9, 1, 'Phase 3')")
    conn.execute("UPDATE trials SET asset_id = 9 WHERE nct_id = 'NCT05133531'")
    conn.commit()
    got = TM.prune_arms(path)
    left = conn.execute("SELECT COUNT(*) FROM assets WHERE id = 9").fetchone()[0]
    trial = conn.execute("SELECT asset_id FROM trials").fetchone()[0]
    conn.close()
    assert ("Ravulizumab", "retired", 0) in got["detail"]
    assert left == 0 and trial is None


def test_a_name_listed_for_one_sponsor_is_untouched_at_another(tmp_path, monkeypatch):
    """The same substance can be a comparator at one company and a programme at the
    next, so the row is per sponsor."""
    path, conn = _db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (9, 2, 'Ravulizumab', 0)")
    conn.commit()
    TM.prune_arms(path)
    left = conn.execute("SELECT COUNT(*) FROM assets WHERE id = 9").fetchone()[0]
    conn.close()
    assert left == 1


def test_the_shipped_file_parses_and_every_row_carries_a_reason():
    import csv
    with TM.NOT_A_PROGRAMME_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")))
    assert rows
    for row in rows:
        assert row["ticker"].strip() and TM.canonical(row["name"]), row
        assert len(row["basis"]) > 40, row["name"]
