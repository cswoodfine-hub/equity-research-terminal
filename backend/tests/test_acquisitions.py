"""The acquisition ledger: a register row reaches the deals table with its terms, the
headline and filing rows for the same target fold into it, and a rebuilt book gets it
back. No network."""

import csv
import pathlib

import acquisitions
import db
import deals
import seed

HEADER = ",".join(acquisitions.FIELDS) + "\n"
CENTESSA = ("LLY,Centessa Pharmaceuticals plc,ORX750,2026-06-24,completed,"
            "business combination,5958,1542,,,Phase 2,,0000059478-26-000108,"
            "\"Cash consideration paid, net of cash acquired | $ 5,958 ... Contingent "
            "consideration | $ 1,542\",agreed 2026-03-31\n")


def _book(tmp_path):
    db_file = tmp_path / "acq.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    return db_file, conn, cid


def _ledger(tmp_path, body=CENTESSA):
    path = tmp_path / "acquisitions.csv"
    path.write_text("# a comment\n" + HEADER + body, encoding="utf-8")
    return path


def _headline(conn, cid, party, date, accession=None, **extra):
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  accession, article_url, milestones_usd, headline_usd) VALUES"
        "  (?, 'acquisition', ?, ?, 'headline', ?, ?, ?, ?)",
        (cid, party, date, accession, extra.get("article_url"),
         extra.get("milestones_usd"), extra.get("headline_usd")))
    conn.commit()


def test_a_ledger_row_is_written_with_its_terms(tmp_path):
    db_file, conn, cid = _book(tmp_path)
    out = acquisitions.load(conn, _ledger(tmp_path))
    assert out["written"] == 1 and out["folded"] == 0
    row = conn.execute("SELECT * FROM deals").fetchone()
    assert row["is_curated"] == 1 and row["deal_type"] == "acquisition"
    assert row["upfront_usd"] == 5958e6 and row["milestones_usd"] == 1542e6
    assert row["total_usd"] == 7500e6 and row["headline_usd"] == 7500e6
    assert row["accession"] == "0000059478-26-000108"
    assert row["counterparty"] == "Centessa Pharmaceuticals plc"


def test_headline_and_filing_rows_for_the_same_target_fold_into_the_ledger_row(tmp_path):
    """Centessa was agreed on 2026-03-31, recapped in the Q1 release and completed on
    2026-06-24: three rows, one deal. The headline's link is kept, and the figure the
    earnings release lent it (Boehringer Ingelheim's milestone) is not."""
    db_file, conn, cid = _book(tmp_path)
    _headline(conn, cid, "Centessa Pharmaceuticals", "2026-03-31",
              article_url="https://news.example/centessa")
    _headline(conn, cid, "Centessa Pharmaceuticals plc.", "2026-04-30",
              accession="0000059478-26-000043", milestones_usd=2e9, headline_usd=2e9)
    _headline(conn, cid, "Centessa Pharmaceuticals plc", "2026-08-05",
              accession="0000059478-26-000077", milestones_usd=250e6, headline_usd=250e6)
    out = acquisitions.load(conn, _ledger(tmp_path))
    assert out["written"] == 1 and out["folded"] == 3
    rows = conn.execute("SELECT * FROM deals").fetchall()
    assert len(rows) == 1
    assert rows[0]["headline_usd"] == 7500e6
    assert rows[0]["article_url"] == "https://news.example/centessa"
    # and the card reads the one deal at the filed size
    card = deals.recent_rows(conn, cid, today=__import__("datetime").date(2026, 11, 27))
    assert len(card) == 1 and card[0]["announced_usd"] == 7500e6
    assert card[0]["terms_summary"] == "$5.96bn upfront, $1.54bn milestones, $7.5bn total"


def test_another_target_on_a_nearby_date_is_not_folded(tmp_path):
    db_file, conn, cid = _book(tmp_path)
    _headline(conn, cid, "Kelonia Therapeutics", "2026-06-25")
    acquisitions.load(conn, _ledger(tmp_path))
    names = sorted(r[0] for r in conn.execute("SELECT counterparty FROM deals"))
    assert names == ["Centessa Pharmaceuticals plc", "Kelonia Therapeutics"]


def test_loading_twice_updates_the_one_row(tmp_path):
    db_file, conn, cid = _book(tmp_path)
    acquisitions.load(conn, _ledger(tmp_path))
    out = acquisitions.load(conn, _ledger(tmp_path))
    assert out == {"written": 0, "updated": 1, "folded": 0, "removed": 0, "skipped": []}
    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 1


