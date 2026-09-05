"""The development name a marketed product used to go by, read from its own filings.

A drug is registered under a programme name and sold under a brand, so the same drug sat
in the database twice: Enhertu with an approval and no studies, "trastuzumab deruxtecan"
with thirteen studies read as an unapproved compound.

The tests that matter most here are the ones about what must not match. Proximity is not
identity, and a filing's pipeline table puts a dozen unrelated products within a line of
each other.
"""

import asset_merge
import db
import programme_alias as pa

FILING = (
    "Our oncology portfolio includes ENHERTU (fam-trastuzumab deruxtecan-nxki), which is"
    " approved in breast cancer. We also market Cobenfy (KarXT) for schizophrenia."
)
PIPELINE_TABLE = (
    "The following programmes are in development: ABBV-313, ABBV-319, ABBV-1451 and"
    " ABBV-859. Our marketed immunology products include RINVOQ and SKYRIZI."
)


# --- the construction, not the nearness ------------------------------------

def test_the_parenthetical_that_introduces_a_product_is_the_evidence():
    assert pa.alias_hits(FILING, "enhertu", "trastuzumab deruxtecan")
    assert pa.alias_hits(FILING, "cobenfy", "karxt")


def test_a_pipeline_table_is_not_an_alias():
    """The rule this replaced matched any brand within ninety characters and paired
    ABBV-313 with Rinvoq and retatrutide with Omvoh. Both would have moved one drug's
    entire trial history onto a different product."""
    assert pa.alias_hits(PIPELINE_TABLE, "rinvoq", "abbv-313") == 0
    assert pa.alias_hits(PIPELINE_TABLE, "skyrizi", "abbv-859") == 0


def test_the_reverse_construction_counts_too():
    assert pa.alias_hits("seladelpar (LIVDELZI) is approved", "livdelzi", "seladelpar")


def test_formerly_and_now_marketed_as_are_read():
    assert pa.alias_hits("CASGEVY, formerly exa-cel, was approved", "casgevy", "exa-cel")
    assert pa.alias_hits("KarXT is now marketed as Cobenfy", "cobenfy", "karxt")


def test_a_short_name_is_never_evidence():
    """Three and four letter names collide with ordinary words and with each other."""
    assert pa.alias_hits("Otez (ABC) treats psoriasis", "otez", "abc") == 0
    assert pa.MIN_NAME == 5


def test_a_window_is_taken_around_each_mention():
    """The patterns run on a window, never a whole 10-K section: it took the pass from
    190 seconds to under two."""
    blob = ("x" * 5000) + "enhertu (fam-trastuzumab deruxtecan)" + ("y" * 5000)
    windows = pa._windows(blob, "trastuzumab deruxtecan")
    assert len(windows) == 1
    assert len(windows[0]) < 500
    assert pa.alias_hits(windows[0], "enhertu", "trastuzumab deruxtecan")


# --- the link ---------------------------------------------------------------

def _seed(tmp_path, text=FILING):
    path = str(tmp_path / "alias.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'AstraZeneca')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " internal_code, is_marketed) VALUES"
                 " (1, 1, 'Enhertu', 'fam-trastuzumab deruxtecan-nxki', 'BLA761139', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (2, 1, 'trastuzumab deruxtecan', 0)")
    for nct in ("NCT1", "NCT2"):
        conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, title,"
                     " phase) VALUES (?, 2, 1, 'a study', 'Phase 3')", (nct,))
    conn.execute("INSERT INTO filing_sections (company_id, accession, form_type,"
                 " filed_date, section, text) VALUES (1, 'a1', '10-K', '2026-01-01',"
                 " 'body', ?)", (text,))
    conn.commit()
    return path, conn


def test_a_programme_that_is_a_product_is_found(tmp_path):
    path, conn = _seed(tmp_path)
    links = pa.find_links(conn)
    assert len(links) == 1
    assert links[0]["programme_id"] == 2 and links[0]["marketed_id"] == 1
    conn.close()


def test_two_candidate_products_are_refused(tmp_path):
    """A guess here moves a drug's whole trial history onto the wrong product."""
    path, conn = _seed(
        tmp_path,
        "Enhertu (trastuzumab deruxtecan) and Imfinzi (trastuzumab deruxtecan) both.")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (3, 1, 'Imfinzi', 'durvalumab', 1)")
    conn.commit()
    assert pa.find_links(conn) == []
    conn.close()


def test_another_companys_product_is_never_linked(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'MRK', 'Merck')")
    conn.execute("UPDATE assets SET owner_company_id = 2 WHERE id = 1")
    conn.commit()
    assert pa.find_links(conn) == []
    conn.close()


