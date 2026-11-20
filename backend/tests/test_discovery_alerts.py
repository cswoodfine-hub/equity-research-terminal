"""Discovery's alerts: what raises one, and that each is raised once and once only."""

import datetime as dt
import json

import pytest

import db
import diff
import discovery as D
import history
import materiality
import whatchanged
from test_papers_europepmc import papers, payload, rows, snapshots  # noqa: F401

DAY = dt.date(2026, 11, 8)
# The rank each paper of the saved payload is given here, by Europe PMC id. Anything
# not listed sits mid-table. The real scorer is held to scikit-learn in test_discovery.
RANKS = {"42969556": (0.995, 0.60),      # top 1% for feasibility: high
         "43032656": (0.40, 0.96),       # top 5% for commercial pull: medium
         "43039921": (0.97, 0.97)}       # arrives without an abstract


class Ranks:
    version = "test-ranks"

    def __init__(self, by_title):
        self.by_title = by_title

    def score(self, title, _abstract, _preprint=False):
        feas, comm = self.by_title.get(title, (0.5, 0.5))
        return {"feas": {"score": feas, "pct": feas, "reasons": {"flags": [], "phrases": []}},
                "comm": {"score": comm, "pct": comm, "reasons": {"flags": [], "phrases": []}}}


@pytest.fixture
def desk(papers, monkeypatch):  # noqa: F811
    path, make, _asked = papers
    titles = {r["title"]: RANKS[r["id"]] for s in ("MED", "PPR")
              for r in payload(s)["resultList"]["result"] if r["id"] in RANKS}
    monkeypatch.setattr(D, "scorer", lambda path=None: Ranks(titles))

    def run(today=DAY, pages=None, to=path):
        conn = db.get_connection(to)
        run_id = conn.execute("INSERT INTO refresh_runs (status) VALUES ('running')").lastrowid
        conn.commit()
        conn.close()
        fetcher = make(today=today, pages=pages, run_id=run_id)
        fetcher.db_path = to
        result = fetcher.run()
        assert result.errors == []
        return diff.detect_changes(to, run_id)["discovery_alerts"]

    return path, run


def alerts(path):
    return rows(path, "SELECT * FROM changes WHERE entity_type IN ('paper', 'lab') ORDER BY id")


def kinds(path):
    return sorted((a["change_type"], a["entity_key"], a["significance"]) for a in alerts(path))


EXPECTED = [
    ("discovery_lab_company", "A2", "high"),
    ("discovery_lab_paper", "A1|MED:42969556", "medium"),
    ("discovery_lab_paper", "A2|MED:42993797", "medium"),
    ("discovery_lab_paper", "A4|PPR:PPR1355809", "medium"),
    ("discovery_lab_stage", "A1|patients", "high"),
    ("discovery_paper_top", "MED:42969556", "high"),
    ("discovery_paper_top", "MED:43032656", "medium"),
]


def test_the_four_alerts_fire_for_what_the_payload_holds(desk):
    path, run = desk
    assert run() == 7
    # A3 is ranked 2,155: its paper is stored and matched and raises nothing. A4 was
    # already in patients, so its paper is a publication and not a later stage. The
    # paper indexed on 31 October was first seen eight days later and raises nothing.
    assert kinds(path) == EXPECTED


def test_a_second_run_and_a_second_diff_repeat_nothing(desk):
    path, run = desk
    run()
    assert run(today=DAY + dt.timedelta(days=1)) == 0
    assert diff.detect_changes(path, 1)["discovery_alerts"] == 0
    assert kinds(path) == EXPECTED


def test_a_database_rebuilt_from_history_repeats_nothing(desk, tmp_path):
    path, run = desk
    run()
    out = tmp_path / "history"
    history.export(path, out)
    rebuilt = tmp_path / "rebuilt.db"
    history.rebuild(rebuilt, out)
    # The rebuild carries snapshots and changes and none of the current-state tables,
    # so the next fetch sees every paper as if for the first time.
    assert rows(rebuilt, "SELECT COUNT(*) AS n FROM discovery_papers")[0]["n"] == 0
    assert run(today=DAY + dt.timedelta(days=1), to=rebuilt) == 0
    assert kinds(rebuilt) == EXPECTED
    assert rows(rebuilt, "SELECT COUNT(*) AS n FROM discovery_papers")[0]["n"] == 9


def test_papers_first_seen_long_after_they_were_indexed_raise_nothing(desk):
    path, run = desk
    assert run(today=dt.date(2026, 12, 20)) == 0
    assert alerts(path) == []
    # The labs still moved, so the same papers cannot read as news on a later day.
    assert set(dict(snapshots(path, "lab"))) == {"A1", "A2"}
    assert run(today=dt.date(2026, 12, 21)) == 0


