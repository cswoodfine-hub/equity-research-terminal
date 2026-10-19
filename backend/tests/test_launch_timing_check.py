"""The hand-check tool: it lists the flags and, offline here, says which registry study
the book is missing and whether it would move the floor. It writes nothing."""

import importlib.util
import json
from pathlib import Path

import db

TOOL = Path(__file__).resolve().parent.parent / "tools" / "launch_timing_check.py"


def _tool():
    spec = importlib.util.spec_from_file_location("launch_timing_check", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _book(tmp_path):
    path = str(tmp_path / "check.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'NVS', 'Novartis', 'USD')")
    conn.execute("INSERT INTO indications (id, name) VALUES (10, 'Atrial Fibrillation')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (1, 1, 'Abelacimab', 0)")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, is_lead,"
                 " region) VALUES (1, 10, 'Phase 3', 1, 'US')")
    conn.execute("INSERT INTO assumptions (asset_id, key, value, source) VALUES"
                 " (1, 'forecast_start_year', 2027, 'convention')")
    conn.execute("INSERT INTO trials (nct_id, asset_id, phase, overall_status,"
                 " primary_completion_date, primary_completion_type, conditions,"
                 " fetched_at) VALUES ('NCT07739888', 1, 'Phase 3', 'Not yet recruiting',"
                 " '2030-12-30', 'estimated', '[\"Atrial Fibrillation\"]', datetime('now'))")
    conn.commit()
    conn.close()
    return path


def test_a_registry_study_missing_from_the_book_is_named_with_the_floor_it_gives(
        tmp_path, monkeypatch, capsys):
    path = _book(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    tool = _tool()
    monkeypatch.setattr(tool, "_registry_hits", lambda names: {
        "NCT05712200": {"nct_id": "NCT05712200", "title": "LILAC-TIMI 76",
                        "status": "RECRUITING", "primary_completion": "2027-12-30",
                        "phases": ["PHASE3"], "sponsor": "Anthos Therapeutics, Inc.",
                        "conditions": ["Atrial Fibrillation (AF)"],
                        "matched_on": "Abelacimab"},
        "NCT07739888": {"nct_id": "NCT07739888", "title": "held", "status":
                        "NOT_YET_RECRUITING", "primary_completion": "2030-12-30",
                        "phases": ["PHASE3"], "sponsor": "Novartis", "conditions": [],
                        "matched_on": "Abelacimab"},
        "NCT05171075": {"nct_id": "NCT05171075", "title": "stopped", "status":
                        "TERMINATED", "primary_completion": "2026-04-10",
                        "phases": ["PHASE3"], "sponsor": "Anthos", "conditions": [],
                        "matched_on": "Abelacimab"}})
    before = Path(path).stat().st_mtime_ns
    assert tool.main(["--registry", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["counts"] == {"before_floor": 1}
    (row,) = body["assets"]
    gaps = {g["nct_id"]: g for g in row["registry"]}
    assert set(gaps) == {"NCT05712200", "NCT05171075"}
    assert gaps["NCT05712200"]["floor_year"] == 2028
    assert gaps["NCT05712200"]["lowers_floor"] is True
    assert gaps["NCT05171075"]["floor_year"] is None
    assert Path(path).stat().st_mtime_ns == before


def test_the_plain_listing_names_each_flag_and_its_source(tmp_path, monkeypatch, capsys):
    path = _book(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    assert _tool().main(["NVS"]) == 0
    out = capsys.readouterr().out
    assert "1 unmarketed assets with a seeded start year: before_floor 1" in out
    assert "NVS Abelacimab (asset 1): before_floor" in out
    assert "seed 2027 (base): convention" in out
