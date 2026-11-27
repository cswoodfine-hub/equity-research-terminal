"""Reading a company's bought pipeline through the companies it bought."""

import acquired_sponsors
import db


def _seed(tmp_path):
    path = str(tmp_path / "acq.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    for kind, party, date in (
            ("acquisition", "Centessa Pharmaceuticals", "2026-03-31"),
            ("acquisition", "Verve Therapeutics", "2025-08-07"),
            # A licence leaves the studies with the licensor.
            ("licensing", "Innovent Biologics", "2026-02-09"),
            # Too old: the registry has moved these records across by now.
            ("acquisition", "Loxo Oncology", "2019-01-07"),
            # One short word matches sponsors that have nothing to do with the deal.
            ("acquisition", "Engage", "2026-05-20")):
        conn.execute(
            "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote)"
            " VALUES (?, ?, ?, ?, ?)",
            (cid, kind, party, date, f"Lilly to acquire {party}"))
    conn.commit()
    conn.close()
    return path


def test_only_recent_acquisitions_are_searched(tmp_path):
    names = acquired_sponsors.for_company(_seed(tmp_path), "LLY",
                                          today=__import__("datetime").date(2026, 7, 27),
                                          ledger_path=tmp_path / "no_ledger.csv")
    assert names == ["Centessa Pharmaceuticals", "Verve Therapeutics"]


def test_the_ledger_adds_the_names_a_target_registers_under(tmp_path):
    """AtaiBeckley's studies are Beckley Psytech Limited's on the registry."""
    ledger = tmp_path / "acquisitions.csv"
    ledger.write_text(
        "ticker,target,asset,event_date,status,accounting,upfront_musd,contingent_musd,"
        "total_musd,announced_value,phase,sponsor_names,source,quote,note\n"
        "LLY,AtaiBeckley Inc.,BPL-003,2026-09-01,completed,asset acquisition,2610,,,,"
        "Phase 2,Beckley Psytech Limited,0000059478-26-000108,q,\n")
    names = acquired_sponsors.for_company(_seed(tmp_path), "LLY",
                                          today=__import__("datetime").date(2026, 7, 27),
                                          ledger_path=ledger)
    assert "Beckley Psytech Limited" in names


def test_a_name_must_be_specific_enough_to_search_with():
    assert acquired_sponsors._plausible("Centessa Pharmaceuticals")
    assert acquired_sponsors._plausible("AtaiBeckley")
    assert not acquired_sponsors._plausible("Engage")
    assert not acquired_sponsors._plausible("")


def test_a_study_is_kept_only_when_the_registry_agrees():
    study = {"protocolSection": {"sponsorCollaboratorsModule": {
        "leadSponsor": {"name": "Centessa Pharmaceuticals (UK) Limited"}}}}
    assert acquired_sponsors.sponsored_by(study, ["Centessa Pharmaceuticals"]) \
        == "Centessa Pharmaceuticals (UK) Limited"
    # A loose query match led by someone else is a coincidence, not an acquisition.
    other = {"protocolSection": {"sponsorCollaboratorsModule": {
        "leadSponsor": {"name": "University of Oxford"}}}}
    assert acquired_sponsors.sponsored_by(other, ["Centessa Pharmaceuticals"]) is None
    assert acquired_sponsors.sponsored_by({}, ["Centessa"]) is None
    # A name inside another sponsor's is that sponsor's study: a company registers in its
    # own name, so the lead sponsor begins with it.
    belun = {"protocolSection": {"sponsorCollaboratorsModule": {
        "leadSponsor": {"name": "Belun Technology Company Limited"}}}}
    assert acquired_sponsors.sponsored_by(belun, ["Technology Company"]) is None
    # A legal suffix on the searched name does not stop the match.
    assert acquired_sponsors.sponsored_by(study, ["Centessa Pharmaceuticals plc."]) \
        == "Centessa Pharmaceuticals (UK) Limited"


