"""The Trading tab's saved boards: kept on this machine, beside the book and not in it.

The file is moved to a temporary folder for every test, so nothing here reads or writes
the reader's own boards.
"""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import db
import desk_layout as DL
import response_cache

BOARD = {"panels": [
    {"panel": "price", "ticker": None, "id": "p1", "x": 0, "y": 0, "w": 12, "h": 13},
    {"panel": "news", "ticker": "NVO", "id": "p2", "x": 0, "y": 13, "w": 6, "h": 9}]}


@pytest.fixture(autouse=True)
def boards_file(tmp_path, monkeypatch):
    file = tmp_path / "boards" / "trading_layouts.json"
    monkeypatch.setenv("ER_TOOL_LAYOUTS", str(file))
    return file


def test_with_no_file_there_are_no_boards_and_that_is_not_a_problem(boards_file):
    assert DL.load() == {"boards": {}, "current": None, "problem": None}
    assert not boards_file.exists()                        # reading creates nothing


def test_a_board_saved_is_the_board_read_back_and_the_one_that_opens_next(boards_file):
    out = DL.save("Readout prep", BOARD)
    assert out["ok"] and out["current"] == "Readout prep"
    assert DL.load()["boards"] == {"Readout prep": BOARD}
    DL.save("Earnings day", dict(BOARD, panels=BOARD["panels"][:1]))
    held = DL.load()
    assert list(held["boards"]) == ["Earnings day", "Readout prep"]
    assert held["current"] == "Earnings day"
    assert len(held["boards"]["Earnings day"]["panels"]) == 1
    on_disk = json.loads(boards_file.read_text())
    assert on_disk["version"] == 1 and set(on_disk["boards"]) == {"Readout prep", "Earnings day"}


def test_saving_under_a_name_again_replaces_that_board_and_no_other():
    DL.save("A", BOARD)
    DL.save("B", BOARD)
    DL.save("A", dict(BOARD, panels=[]))
    held = DL.load()["boards"]
    assert held["A"]["panels"] == [] and held["B"] == BOARD


@pytest.mark.parametrize("name", ["", "   ", "../escape", "a/b", "x" * 41, "<script>", None,
                                  ".hidden", "tab\there?", "semi;colon"])
def test_a_name_that_is_not_a_name_is_refused_and_nothing_is_written(name, boards_file):
    out = DL.save(name, BOARD)
    assert out["ok"] is False and "name" in out["reason"]
    assert not boards_file.exists()


def test_a_name_is_kept_on_one_line_with_its_spaces_made_single():
    assert DL.save("  Readout    prep  ", BOARD)["current"] == "Readout prep"
    assert DL.save("name\nwith a break", BOARD)["current"] == "name with a break"


@pytest.mark.parametrize("layout", [None, [], "a board", {"columns": 2}, {"panels": "many"}])
def test_what_is_not_a_board_is_refused(layout, boards_file):
    out = DL.save("A", layout)
    assert out["ok"] is False and "not a board" in out["reason"]
    assert not boards_file.exists()


def test_a_board_is_kept_as_its_shape_and_nothing_else_rides_along():
    out = DL.save("A", {"columns": 9, "ask": "yes", "extra": {"x": 1}, "panels": [
        {"panel": "news", "ticker": "nvo", "wide": "wide", "script": "<b>", "id": "p<1>",
         "x": 2.5, "y": -1, "w": True, "h": "9"},
        {"panel": "Not A Kind"}, {"panel": 7}, "nonsense", {"ticker": "LLY"},
        {"panel": "price", "ticker": "NOVO-B.CO", "id": "p4", "x": 0, "y": 3, "w": 12,
         "h": 13}]})
    assert out["boards"]["A"] == {"panels": [
        {"panel": "news", "ticker": None},
        {"panel": "price", "ticker": "NOVO-B.CO", "id": "p4", "x": 0, "y": 3, "w": 12,
         "h": 13}]}


def test_a_board_saved_before_the_grid_keeps_what_says_how_it_was_drawn():
    out = DL.save("Old", {"columns": 3, "panels": [{"panel": "price", "wide": True},
                                                   {"panel": "news"}]})
    assert out["boards"]["Old"] == {"columns": 3, "panels": [
        {"panel": "price", "ticker": None, "wide": True}, {"panel": "news", "ticker": None}]}


