"""The assumption layer: analyst inputs with provenance, loaded, saved and seeded.

The rules under test are the roadmap's: every number is an analyst input carrying its
source, a scenario restates only what it changes, and the seed file reconstructs the
whole layer on a database rebuilt from nothing.
"""

import pytest

import db
import assumptions as A


def _seed(tmp_path):
    path = str(tmp_path / "a.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " modality, is_marketed) VALUES"
                 " (1, 1, 'Casgevy', 'Exagamglogene autotemcel', 'biologic', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Anemia, Sickle Cell')")
    conn.commit()
    return path, conn


def test_save_and_load_round_trip(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [
        {"key": "therapy_mode", "text_value": "one_time", "source": "workbook"},
        {"key": "net_price_per_patient", "value": 1.8, "unit": "mm USD",
         "source": "Vertex Dec 2023"},
        {"key": "prevalence", "value": 100000, "indication_id": 1, "source": "CDC"},
        {"key": "new_patients", "value": 5, "year": 2024, "indication_id": 1,
         "source": "analyst"},
        {"key": "new_patients", "value": 45, "year": 2025, "indication_id": 1,
         "source": "analyst"},
    ])
    conn.commit()
    got = A.load(conn, 1)
    assert got["scalars"]["therapy_mode"] == "one_time"
    assert got["scalars"]["net_price_per_patient"] == 1.8
    ind = got["indications"][0]
    assert ind["name"] == "Anemia, Sickle Cell"
    assert ind["scalars"]["prevalence"] == 100000
    assert ind["series"]["new_patients"] == {2024: 5, 2025: 45}
    conn.close()


def test_writing_the_same_key_replaces_rather_than_duplicates(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "net_price_per_patient", "value": 1.8, "source": "a"}])
    A.save(conn, 1, [{"key": "net_price_per_patient", "value": 1.65, "source": "b"}])
    conn.commit()
    rows = A.rows(conn, 1)
    assert len(rows) == 1
    assert rows[0]["value"] == 1.65 and rows[0]["source"] == "b"
    conn.close()


def test_an_empty_value_deletes_the_row(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2}])
    A.save(conn, 1, [{"key": "sga_pct", "value": None}])
    conn.commit()
    assert A.rows(conn, 1) == []
    conn.close()


def test_a_row_with_no_key_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    try:
        A.save(conn, 1, [{"value": 1.0}])
        raised = False
    except ValueError:
        raised = True
    assert raised
    conn.close()


def test_a_scenario_restates_only_what_it_changes(tmp_path):
    """A bear case that touches three numbers must not need the other forty copied."""
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [
        {"key": "net_price_per_patient", "value": 1.8, "source": "base"},
        {"key": "sga_pct", "value": 0.2, "source": "base"},
        {"key": "net_price_per_patient", "value": 1.5, "scenario": "bear",
         "source": "bear case"},
    ])
    conn.commit()
    bear = A.load(conn, 1, scenario="bear")
    assert bear["scalars"]["net_price_per_patient"] == 1.5   # restated
    assert bear["scalars"]["sga_pct"] == 0.2                 # inherited from base
    conn.close()


def test_the_seed_file_rebuilds_the_layer_from_nothing(tmp_path):
    path, conn = _seed(tmp_path)
    seed_dir = tmp_path / "assumptions"
    seed_dir.mkdir()
    (seed_dir / "x.csv").write_text(
        "# comment\n"
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,"
        "source,note\n"
        "VRTX,Casgevy,,US,base,therapy_mode,,,one_time,,workbook,\n"
        'VRTX,Casgevy,"Anemia, Sickle Cell",US,base,prevalence,,100000,,patients,CDC,\n'
        "VRTX,Casgevy,\"Anemia, Sickle Cell\",US,base,new_patients,2024,5,,patients,"
        "analyst,\n"
        "OTHR,Missing,,US,base,therapy_mode,,,one_time,,x,\n")
    out = A.load_seeds(conn, seed_dir)
    assert out["written"] == 3
    assert out["skipped"] == 1                      # the unknown product is skipped
    got = A.load(conn, 1)
    assert got["scalars"]["therapy_mode"] == "one_time"
    assert got["indications"][0]["series"]["new_patients"] == {2024: 5}
    conn.close()


