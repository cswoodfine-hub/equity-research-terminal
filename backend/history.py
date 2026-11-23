"""Export and rebuild the app-produced history as newline-delimited JSON.

The differentiator is the accumulated snapshot history, which no source can hand
back once a day is missed. A binary SQLite file diffs badly and bloats a repo, so
the durable off-machine copy is NDJSON: one file per table, one JSON object per
line, ordered by id so a day's new rows append at the end and git stores the delta
cleanly. This is the git-scraping pattern, and it doubles as the backup.

Only the tables the app produces over time are exported. Prices, financials and
current trial state are re-fetchable and left out; the snapshot history that feeds
the diff engine, the detected changes, the catalysts, the notes, the run ledger,
the annotations, the FX rates and the model's own dated calls are not, so those travel.

Rebuild is the inverse: recreate the schema, then load every row back with foreign
keys off, since the export is already internally consistent and the referenced
current-state tables are repopulated by the next refresh.

A number is not a row. Every table here takes the next number for a new row, and two
books that start from the same release and each run a refresh hand out the same numbers
to different rows. On 2026-11-23 the book on the analyst's machine and the committed
record had done exactly that since run 127: run 131 was 23 November in one and 11
November in the other, and 1,774 snapshots, 378 changes and 36 catalysts shared a number
and nothing else. A merge by number would have put one book's rows in place of the
other's and reported success. So a merge first asks whether each shared number is the
same row (``SAME_ROW``), and where the book turns out to be another book, nothing is
written in either direction: ``rebuild`` loads nothing, ``export`` writes nothing, and
``restore_check`` turns the restored file away. Which book is right is for a person to
say.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import db

# Foreign keys point from these toward companies/assets, which are not exported (a
# refresh rebuilds them), so load order does not matter with FK off. Kept as a list
# for a stable, readable export directory.
HISTORY_TABLES = [
    "refresh_runs", "snapshots", "changes", "catalysts", "insights",
    "annotations", "fx_rates",
    # The model's calls as made each day (call_log.py): exported so each day's commit is
    # the dated record they are scored against.
    "model_calls", "gate_calls",
    # What the book said each company was worth, on the day it said it
    # (valuation_history.py). The same reason as the call log and a sharper one: a
    # valuation call is scored against a forward return twelve months out, so the record
    # has to survive twelve months of runs. It lived only inside the published database
    # release, which no source can hand back if that asset is ever lost or a restore
    # falls through to the rebuild path, and the twelve-month clock would start again
    # from nothing.
    "valuation_snapshots",
    # What became of each catalyst (catalyst_outcomes.py). The same reason again: a
    # resolution is dated by an approval or an announcement and no source hands the
    # calendar's own record back, so it travels with the snapshots rather than living
    # only in the published database.
    "catalyst_resolutions",
    # The recorded prices that were not the close of their day, and the close
    # (price_record.py). Found the day after, from the daily series, by the one run that
    # writes the record, so it travels with the snapshots and calls it stands beside.
    "price_corrections",
    # Every change to an analyst assumption (assumption_log.py). The assumptions table
    # itself reseeds from data/assumptions/*.csv, so the seeds and this ledger together
    # carry the model through a rebuild; the ledger alone carries what the seeds cannot,
    # which is every number edited in the terminal after it was first written.
    "assumption_edits",
    # What the model read out of the filings: whether a Phase 3 met its endpoint
    # (trial_readouts.py), the PDUFA dates in acceptance filings (pdufa.py), and the
    # ledger and rows of management guidance (guidance.py).
    #
    # These are reads, not fetches. No source hands them back: the filing can be fetched
    # again but the reading costs a model call, and a reading already paid for is the
    # kind of thing history is for. They lived only inside the published database, and
    # on 2026-11-09 a restore from that release arrived with every one of them empty,
    # which took 1,359 readouts and 1,728 PDUFA reads out of the book in one step.
    #
    # Append-only and keyed on the filing accession, so a day's diff is the day's new
    # filings: 1,359 rows is 524KB against the 50MB of snapshots already carried.
    #
    # consensus_estimates travels with guidance_scans and not apart from it. The scans
    # table is the ledger that says a section has been read; carried alone it would tell
    # a rebuilt database to skip sections whose rows had gone, and the guidance would
    # never come back.
    "trial_readouts", "pdufa_reads", "guidance_scans", "consensus_estimates",
]

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "history"


def _columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone() is not None

# What makes a row the row it is, apart from its number: the columns written once and
# never changed, and whether the table itself keeps them unique. Two rows with one
# number and different values here are two rows, whatever else they share. A column
# that is edited after the fact (a catalyst's title, a readout's reread_at, a run's
# status) is left out on purpose, so the same row carried forward still merges.
#
# A table keyed by something other than a number (pdufa_reads and guidance_scans, on
# the filing accession) needs no entry: its key is already what the row is. Every other
# exported table needs one, and test_history.py fails for a table added without it.
SAME_ROW = {
    "refresh_runs": (("started_at",), False),
    "snapshots": (("source", "entity_type", "entity_key", "captured_at"), False),
    "changes": (("entity_type", "entity_key", "field", "detected_at"), False),
    "catalysts": (("created_at",), False),
    "insights": (("company_id", "generated_at"), False),
    "annotations": (("created_at", "ticker"), False),
    "assumption_edits": (("changed_at", "batch_id", "key", "year", "op"), False),
    "fx_rates": (("base", "quote", "as_of"), True),
    "model_calls": (("as_of", "ticker"), True),
    "gate_calls": (("as_of", "ticker", "catalyst_id"), True),
    "valuation_snapshots": (("company_id", "as_of"), True),
    "catalyst_resolutions": (("catalyst_id", "outcome", "dedupe"), True),
    "trial_readouts": (("accession",), True),
    "consensus_estimates": (("company_id", "metric", "period", "as_of"), True),
}

# The tables nothing is ever deleted from. SQLite gives a new row one more than the
# highest number in the table, so a table that loses its newest row hands the same
# number out again: a catalyst removed and another made in the same run share a number
# inside one book, honestly. In these tables that cannot happen, so a number holding
# two different rows here is proof of two books. Everywhere else it is proof only when
# the book is not a continuation of the files (``_Compared``).
NEVER_DELETED = frozenset({"refresh_runs", "snapshots", "fx_rates", "model_calls",
                           "gate_calls", "valuation_snapshots"})


class Parted(Exception):
    """The book and the history files hold different rows under the same numbers.
    ``found`` is ``parted``'s answer, a table at a time."""

    def __init__(self, doing: str, found: dict):
        self.found = found
        super().__init__(f"{doing}: {sentence(found)}")


