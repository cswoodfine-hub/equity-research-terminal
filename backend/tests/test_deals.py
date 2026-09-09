"""The deal reader: the guard that a party and a value must be in the filing, multi-deal
extraction, candidate selection, and one filing through a fake model. No network."""

import datetime as dt
import json

import db
import deals
import seed

_DOC = (
    "Biogen Inc. (Nasdaq: BIIB) today announced the successful completion of the "
    "acquisition of Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share in "
    "cash. Apellis is a leader in complement-driven diseases."
)
_MULTI = (
    "Lilly to acquire Kelonia Therapeutics to advance in vivo CAR-T cell therapies. "
    "Lilly to acquire Ajax Therapeutics for patients with myelofibrosis."
)


def test_validate_returns_a_deal_grounded_in_the_text():
    reply = {"deals": [{"deal_type": "acquisition",
                        "counterparty": "Apellis Pharmaceuticals, Inc.",
                        "value": "$41 per share", "area": "complement-driven diseases",
                        "quote": "Biogen Inc. (Nasdaq: BIIB) today announced the "
                                 "successful completion of the acquisition of Apellis "
                                 "Pharmaceuticals, Inc."}]}
    out = deals.validate(reply, _DOC)
    assert len(out) == 1 and out[0]["counterparty"] == "Apellis Pharmaceuticals, Inc."
    assert out[0]["announced_value"] == "$41 per share"


def test_validate_lists_every_deal_a_filing_announces():
    reply = {"deals": [
        {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics",
         "value": None, "area": "in vivo CAR-T cell therapies",
         "quote": "Lilly to acquire Kelonia Therapeutics to advance in vivo CAR-T "
                  "cell therapies"},
        {"deal_type": "acquisition", "counterparty": "Ajax Therapeutics", "value": None,
         "area": "myelofibrosis",
         "quote": "Lilly to acquire Ajax Therapeutics for patients with myelofibrosis"}]}
    out = deals.validate(reply, _MULTI)
    assert {d["counterparty"] for d in out} == {"Kelonia Therapeutics", "Ajax Therapeutics"}


def test_validate_drops_a_party_not_in_the_text():
    """A counterparty from the model's own knowledge cannot become an event."""
    reply = {"deals": [{"deal_type": "acquisition", "counterparty": "Nowhere Bio",
                        "value": None, "area": None,
                        "quote": "acquisition of Apellis Pharmaceuticals, Inc."}]}
    assert deals.validate(reply, _DOC) == []


def test_validate_drops_a_value_not_in_the_text():
    reply = {"deals": [{"deal_type": "acquisition",
                        "counterparty": "Apellis Pharmaceuticals", "value": "$6.5 billion",
                        "area": None,
                        "quote": "completion of the acquisition of Apellis "
                                 "Pharmaceuticals, Inc."}]}
    out = deals.validate(reply, _DOC)
    assert len(out) == 1 and out[0]["announced_value"] is None


def test_validate_rejects_an_out_of_scope_type_and_a_non_deal():
    good_quote = "acquisition of Apellis Pharmaceuticals, Inc. (Nasdaq: APLS)"
    assert deals.validate({"deals": [{"deal_type": "financing",
                                      "counterparty": "Apellis Pharmaceuticals",
                                      "quote": good_quote}]}, _DOC) == []
    assert deals.validate({"deals": []}, _DOC) == []


def _seed_filing(db_file, ticker, form, title, date, accession):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, ?, ?, ?, ?, 'http://x/f.htm')",
                 (cid, accession, form, date, title))
    conn.commit()
    conn.close()


def test_candidates_pick_deal_titles_and_skip_the_already_read(tmp_path):
    db_file = tmp_path / "t.db"
    old = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    _seed_filing(db_file, "LLY", "8-K", "Results of operations", old, "acc-earn")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    # a routine 8-K that is not a deal title, and a deal filing already recorded
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-vote', '8-K', ?, 'Shareholder vote',"
                 " 'http://x/v.htm')", (cid, old))
    conn.execute("INSERT INTO deals (accession, company_id, deal_type) VALUES"
                 " ('acc-seen', ?, 'none')", (cid,))
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-seen', '8-K', ?, 'Other events',"
                 " 'http://x/s.htm')", (cid, old))
    conn.commit()
    conn.close()

    got = {c["accession"] for c in deals.candidates(db_file)}
    assert got == {"acc-earn"}          # earnings title kept, vote dropped, seen skipped


