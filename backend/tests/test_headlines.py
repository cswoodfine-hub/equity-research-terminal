"""What leads an engine, and the ranking that decides it."""

import datetime as dt

import db
import headlines

TODAY = dt.date(2026, 7, 30)


def _seed(tmp_path):
    path = str(tmp_path / "h.db")
    db.init(path)
    conn = db.get_connection(path)
    for ticker in ("JNJ", "MRK", "SRPT"):
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)",
                     (ticker, ticker.title()))
    conn.commit()
    return path, conn


def _deal(conn, ticker, counterparty, date, **terms):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
        "  upfront_usd, equity_usd, milestones_usd, option_usd, total_usd, headline_usd,"
        "  terms_evidence) VALUES (?, 'collaboration', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, counterparty, date, terms.get("upfront"), terms.get("equity"),
         terms.get("milestones"), terms.get("option"), terms.get("total"),
         terms.get("headline"), terms.get("evidence")))
    conn.commit()


def test_a_deal_leads_and_carries_its_structure(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29", upfront=785e6, equity=465e6,
          milestones=140e6, option=2.58e9, headline=2.58e9,
          evidence="Under the terms of the agreements...")
    conn.close()

    rows = headlines.build(path, today=TODAY)
    assert rows[0]["kind"] == "deal"
    assert rows[0]["figure"] == "$2.58bn"
    assert rows[0]["detail"] == (
        "$785m upfront, $465m equity, $140m milestones, $2.58bn option to acquire")


def test_a_deal_with_no_terms_is_not_a_headline(tmp_path):
    """"J&J announces collaboration with Sail" says something happened and nothing about
    whether it counts. Without a figure there is no way to tell a research tie-up from a
    takeover."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29")
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_the_bigger_deal_leads(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Small Co", "2026-07-29", total=1e9, headline=1e9)
    _deal(conn, "MRK", "Big Co", "2026-07-28", total=9e9, headline=9e9)
    conn.close()
    assert [r["ticker"] for r in headlines.build(path, today=TODAY)] == ["MRK", "JNJ"]


def test_one_headline_per_company(tmp_path):
    """Four headlines about one filer is a page about that filer, not about the engine."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "One", "2026-07-29", total=9e9, headline=9e9)
    _deal(conn, "JNJ", "Two", "2026-07-28", total=8e9, headline=8e9)
    conn.close()
    rows = headlines.build(path, today=TODAY)
    assert [r["ticker"] for r in rows] == ["JNJ"]
    assert rows[0]["headline"].endswith("One")


def test_an_engine_sees_only_its_own_companies(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "One", "2026-07-29", total=9e9, headline=9e9)
    _deal(conn, "SRPT", "Two", "2026-07-28", total=8e9, headline=8e9)
    conn.close()
    rows = headlines.build(path, tickers=["SRPT"], today=TODAY)
    assert [r["ticker"] for r in rows] == ["SRPT"]