def test_seeding_twice_is_idempotent(tmp_path):
    path, conn = _seed(tmp_path)
    seed_dir = tmp_path / "assumptions"
    seed_dir.mkdir()
    (seed_dir / "x.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,"
        "source,note\n"
        "VRTX,Casgevy,,US,base,sga_pct,,0.2,,,workbook,\n")
    A.load_seeds(conn, seed_dir)
    A.load_seeds(conn, seed_dir)
    assert len(A.rows(conn, 1)) == 1
    conn.close()


def test_the_shipped_casgevy_seed_parses_and_carries_sources():
    """The real file: every row a source or an explicit for-review note, so a typo fails
    here rather than silently seeding nothing."""
    import csv
    path = A.SEED_DIR / "casgevy.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(
            [l for l in handle if not l.lstrip().startswith("#")]))
    assert len(rows) > 40
    for row in rows:
        assert row["ticker"] == "VRTX" and row["brand"] == "Casgevy"
        assert (row["source"] or "").strip() or "for review" in (row["note"] or ""), \
            f"unsourced row without a for-review note: {row['key']}"


def test_the_default_files_parse_and_carry_sources():
    pos = A.pos_defaults()
    assert "Phase 3" in pos and pos["Phase 3"]["pos"] == 0.65
    assert all(row["source"] for row in pos.values())
    erosion = A.erosion_defaults()
    assert "small molecule" in erosion
    assert erosion["small molecule"]["year1_pct"] > erosion["biologic"]["year1_pct"]
    assert all(row["source"] for row in erosion.values())


def test_snapshot_writes_forecast_history(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "x"}])
    A.snapshot(conn, 1, "base", {"rnpv": 1911.7, "npv": 2367.5, "wacc": 0.098,
                                 "pos": 0.8075, "revenue_after_loe": [1.0],
                                 "years": [2026]})
    conn.commit()
    row = conn.execute("SELECT source, entity_key, payload FROM snapshots"
                       " WHERE source = 'forecast'").fetchone()
    assert row["entity_key"] == "1"
    import json
    payload = json.loads(row["payload"])
    assert payload["rnpv"] == 1911.7
    assert payload["assumptions"][0]["key"] == "sga_pct"
    conn.close()


def test_xlsx_export_round_trips_through_openpyxl(tmp_path):
    import io

    from openpyxl import load_workbook
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "net_price_per_patient", "value": 1.8,
                      "source": "Vertex"}])
    blob = A.export_xlsx(conn, 1, "base", None)
    book = load_workbook(io.BytesIO(blob))
    sheet = book["Assumptions"]
    header = [c.value for c in sheet[1]]
    assert "key" in header and "source" in header
    values = {row[header.index("key")]: row[header.index("value")]
              for row in sheet.iter_rows(min_row=2, values_only=True)}
    assert values["net_price_per_patient"] == 1.8
    conn.close()


def test_a_product_built_from_revenue_exports_with_blank_patient_cells(tmp_path):
    """A marketed product runs off reported revenue, so the engine returns no patient
    count for a year. The export rounded each one and failed on the first, so the
    download of any marketed product's forecast answered with a server error."""
    import io

    from openpyxl import load_workbook
    path, conn = _seed(tmp_path)
    result = {"years": [2026, 2027], "patients": {"total": [None, None]},
              "revenue_after_loe": [1000.04, 1100.06], "wacc": 0.08, "pos": 1.0,
              "npv": 5000.0, "rnpv": 5000.0}
    blob = A.export_xlsx(conn, 1, "base", result)
    forecast = load_workbook(io.BytesIO(blob))["Forecast"]
    rows = {r[0]: r[1:] for r in forecast.iter_rows(values_only=True) if r and r[0]}
    conn.close()
    assert rows["new patients"] == (None, None)
    assert rows["revenue, mm"] == (1000.0, 1100.1)


def test_a_seed_can_name_a_compound_that_has_no_brand_yet(tmp_path):
    """Retatrutide, milvexian and every other Phase 3 asset carries a generic name and a
    null brand. A loader matching brand alone could seed marketed products and nothing in
    the pipeline, which is where a forecast is worth most."""
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (2, 1, 'Retatrutide', 0)")
    conn.commit()
    directory = tmp_path / "seeds"
    directory.mkdir()
    (directory / "reta.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"
        "VRTX,Retatrutide,,US,base,tax_rate,,0.2,,,10-K,\n", encoding="utf-8")

    assert A.load_seeds(conn, directory)["written"] == 1
    got = A.load(conn, 2)
    assert got["scalars"]["tax_rate"] == 0.2
    conn.close()