def test_store_writes_a_row_per_deal_and_a_none_marker(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_filing(db_file, "LLY", "8-K", "Results of operations", "2026-04-30", "acc-multi")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    filing = {"accession": "acc-multi", "company_id": cid, "filed_date": "2026-04-30",
              "url": "http://x/f.htm"}
    deals._store(conn, filing, [
        {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics",
         "announced_value": None, "area": "in vivo CAR-T", "quote": "q1"},
        {"deal_type": "acquisition", "counterparty": "Ajax Therapeutics",
         "announced_value": None, "area": "myelofibrosis", "quote": "q2"}])
    empty = {"accession": "acc-none", "company_id": cid, "filed_date": "2026-04-30",
             "url": "http://x/g.htm"}
    deals._store(conn, empty, [])
    conn.commit()
    parties = [r[0] for r in conn.execute(
        "SELECT counterparty FROM deals WHERE accession='acc-multi' ORDER BY counterparty")]
    assert parties == ["Ajax Therapeutics", "Kelonia Therapeutics"]
    assert conn.execute("SELECT deal_type FROM deals WHERE accession='acc-none'"
                        ).fetchone()[0] == "none"
    conn.close()


def test_classify_runs_the_model_and_validates(tmp_path):
    filing = {"form_type": "8-K", "filed_date": "2026-05-14"}

    def fake_complete(system, user, max_tokens, prefer=None, thinking_budget=None):
        return ('{"deals": [{"deal_type": "acquisition", "counterparty": '
                '"Apellis Pharmaceuticals, Inc.", "value": "$41 per share", '
                '"area": "complement-driven diseases", "quote": "acquisition of '
                'Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share"}]}')

    out = deals._classify(_DOC, filing, fake_complete)
    assert len(out) == 1 and out[0]["announced_value"] == "$41 per share"


def test_recent_dedupes_to_earliest_merges_value_and_shortens(tmp_path):
    """The tab reader: one row per counterparty, earliest date, value merged from any
    filing and trimmed to the headline, and a party trimmed of its legal chain."""
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='GILD'").fetchone()[0]
    conn.execute("INSERT INTO deals (accession, company_id, deal_type, counterparty,"
                 " announced_value, area, event_date) VALUES ('g0', ?, 'acquisition',"
                 " 'Arcellx, Inc.', '$7.8 billion in cash plus a contingent value right"
                 " of up to $2 more per share', 'oncology', '2026-02-23')", (cid,))
    conn.execute("INSERT INTO deals (accession, company_id, deal_type, counterparty,"
                 " announced_value, area, event_date) VALUES ('g1', ?, 'acquisition', 'Arcellx',"
                 " NULL, NULL, '2026-05-07')", (cid,))
    conn.execute("INSERT INTO deals (accession, company_id, deal_type, counterparty,"
                 " announced_value, area, event_date) VALUES ('c1', ?, 'collaboration',"
                 " 'Sino Biopharmaceutical, (SBP Group), through its subsidiary Chia Tai"
                 " Tianqing Pharmaceutical Group Co., Ltd.', NULL, 'hepatitis B',"
                 " '2026-05-11')", (cid,))
    conn.commit()
    conn.close()

    rows = deals.recent(db_file, "GILD", today=dt.date(2026, 7, 26))
    arcellx = next(r for r in rows if r["counterparty"].startswith("Arcellx"))
    assert arcellx["event_date"] == "2026-02-23"        # earliest, not the later filing
    assert arcellx["announced_value"] == "$7.8 billion"           # trimmed from the long clause
    assert arcellx["area"] == "oncology"
    sino = next(r for r in rows if r["deal_type"] == "collaboration")
    assert sino["counterparty"] == "Sino Biopharmaceutical"   # trimmed of the legal chain


_DATED = ("Big Pharma today announced that on April 20, 2026 it entered a definitive "
          "agreement to acquire Kelonia Therapeutics, Inc. to advance in vivo therapies.")


def test_announced_date_kept_only_when_it_appears_in_the_text():
    base = {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics, Inc.",
            "announced_value": None, "area": "in vivo therapies",
            "quote": "entered a definitive agreement to acquire Kelonia Therapeutics, Inc."}
    grounded = deals.validate({"deals": [{**base, "announced_date": "2026-04-20"}]}, _DATED)
    assert grounded[0]["announced_date"] == "2026-04-20"        # "April 20, 2026" is in the text
    invented = deals.validate({"deals": [{**base, "announced_date": "2025-01-01"}]}, _DATED)
    assert invented[0]["announced_date"] is None                # not in the text, dropped


def test_store_dates_a_deal_to_the_announcement_when_grounded(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_filing(db_file, "LLY", "8-K", "Results of operations", "2026-04-30", "acc-x")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    filing = {"accession": "acc-x", "company_id": cid, "filed_date": "2026-04-30",
              "url": "http://x/f.htm"}
    deals._store(conn, filing, [
        {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics",
         "announced_value": None, "area": "in vivo", "announced_date": "2026-04-20", "quote": "q"},
        {"deal_type": "acquisition", "counterparty": "Orna Therapeutics",
         "announced_value": None, "area": "cell", "announced_date": None, "quote": "q"}])
    conn.commit()
    dates = dict(conn.execute("SELECT counterparty, event_date FROM deals").fetchall())
    conn.close()
    assert dates["Kelonia Therapeutics"] == "2026-04-20"   # the announcement date
    assert dates["Orna Therapeutics"] == "2026-04-30"      # no date stated, so the filing


def test_announced_usd_reads_the_number_and_refuses_a_share_price():
    assert deals.announced_usd("up to $3.8 billion") == 3.8e9
    assert deals.announced_usd("$202 million") == 202e6
    assert deals.announced_usd("$2.25B") == 2.25e9
    # A price per share is not a deal size, so it stays absent rather than being read
    # as one: "$41 per share" is not a $41 deal.
    assert deals.announced_usd("$41 per share") is None
    assert deals.announced_usd("undisclosed") is None
    assert deals.announced_usd(None) is None


def test_deal_area_uses_the_pipeline_taxonomy():
    assert deals.deal_area({"area": "treatments for sleep-wake disorders"}) == "Neuroscience"
    assert deals.deal_area(
        {"area": "outcomes for patients with myelofibrosis"}) == "Haematology"
    # The headline names the disease where the area names only the modality.
    assert deals.deal_area({"area": "cell therapies",
                            "quote": "Lilly buys into lung cancer"}) == "Oncology"
    # A modality is not a disease and is never guessed into an area.
    assert deals.deal_area({"area": "in vivo CAR-T cell therapies", "quote": ""}) is None
    assert deals.deal_area({}) is None


# --- the terms, from the press release to the panel ------------------------------------

SAIL_RELEASE = (
    "Johnson & Johnson Announces Collaboration with Sail Biomedicines. "
    "Additionally, Johnson & Johnson has been granted an exclusive option to acquire "
    "Sail for $2.58 billion. Under the terms of the agreements, Johnson & Johnson would "
    "make total initial payments of $785 million, including a $465 million equity "
    "investment, and additional contingent payments of $140 million if certain "
    "development milestones are achieved.")


def _deals_db(tmp_path):
    db_file = tmp_path / "terms.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'JNJ'").fetchone()[0]
    return db_file, conn, cid


def _news_deal(conn, cid, party, date):
    """A deal as the news route captures it: a party, a type, and no size at all."""
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  event_date_source) VALUES (?, 'collaboration', ?, ?, 'headline', 'news')",
        (cid, party, date))
    conn.commit()


