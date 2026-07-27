"""The derived analytics: revenue at risk, slippage, catalyst grid, screen,
as-of, annotations, and the materiality thresholds behind them.

All seeded; no network. Every module is tested on three paths: populated, empty,
and the null-input case, because a missing input must surface as null or a count,
never as a computed placeholder.
"""

import datetime as dt
import json

import pytest

import annotations
import asof
import asset_revenue
import catalyst_grid
import catalysts as catalysts_module
import db
import diff
import materiality
import screen
import seed
import slippage


TODAY = dt.date.today()
THIS_YEAR = TODAY.year


def _base(db_file):
    db.init(db_file)
    seed.load_companies(db_file)


def _asset(conn, ticker, brand, code=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker=?",
                       (ticker,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, internal_code, modality,"
        " is_marketed) VALUES (?, ?, ?, 'small molecule', 1)",
        (cid, brand, code or brand.upper()))
    return cur.lastrowid


def _protect(conn, asset_id, expiry, protection="patent"):
    conn.execute(
        "INSERT INTO exclusivities (asset_id, protection_type, identifier,"
        " expiry_date, source) VALUES (?, ?, 'X', ?, 'orange_book')",
        (asset_id, protection, expiry))


def _price(conn, asset_id, value, year=None, unit="USD"):
    conn.execute(
        "INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
        " VALUES (?, ?, ?, ?)", (asset_id, year or THIS_YEAR - 1, value, unit))


# --- materiality ------------------------------------------------------------
def test_a_phase_three_slip_over_the_threshold_is_high():
    assert materiality.slip_significance(
        "Phase 3", "2027-01-01", "2027-03-01") == "high"


def test_a_small_phase_three_slip_stays_medium():
    assert materiality.slip_significance(
        "Phase 3", "2027-01-01", "2027-01-20") == "medium"


def test_an_early_phase_slip_stays_medium_at_any_size():
    assert materiality.slip_significance(
        "Phase 2", "2027-01-01", "2028-06-01") == "medium"


def test_restatement_threshold_is_five_percent():
    assert materiality.restatement_is_material(10.0, 10.6)
    assert not materiality.restatement_is_material(10.0, 10.4)
    assert not materiality.restatement_is_material(None, 10.0)


def test_a_material_restatement_lands_in_the_changes_feed(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    asset = _asset(conn, "LLY", "Verzenio")
    _price(conn, asset, 5_000_000_000.0)
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)                    # baseline

    conn = db.get_connection(db_file)
    conn.execute("UPDATE asset_revenue SET value = 5600000000.0")
    conn.commit()
    conn.close()
    summary = diff.detect_changes(db_file)
    assert summary["restatements"] == 1

    conn = db.get_connection(db_file)
    row = conn.execute("SELECT * FROM changes WHERE change_type ="
                       " 'revenue_restatement'").fetchone()
    conn.close()
    assert row["significance"] == "high"
    assert "Verzenio" in row["new_value"]


def test_a_small_revenue_drift_is_resnapshotted_silently(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    asset = _asset(conn, "LLY", "Verzenio")
    _price(conn, asset, 5_000_000_000.0)
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)
    conn = db.get_connection(db_file)
    conn.execute("UPDATE asset_revenue SET value = 5100000000.0")  # 2%
    conn.commit()
    conn.close()
    assert diff.detect_changes(db_file)["restatements"] == 0


# --- revenue at risk --------------------------------------------------------
def _seed_at_risk(db_file):
    _base(db_file)
    conn = db.get_connection(db_file)
    priced = _asset(conn, "LLY", "Priced")
    _protect(conn, priced, f"{THIS_YEAR + 2}-06-01")
    _price(conn, priced, 6_000_000_000.0)
    unpriced = _asset(conn, "LLY", "Unpriced")
    _protect(conn, unpriced, f"{THIS_YEAR + 2}-09-01")
    orphan = _asset(conn, "LLY", "Orphan")
    _protect(conn, orphan, f"{THIS_YEAR + 1}-01-01", "orphan exclusivity")
    safe = _asset(conn, "LLY", "Safe")
    _protect(conn, safe, f"{THIS_YEAR + 20}-01-01")
    _price(conn, safe, 4_000_000_000.0)
    conn.commit()
    conn.close()


def test_revenue_at_risk_shares_and_the_unpriced_band(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_at_risk(db_file)
    built = asset_revenue.build_revenue_at_risk(db_file, "LLY")

    assert built["priced_total"] == pytest.approx(10_000_000_000.0)
    year = str(THIS_YEAR + 2)
    assert built["share_by_year"][year] == pytest.approx(0.6)   # 6bn of 10bn
    assert built["unpriced_by_year"][year] == 1                 # drawn, not imputed
    assert built["cumulative_share"][year] == pytest.approx(0.6)
    assert built["share_5y"] == pytest.approx(0.6)              # Safe is 20y out
    # The orphan expiry is not a cliff and appears nowhere.
    assert all("Orphan" not in str(b["covered"]) + str(b["uncovered"])
               for b in built["buckets"])


def test_revenue_at_risk_with_no_revenue_rows_is_null_not_zero(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    bare = _asset(conn, "GSK", "Bare")
    _protect(conn, bare, f"{THIS_YEAR + 1}-01-01")
    conn.commit()
    conn.close()
    built = asset_revenue.build_revenue_at_risk(db_file, "GSK")
    assert built["priced_total"] is None
    assert built["share_5y"] is None                            # not 0, unknown
    assert built["unpriced_by_year"][str(THIS_YEAR + 1)] == 1


def test_revenue_at_risk_unknown_ticker_is_none(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    assert asset_revenue.build_revenue_at_risk(db_file, "ZZZ") is None


def test_universe_at_risk_carries_shares_never_mixed_currency_sums(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_at_risk(db_file)
    built = asset_revenue.build_universe_at_risk(db_file)
    lly = next(r for r in built["rows"] if r["ticker"] == "LLY")
    assert lly["share_5y"] == pytest.approx(0.6)
    # Shares stay each company's own; with no FX rates stored the USD figure is null.
    assert "own tagged product revenue" in built["note"]
    assert built["fx_as_of"] is None
    assert lly["priced_total_usd"] is None


# --- slippage ----------------------------------------------------------------
def _move_trial(db_file, nct, dates):
    """Baseline a trial then walk its completion date through ``dates``."""
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase,"
        " overall_status, primary_completion_date) VALUES (?, ?, 'T', 'Phase 3',"
        " 'Recruiting', ?)", (nct, cid, dates[0]))
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)
    for date in dates[1:]:
        conn = db.get_connection(db_file)
        conn.execute("UPDATE trials SET primary_completion_date=? WHERE nct_id=?",
                     (date, nct))
        conn.commit()
        conn.close()
        diff.detect_changes(db_file)


def test_slippage_accumulates_across_observations(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    _move_trial(db_file, "NCT_SLIP", ["2027-01-01", "2027-02-01", "2027-03-15"])
    _move_trial(db_file, "NCT_PULL", ["2027-06-01", "2027-05-01"])

    built = slippage.build(db_file)
    rows = {r["nct_id"]: r for r in built["rows"]}
    assert rows["NCT_SLIP"]["days_moved"] == 73        # first old to latest new
    assert rows["NCT_SLIP"]["observations"] == 2
    assert rows["NCT_PULL"]["days_moved"] == -31

    summary = built["summary"][0]
    assert summary["ticker"] == "LLY"
    assert summary["slipped"] == 1 and summary["pulled_in"] == 1


def test_slippage_ticker_filter_and_empty_state(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    assert slippage.build(db_file) == {"rows": [], "summary": [], "ticker": None}
    _move_trial(db_file, "NCT_X", ["2027-01-01", "2027-02-01"])
    assert slippage.build(db_file, ticker="MRK")["rows"] == []
    assert len(slippage.build(db_file, ticker="lly")["rows"]) == 1


# --- catalyst grid -------------------------------------------------------
def test_catalyst_grid_counts_weights_and_flags(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    soon = (TODAY + dt.timedelta(days=7)).isoformat()
    later = (TODAY + dt.timedelta(days=200)).isoformat()
    catalysts_module.add_catalyst(db_file, "LLY", "data readout", soon, "R1")
    catalysts_module.add_catalyst(db_file, "LLY", "data readout", later, "R2")
    # an uncurated PDUFA extraction, distinctly marked
    catalysts_module.add_catalyst(db_file, "MRK", "PDUFA", later, "P1",
                                  is_curated=0)

    built = catalyst_grid.build(db_file, today=TODAY)
    lly_soon = built["cells"]["LLY"][soon[:7]]
    assert lly_soon["count"] == 1 and lly_soon["weight"] == 1.0
    mrk = built["cells"]["MRK"][later[:7]]
    assert mrk["uncurated_pdufa"] is True
    assert mrk["weight"] == pytest.approx(0.85)
    assert built["cells"]["PFE"] == {}                 # absence, not zeros


# --- screen ---------------------------------------------------------------
def test_screen_nulls_every_column_missing_an_input(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    rows = {r["ticker"]: r for r in screen.build_screen(db_file)}
    empty = rows["ROG"]
    assert empty["revenue"] is None
    assert empty["revenue_per_late_trial"] is None     # 0 trials: undefined
    assert empty["loe_share_5y"] is None
    assert empty["ttm_price_change"] is None
    assert empty["catalysts_12m"] == 0                 # a real count, zero is true


def test_screen_computes_revenue_per_late_trial_when_both_exist(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric,"
        " value, unit, fiscal_year) VALUES (?, '2025-12-31', 'FY', 'Revenues',"
        " 60e9, 'USD', 2025)", (cid,))
    for i, phase in enumerate(("Phase 3", "Phase 2/3", "Phase 1")):
        conn.execute(
            "INSERT INTO trials (nct_id, sponsor_company_id, phase,"
            " overall_status) VALUES (?, ?, ?, 'Recruiting')",
            (f"NCT_{i}", cid, phase))
    conn.commit()
    conn.close()
    row = {r["ticker"]: r for r in screen.build_screen(db_file)}["LLY"]
    assert row["late_trials"] == 2                     # Phase 3 + Phase 2/3
    assert row["revenue_per_late_trial"] == pytest.approx(30e9)


# --- as-of ------------------------------------------------------------------
def test_asof_reconstructs_the_earlier_status(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase,"
        " overall_status, primary_completion_date) VALUES ('NCT_A', ?, 'T',"
        " 'Phase 3', 'Recruiting', '2027-06-30')", (cid,))
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)                       # snapshot: Recruiting

    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated'"
                 " WHERE nct_id='NCT_A'")
    # push the second snapshot into tomorrow so the cutoff can sit between them
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)
    conn = db.get_connection(db_file)
    conn.execute("UPDATE snapshots SET captured_at = datetime('now', '+2 days')"
                 " WHERE id = (SELECT MAX(id) FROM snapshots"
                 "             WHERE entity_type='trial')")
    conn.commit()
    conn.close()

    past = asof.state_at(db_file, TODAY.isoformat())
    trial = next(t for t in past["trials"] if t["nct_id"] == "NCT_A")
    assert trial["overall_status"] == "Recruiting"     # the state as of today

    future = asof.state_at(db_file, (TODAY + dt.timedelta(days=3)).isoformat())
    trial = next(t for t in future["trials"] if t["nct_id"] == "NCT_A")
    assert trial["overall_status"] == "Terminated"


def test_asof_rejects_a_bad_date_and_names_prehistory(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    assert asof.state_at(db_file, "not-a-date") is None
    state = asof.state_at(db_file, "2001-01-01")
    assert state["trials"] == []
    assert state["financials"] == {} and state["approvals"] == []
    # With no snapshots at all there is no history to be before.
    assert state["history_begins"] is None


def test_asof_reconstructs_financials_at_field_grain(tmp_path):
    """The financial snapshot in force at the date, not a count."""
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload, captured_at)"
        " VALUES ('financials','company','LLY',?,datetime('now','-10 days'))",
        (json.dumps({"ticker": "LLY", "fiscal_year": 2024, "currency": "USD",
                     "revenue": 45_000_000_000.0, "net_income": 10_000_000_000.0,
                     "rd_expense": 9_000_000_000.0}),))
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload, captured_at)"
        " VALUES ('financials','company','LLY',?,datetime('now','+2 days'))",
        (json.dumps({"ticker": "LLY", "fiscal_year": 2025, "currency": "USD",
                     "revenue": 65_000_000_000.0, "net_income": 20_000_000_000.0,
                     "rd_expense": 13_000_000_000.0}),))
    conn.commit()
    conn.close()

    today = asof.state_at(db_file, TODAY.isoformat())
    assert today["financials"]["LLY"]["revenue"] == pytest.approx(45_000_000_000.0)
    assert today["financials"]["LLY"]["fiscal_year"] == 2024   # the earlier report
    assert today["by_ticker"]["LLY"]["revenue"] == pytest.approx(45_000_000_000.0)

    future = asof.state_at(db_file, (TODAY + dt.timedelta(days=5)).isoformat())
    assert future["financials"]["LLY"]["fiscal_year"] == 2025


def test_asof_reconstructs_approvals_known_by_the_date(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, internal_code)"
                 " VALUES (1, ?, 'Zepbound', 'NDA217806')", (cid,))
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (1, 'NDA217806', '2023-11-08')")
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload, captured_at)"
        " VALUES ('approvals','approval','NDA217806',?,datetime('now','-3 days'))",
        (json.dumps({"ticker": "LLY", "approval_date": "2023-11-08"}),))
    # one that is not known until after the cutoff
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload, captured_at)"
        " VALUES ('approvals','approval','NDA999',?,datetime('now','+5 days'))",
        (json.dumps({"ticker": "LLY", "approval_date": "2026-09-01"}),))
    conn.commit()
    conn.close()

    state = asof.state_at(db_file, TODAY.isoformat())
    apps = {a["application_number"] for a in state["approvals"]}
    assert "NDA217806" in apps and "NDA999" not in apps    # not yet known
    zep = next(a for a in state["approvals"] if a["application_number"] == "NDA217806")
    assert zep["brand_name"] == "Zepbound"                 # joined to current metadata
    assert state["by_ticker"]["LLY"]["approvals_known"] == 1


