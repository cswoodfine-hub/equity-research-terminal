"""Catalysts with stakes: the calendar ranked by dollars rather than by date.

The stake is two runs of the same engine the sliders use, one per leg, so a stake can
never say anything the model would not. A catalyst is priced only where the analyst has
put both legs on file; nothing is derived for the rest.
"""

import json

import pytest

import assumptions as A
import catalysts as C
import db
import forecast_view as V


def _seed(tmp_path):
    path = str(tmp_path / "stakes.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'CRSP', 'CRISPR')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Casgevy', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (2, 1, 'Unpriced', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Anemia, Sickle Cell')")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 1.8), ("cogs_per_patient", 0.75),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15),
        ("wacc", 0.10), ("pos", 0.8), ("economics_share", 0.6),
        ("pos_success", 0.95), ("pos_failure", 0.40),
        ("forecast_start_year", 2026), ("forecast_years", 3))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    rows.append({"key": "partner_ticker", "text_value": "CRSP", "source": "t"})
    for year, patients in ((2026, 100), (2027, 200), (2028, 300)):
        rows.append({"key": "new_patients", "indication_id": 1, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 1, rows)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, 258000000, '2025-12-31')")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES"
                 " (10, 1, 1, 'data readout', date('now', '+90 days'),"
                 " 'Phase 3 long-term follow-up', 'NCT1', 'pending')")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES"
                 " (11, 1, 2, 'data readout', date('now', '+30 days'),"
                 " 'A readout on an unpriced asset', 'NCT2', 'pending')")
    conn.commit(); conn.close()
    return path


# --- the ranking ------------------------------------------------------------

def test_a_priced_catalyst_carries_its_swing_and_the_unpriced_says_what_would(tmp_path):
    path = _seed(tmp_path)
    out = V.catalyst_stakes(path, "VRTX")
    assert [r["id"] for r in out["priced"]] == [10]
    row = out["priced"][0]
    # the stake is the arithmetic of the two legs, at the company's share
    up = V.whatif(path, "VRTX", 1, pos=0.95)["varied"]["rnpv"]
    down = V.whatif(path, "VRTX", 1, pos=0.40)["varied"]["rnpv"]
    assert row["swing"] == pytest.approx(up - down)
    assert row["share"] == 0.6
    assert row["share_swing"] == pytest.approx((up - down) * 0.6)
    assert row["per_share"] == pytest.approx((up - down) * 0.6 * 1e6 / 258e6)
    unpriced = out["unpriced"]
    assert [r["id"] for r in unpriced] == [11]
    assert set(unpriced[0]["missing"]) == {"pos_success", "pos_failure"}


def test_the_partner_prices_the_same_event_at_its_share(tmp_path):
    path = _seed(tmp_path)
    out = V.catalyst_stakes(path, "CRSP")
    assert [r["id"] for r in out["priced"]] == [10]
    assert out["priced"][0]["share"] == pytest.approx(0.4)
    # the unpriced asset belongs to Vertex alone and has no partner row
    assert out["unpriced"] == []


def test_priced_rank_by_size_not_date(tmp_path):
    """A second priced catalyst on a nearer date but a smaller swing sorts second."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (3, 1, 'Smaller', 1)")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 0.2), ("cogs_per_patient", 0.05),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15),
        ("wacc", 0.10), ("pos", 0.5), ("pos_success", 0.6), ("pos_failure", 0.4),
        ("forecast_start_year", 2026), ("forecast_years", 3))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    rows.append({"key": "new_patients", "indication_id": 1, "year": 2026,
                 "value": 50, "source": "t"})
    A.save(conn, 3, rows)
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, status) VALUES (12, 1, 3, 'data readout',"
                 " date('now', '+10 days'), 'Sooner but smaller', 'pending')")
    conn.commit(); conn.close()
    out = V.catalyst_stakes(path, "VRTX")
    assert [r["id"] for r in out["priced"]] == [10, 12]     # size first, not date


# --- resolve ----------------------------------------------------------------

def test_resolve_steps_the_pos_and_keeps_both_sides_of_history(tmp_path):
    path = _seed(tmp_path)
    before = V.asset_forecast(path, "VRTX", 1)["result"]["rnpv"]
    out = V.resolve_catalyst(path, "VRTX", 10, "missed")
    assert out["pos_applied"] == 0.40
    after = V.asset_forecast(path, "VRTX", 1)["result"]
    assert after["pos"] == 0.40
    assert after["pos_basis"] == "stated"
    assert after["rnpv"] == pytest.approx(before * 0.40 / 0.80)
    conn = db.get_connection(path)
    # the catalyst left the calendar with the outcome on its row
    assert conn.execute("SELECT status FROM catalysts WHERE id = 10"
                        ).fetchone()[0] == "missed"
    assert "resolved missed" in conn.execute(
        "SELECT description FROM catalysts WHERE id = 10").fetchone()[0]
    assert C.list_catalysts(path, within_days=365, ticker="VRTX") == [
        r for r in C.list_catalysts(path, within_days=365, ticker="VRTX")
        if r["id"] != 10]
    # both sides of the event are on file: the pre snapshot and the post one
    snaps = [json.loads(r[0]) for r in conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'forecast'"
        " AND entity_key = '1' ORDER BY id")]
    conn.close()
    assert len(snaps) >= 2
    assert snaps[-2]["pos"] == pytest.approx(0.80)      # pre-event
    assert snaps[-1]["pos"] == pytest.approx(0.40)      # post-event


def test_resolve_refuses_what_it_should(tmp_path):
    path = _seed(tmp_path)
    with pytest.raises(ValueError):                      # not an outcome
        V.resolve_catalyst(path, "VRTX", 10, "maybe")
    with pytest.raises(ValueError):                      # no priced leg on file
        V.resolve_catalyst(path, "VRTX", 11, "met")
    assert V.resolve_catalyst(path, "LLY", 10, "met") is None    # unknown ticker
    V.resolve_catalyst(path, "VRTX", 10, "met")
    with pytest.raises(ValueError):                      # already resolved
        V.resolve_catalyst(path, "VRTX", 10, "missed")


def test_the_partner_can_resolve_too(tmp_path):
    """CRISPR watches the same readout; either side of the economics may record it."""
    path = _seed(tmp_path)
    out = V.resolve_catalyst(path, "CRSP", 10, "met")
    assert out["pos_applied"] == 0.95


def test_a_resolved_catalyst_leaves_list_catalysts(tmp_path):
    path = _seed(tmp_path)
    assert {r["id"] for r in C.list_catalysts(path, 365, "VRTX")} == {10, 11}
    V.resolve_catalyst(path, "VRTX", 10, "met")
    assert {r["id"] for r in C.list_catalysts(path, 365, "VRTX")} == {11}


def test_list_catalysts_now_carries_the_asset_handle(tmp_path):
    path = _seed(tmp_path)
    row = C.list_catalysts(path, 365, "VRTX")[0]
    assert "asset_id" in row and "status" in row