def _exhibit(conn, cid, text, date, accession="0001-1", section="exhibit"):
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "  section, char_count, text) VALUES (?, ?, '8-K', ?, ?, ?, ?)",
        (cid, accession, date, section, len(text), text))
    conn.commit()


def test_enrich_fills_a_news_deal_from_the_press_release(tmp_path):
    """The wire runs the headline the morning of the 8-K. The terms are in the exhibit
    furnished with it, and the two are matched on the party's name in the document."""
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-29")
    _exhibit(conn, cid, SAIL_RELEASE, "2026-07-29")
    conn.close()

    assert deals.enrich(db_file)["filled"] == 1

    row = deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))[0]
    assert row["terms_summary"] == (
        "$785m upfront, $465m equity, $140m milestones, $2.58bn option to acquire")
    assert row["headline_usd"] == 2.58e9
    assert "total initial payments" in row["terms_evidence"]


def test_the_terms_belong_to_the_party_named_in_the_document(tmp_path):
    """J&J furnished two press releases with one 8-K, Firefly at 1bn and Sail at 2.58bn.
    Matching on the filing alone would give each the other's numbers."""
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Firefly Bio", "2026-07-29")
    _exhibit(conn, cid, SAIL_RELEASE, "2026-07-29")
    _exhibit(conn, cid,
             "Johnson & Johnson Completes Acquisition of Firefly Bio, Inc. for $1 billion "
             "in cash.", "2026-07-29", section="exhibit_2")
    conn.close()

    deals.enrich(db_file)
    row = deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))[0]
    assert row["headline_usd"] == 1e9
    assert row["terms_summary"] == "$1bn total"


