"""The headline parser, tested on the headlines it will actually see.

Every case here is a real Google News title from the Lilly feed, publisher suffix and
all. A headline parser earns its keep by what it refuses: the commentary cases matter
more than the deal cases, since a false deal is worse than a missed one.
"""

import db
from fetchers.deals_news import DealsNewsFetcher, parse_deal, parse_feed, parse_value

NAMES = {"Eli Lilly and Company", "LLY", "Lilly"}


def test_reads_an_acquisition():
    deal = parse_deal("Eli Lilly acquires Ajax Therapeutics - Reuters", NAMES)
    assert deal["deal_type"] == "acquisition"
    assert deal["counterparty"] == "Ajax Therapeutics"
    assert deal["value"] is None


def test_reads_the_value_and_stops_at_the_company_name():
    deal = parse_deal(
        "Eli Lilly signs a deal with Innovent Biologics worth $8.85 billion - Fierce",
        NAMES)
    assert deal["counterparty"] == "Innovent Biologics"
    assert deal["value"] == "$8.85 billion"


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
        "INSERT INTO deals (accession, company_id, deal_type, counterparty, value)"
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
    stored = conn.execute("SELECT accession, value FROM deals").fetchall()
    conn.close()
    assert len(stored) == 1
    assert stored[0]["accession"] == "0000-24-1"      # the filing's row, untouched
    assert stored[0]["value"] == "$1.0 billion"