def test_an_old_deal_is_not_a_headline(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Old", "2026-05-01", total=9e9, headline=9e9)
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_the_order_is_stated_rather_than_scored():
    """A reader who disagrees with the ranking can see it, which is the point of writing
    it down as a tuple instead of computing a score."""
    assert headlines.ORDER.index("deal") < headlines.ORDER.index("approval")
    assert headlines.ORDER.index("approval") < headlines.ORDER.index("leadership")
    assert headlines.ORDER.index("leadership") < headlines.ORDER.index("trial_stopped")


def test_a_trial_starting_is_not_a_trial_stopping():
    """A status change to Recruiting is a programme beginning. Only Terminated, Withdrawn
    and Suspended are the fastest a programme's value ever changes."""
    assert headlines._STOPPED.search("trial NCT1: status Active -> Terminated")
    assert not headlines._STOPPED.search(
        "trial NCT1: status Not yet recruiting -> Recruiting")


# --- the forward view ------------------------------------------------------------------

def _catalyst(conn, ticker, kind, date, title, curated=0, nct=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO catalysts (company_id, catalyst_type, expected_date, title,"
        "  description, is_curated, date_confidence, status)"
        "  VALUES (?, ?, ?, ?, ?, ?, 'estimated', 'pending')",
        (cid, kind, date, title, nct, curated))
    conn.commit()


def test_the_forward_view_is_a_calendar(tmp_path):
    """Soonest first: it answers "what is coming", and a ranking by kind would bury
    tomorrow under something three weeks out."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-20", "Phase 3, Keytruda")
    _catalyst(conn, "JNJ", "data readout", "2026-08-02", "Phase 2, Something")
    conn.close()
    rows = headlines.ahead(path, today=TODAY)
    assert [r["date"] for r in rows] == ["2026-08-02", "2026-08-20"]


def test_the_firmest_kind_leads_its_day(tmp_path):
    """A decision date outranks the vote that informs it, which outranks a readout the
    registry only estimates."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, Something")
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA", curated=1)
    conn.close()
    assert [r["kind"] for r in headlines.ahead(path, today=TODAY)] == [
        "PDUFA", "data readout"]


def test_a_derived_readout_says_it_is_derived(tmp_path):
    """A registry completion date is an estimate that slips, and the box has to say so
    rather than leaving a reader to know it."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, X", nct="NCT1")
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    assert row["curated"] is False
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "registry primary completion date" in confidence["value"]
    assert any(p["label"] == "Study" and p["value"] == "NCT1" for p in row["summary"])


def test_a_curated_date_says_the_company_stated_it(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA", curated=1)
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    assert row["curated"] is True
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "curated" in confidence["value"]


def test_nothing_outside_the_window(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-11-01", "Phase 3, Far off")
    _catalyst(conn, "JNJ", "data readout", "2026-07-01", "Phase 3, Gone by")
    conn.close()
    assert headlines.ahead(path, today=TODAY) == []


def test_the_forward_view_respects_the_engine(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, Theirs")
    _catalyst(conn, "SRPT", "data readout", "2026-08-11", "Phase 3, Ours")
    conn.close()
    rows = headlines.ahead(path, tickers=["SRPT"], today=TODAY)
    assert [r["ticker"] for r in rows] == ["SRPT"]


def test_every_headline_carries_a_summary_to_open(tmp_path):
    """The box is a disclosure, so an item with nothing behind it opens onto nothing."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29", upfront=785e6, equity=465e6,
          option=2.58e9, headline=2.58e9, evidence="Under the terms...")
    conn.close()
    row = headlines.build(path, today=TODAY)[0]
    labels = [p["label"] for p in row["summary"]]
    assert labels[:3] == ["Upfront", "Equity", "Option to acquire"]
    assert "Counterparty" in labels


def test_a_week_is_the_window():
    """The page answers "what happened since I last looked". A fortnight put things on it
    that had already been read and acted on."""
    assert headlines.LOOKBACK_DAYS == 7


def test_a_decision_date_does_not_claim_the_registry(tmp_path):
    """A PDUFA date is read out of an 8-K. Calling it "derived from the registry" names a
    source that never carried it."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA",
              nct="The Company's BLA remains on track for a target action date.")
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "8-K" in confidence["value"]
    assert "registry" not in confidence["value"]
    # The announcing sentence is a quote, not a study identifier.
    assert not any(p["label"] == "Study" for p in row["summary"])
    assert row["evidence"].startswith("The Company's BLA")
    # Somebody stated it, so it is firm even though it was extracted rather than typed.
    assert row["curated"] is True


# --- a filing whose title is the news ---------------------------------------------------

def _filing(conn, ticker, form, title, date):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 "  title, url) VALUES (?, ?, ?, ?, ?, 'http://x')",
                 (cid, f"{ticker}-{date}-{title[:8]}", form, date, title))
    conn.commit()


def test_a_six_k_title_is_the_announcement(tmp_path):
    """A foreign filer titles its own filing, so the title is the news. "HANSOH POSITIVE
    2ND PHASE III RESULTS" is a headline; nothing else in the model would carry it."""
    path, conn = _seed(tmp_path)
    _filing(conn, "MRK", "6-K", "HANSOH POSITIVE 2ND PHASE III RESULTS FOR RIZ-REZ",
            "2026-07-28")
    conn.close()
    row = headlines.build(path, today=TODAY)[0]
    assert row["kind"] == "filing"
    assert row["headline"] == "MRK Hansoh positive 2nd phase III results for RIZ-REZ"


