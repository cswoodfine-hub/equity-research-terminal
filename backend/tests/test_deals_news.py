"""The headline parser, tested on the headlines it will actually see.

Every case here is a real Google News title from the Lilly feed, publisher suffix and
all. A headline parser earns its keep by what it refuses: the commentary cases matter
more than the deal cases, since a false deal is worse than a missed one.
"""

import db
from fetchers.deals_news import (DealsNewsFetcher, parse_area, parse_deal,
                                 parse_feed, parse_value)

NAMES = {"Eli Lilly and Company", "LLY", "Lilly"}


def test_reads_an_acquisition():
    deal = parse_deal("Eli Lilly acquires Ajax Therapeutics - Reuters", NAMES)
    assert deal["deal_type"] == "acquisition"
    assert deal["counterparty"] == "Ajax Therapeutics"
    assert deal["announced_value"] is None


def test_reads_the_value_and_stops_at_the_company_name():
    deal = parse_deal(
        "Eli Lilly signs a deal with Innovent Biologics worth $8.85 billion - Fierce",
        NAMES)
    assert deal["counterparty"] == "Innovent Biologics"
    assert deal["announced_value"] == "$8.85 billion"


def test_reads_a_licensing_deal():
    deal = parse_deal(
        "Lilly licenses rights to Nimbus Therapeutics obesity programme - Endpoints",
        NAMES)
    assert deal["deal_type"] == "licensing"
    assert deal["counterparty"] == "Nimbus Therapeutics"


def test_keeps_up_to_because_it_means_milestones():
    assert parse_value("deal worth up to $3.8 billion") == "up to $3.8 billion"
    assert parse_value("a $2.25B buy") == "$2.25 billion"
    assert parse_value("$950 million upfront") == "$950 million"
    assert parse_value("no number here") is None


def test_refuses_commentary():
    for headline in (
            "Why other Big Pharmas could follow Lilly into psychedelics - Fierce",
            "Eli Lilly Has Been On An Acquisition Spree - Yahoo",
            "Lilly moves closer to major acquisition, reportedly - Barron's",
            "Is Eli Lilly about to acquire a rival? - Motley Fool",
    ):
        assert parse_deal(headline, NAMES) is None


def test_refuses_the_passive_voice():
    # Names the same two parties the other way round, and no counterparty this way.
    assert parse_deal("Startup to acquire Eli Lilly unit - Reuters", NAMES) is None


