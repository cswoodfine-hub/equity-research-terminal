"""The watch: a look at press feeds and filing lists between refreshes.

What has to hold: a quiet hour writes nothing, something new is written and then read,
a source that fails costs only itself, and the pass stands aside for a refresh.
"""

import datetime as dt

import pytest

import db
import watch

TODAY = dt.date(2026, 11, 23)


class Feed:
    """A stand-in fetcher: answers from a list and records what it was asked to write."""

    written = []

    def __init__(self, rows, kind, ticker, db_path, fail=None):
        self.rows, self.kind, self.ticker, self.db_path, self.fail = rows, kind, ticker, db_path, fail

    def fetch(self):
        if self.fail:
            raise self.fail
        return self.rows

    def normalise(self, raw):
        return list(raw)

    def snapshot(self, rows):
        Feed.written.append(("snapshot", self.ticker, self.kind, len(rows)))

    def upsert(self, rows):
        conn = db.get_connection(self.db_path)
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (self.ticker,)).fetchone()[0]
        for r in rows:
            if self.kind == "press":
                conn.execute("INSERT OR IGNORE INTO news (company_id, source, title, url, published_at)"
                             " VALUES (?, 'press_ir', ?, ?, ?)", (company, r["title"], r["url"], r["published"]))
            else:
                conn.execute("INSERT OR IGNORE INTO filings (company_id, form_type, filed_date, accession,"
                             " title, url) VALUES (?, '8-K', ?, ?, 'Other events', 'u')",
                             (company, r["filed_date"], r["accession"]))
        conn.commit()
        conn.close()
        Feed.written.append(("upsert", self.ticker, self.kind, len(rows)))


@pytest.fixture
def book(tmp_path):
    Feed.written = []
    path = str(tmp_path / "w.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, cik, is_sec_filer, ir_rss_url)"
                 " VALUES (1, 'AAA', 'Aaa', '0000000001', 1, 'https://example.test/rss')")
    conn.execute("INSERT INTO companies (id, ticker, name, cik, is_sec_filer, ir_rss_url)"
                 " VALUES (2, 'BBB', 'Bbb', NULL, 0, NULL)")
    conn.execute("INSERT INTO news (company_id, source, title, url, published_at)"
                 " VALUES (1, 'press_ir', 'Old release', 'https://example.test/old', '2026-11-01')")
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                 " VALUES (1, '8-K', '2026-11-01', '0001-26-000001', 'Other events', 'u')")
    conn.commit()
    conn.close()
    return path


def _maker(answers, fail=None):
    def make(factory, ticker, db_path):
        kind = "press" if factory.__name__ == "PressIrFetcher" else "filings"
        return Feed(answers.get((ticker, kind), []), kind, ticker, db_path,
                    fail=(fail or {}).get((ticker, kind)))
    return make


OLD_PRESS = {"company_id": 1, "title": "Old release", "url": "https://example.test/old",
             "published": "2026-11-01"}
OLD_FILING = {"accession": "0001-26-000001", "filed_date": "2026-11-01"}


def test_only_a_company_with_a_feed_or_a_filing_list_is_asked(book):
    conn = db.get_connection(book)
    got = [(t, k) for t, k, _f in watch.sources(conn)]
    conn.close()
    assert got == [("AAA", "press"), ("AAA", "filings")]


def test_a_quiet_hour_writes_nothing_and_reads_nothing(book, monkeypatch):
    """Most hours. The feed and the filing list answer with what the book already holds,
    so nothing is snapshotted, nothing upserted, and the readers are not run."""
    monkeypatch.setattr(watch, "read", lambda *a, **k: pytest.fail("the readers ran"))
    answers = {("AAA", "press"): [OLD_PRESS], ("AAA", "filings"): [OLD_FILING]}
    out = watch.run(book, today=TODAY, make=_maker(answers), pause=0,
                    refresh_in_flight=lambda: False)
    assert out["look"]["asked"] == 2 and out["look"]["new"] == {"press": 0, "filings": 0}
    assert Feed.written == [] and "read" not in out
    assert "nothing new" in watch.sentence(out)


def test_something_new_is_written_and_then_read(book, monkeypatch):
    seen = {}
    monkeypatch.setattr(watch, "read", lambda db_path, today=None: seen.setdefault(
        "read", {"errors": []}))
    new = {"company_id": 1, "title": "AAA drug meets its primary endpoint",
           "url": "https://example.test/new", "published": "2026-11-23"}
    answers = {("AAA", "press"): [OLD_PRESS, new], ("AAA", "filings"): [OLD_FILING]}
    out = watch.run(book, today=TODAY, make=_maker(answers), pause=0,
                    refresh_in_flight=lambda: False)
    assert out["look"]["new"] == {"press": 1, "filings": 0}
    assert out["look"]["by_company"] == {"AAA": {"press": 1}}
    # The whole answer goes to the fetcher's own write path; the filing list is untouched.
    assert Feed.written == [("snapshot", "AAA", "press", 2), ("upsert", "AAA", "press", 2)]
    assert "read" in seen and "1 new releases and 0 new filings" in watch.sentence(out)
    # And the next look finds it on file.
    Feed.written = []
    again = watch.look(book, make=_maker(answers), pause=0)
    assert again["new"] == {"press": 0, "filings": 0} and Feed.written == []