def test_the_structure_beats_a_headline_figure_on_the_card(tmp_path):
    """A wire's "$2.58 billion" is the option price. The deal is also 785m of cash today,
    and the card has to be able to say both."""
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  announced_value, announced_value_source) VALUES (?, 'collaboration',"
        "  'Sail Biomedicines', '2026-07-29', 'q', '$2.58 billion', 'news')", (cid,))
    conn.commit()
    _exhibit(conn, cid, SAIL_RELEASE, "2026-07-29")
    conn.close()

    deals.enrich(db_file)
    row = deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))[0]
    assert "785m upfront" in deals.deal_line(row)
    assert row["announced_usd"] == 2.58e9


def test_a_deal_with_no_press_release_keeps_what_the_headline_gave(tmp_path):
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  announced_value, announced_value_source) VALUES (?, 'acquisition',"
        "  'Firefly Bio', '2026-06-08', 'q', '$1 billion', 'news')", (cid,))
    conn.commit()
    conn.close()

    assert deals.enrich(db_file)["filled"] == 0
    row = deals.recent(db_file, "JNJ", today=dt.date(2026, 6, 9))[0]
    assert row["terms_summary"] == ""
    assert row["announced_value"] == "$1 billion"
    assert "for $1 billion" in deals.deal_line(row)


def test_terms_from_a_later_filing_reach_the_earlier_row(tmp_path):
    """A deal arrives on a wire and its structure lands with the 8-K a day or two after."""
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-27")
    _exhibit(conn, cid, SAIL_RELEASE, "2026-07-29")
    conn.close()

    assert deals.enrich(db_file)["filled"] == 1
    assert deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))[0]["headline_usd"]


# --- reaching a release that is not stored yet -----------------------------------------

def _filing_row(conn, cid, accession, date, form="8-K"):
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 "  title, url) VALUES (?, ?, ?, ?, 'Other events',"
                 "  ?)",
                 (cid, accession, form, date,
                  f"https://www.sec.gov/Archives/edgar/data/1/{accession}/x.htm"))
    conn.commit()


def _fake_get(pages):
    """A get() over a dict of url fragment -> body, counting what it was asked for."""
    calls = []

    def get(url):
        calls.append(url)
        for fragment, body in pages.items():
            if fragment in url:
                return body
        raise RuntimeError(f"no page for {url}")

    return get, calls


