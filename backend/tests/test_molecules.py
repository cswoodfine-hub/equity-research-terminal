"""One molecule, several brands, and which of them the studies belong to.

Novo sells semaglutide as Ozempic and Wegovy. Both carry the same generic name, so every
semaglutide study matched both and the tie fell to row order: Wegovy took all of them and
Ozempic, on 127bn of revenue, showed no pipeline. 159 molecules are sold under more than
one brand by one company.
"""

import db
import molecules
import trial_mapping


def _seed(tmp_path):
    path = str(tmp_path / "mol.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVO', 'Novo')")
    # Wegovy is the lower id and the later approval, which is the whole test: row order
    # says Wegovy, the drug's history says Ozempic.
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " internal_code, is_marketed) VALUES"
                 " (1, 1, 'Wegovy', 'Semaglutide', 'NDA215256', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " internal_code, is_marketed) VALUES"
                 " (2, 1, 'Ozempic', 'Semaglutide', 'NDA213051', 1)")
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (1, 'NDA215256', '2021-06-04')")
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (2, 'NDA213051', '2017-12-05')")
    conn.commit()
    return path, conn


def _trial(conn, nct, asset_id=None):
    conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, title, phase)"
                 " VALUES (?, ?, 1, 'a semaglutide study', 'Phase 3')", (nct, asset_id))
    conn.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
                 " VALUES (?, 'Semaglutide', 'semaglutide', 'DRUG')", (nct,))
    conn.commit()


# --- the grouping -----------------------------------------------------------

def test_a_salt_does_not_split_a_molecule():
    """Calquence is filed as both acalabrutinib and acalabrutinib maleate."""
    assert molecules.group_key(1, "Acalabrutinib") == \
        molecules.group_key(1, "Acalabrutinib Maleate")


def test_two_companies_are_never_one_molecule():
    assert molecules.group_key(1, "Semaglutide") != molecules.group_key(2, "Semaglutide")


def test_a_name_too_short_to_identify_anything_groups_nothing():
    assert molecules.group_key(1, "") is None
    assert molecules.group_key(None, "Semaglutide") is None


def test_the_holder_is_the_earliest_approved_not_the_lowest_row():
    """The point of the whole change: row order gave Wegovy, which is an accident of what
    was fetched first. The approval date is a fact about the drug."""
    rows = [{"id": 1, "first_approval": "2021-06-04"},
            {"id": 2, "first_approval": "2017-12-05"}]
    assert molecules.holder(rows) == 2


def test_an_unapproved_sibling_never_takes_the_molecule():
    rows = [{"id": 1, "first_approval": None}, {"id": 2, "first_approval": "2017-12-05"}]
    assert molecules.holder(rows) == 2


def test_the_oldest_row_settles_it_when_nothing_is_approved():
    rows = [{"id": 5, "first_approval": None}, {"id": 2, "first_approval": None}]
    assert molecules.holder(rows) == 2


def test_siblings_point_at_the_holder(tmp_path):
    path, conn = _seed(tmp_path)
    conn.close()
    out = molecules.assign(path)
    assert out["groups_with_siblings"] == 1 and out["shared_brands"] == 2
    conn = db.get_connection(path)
    rows = dict(conn.execute("SELECT brand_name, molecule_id FROM assets").fetchall())
    assert rows["Ozempic"] == 2 and rows["Wegovy"] == 2
    conn.close()


def test_a_product_with_no_sibling_is_its_own_molecule(tmp_path):
    """So every query keeps one shape rather than special-casing the common case."""
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (3, 1, 'Tresiba', 'Insulin Degludec', 1)")
    conn.commit(); conn.close()
    molecules.assign(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT molecule_id FROM assets WHERE id = 3").fetchone()[0] == 3
    conn.close()


def test_assigning_twice_changes_nothing(tmp_path):
    path, conn = _seed(tmp_path)
    conn.close()
    assert molecules.assign(path) == molecules.assign(path)


# --- what it fixes ----------------------------------------------------------

def test_the_holder_takes_the_study_not_the_lower_row(tmp_path):
    path, conn = _seed(tmp_path)
    _trial(conn, "NCT1")
    conn.close()
    molecules.assign(path)
    trial_mapping.map_trials(path)
    conn = db.get_connection(path)
    got = conn.execute("SELECT asset_id FROM trials WHERE nct_id = 'NCT1'").fetchone()[0]
    assert got == 2, "the study should land on Ozempic, the molecule's holder"
    conn.close()


def test_the_sibling_reaches_the_studies_it_does_not_hold(tmp_path):
    """Answering "no trials" to a reader looking at a 127bn franchise is worse than saying
    where the molecule's studies sit."""
    path, conn = _seed(tmp_path)
    _trial(conn, "NCT1", asset_id=2)
    conn.close()
    molecules.assign(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = 1").fetchone()[0] == 0
    assert len(molecules.molecule_trials(conn, 1)) == 1
    assert molecules.molecule_trials(conn, 1)[0]["held_by"] == "Ozempic"
    conn.close()


def test_a_study_is_never_counted_twice(tmp_path):
    """Attributing it to every sibling would inflate exactly the biggest franchises, which
    is where a pipeline count is read hardest."""
    path, conn = _seed(tmp_path)
    _trial(conn, "NCT1")
    conn.close()
    molecules.assign(path)
    trial_mapping.map_trials(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id IS NOT NULL"
                        ).fetchone()[0] == 1
    conn.close()


def test_siblings_are_named_for_a_page_that_would_be_blank(tmp_path):
    path, conn = _seed(tmp_path)
    _trial(conn, "NCT1", asset_id=2)
    conn.close()
    molecules.assign(path)
    conn = db.get_connection(path)
    sibs = molecules.siblings(conn, 1)
    assert [s["brand_name"] for s in sibs] == ["Ozempic"]
    assert sibs[0]["trials"] == 1
    assert molecules.siblings(conn, 2)[0]["brand_name"] == "Wegovy"
    conn.close()


def test_a_lone_product_has_no_siblings(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (3, 1, 'Tresiba', 'Insulin Degludec', 1)")
    conn.commit(); conn.close()
    molecules.assign(path)
    conn = db.get_connection(path)
    assert molecules.siblings(conn, 3) == []
    conn.close()
