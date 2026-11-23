"""The thesis log: a read is written once, priced from the book, and marked on its day.

What has to hold: a thesis that could never be marked is refused before it is written,
nothing on the ledger is ever changed, and a mark is the stock's return less XBI's over
the same days, counted only once the horizon has traded.
"""

import datetime as dt
import json

import pytest

import db
import thesis_log as TL

CLAIM = "The price pays for a result the Phase 3 has not given yet."
RESTS = "Gate odds: the book says 53 percent, the price implies 94 percent."
WRONG = "The stock beats XBI over the thirty days to the due date."


def _book(tmp_path, stock, bench):
    """A book with one company and its closes, and XBI's: {day: close} each."""
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'Aaa Bio')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'BBB', 'No Prices')")
    for day, close in stock.items():
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                     " VALUES (1, ?, ?, '1d')", (day, close))
    for day, close in bench.items():
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close)"
                     " VALUES ('XBI', ?, ?)", (day, close))
    conn.commit()
    conn.close()
    return path


def _log(path, ledger, today, **over):
    args = dict(ticker="AAA", side="underperform", horizon_days=30, claim=CLAIM,
                rests_on=RESTS, wrong_if=WRONG)
    args.update(over)
    return TL.record(path, today=today, path=ledger, **args)


@pytest.fixture
def book(tmp_path):
    stock = {"2026-10-12": 20.0, "2026-11-11": 18.0, "2026-11-20": 25.0}
    bench = {"2026-10-12": 100.0, "2026-11-11": 105.0, "2026-11-20": 100.0}
    return _book(tmp_path, stock, bench), tmp_path / "ledger" / "theses.ndjson"


def test_a_thesis_is_priced_from_the_book_and_dated_to_its_due_day(book):
    path, ledger = book
    row = _log(path, ledger, dt.date(2026, 10, 12), author="  an   analyst ")
    assert row["id"] == 1 and row["price"] == 20.0 and row["price_date"] == "2026-10-12"
    assert row["benchmark"] == "XBI" and row["benchmark_close"] == 100.0
    assert row["due"] == "2026-11-11" and row["author"] == "an analyst"
    assert json.loads(ledger.read_text().strip()) == row


def test_a_thesis_that_could_never_be_marked_is_refused_and_nothing_is_written(book):
    path, ledger = book
    day = dt.date(2026, 10, 12)
    for over, word in (({"side": "long"}, "outperform"),
                       ({"horizon_days": 2}, "between"),
                       ({"horizon_days": "soon"}, "whole number"),
                       ({"claim": "up"}, "claim"),
                       ({"wrong_if": ""}, "wrong_if"),
                       ({"rests_on": "x" * 2000}, "rests_on"),
                       ({"ticker": "ZZZ"}, "universe"),
                       ({"ticker": "BBB"}, "no closing price"),
                       ({"supersedes": 9}, "no thesis 9")):
        with pytest.raises(TL.Refused) as exc:
            _log(path, ledger, day, **over)
        assert word in str(exc.value)
    assert not ledger.exists()


def test_a_stale_price_is_not_a_starting_point(book):
    path, ledger = book
    with pytest.raises(TL.Refused) as exc:
        _log(path, ledger, dt.date(2026, 12, 20))          # last close is 20 November
    assert "too old" in str(exc.value)


def test_the_ledger_only_grows(book):
    """There is no edit and no delete: a second thought is a new row naming the first."""
    path, ledger = book
    first = _log(path, ledger, dt.date(2026, 10, 12))
    second = _log(path, ledger, dt.date(2026, 10, 12), side="outperform",
                  supersedes=first["id"])
    assert (first["id"], second["id"]) == (1, 2)
    lines = ledger.read_text().strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0]) == first
    assert not [name for name in dir(TL) if name in ("delete", "update", "edit", "remove")]
    marked = TL.score(path, dt.date(2026, 11, 23), ledger)["theses"]
    assert [(r["id"], r["superseded"]) for r in marked] == [(2, False), (1, True)]


def test_a_mark_is_the_return_less_the_benchmarks_and_right_follows_the_side(book):
    """The stock fell 10% while XBI rose 5%: fifteen points behind. The underperform
    thesis was right and the outperform one, logged the same day, was wrong."""
    path, ledger = book
    _log(path, ledger, dt.date(2026, 10, 12))
    _log(path, ledger, dt.date(2026, 10, 12), side="outperform")
    out = TL.score(path, dt.date(2026, 11, 23), ledger)
    under, over = out["theses"][1], out["theses"][0]
    assert under["status"] == "marked" and under["excess"] == -0.15 and under["right"] is True
    assert over["right"] is False and over["marked_on"] == "2026-11-11"
    assert out["summary"] == {"theses": 2, "open": 0, "marked": 2, "right": 1,
                              "hit_rate": 0.5, "mean_excess_on_side": 0.0,
                              "companies": 1, "starting_days": 1}


def test_a_mark_does_not_move_with_what_the_price_did_after_the_due_day(book):
    path, ledger = book
    _log(path, ledger, dt.date(2026, 10, 12))
    early = TL.score(path, dt.date(2026, 11, 12), ledger)["theses"][0]
    late = TL.score(path, dt.date(2026, 11, 23), ledger)["theses"][0]   # after the rally
    assert early["excess"] == late["excess"] == -0.15


def test_an_open_thesis_shows_its_excess_so_far_and_is_not_counted(book):
    path, ledger = book
    _log(path, ledger, dt.date(2026, 10, 12), horizon_days=90)
    out = TL.score(path, dt.date(2026, 11, 23), ledger)
    row = out["theses"][0]
    assert row["status"] == "open" and row["right"] is None
    assert row["excess"] == 0.25                           # 25 from 20, XBI flat
    assert out["summary"]["marked"] == 0 and out["summary"]["hit_rate"] is None


def test_a_due_day_with_no_price_near_it_is_unpriced_not_guessed(tmp_path):
    path = _book(tmp_path, {"2026-10-12": 20.0}, {"2026-10-12": 100.0, "2026-11-11": 105.0})
    ledger = tmp_path / "t.ndjson"
    _log(path, ledger, dt.date(2026, 10, 12))
    row = TL.score(path, dt.date(2026, 11, 23), ledger)["theses"][0]
    assert row["status"] == "unpriced" and row["excess"] is None and row["right"] is None


def test_one_damaged_line_does_not_hide_the_rest_of_the_record(book):
    path, ledger = book
    _log(path, ledger, dt.date(2026, 10, 12))
    with ledger.open("a") as handle:
        handle.write("{not json\n")
    _log(path, ledger, dt.date(2026, 10, 12))
    assert [e["id"] for e in TL.entries(ledger)] == [1, 2]


def test_the_log_narrows_to_one_company(book):
    path, ledger = book
    _log(path, ledger, dt.date(2026, 10, 12))
    assert TL.score(path, dt.date(2026, 11, 23), ledger, ticker="aaa")["summary"]["theses"] == 1
    assert TL.score(path, dt.date(2026, 11, 23), ledger, ticker="BBB")["theses"] == []


def test_the_ledger_sits_beside_the_data_folder_not_inside_it():
    """A line appended under data/ would move the response cache's stamp and have every
    valuation recomputed for a write that changed none of them."""
    assert TL.LEDGER.parent.name == "ledger"
    assert "data" not in TL.LEDGER.relative_to(TL.LEDGER.parent.parent).parts