def sentence(found: dict) -> str:
    """``parted``'s answer in a line, for a log or a refusal."""
    parts = []
    for table, got in found.items():
        bits = []
        if got.get("different"):
            bits.append(f"{got['different']:,} from number {got['first']} are different rows")
        if got.get("renumbered"):
            bits.append(f"{got['renumbered']:,} are the same rows under other numbers")
        if got.get("missing"):
            bits.append(f"{got['missing']:,} the files hold are not in the book")
        parts.append(f"{table}: " + ", ".join(bits))
    return ("the book and the history files have parted (" + "; ".join(parts)
            + "). Nothing was written.")


def _parted_table(conn, table: str, source: Path) -> tuple:
    """One table's disagreement between the book and its file: what to report, or None
    where every number the two share is the same row, and the numbers in the file that
    cannot be loaded without displacing a different row of the book's."""
    columns = _columns(conn, table)
    if "id" not in columns or table not in SAME_ROW:
        return None, set()
    named, unique = SAME_ROW[table]
    cols = [c for c in named if c in columns]
    held = {r["id"]: tuple(r[c] for c in cols) for r in conn.execute(
        f"SELECT {', '.join(['id'] + cols)} FROM {table}")}
    number_of = {key: ident for ident, key in held.items()} if unique else {}
    different = renumbered = 0
    first = example = None
    clash = set()
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ident = row.get("id")
            # Only the columns the line carries: a file written before a column existed
            # says nothing about it, and silence is not a disagreement.
            there = [i for i, c in enumerate(cols) if c in row]
            theirs = tuple(row[cols[i]] for i in there)
            if ident in held:
                mine = tuple(held[ident][i] for i in there)
                if mine != theirs:
                    different += 1
                    clash.add(ident)
                    if first is None or ident < first:
                        first = ident
                        example = {"id": ident,
                                   "book": dict(zip((cols[i] for i in there), mine)),
                                   "file": dict(zip((cols[i] for i in there), theirs))}
            elif (unique and len(there) == len(cols) and None not in theirs
                  and theirs in number_of):
                # The same row under another number. INSERT OR REPLACE would delete the
                # book's copy to make room, which is a row replaced all the same.
                renumbered += 1
                clash.add(ident)
    if not clash:
        return None, clash
    out = {"different": different, "renumbered": renumbered}
    if different:
        out.update(first=first, example=example)
    return out, clash


