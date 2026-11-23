"""The call log follows the committed record: it appends what the history file holds
beyond the book, changes nothing already there, and refuses where the two have parted."""

import json

import pytest

import call_sync
import db


@pytest.fixture(autouse=True)
def call_log_on(monkeypatch):
    # The suite switches the call log off so no test records a day's calls on a book;
    # these tests are about the log itself.
    monkeypatch.setenv("ER_TOOL_CALL_LOG", "1")


def _call(ident, day, ticker="AAA", fair=10.0):
    return {"id": ident, "as_of": day, "ticker": ticker, "cohort": "biotech",
            "price": 9.0, "price_date": day, "fair_value": fair, "source": "scheduled"}


def _gate(ident, day, catalyst, ticker="AAA"):
    return {"id": ident, "as_of": day, "ticker": ticker, "catalyst_id": catalyst,
            "asset_name": "drug", "per_share_now": 5.0, "per_share_success": 9.0,
            "per_share_failure": 0.0, "a_column_this_book_lacks": "ignored"}


def _write(folder, table, rows):
    folder.mkdir(exist_ok=True)
    (folder / f"{table}.ndjson").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def _book(tmp_path, calls=(), gates=()):
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    for table, rows in (("model_calls", calls), ("gate_calls", gates)):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        for row in rows:
            record = {k: v for k, v in row.items() if k in columns}
            conn.execute(f"INSERT INTO {table} ({', '.join(record)})"
                         f" VALUES ({', '.join('?' for _ in record)})", list(record.values()))
    conn.commit()
    conn.close()
    return path


def _rows(path, table):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        conn.close()


def test_the_days_the_book_is_missing_are_appended_and_nothing_else_moves(tmp_path):
    held = [_call(1, "2026-11-07"), _call(2, "2026-11-08")]
    path = _book(tmp_path, calls=held, gates=[_gate(1, "2026-11-08", 7)])
    before = _rows(path, "model_calls")
    hist = tmp_path / "history"
    _write(hist, "model_calls", held + [_call(3, "2026-11-09"), _call(4, "2026-11-10")])
    _write(hist, "gate_calls", [_gate(1, "2026-11-08", 7), _gate(2, "2026-11-09", 7)])
    out = call_sync.catch_up(path, hist)
    assert out["model_calls"] == {"appended": 2, "from": "2026-11-09", "through": "2026-11-10"}
    assert out["gate_calls"]["appended"] == 1
    after = _rows(path, "model_calls")
    assert after[:2] == before and [r["as_of"] for r in after[2:]] == ["2026-11-09", "2026-11-10"]
    assert "+2 rows" in call_sync.sentence(out)


def test_a_second_run_appends_nothing(tmp_path):
    path = _book(tmp_path, calls=[_call(1, "2026-11-08")])
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08"), _call(2, "2026-11-09")])
    call_sync.catch_up(path, hist)
    again = call_sync.catch_up(path, hist)
    assert again["model_calls"] == {"appended": 0, "through": "2026-11-09"}
    assert len(_rows(path, "model_calls")) == 2
    assert "already current" in call_sync.sentence(again)


def test_a_book_with_calls_the_record_does_not_hold_is_left_alone(tmp_path):
    """A book that recorded its own day is ahead of the file. Appending the file's rows
    around it would interleave two records of the same days."""
    path = _book(tmp_path, calls=[_call(1, "2026-11-08"), _call(2, "2026-11-09")])
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08")])
    out = call_sync.catch_up(path, hist)
    assert "not in model_calls.ndjson" in out["model_calls"]["refused"]
    assert len(_rows(path, "model_calls")) == 2
    assert "not synced" in call_sync.sentence(out)


def test_a_book_whose_last_row_is_a_different_call_is_refused(tmp_path):
    path = _book(tmp_path, calls=[_call(1, "2026-11-08"), _call(2, "2026-11-09", "AAA")])
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08"), _call(2, "2026-11-09", "BBB"),
                                 _call(3, "2026-11-10")])
    out = call_sync.catch_up(path, hist)
    assert "disagree about model_calls row 2" in out["model_calls"]["refused"]
    assert len(_rows(path, "model_calls")) == 2


def test_a_colliding_row_undoes_the_whole_tables_append(tmp_path):
    """The file's row 3 is the day and company the book holds as row 2 under the same
    key as the file's row 2, so the check passes and the insert collides. Half a day's
    calls is worse than none: the two rows before it are not kept either."""
    path = _book(tmp_path, calls=[_call(1, "2026-11-08", "AAA"), _call(2, "2026-11-08", "BBB")])
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08", "AAA"), _call(2, "2026-11-08", "BBB"),
                                 _call(3, "2026-11-09", "AAA"), _call(4, "2026-11-08", "BBB")])
    out = call_sync.catch_up(path, hist)
    assert "collides" in out["model_calls"]["refused"]
    assert len(_rows(path, "model_calls")) == 2


def test_an_empty_book_takes_the_whole_record_and_a_missing_file_is_not_an_error(tmp_path):
    path = _book(tmp_path)
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08"), _call(2, "2026-11-09")])
    out = call_sync.catch_up(path, hist)
    assert out["model_calls"]["appended"] == 2
    assert out["gate_calls"] == {"appended": 0, "reason": "no gate_calls.ndjson to read"}


def test_a_damaged_line_is_skipped_and_the_rest_still_lands(tmp_path):
    path = _book(tmp_path, calls=[_call(1, "2026-11-08")])
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08"), _call(2, "2026-11-09")])
    with (hist / "model_calls.ndjson").open("a") as handle:
        handle.write("{not json\n")
    assert call_sync.catch_up(path, hist)["model_calls"]["appended"] == 1


def test_nothing_is_synced_where_the_call_log_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ER_TOOL_CALL_LOG", "0")
    path = _book(tmp_path)
    hist = tmp_path / "history"
    _write(hist, "model_calls", [_call(1, "2026-11-08")])
    out = call_sync.catch_up(path, hist)
    assert "off" in out and _rows(path, "model_calls") == []