def test_a_brand_still_wins_over_a_compound_of_the_same_name(tmp_path):
    path, conn = _seed(tmp_path)
    # A launched product must never be shadowed by a compound sharing its ingredient.
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (3, 1, 'Casgevy', 0)")
    conn.commit()
    directory = tmp_path / "seeds"
    directory.mkdir()
    (directory / "c.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"
        "VRTX,Casgevy,,US,base,tax_rate,,0.15,,,workbook,\n", encoding="utf-8")
    A.load_seeds(conn, directory)

    assert A.load(conn, 1)["scalars"].get("tax_rate") == 0.15   # the marketed row
    assert not A.load(conn, 3)["scalars"]
    conn.close()


def test_no_seed_file_is_silently_unloaded():
    """A seed file naming an asset the book cannot resolve loads nothing and says
    nothing: load_seeds counts the row as skipped, among the many rows a reseed
    legitimately passes over because they are already there. Twenty-seven files, 602
    cited rows, were sitting unloaded when this was first measured. The list is checked
    in so it cannot grow without the suite saying so."""
    import db as _db
    import pathlib as _pathlib
    # The same rule the other book guards keep: skipped, with the reason, where no built
    # database is on file.
    if not _db.DB_PATH.exists():
        pytest.skip(f"no built database at {_db.DB_PATH}")
    known = {line.strip() for line in
             (db.BACKEND_DIR.parent / "data" / "unloaded_seed_files.txt"
              ).read_text().splitlines()
             if line.strip() and not line.startswith("#")}
    conn = _db.get_connection()
    try:
        got = set(A.unresolved_seed_files(conn))
    finally:
        conn.close()
    new = got - known
    assert not new, f"seed files that now load nothing: {sorted(new)}"
    # And when one is fixed, the list has to be trimmed with it.
    fixed = known - got
    assert not fixed, (f"these now resolve, remove them from "
                       f"data/unloaded_seed_files.txt: {sorted(fixed)}")


def test_a_number_written_as_words_is_refused_at_the_seed(tmp_path):
    """A sourcing refusal written into the value column rather than left out.

    data/assumptions/amgn_tavneos.csv carried
    `penetration_peak_pct,,,REFUSED - see note` for a day. assumptions.load reads
    `value if value is not None else text_value`, so the string reached
    forecast.s_curve as `peak * funnel` and raised "can't multiply sequence by
    non-int of type 'float'" from inside the build, naming neither the key nor the
    asset nor the file. Every catalyst on Amgen stopped pricing.
    """
    import db as _db
    path = str(tmp_path / "seeds.db")
    _db.init(path)
    conn = _db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Tavneos', 1)")
    conn.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "amgn_tavneos.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"
        "AMGN,Tavneos,,US,base,penetration_peak_pct,,,REFUSED - see note,,src,n\n"
        "AMGN,Tavneos,,US,base,therapy_mode,,,marketed,,src,n\n"
        "AMGN,Tavneos,,US,base,base_revenue,,459.0,,mm USD,src,n\n", encoding="utf-8")
    out = A.load_seeds(conn, seeds)
    # The two good rows land and the refusal does not.
    assert out["written"] == 2
    assert len(out["refused"]) == 1
    said = out["refused"][0]
    assert "amgn_tavneos.csv" in said and "penetration_peak_pct" in said
    assert "'REFUSED - see note'" in said
    held = conn.execute("SELECT key FROM assumptions WHERE asset_id = 1").fetchall()
    assert {r["key"] for r in held} == {"therapy_mode", "base_revenue"}
    conn.close()


def test_a_text_key_still_takes_its_text(tmp_path):
    """The guard is for keys the engine multiplies. therapy_mode is a word and must
    keep arriving as one."""
    import db as _db
    path = str(tmp_path / "seeds2.db")
    _db.init(path)
    conn = _db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Tavneos', 1)")
    conn.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "x.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"
        "AMGN,Tavneos,,US,base,therapy_mode,,,marketed,,src,n\n", encoding="utf-8")
    out = A.load_seeds(conn, seeds)
    assert out["written"] == 1 and out["refused"] == []
    assert conn.execute("SELECT text_value FROM assumptions WHERE key='therapy_mode'"
                        ).fetchone()[0] == "marketed"
    conn.close()