def test_parses_a_feed():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Eli Lilly acquires Verve Therapeutics - PR</title>
        <link>https://news.example/1</link>
        <pubDate>Wed, 16 Jul 2025 09:00:00 GMT</pubDate></item>
      <item><title>No date here</title><link>https://news.example/2</link>
        <pubDate>not a date</pubDate></item>
    </channel></rss>"""
    items = parse_feed(xml)
    assert [i["date"] for i in items] == ["2025-07-16", None]
    assert items[0]["link"] == "https://news.example/1"


def _seed(tmp_path):
    path = str(tmp_path / "news.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.commit()
    conn.close()
    return path, cid


def _feed(*titles):
    items = "".join(
        f"<item><title>{t}</title><link>https://n/{i}</link>"
        f"<pubDate>Wed, 16 Jul 2025 09:00:00 GMT</pubDate></item>"
        for i, t in enumerate(titles))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_writes_one_row_per_deal_and_dedupes_retellings(tmp_path):
    path, cid = _seed(tmp_path)
    fetcher = DealsNewsFetcher(path)
    raw = {"companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
           "feeds": {"LLY": _feed(
               "Eli Lilly acquires Ajax Therapeutics - Reuters",
               "Eli Lilly acquires Ajax Therapeutics for $1B - Bloomberg",
               "Eli Lilly partners with Camurus - Endpoints")},
           "errors": []}
    rows = fetcher.normalise(raw)
    assert [r["counterparty"] for r in rows] == ["Ajax Therapeutics", "Camurus"]
    assert fetcher.upsert(rows).rows_fetched == 2

    conn = db.get_connection(path)
    stored = conn.execute(
        "SELECT counterparty, deal_type, accession FROM deals ORDER BY counterparty"
    ).fetchall()
    conn.close()
    assert [r["counterparty"] for r in stored] == ["Ajax Therapeutics", "Camurus"]
    # A null accession is what marks the row as read off a headline, not a filing.
    assert all(r["accession"] is None for r in stored)


def test_never_restates_a_deal_the_filings_already_named(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty,"
        "                    announced_value)"
        " VALUES ('0000-24-1', ?, 'acquisition', 'Ajax Therapeutics', '$1.0 billion')",
        (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed("Eli Lilly acquires Ajax Therapeutics - Reuters")},
        "errors": []})
    assert fetcher.upsert(rows).rows_fetched == 0

    conn = db.get_connection(path)
    stored = conn.execute(
        "SELECT accession, announced_value FROM deals").fetchall()
    conn.close()
    assert len(stored) == 1
    assert stored[0]["accession"] == "0000-24-1"      # the filing's row, untouched
    assert stored[0]["announced_value"] == "$1.0 billion"


def test_fills_a_size_the_filing_left_blank(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty)"
        " VALUES ('0000-24-1', ?, 'acquisition', 'Orna Therapeutics')", (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed(
            "Eli Lilly acquires Orna Therapeutics for $8.5 billion - Fierce")},
        "errors": []})
    result = fetcher.upsert(rows)
    assert result.rows_fetched == 0                  # no new row, the filing has it
    assert "1 filed deals gained a size from a headline" in result.notes

    conn = db.get_connection(path)
    stored = conn.execute("SELECT * FROM deals").fetchall()
    conn.close()
    assert len(stored) == 1
    assert stored[0]["accession"] == "0000-24-1"     # still the filing's row
    assert stored[0]["announced_value"] == "$8.5 billion"
    assert stored[0]["announced_value_source"] == "news"


def test_never_overwrites_a_size_the_filing_states(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty,"
        "                   announced_value, announced_value_source)"
        " VALUES ('0000-24-1', ?, 'acquisition', 'Orna Therapeutics', '$2.4 billion',"
        "         'filing')", (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed(
            "Eli Lilly acquires Orna Therapeutics for $8.5 billion - Fierce")},
        "errors": []})
    notes = fetcher.upsert(rows).notes
    assert not any("size" in n for n in notes)

    conn = db.get_connection(path)
    row = conn.execute("SELECT announced_value, announced_value_source FROM deals").fetchone()
    conn.close()
    assert row["announced_value"] == "$2.4 billion"
    assert row["announced_value_source"] == "filing"


def test_reads_what_the_deal_is_for_from_the_headline():
    assert parse_area("Lilly snaps up Engage to advance non-viral genetic medicines") \
        == "non-viral genetic medicines"
    # Title case is undone per hyphen segment, so CAR-T keeps its capitals.
    assert parse_area("Lilly to acquire Kelonia to advance in vivo CAR-T cell therapies") \
        == "in vivo CAR-T cell therapies"
    assert parse_area(
        "Eli Lilly Acquires AtaiBeckley to Expand Mental Health Pipeline in $3.8 Billion"
        " Deal") == "mental health pipeline"
    # A headline that states no purpose gets no area rather than a guess.
    assert parse_area("Eli Lilly acquires Ajax Therapeutics - Reuters") is None


def test_moves_a_filed_deal_to_its_announcement_date(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty, event_date,"
        "                   event_date_source)"
        " VALUES ('0000-26-1', ?, 'acquisition', 'Orna Therapeutics', '2026-04-30',"
        "         'filing')", (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed(
            "Lilly to acquire Orna Therapeutics to advance cell therapies")},
        "errors": []})
    result = fetcher.upsert(rows)
    assert "1 filed deals moved to their announcement date" in result.notes

    conn = db.get_connection(path)
    row = conn.execute("SELECT * FROM deals").fetchone()
    conn.close()
    assert row["event_date"] == "2025-07-16"          # the day it was announced
    assert row["event_date_source"] == "news"
    assert row["area"] == "cell therapies"            # the filing stated none


def test_never_moves_a_date_later(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty, event_date,"
        "                   event_date_source)"
        " VALUES ('0000-26-1', ?, 'acquisition', 'Orna Therapeutics', '2025-02-09',"
        "         'filing')", (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed("Lilly completes acquisition of Orna Therapeutics")},
        "errors": []})
    notes = fetcher.upsert(rows).notes
    assert not any("announcement date" in n for n in notes)

    conn = db.get_connection(path)
    date = conn.execute("SELECT event_date FROM deals").fetchone()["event_date"]
    conn.close()
    assert date == "2025-02-09"      # a recap is not an announcement


def test_links_a_filed_deal_to_the_article_that_announced_it(tmp_path):
    path, cid = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO deals (accession, company_id, deal_type, counterparty, source_url)"
        " VALUES ('0000-26-1', ?, 'acquisition', 'Orna Therapeutics',"
        "         'https://www.sec.gov/Archives/edgar/data/59478/lly-20260430.htm')",
        (cid,))
    conn.commit()
    conn.close()

    fetcher = DealsNewsFetcher(path)
    rows = fetcher.normalise({
        "companies": [{"id": cid, "ticker": "LLY", "name": "Eli Lilly"}],
        "feeds": {"LLY": _feed("Lilly to acquire Orna Therapeutics")},
        "errors": []})
    assert "1 filed deals linked to their announcing article" in fetcher.upsert(rows).notes

    conn = db.get_connection(path)
    row = conn.execute("SELECT source_url, article_url FROM deals").fetchone()
    conn.close()
    assert row["article_url"] == "https://n/0"          # the announcement, for the card
    assert "sec.gov" in row["source_url"]               # the filing it was read from


def test_a_hyphenated_description_is_trimmed_off_a_name():
    """"Prostate Cancer Treatment-Maker Halda Therapeutics" and "CT-based Halda
    Therapeutics" are one company described two ways, and left in they read as two more
    deals than there were."""
    deal = parse_deal(
        "Johnson & Johnson Acquires Prostate Cancer Treatment-Maker Halda Therapeutics "
        "For $3.1 Billion", ["Johnson & Johnson"])
    assert deal["counterparty"] == "Halda Therapeutics"


def test_a_roundup_names_nobody_s_deal():
    """A roundup pairs three companies wrongly: WHO ended up against J&J because the
    headline named Gilead first."""
    assert parse_deal(
        "Pharma M&A Roundup: Gilead Sciences Expands Collaboration with World Health "
        "Organization, Johnson & Johnson Enters Collaboration with Department of Health",
        ["Johnson & Johnson"]) is None


def test_an_award_partnership_is_not_business_development():
    assert parse_deal(
        "Johnson & Johnson Announces Collaboration with TIME to Introduce New Healthcare "
        "Champion of the Year Award", ["Johnson & Johnson"]) is None


def test_a_property_deal_that_names_a_company_is_not_its_deal():
    assert parse_deal(
        "Rubicon Point Partners Acquires Shockwave Medical Headquarters Campus In "
        "Silicon Valley", ["Johnson & Johnson"]) is None


def test_the_asset_after_the_verb_is_not_the_party():
    """"Axsome Therapeutics Acquires Selective PDE10A Inhibitor" names no counterparty,
    and "AstraZeneca to acquire China rights" names a market."""
    assert parse_deal("Axsome Therapeutics Acquires Selective PDE10A Inhibitor",
                      ["Axsome Therapeutics"]) is None
    assert parse_deal("AstraZeneca to acquire China rights for AbelZeta CAR-T therapy",
                      ["AstraZeneca"]) is None


def test_a_plain_deal_still_reads():
    deal = parse_deal(
        "Johnson & Johnson Announces Collaboration with Sail Biomedicines to Advance "
        "in vivo CAR-T Programs", ["Johnson & Johnson"])
    assert deal["counterparty"] == "Sail Biomedicines"
    assert deal["deal_type"] == "collaboration"


def test_a_holder_is_stepped_over_to_reach_the_party():
    """"argenx SE to acquire BIOG portfolio company, Forte Biosciences, Inc" names the
    trust that owns Forte. BIOG is its ticker, and Forte is the company changing hands."""
    deal = parse_deal(
        "The Biotech Growth Trust PLC - argenx SE to acquire BIOG portfolio company, "
        "Forte Biosciences, Inc - Investegate", ["argenx"])
    assert deal["counterparty"] == "Forte Biosciences"


def test_a_subsidiary_names_the_subsidiary():
    deal = parse_deal("Roche to acquire Genentech subsidiary Alpha Bio for $400 million",
                      ["Roche"])
    assert deal["counterparty"] == "Alpha Bio"


def test_a_plain_name_is_not_mistaken_for_a_holder():
    deal = parse_deal("AbbVie acquires Gilgamesh Pharmaceuticals", ["AbbVie"])
    assert deal["counterparty"] == "Gilgamesh Pharmaceuticals"
