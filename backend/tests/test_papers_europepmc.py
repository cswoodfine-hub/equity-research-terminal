"""The Europe PMC fetcher, on a saved payload and a temporary database."""

import datetime as dt
import json
import pathlib

import pytest

import db
import discovery as D
from fetchers import papers_europepmc as E

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "europepmc"
TODAY = dt.date(2026, 11, 20)

LABS = [
    # The paper in the payload is in patients; the lab had only reached mice.
    {"id": "A1", "name": "Matthew J. Atherton", "name_keys": ["matthew|atherton"],
     "institutions": ["University of Pennsylvania"], "rank": 12, "furthest_stage": "mouse",
     "company_coauthor": True},
    # In mice already, and this is its first paper with a company among the authors.
    {"id": "A2", "name": "Rafael A. Fissore", "name_keys": ["rafael|fissore"],
     "institutions": ["University of Massachusetts"], "rank": 40, "furthest_stage": "mouse",
     "company_coauthor": False},
    {"id": "A3", "name": "Pratik Gurnani", "name_keys": ["pratik|gurnani"],
     "institutions": ["University College London"], "rank": 2155, "furthest_stage": None,
     "company_coauthor": False},
    {"id": "A4", "name": "William Robinson", "name_keys": ["william|robinson"],
     "institutions": ["Stanford University"], "rank": 100, "furthest_stage": "patients",
     "company_coauthor": False},
]


def payload(source):
    return json.loads((FIXTURES / f"search_{source}.json").read_text())


def records():
    return [r for s in ("MED", "PPR") for r in payload(s)["resultList"]["result"]]


@pytest.fixture
def papers(tmp_path, monkeypatch):
    """A database, a lab seed of four, and a fetcher that reads the saved payload."""
    seed = tmp_path / "labs.ndjson"
    seed.write_text("".join(json.dumps({
        "country": None, "pct": 1 - lab["rank"] / 6345, "ranked_as_of": "2026-11-14",
        "modalities": [], "papers": 3, **lab}) + "\n" for lab in LABS))
    monkeypatch.setattr(D, "LABS_SEED", seed)
    path = db.init(tmp_path / "d.db")
    asked = []

    def make(today=TODAY, pages=None, run_id=None):
        fetcher = E.EuropePmcPapersFetcher(path, today=today)
        fetcher.force = True
        fetcher.refresh_run_id = run_id
        source = pages or {"MED": payload("MED"), "PPR": payload("PPR")}

        def get(params):
            asked.append(params["query"])
            return source["MED" if "SRC:MED" in params["query"] else "PPR"]
        fetcher._get = get
        return fetcher

    return path, make, asked


def rows(path, sql, *args):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def paper(path, pid):
    return rows(path, "SELECT * FROM discovery_papers WHERE id = ?", pid)[0]


def snapshots(path, kind):
    return [(r["entity_key"], json.loads(r["payload"])) for r in rows(
        path, "SELECT entity_key, payload FROM snapshots WHERE source = 'europepmc'"
              " AND entity_type = ? ORDER BY id", kind)]


# --- the parser ------------------------------------------------------------

def test_a_journal_paper_is_read_from_the_saved_payload():
    got = E.parse(next(r for r in records() if r["id"] == "42969556"))
    assert got["id"] == "MED:42969556" and got["source"] == "MED" and not got["preprint"]
    assert got["published"] == "2026-11-01" and got["indexed"] == "2026-11-03"
    assert got["senior_author"] == "Matthew J Atherton" and got["senior_last"] == "Atherton"
    assert "University of Pennsylvania" in got["senior_addresses"][0]
    assert got["journal"] and got["abstract"] and got["authors"] > 1
    assert not got["title"].endswith(".") and "<" not in got["title"]


def test_a_preprint_has_no_address_and_names_its_server():
    got = E.parse(next(r for r in records() if r["id"] == "PPR1355809"))
    assert got["preprint"] and got["id"] == "PPR:PPR1355809"
    assert got["senior_addresses"] == [] and got["all_addresses"] == []
    assert got["journal"] == "bioRxiv" and got["pmid"] is None