# --- annotations ------------------------------------------------------------
def test_annotation_roundtrip(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    note_id = annotations.add(db_file, "lly", "company", None,
                              "watching the obesity readout cadence")
    rows = annotations.list_annotations(db_file, ticker="LLY")
    assert len(rows) == 1 and rows[0]["id"] == note_id
    assert rows[0]["entity_type"] == "company"
    assert annotations.delete(db_file, note_id) is True
    assert annotations.list_annotations(db_file) == []


def test_annotation_validation(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    with pytest.raises(ValueError, match="unknown ticker"):
        annotations.add(db_file, "ZZZ", "company", None, "x")
    with pytest.raises(ValueError, match="entity_type"):
        annotations.add(db_file, "LLY", "poem", None, "x")
    with pytest.raises(ValueError, match="body"):
        annotations.add(db_file, "LLY", "company", None, "   ")


def test_annotation_scopes_to_one_entity(tmp_path):
    db_file = tmp_path / "test.db"
    _base(db_file)
    annotations.add(db_file, "LLY", "change", "17", "slip looks structural")
    annotations.add(db_file, "LLY", "catalyst", "9", "date is soft")
    scoped = annotations.list_annotations(db_file, entity_type="change",
                                          entity_id="17")
    assert len(scoped) == 1 and scoped[0]["body"] == "slip looks structural"


def test_screen_converts_revenue_to_one_currency(tmp_path):
    """A comps column that ranks companies cannot hold kroner beside dollars."""
    import db, seed, screen
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    for ticker, value, unit in (("NVO", 300_000_000_000, "DKK"),
                                ("LLY", 60_000_000_000, "USD"),
                                ("ROG", 60_000_000_000, "CHF")):
        cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
        conn.execute("INSERT INTO financials (company_id, period_end, period_type,"
                     " metric, value, unit, fiscal_year, source)"
                     " VALUES (?, '2025-12-31', 'FY', 'Revenues', ?, ?, 2025, 'test')",
                     (cid, value, unit))
    # A rate for DKK but deliberately none for CHF.
    for base, rate in (("DKK", 0.15), ("USD", 1.0)):
        conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of, source)"
                     " VALUES (?, 'USD', ?, '2026-07-24', 'ecb')", (base, rate))
    conn.commit()
    conn.close()

    rows = {r["ticker"]: r for r in screen.build_screen(db_file)}
    assert rows["NVO"]["revenue"] == 300_000_000_000 * 0.15   # converted
    assert rows["NVO"]["reported_revenue"] == 300_000_000_000  # as filed, kept
    assert rows["NVO"]["currency"] == "DKK"
    assert rows["NVO"]["fx_as_of"] == "2026-07-24"
    assert rows["LLY"]["revenue"] == 60_000_000_000            # already dollars
    assert rows["LLY"]["fx_as_of"] is None
    # No rate on file converts to nothing rather than being counted at par.
    assert rows["ROG"]["revenue"] is None
    assert rows["ROG"]["reported_revenue"] == 60_000_000_000


