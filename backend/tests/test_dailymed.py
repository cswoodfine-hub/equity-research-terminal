"""DailyMed: the pure parsers, the population extraction over the seam, and the
label diff that turns a version increment into the right change type."""

import json
from pathlib import Path

import dailymed
import db
import diff
import seed

_FIX = Path(__file__).resolve().parent / "fixtures"

_SEARCH = json.dumps({"data": [
    {"setid": "aaa", "title": "SOMETHINGELSE (OTHER) TABLET"},
    {"setid": "bbb", "title": "DRUGX (GENERICX) INJECTION, SOLUTION"},
]})

_HISTORY = json.dumps({"data": {"history": [
    {"spl_version": 3, "published_date": "Jan 06, 2026"},
    {"spl_version": 12, "published_date": "May 06, 2026"},
    {"spl_version": 8, "published_date": "Mar 03, 2026"},
]}})


# --- parsers --------------------------------------------------------------
def test_parse_search_matches_the_brand_not_a_near_name():
    assert dailymed.parse_search(_SEARCH, "DrugX", "genericx") == "bbb"
    assert dailymed.parse_search(_SEARCH, "Nonesuch") is None


def test_parse_history_takes_the_highest_version():
    latest = dailymed.parse_history(_HISTORY)
    assert latest == {"spl_version": 12, "published_date": "May 06, 2026"}


def test_parse_history_empty_is_none():
    assert dailymed.parse_history(json.dumps({"data": {"history": []}})) is None


def test_parse_indications_extracts_only_the_loinc_section():
    text = dailymed.parse_indications((_FIX / "spl_indications.xml").read_text())
    assert "moderate to severe plaque psoriasis" in text
    assert "2 years of age" in text
    assert "Not the indications section" not in text   # the dosage block is excluded


def test_parse_indications_absent_section_is_none():
    xml = '<document xmlns="urn:hl7-org:v3"><component/></document>'
    assert dailymed.parse_indications(xml) is None


# --- extraction over the seam ---------------------------------------------
def test_extract_population_parses_model_json():
    def fake(system, user, mx):
        return ('```json\n{"age_floor_years": 2, "age_ceiling_years": null,'
                ' "indication_count": 2, "population_text": "adults and children"}\n```')
    out = dailymed.extract_population("some indications", complete=fake)
    assert out["age_floor_years"] == 2 and out["indication_count"] == 2
    assert out["age_ceiling_years"] is None
    assert out["population_text"] == "adults and children"


def test_extract_population_without_a_model_returns_nulls(monkeypatch):
    # No provider configured: the default path must not fabricate the fields.
    monkeypatch.setattr(dailymed.llm, "provider", lambda: None)
    out = dailymed.extract_population("some indications")
    assert out == {"age_floor_years": None, "age_ceiling_years": None,
                   "indication_count": None, "population_text": None}


def test_extract_population_empty_text_is_null():
    assert dailymed.extract_population("", complete=lambda *a: "{}")[
        "indication_count"] is None


# --- the label diff -------------------------------------------------------
def _label(db_file, setid, version, floor=None, count=None, ceiling=None):
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    asset = conn.execute(
        "SELECT id FROM assets WHERE brand_name='DrugX'").fetchone()
    if asset is None:
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, 'DrugX', 1)", (cid,))
        asset_id = conn.execute("SELECT id FROM assets WHERE brand_name='DrugX'"
                                ).fetchone()[0]
    else:
        asset_id = asset["id"]
    conn.execute(
        """
        INSERT INTO labels (asset_id, setid, drug_name, spl_version,
            age_floor_years, indication_count, age_ceiling_years)
        VALUES (?, ?, 'DrugX', ?, ?, ?, ?)
        ON CONFLICT(setid) DO UPDATE SET spl_version=excluded.spl_version,
            age_floor_years=excluded.age_floor_years,
            indication_count=excluded.indication_count,
            age_ceiling_years=excluded.age_ceiling_years
        """,
        (asset_id, setid, version, floor, count, ceiling))
    conn.commit()
    conn.close()


def _label_changes(db_file):
    conn = db.get_connection(db_file)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT change_type, new_value, significance FROM changes"
            " WHERE entity_type='label'")]
    finally:
        conn.close()


def test_a_version_bump_alone_is_a_label_change(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _label(db_file, "s1", 5, floor=18, count=1)
    diff.detect_changes(db_file)                       # baseline, nothing emitted
    assert _label_changes(db_file) == []
    _label(db_file, "s1", 6, floor=18, count=1)
    assert diff.detect_changes(db_file)["label_changes"] == 1
    rows = _label_changes(db_file)
    assert rows[0]["change_type"] == "label_change"
    assert "version 6" in rows[0]["new_value"]
    # idempotent: re-running detects nothing new
    assert diff.detect_changes(db_file)["label_changes"] == 0


def test_a_new_indication_outranks_a_bare_revision(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _label(db_file, "s1", 5, floor=18, count=1)
    diff.detect_changes(db_file)
    _label(db_file, "s1", 6, floor=18, count=2)        # an indication added
    diff.detect_changes(db_file)
    row = _label_changes(db_file)[0]
    assert row["change_type"] == "new_indication" and row["significance"] == "high"
    assert "1 -> 2" in row["new_value"]


def test_a_dropped_age_floor_is_a_population_expansion(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _label(db_file, "s1", 5, floor=12, count=1)
    diff.detect_changes(db_file)
    _label(db_file, "s1", 6, floor=2, count=1)         # 12 to 2, a real expansion
    diff.detect_changes(db_file)
    row = _label_changes(db_file)[0]
    assert row["change_type"] == "population_expansion"
    assert row["significance"] == "high"
    assert "age floor 12 -> 2" in row["new_value"]