def test_a_paper_with_no_abstract_or_no_authors_is_still_a_paper():
    bare = E.parse(next(r for r in records() if r["id"] == "42977824"))
    assert bare["abstract"] == "" and bare["authors"] == 0 and bare["senior_author"] is None
    assert E.parse(next(r for r in records() if r["id"] == "43039921"))["abstract"] == ""


def test_a_consortium_is_not_the_senior_author():
    got = E.parse({"id": "1", "source": "MED", "title": "T", "firstPublicationDate": "2026-11-01",
                   "authorList": {"author": [
                       {"firstName": "Ada", "lastName": "Byron", "fullName": "Byron A"},
                       {"collectiveName": "The Example Consortium"}]}})
    assert got["senior_author"] == "Ada Byron" and got["authors"] == 1


def test_a_record_with_no_title_or_date_is_refused():
    assert E.parse({"id": "1", "source": "MED", "title": "T"}) is None
    assert E.parse({"id": "1", "source": "MED", "firstPublicationDate": "2026-11-01"}) is None


# --- a run -----------------------------------------------------------------

def test_a_run_stores_scores_and_matches(papers):
    path, make, asked = papers
    result = make().run()
    assert result.errors == [] and result.rows_fetched == 9 and not result.skipped_ttl
    assert all("FIRST_IDATE:[" in q and "TITLE_ABS:" in q for q in asked) and len(asked) == 2
    assert 'NOT PUB_TYPE:"Review"' in asked[0] and "PUB_TYPE" not in asked[1]

    matched = paper(path, "MED:42969556")
    assert (matched["lab_id"], matched["lab_match"]) == ("A1", D.LabIndex.BY_INSTITUTION)
    assert matched["institution"] == "University of Pennsylvania"
    assert matched["stage"] == "patients" and matched["first_seen"] == "2026-11-20"
    assert 0 <= matched["feas_pct"] <= 1 and 0 <= matched["comm_pct"] <= 1
    assert matched["model_version"] == D.scorer().version and matched["text_sha"]
    assert set(json.loads(matched["reasons"])) == {"feas", "comm"}
    assert json.loads(matched["areas"]) is not None
    assert "abstract" not in matched                        # the text itself is not kept

    preprint = paper(path, "PPR:PPR1355809")
    assert (preprint["lab_id"], preprint["lab_match"]) == ("A4", D.LabIndex.BY_NAME)
    assert preprint["institution"] is None
    assert preprint["company_author"] is None               # no address, so not known
    assert paper(path, "PPR:PPR1363655")["lab_id"] is None
    assert paper(path, "MED:43032656")["company_author"] == 1
    assert paper(path, "MED:42961140")["company_author"] == 0


def test_a_paper_with_no_abstract_is_held_unscored(papers):
    path, make, _ = papers
    make().run()
    held = paper(path, "MED:43039921")
    assert held["feas_pct"] is None and held["comm_pct"] is None and held["text_sha"] is None
    assert held["stage"] is None and held["areas"] is None and held["model_version"] is None
    assert "MED:43039921" not in dict(snapshots(path, "paper"))
    assert len(snapshots(path, "paper")) == 7


def test_the_feed_snapshot_is_what_the_ttl_reads(papers):
    path, make, _ = papers
    make().run()
    key, feed = snapshots(path, "feed")[0]
    assert key == E.ENTITY_KEY and feed["fetch_kind"] == "live"
    assert feed["records"] == 9 and feed["without_abstract"] == 2
    again = make()
    again.force = False
    result = again.run()
    assert result.skipped_ttl and result.rows_fetched == 0
    assert snapshots(path, "feed")[-1][1] == {"fetch_kind": "cache"}


def test_a_day_with_nothing_new_is_a_quiet_day_not_a_broken_source(papers):
    path, make, _ = papers
    make().run()
    before = (len(snapshots(path, "paper")), len(snapshots(path, "lab")))
    result = make(today=TODAY + dt.timedelta(days=1)).run()
    assert result.rows_fetched == 9 and result.errors == []
    assert (len(snapshots(path, "paper")), len(snapshots(path, "lab"))) == before
    assert paper(path, "MED:42969556")["first_seen"] == "2026-11-20"