def test_market_cap_uses_the_adr_ratio_not_a_currency_match():
    """An ADS price times an ordinary share count is wrong by the ratio between them."""
    import comps
    # AstraZeneca: 1 ADS is half an ordinary share, and it reports in dollars, so the
    # old currency check passed and the figure came out at half the company.
    assert comps._market_cap(100.0, "USD", 1_000_000, "USD", 0.5) == 200_000_000
    # Novartis: ratio one, so the answer matches the naive product; it was only ever
    # right by that coincidence.
    assert comps._market_cap(100.0, "USD", 1_000_000, "USD", 1.0) == 100_000_000
    # GSK: files in sterling, quoted in dollars per ADS. No rate is needed, because the
    # depositary quote is already dollars.
    assert comps._market_cap(50.0, "USD", 4_000_000, "GBP", 2.0) == 100_000_000
    # A depositary listing with no ratio on file yields nothing rather than a guess.
    assert comps._market_cap(100.0, "USD", 1_000_000, "GBP", None) is None
    # A plain US filer still multiplies directly.
    assert comps._market_cap(100.0, "USD", 1_000_000, "USD", None) == 100_000_000
    # Any missing input yields nothing.
    assert comps._market_cap(None, "USD", 1_000_000, "USD", 1.0) is None
    assert comps._market_cap(100.0, "USD", None, "USD", 1.0) is None