def test_a_board_and_the_file_are_both_held_to_a_size():
    many = {"panels": [{"panel": "news"}] * (DL.MAX_PANELS + 10)}
    assert len(DL.save("Big", many)["boards"]["Big"]["panels"]) == DL.MAX_PANELS
    for n in range(DL.MAX_BOARDS - 1):
        assert DL.save(f"Board {n}", BOARD)["ok"]
    out = DL.save("One too many", BOARD)
    assert out["ok"] is False and str(DL.MAX_BOARDS) in out["reason"]
    assert DL.save("Board 0", BOARD)["ok"]                 # replacing one is still allowed


def test_a_board_is_forgotten_and_forgetting_one_that_is_not_there_is_no_error():
    DL.save("A", BOARD)
    DL.save("B", BOARD)
    out = DL.remove("B")
    assert out["ok"] and list(out["boards"]) == ["A"] and out["current"] is None
    assert DL.remove("never saved")["ok"] and DL.remove("../x")["ok"]
    assert list(DL.load()["boards"]) == ["A"]


def test_a_file_that_cannot_be_read_is_no_boards_with_the_reason_and_is_left_alone(boards_file):
    boards_file.parent.mkdir(parents=True)
    boards_file.write_text("{ this is not json")
    before = boards_file.read_text()
    held = DL.load()
    assert held["boards"] == {} and "could not be read" in held["problem"]
    out = DL.save("A", BOARD)
    assert out["ok"] is False and "could not be read" in out["reason"]
    assert boards_file.read_text() == before               # not overwritten on a guess


def test_a_write_goes_by_a_second_file_and_leaves_none_behind(boards_file):
    DL.save("A", BOARD)
    assert [f.name for f in boards_file.parent.iterdir()] == ["trading_layouts.json"]


def test_the_boards_are_kept_outside_the_book_and_outside_data(monkeypatch):
    """A file under data/ or a write to the database moves the stamp every held read is
    kept against, and every valuation would be worked out again."""
    monkeypatch.delenv("ER_TOOL_LAYOUTS", raising=False)
    where = DL.path().resolve()
    assert where.parent == (db.BACKEND_DIR / "cache").resolve()
    assert (db.BACKEND_DIR.parent / "data").resolve() not in where.parents
    assert where.suffix == ".json"
    ignored = (db.BACKEND_DIR.parent / ".gitignore").read_text()
    assert "backend/cache/" in ignored


def test_saving_a_board_is_never_held_and_clears_nothing_that_is():
    assert not response_cache.cacheable("/desk/layouts", "")
    assert any("/desk/layouts".startswith(prefix) for prefix in response_cache.QUIET_WRITES)
    assert any("/desk/layouts/Readout prep".startswith(p) for p in response_cache.QUIET_WRITES)


# ------------------------------------------------------------------------- the routes
@pytest.fixture
def client(tmp_path, monkeypatch):
    import main
    import seed
    book = tmp_path / "book.db"
    db.init(book)
    seed.load_companies(book)
    monkeypatch.setattr(db, "DB_PATH", book)
    return TestClient(main.app), book


def _sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def test_the_routes_save_read_and_delete_a_board(client):
    api, _book = client
    assert api.get("/desk/layouts").json() == {"boards": {}, "current": None, "problem": None}
    saved = api.put("/desk/layouts", json={"name": "Readout prep", "layout": BOARD})
    assert saved.status_code == 200 and saved.json()["current"] == "Readout prep"
    assert api.get("/desk/layouts").json()["boards"] == {"Readout prep": BOARD}
    gone = api.delete("/desk/layouts/Readout prep")
    assert gone.status_code == 200 and gone.json()["boards"] == {}


def test_a_bad_name_or_a_bad_board_is_refused_with_the_reason(client):
    api, _book = client
    bad = api.put("/desk/layouts", json={"name": "../x", "layout": BOARD})
    assert bad.status_code == 422 and "name" in bad.json()["detail"]
    assert api.put("/desk/layouts", json={"name": "A", "layout": {}}).status_code == 422
    assert api.put("/desk/layouts", json={"name": "A"}).status_code == 422


def test_saving_and_deleting_a_board_leave_the_book_untouched(client):
    api, book = client
    before = (_sha(book), book.stat().st_mtime_ns)
    for n in range(4):
        assert api.put("/desk/layouts", json={"name": f"B{n}", "layout": BOARD}).status_code == 200
    api.get("/desk/layouts")
    api.delete("/desk/layouts/B0")
    assert (_sha(book), book.stat().st_mtime_ns) == before
    wal = book.with_name(book.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
