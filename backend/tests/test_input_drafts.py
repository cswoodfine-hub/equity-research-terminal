"""The guided input step: detection once, drafting from filed sources, and review that
writes the book and the seed file together. Built on a tmp database and saved filings:
Neurocrine's Soleno closing (public, with projections) and Incyte's Vega closing (private).
"""

import json
from pathlib import Path

import pytest

import db
import filingtext
import input_drafts
import other_claims

FIXTURES = Path(__file__).parent / "fixtures"
NBIX_8K = "0001193125-26-228013"
INCY_8K = "0000879169-26-000048"


class FakeEdgar:
    """The four EDGAR reads, answered from fixtures. A current report is never fetched:
    the tests store the text the filing text fetcher would have stored."""

    def __init__(self):
        self.searches = []

    def current_report(self, url):
        raise AssertionError(f"no fetch expected: {url}")

    def search(self, phrase, forms=None, start=None, end=None):
        self.searches.append((phrase, start, end))
        if phrase.lower().startswith("soleno"):
            return json.loads((FIXTURES / "closings_fts_soleno.json").read_text())
        return json.loads((FIXTURES / "closings_fts_vega_none.json").read_text())

    def document(self, cik, accession, filename):
        assert accession == "0001193125-26-162853"
        return (FIXTURES / "closings_sc14d9_soleno_projections.htm").read_text()

    def companyfacts(self, cik):
        assert cik == "1484565"
        return json.loads((FIXTURES / "closings_companyfacts_soleno_revenue.json").read_text())