def test_a_release_listed_at_a_second_address_is_not_new(book, monkeypatch):
    """AstraZeneca's feed lists a release and its social card as two items. The write
    path keeps one, so asked by address alone the other looked new on every pass, and
    every pass wrote a snapshot and ran every reader over a feed that had not moved."""
    monkeypatch.setattr(watch, "read", lambda *a, **k: pytest.fail("the readers ran"))
    card = {"company_id": 1, "title": "Old release", "url": "https://example.test/old-social",
            "published": "2026-11-02"}
    answers = {("AAA", "press"): [OLD_PRESS, card], ("AAA", "filings"): [OLD_FILING]}
    out = watch.run(book, today=TODAY, make=_maker(answers), pause=0,
                    refresh_in_flight=lambda: False)
    assert out["look"]["new"] == {"press": 0, "filings": 0} and Feed.written == []


def test_the_pass_reports_what_it_closed_and_nothing_the_morning_did(book, monkeypatch):
    """A resolution is dated by the day, and the refresh that ran this morning shares
    the day. Reported by date, a pass that closed one gate claimed all of the morning's."""
    conn = db.get_connection(book)
    for cid, title in ((1, "Morning readout"), (2, "Afternoon readout")):
        conn.execute("INSERT INTO catalysts (id, company_id, catalyst_type, expected_date,"
                     " date_confidence, title, status) VALUES (?, 1, 'data readout',"
                     " '2026-11-20', 'confirmed', ?, 'pending')", (cid, title))
    conn.execute("INSERT INTO catalyst_resolutions (catalyst_id, outcome, event_date, source,"
                 " resolved_at) VALUES (1, 'met', '2026-11-20', 'hand', '2026-11-23')")
    conn.commit()
    conn.close()

    def reading(db_path, today=None):
        c = db.get_connection(db_path)
        c.execute("INSERT INTO catalyst_resolutions (catalyst_id, outcome, event_date, source,"
                  " resolved_at) VALUES (2, 'missed', '2026-11-23', 'posted:press', '2026-11-23')")
        c.commit()
        c.close()
        return {"errors": []}
    monkeypatch.setattr(watch, "read", reading)
    new = {"accession": "0001-26-000003", "filed_date": "2026-11-23"}
    out = watch.run(book, today=TODAY, pause=0, refresh_in_flight=lambda: False,
                    make=_maker({("AAA", "press"): [OLD_PRESS], ("AAA", "filings"): [OLD_FILING, new]}))
    assert [(c["title"], c["outcome"]) for c in out["closed"]] == [("Afternoon readout", "missed")]
    assert watch.sentence(out).endswith("closed AAA data readout missed")


def test_a_source_that_fails_costs_only_itself(book, monkeypatch):
    monkeypatch.setattr(watch, "read", lambda db_path, today=None: {"errors": []})
    new = {"accession": "0001-26-000002", "filed_date": "2026-11-23"}
    answers = {("AAA", "filings"): [OLD_FILING, new]}
    out = watch.run(book, today=TODAY, pause=0, refresh_in_flight=lambda: False,
                    make=_maker(answers, fail={("AAA", "press"): OSError("feed refused")}))
    assert out["look"]["new"] == {"press": 0, "filings": 1}
    assert out["look"]["errors"] == ["AAA press: OSError: feed refused"]
    assert "1 steps did not answer" in watch.sentence(out)


def test_the_watch_stands_aside_for_a_refresh(book):
    out = watch.run(book, today=TODAY, pause=0, refresh_in_flight=lambda: True,
                    make=lambda *a: pytest.fail("a source was asked during a refresh"))
    assert "a refresh is running" in out["skipped"] and "look" not in out
    assert watch.sentence(out).startswith("watch stood aside")


def test_a_reader_that_fails_costs_only_its_own_step(book, monkeypatch):
    import catalyst_outcomes
    import landed_readouts
    import pdufa
    import press_readouts
    import submissions
    import trial_readouts
    calls = []

    def ok(name, value=None):
        def step(*a, **k):
            calls.append(name)
            return value if value is not None else {"found": 0}
        return step

    def broken(*a, **k):
        raise RuntimeError("no model key")
    monkeypatch.setattr(trial_readouts, "extract", broken)
    monkeypatch.setattr(press_readouts, "extract", ok("press"))
    monkeypatch.setattr(landed_readouts, "run", ok("landed", {"landed": 1, "note": "x"}))
    monkeypatch.setattr(catalyst_outcomes, "resolve", ok("resolve", {"met": 1, "open": 3}))
    monkeypatch.setattr(pdufa, "extract", ok("pdufa"))
    monkeypatch.setattr(submissions, "derive", ok("submissions"))
    out = watch.read(book, today=TODAY)
    assert out["errors"] == ["trial_readouts: RuntimeError: no model key"]
    # The resolver runs again once the decision dates are read: an acceptance closes a
    # filing gate and is on file only after pdufa has read the filing.
    assert calls == ["press", "landed", "resolve", "pdufa", "resolve", "submissions"]
    assert out["landed_readouts"] == {"landed": 1} and out["catalyst_outcomes"] == {"met": 1, "open": 3}


def test_the_timer_is_off_at_nought_and_under_the_suite(monkeypatch):
    assert watch.minutes() == 0 and watch.start() is False        # conftest switches it off
    monkeypatch.setenv("ER_TOOL_WATCH_MINUTES", "30")
    assert watch.minutes() == 30
    monkeypatch.setenv("ER_TOOL_WATCH_MINUTES", "soon")
    assert watch.minutes() == watch.DEFAULT_MINUTES
    assert watch.status()["last"] is None or isinstance(watch.status()["last"], dict)