def test_a_stage_alert_needs_a_later_stage_than_any_before(desk):
    path, run = desk
    run()
    stage = [a for a in alerts(path) if a["change_type"] == "discovery_lab_stage"]
    assert [(a["entity_key"], a["old_value"]) for a in stage] == [("A1|patients", "mice")]
    # A second paper in patients from the same lab is a publication, not a new stage.
    again = payload("MED")
    record = next(r for r in again["resultList"]["result"] if r["id"] == "42969556")
    record["id"] = record["pmid"] = "49999999"
    record["title"] = "A second study in patients"
    assert run(today=DAY + dt.timedelta(days=1),
               pages={"MED": again, "PPR": payload("PPR")}) == 1
    assert kinds(path) == sorted(
        EXPECTED + [("discovery_lab_paper", "A1|MED:49999999", "medium")])


def test_a_held_paper_alerts_when_its_abstract_arrives(desk):
    path, run = desk
    run(today=dt.date(2026, 11, 18))
    assert not [a for a in alerts(path) if a["entity_key"] == "MED:43039921"]
    later = payload("MED")
    record = next(r for r in later["resultList"]["result"] if r["id"] == "43039921")
    record["abstractText"] = "An adeno-associated virus vector was given to mice."
    # Ten days on: past the limit for a paper seen for the first time, and this one was
    # first seen the day after it was indexed.
    assert run(today=dt.date(2026, 11, 28), pages={"MED": later, "PPR": payload("PPR")}) == 1
    arrived = [a for a in alerts(path) if a["entity_key"] == "MED:43039921"]
    assert [(a["change_type"], a["significance"]) for a in arrived] == [
        ("discovery_paper_top", "medium")]


def test_an_alert_reads_as_a_sentence_and_names_its_paper(desk):
    path, run = desk
    run()
    by_kind = {(a["change_type"], a["entity_key"]): a for a in alerts(path)}
    top = by_kind["discovery_paper_top", "MED:42969556"]
    assert top["new_value"].startswith("Top 1% for feasibility, top 40% for commercial pull: ")
    assert "Matthew J Atherton, University of Pennsylvania" in top["new_value"]
    assert top["new_value"].endswith(", 2026-11-01)") and top["field"] == "MED:42969556"
    published = by_kind["discovery_lab_paper", "A4|PPR:PPR1355809"]["new_value"]
    assert published.startswith("William Robinson, ranked 100 of 4 lab heads, published: ")
    assert "bioRxiv preprint, 2026-11-02" in published
    assert published.endswith(f"Matched by {D.LabIndex.BY_NAME}.")
    stage = by_kind["discovery_lab_stage", "A1|patients"]
    assert ": first paper in patients, after mice. " in stage["new_value"]
    assert stage["field"] == "MED:42969556"
    company = by_kind["discovery_lab_company", "A2"]
    assert ": first paper with a company among the authors. " in company["new_value"]
    for alert in alerts(path):
        assert "—" not in alert["new_value"] and "None" not in alert["new_value"]


def test_the_feed_carries_discovery_items_and_a_company_feed_does_not(desk):
    path, run = desk
    run()
    feed = [i for i in whatchanged.build_feed(path) if i["kind"] == "discovery"]
    assert len(feed) == 7 and all(i["ticker"] is None for i in feed)
    assert feed[0]["significance"] == "high"
    top = next(i for i in feed if i["change_type"] == "discovery_paper_top"
               and i["entity_key"] == "MED:42969556")
    assert top["url"] == "https://europepmc.org/article/MED/42969556"
    assert top["reason"] == "Discovery, paper in the top 5%"
    assert not [i for i in whatchanged.build_feed(path, ticker="LLY")
                if i["kind"] == "discovery"]


def test_each_alert_names_the_rule_that_raised_it():
    reason = materiality.change_reason
    assert reason("discovery_lab_paper") == "Discovery, lab head ranked in the top 300"
    assert reason("discovery_lab_stage") == "Discovery, lab reached a later model"
    assert reason("discovery_lab_company") == "Discovery, lab's first company co-author"


def test_the_bars_are_the_ones_the_config_states():
    rate = materiality.discovery_paper_significance
    assert rate(0.949, 0.2) is None and rate(None, None) is None
    assert rate(0.95, None) == "medium" and rate(0.3, 0.99) == "high"
    assert materiality.discovery_is_news("2026-11-01", "2026-11-08")
    assert not materiality.discovery_is_news("2026-11-01", "2026-11-09")
    assert not materiality.discovery_is_news(None, "2026-11-09")
    assert materiality.discovery_stage_significance("primate") == "high"
    assert materiality.discovery_stage_significance("mouse") == "medium"


def test_a_database_from_before_discovery_is_left_alone(tmp_path):
    path = db.init(tmp_path / "old.db")
    conn = db.get_connection(path)
    try:
        conn.execute("DROP TABLE discovery_papers")
        conn.execute("DROP TABLE discovery_labs")
        assert diff._diff_discovery(conn, None) == 0
    finally:
        conn.close()
