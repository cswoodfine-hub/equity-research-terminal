"""What a company announces about itself, read off its own IR feed.

The fixtures are two real feeds. AstraZeneca's is its own shape, carrying link, guid,
title and pubDate and no body at all, which is the constraint the catalyst rule has to
live with. Lilly's is the Q4/Investis shape most of the seeded feeds share.
"""

import datetime as dt
import json
import pathlib

import db
import press_releases as pr
from fetchers.press_ir import PressIrFetcher

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
AZN = (FIXTURES / "ir_feed_azn.xml").read_text()
LLY = (FIXTURES / "ir_feed_lly.xml").read_text()


def _titles(xml):
    return [i["title"] for i in pr.parse_feed(xml)]


def _kind(title):
    return pr.classify(title)[0]


# --- parsing ---------------------------------------------------------------

def test_both_feed_shapes_parse_with_a_link_and_a_date_on_every_item():
    for xml in (AZN, LLY):
        items = pr.parse_feed(xml)
        assert items
        assert all(i["url"] for i in items)
        assert all(i["published"] for i in items)
        # RFC 822 in the feed, ISO in the row, because that is what the tables hold.
        assert all(len(i["published"]) == 10 for i in items)


def test_the_headline_survives_parsing_intact():
    assert any(t.startswith("US FDA decision date extended for SERENA-6")
               for t in _titles(AZN))


# --- classifying -----------------------------------------------------------

def test_an_approval_is_read_as_an_approval():
    assert _kind("US FDA approves Lumoxiti (moxetumomab pasudotox-tdfk) for certain"
                 " patients with hairy cell leukaemia") == "approval"
    assert _kind("Datroway approved in the EU as only TROP2-directed medicine with"
                 " overall survival data") == "approval"


def test_a_european_opinion_is_regulatory_and_not_an_approval():
    """CHMP recommends and the Commission approves. Reading the opinion as the approval
    would date the approval two months early."""
    assert _kind("Enhertu plus pertuzumab recommended for approval in the EU by CHMP"
                 " as 1st-line treatment") == "regulatory"


def test_a_trial_result_is_read_either_way_it_went():
    assert _kind("CARES Phase III clinical programme did not meet primary endpoint in"
                 " overall linagliptin population") == "data readout"
    assert _kind("Baxdrostat met the primary endpoint in Bax24 Phase III trial in"
                 " patients with hypertension") == "data readout"


def test_a_refusal_is_kept_rather_than_dropped():
    """A complete response letter is the news of the year for the asset it lands on."""
    assert _kind("AstraZeneca receives Complete Response Letter from US FDA for ZS-9"
                 " (sodium zirconium cyclosilicate)") == "regulatory"


def test_an_acquisition_is_a_deal_and_a_quarterly_is_results():
    assert _kind("Acquisition of EsoBiotec completed") == "deal"
    assert _kind("H1 and Q2 2026 results") == "results"


def test_the_feeds_own_furniture_is_not_news():
    assert _kind("Press releases") is None
    assert _kind("") is None


# --- forward dating --------------------------------------------------------

def test_an_adcomm_outcome_is_not_a_future_event():
    """Nearly every advisory committee headline reports a vote already taken. Reading
    "Truqap recommended by FDA Advisory Committee" as upcoming would put an event that
    happened in 2026 on the forward calendar."""
    kind, ahead = pr.classify("Truqap recommended by FDA Advisory Committee for"
                              " PTEN-deficient metastatic hormone receptor breast cancer")
    assert kind == "panel"
    assert ahead is False


def test_a_decision_date_still_reads_as_forward():
    kind, ahead = pr.classify("US FDA decision date extended for SERENA-6 filing of"
                              " camizestrant to enable review of additional data")
    assert (kind, ahead) == ("PDUFA", True)


def test_a_quarter_is_not_turned_into_a_date():
    """The one rule that cannot bend. A release saying a decision is expected in the
    first quarter of 2027 does not state a date, and inventing the middle of the quarter
    would put a fabricated number on the calendar."""
    assert pr.stated_date("PDUFA decision expected in the first quarter of 2027") is None