def test_a_programme_with_no_trials_is_left_alone(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("DELETE FROM trials")
    conn.commit()
    assert pa.find_links(conn) == []
    conn.close()


# --- the merge, and surviving the next refresh -----------------------------

def test_the_merge_moves_the_trials_onto_the_product(tmp_path):
    path, conn = _seed(tmp_path)
    conn.close()
    out = asset_merge.merge(path)
    assert out["by_alias"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = 1").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 2").fetchone()[0] == 0
    conn.close()


def test_the_programme_name_is_recorded_so_it_is_not_derived_again(tmp_path):
    """Without this the next run derives the pipeline row from the same intervention and
    the merge undoes itself every refresh."""
    path, conn = _seed(tmp_path)
    conn.close()
    asset_merge.merge(path)
    conn = db.get_connection(path)
    row = conn.execute("SELECT asset_id, note FROM asset_aliases WHERE internal_code = ?",
                       ("trastuzumab deruxtecan",)).fetchone()
    assert row["asset_id"] == 1
    assert "development name" in row["note"]
    conn.close()


def test_a_recorded_programme_name_is_treated_as_marketed(tmp_path):
    """The derivation drops any intervention a universe company already sells, and an
    absorbed development name has to count as one of those."""
    import trial_mapping
    path, conn = _seed(tmp_path)
    conn.close()
    asset_merge.merge(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
                 " VALUES ('NCT1', 'Trastuzumab Deruxtecan', 'trastuzumab deruxtecan',"
                 " 'DRUG')")
    conn.commit(); conn.close()
    trial_mapping.derive_pipeline_assets(path)
    conn = db.get_connection(path)
    remade = conn.execute("SELECT COUNT(*) FROM assets WHERE is_marketed = 0"
                          "   AND LOWER(generic_name) = 'trastuzumab deruxtecan'"
                          ).fetchone()[0]
    assert remade == 0
    conn.close()


def test_the_alias_pass_is_idempotent(tmp_path):
    path, conn = _seed(tmp_path)
    conn.close()
    assert asset_merge.merge(path)["by_alias"] == 1
    assert asset_merge.merge(path)["by_alias"] == 0


# --- the curated override, for what no filing gives up ---------------------

CURATED = ("ticker,programme_name,brand,note\n"
           "AZN,CTX001,Enhertu,development name\n")


def _curated(tmp_path, body=CURATED):
    f = tmp_path / "alias_map.csv"
    f.write_text("# a comment line that must be skipped\n" + body)
    return str(f)


def test_a_curated_name_is_written_against_the_product(tmp_path):
    path, conn = _seed(tmp_path)
    assert pa.load_curated(conn, _curated(tmp_path)) == 1
    row = conn.execute("SELECT asset_id, note FROM asset_aliases"
                       " WHERE internal_code = 'CTX001'").fetchone()
    assert row["asset_id"] == 1
    assert row["note"].startswith("curated:")
    conn.close()


def test_a_curated_name_folds_the_pipeline_row(tmp_path):
    """Casgevy is the case: the studies are filed under CTX001, the filings bind the brand
    to exa-cel, and nothing on record joins those two. One row settles it, and settles it
    on every future refresh rather than once by hand."""
    path, conn = _seed(tmp_path)
    conn.execute("UPDATE assets SET generic_name = 'CTX001' WHERE id = 2")
    conn.execute("DELETE FROM filing_sections")       # no filing evidence at all
    conn.commit(); conn.close()
    import shutil
    shutil.copy(_curated(tmp_path), tmp_path / "map.csv")
    import programme_alias
    real = programme_alias.CURATED
    programme_alias.CURATED = tmp_path / "map.csv"
    try:
        out = asset_merge.merge(path)
    finally:
        programme_alias.CURATED = real
    assert out["by_alias"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = 1").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 2").fetchone()[0] == 0
    conn.close()


def test_an_override_for_a_product_not_yet_on_file_is_skipped(tmp_path):
    """A fresh database has no products until the fetchers run, and a row pointing at
    nothing must not fail the merge."""
    path, conn = _seed(tmp_path)
    body = "ticker,programme_name,brand,note\nAZN,XYZ999,Nothinghere,n/a\n"
    assert pa.load_curated(conn, _curated(tmp_path, body)) == 0
    conn.close()


def test_a_missing_override_file_is_not_an_error(tmp_path):
    path, conn = _seed(tmp_path)
    assert pa.load_curated(conn, str(tmp_path / "absent.csv")) == 0
    conn.close()


def test_the_shipped_override_file_parses():
    """The real file, so a typo in it fails here rather than silently doing nothing."""
    import csv as _csv
    with pa.CURATED.open(newline="", encoding="utf-8") as handle:
        rows = list(_csv.DictReader(
            [l for l in handle if not l.lstrip().startswith("#")]))
    assert rows, "the curated file should hold at least the Casgevy row"
    for row in rows:
        assert row["ticker"] and row["programme_name"] and row["brand"]
    assert any(r["programme_name"] == "CTX001" and r["brand"] == "Casgevy" for r in rows)


def test_a_curated_row_can_point_at_a_compound_that_has_no_brand(tmp_path):
    """14C-bleximenib is the case: the registry files a mass balance study under the
    carbon-14 label and the compound itself has no brand, so a target column that only
    matched brand_name could never join them. The pairs that need merging most are two
    pipeline rows, not a code and a product."""
    path, conn = _seed(tmp_path)
    body = ("ticker,programme_name,brand,note\n"
            "AZN,14C-trastuzumab deruxtecan,trastuzumab deruxtecan,the radiolabel\n")
    assert pa.load_curated(conn, _curated(tmp_path, body)) == 1
    row = conn.execute("SELECT asset_id FROM asset_aliases"
                       " WHERE internal_code = '14C-trastuzumab deruxtecan'").fetchone()
    assert row["asset_id"] == 2          # the compound, matched on its generic name
    conn.close()


def test_a_brand_still_wins_over_a_compound_sharing_the_name(tmp_path):
    """The fallback must not let a development row shadow a launched product."""
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (3, 1, 'Enhertu', 0)")
    conn.commit()
    assert pa.load_curated(conn, _curated(tmp_path)) == 1
    row = conn.execute("SELECT asset_id FROM asset_aliases"
                       " WHERE internal_code = 'CTX001'").fetchone()
    assert row["asset_id"] == 1          # the product, not the compound named after it
    conn.close()
