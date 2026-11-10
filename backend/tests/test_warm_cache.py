"""Saving the slow reads for a container that starts cold: one warming pass, in the order
the reads' embeddings need, and the deployed app picking each release asset by its name.
No network: the fetches and the release listing are stubbed."""

import ast
import io
import json
import pathlib

import response_cache as R

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_one_pass_reads_globals_then_companies_then_what_embeds_them(monkeypatch):
    fetched = []

    def fetch(url):
        if url.endswith("/companies/BBB/street"):
            raise OSError("down")
        fetched.append(url)

    monkeypatch.setattr(R, "_fetch", fetch)
    monkeypatch.setattr(R, "_tickers", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(R, "_area_reads", lambda: ["/areas/oncology"])
    monkeypatch.setattr(R, "_universe_reads",
                        lambda base, first: [base + "/universe/command?ticker=BBB&part=all"])
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    done = R.warm_once("http://api")
    paths = [u[len("http://api"):] for u in fetched]
    assert paths[:len(R.GLOBAL_READS)] == list(R.GLOBAL_READS)
    # Every company's reads before the reads that embed them.
    last_company = max(i for i, p in enumerate(paths) if p.startswith("/companies/BBB/"))
    assert paths.index("/comps/valuation") > last_company
    assert paths[-2:] == ["/areas/oncology", "/universe/command?ticker=BBB&part=all"]
    total = len(R.GLOBAL_READS) + 2 * len(R.COMPANY_READS) + len(R.LATE_GLOBAL_READS) + 2
    assert done == {"reads": total - 1, "failed": 1}


def _resolver():
    """The cloud app's asset lookup, lifted out of the module, which starts the app on
    import."""
    source = (ROOT / "streamlit_cloud_app.py").read_text()
    tree = ast.parse(source)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "_resolve_release_asset")
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") in ("DB_ASSET", "RESPONSES_ASSET")
                        for t in n.targets))]
    release = {"assets": [
        {"name": "responses.db.gz", "url": "https://api.github.com/assets/2"},
        {"name": "er_tool.db.gz", "url": "https://api.github.com/assets/1"}]}

    class Stub:
        class request:
            Request = staticmethod(lambda url, headers=None: url)

            @staticmethod
            def urlopen(request, timeout=None):
                return io.BytesIO(json.dumps(release).encode())

    space = {"json": json, "urllib": Stub}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "streamlit_cloud_app.py", "exec"),
         space)
    return space


def test_the_app_takes_the_database_by_name_not_the_first_gz():
    space = _resolver()
    find = space["_resolve_release_asset"]
    # The responses are listed first, and taking the first .gz would load them as the book.
    assert find("o/r", "data-latest", "") == "https://api.github.com/assets/1"
    assert (find("o/r", "data-latest", "", space["RESPONSES_ASSET"])
            == "https://api.github.com/assets/2")
    try:
        find("o/r", "data-latest", "", "missing.gz")
    except RuntimeError as exc:
        assert "publishes no missing.gz" in str(exc)
    else:
        raise AssertionError("a missing asset must be reported")


def _saved_file(folder, monkeypatch, book, commit, day):
    """A database and a saved file beside it, recording the given book, commit and day,
    with the process reset so the next read loads the file afresh."""
    import datetime as dt
    import zlib
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / "book.db"
    database.write_bytes(b"SQLite format 3\x00" + b"book" * 100)
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE", "1")
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE_DISK", "1")
    monkeypatch.setattr(R.db, "DB_PATH", database)
    monkeypatch.setattr(R, "DISK_DIR", folder / "cache")
    monkeypatch.setattr(R, "code_commit", lambda: "abc123")
    monkeypatch.setattr(R, "_disk_state", {"loaded": False, "writer": False})
    monkeypatch.setattr(R, "_entries", R.OrderedDict())
    conn = R._disk_connect()
    with conn:
        conn.execute("INSERT INTO responses VALUES (?, ?, ?, ?)",
                     ("/companies/AZN/fair-value?", zlib.compress(b'{"v": 1}'),
                      "application/json", 0.0))
        conn.execute(f"CREATE TABLE {R.SAVED_FOR} (book_sha TEXT, code_commit TEXT,"
                     " day TEXT)")
        conn.execute(f"INSERT INTO {R.SAVED_FOR} VALUES (?, ?, ?)",
                     (R.book_sha(str(database)) if book == "same" else "other", commit,
                      dt.date.today().isoformat() if day == "today" else "2000-01-01"))
    conn.close()


def test_a_saved_file_is_current_only_for_its_own_book_code_and_day(tmp_path, monkeypatch):
    _saved_file(tmp_path / "match", monkeypatch, "same", "abc123", "today")
    R.load_from_disk()
    assert R._entries["/companies/AZN/fair-value?"]["stamp"] == R.stamp()
    for book, commit, day in (("other", "abc123", "today"), ("same", "zzz", "today"),
                              ("same", "abc123", "past")):
        _saved_file(tmp_path / f"{book}-{commit}-{day}", monkeypatch, book, commit, day)
        R.load_from_disk()
        # Loaded all the same, but stale: a company read recomputes before it is served.
        assert R._entries["/companies/AZN/fair-value?"]["stamp"] is None


def test_an_empty_write_ahead_log_does_not_move_the_stamp(tmp_path, monkeypatch):
    database = tmp_path / "book.db"
    database.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(R.db, "DB_PATH", database)
    before = R.stamp()
    # SQLite creates the log empty when a process first opens the database.
    (tmp_path / "book.db-wal").write_bytes(b"")
    assert R.stamp() == before
    # A write puts pages in it, and that moves the stamp.
    (tmp_path / "book.db-wal").write_bytes(b"page")
    assert R.stamp() != before