def test_enrich_fetches_the_release_when_none_is_stored(tmp_path):
    """The filing-text fetcher keeps the latest few current reports per company, which is
    a month or two of an active filer. A deal from last summer needs its own release."""
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-29")
    _filing_row(conn, cid, "0001-9", "2026-07-29")
    conn.close()

    get, calls = _fake_get({
        "index.json": json.dumps({"directory": {"item": [{"name": "ex99_1.htm",
                                                          "size": "900"}]}}),
        "ex99_1.htm": f"<p>{SAIL_RELEASE}</p>",
    })
    assert deals.enrich(db_file, get=get) == {"filled": 1, "fetched": 1, "errors": []}
    row = deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))[0]
    assert row["headline_usd"] == 2.58e9


def test_the_live_fetch_is_bounded(tmp_path):
    """EDGAR is polite or it is blocked, so a first run works through the backlog rather
    than pulling every release a company ever filed."""
    db_file, conn, cid = _deals_db(tmp_path)
    for day in range(1, 6):
        _news_deal(conn, cid, f"Party {day} Bio", f"2026-07-0{day}")
        _filing_row(conn, cid, f"0002-{day}", f"2026-07-0{day}")
    conn.close()

    get, calls = _fake_get({"index.json": json.dumps({"directory": {"item": []}}),
                            "x.htm": "<p>nothing here</p>"})
    result = deals.enrich(db_file, limit=2, get=get)
    assert result["fetched"] == 2
    assert result["filled"] == 0


def test_one_filing_is_fetched_once_for_two_deals(tmp_path):
    """A single 8-K can carry the terms of two deals, and a company files several a
    quarter. Fetching per deal would read the same document twice."""
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-29")
    _news_deal(conn, cid, "Firefly Bio", "2026-07-29")
    _filing_row(conn, cid, "0003-1", "2026-07-29")
    conn.close()

    get, calls = _fake_get({
        "index.json": json.dumps({"directory": {"item": [{"name": "ex99_1.htm",
                                                          "size": "900"}]}}),
        "ex99_1.htm": (f"<p>{SAIL_RELEASE} Separately, we completed the acquisition of "
                       "Firefly Bio, Inc. for $1 billion in cash.</p>"),
    })
    result = deals.enrich(db_file, get=get)
    assert result["fetched"] == 1          # one accession, not one per deal
    assert result["filled"] == 2


def test_an_unreadable_filing_does_not_stop_the_run(tmp_path):
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Broken Bio", "2026-07-28")
    _filing_row(conn, cid, "0004-1", "2026-07-28")
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-29")
    _filing_row(conn, cid, "0005-1", "2026-07-29")
    conn.close()

    def get(url):
        if "0004-1" in url:
            raise OSError("timed out")
        if "index.json" in url:
            return json.dumps({"directory": {"item": [{"name": "ex99_1.htm",
                                                        "size": "900"}]}})
        return f"<p>{SAIL_RELEASE}</p>"

    result = deals.enrich(db_file, get=get)
    assert result["filled"] == 1
    assert len(result["errors"]) == 1


def test_a_stored_release_costs_no_fetch(tmp_path):
    db_file, conn, cid = _deals_db(tmp_path)
    _news_deal(conn, cid, "Sail Biomedicines", "2026-07-29")
    _exhibit(conn, cid, SAIL_RELEASE, "2026-07-29")
    _filing_row(conn, cid, "0006-1", "2026-07-29")
    conn.close()

    get, calls = _fake_get({"x": "unused"})
    result = deals.enrich(db_file, get=get)
    assert result == {"filled": 1, "fetched": 0, "errors": []}
    assert calls == []


# --- what counts as a counterparty ------------------------------------------------------

def test_a_company_is_a_party():
    for name in ("Sail Biomedicines", "Firefly Bio", "Madrigal Pharmaceuticals",
                 "RemeGen", "Modella AI", "Viz.ai", "Kyowa Kirin Co., Ltd.",
                 "Thermo Fisher Scientific", "West Pharmaceutical Services",
                 "Bio Palette Co., Ltd.", "Mayo Clinic", "US WorldMeds"):
        assert deals.is_party(name), name