def test_adr_ratios_are_seeded_for_every_foreign_issuer(tmp_path):
    """A foreign issuer without a ratio would silently lose its market cap."""
    import db, seed
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    missing = [r["ticker"] for r in conn.execute(
        """SELECT ticker FROM companies WHERE is_foreign_private_issuer = 1
             AND ticker NOT IN (SELECT ticker FROM adr_ratios)""")]
    conn.close()
    assert missing == [], f"foreign issuers with no ADR ratio: {missing}"


def _seed_cashflow_company(tmp_path, **lines):
    import db, seed
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    flows = ("Revenues", "NetIncomeLoss", "CashFlowOperating", "CapitalExpenditure",
             "OperatingIncomeLoss", "DepreciationAndAmortisation")
    for metric, value in lines.items():
        if value is None:
            continue
        period = "FY" if metric in flows else "instant"
        conn.execute("INSERT INTO financials (company_id, period_end, period_type,"
                     " metric, value, unit, fiscal_year, source)"
                     " VALUES (?, '2025-12-31', ?, ?, ?, 'USD', 2025, 'test')",
                     (cid, period, metric, value))
    conn.commit()
    conn.close()
    return db_file


def test_cashflow_derives_fcf_conversion_and_leverage(tmp_path):
    import cashflow
    db_file = _seed_cashflow_company(
        tmp_path, Revenues=100.0, NetIncomeLoss=20.0, CashFlowOperating=30.0,
        CapitalExpenditure=10.0, OperatingIncomeLoss=25.0,
        DepreciationAndAmortisation=5.0, TotalDebt=60.0, CashAndEquivalents=15.0)
    r = cashflow.build_cashflow(db_file, "LLY")
    assert r["fcf"] == 20.0                    # 30 operating less 10 capex
    assert r["fcf_margin"] == 0.20             # against 100 of revenue
    assert r["cash_conversion"] == 1.0         # 20 of cash on 20 of profit
    assert r["net_debt"] == 45.0               # 60 debt less 15 cash
    assert r["ebitda"] == 30.0                 # 25 operating plus 5 D&A
    assert r["net_debt_ebitda"] == 1.5


def test_cashflow_takes_capex_sign_from_magnitude(tmp_path):
    """Filers tag capital expenditure as an outflow either way round."""
    import cashflow
    db_file = _seed_cashflow_company(
        tmp_path, Revenues=100.0, CashFlowOperating=30.0, CapitalExpenditure=-10.0)
    assert cashflow.build_cashflow(db_file, "LLY")["fcf"] == 20.0


def test_cashflow_leaves_a_ratio_empty_rather_than_guessing(tmp_path):
    import cashflow
    # No debt line and a loss: leverage and conversion have no honest value.
    db_file = _seed_cashflow_company(
        tmp_path, Revenues=100.0, NetIncomeLoss=-5.0, CashFlowOperating=30.0,
        CapitalExpenditure=10.0, CashAndEquivalents=15.0)
    r = cashflow.build_cashflow(db_file, "LLY")
    assert r["fcf"] == 20.0                    # still computable
    assert r["net_debt"] is None               # no debt line filed
    assert r["net_debt_ebitda"] is None
    assert r["cash_conversion"] is None        # undefined on a loss
    assert r["inputs"]["total_debt"] is None   # the blank names its missing line
    assert cashflow.build_cashflow(db_file, "ZZZZ") is None