def test_the_shipped_seeds_carry_no_number_written_as_words():
    """The guard over the book itself: no seed file may hold a numeric key with no
    value."""
    import csv as _csv
    import pathlib as _pl
    bad = []
    for path in sorted(_pl.Path(A.SEED_DIR).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            lines = [l for l in handle if not l.lstrip().startswith("#")]
        for row in _csv.DictReader(lines):
            key = (row.get("key") or "").strip()
            if key in A._NUMERIC_KEYS and str(row.get("value") or "").strip() == "":
                bad.append(f"{path.name}: {key}")
    assert bad == [], bad


# --- a seed file can correct what it wrote, and nothing else -----------------

_SEED_HEADER = ("ticker,brand,indication,region,scenario,key,year,value,text_value,"
                "unit,source,note\n")


def _seed_book(tmp_path):
    import db as _db
    path = str(tmp_path / "reconcile.db")
    _db.init(path)
    conn = _db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'PFE', 'Pfizer')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Tukysa', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Colorectal Neoplasms')")
    conn.execute("INSERT INTO indications (id, name) VALUES (2, 'First-line HER2-positive"
                 " metastatic colorectal cancer')")
    conn.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    return conn, seeds


def _row(conn, key, indication_id=None):
    return conn.execute(
        "SELECT value, source FROM assumptions WHERE asset_id = 1 AND key = ?"
        " AND IFNULL(indication_id, 0) = IFNULL(?, 0)", (key, indication_id)).fetchone()


def test_a_value_corrected_in_the_file_reaches_the_row_it_wrote(tmp_path):
    """The bug. The nightly run restores yesterday's database and reseeds on top, and
    a loader that only inserts can never carry a correction: Arcturus's cost charge was
    changed in its file and the published book kept the old figure."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,other_costs_pct,,-0.0017,,,s,n\n")
    A.load_seeds(conn, seeds)
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,other_costs_pct,,0.0,,,s,n\n")
    out = A.load_seeds(conn, seeds)
    assert out["corrected"] == 1
    assert _row(conn, "other_costs_pct")["value"] == 0.0
    conn.close()


def test_a_pool_moved_to_another_indication_is_held_once(tmp_path):
    """Tukysa's first-line colorectal pool was moved from the approved disease row onto
    its sub-population row. Insert-only kept both, which is the same patients twice."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER +
                 "PFE,Tukysa,Colorectal Neoplasms,US,base,prevalence,,158850,,,s,n\n")
    A.load_seeds(conn, seeds)
    f.write_text(_SEED_HEADER + "PFE,Tukysa,First-line HER2-positive metastatic "
                 "colorectal cancer,US,base,prevalence,,158850,,,s,n\n")
    out = A.load_seeds(conn, seeds)
    assert out["retracted"] == 1
    assert _row(conn, "prevalence", 1) is None
    assert _row(conn, "prevalence", 2)["value"] == 158850
    conn.close()


def test_an_edit_made_in_the_terminal_survives_a_corrected_file(tmp_path):
    """The promise that matters most and that this must not break. A row an analyst has
    edited is the analyst's, whatever the file says afterwards."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,other_costs_pct,,-0.0017,,,s,n\n")
    A.load_seeds(conn, seeds)
    A.save(conn, 1, [{"key": "other_costs_pct", "value": -0.05, "source": "analyst"}],
           reason="correction")
    conn.commit()
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,other_costs_pct,,0.0,,,s,n\n")
    out = A.load_seeds(conn, seeds)
    assert out["corrected"] == 0
    assert _row(conn, "other_costs_pct")["value"] == -0.05
    # And taking it out of the file does not either. Another row keeps the asset
    # covered, or this would pass for the wrong reason (see the test below).
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,therapy_mode,,,marketed,,s,n\n")
    assert A.load_seeds(conn, seeds)["retracted"] == 0
    assert _row(conn, "other_costs_pct")["value"] == -0.05
    conn.close()


def test_a_row_changed_outside_the_ledger_is_left_alone(tmp_path):
    """The rates refresh writes risk_free straight into the table. A row that no longer
    holds what the seed wrote has been touched by something, and is not the file's."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,risk_free,,0.0501,,,s,n\n")
    A.load_seeds(conn, seeds)
    conn.execute("UPDATE assumptions SET value = 0.0505 WHERE key = 'risk_free'")
    conn.commit()
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,risk_free,,0.0499,,,s,n\n")
    assert A.load_seeds(conn, seeds)["corrected"] == 0
    assert _row(conn, "risk_free")["value"] == 0.0505
    conn.close()


