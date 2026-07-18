"""parse_drugsfda runs against a saved drugsfda payload, no network."""

import json
from pathlib import Path

from fetchers.approvals_openfda import parse_drugsfda

FIXTURE = Path(__file__).parent / "fixtures" / "drugsfda_lly.json"


def test_parse_drugsfda_nda_and_bla():
    payload = json.loads(FIXTURE.read_text())
    rows = parse_drugsfda(payload, "LLY")
    by_code = {r["internal_code"]: r for r in rows}

    # An NDA and a BLA are kept; an application with no original approval is dropped.
    assert set(by_code) == {"NDA21368", "BLA205692"}

    cialis = by_code["NDA21368"]
    assert cialis["brand"] == "Cialis"
    assert cialis["modality"] == "small molecule"
    assert cialis["approval_date"] == "2003-11-21"

    basaglar = by_code["BLA205692"]
    assert basaglar["modality"] == "biologic"
    assert basaglar["approval_date"] == "2015-12-16"
