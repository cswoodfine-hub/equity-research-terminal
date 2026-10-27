"""Book guards for the derived stakes, on the built database.

Each big pharma gate is priced on one catalyst at most, its stake is NPV times the
success leg at the holder's share, and every catalyst left unpriced names a reason from
the published set. Pricing never writes: the database is byte-for-byte as it was.
Skipped, with the reason, where no built database is on file.
"""

import sqlite3

import pytest

import db
import forecast_view as V


@pytest.fixture(scope="module")
def stakes():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        tickers = [r[0] for r in conn.execute("SELECT ticker FROM companies ORDER BY ticker")]
    except sqlite3.OperationalError:
        tickers = []
    finally:
        conn.close()
    if not tickers:
        pytest.skip(f"the database at {db.DB_PATH} has not been built")
    before = db.DB_PATH.stat().st_mtime_ns
    out = {t: V.catalyst_stakes(None, t) for t in tickers}
    assert db.DB_PATH.stat().st_mtime_ns == before, "pricing must never write"
    return out


def test_each_gate_is_priced_on_one_catalyst_at_most(stakes):
    """A derived gate once per asset and gate, stated legs once per asset, and an
    indication layer once per indication.

    The third case is the layer gate, which did not exist when this was written and
    which everything other than "derived" fell into as if it were a stated leg. A
    product can carry two layers that resolve independently: Imfinzi's bladder layer
    reads out in June 2027 and its oesophageal layer in August 2028, on different
    diseases, worth 141 and 1,876 a share. Both should be priced, and
    forecast_view._layer_gate says so in as many words -- "One readout per indication".
    The invariant is unchanged; only the unit it is keyed on is right for the basis."""
    for ticker, got in stakes.items():
        seen = {}
        for row in got["priced"]:
            if row["legs_basis"] == "derived":
                key = (row["asset_id"], row["gate"])
            elif row["legs_basis"] == "indication layer":
                key = (row["asset_id"], "layer", row["asset_indication_id"])
            else:
                key = (row["asset_id"], "stated")
            assert key not in seen, (ticker, key, seen.get(key), row["id"])
            seen[key] = row["id"]


def test_a_derived_stake_is_npv_times_the_success_leg(stakes):
    for ticker, got in stakes.items():
        for row in (r for r in got["priced"] if r["legs_basis"] == "derived"):
            assert row["pos_failure"] == 0.0 and row["rnpv_failure"] == 0.0
            npv = row["rnpv_now"] / row["pos_now"]
            assert row["swing"] == pytest.approx(npv * row["pos_success"], rel=1e-9)
            assert row["p_gate"] * row["pos_success"] == pytest.approx(row["pos_now"],
                                                                      rel=1e-12)
            assert row["resolvable"] == (V.DERIVED_RESOLVE and row["gate"] == "p3_to_nda"), \
                (ticker, row["id"])


def test_every_unpriced_catalyst_names_a_published_reason(stakes):
    for ticker, got in stakes.items():
        for row in got["unpriced"]:
            assert row["reason"] in V.STAKE_REASONS, (ticker, row["id"], row["reason"])
            assert row["why"] and row["why"].endswith("."), (ticker, row["id"])
