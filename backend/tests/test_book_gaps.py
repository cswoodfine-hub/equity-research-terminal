"""The book reports its own gaps: a bought asset with no forecast, a late-stage asset the
engine refuses, an anchor older than the latest filed quarter, a model outside guidance.
Scratch books only; no network."""

import datetime as dt

import book_gaps
import db
import seed

TODAY = dt.date(2026, 11, 27)


def _book(tmp_path):
    path = tmp_path / "gaps.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    return path, conn, cid


def _asset(conn, cid, name, phase, nct="NCT00000001", sponsor="Eli Lilly and Company"):
    cur = conn.execute("INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                       " VALUES (?, ?, 0)", (cid, name))
    asset_id = cur.lastrowid
    ind = conn.execute("INSERT INTO indications (name) VALUES (?)",
                       (f"Disease of {name}",)).lastrowid
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, is_lead)"
                 " VALUES (?, ?, ?, 1)", (asset_id, ind, phase))
    conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                 "  overall_status, lead_sponsor) VALUES (?, ?, ?, ?, 'Recruiting', ?)",
                 (nct, asset_id, cid, phase, sponsor))
    conn.commit()
    return asset_id


def test_a_bought_asset_at_phase_2_with_no_seed_is_named(tmp_path):
    path, conn, cid = _book(tmp_path)
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote)"
                 " VALUES (?, 'acquisition', 'Curevo Inc.', '2026-07-01', 'q')", (cid,))
    bought = _asset(conn, cid, "amezosvatein", "Phase 2", sponsor="Curevo Inc.")
    _asset(conn, cid, "LY0000001", "Phase 2", nct="NCT00000002")     # Lilly's own
    _asset(conn, cid, "KLN-1010", "Phase 1", nct="NCT00000003", sponsor="Curevo Inc.")
    out = book_gaps.bought_unvalued(conn, "LLY", today=TODAY)
    assert [(a["asset"], a["target"], a["reason"]) for a in out["assets"]] == [
        ("amezosvatein", "Curevo Inc.", "no seed")]
    assert [d["counterparty"] for d in out["deals_without_terms"]] == ["Curevo Inc."]
    assert out["assets"][0]["asset_id"] == bought


def test_an_old_acquisition_is_outside_the_window(tmp_path):
    path, conn, cid = _book(tmp_path)
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote)"
                 " VALUES (?, 'acquisition', 'ARMO BioSciences', '2018-06-22', 'q')", (cid,))
    _asset(conn, cid, "pegilodecakin", "Phase 3", sponsor="ARMO BioSciences")
    out = book_gaps.bought_unvalued(conn, "LLY", today=TODAY)
    assert out["assets"] == [] and out["deals_without_terms"] == []


def test_a_late_stage_asset_with_no_seed_and_one_the_engine_refuses_are_named(tmp_path):
    path, conn, cid = _book(tmp_path)
    _asset(conn, cid, "tersolisib", "Phase 3")
    refused = _asset(conn, cid, "mazdutide", "Phase 2/3", nct="NCT00000002")
    conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                 " VALUES (?, 'US', 'base', 'forecast_start_year', 2032)", (refused,))
    _asset(conn, cid, "LY0000001", "Phase 2", nct="NCT00000003")       # not late stage
    conn.commit()
    out = book_gaps.late_stage_unmodelled(conn, "LLY")
    by = {o["asset"]: o for o in out}
    assert set(by) == {"tersolisib", "mazdutide"}
    assert by["tersolisib"]["reason"] == "no seed"
    assert by["mazdutide"]["reason"].startswith("refused: ")
    assert "therapy_mode" in by["mazdutide"]["reason"]


def test_a_filed_asset_counts_as_late_stage(tmp_path):
    path, conn, cid = _book(tmp_path)
    asset = _asset(conn, cid, "LY0000009", "Phase 2")
    conn.execute("INSERT INTO catalysts (company_id, asset_id, catalyst_type, expected_date,"
                 "  title, status) VALUES (?, ?, 'PDUFA', '2027-03-01', 'decision', 'pending')",
                 (cid, asset))
    conn.commit()
    out = book_gaps.late_stage_unmodelled(conn, "LLY")
    assert [(o["asset"], o["phase"]) for o in out] == [("LY0000009", "Filed")]


