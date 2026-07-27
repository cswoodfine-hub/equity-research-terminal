"""Reading a company's bought pipeline through the companies it bought."""

import acquired_sponsors
import db


def _seed(tmp_path):
    path = str(tmp_path / "acq.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    for kind, party, date in (
            ("acquisition", "Centessa Pharmaceuticals", "2026-03-31"),
            ("acquisition", "Verve Therapeutics", "2025-08-07"),
            # A licence leaves the studies with the licensor.
            ("licensing", "Innovent Biologics", "2026-02-09"),
            # Too old: the registry has moved these records across by now.
            ("acquisition", "Loxo Oncology", "2019-01-07"),
            # One short word matches sponsors that have nothing to do with the deal.
            ("acquisition", "Engage", "2026-05-20")):
        conn.execute(
            "INSERT INTO deals (company_id, deal_type, counterparty, event_date)"
            " VALUES (?, ?, ?, ?)", (cid, kind, party, date))
    conn.commit()
    conn.close()
    return path


def test_only_recent_acquisitions_are_searched(tmp_path):
    names = acquired_sponsors.for_company(_seed(tmp_path), "LLY",
                                          today=__import__("datetime").date(2026, 7, 27))
    assert names == ["Centessa Pharmaceuticals", "Verve Therapeutics"]


def test_a_name_must_be_specific_enough_to_search_with():
    assert acquired_sponsors._plausible("Centessa Pharmaceuticals")
    assert acquired_sponsors._plausible("AtaiBeckley")
    assert not acquired_sponsors._plausible("Engage")
    assert not acquired_sponsors._plausible("")


def test_a_study_is_kept_only_when_the_registry_agrees():
    study = {"protocolSection": {"sponsorCollaboratorsModule": {
        "leadSponsor": {"name": "Centessa Pharmaceuticals (UK) Limited"}}}}
    assert acquired_sponsors.sponsored_by(study, ["Centessa Pharmaceuticals"]) \
        == "Centessa Pharmaceuticals (UK) Limited"
    # A loose query match led by someone else is a coincidence, not an acquisition.
    other = {"protocolSection": {"sponsorCollaboratorsModule": {
        "leadSponsor": {"name": "University of Oxford"}}}}
    assert acquired_sponsors.sponsored_by(other, ["Centessa Pharmaceuticals"]) is None
    assert acquired_sponsors.sponsored_by({}, ["Centessa"]) is None