def _runs_only_in_files(conn, in_dir: Path) -> int:
    """How many refresh runs the files hold that the book does not."""
    source = in_dir / "refresh_runs.ndjson"
    if not source.exists() or not _table_exists(conn, "refresh_runs"):
        return 0
    held = {r["id"] for r in conn.execute("SELECT id FROM refresh_runs")}
    with source.open(encoding="utf-8") as handle:
        return sum(1 for line in handle
                   if line.strip() and json.loads(line).get("id") not in held)


class _Compared:
    """The book set against the files, and what each direction may do about it.

    ``found`` is every table where a number holds different rows, ``clash`` the file's
    numbers that cannot be loaded without displacing one of the book's rows, ``behind``
    how many refresh runs the files hold that the book does not.

    Three cases follow from those.

    Another book: a table nothing is deleted from disagrees (``NEVER_DELETED``). Every
    refresh writes a run and its snapshots, so two books that have each refreshed always
    land here. Nothing may be merged either way.

    A continuation: no such table disagrees and the book holds every run the files do.
    The book has seen everything in the files and moved on, so where a number now holds
    another row the book deleted the first and gave the number out again, and its row
    stands. A release published by a run whose history push failed is this case.

    Behind, with work of its own: no ledger disagrees, the files hold runs the book does
    not, and some other table disagrees. That is a book restored some days ago and edited
    by hand since, and the files' rows cannot be told from the ones it would displace.
    """

    def __init__(self, conn, in_dir: Path, tables: list[str]):
        self.found, self.clash = {}, {}
        for table in tables:
            source = in_dir / f"{table}.ndjson"
            if not source.exists() or not _table_exists(conn, table):
                continue
            got, clash = _parted_table(conn, table, source)
            if got:
                self.found[table], self.clash[table] = got, clash
        self.behind = _runs_only_in_files(conn, in_dir)

    @property
    def another_book(self) -> bool:
        return any(table in NEVER_DELETED for table in self.found)

    def refusal(self, behind_is_fatal: bool) -> dict:
        """What to refuse over, or {} where the merge may go ahead. An export writes the
        files whole, so for it a run the book lacks is a run it would take out."""
        out = {}
        if self.another_book or (self.behind and (self.found or behind_is_fatal)):
            out = {t: dict(g) for t, g in self.found.items()}
            if self.behind and behind_is_fatal:
                out.setdefault("refresh_runs", {})["missing"] = self.behind
        return out