def _book(tmp_path):
    path = tmp_path / "book.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.executescript("""
        INSERT INTO companies (id, ticker, name, cik) VALUES
            (1, 'NBIX', 'Neurocrine Biosciences, Inc.', '0000914475'),
            (2, 'INCY', 'Incyte Corporation', '0000879169');
        INSERT INTO assets (id, owner_company_id, generic_name, brand_name, is_marketed,
                            modality) VALUES
            (10, 1, 'Diazoxide Choline', 'Vykat Xr', 1, 'small molecule'),
            (11, 1, 'DCCR', NULL, 0, NULL),
            (12, 1, 'Valbenazine', 'Ingrezza', 1, 'small molecule'),
            (20, 2, 'VGA039', NULL, 0, NULL);
        INSERT INTO trials (nct_id, asset_id, lead_sponsor) VALUES
            ('NCT0000001', 11, 'Soleno Therapeutics, Inc.'),
            ('NCT0000002', 20, 'Vega Therapeutics, Inc');
        INSERT INTO financials (company_id, period_end, period_type, metric, value) VALUES
            (1, '2026-03-31', 'Q', 'CashAndEquivalents', 1.0),
            (2, '2026-03-31', 'Q', 'CashAndEquivalents', 1.0);
    """)
    conn.execute(
        "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
        " VALUES (1, '8-K', '2026-05-18', ?, ?, ?)",
        (NBIX_8K, "Material agreement signed, Acquisition or disposition completed, Direct "
                  "financial obligation created",
         "https://www.sec.gov/Archives/edgar/data/914475/000119312526228013/d94926d8k.htm"))
    conn.execute(
        "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
        " VALUES (2, '8-K', '2026-07-06', ?, 'Other events', ?)",
        (INCY_8K, "https://www.sec.gov/Archives/edgar/data/879169/000087916926000048/"
                  "incy-20260706.htm"))
    body = filingtext.html_to_text((FIXTURES / "closings_8k_201_nbix_soleno.htm").read_text())
    rows = [
        (1, NBIX_8K, "8-K", "2026-05-18", "body", body),
        (2, INCY_8K, "8-K", "2026-07-06", "exhibit",
         (FIXTURES / "closings_8k_incy_vega_exhibit.txt").read_text()),
        # Neurocrine's first-quarter 10-Q, as filed (0000914475-26-000026).
        (1, "0000914475-26-000026", "10-Q", "2026-05-05", "mdna",
         "In April 2026, we entered into the Merger Agreement to acquire Soleno for "
         "approximately $2.9 billion in cash, as described above."),
    ]
    conn.executemany(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date, section,"
        " text) VALUES (?, ?, ?, ?, ?, ?)", rows)
    # Ingrezza is seeded, so a new product can take the company's ratios from it.
    for key, value, text in (("therapy_mode", None, "marketed"), ("cogs_pct", 0.04, None),
                             ("tax_rate", 0.2, None)):
        conn.execute(
            "INSERT INTO assumptions (asset_id, region, scenario, key, value, text_value,"
            " source) VALUES (12, 'US', 'base', ?, ?, ?, 'NBIX FY2025 10-K, filed lines')",
            (key, value, text))
    conn.commit()
    return path, conn


def test_detection_reads_each_filing_once(tmp_path):
    _path, conn = _book(tmp_path)
    first = input_drafts.detect(conn, None, since="2025-01-01")
    assert sorted((c["target"], c["closing_date"], c["kind"]) for c in first["closings"]) == [
        ("Soleno Therapeutics, Inc.", "2026-05-18", "8-K item 2.01"),
        ("Vega Therapeutics, Inc.", "2026-07-06", "8-K press release")]
    # The headline's shorter name gave way to the lead's longer one.
    again = input_drafts.detect(conn, None, since="2025-01-01")
    assert again["closings"] == [] and sum(again["verdicts"].values()) == 0
    assert conn.execute("SELECT COUNT(*) FROM deal_closings").fetchone()[0] == 2


def test_a_public_target_drafts_base_peak_and_growth_from_its_filings(tmp_path):
    path, conn = _book(tmp_path)
    input_drafts.detect(conn, None)
    closing = conn.execute("SELECT id FROM deal_closings WHERE company_id = 1").fetchone()
    out = input_drafts.draft(conn, closing["id"], FakeEdgar())
    rows = {r["key"]: r for r in out["rows"]}
    base = rows["base_revenue"]
    assert base["asset_id"] == 10 and base["value"] == 190.405
    assert base["evidence"] == "filed" and base["status"] == "draft"
    assert "us-gaap:" in base["source"] and "190405" in base["quote"]
    peak = rows["revenue_ceiling_musd"]
    assert peak["value"] == 1100.0 and "2034: 1,100 (amounts in millions)" in peak["quote"]
    assert "0001193125-26-162853" in peak["source"] and peak["evidence"] == "filed"
    growth = rows["revenue_growth_pct"]
    assert growth["value"] == pytest.approx((1100 / 190.405) ** (1 / 9) - 1, abs=1e-6)
    # Ratios borrowed from Ingrezza, graded as borrowed.
    assert rows["cogs_pct"]["evidence"] == "analogue" and rows["cogs_pct"]["value"] == 0.04
    # The cash paid, after the last balance sheet, is a pending claim.
    claim = rows["pending_acquisition_soleno_therapeutics"]
    assert claim["destination"] == "other_claims" and claim["value"] == 2900.0
    assert "$2.9 billion" in claim["quote"]
    # DCCR is linked by Soleno's trial and not named in the projections.
    assert "DCCR is linked by the target's registered trials" in out["note"]
    assert out["context"]["projection"]["falls_by_half_in"] == 2036
    stored = conn.execute("SELECT COUNT(*) FROM input_drafts").fetchone()[0]
    assert stored == len(out["rows"])


def test_a_private_target_proposes_no_value_rows(tmp_path):
    _path, conn = _book(tmp_path)
    input_drafts.detect(conn, None)
    closing = conn.execute("SELECT id FROM deal_closings WHERE company_id = 2").fetchone()
    out = input_drafts.draft(conn, closing["id"], FakeEdgar())
    assert "no free data" in out["note"]
    assert {r["destination"] for r in out["rows"]} == {"other_claims"}
    claim = out["rows"][0]
    assert claim["value"] == 1250.0 and "$1.25 billion upfront" in claim["quote"]
    assert conn.execute("SELECT target_status FROM deal_closings WHERE id = ?",
                        (closing["id"],)).fetchone()[0] == "private"


def test_a_row_the_book_already_holds_is_not_drafted_and_a_different_one_is_shown(tmp_path):
    _path, conn = _book(tmp_path)
    conn.executemany(
        "INSERT INTO assumptions (asset_id, region, scenario, key, value, source)"
        " VALUES (10, 'US', 'base', ?, ?, ?)",
        [("revenue_ceiling_musd", 1100.0, "already seeded"),
         ("base_revenue", 250.0, "a run rate")])
    input_drafts.detect(conn, None)
    closing = conn.execute("SELECT id FROM deal_closings WHERE company_id = 1").fetchone()
    out = input_drafts.draft(conn, closing["id"], FakeEdgar())
    rows = {r["key"]: r for r in out["rows"]}
    assert "revenue_ceiling_musd" not in rows
    assert rows["base_revenue"]["existing_value"] == 250.0
    assert rows["base_revenue"]["existing_source"] == "a run rate"


def test_accept_writes_the_book_and_the_seed_file(tmp_path):
    path, conn = _book(tmp_path)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    input_drafts.detect(conn, None)
    closing = conn.execute("SELECT id FROM deal_closings WHERE company_id = 1").fetchone()
    input_drafts.draft(conn, closing["id"], FakeEdgar())
    draft_id = conn.execute("SELECT id FROM input_drafts WHERE key = 'revenue_ceiling_musd'"
                            ).fetchone()[0]
    out = input_drafts.decide(conn, draft_id, "accept", seed_dir=seeds)
    assert out["status"] == "accepted" and out["seed"] == "added"
    row = conn.execute("SELECT value, source, evidence, evidence_reviewed FROM assumptions"
                       " WHERE asset_id = 10 AND key = 'revenue_ceiling_musd'").fetchone()
    assert row["value"] == 1100.0 and '"Revenue, 2034: ' in row["source"]
    assert (row["evidence"], row["evidence_reviewed"]) == ("filed", 1)
    seed = (seeds / "nbix_vykat_xr.csv").read_text()
    assert "NBIX,Vykat Xr,,US,base,revenue_ceiling_musd,,1100," in seed
    assert conn.execute("SELECT COUNT(*) FROM snapshots WHERE source = 'input_drafts'"
                        ).fetchone()[0] == 1
    with pytest.raises(ValueError, match="accepted already"):
        input_drafts.decide(conn, draft_id, "accept", seed_dir=seeds)
    # A rebuilt book reads the row back from the file.
    rebuilt = tmp_path / "rebuilt.db"
    db.init(rebuilt)
    other = db.get_connection(rebuilt)
    other.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NBIX', 'n')")
    other.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                  " is_marketed) VALUES (10, 1, 'Diazoxide Choline', 'Vykat Xr', 1)")
    import assumptions
    assert assumptions.load_seeds(other, seeds)["written"] == 1
    assert other.execute("SELECT value FROM assumptions WHERE key = 'revenue_ceiling_musd'"
                         ).fetchone()[0] == 1100.0


def test_incomplete_rows_need_an_edit_and_rejected_rows_stay_rejected(tmp_path):
    _path, conn = _book(tmp_path)
    conn.execute(
        "INSERT INTO input_drafts (id, company_id, trigger_accession, trigger_kind,"
        " destination, asset_id, key, value, source, quote, status) VALUES"
        " (900, 1, 'x', '10-Q', 'assumptions', 10, 'revenue_ceiling_musd', 5000, 'a proxy',"
        " 'Net Revenue, 2038: \"5,000\"', 'incomplete')")
    conn.execute(
        "INSERT INTO input_drafts (id, company_id, trigger_accession, trigger_kind,"
        " destination, asset_id, key, value, status) VALUES"
        " (901, 1, 'x', '10-Q', 'assumptions', 10, 'base_revenue', 10, 'draft')")
    conn.commit()
    with pytest.raises(ValueError, match="incomplete"):
        input_drafts.decide(conn, 900, "accept", seed_dir=tmp_path)
    with pytest.raises(ValueError, match="source"):
        input_drafts.decide(conn, 901, "accept", seed_dir=tmp_path)
    out = input_drafts.decide(conn, 900, "accept", {"value": 2500.0}, seed_dir=tmp_path)
    assert out["status"] == "edited"
    assert conn.execute("SELECT value FROM input_drafts WHERE id = 900").fetchone()[0] == 2500
    assert input_drafts.decide(conn, 901, "reject")["status"] == "rejected"
    queue = input_drafts.queue(conn, "NBIX")
    assert queue["ticker"] == "NBIX"


def test_a_pending_claim_stands_until_a_balance_sheet_carries_the_deal(tmp_path):
    _path, conn = _book(tmp_path)
    claims = tmp_path / "other_claims.csv"
    claims.write_text("# curated\r\nticker,item,label,kind,value,as_of,source,note\r\n")
    input_drafts.detect(conn, None)
    closing = conn.execute("SELECT id FROM deal_closings WHERE company_id = 2").fetchone()
    input_drafts.draft(conn, closing["id"], FakeEdgar())
    draft_id = conn.execute("SELECT id FROM input_drafts WHERE destination = 'other_claims'"
                            " AND company_id = 2").fetchone()[0]
    input_drafts.decide(conn, draft_id, "accept", claims_path=claims)
    text = claims.read_bytes().decode()
    assert "INCY,pending_acquisition_vega_therapeutics" in text
    assert text.count("\r\n") == 3            # the file's own line endings kept
    before = other_claims.for_company(conn, "INCY", "2026-03-31")
    assert before["total"] == -1250.0
    after = other_claims.for_company(conn, "INCY", "2026-09-30")
    assert after["total"] == 0.0 and after["absorbed"][0]["value"] == 1250.0


def test_upsert_replaces_the_matching_line_and_keeps_the_rest(tmp_path):
    path = tmp_path / "jnj_x.csv"
    path.write_bytes(b"# a comment\r\nticker,brand,key,value\r\nJNJ,X,a,1\r\nJNJ,X,b,2\r\n")
    assert input_drafts.upsert_csv(path, [], ("key",),
                                   {"ticker": "JNJ", "brand": "X", "key": "b",
                                    "value": 3.0}) == "updated"
    assert path.read_bytes() == (b"# a comment\r\nticker,brand,key,value\r\nJNJ,X,a,1\r\n"
                                 b"JNJ,X,b,3\r\n")
