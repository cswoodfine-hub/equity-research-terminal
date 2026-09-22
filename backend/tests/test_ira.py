"""The CMS negotiated price file, and what it puts at risk."""

from __future__ import annotations

import pathlib

import db
import ira
from fetchers.negotiated_prices_cms import NegotiatedPricesCmsFetcher

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "cms_negotiated_prices.csv"


def _rows():
    return ira.parse(FIXTURE.read_text())


def test_parse_reads_a_row_per_drug_code_and_period():
    rows = _rows()
    # The blank trailing line and the repeated package code both drop out.
    assert len(rows) == 6
    eliquis = [r for r in rows if r["drug"] == "ELIQUIS"]
    assert {r["effective_from"] for r in eliquis} == {"2026-01-01", "2027-01-01"}
    assert eliquis[0]["ingredient"] == "APIXABAN"
    assert eliquis[0]["ipay"] == 2026


def test_a_price_with_no_end_date_is_the_one_in_force():
    rows = _rows()
    assert ira.current(rows, "ELIQUIS")["mfp_30des"] == 237.25
    # Xarelto's only row was end dated when CMS deselected it, so no price stands.
    assert ira.current(rows, "XARELTO") is None
    # A 2028 drug is selected with no price announced yet.
    assert ira.current(rows, "BIKTARVY") is None


def test_one_price_can_cover_several_brands():
    assert ira.brands("OZEMPIC; RYBELSUS; WEGOVY") == ["OZEMPIC", "RYBELSUS", "WEGOVY"]
    assert ira.brands("ELIQUIS") == ["ELIQUIS"]
    assert ira.brands("") == []


def test_the_ceiling_cut_is_bounded_at_nil_and_needs_both_sides():
    assert ira.ceiling_cut(600.0, 237.25) == 1 - 237.25 / 600.0
    assert ira.ceiling_cut(200.0, 237.25) == 0.0      # a price above what Medicare pays
    assert ira.ceiling_cut(None, 237.25) is None
    assert ira.ceiling_cut(600.0, None) is None


def test_selected_binds_a_drug_to_the_asset_it_is(tmp_path):
    path = tmp_path / "t.db"
    db.init(str(path))
    conn = db.get_connection(str(path))
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('BMY', 'Bristol')")
    company = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name)"
                 " VALUES (?, 'Eliquis', 'apixaban')", (company,))
    asset = conn.execute("SELECT id FROM assets").fetchone()["id"]
    conn.commit()
    conn.close()

    fetcher = NegotiatedPricesCmsFetcher(str(path))
    rows = fetcher.normalise(FIXTURE.read_text())
    fetcher.upsert(rows)

    conn = db.get_connection(str(path))
    try:
        got = {r["brand"]: r for r in ira.selected(conn)}
        assert got["ELIQUIS"]["asset_id"] == asset
        assert got["ELIQUIS"]["ticker"] == "BMY"
        assert got["ELIQUIS"]["mfp_30des"] == 237.25
        assert got["ELIQUIS"]["in_force"] is True
        # A brand the book does not model is reported, not dropped.
        assert got["WEGOVY"]["asset_id"] is None
        assert got["XARELTO"]["in_force"] is False

        # Exposure needs Part D volume; without it the reason says so.
        assert "no Part D spending" in ira.exposure(conn, asset)["reason"]
        conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year,"
                     " total_spending, total_claims) VALUES (?, 'D', 'Eliquis', 2023,"
                     " 1000000.0, 2000)", (asset,))
        conn.commit()
        got = ira.exposure(conn, asset)
        assert got["gross_per_claim"] == 500.0
        assert ira.ceiling_cut(got["gross_per_claim"], 237.25) > 0.5
    finally:
        conn.close()


def test_the_archive_reader_takes_the_csv():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("readme.xlsx", "not this one")
        archive.writestr("prices.csv", FIXTURE.read_text())
    from fetchers import negotiated_prices_cms as mod
    assert "ELIQUIS" in mod.csv_from_zip(buf.getvalue())


def test_a_live_snapshot_says_so_and_a_cache_snapshot_does_not(tmp_path):
    """The weekly TTL is read off a snapshot claiming a live fetch. Without the claim
    CMS was asked for a 5MB zip on every run, and an outage left the same mark as a
    successful pull."""
    import json

    path = str(tmp_path / "ira.db")
    db.init(path)
    fetcher = NegotiatedPricesCmsFetcher(db_path=path)
    assert fetcher._last_live_fetch_at() is None
    assert fetcher._within_ttl() is False

    fetcher.snapshot(_rows())
    assert fetcher._within_ttl() is True
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'cms_mfp'"
        " ORDER BY id DESC LIMIT 1").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "live"
    assert payload["drugs"]["ELIQUIS"]["mfp_30des"] == 237.25
    assert "fetch_kind" not in payload["drugs"]


def test_a_cache_snapshot_leaves_the_ttl_unstarted(tmp_path):
    import json

    path = str(tmp_path / "ira2.db")
    db.init(path)
    fetcher = NegotiatedPricesCmsFetcher(db_path=path)
    fetcher._snapshot_cache()
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'cms_mfp'").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "cache"
    assert fetcher._last_live_fetch_at() is None
    assert fetcher._within_ttl() is False