def test_an_eight_k_title_is_the_form_not_the_news(tmp_path):
    """An 8-K is titled by the items it uses, so its headline is "Other events" however
    large the event. Whatever happened reaches the page by another route or not at all."""
    path, conn = _seed(tmp_path)
    _filing(conn, "JNJ", "8-K", "Regulation FD disclosure, Financial statements and "
            "exhibits", "2026-07-29")
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_listing_rule_housekeeping_is_not_news(tmp_path):
    """Most 6-Ks are UK listing-rule filings: a director's share dealing, a buyback
    tranche, a voting-rights total. Filings a company must make, not things that
    happened to it."""
    path, conn = _seed(tmp_path)
    for title in ("DIRECTOR/PDMR SHAREHOLDING", "TRANSACTION IN OWN SHARES",
                  "TOTAL VOTING RIGHTS", "FORM 6-K", "6-K"):
        _filing(conn, "MRK", "6-K", title, "2026-07-28")
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_a_shouted_title_keeps_what_was_meant_to_be_capitals():
    """A vowel test alone is not enough: "III" is all vowels and "HSCT-TMA" contains one,
    and both are abbreviations."""
    assert headlines._sentence_case(
        "UPDATE ON ULTOMIRIS PHASE III TRIAL IN HSCT-TMA", {"ULTOMIRIS"}) == (
        "Update on Ultomiris phase III trial in HSCT-TMA")
    assert headlines._sentence_case("NEW GSK FLAGSHIP R&D CENTRE") == (
        "New GSK flagship R&D centre")


def test_a_title_the_filer_already_mixed_is_left_alone():
    """Their capitalisation is their choice where they made one."""
    assert headlines._sentence_case("Positive Phase III data for Riz-Rez") == (
        "Positive Phase III data for Riz-Rez")


def test_the_title_as_filed_survives_in_the_detail(tmp_path):
    """Softening a shouted title guesses at proper nouns. The original rides along so the
    guess is never the only record."""
    path, conn = _seed(tmp_path)
    _filing(conn, "MRK", "6-K", "NEW FLAGSHIP R&D CENTRE IN CAMBRIDGE", "2026-07-28")
    conn.close()
    row = headlines.build(path, today=TODAY)[0]
    filed = next(p for p in row["summary"] if p["label"] == "As filed")
    assert filed["value"] == "NEW FLAGSHIP R&D CENTRE IN CAMBRIDGE"


def test_the_forward_list_leads_with_the_biggest_not_the_soonest():
    """A forty-patient Phase 2 dated tomorrow used to lead the front page over the
    Phase 3 that decides a launch, because the list was a calendar."""
    small = headlines._ahead_weight("data readout", "Phase 2", 40, 0)
    large = headlines._ahead_weight("data readout", "Phase 3", 5000, 0)
    assert large > small


def test_a_decision_outranks_a_readout_of_the_same_size():
    """A PDUFA date is a decision; a registry completion date is an estimate."""
    assert headlines._ahead_weight("PDUFA", "Phase 3", 500, 1) > \
        headlines._ahead_weight("data readout", "Phase 3", 500, 1)


def test_one_enormous_study_cannot_outrank_every_decision():
    """Enrollment is compressed, so a 90,000-patient outcomes trial informs the order
    without taking it over."""
    huge = headlines._ahead_weight("data readout", "Phase 3", 90_000, 0)
    assert huge < headlines._ahead_weight("PDUFA", "Phase 3", 100, 0) + 30


def test_a_missing_phase_or_enrollment_still_ranks():
    """Most registry rows carry neither. They rank on the kind alone rather than erroring
    or sorting to the bottom as zero."""
    assert headlines._ahead_weight("data readout", None, None, 0) > 0


# --- Phase 3 results -------------------------------------------------------
# The most material thing that happens to a drug, and it used to reach the front page
# only sideways, as a trial whose status had changed.

def _filed_readout(conn, ticker, date, phase="3", outcome="positive",
                   drug="volrustomig", quote="The trial met its primary endpoint."):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
        "  event_date, quote, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"acc-{ticker}-{date}", cid, drug, phase, outcome, date, quote,
         "https://example.com/8k"))
    conn.commit()