def parted(db_path=None, in_dir: Path | None = None, tables: list[str] = None) -> dict:
    """{table: what differs} wherever the book and the history files hold different rows
    under one number. Empty when no number means two things. Reads only.

    ``different`` counts numbers the two share for different rows, ``first`` is the
    lowest of them and ``example`` shows it from both sides; ``renumbered`` counts rows
    the book holds under another number than the file gives them. A table in
    ``NEVER_DELETED`` in the answer means two books.
    """
    return standing(db_path, in_dir, tables)["parted"]


def standing(db_path=None, in_dir: Path | None = None, tables: list[str] = None) -> dict:
    """Where the book stands against the history files, in one answer: whether it is
    another book, how many refresh runs the files hold that it does not, and
    ``parted``'s table by table account. Reads only."""
    in_dir = Path(in_dir) if in_dir else DEFAULT_DIR
    conn = db.get_connection(db_path)
    try:
        compared = _Compared(conn, in_dir, tables or HISTORY_TABLES)
        return {"another_book": compared.another_book, "runs_behind": compared.behind,
                "parted": compared.found}
    finally:
        conn.close()


def export(db_path=None, out_dir: Path | None = None,
           tables: list[str] = None) -> dict:
    """Write each history table to ``out_dir/{table}.ndjson``, rows by id ascending.

    Keys are sorted per line so the text is stable, which keeps the git diff to the
    rows that actually changed. Returns rows written per table.

    Each file is written whole from the book, so the book has to be a continuation of
    what the files already hold. Where it is not, ``Parted`` is raised before a file is
    touched: it is another book (``_Compared``), or the files hold a refresh run it does
    not, which is what a book left behind by the scheduled runs looks like. In the
    workflow the export follows the rebuild, so neither can be so there.
    """
    out_dir = Path(out_dir) if out_dir else DEFAULT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = tables or HISTORY_TABLES
    conn = db.get_connection(db_path)
    written = {}
    try:
        refused = _Compared(conn, out_dir, tables).refusal(behind_is_fatal=True)
        if refused:
            raise Parted(f"not exported to {out_dir}", refused)
        for table in tables:
            if not _table_exists(conn, table):
                continue
            order = "id" if "id" in _columns(conn, table) else "rowid"
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            path = out_dir / f"{table}.ndjson"
            with path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps({k: row[k] for k in row.keys()},
                                            sort_keys=True, ensure_ascii=False))
                    handle.write("\n")
            written[table] = len(rows)
    finally:
        conn.close()
    return written


def rebuild(db_path=None, in_dir: Path | None = None,
            tables: list[str] = None) -> dict:
    """Recreate the schema and load every exported row back. Idempotent: a row
    replaces the one with its id, so rebuilding twice is a no-op.

    Only where it is the same row. A book that has run refreshes of its own holds other
    rows under the numbers the files use, and loading over it would swap them one for
    one. That raises ``Parted`` before a row is written, and the book is left as it was.
    Where the book is a continuation of the files and has given a number out again, the
    file's older row under that number is not loaded and the book's stands
    (``_Compared``).

    Foreign keys are off for the load because the export is already consistent and
    the current-state tables it points at are repopulated by the next refresh.
    """
    in_dir = Path(in_dir) if in_dir else DEFAULT_DIR
    tables = tables or HISTORY_TABLES
    path = db.init(db_path)                       # schema + migrations
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    loaded = {}
    try:
        compared = _Compared(conn, in_dir, tables)
        refused = compared.refusal(behind_is_fatal=False)
        if refused:
            raise Parted(f"not rebuilt from {in_dir}", refused)
        for table in tables:
            source = in_dir / f"{table}.ndjson"
            if not source.exists() or not _table_exists(conn, table):
                continue
            columns = set(_columns(conn, table))
            stands = compared.clash.get(table, ())
            count = 0
            with source.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    record = {k: v for k, v in json.loads(line).items()
                              if k in columns}
                    if stands and record.get("id") in stands:
                        continue                  # the book's row under this number stands
                    cols = ", ".join(record)
                    marks = ", ".join("?" for _ in record)
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
                        list(record.values()))
                    count += 1
            loaded[table] = count
        conn.commit()
    finally:
        conn.close()
    return loaded