def test_a_headline_fragment_is_not_a_sponsor():
    """These arrived as counterparty names off real headlines. The registry answers
    400 to the first, which failed a whole company's fetch."""
    assert not acquired_sponsors._plausible("OURO MEDICINES TO FURTHER EXPAND")
    assert not acquired_sponsors._plausible("Tubulis Adding Potentially Best-in-Class")
    assert not acquired_sponsors._plausible("Arcellx Ahead")
    # "Sanofi's Deal To Buy Biotech Firm Is Just What The Doctor Ordered", 2026-11-24.
    assert not acquired_sponsors._plausible("Is Just What")
    # Real names still pass, commas and all.
    assert acquired_sponsors._plausible("Arcellx, Inc.")
    assert acquired_sponsors._plausible("Centessa Pharmaceuticals")


def _company(conn, ticker, name, sponsor=None):
    conn.execute("INSERT INTO companies (ticker, name, ctgov_sponsor) VALUES (?, ?, ?)",
                 (ticker, name, sponsor))
    return conn.execute("SELECT id FROM companies WHERE ticker = ?",
                        (ticker,)).fetchone()["id"]


def _deal(conn, cid, party, quote, accession=None, date="2026-04-27"):
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        " accession) VALUES (?, 'acquisition', ?, ?, ?, ?)",
        (cid, party, date, quote, accession))


def _universe(tmp_path):
    """Structure Therapeutics' news search filed BioMarin's and Day One's acquisitions as
    its own (2026-09); BioMarin's own filing states its Amicus deal."""
    path = str(tmp_path / "acq.db")
    db.init(path)
    conn = db.get_connection(path)
    gpcr = _company(conn, "GPCR", "Structure Therapeutics Inc.", "Structure Therapeutics")
    bmrn = _company(conn, "BMRN", "BioMarin Pharmaceutical Inc.", "BioMarin Pharmaceutical")
    jnj = _company(conn, "JNJ", "Johnson & Johnson")
    _deal(conn, gpcr, "Amicus Therapeutics", "BioMarin acquires Amicus Therapeutics for $4.8bn")
    _deal(conn, gpcr, "Mersana Therapeutics",
          "Day One Completes Acquisition of Mersana Therapeutics")
    _deal(conn, bmrn, "Amicus Therapeutics",
          "BioMarin Pharmaceutical Inc. said today that it completed the previously"
          " announced agreement to acquire Amicus Therapeutics", accession="0001-26-1")
    _deal(conn, jnj, "Connecticut", "J&J to acquire Connecticut biotech in $3.05B oncology deal")
    _deal(conn, jnj, "AtaiBeckley",
          "Lilly buys AtaiBeckley for $2.8B upfront to challenge J&J")
    _deal(conn, jnj, "Halda Therapeutics", "Johnson & Johnson acquires Halda Therapeutics")
    for nct, cid, lead, asset in (
            ("NCT04808505", gpcr, "Amicus Therapeutics", None),
            ("NCT03319628", gpcr, "Mersana Therapeutics", None),
            ("NCT07654361", gpcr, "Gasherbrum Bio, Inc., a wholly owned subsidiary of"
                                  " Structure Therapeutics", None),
            ("NCT05283382", jnj, "University of Connecticut", None),
            ("NCT09999999", jnj, "Halda Therapeutics, Inc.", None)):
        conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, lead_sponsor)"
                     " VALUES (?, ?, ?)", (nct, cid, lead))
    conn.commit()
    conn.close()
    return path


def test_a_headline_is_believed_only_when_it_names_the_buyer(tmp_path):
    path = _universe(tmp_path)
    today = __import__("datetime").date(2026, 10, 12)
    # Another company's acquisition, read off this company's news search.
    assert acquired_sponsors.for_company(path, "GPCR", today=today) == []
    # The company's own filing stands whatever its sentence leads with.
    assert acquired_sponsors.for_company(path, "BMRN", today=today) \
        == ["Amicus Therapeutics"]
    # J&J named only as the rival is not J&J's deal; a place is not a company.
    assert acquired_sponsors.for_company(path, "JNJ", today=today) \
        == ["Halda Therapeutics"]