def _press_readout(conn, ticker, date, title):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO news (company_id, source, title, url, published_at)"
        " VALUES (?, 'press_ir', ?, ?, ?)",
        (cid, title, f"https://example.com/{ticker}-{date}", date))
    # Detected now, dated when the company published it. The feed's window is measured
    # against the wall clock, while the headline is dated off the release itself, which
    # is the same split a real run has: today's read of a release from last Tuesday.
    conn.execute(
        "INSERT INTO changes (entity_type, entity_key, field, old_value, new_value,"
        "  change_type, significance, detected_at) VALUES"
        "  ('company', ?, 'press', NULL, ?, 'press_data_readout', 'high',"
        "   datetime('now'))",
        (f"{ticker}|https://example.com/{ticker}-{date}", title))
    conn.commit()


def test_a_filed_phase_3_result_leads_with_its_outcome(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-29", outcome="positive", drug="intismeran")
    conn.close()

    rows = headlines.build(path, today=TODAY)
    readout = next(r for r in rows if r["kind"] == "readout")
    assert readout["figure"] == "Phase 3 positive"
    assert "intismeran" in readout["headline"]
    # The sentence it was read out of travels with it.
    assert readout["evidence"] == "The trial met its primary endpoint."


def test_a_negative_result_is_the_same_size_of_news(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-29", outcome="negative")
    conn.close()

    readout = next(r for r in headlines.build(path, today=TODAY)
                   if r["kind"] == "readout")
    assert readout["figure"] == "Phase 3 negative"


def test_a_phase_2_result_is_not_a_phase_3_headline(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-29", phase="2")
    _press_readout(conn, "SRPT", "2026-07-29",
                   "SRPT Announces Positive Topline Results from Phase 2 Study")
    conn.close()

    assert not [r for r in headlines.build(path, today=TODAY)
                if r["kind"] == "readout"]


def test_an_announcement_stating_phase_3_reaches_the_page(tmp_path):
    path, conn = _seed(tmp_path)
    _press_readout(conn, "MRK", "2026-07-29",
                   "Merck and Moderna Announce Phase 3 INTerpath-001 Trial Met Endpoints")
    conn.close()

    readout = next(r for r in headlines.build(path, today=TODAY)
                   if r["kind"] == "readout")
    # No outcome is claimed off a company's own adjective; the figure says a result
    # exists and the headline says what the company said.
    assert readout["figure"] == "Phase 3 result"
    assert "INTerpath-001" in readout["headline"]


def test_phase_iii_in_roman_numerals_is_the_same_event(tmp_path):
    path, conn = _seed(tmp_path)
    _press_readout(conn, "MRK", "2026-07-29",
                   "Update on eVOLVE-Lung02 Phase III trial of volrustomig")
    conn.close()
    assert [r for r in headlines.build(path, today=TODAY) if r["kind"] == "readout"]


def test_an_announcement_naming_no_phase_is_not_assumed_to_be_one(tmp_path):
    path, conn = _seed(tmp_path)
    _press_readout(conn, "MRK", "2026-07-29", "Merck reports topline results")
    conn.close()
    assert not [r for r in headlines.build(path, today=TODAY)
                if r["kind"] == "readout"]


def test_the_filed_result_wins_where_both_describe_it(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-28", outcome="negative")
    _press_readout(conn, "MRK", "2026-07-29",
                   "Update on eVOLVE-Lung02 Phase III trial of volrustomig")
    conn.close()

    readouts = [r for r in headlines.build(path, today=TODAY) if r["kind"] == "readout"]
    # One per company, and the one kept is the one with a stated outcome.
    assert len(readouts) == 1
    assert readouts[0]["figure"] == "Phase 3 negative"


def test_a_result_outranks_an_approval_on_the_page(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-29")
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'SRPT'").fetchone()[0]
    conn.execute(
        "INSERT INTO changes (entity_type, entity_key, field, old_value, new_value,"
        "  change_type, significance, detected_at) VALUES"
        "  ('asset', 'SRPT|1', 'approval', NULL, 'FDA approval', 'new_approval',"
        "   'high', '2026-07-29')")
    conn.commit()
    conn.close()

    kinds = [r["kind"] for r in headlines.build(path, today=TODAY)]
    if "approval" in kinds:
        assert kinds.index("readout") < kinds.index("approval")
    else:
        assert "readout" in kinds


def test_a_result_older_than_the_lookback_is_not_this_week(tmp_path):
    path, conn = _seed(tmp_path)
    _filed_readout(conn, "MRK", "2026-07-01")
    conn.close()
    assert not [r for r in headlines.build(path, today=TODAY)
                if r["kind"] == "readout"]
