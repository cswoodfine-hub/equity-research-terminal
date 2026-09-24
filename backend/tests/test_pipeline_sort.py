"""The late-stage sort: the population it covers, and the file that sorts it."""

import csv

import db
import pipeline_sort as P

HEADER = ["ticker", "name", "class", "of", "approved", "confidence", "evidence", "as_of"]


def _db(tmp_path):
    path = str(tmp_path / "sort.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.executescript("""
        INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Eli Lilly'),
                                                         (2, 'ROG', 'Roche');
        INSERT INTO indications (id, name) VALUES (1, 'Obesity');
        INSERT INTO assets (id, owner_company_id, generic_name, internal_code, is_marketed)
        VALUES (1, 1, 'Orforglipron', NULL, 0),      -- in: late, unmodelled
               (2, 1, 'Retatrutide', NULL, 0),       -- out: modelled
               (3, 1, 'Tirzepatide', NULL, 1),       -- out: marketed
               (4, 1, NULL, 'LY3549492', 0),         -- in: keyed by its code
               (5, 1, 'Early thing', NULL, 0),       -- out: Phase 1 only
               (6, 2, 'Trontinemab', NULL, 0);       -- out: Roche
        INSERT INTO asset_indications (asset_id, indication_id, phase) VALUES
               (1, 1, 'Phase 3'), (2, 1, 'Phase 3'), (3, 1, 'Phase 3'),
               (4, 1, 'Phase 2'), (5, 1, 'Phase 1'), (6, 1, 'Phase 3');
        INSERT INTO assumptions (asset_id, indication_id, key, value)
        VALUES (2, 1, 'prevalence', 1.0);
    """)
    conn.commit()
    return conn


def test_the_population_is_unmarketed_unmodelled_late_stage_outside_roche(tmp_path):
    conn = _db(tmp_path)
    got = P.population(conn)
    conn.close()
    assert [(r["ticker"], r["name"]) for r in got] == [("LLY", "Orforglipron"),
                                                       ("LLY", "LY3549492")]


def test_unsorted_is_what_the_file_does_not_cover(tmp_path):
    conn = _db(tmp_path)
    sort = tmp_path / "sort.csv"
    with sort.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerow(["LLY", "orforglipron", "NEW", "", "", "high", "x", "2026-09-24"])
    left = P.unsorted(conn, sort)
    conn.close()
    assert [r["name"] for r in left] == ["LY3549492"]    # matched case-insensitively