def test_the_buyer_must_lead_the_headline():
    names = {"Bayer", "BAYN", "Bayer AG"}
    assert not acquired_sponsors.names_acquirer(
        "Crystal Crop Protection acquires Ethoxysulfuron assets from Bayer AG", names,
        "Ethoxysulfuron")
    assert acquired_sponsors.names_acquirer(
        "Bayer to buy Perfuse Therapeutics in up to $2.45 billion deal", names,
        "Perfuse Therapeutics")


def test_a_misfiled_study_goes_to_its_buyer_or_to_no_one(tmp_path):
    path = _universe(tmp_path)
    today = __import__("datetime").date(2026, 10, 12)
    assert acquired_sponsors.release(path, today=today) == {"moved": 1, "released": 2}
    conn = db.get_connection(path)
    held = dict(conn.execute(
        "SELECT t.nct_id, c.ticker FROM trials t"
        "  LEFT JOIN companies c ON c.id = t.sponsor_company_id").fetchall())
    snaps = conn.execute("SELECT entity_key FROM snapshots"
                         " WHERE source = 'acquired_sponsors' ORDER BY entity_key"
                         ).fetchall()
    conn.close()
    assert held == {"NCT04808505": "BMRN",          # BioMarin bought Amicus
                    "NCT03319628": None,            # Day One is not in the universe
                    "NCT07654361": "GPCR",          # Structure's own subsidiary
                    "NCT05283382": None,            # the University of Connecticut
                    "NCT09999999": "JNJ"}           # a deal J&J did make
    assert [r["entity_key"] for r in snaps] == ["GPCR", "JNJ"]
    # Idempotent.
    assert acquired_sponsors.release(path, today=today) == {"moved": 0, "released": 0}



def test_a_rumour_is_not_an_acquisition():
    row = {"accession": None, "is_curated": 0, "counterparty": "Rhythm Pharmaceuticals",
           "quote": "AstraZeneca said to offer $10B to acquire Rhythm, analysts whisper "
                    "of a bidding war"}
    assert not acquired_sponsors._trusted(row, {"astrazeneca"})


def test_a_city_is_not_the_company_bought():
    """'AstraZeneca buys St. Louis vaccine startup Omniose' stored 'St. Louis'."""
    assert not acquired_sponsors._plausible("St. Louis")


def test_a_deal_held_as_pending_is_searched_without_a_headline(tmp_path):
    """Sanofi and Insmed, 2026-11-23. The deals table held a rumour ("considering a
    deal") and a headline whose counterparty parsed as "Is Just What", so no headline
    vouched for the acquisition. The pending register does: a row there is the decision
    to hold the target's products in the acquirer's name."""
    path = str(tmp_path / "acq.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('SNY', 'Sanofi')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote)"
        " VALUES (?, 'acquisition', 'Insmed', '2026-11-19',"
        " 'Sanofi considering a deal to acquire Insmed, according to report')", (cid,))
    conn.commit()
    conn.close()
    pending = tmp_path / "pending.csv"
    pending.write_text(
        "acquirer,asset,target,announced,terms,basis\n"
        "SNY,Brinsupri,Insmed Incorporated,2026-11-23,$175.00 a share in cash,an Item 1.01\n"
        "SNY,Arikayce Kit,Insmed Incorporated,2026-11-23,$175.00 a share in cash,an Item 1.01\n"
        # One short word is still not a name a registry can be searched with.
        "SNY,Somedrug,Engage,2026-11-23,terms,basis\n")
    empty = tmp_path / "none.csv"
    empty.write_text("acquirer,asset,target,announced,terms,basis\n")

    assert acquired_sponsors.for_company(path, "SNY", pending_path=empty,
                                         ledger_path=empty) == []
    assert acquired_sponsors.for_company(path, "SNY", pending_path=pending,
                                         ledger_path=empty) == [
        "Insmed Incorporated"]
    # Another company's pending deal is not this one's.
    assert acquired_sponsors.for_company(path, "LLY", pending_path=pending,
                                         ledger_path=empty) == []
