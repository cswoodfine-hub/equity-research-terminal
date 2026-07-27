"""Trial-to-asset mapping over a seeded DB, no network."""

import db
import seed
import trial_mapping as tm


def _asset(conn, ticker, brand=None, generic=None, code=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 " internal_code, is_marketed) VALUES (?,?,?,?,1)",
                 (cid, brand, generic, code))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _trial(conn, nct, ticker, drugs):
    cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, title, phase,"
                 " overall_status, source) VALUES (?,?,?,'Phase 3','Recruiting','ctgov')",
                 (nct, cid, f"study {nct}"))
    for d in drugs:
        conn.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
                     " VALUES (?,?,?,'DRUG')", (nct, d, tm.normalise(d)))


def _seeded(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly_tirz = _asset(conn, "LLY", brand="Mounjaro", generic="Tirzepatide",
                      code="LY3298176")
    lly_ins = _asset(conn, "LLY", brand="Humalog", generic="Insulin lispro")
    pfe = _asset(conn, "PFE", brand="Paxlovid", generic="Nirmatrelvir")
    conn.commit()
    return db_file, conn, lly_tirz, lly_ins, pfe


def test_normalise_reduces_punctuation_and_case():
    assert tm.normalise("LY-3298176") == "ly 3298176"
    assert tm.normalise("  Tirzepatide,  5 mg ") == "tirzepatide 5 mg"
    assert tm.normalise(None) == ""


def test_match_prefers_exact_then_longest_whole_word():
    names = [("insulin lispro", 2), ("tirzepatide", 1), ("mounjaro", 1)]
    names.sort(key=lambda n: len(n[0]), reverse=True)
    # Exact.
    assert tm.match_intervention("tirzepatide", names) == 1
    # Embedded in a dose string, matched as a whole word.
    assert tm.match_intervention("tirzepatide 5 mg injection", names) == 1
    # The longer, more specific name wins over a shorter one it contains.
    assert tm.match_intervention("insulin lispro 100 units", names) == 2
    # No match rather than a guess.
    assert tm.match_intervention("placebo", names) is None
    # A partial word does not match.
    assert tm.match_intervention("tirzepatidex", names) is None


def test_strip_salt_only_takes_a_trailing_salt_token():
    assert tm.strip_salt("orforglipron calcium") == "orforglipron"
    assert tm.strip_salt("ly3295668 erbumine") == "ly3295668"
    assert tm.strip_salt("tirzepatide") == "tirzepatide"
    # A single-token name is never reduced to nothing, even if it is a salt word.
    assert tm.strip_salt("calcium") == "calcium"


def test_registry_base_molecule_binds_to_the_orange_book_salt_form(tmp_path):
    """The Orange Book names the salt, the registry the base molecule. Both must bind."""
    db_file, conn, _, _, _ = _seeded(tmp_path)
    orfo = _asset(conn, "LLY", brand="Foundayo", generic="Orforglipron Calcium")
    _trial(conn, "NCT7", "LLY", ["Orforglipron"])
    conn.commit()
    conn.close()

    tm.map_trials(db_file)
    conn = db.get_connection(db_file)
    asset_id = conn.execute(
        "SELECT asset_id FROM trials WHERE nct_id='NCT7'").fetchone()[0]
    conn.close()
    assert asset_id == orfo


def test_map_trials_binds_by_brand_generic_and_code(tmp_path):
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _trial(conn, "NCT1", "LLY", ["Tirzepatide 10 mg"])       # generic
    _trial(conn, "NCT2", "LLY", ["Mounjaro"])                 # brand
    _trial(conn, "NCT3", "LLY", ["LY3298176 injection"])      # internal code
    _trial(conn, "NCT4", "LLY", ["Placebo"])                  # nothing to bind
    conn.commit()
    conn.close()

    out = tm.map_trials(db_file)
    conn = db.get_connection(db_file)
    got = dict(conn.execute("SELECT nct_id, asset_id FROM trials"))
    conn.close()

    assert got["NCT1"] == tirz
    assert got["NCT2"] == tirz
    assert got["NCT3"] == tirz
    assert got["NCT4"] is None          # unmatched is left null, never guessed
    assert out["matched"] == 3
    assert out["unmapped"] == 1


def test_match_is_scoped_to_the_sponsor(tmp_path):
    """A shared molecule name must not bind one company's trial to another's asset."""
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    # Pfizer runs a study naming Lilly's generic; it must not bind to the Lilly asset.
    _trial(conn, "NCT9", "PFE", ["Tirzepatide"])
    conn.commit()
    conn.close()

    tm.map_trials(db_file)
    conn = db.get_connection(db_file)
    asset_id = conn.execute(
        "SELECT asset_id FROM trials WHERE nct_id='NCT9'").fetchone()[0]
    conn.close()
    assert asset_id is None


def test_curated_override_wins_and_is_never_overwritten(tmp_path):
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _trial(conn, "NCT5", "LLY", ["Tirzepatide"])      # would derive to tirz
    conn.execute("INSERT INTO trial_asset_map (nct_id, asset_id, note)"
                 " VALUES ('NCT5', ?, 'analyst says insulin arm')", (ins,))
    conn.commit()
    conn.close()

    out = tm.map_trials(db_file)
    conn = db.get_connection(db_file)
    asset_id = conn.execute(
        "SELECT asset_id FROM trials WHERE nct_id='NCT5'").fetchone()[0]
    conn.close()
    assert asset_id == ins            # the curated answer, not the derived one
    assert out["curated"] == 1


def _pipeline_assets(db_file):
    conn = db.get_connection(db_file)
    rows = [dict(r) for r in conn.execute(
        "SELECT a.generic_name, a.is_marketed, c.ticker FROM assets a"
        "  JOIN companies c ON c.id = a.owner_company_id WHERE a.is_marketed = 0")]
    conn.close()
    return {r["generic_name"]: r["ticker"] for r in rows}


def test_pipeline_assets_exclude_design_comparators_and_backbones(tmp_path):
    """The three ways a trial names something that is not the sponsor's own programme."""
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    # A genuine Lilly pipeline compound: only Lilly studies it, nobody sells it.
    _trial(conn, "NCT10", "LLY", ["Retatrutide", "Placebo"])
    # Pfizer's marketed drug appearing in a Lilly study as a comparator.
    _trial(conn, "NCT11", "LLY", ["Nirmatrelvir"])
    # A backbone both companies run trials with.
    _trial(conn, "NCT12", "LLY", ["Paclitaxel"])
    _trial(conn, "NCT13", "PFE", ["Paclitaxel"])
    conn.commit()
    conn.close()

    out = tm.derive_pipeline_assets(db_file)
    created = _pipeline_assets(db_file)

    assert created == {"Retatrutide": "LLY"}     # only the real programme
    assert out["created"] == 1
    assert "Placebo" not in created              # study design
    assert "Nirmatrelvir" not in created         # another company's marketed drug
    assert "Paclitaxel" not in created           # studied by two sponsors


def test_aliases_cover_biologic_suffix_and_salt():
    # The FDA's four-letter biologic suffix, which is how an approved biologic's generic
    # name is spelled, must reduce to the base molecule the registry uses.
    assert "donanemab" in tm.aliases("donanemab-azbt")
    assert "sotatercept" in tm.aliases("Sotatercept-csrk")
    assert "orforglipron" in tm.aliases("Orforglipron Calcium")
    # A hyphenated word that is not a four-letter suffix is left alone.
    assert "co trimoxazole" in tm.aliases("Co-trimoxazole")


def test_an_approved_biologic_is_not_recreated_as_pipeline(tmp_path):
    """Kisunla's generic is "donanemab-azbt" but its trials say "Donanemab". Without
    reducing the suffix the approved product is duplicated as a pipeline programme."""
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _asset(conn, "LLY", brand="Kisunla", generic="donanemab-azbt")
    _trial(conn, "NCT16", "LLY", ["Donanemab"])
    conn.commit()
    conn.close()

    out = tm.derive_pipeline_assets(db_file)
    assert out["created"] == 0
    assert _pipeline_assets(db_file) == {}

    # It binds to the approved product instead.
    tm.map_trials(db_file)
    conn = db.get_connection(db_file)
    brand = conn.execute("SELECT a.brand_name FROM trials t JOIN assets a"
                         "  ON a.id = t.asset_id WHERE t.nct_id='NCT16'").fetchone()[0]
    conn.close()
    assert brand == "Kisunla"


def test_pipeline_assets_then_bind_their_trials(tmp_path):
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _trial(conn, "NCT14", "LLY", ["Retatrutide"])
    conn.commit()
    conn.close()

    tm.derive_pipeline_assets(db_file)
    tm.map_trials(db_file)

    conn = db.get_connection(db_file)
    row = conn.execute(
        "SELECT a.generic_name, a.is_marketed FROM trials t"
        "  JOIN assets a ON a.id = t.asset_id WHERE t.nct_id = 'NCT14'").fetchone()
    conn.close()
    assert row["generic_name"] == "Retatrutide"
    assert row["is_marketed"] == 0


def test_deriving_pipeline_assets_twice_makes_one(tmp_path):
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _trial(conn, "NCT15", "LLY", ["Retatrutide"])
    conn.commit()
    conn.close()

    tm.derive_pipeline_assets(db_file)
    tm.map_trials(db_file)
    second = tm.derive_pipeline_assets(db_file)
    assert second["created"] == 0
    assert list(_pipeline_assets(db_file)) == ["Retatrutide"]


def test_map_trials_is_idempotent(tmp_path):
    db_file, conn, tirz, ins, pfe = _seeded(tmp_path)
    _trial(conn, "NCT6", "LLY", ["Mounjaro"])
    conn.commit()
    conn.close()

    first = tm.map_trials(db_file)
    second = tm.map_trials(db_file)
    assert first["mapped"] == second["mapped"] == 1