def test_an_unfiled_deal_carries_only_what_was_announced(tmp_path):
    body = ("LLY,Merida Biosciences Inc.,MER511,2026-10-01,completed,not yet filed,,,2900,"
            "\"up to $2.9 billion in aggregate\",Phase 1,,0000059478-26-000108,"
            "\"In October 2026, we acquired Merida\",\n")
    db_file, conn, cid = _book(tmp_path)
    acquisitions.load(conn, _ledger(tmp_path, body))
    row = conn.execute("SELECT * FROM deals").fetchone()
    assert row["upfront_usd"] is None and row["milestones_usd"] is None
    assert row["total_usd"] == 2900e6 and row["announced_value"] == "up to $2.9 billion in aggregate"


def test_same_target_reads_through_suffixes_and_hyphens():
    assert acquisitions.same_target("Atai-Beckley", "AtaiBeckley Inc.")
    assert acquisitions.same_target("Centessa", "Centessa Pharmaceuticals plc.")
    assert not acquisitions.same_target("Orna Therapeutics", "Ajax Therapeutics, Inc.")
    assert not acquisitions.same_target("Therapeutics, Inc.", "Ajax Therapeutics")


def test_the_names_a_target_registers_under_reach_the_sponsor_list(tmp_path):
    """AtaiBeckley's studies sit under Beckley Psytech Limited and Ventyx's under Zomagen
    Biosciences Ltd.; a fetch that searched only the targets' own names found neither."""
    body = ("LLY,AtaiBeckley Inc.,BPL-003,2026-09-01,completed,asset acquisition,2610,1000,"
            "3800,,Phase 2,Beckley Psytech Limited|Zomagen Biosciences Ltd.,"
            "0000059478-26-000108,q,\n")
    path = _ledger(tmp_path, body)
    assert acquisitions.sponsor_names("LLY", path) == ["Beckley Psytech Limited",
                                                       "Zomagen Biosciences Ltd."]
    assert acquisitions.sponsor_names("JNJ", path) == []


def test_rows_without_terms_are_named(tmp_path):
    db_file, conn, cid = _book(tmp_path)
    _headline(conn, cid, "Kelonia Therapeutics", "2026-06-25")
    acquisitions.load(conn, _ledger(tmp_path))
    bare = acquisitions.without_terms(conn, "LLY",
                                      today=__import__("datetime").date(2026, 11, 27))
    assert [r["counterparty"] for r in bare] == ["Kelonia Therapeutics"]


def test_the_register_on_file_reads_and_every_row_cites_a_source():
    rows = acquisitions.rows()
    assert rows, "data/acquisitions.csv holds no rows"
    for r in rows:
        assert r["source"], r["target"]
        assert r["status"] in ("completed", "agreed", "announced"), r["target"]
        assert r["quote"], r["target"]
        for col in ("upfront_musd", "contingent_musd", "total_musd"):
            if r[col]:
                float(r[col].replace(",", ""))
    # the file is well formed for a plain reader too
    with pathlib.Path(acquisitions.DATA).open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    assert list(csv.DictReader(lines))


def test_a_row_that_is_not_an_acquisition_removes_the_headline_rows_and_writes_none(tmp_path):
    """"AstraZeneca said to offer $10B to acquire Rhythm" was a report; the table held it
    three times under three spellings. The ledger row names it and the rows go."""
    db_file, conn, cid = _book(tmp_path)
    for party in ("Rhythm", "Rhythm Pharma", "Rhythm Pharmaceuticals"):
        _headline(conn, cid, party, "2026-11-05")
    _headline(conn, cid, "Rhythm Pharmaceuticals", "2024-01-01")      # another time
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
                 "  quote, is_curated) VALUES (?, 'acquisition', 'Rhythm Pharmaceuticals',"
                 "  '2026-11-06', 'an analyst wrote this', 1)", (cid,))
    conn.commit()
    ledger = _ledger(tmp_path, "LLY,Rhythm Pharmaceuticals,,2026-11-05,not an acquisition,"
                               ",,,,,,,,,a press report of an offer; no agreement filed\n")
    out = acquisitions.load(conn, ledger)
    assert out["removed"] == 3 and out["written"] == 0
    left = conn.execute("SELECT counterparty, event_date, is_curated FROM deals"
                        " ORDER BY event_date").fetchall()
    assert [(r["counterparty"], r["event_date"], r["is_curated"]) for r in left] == [
        ("Rhythm Pharmaceuticals", "2024-01-01", 0),
        ("Rhythm Pharmaceuticals", "2026-11-06", 1)]
