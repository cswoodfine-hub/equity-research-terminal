"""Book guards for the gate split and the legs, on the built database.

Every placed asset's gates multiply back to its point; the first gate is the gate odds
the legs carry; and the legs average back to the value the forecast books, so pricing a
gate can never disagree with the headline it sits beside. Skipped, with the reason,
where no built database is on file, the same convention as the ``book`` fixture.
"""

import math
import sqlite3

import pytest

import assumptions
import db
import forecast
import pos_granular as PG


@pytest.fixture(scope="module")
def placed():
    """Every big pharma Phase 2 or 3 asset the book places, read once for the module:
    its inputs, placement, gathered rows, its own legs and the legs in force."""
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        built = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    except sqlite3.OperationalError:
        built = 0
    if not built:
        conn.close()
        pytest.skip(f"the database at {db.DB_PATH} has not been built")
    table = PG.transitions()
    out = []
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM assets WHERE COALESCE(is_marketed, 0) = 0 ORDER BY id")]
        for asset_id in ids:
            if PG._phase(conn, asset_id) not in PG.FROM_PHASE:
                continue
            inputs = assumptions.load(conn, asset_id)
            placement = inputs["pos_granular"]
            if not placement:
                continue
            gathered = PG._gather(conn, asset_id, area=inputs["therapeutic_area"],
                                  phase=inputs["phase"], scalars=inputs["scalars"])
            out.append({
                "id": asset_id, "inputs": inputs, "placement": placement,
                "own": PG.legs(conn, asset_id, placement, gathered, None, table),
                "force": PG.legs(conn, asset_id, placement, gathered, None, table,
                                 stated_pos=PG.stated_pos(inputs["scalars"]))})
    finally:
        conn.close()
    if not out:
        pytest.skip("no placed asset in this book")
    return out


def test_every_placed_assets_gates_multiply_back_to_its_point(placed):
    for row in placed:
        placement = row["placement"]
        if placement["stage"] == "negative":
            assert placement["gates"] == [], row["id"]
            continue
        gates = [g["gate"] for g in placement["gates"]]
        assert gates == [s["gate"] for s in placement["chain"]], row["id"]
        product = math.prod(g["pos"] for g in placement["gates"])
        # resolve rounds its point to four places; the split is the point unrounded.
        assert abs(product - placement["pos"]) <= 5e-5 + 1e-12, row["id"]


def test_the_first_gate_is_the_gate_odds_the_legs_carry(placed):
    """|gates[0].pos - p_gate| is held to 1e-4, widened only by what the four-place
    rounding of today's probability and of the success leg can move a ratio of them:
    p_gate is pos / pos_success with both rounded, which is what makes the legs average
    back exactly. On the 2026-10-05 copy 14 of 280 assets sit past 1e-4 for that reason
    alone, the widest at 1.26e-4: Phase 2 entries with no cut in oncology, such as TUB-040,
    at 0.108 over a 0.4388 success leg against the 0.246 published. The unrounded
    identity has no allowance: the split's later gates are exactly the success leg's."""
    checked = 0
    for row in placed:
        own, placement = row["own"], row["placement"]
        if own is None:
            continue
        checked += 1
        first = placement["gates"][0]["pos"]
        rounding = 5e-5 * (1 + own["p_gate"]) / own["pos_success"]
        assert abs(first - own["p_gate"]) <= max(1e-4, rounding) + 1e-12, row["id"]
        assert placement["gates"][1:] == own["gates"][1:], row["id"]
        assert abs(placement["pos"] - first * own["pos_success"]) < 1e-4, row["id"]
        if placement["stage"] != "mixed":
            assert own["p_gate_published"] == first, row["id"]
    assert checked


def test_the_legs_average_back_to_the_value_the_forecast_books(placed):
    """rNPV is npv x pos in forecast.build, so the success leg weighted by the gate odds,
    with failure at nil, is today's rNPV: the stated probability where one governs."""
    checked = 0
    for row in placed:
        try:
            built = forecast.build(row["inputs"])
        except forecast.ForecastError:
            continue
        force = row["force"]
        if force is None:
            assert built["pos"] == 0.0 or row["placement"]["stage"] == "negative", row["id"]
            continue
        checked += 1
        assert built["pos"] == force["pos_now"], row["id"]
        expected = (force["p_gate"] * built["npv"] * force["pos_success"]
                    + (1 - force["p_gate"]) * built["npv"] * force["pos_failure"])
        tolerance = 1e-9 * max(1.0, abs(built["npv"]))
        assert abs(expected - built["rnpv"]) <= tolerance, row["id"]
    assert checked


def test_a_stated_probability_is_never_published_odds(placed):
    for row in placed:
        force = row["force"]
        if not force or not force["stated"]:
            continue
        assert force["evidence"]["p_gate"] == "implied", row["id"]
        if force["placed"]:
            assert force["placed"] == "stated PoS implies a filing"
            assert force["gate"] == "nda_to_approval" and force["pos_success"] == 1.0
            assert force["p_gate_published"] is None
            assert force["pos_now"] >= force["pos_success_at_gate"] - PG.STATED_PAST_GATE
        else:
            assert force["pos_now"] < force["pos_success"] - PG.STATED_PAST_GATE \
                or force["gate"] == "nda_to_approval", row["id"]