def test_a_row_that_arrived_by_a_fold_is_never_the_files(tmp_path):
    """asset_merge moves a folded asset's rows onto the survivor and leaves their ledger
    filed under the asset that is gone. Such a row has no entry under its new asset, so
    the reconcile cannot see it as the seed's and cannot retract it, whatever the
    survivor's own file says."""
    conn, seeds = _seed_book(tmp_path)
    (seeds / "pfe_tukysa.csv").write_text(
        _SEED_HEADER + "PFE,Tukysa,,US,base,therapy_mode,,,marketed,,s,n\n")
    A.load_seeds(conn, seeds)
    # A row moved in from a folded asset: present on the survivor, ledger elsewhere.
    conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value, source)"
                 " VALUES (1, 'US', 'base', 'base_revenue', 1000.0, 'from the fold')")
    conn.execute("INSERT INTO assumption_edits (asset_id, region, scenario, key, op,"
                 " new_value, reason) VALUES (99, 'US', 'base', 'base_revenue', 'create',"
                 " '1000.0', 'initial_seed')")
    conn.commit()
    assert A.load_seeds(conn, seeds)["retracted"] == 0
    assert _row(conn, "base_revenue")["value"] == 1000.0
    conn.close()


def test_retraction_waits_while_an_indication_does_not_resolve(tmp_path):
    """Where one of an asset's rows names an indication the book does not hold yet, the
    file's whole intention for that asset cannot be read, so nothing is taken away."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER +
                 "PFE,Tukysa,Colorectal Neoplasms,US,base,prevalence,,158850,,,s,n\n")
    A.load_seeds(conn, seeds)
    f.write_text(_SEED_HEADER +
                 "PFE,Tukysa,A disease not yet built,US,base,prevalence,,158850,,,s,n\n")
    assert A.load_seeds(conn, seeds)["retracted"] == 0
    assert _row(conn, "prevalence", 1)["value"] == 158850
    conn.close()


def test_every_correction_is_in_the_ledger(tmp_path):
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,therapy_mode,,,marketed,,s,n\n" +
                 "PFE,Tukysa,,US,base,other_costs_pct,,-0.0017,,,s,n\n")
    A.load_seeds(conn, seeds)
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,therapy_mode,,,marketed,,s,n\n")
    assert A.load_seeds(conn, seeds)["retracted"] == 1
    last = conn.execute("SELECT op, reason FROM assumption_edits WHERE key = "
                        "'other_costs_pct' ORDER BY id DESC LIMIT 1").fetchone()
    assert (last["op"], last["reason"]) == ("delete", "seed_correction")
    conn.close()


def test_a_blank_cell_is_the_same_as_no_value():
    """The CSV hands back "" for a blank note and the table holds NULL. Treating those
    as different flagged fifteen untouched rows on the first dry run."""
    assert A._same("", None) and A._same(None, "  ") and A._same(1, 1.0)
    assert not A._same("x", None) and not A._same(0.0, 0.0017)


def test_an_asset_no_file_resolves_to_is_left_whole(tmp_path):
    """The boundary, chosen on purpose. A file that resolves to nothing for an asset
    reads the same whether its model was deliberately removed or its brand string simply
    stopped matching after a rename or a fold, and only one of those should empty the
    asset. So an asset no file covers keeps its rows, and removing a model is done in
    the terminal, where it is a decision with a reason."""
    conn, seeds = _seed_book(tmp_path)
    f = seeds / "pfe_tukysa.csv"
    f.write_text(_SEED_HEADER + "PFE,Tukysa,,US,base,other_costs_pct,,-0.0017,,,s,n\n")
    A.load_seeds(conn, seeds)
    f.write_text(_SEED_HEADER)
    assert A.load_seeds(conn, seeds)["retracted"] == 0
    assert _row(conn, "other_costs_pct")["value"] == -0.0017
    conn.close()
