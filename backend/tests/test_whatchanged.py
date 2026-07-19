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


def test_feed_narrows_to_one_company(tmp_path):
    """The ticker filter must not leak another company's dates into the view."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    soon = (dt.date.today() + dt.timedelta(days=20)).isoformat()
    catalysts.add_catalyst(db_file, "LLY", "PDUFA", soon, "LLY decision")
    catalysts.add_catalyst(db_file, "AMGN", "PDUFA", soon, "AMGN decision")

    everything = whatchanged.build_feed(db_file)
    assert {it["ticker"] for it in everything} == {"LLY", "AMGN"}

    just_lly = whatchanged.build_feed(db_file, ticker="LLY")
    assert [it["ticker"] for it in just_lly] == ["LLY"]
    assert "AMGN" not in " ".join(it["headline"] for it in just_lly)
    assert whatchanged.build_feed(db_file, ticker="lly") == just_lly  # case insensitive


def test_forward_looking_items_rank_soonest_first(tmp_path):
    """The nearest expiry outranks a later one, so the note leads with the urgent item."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    for brand, days_out in (("Later", 500), ("Sooner", 120)):
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality,"
                     " is_marketed) VALUES (?, ?, 'small molecule', 1)", (cid, brand))
        aid = conn.execute("SELECT id FROM assets WHERE brand_name=?", (brand,)).fetchone()[0]
        conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                     " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                     (aid, (dt.date.today() + dt.timedelta(days=days_out)).isoformat()))
    conn.commit()
    conn.close()

    feed = whatchanged.build_feed(db_file, ticker="LLY")
    assert "Sooner" in feed[0]["headline"] and "Later" in feed[1]["headline"]


def test_loe_limit_applies_per_company_not_globally(tmp_path):
    """Regression: a company's LOE must not be cut off by other companies' nearer ones.

    The cap used to be applied across the universe before the ticker filter, so a
    company whose expiries all fell outside the global top N showed an empty LOE
    section while its own products were expiring.
    """
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    conn = db.get_connection(db_file)
    for ticker, brand, days_out in (("AMGN", "Nearer", 100), ("LLY", "Further", 400)):
        cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
                     " VALUES (?, ?, 'small molecule', 1)", (cid, brand))
        aid = conn.execute("SELECT id FROM assets WHERE brand_name=?", (brand,)).fetchone()[0]
        conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                     " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                     (aid, (dt.date.today() + dt.timedelta(days=days_out)).isoformat()))
    conn.commit()
    conn.close()

    # A global cap of 1 keeps only AMGN's nearer expiry.
    assert [it["ticker"] for it in whatchanged.build_feed(db_file, loe_limit=1)] == ["AMGN"]

    # LLY still sees its own, because the cap is applied per company.
    lly = whatchanged.build_feed(db_file, loe_limit=1, ticker="LLY")
    assert [it["ticker"] for it in lly] == ["LLY"]
    assert "Further" in lly[0]["headline"]


def test_an_approval_is_dated_when_it_happened_not_when_we_saw_it(tmp_path):
    """Regression: the feed showed detected_at for approvals.

    Saphnelo was approved 2026-04-24 and first seen 2026-07-18, and the feed read
    "AZN FDA approval: Saphnelo (2026-07-18)" as though that were the approval.
    """
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='AZN'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, 'Saphnelo', 1)", (cid,))
    aid = conn.execute("SELECT id FROM assets WHERE brand_name='Saphnelo'").fetchone()[0]
    approved = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 " application_number) VALUES (?,'US','FDA',?,'BLA761451')",
                 (aid, approved))
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, new_value,"
                 " change_type, significance) VALUES ('approval','BLA761451','approval',"
                 "'AZN FDA approval: Saphnelo (BLA761451)','new_approval','high')")
    conn.commit()
    conn.close()

    item = next(i for i in whatchanged.build_feed(db_file, ticker="AZN")
                if i["kind"] == "change")
    assert item["date"] == approved, "the feed must date an approval by its approval date"
    # Detection time is kept as bookkeeping, and is not the date shown. It comes from
    # SQLite's datetime('now'), which is UTC, so it is only compared for difference.
    assert item["detected_at"] and item["detected_at"][:10] != approved


def test_a_derived_readout_carries_the_trial_detail(tmp_path):
    """The note needs more than a headline: the drug, phase, enrolment, indication and
    NCT id all come from the trial the catalyst was derived from."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    due = (dt.date.today() + dt.timedelta(days=40)).isoformat()

    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status, "
        "enrollment, conditions, primary_completion_date) VALUES "
        "('NCT06260722', ?, 'Phase 3, Effect of Retatrutide vs Semaglutide', 'Phase 3', "
        "'Active not recruiting', 1250, '[\"Type 2 Diabetes\"]', ?)",
        (cid, due),
    )
    conn.commit()
    conn.close()
    catalysts.derive_readouts(db_file)

    feed = whatchanged.build_feed(db_file, ticker="LLY")
    catalyst = next(it for it in feed if it["kind"] == "catalyst")
    detail = catalyst["detail"]

    assert "NCT06260722" in detail
    assert "phase 3" in detail
    assert "1250 enrolled" in detail
    assert "Type 2 Diabetes" in detail
    assert "Retatrutide vs Semaglutide" in detail   # the full title, not the clip


def test_a_pdufa_catalyst_has_no_trial_detail(tmp_path):
    """A PDUFA row is not a trial; its title already carries product and indication."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    catalysts.add_catalyst(db_file, "LLY", "PDUFA",
                           (dt.date.today() + dt.timedelta(days=20)).isoformat(),
                           "Zepbound sBLA decision")

    feed = whatchanged.build_feed(db_file, ticker="LLY")
    catalyst = next(it for it in feed if it["kind"] == "catalyst")
    assert catalyst["detail"] is None
