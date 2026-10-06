"""Book guards for the development cost view: on the built database every company reads,
every refusal says why, the arithmetic reconciles, the named trials spend less in a year
than the book charges for R&D, and reading it writes nothing."""

import datetime as dt
import re

import pytest

import development as D
import forecast_view as V

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


@pytest.fixture(scope="module")
def views(request):
    book = request.getfixturevalue("book")
    tickers = [r[0] for r in book.execute("SELECT ticker FROM companies ORDER BY ticker")]
    # Every read opens its own connection, so this connection's total_changes would never
    # see a write; data_version moves whenever any other connection commits to the file.
    version = book.execute("PRAGMA data_version").fetchone()[0]
    out = {t: D.for_company(None, t, dt.date.today()) for t in tickers}
    assert book.execute("PRAGMA data_version").fetchone()[0] == version, \
        "reading the cost view wrote to the book"
    return out


@pytest.fixture(scope="module")
def book(request):
    """The conftest book, at module scope so the whole book is read once."""
    import sqlite3

    import db
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        built = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    except sqlite3.OperationalError:
        built = 0
    if not built:
        conn.close()
        pytest.skip(f"the database at {db.DB_PATH} has not been built")
    yield conn
    conn.close()


def _read(view):
    """Every line that reads: funding, failing, or with its cost to the gate unread."""
    return view["rows"] + view["failing"] + view["uncosted"]


def test_every_pipeline_line_reads_or_says_why_not(views):
    ok = sum(len(_read(v)) for v in views.values())
    refused = [r for v in views.values() for r in v["refused"]]
    assert ok, "no pipeline line reads"
    assert ok >= 0.9 * (ok + len(refused)), (ok, len(refused))
    for row in refused:
        assert row["ok"] is False and row["reason"] in D.REFUSALS and row["why"], row
        # A line that failed is named rather than taking the list down, but on the book
        # none should: an error here is a defect, not a reading.
        assert row["reason"] != "error", row


def test_the_arithmetic_reconciles_on_every_asset(views):
    for view in views.values():
        for row in _read(view):
            gate, ladder = row["gate"], row["ladder"]
            scale = max(1.0, abs(ladder["rnpv"]))
            # p_gate x the success leg is the rNPV in force at the company's share.
            assert abs(gate["ev"] - ladder["rnpv"]) <= 1e-9 * scale, row["name"]
            if gate["unread"]:
                # Nothing counted and nothing sunk, or a counted study the registry gives
                # no enrolment or completion for: unknown, never a free gate.
                counted = row["stages"][0]["studies"]
                assert (not counted or any(s["ahead_usd_mm"] is None for s in counted)), \
                    row["name"]
                assert gate["cost"] is None and gate["net"] is None, row["name"]
                assert gate["funds"] is None and ladder["value_today"] is None
                assert "cannot be read" in gate["basis"], row["name"]
                continue
            # A gate that costs nothing to reach has only sunk studies ahead of it.
            if gate["cost"] == 0:
                assert gate["due"] or all(s["share_ahead"] == 0
                                          for s in row["stages"][0]["studies"]), row["name"]
            assert abs(gate["net"] - (gate["ev"] - gate["cost"])) <= 1e-9 * scale
            # Today's value after every cost reads unless a later stage cannot be costed.
            if ladder["value_today"] is None:
                assert any(s.get("unread") for s in row["stages"][1:]), row["name"]
            else:
                assert abs(ladder["value_today"] - (ladder["rnpv"] - ladder["risked_cost"])) \
                    <= 1e-9 * scale, row["name"]
            assert gate["cost"] >= 0 and gate["high"]["cost"] >= gate["cost"] - 1e-12
            assert gate["funds"] == (gate["net"] >= 0)
            assert row["stages"][0]["gate"] == gate["gate"]
            for stage in row["stages"]:
                assert stage["grade"] in ("analogue", "convention"), stage
                for study in stage["studies"]:
                    assert study["fit"] == "modelled", study


def test_every_open_study_is_counted_or_in_the_separate_figure(views, book):
    """The headline counts the gate's studies in a modelled indication, the ladder the
    later stages', and the separate figure every other open Phase 2 and 3 study of the
    asset, so the whole programme is accounted for and none silently drops out."""
    import pos_granular as PG
    states = ",".join("?" * len(PG.OPEN_STATUSES))
    for view in views.values():
        for row in _read(view):
            listed = ({s["nct_id"] for st in row["stages"] for s in st["studies"]}
                      | {s["nct_id"] for s in row["outside"]["studies"]})
            answered = set(PG.read_out(book, row["asset_id"]))
            live = {r[0] for r in book.execute(
                f"""SELECT nct_id FROM trials WHERE asset_id = ?
                      AND phase IN ('Phase 2', 'Phase 2/3', 'Phase 3')
                      AND overall_status IN ({states})""",
                (row["asset_id"], *PG.OPEN_STATUSES))}
            assert live - answered <= listed, (row["name"], live - answered - listed)


def test_failing_gates_come_first(views):
    for view in views.values():
        assert all(r["gate"]["funds"] is False for r in view["failing"])
        assert all(r["gate"]["funds"] is True for r in view["rows"])
        assert all(r["gate"]["funds"] is None and r["gate"]["unread"]
                   for r in view["uncosted"])


def test_named_trial_spend_sits_inside_the_books_rd(views):
    """The R&D ratio already pays for today's trials: a year of the named studies'
    spend never exceeds the R&D the book charges its marketed lines in its first year."""
    for ticker, view in views.items():
        rec = view["reconciliation"]
        if rec["book_rd"]:
            assert rec["named_spend_12m"] < rec["book_rd"], (ticker, rec)


def test_the_success_leg_is_the_rollup_gates(views):
    """'If it passes' is build 2's leg wherever it is shown."""
    for ticker in ("LLY", "AZN", "MRK", "NVO"):
        if ticker not in views:
            continue
        lines = {l["asset_id"]: l for l in V.company_rollup(None, ticker)["lines"]}
        for row in _read(views[ticker]):
            gate = lines[row["asset_id"]]["gate"]
            if gate and gate.get("legs_basis") == "derived":
                assert row["gate"]["success_leg_per_share"] == pytest.approx(
                    gate["per_share_success"], rel=1e-9), row["name"]


def test_the_copy_keeps_the_house_style(views):
    texts = []
    for view in views.values():
        texts.append(view["reconciliation"]["sentence"] or "")
        for row in _read(view) + view["refused"]:
            texts.append(row.get("why") or "")
            for stage in row.get("stages") or []:
                texts += [stage["basis"], stage.get("date_basis") or ""]
    for text in texts:
        assert "—" not in text and "–" not in text, text
        assert not any(re.search(rf"\b{w}\b", text, re.I) for w in BANNED), text
