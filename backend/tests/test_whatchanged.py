"""The what-changed feed merges changes, catalysts, and LOE, ranked. No network."""

import datetime as dt

import catalysts
import db
import diff
import seed
import whatchanged


def test_feed_merges_and_ranks(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status, "
        "primary_completion_date) VALUES ('NCT001', ?, 'X', 'Phase 3', 'Recruiting', '2027-06-30')",
        (cid,),
    )
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality, internal_code, "
                 "is_marketed) VALUES (?, 'Verzenio', 'small molecule', 'NDA208716', 1)", (cid,))
    aid = conn.execute("SELECT id FROM assets WHERE internal_code='NDA208716'").fetchone()[0]
    loe_date = (dt.date.today() + dt.timedelta(days=300)).isoformat()
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier, expiry_date, "
                 "source) VALUES (?, 'patent', 'X', ?, 'orange_book')", (aid, loe_date))
    conn.commit()
    conn.close()

    diff.detect_changes(db_file)  # baseline
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated' WHERE nct_id='NCT001'")
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)  # emits a high status_change

    catalysts.add_catalyst(db_file, "LLY", "PDUFA",
                           (dt.date.today() + dt.timedelta(days=30)).isoformat(), "PDUFA")

    feed = whatchanged.build_feed(db_file)
    assert {it["kind"] for it in feed} == {"change", "catalyst", "loe"}
    # Highest significance (the terminated trial) ranks first.
    assert feed[0]["significance"] == "high" and feed[0]["kind"] == "change"
    assert all("headline" in it and it["ticker"] == "LLY" for it in feed)