def test_the_thing_being_bought_is_not_the_party():
    """"Arrowhead licenses Clinical MASH Program Targeting PNPLA3 to Madrigal" names
    Madrigal, and "Axsome Acquires Selective PDE10A Inhibitor" names nobody."""
    assert not deals.is_party("MASH Program Targeting PNPLA3")
    assert not deals.is_party("Selective PDE10A Inhibitor")
    assert not deals.is_party("Biologics License Application")


def test_a_building_is_not_a_company():
    """"Rubicon Point Partners Acquires Shockwave Medical Headquarters Campus" is a
    real-estate deal that mentions a covered company's address."""
    assert not deals.is_party("Shockwave Medical Headquarters Campus")


def test_a_bare_noun_left_by_a_truncated_name_is_not_a_party():
    """The capital-letter match stops where a name runs on in lower case: "acquire China
    rights", "Collaboration with Department of Health - Abu Dhabi"."""
    assert not deals.is_party("China")
    assert not deals.is_party("Department")
    assert not deals.is_party("Application")


def test_letters_a_filer_spaced_out_are_rejoined():
    """A contract exhibit renders with letter spacing: "K YOWA K IRIN C O ., L TD ."."""
    assert deals.unspace("K YOWA K IRIN C O ., L TD .") == "KYOWA KIRIN CO., LTD."


def test_two_initials_are_left_alone():
    """Three or more single letters is a rendering artefact; two is a person."""
    assert deals.unspace("J P Morgan") == "J P Morgan"


def test_a_roundup_is_not_one_company_s_deal():
    """"Pharma M&A Roundup: Gilead Expands Collaboration with World Health Organization,
    Johnson & Johnson Enters Collaboration with Department of Health" put WHO against
    J&J."""
    assert deals.NOT_OUR_DEAL.search(
        "Pharma M&A Roundup: Gilead Sciences Expands Collaboration with WHO")


def test_a_marketing_tie_up_is_not_business_development():
    assert deals.NOT_OUR_DEAL.search(
        "Johnson & Johnson Announces Collaboration with TIME to Introduce New "
        "Healthcare Champion of the Year Award")


def test_prune_clears_a_party_that_is_not_one(tmp_path):
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
                 "  quote, event_date_source) VALUES (?, 'acquisition', 'China',"
                 "  '2026-01-19', 'AstraZeneca to acquire China rights', 'news')", (cid,))
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
                 "  quote, event_date_source) VALUES (?, 'collaboration',"
                 "  'Sail Biomedicines', '2026-07-29', 'J&J and Sail', 'news')", (cid,))
    conn.commit()
    conn.close()

    assert deals.prune_parties(db_file)["dropped"] == 1
    kept = deals.recent(db_file, "JNJ", today=dt.date(2026, 7, 30))
    assert [d["counterparty"] for d in kept] == ["Sail Biomedicines"]


def test_prune_rejoins_a_spaced_name(tmp_path):
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
                 "  quote, accession) VALUES (?, 'collaboration',"
                 "  'K YOWA K IRIN C O ., L TD .', '2026-01-30', 'a contract', '0001-1')",
                 (cid,))
    conn.commit()
    conn.close()

    assert deals.prune_parties(db_file) == {"dropped": 0, "fixed": 1}
    kept = deals.recent(db_file, "JNJ", today=dt.date(2026, 2, 1))
    assert kept[0]["counterparty"] == "KYOWA KIRIN CO., LTD."


def test_the_headline_rule_is_not_applied_to_a_filing(tmp_path):
    """A filing's quote is prose. A sentence about an acquisition mentions a headquarters
    or an award in passing without being about either, and applying a headline rule to it
    deleted a real deal."""
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
                 "  quote, accession, event_date_source) VALUES (?, 'acquisition',"
                 "  'Vidya Therapeutics', '2026-07-30',"
                 "  'We acquired Vidya Therapeutics, whose headquarters are in Boston.',"
                 "  '0002-1', 'filing')", (cid,))
    conn.commit()
    conn.close()

    assert deals.prune_parties(db_file)["dropped"] == 0


