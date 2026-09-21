"""CMS decorates a drug name, and an exact match dropped the decorated lines.

259 of the 799 Part B rows carry a footnote marker, and some carry the billing code the
line is reported under. Matching the decorated string lost 110 assets and $6,890mm of
2024 spending, Prolia, Orencia, Comirnaty, Botox and the whole infliximab series among
them, which is why an earlier attempt to measure biologic erosion from CMS found almost
no observations.
"""

from __future__ import annotations

import json
import pathlib

import db
from fetchers.demand_cms import DemandCmsFetcher, _norm

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "cms_part_b_footnotes.json"


def test_a_decorated_name_reduces_to_the_name():
    assert _norm("Prolia*") == "prolia"
    assert _norm("Comirnaty *") == "comirnaty"
    assert _norm("Actemra (J3262)") == "actemra"
    assert _norm("Afluria Trivalent  (90657)*") == "afluria trivalent"   # either order
    assert _norm("Keytruda") == "keytruda"
    # A name that merely contains digits in brackets is not a billing code.
    assert _norm("Prevnar 13") == "prevnar 13"


def _db(tmp_path):
    path = str(tmp_path / "demand.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'AMGN','Amgen'),"
                 " (2,'ROG','Roche'), (3,'JNJ','J&J'), (4,'MRK','Merck'),"
                 " (5,'REGN','Regeneron'), (6,'SNY','Sanofi')")
    conn.execute("""INSERT INTO assets (id, owner_company_id, brand_name, generic_name)
        VALUES (10,1,'Prolia','Denosumab'), (11,2,'Actemra','Tocilizumab'),
               (12,4,'Keytruda','Pembrolizumab'),
               (13,3,NULL,'Infliximab'),
               (14,5,'Dupixent','Dupilumab'), (15,6,'Dupixent','Dupilumab')""")
    conn.commit()
    return path, conn


def test_the_decorated_rows_reach_their_assets(tmp_path):
    path, conn = _db(tmp_path)
    conn.close()
    fetcher = DemandCmsFetcher(path)
    raw = [{**row, "_part": "B"} for row in json.loads(FIXTURE.read_text())]
    rows = fetcher.normalise(raw)
    got = {r["brand"]: r["asset_id"] for r in rows}
    assert got["Prolia*"] == 10            # the footnote no longer hides it
    assert got["Actemra (J3262)"] == 11    # nor does the billing code
    assert got["Infliximab*"] == 13        # matched on the ingredient CMS names it by
    assert got["Keytruda"] == 12           # an undecorated name still matches
    assert "Nothing We Model*" not in got  # a drug outside the universe is still dropped
    assert all(r["total_spending"] is not None for r in rows)


def test_an_ingredient_two_companies_sell_matches_neither(tmp_path):
    """Regeneron and Sanofi both carry Dupixent, so dupilumab resolves to no asset
    rather than to whichever row was read first."""
    path, conn = _db(tmp_path)
    conn.close()
    fetcher = DemandCmsFetcher(path)
    rows = fetcher.normalise([{"Brnd_Name": "Dupilumab*", "Gnrc_Name": "Dupilumab",
                               "Tot_Spndng_2024": "100", "_part": "B"}])
    assert rows == []
    # But the brand itself still matches, and brands win over ingredients.
    rows = fetcher.normalise([{"Brnd_Name": "Dupixent", "Gnrc_Name": "Dupilumab",
                               "Tot_Spndng_2024": "100", "_part": "B"}])
    assert [r["asset_id"] for r in rows] == [14]