def test_a_date_the_headline_states_in_full_is_read_either_way_round():
    assert pr.stated_date("PDUFA date of 12 March 2027",
                          today=dt.date(2026, 8, 1)) == "2027-03-12"
    assert pr.stated_date("FDA action date of March 12, 2027",
                          today=dt.date(2026, 8, 1)) == "2027-03-12"


def test_a_date_already_past_is_not_a_catalyst():
    assert pr.stated_date("PDUFA date of 12 March 2020", today=dt.date(2026, 8, 1)) is None


# --- the fetcher -----------------------------------------------------------

def _fetcher(tmp_path, monkeypatch, xml=AZN, feed="https://example.test/rss.xml"):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name, ir_rss_url)"
                 " VALUES ('AZN', 'AstraZeneca', ?)", (feed,))
    conn.commit()
    conn.close()
    fetcher = PressIrFetcher("AZN", db_path=path)
    if xml is not None:
        monkeypatch.setattr(
            "fetchers.press_ir.urllib.request.urlopen",
            lambda *a, **k: _Response(xml))
    return fetcher, path


class _Response:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _rows(path, sql, args=()):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def test_the_releases_land_as_news(tmp_path, monkeypatch):
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    result = fetcher.run()
    assert result.errors == []
    news = _rows(path, "SELECT title, url, published_at, source FROM news")
    assert len(news) == len(pr.parse_feed(AZN))
    assert {n["source"] for n in news} == {"press_ir"}
    assert all(n["url"] and n["published_at"] for n in news)


def test_a_second_run_repeats_nothing(tmp_path, monkeypatch):
    """The url is the identity and the insert that takes is what decides. Without that a
    daily run would re-report the same archive every day."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    fetcher.run()
    before = _rows(path, "SELECT COUNT(*) c FROM changes")[0]["c"]
    again = PressIrFetcher("AZN", db_path=path)
    again.force = True
    monkeypatch.setattr("fetchers.press_ir.urllib.request.urlopen",
                        lambda *a, **k: _Response(AZN))
    assert again.run().rows_fetched == 0
    assert _rows(path, "SELECT COUNT(*) c FROM changes")[0]["c"] == before


def test_only_a_recent_release_becomes_a_change(tmp_path, monkeypatch):
    """The first run reads the whole archive, 1,626 items for AstraZeneca. A change per
    item would bury today's news under a decade of it, so the old ones are stored as news
    and do not claim to be new."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    fetcher.run()
    cutoff = (dt.date.today() - dt.timedelta(days=21)).isoformat()
    dated = {n["url"]: n["published_at"]
             for n in _rows(path, "SELECT url, published_at FROM news")}
    for change in _rows(path, "SELECT entity_key FROM changes"):
        assert dated[change["entity_key"].split("|", 1)[1]] >= cutoff


def test_a_change_carries_its_kind_and_its_headline(tmp_path, monkeypatch):
    fetcher, path = _fetcher(tmp_path, monkeypatch, xml=LLY)
    fetcher.run()
    changes = _rows(path, "SELECT entity_type, field, new_value, change_type,"
                          " significance FROM changes")
    assert changes, "Lilly's feed is the last ten releases, so some are recent"
    for change in changes:
        assert change["entity_type"] == "company"
        assert change["field"] == "press release"
        assert change["change_type"].startswith("press_")
        assert change["significance"] in ("high", "medium", "low")
        # The headline verbatim, because a press release is worth the words it used.
        assert change["new_value"] in _titles(LLY)


def test_an_unclassified_release_is_stored_but_not_reported(tmp_path, monkeypatch):
    """Half of what a company publishes is a conference appearance or a share buyback
    notice. It belongs in the record and not in the change feed."""
    fetcher, path = _fetcher(tmp_path, monkeypatch, xml=LLY)
    fetcher.run()
    unclassified = [t for t in _titles(LLY) if _kind(t) is None]
    assert unclassified
    reported = {c["new_value"] for c in _rows(path, "SELECT new_value FROM changes")}
    assert not (set(unclassified) & reported)