def test_a_retired_programme_is_not_a_gap(tmp_path):
    path, conn, cid = _book(tmp_path)
    asset = _asset(conn, cid, "gandotinib", "Phase 3")
    conn.execute("INSERT INTO retired_programmes (asset_id, basis) VALUES (?, 'stopped')",
                 (asset,))
    conn.commit()
    assert book_gaps.late_stage_unmodelled(conn, "LLY") == []


def test_the_cited_period_is_the_latest_quarter_the_anchor_names():
    assert book_gaps.cited_period(
        "the first half of 2026 as reported, 18,605mm, and the second half at the second "
        "quarter's pace. Lilly's second-quarter 2026 results") == "2026-06-30"
    assert book_gaps.cited_period(
        "the nine months of 2026 as reported and the fourth quarter at the third quarter's "
        "pace. Lilly's third-quarter 2026 results") == "2026-09-30"
    assert book_gaps.cited_period("Q1 2026 results against Q3 2025") == "2026-03-31"
    assert book_gaps.cited_period("the quarter to 2026-06-30 (0000059478-26-000081)") == "2026-06-30"
    assert book_gaps.cited_period("LLY FY2025 reported product revenue") is None


def test_an_anchor_older_than_the_latest_filed_quarter_is_stale(tmp_path):
    path, conn, cid = _book(tmp_path)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 "  period_end, value, unit) VALUES (?, 'Revenues', 'Q', 2026,"
                 "  '2026-09-30', 24397e6, 'USD')", (cid,))
    old = conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                       " VALUES (?, 'Jaypirca', 1)", (cid,)).lastrowid
    fresh = conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                         " VALUES (?, 'Mounjaro', 1)", (cid,)).lastrowid
    annual = conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                          " VALUES (?, 'Verzenio', 1)", (cid,)).lastrowid
    for asset, source in ((old, "a 2026 run rate: the first half of 2026 as reported and "
                                "the second half at the second quarter's pace"),
                          (fresh, "the nine months of 2026 as reported, third-quarter 2026"),
                          (annual, "LLY FY2025 reported product revenue")):
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value,"
                     "  source) VALUES (?, 'US', 'base', 'base_revenue', 1.0, ?)",
                     (asset, source))
    conn.execute("INSERT INTO company_lines (company_id, line, scenario, key, value, source)"
                 " VALUES (?, 'Other oncology', 'base', 'base_revenue', 3253,"
                 "  'the first half of 2026 against the first half of 2025')", (cid,))
    conn.commit()
    out = book_gaps.stale_anchors(conn, "LLY")
    assert sorted((o["kind"], o["name"], o["cited"]) for o in out) == [
        ("line", "Other oncology", "2026-06-30"), ("seed", "Jaypirca", "2026-06-30")]
    assert all(o["latest"] == "2026-09-30" for o in out)


def test_the_guidance_flag_reads_the_distance_outside_the_range():
    split = {"ok": True, "expected": 95_000.0,
             "guidance": {"mid": 91_500.0, "low": 91_000.0, "high": 92_000.0}}
    flag = book_gaps.guidance_flag(split)
    assert round(flag["outside_pct"], 4) == round(3_000 / 91_500, 4) and flag["flagged"]
    inside = {"ok": True, "expected": 91_700.0,
              "guidance": {"mid": 91_500.0, "low": 91_000.0, "high": 92_000.0}}
    assert book_gaps.guidance_flag(inside) == {"outside_pct": 0.0, "flagged": False}
    near = {"ok": True, "expected": 92_900.0,
            "guidance": {"mid": 91_500.0, "low": 91_000.0, "high": 92_000.0}}
    assert not book_gaps.guidance_flag(near)["flagged"]      # 1.0% outside, under 3%
    assert book_gaps.guidance_flag({"ok": False}) is None


def test_the_summary_line_counts_by_company(tmp_path):
    path, conn, cid = _book(tmp_path)
    _asset(conn, cid, "tersolisib", "Phase 3")
    conn.close()
    out = book_gaps.summary(path, today=TODAY)
    assert "late-stage and unmodelled: LLY 1" in out["line"]
    assert "bought and unvalued: none" in out["line"]
    assert [o["asset"] for o in out["late_stage_unmodelled"]] == ["tersolisib"]