def test_prune_clears_a_holder_named_instead_of_the_party(tmp_path):
    """The headline parser steps over "BIOG portfolio company" now. This clears the row
    it wrote before it did."""
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  event_date_source) VALUES (?, 'acquisition', 'BIOG', '2026-07-28',"
        "  'argenx SE to acquire BIOG portfolio company, Forte Biosciences, Inc',"
        "  'news')", (cid,))
    conn.commit()
    conn.close()
    assert deals.prune_parties(db_file)["dropped"] == 1


def test_a_company_with_subsidiaries_is_not_a_holder(tmp_path):
    """The phrase has to sit right after the name. A headline that mentions a party and
    a subsidiary elsewhere in the sentence is still that party's deal."""
    db_file, conn, cid = _deals_db(tmp_path)
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  event_date_source) VALUES (?, 'acquisition', 'Alpha Bio', '2026-07-28',"
        "  'J&J to acquire Alpha Bio, expanding a subsidiary in Boston', 'news')", (cid,))
    conn.commit()
    conn.close()
    assert deals.prune_parties(db_file)["dropped"] == 0


# --- the questions a reader asks about a deal ----------------------------

ZEGFROVY_DOC = (
    "AstraZeneca has acquired exclusive rights to ZEGFROVY from Dizal outside "
    "Greater China. Financial considerations AstraZeneca will make an upfront payment "
    "of $600m to Dizal together with additional payments of up to $900m upon "
    "achievement of specific development, regulatory and sales-related milestones. "
    "ZEGFROVY is approved in the US for adult patients with locally advanced or "
    "metastatic non-small cell lung cancer with EGFR exon 20 insertion mutations "
    "whose disease has progressed on or after platinum-based chemotherapy. The "
    "acquisition strengthens AstraZeneca's lung cancer portfolio and complements its "
    "existing EGFR medicines. AstraZeneca plans to explore ZEGFROVY in earlier lines "
    "of therapy and to file in additional geographies."
)


def _reply(**over):
    deal = {"deal_type": "acquisition", "counterparty": "Dizal",
            "value": "$600m", "area": "lung cancer", "announced_date": None,
            "quote": "AstraZeneca has acquired exclusive rights to ZEGFROVY from Dizal "
                     "outside Greater China"}
    deal.update(over)
    return {"deals": [deal]}


def test_the_four_reader_questions_are_kept_when_the_text_answers_them():
    """A deal was recorded as a verb, a party and a figure, which answers one of the five
    things a reader asks and none of the other four."""
    got = deals.validate(_reply(
        rationale="Strengthens AstraZeneca's lung cancer portfolio and complements its "
                  "existing EGFR medicines",
        intended_use="Adds an EGFR medicine to the lung cancer portfolio",
        approval_scope="Approved in the US for metastatic non-small cell lung cancer "
                       "with EGFR exon 20 insertion mutations after platinum-based "
                       "chemotherapy",
        expansion="Plans to explore earlier lines of therapy and to file in additional "
                  "geographies"), ZEGFROVY_DOC)
    assert len(got) == 1
    assert got[0]["rationale"].startswith("Strengthens")
    assert "exon 20" in got[0]["approval_scope"]
    assert "earlier lines" in got[0]["expansion"]


def test_an_answer_the_document_does_not_support_is_dropped():
    """These are the model's sentences, not the filer's, so they cannot be checked by
    substring the way a quote is. What they may not do is introduce subject matter the
    source never mentions."""
    got = deals.validate(_reply(
        rationale="Expands the company's presence in paediatric rheumatology and "
                  "dermatology across Japanese hospital formularies"), ZEGFROVY_DOC)
    assert got[0]["rationale"] is None


def test_an_unanswered_question_is_null_rather_than_padded():
    got = deals.validate(_reply(), ZEGFROVY_DOC)
    assert got[0]["rationale"] is None
    assert got[0]["expansion"] is None


