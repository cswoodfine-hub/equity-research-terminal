"""Efficacy supplements: parsing the drugsfda submissions, storing them, and
detecting a newly approved one as a label expansion. No network."""

import datetime as dt

import db
import diff
import seed
from fetchers import approvals_openfda as af

_RECENT = (dt.date.today() - dt.timedelta(days=20)).strftime("%Y%m%d")
_OLD = "20180629"

_PAYLOAD = {"results": [{
    "application_number": "BLA125469",
    "products": [{"brand_name": "TRULICITY", "marketing_status": "Prescription"}],
    "submissions": [
        {"submission_type": "ORIG", "submission_number": "1",
         "submission_status": "AP", "submission_status_date": "20140918"},
        {"submission_type": "SUPPL", "submission_number": "17",
         "submission_class_code": "EFFICACY", "submission_status": "AP",
         "submission_status_date": _OLD,
         "submission_class_code_description": "Efficacy"},
        {"submission_type": "SUPPL", "submission_number": "40",
         "submission_class_code": "EFFICACY", "submission_status": "AP",
         "submission_status_date": _RECENT,
         "submission_class_code_description": "Efficacy"},
        {"submission_type": "SUPPL", "submission_number": "41",
         "submission_class_code": "LABELING", "submission_status": "AP",
         "submission_status_date": _RECENT},              # not efficacy, ignored
    ],
}]}


def test_parse_supplements_keeps_only_approved_efficacy():
    rows = af.parse_supplements(_PAYLOAD, "LLY")
    assert {r["submission_number"] for r in rows} == {"17", "40"}
    row = next(r for r in rows if r["submission_number"] == "40")
    assert row["application_number"] == "BLA125469"
    assert row["approval_date"] == f"{_RECENT[:4]}-{_RECENT[4:6]}-{_RECENT[6:8]}"
    assert row["brand"] == "Trulicity"


def test_normalise_returns_both_approvals_and_supplements():
    out = af.ApprovalsOpenFdaFetcher("LLY").normalise(_PAYLOAD)
    assert out["approvals"] and out["supplements"]
    assert out["approvals"][0]["application_number"] == "BLA125469"


def _seed_asset(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, internal_code,"
                 " modality, is_marketed) VALUES (?, 'Trulicity', 'BLA125469',"
                 " 'biologic', 1)", (cid,))
    conn.commit()
    conn.close()


def test_upsert_stores_supplements_against_the_asset(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_asset(db_file)
    fetcher = af.ApprovalsOpenFdaFetcher("LLY", db_file)
    fetcher.upsert(fetcher.normalise(_PAYLOAD))
    conn = db.get_connection(db_file)
    try:
        rows = conn.execute(
            "SELECT submission_number, approval_date, asset_id FROM supplements"
            " ORDER BY submission_number").fetchall()
    finally:
        conn.close()
    assert [r["submission_number"] for r in rows] == ["17", "40"]
    assert all(r["asset_id"] is not None for r in rows)   # resolved to the asset


def _payload(*submission_numbers):
    """A payload carrying only the named efficacy supplements (plus the original)."""
    subs = [{"submission_type": "ORIG", "submission_number": "1",
             "submission_status": "AP", "submission_status_date": "20140918"}]
    dates = {"17": _OLD, "40": _RECENT}
    for number in submission_numbers:
        subs.append({"submission_type": "SUPPL", "submission_number": number,
                     "submission_class_code": "EFFICACY", "submission_status": "AP",
                     "submission_status_date": dates[number]})
    return {"results": [{"application_number": "BLA125469",
                         "products": [{"brand_name": "TRULICITY"}],
                         "submissions": subs}]}


def test_a_newly_seen_recent_supplement_is_detected(tmp_path):
    """A company's first sighting baselines the back catalogue; a supplement that
    appears later and is recent is the event."""
    db_file = tmp_path / "t.db"
    _seed_asset(db_file)
    fetcher = af.ApprovalsOpenFdaFetcher("LLY", db_file)

    # Round one: only the 2018 supplement. Baseline for LLY, nothing emitted.
    fetcher.upsert(fetcher.normalise(_payload("17")))
    assert diff.detect_changes(db_file)["efficacy_supplements"] == 0

    # Round two: a recent supplement appears against a now-baselined company.
    fetcher.upsert(fetcher.normalise(_payload("17", "40")))
    assert diff.detect_changes(db_file)["efficacy_supplements"] == 1
    conn = db.get_connection(db_file)
    try:
        row = conn.execute("SELECT new_value FROM changes"
                           " WHERE change_type='efficacy_supplement'").fetchone()
    finally:
        conn.close()
    assert "Trulicity" in row["new_value"]
    # Idempotent: re-running detects nothing new.
    assert diff.detect_changes(db_file)["efficacy_supplements"] == 0