def test_a_catalyst_is_written_only_where_a_date_is_stated(tmp_path, monkeypatch):
    """AstraZeneca's feed has no body, so a headline that does not state its date gives
    no catalyst rather than a guessed one."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    fetcher.run()
    for row in _rows(path, "SELECT expected_date, is_curated, source_url, title"
                           " FROM catalysts"):
        assert row["is_curated"] == 0        # auto extracted, review before trusting
        assert pr.stated_date(row["title"], today=dt.date(1900, 1, 1)) == \
            row["expected_date"]


def test_a_company_with_no_feed_reports_nothing_and_fails_nothing(tmp_path, monkeypatch):
    fetcher, path = _fetcher(tmp_path, monkeypatch, xml=None, feed="")
    result = fetcher.run()
    assert result.errors == []
    assert result.rows_fetched == 0
    assert "no IR feed" in " ".join(result.notes)
    assert _rows(path, "SELECT COUNT(*) c FROM news")[0]["c"] == 0


def test_a_feed_that_refuses_is_one_companys_error(tmp_path, monkeypatch):
    """A 403 from one IR site must not fail the run for the other sixty-nine."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)

    def refuse(*a, **k):
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr("fetchers.press_ir.urllib.request.urlopen", refuse)
    result = fetcher.run()
    assert result.rows_fetched == 0
    assert any("403" in e for e in result.errors)


def test_a_diary_entry_is_not_results():
    """"Exelixis to Release Second Quarter 2026 Financial Results on Wednesday, August 5"
    matches the results vocabulary and announces nothing. The results themselves say
    reports or announces, never "to report"."""
    assert _kind("Exelixis to Release Second Quarter 2026 Financial Results on"
                 " Wednesday, August 5, 2026") is None
    assert _kind("Lilly confirms date and conference call for second-quarter 2026"
                 " financial results") is None
    assert _kind("AMGEN ANNOUNCES WEBCAST OF 2026 SECOND QUARTER FINANCIAL RESULTS") \
        is None
    assert _kind("Vertex Reports Second Quarter 2026 Financial Results") == "results"


def test_a_dividend_is_not_results():
    """"AMGEN ANNOUNCES 2026 THIRD QUARTER DIVIDEND" is a quarter and a payout, not the
    quarter's numbers."""
    assert _kind("AMGEN ANNOUNCES 2026 THIRD QUARTER DIVIDEND") == "dividend"


# --- a feed that answers, and says nothing new -----------------------------
# Moderna's seeded feed returns HTTP 200 and 142 items on every run, newest dated
# 2025-05-01: the URL serves an abandoned commentary feed rather than the press wire.
# Counting what parsed and calling it success left the company unwatched for fifteen
# months with nothing anywhere saying so.

def _feed_items(published):
    return [{"published": d, "kind": None, "title": "x", "url": f"u{i}"}
            for i, d in enumerate(published)]


def test_a_feed_frozen_a_year_ago_is_reported_as_stale():
    import datetime as dt
    from fetchers.press_ir import PressIrFetcher

    fetcher = PressIrFetcher("MRNA")
    old = (dt.date.today() - dt.timedelta(days=476)).isoformat()
    behind = fetcher.stale_by_days(_feed_items([old, "2024-01-01"]))
    assert behind is not None and 470 <= behind <= 480
    assert fetcher.newest_published(_feed_items([old, "2024-01-01"])) == old


def test_a_current_feed_is_not_reported():
    import datetime as dt
    from fetchers.press_ir import PressIrFetcher

    recent = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    assert PressIrFetcher("VRTX").stale_by_days(_feed_items([recent])) is None


def test_an_undated_feed_makes_no_claim_either_way():
    from fetchers.press_ir import PressIrFetcher
    assert PressIrFetcher("ABEO").stale_by_days(_feed_items([None, None])) is None
    assert PressIrFetcher("ABEO").stale_by_days([]) is None


def test_the_snapshot_records_the_newest_item_it_saw(tmp_path):
    import db
    from fetchers.press_ir import PressIrFetcher

    path = str(tmp_path / "n.db")
    db.init(path)
    fetcher = PressIrFetcher("MRNA", path)
    fetcher.snapshot(_feed_items(["2025-05-01", "2024-02-02"]))

    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()["payload"])
    conn.close()
    # The date is on the snapshot, so the history itself shows when a feed went quiet.
    assert payload["newest_published"] == "2025-05-01"
    assert payload["fetch_kind"] == "live"
