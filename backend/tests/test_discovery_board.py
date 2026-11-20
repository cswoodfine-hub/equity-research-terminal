"""The Discovery tab's two reads, as functions and through the API."""

import db
import discovery_board as B
import response_cache
from test_discovery_alerts import desk  # noqa: F401
from test_papers_europepmc import papers  # noqa: F401

EVER = 100_000        # the saved payload is dated November 2026; ask for all of it


def test_an_empty_book_gives_empty_lists_and_says_what_it_stands_on(tmp_path):
    path = db.init(tmp_path / "d.db")
    got = B.alerts(path)
    assert got["alerts"] == [] and got["label"].startswith("Discovery")
    assert got["basis"]["labs"] == 0 and got["basis"]["last_read"] is None
    assert got["basis"]["top_paper_share"] == 5 and got["basis"]["lab_rank_limit"] == 300
    assert B.papers(path)["papers"] == [] and B.papers(path)["total"] == 0


def test_a_database_from_before_discovery_gives_nothing_and_no_error(tmp_path):
    path = db.init(tmp_path / "d.db")
    conn = db.get_connection(path)
    conn.execute("DROP TABLE discovery_papers")
    conn.execute("DROP TABLE discovery_labs")
    conn.commit()
    conn.close()
    assert B.alerts(path) == {"label": B.LABEL, "basis": None, "days": 14, "alerts": []}
    assert B.papers(path)["papers"] == []


def test_alerts_come_with_their_paper_and_their_lab(desk):  # noqa: F811
    path, run = desk
    run()
    got = B.alerts(path, days=EVER)
    assert len(got["alerts"]) == 7
    assert [a["significance"] for a in got["alerts"]][:3] == ["high", "high", "high"]
    assert got["basis"]["labs"] == 4 and got["basis"]["last_read_records"] == 9
    assert got["basis"]["held_without_abstract"] == 2
    stage = next(a for a in got["alerts"] if a["kind"] == "discovery_lab_stage")
    assert stage["kind_name"] == "Lab reached a later model" and stage["before"] == "mice"
    assert stage["lab"] == {"id": "A1", "name": "Matthew J. Atherton", "rank": 12,
                            "institutions": ["University of Pennsylvania"]}
    assert stage["paper"]["id"] == "MED:42969556" and stage["paper"]["stage_name"] == "patients"
    assert stage["url"] == "https://europepmc.org/article/MED/42969556"
    top = next(a for a in got["alerts"] if a["kind"] == "discovery_paper_top"
               and a["paper_id"] == "MED:43032656")
    assert top["lab"] is None and top["paper"]["comm_top"] == "top 4%"
    assert top["paper"]["company_author"] is True


def test_papers_are_listed_best_first_and_held_ones_are_left_out(desk):  # noqa: F811
    path, run = desk
    run()
    got = B.papers(path, days=EVER, sort="feas")
    assert got["total"] == 7 and len(got["papers"]) == 7
    assert got["papers"][0]["id"] == "MED:42969556" and got["papers"][0]["feas_top"] == "top 1%"
    assert "MED:43039921" not in {p["id"] for p in got["papers"]}
    assert B.papers(path, days=EVER, sort="comm")["papers"][0]["id"] == "MED:43032656"
    newest = B.papers(path, days=EVER, sort="date")["papers"]
    assert [p["indexed"] for p in newest] == sorted((p["indexed"] for p in newest), reverse=True)
    assert B.papers(path, days=EVER, sort="nonsense")["sort"] == "feas"
    preprint = next(p for p in got["papers"] if p["id"] == "PPR:PPR1355809")
    assert preprint["preprint"] and preprint["company_author"] is None
    assert preprint["lab"] == {"id": "A4", "name": "William Robinson", "rank": 100}


def test_the_reads_answer_over_the_api(desk, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    import main

    path, run = desk
    run()
    monkeypatch.setattr(db, "DB_PATH", path)
    client = TestClient(main.app)
    alerts = client.get(f"/discovery/alerts?days={EVER}")
    assert alerts.status_code == 200 and len(alerts.json()["alerts"]) == 7
    listed = client.get(f"/discovery/papers?days={EVER}&sort=comm")
    assert listed.status_code == 200 and listed.json()["sort"] == "comm"
    feed = client.get("/changes").json()
    assert sum(1 for i in feed if i.get("kind") == "discovery") == 7


def test_the_tab_reads_are_kept_warm():
    assert "/discovery/alerts?days=14" in response_cache.GLOBAL_READS
    assert "/discovery/papers?days=30&sort=feas" in response_cache.GLOBAL_READS
