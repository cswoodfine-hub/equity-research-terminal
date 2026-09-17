"""Evidence grades read off each assumption's own source, and kept once an analyst sets one."""

import db
import assumptions as A
import company_lines
import evidence as E


def test_a_row_takes_the_weakest_kind_of_evidence_it_names():
    assert E.grade("Amgen 10-Q for the quarter to 2026-06-30 (0000318154-26-000126)") == "filed"
    assert E.grade("US 10Y Treasury (FRED DGS10), 2026-08-26") == "measured"
    assert E.grade("Mirza et al., N Engl J Med 2023") == "published"
    assert E.grade("comparator estimate, reused from lly_eloralintide.csv: CMS Part D 2024") == "analogue"
    assert E.grade("convention: a recent rate describes next year") == "convention"
    assert E.grade("judgement, set against Zepbound's observed capture (CMS Part D)") == "judgement"
    assert E.grade("a share of the pool above, set against what the molecule has to displace") == "judgement"


def test_negated_conventions_and_structural_keys():
    assert E.grade("Zero is a reading of the balance sheet, not a convention") == "filed"
    assert E.grade("dosing schedule of the programme", key="therapy_mode") == "convention"
    assert E.grade("roughly 160,000 US women live with the disease") is None
    assert E.grade(None, key="beta") is None


def test_weakest_and_class():
    assert E.weakest(["filed", "analogue", "measured"]) == "analogue"
    assert E.weakest(["filed", None]) is None
    assert E.evidence_class("published") == "evidence"
    assert E.evidence_class("analogue") == "partial evidence"
    assert E.evidence_class(None) == "assumption"


def _db(tmp_path):
    path = str(tmp_path / "e.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Uplizna', 1)")
    conn.commit()
    return conn


def test_saving_grades_from_the_source_and_a_stated_grade_is_kept(tmp_path):
    conn = _db(tmp_path)
    A.save(conn, 1, [{"key": "revenue_growth_pct", "value": 0.9, "source": "Amgen 10-Q (0000318154-26-000126)"}])
    row = conn.execute("SELECT evidence, evidence_reviewed FROM assumptions").fetchone()
    assert (row["evidence"], row["evidence_reviewed"]) == ("filed", 0)
    A.save(conn, 1, [{"key": "revenue_growth_pct", "value": 0.9, "source": "the analyst's call", "evidence": "judgement"}])
    A.save(conn, 1, [{"key": "revenue_growth_pct", "value": 0.8, "source": "Amgen 10-Q (0000318154-26-000126)"}])
    row = conn.execute("SELECT evidence, evidence_reviewed, value FROM assumptions").fetchone()
    assert (row["evidence"], row["evidence_reviewed"], row["value"]) == ("judgement", 1, 0.8)


def test_backfill_regrades_unreviewed_rows_only(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO assumptions (asset_id, key, value, source, evidence, evidence_reviewed)"
                 " VALUES (1, 'beta', 0.6, 'computed from 261 weekly returns', 'judgement', 0)")
    conn.execute("INSERT INTO assumptions (asset_id, key, value, source, evidence, evidence_reviewed)"
                 " VALUES (1, 'pos', 0.5, 'computed from 261 weekly returns', 'judgement', 1)")
    conn.execute("INSERT INTO company_lines (company_id, line, key, value, source) VALUES (1, 'Other products', 'base_revenue', 5981, 'Amgen FY2025 10-K')")
    counts = E.backfill(conn)
    got = dict(conn.execute("SELECT key, evidence FROM assumptions").fetchall())
    assert got == {"beta": "measured", "pos": "judgement"}
    assert conn.execute("SELECT evidence FROM company_lines").fetchone()[0] == "filed"
    assert counts == {"measured": 1, "filed": 1}


def test_a_seed_evidence_column_is_taken_as_reviewed(tmp_path):
    conn = _db(tmp_path)
    folder = tmp_path / "seeds"
    folder.mkdir()
    (folder / "amgn.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note,evidence\n"
        "AMGN,Uplizna,,US,base,pos,,1.0,,,approved and selling,,filed\n"
        "AMGN,Uplizna,,US,base,beta,,0.61,,,computed from weekly returns,,\n")
    A.load_seeds(conn, folder)
    got = {r["key"]: (r["evidence"], r["evidence_reviewed"]) for r in conn.execute("SELECT key, evidence, evidence_reviewed FROM assumptions")}
    assert got == {"pos": ("filed", 1), "beta": ("measured", 0)}
    lines = tmp_path / "lines"
    lines.mkdir()
    (lines / "amgn.csv").write_text(
        "ticker,line,scenario,key,value,text_value,unit,source,note,evidence\n"
        "AMGN,Other products,base,revenue_growth_pct,0.1,,,the analyst's call,,judgement\n")
    company_lines.load_seeds(conn, lines)
    assert conn.execute("SELECT evidence, evidence_reviewed FROM company_lines").fetchone()[:] == ("judgement", 1)
