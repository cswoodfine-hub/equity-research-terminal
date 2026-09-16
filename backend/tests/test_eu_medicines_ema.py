"""EMA medicines data, parsed from a real slice of the published JSON, no network."""

import json
from pathlib import Path

import db
from fetchers.eu_medicines_ema import EuMedicinesFetcher, parse_medicines

FIXTURE = Path(__file__).parent / "fixtures" / "ema_medicines.json"


def _payload():
    return json.loads(FIXTURE.read_text())


def test_human_medicines_are_read_with_their_authorisation_date_day_first():
    rows = {r["name"]: r for r in parse_medicines(_payload())}
    assert "Cirbloc" not in rows                       # veterinary
    assert rows["Ozempic"]["authorised_on"] == "2018-02-08"
    assert rows["Ozempic"]["active_substance"] == "semaglutide"
    assert rows["Wegovy"]["authorised_on"] == "2022-01-06"
    assert rows["Zumrad"]["authorised_on"] is None      # application withdrawn, never authorised


def test_generics_and_biosimilars_are_flagged():
    rows = {r["name"]: r for r in parse_medicines(_payload())}
    assert rows["Apixaban Accord"]["is_generic"] == 1 and rows["Eliquis"]["is_generic"] == 0
    assert rows["Imraldi"]["is_biosimilar"] == 1 and rows["Humira"]["is_biosimilar"] == 0


def test_upsert_stores_one_row_per_product(tmp_path):
    path = str(tmp_path / "ema.db")
    db.init(path)
    fetcher = EuMedicinesFetcher(path)
    rows = parse_medicines(_payload())
    fetcher.upsert(rows)
    fetcher.upsert(rows)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM eu_medicines").fetchone()[0] == len(rows)
    assert conn.execute("SELECT authorised_on FROM eu_medicines WHERE name = 'Eliquis'"
                        ).fetchone()[0] == "2011-05-18"