def test_the_summary_carries_only_the_questions_that_were_answered():
    """A deal announced in three lines carries one of these, not five: a heading with
    nothing under it reads as a fact withheld rather than a fact absent."""
    line = deals.deal_line({
        "deal_type": "acquisition", "counterparty": "Dizal", "event_date": "2026-09-01",
        "announced_value": "$600 million", "area": "Oncology",
        "rationale": "Strengthens the lung cancer portfolio.",
        "approval_scope": "US approval in EGFR exon 20 insertion NSCLC.",
        "intended_use": None, "expansion": None})
    assert line.startswith("Acquired Dizal for $600 million (Oncology), 2026-09-01.")
    assert "Why: Strengthens the lung cancer portfolio." in line
    assert "Approval: US approval in EGFR exon 20 insertion NSCLC." in line
    assert "Use:" not in line and "Next:" not in line


# --- backfilling deals recorded before the questions were asked ----------

def _deal_db(tmp_path, *, sections=True, terms=True):
    path = str(tmp_path / "d.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'AstraZeneca')")
    conn.execute(
        "INSERT INTO deals (id, accession, company_id, deal_type, counterparty,"
        " event_date, quote, terms_evidence) VALUES (1, 'a1', 1, 'acquisition',"
        " 'Dizal', '2026-09-01', ?, ?)",
        ("AstraZeneca acquires ZEGFROVY rights for $600 million",
         ZEGFROVY_DOC if terms else None))
    if sections:
        conn.execute(
            "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
            " section, text) VALUES (1, 'a1', '8-K', '2026-09-01', 'body', ?)",
            (ZEGFROVY_DOC,))
    conn.commit()
    conn.close()
    return path


def test_a_deal_with_only_its_own_headline_is_not_sent_to_the_model(tmp_path):
    """One sentence cannot answer four questions. Asking anyway spends a call to be told
    nothing, or tempts an answer the grounding then throws away."""
    path = _deal_db(tmp_path, sections=False, terms=False)
    calls = []

    def complete(*a, **k):
        calls.append(a)
        raise AssertionError("should not be called")

    out = deals.backfill_aspects(path, complete=complete)
    assert calls == []
    assert out["read"] == 0 and out["skipped"] == 1 and out["filled"] == 0


def test_a_deal_with_a_filing_on_file_is_read_and_filled(tmp_path):
    path = _deal_db(tmp_path)
    reply = ('{"rationale": "Strengthens AstraZeneca\'s lung cancer portfolio and '
             'complements its existing EGFR medicines", "intended_use": null, '
             '"approval_scope": "Approved in the US for metastatic non-small cell lung '
             'cancer with EGFR exon 20 insertion mutations", "expansion": null}')
    out = deals.backfill_aspects(path, complete=lambda *a, **k: reply)
    assert out["read"] == 1 and out["filled"] == 1
    conn = db.get_connection(path)
    row = conn.execute("SELECT * FROM deals WHERE id = 1").fetchone()
    conn.close()
    assert row["rationale"].startswith("Strengthens")
    assert "exon 20" in row["approval_scope"]
    assert row["intended_use"] is None and row["expansion"] is None


def test_the_backfill_is_idempotent(tmp_path):
    """A row carrying any answer is not read again, so a second pass costs nothing."""
    path = _deal_db(tmp_path)
    reply = '{"rationale": "Strengthens the lung cancer portfolio", "intended_use": null,' \
            ' "approval_scope": null, "expansion": null}'
    assert deals.backfill_aspects(path, complete=lambda *a, **k: reply)["filled"] == 1
    again = deals.backfill_aspects(path, complete=lambda *a, **k: reply)
    assert again["read"] == 0 and again["filled"] == 0


def test_an_answer_the_document_does_not_carry_is_refused_on_backfill_too(tmp_path):
    path = _deal_db(tmp_path)
    reply = ('{"rationale": "Expands the paediatric rheumatology franchise across '
             'Japanese hospital formularies", "intended_use": null, '
             '"approval_scope": null, "expansion": null}')
    out = deals.backfill_aspects(path, complete=lambda *a, **k: reply)
    assert out["read"] == 1 and out["filled"] == 0
    conn = db.get_connection(path)
    assert conn.execute("SELECT rationale FROM deals WHERE id = 1").fetchone()[0] is None
    conn.close()