def test_a_held_paper_is_scored_when_its_abstract_arrives(papers):
    path, make, _ = papers
    make().run()
    later = payload("MED")
    record = next(r for r in later["resultList"]["result"] if r["id"] == "43039921")
    record["abstractText"] = ("An adeno-associated virus vector was given to mice. Expression"
                              " was durable and dose-dependent, with no toxicity seen.")
    make(today=TODAY + dt.timedelta(days=3), pages={"MED": later, "PPR": payload("PPR")}).run()
    now = paper(path, "MED:43039921")
    assert now["feas_pct"] is not None and now["stage"] == "mouse"
    assert now["first_seen"] == "2026-11-20"
    snap = dict(snapshots(path, "paper"))["MED:43039921"]
    assert snap["seen"] == "2026-11-20" and snap["indexed"] == "2026-11-17"


def test_the_first_run_reaches_back_to_the_day_the_labs_were_ranked(papers):
    _path, make, asked = papers
    make(today=dt.date(2026, 12, 20)).run()
    assert "FIRST_IDATE:[2026-11-14 TO 2026-12-21]" in asked[0]
    asked.clear()
    make(today=dt.date(2026, 12, 21)).run()
    assert "FIRST_IDATE:[2026-11-30 TO 2026-12-22]" in asked[0]


def test_the_first_run_never_reaches_further_than_its_limit(papers):
    _path, make, asked = papers
    make(today=dt.date(2027, 11, 20)).run()
    assert "FIRST_IDATE:[2027-07-23 TO" in asked[0]


def test_a_lab_snapshot_is_written_only_when_the_lab_moves(papers):
    path, make, _ = papers
    make().run()
    labs = dict(snapshots(path, "lab"))
    # A1 went from mice to patients; A2 gained its first company co-author; A3's paper
    # names no model and A4 was already in patients.
    assert set(labs) == {"A1", "A2"}
    assert labs["A1"]["furthest_stage"] == "patients" and labs["A1"]["paper"] == "MED:42969556"
    assert labs["A2"]["company_coauthor"] is True and labs["A2"]["furthest_stage"] == "mouse"
    assert labs["A1"]["seen"] == "2026-11-20" and labs["A1"]["indexed"] == "2026-11-03"


def test_every_snapshot_carries_the_run_that_wrote_it(papers):
    path, make, _ = papers
    conn = db.get_connection(path)
    run_id = conn.execute("INSERT INTO refresh_runs (status) VALUES ('running')").lastrowid
    conn.commit()
    conn.close()
    make(run_id=run_id).run()
    assert {r["refresh_run_id"] for r in rows(
        path, "SELECT refresh_run_id FROM snapshots WHERE source = 'europepmc'")} == {run_id}


def test_a_paper_leaves_the_table_after_its_keep_time(papers):
    path, make, _ = papers
    make().run()
    empty = {"resultList": {"result": []}}
    make(today=TODAY + dt.timedelta(days=E.KEEP_DAYS + 1),
         pages={"MED": empty, "PPR": empty}).run()
    assert rows(path, "SELECT COUNT(*) AS n FROM discovery_papers")[0]["n"] == 0
    assert len(snapshots(path, "paper")) == 7                # the history stays


def test_without_a_model_file_papers_are_stored_unscored(papers, monkeypatch):
    path, make, _ = papers
    monkeypatch.setattr(D, "scorer", lambda path=None: None)
    result = make().run()
    assert result.errors == [] and any("no score model" in n for n in result.notes)
    stored = paper(path, "MED:42969556")
    assert stored["feas_pct"] is None and stored["lab_id"] == "A1"
    assert stored["stage"] == "patients"


def test_a_source_that_fails_is_reported_and_marked(papers):
    path, make, _ = papers
    fetcher = make()

    def down(_params):
        raise ValueError("Europe PMC answered with a page of HTML")
    fetcher._get = down
    result = fetcher.run()
    assert result.rows_fetched == 0 and "Europe PMC" in result.errors[0]
    assert snapshots(path, "feed")[-1][1]["fetch_kind"] == "error"


def test_the_fetcher_is_part_of_the_refresh():
    import refresh

    assert any(isinstance(f, E.EuropePmcPapersFetcher)
               for f in refresh._universe_fetchers(None))