def _history_last_run(in_dir: Path) -> int | None:
    source = in_dir / "refresh_runs.ndjson"
    if not source.exists():
        return None
    last = None
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                run_id = json.loads(line).get("id")
                if isinstance(run_id, int) and (last is None or run_id > last):
                    last = run_id
    return last


def restore_check(db_path=None, in_dir: Path | None = None,
                  remove: bool = True) -> dict:
    """Whether a database restored from yesterday's published release can be refreshed
    as it is, rather than rebuilt from the exported history.

    A rebuilt database holds the history tables and nothing else, so every source has to
    fetch in full, and the sources slower than daily (the pharmacology lookups, the drug
    codes, the Part D readers) took the daily run from 20 minutes to over an hour from
    2026-10-08. A restored one holds their data, so their TTLs can hold.

    Accepted only when it is the release the last committed run produced, or a later one:
    it opens, passes SQLite's quick check, its latest refresh run is at least the latest
    in the committed history, and it is not another book: every number it shares with
    that history's ledgers is the same row (``_Compared``). A later one is the 2026-10-26
    case, a release that went out when the history push failed, and the rebuild that
    follows merges the committed rows into it without losing its own. The last test is
    what the run number alone could not say: a book refreshed somewhere else reaches the
    same number by another road.
    Anything else is removed, so the rebuild starts clean and the run fetches every
    source, as it did before.

    ``remove=False`` gives the verdict and leaves the file where it is. The command line
    removes only on a GitHub runner, where the file is a download: run by hand against
    the book on an analyst's machine, which is behind the record on any ordinary day,
    the same command used to delete it.
    """
    path = Path(db_path if db_path is not None else db.DB_PATH)
    in_dir = Path(in_dir) if in_dir else DEFAULT_DIR
    expected = _history_last_run(in_dir)

    def refuse(why: str) -> dict:
        if remove:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        return {"restored": False, "why": why, "history_last_run": expected,
                "removed": remove}

    if not path.exists():
        return {"restored": False, "why": "no database was restored",
                "history_last_run": expected}
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
            last = conn.execute("SELECT MAX(id) FROM refresh_runs").fetchone()[0]
            compared = (_Compared(conn, in_dir, HISTORY_TABLES)
                        if check == "ok" and last is not None else None)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return refuse(f"the restored file does not open as a database: {exc}")
    if check != "ok":
        return refuse(f"the restored database fails its integrity check: {check}")
    if last is None:
        return refuse("the restored database records no refresh run")
    if expected is not None and last < expected:
        return refuse(f"the restored database stops at run {last}, before the committed "
                      f"history's run {expected}")
    if compared.another_book:
        return refuse("the restored database is not the committed history's own: "
                      + sentence(compared.found))
    return {"restored": True, "why": f"restored at run {last}",
            "history_last_run": expected}


if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "export"
    try:
        if action == "rebuild":
            print(json.dumps({"rebuilt": rebuild()}, indent=2))
        elif action == "restore-check":
            # Exit 0 when the restored database stands, 3 when it was refused or absent,
            # so the workflow can choose the fetch mode on the exit code alone.
            verdict = restore_check(remove=os.getenv("GITHUB_ACTIONS") == "true")
            print(json.dumps(verdict, indent=2))
            sys.exit(0 if verdict["restored"] else 3)
        elif action == "parted":
            # Whether this book is still a continuation of the committed record.
            print(json.dumps(standing(), indent=2))
        else:
            print(json.dumps({"exported": export()}, indent=2))
    except Parted as exc:
        # Exit 4, apart from restore-check's 3: the book and the files disagree and
        # nothing was written to either.
        print(json.dumps({"refused": str(exc), "tables": exc.found}, indent=2))
        sys.exit(4)
