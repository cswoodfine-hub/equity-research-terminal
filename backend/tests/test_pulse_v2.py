"""The daily pulse's schema 2: companies tagged by the terminal's own tickers with a role,
a story keyed across the days it runs, and the week's stories placed in the ranked feed.
Invented test data in the file's shape (example.com links); no network."""

import datetime as dt
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

import db
import main
import pulse
import pulse_universe
import seed
import universe_command as uc
from fetchers.news_pulse import PulseNewsFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "pulse_v2"
WEEK_FIXTURE = Path(__file__).parent / "fixtures" / "universe" / "week_sources.json"


def _book(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    nvs = conn.execute("SELECT id FROM companies WHERE ticker = 'NVS'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, generic_name, brand_name, is_marketed)"
                 " VALUES (?, 'onasemnogene abeparvovec', 'Zolgensma', 1)", (nvs,))
    conn.commit()
    conn.close()
    folder = tmp_path / "pulse"
    folder.mkdir()
    for f in FIXTURES.glob("*.json"):
        shutil.copy(f, folder)
    return path, folder


def _run(path, folder, today=dt.date(2026, 11, 10)):
    fetcher = PulseNewsFetcher(path, folder=folder, today=today)
    return fetcher.upsert(fetcher.normalise(fetcher.fetch()))


def test_schema_2_fields_are_read_and_spelled_one_way():
    payload = json.loads((FIXTURES / "2026-11-09.json").read_text())
    got, problems = pulse.parse(payload, "2026-11-09.json")
    assert problems == []
    first, deal, kite = got["items"][:3]
    # A key and a role are read one way however the file spells them.
    assert first["event_key"] == "bayn:asundexian:fda-approval"
    assert [e["role"] for e in first["entities"]] == ["subject", "read_across", "read_across"]
    # The schema 1 fields still carry every entity, for a reader that knows only them.
    assert first["tickers"] == ["BAYN", "BMY", "JNJ"]
    assert deal["companies"] == ["Roche", "Testco"]
    assert kite["phase"] == "2" and kite["entities"] == []


def test_a_ticker_the_terminal_holds_or_a_name_ties_and_nothing_is_guessed(tmp_path):
    path, folder = _book(tmp_path)
    result = _run(path, folder)
    assert result.notes == ["2026-11-09.json item 1: ZZZZ is not a company the terminal "
                            "holds; left untied"]
    conn = db.get_connection(path)
    roles = {(r["url"].rsplit("/", 1)[1], r["ticker"], r["role"]) for r in conn.execute(
        "SELECT p.url, c.ticker, pc.role FROM pulse_item_companies pc"
        " JOIN pulse_items p ON p.id = pc.item_id JOIN companies c ON c.id = pc.company_id")}
    assert roles == {
        ("bayer-approval", "BAYN", "subject"), ("bayer-approval", "BMY", "read_across"),
        ("bayer-approval", "JNJ", "read_across"),
        ("bayer-approval-2", "BAYN", "subject"), ("bayer-approval-2", "BMY", "read_across"),
        # Roche's ADR ticker is Roche.
        ("roche-testco", "ROG", "subject"), ("roche-testco-2", "ROG", "subject"),
        # Kite is Gilead's; a schema 1 item names every company a subject.
        ("kite", "GILD", "subject"),
        # Zolgensma is Novartis's alone, so the asset names it.
        ("zolgensma", "NVS", "subject"),
        ("novo", "NVO", "subject")}
    # Novo Holdings is not Novo Nordisk.
    assert conn.execute("SELECT tickers FROM pulse_items WHERE url LIKE '%windward'"
                        ).fetchone()[0] is None


def test_read_across_and_repeats_stay_out_of_the_change_feed(tmp_path):
    path, folder = _book(tmp_path)
    _run(path, folder)
    conn = db.get_connection(path)
    changes = sorted((r["entity_key"].rsplit("/", 1)[1], r["entity_key"].split("|")[0])
                     for r in conn.execute("SELECT entity_key FROM changes"))
    # Bayer's approval once though the pulse ran it twice; BMS and J&J never, since they
    # are read-across; Roche's deal twice, because the second telling is an update.
    assert changes == [("bayer-approval", "BAYN"), ("kite", "GILD"), ("novo", "NVO"),
                       ("roche-testco", "ROG"), ("roche-testco-2", "ROG"),
                       ("zolgensma", "NVS")]


def test_read_across_reaches_the_companys_news_marked(tmp_path, monkeypatch):
    path, folder = _book(tmp_path)
    _run(path, folder)
    monkeypatch.setattr(db, "DB_PATH", path)
    news = TestClient(main.app).get("/companies/BMY/news").json()["news"]
    assert {(n["source"], n["url"].rsplit("/", 1)[1]) for n in news} == {
        ("pulse (read-across)", "bayer-approval"), ("pulse (read-across)", "bayer-approval-2")}


def test_the_week_reads_a_story_once_by_its_latest_telling(tmp_path):
    path, folder = _book(tmp_path)
    _run(path, folder)
    conn = db.get_connection(path)
    rows = {r["event_key"]: r for r in uc._pulse_rows(conn, ["BAYN", "BMY", "ROG", "NVO"],
                                                      "2026-11-03", "2026-11-10")}
    bayer = rows["bayn:asundexian:fda-approval"]
    assert bayer["headline"] == "Bayer's factor XIa approval, a day on"
    assert bayer["days"] == ["2026-11-09", "2026-11-10"] and bayer["first"] == "2026-11-09"
    assert bayer["roles"] == {"BAYN": "subject", "BMY": "read_across"}
    # The deal was first reported on the 9th, from an article of the 8th.
    assert rows["rog:testco:deal"]["first"] == "2026-11-08"


def _pulse_row(key, tier, kind, roles, first, headline=None):
    return {"id": hash(key) % 1000, "pulse_date": first, "tier": tier, "kind": kind,
            "headline": headline or f"Pulse story {key}", "detail": None,
            "url": f"https://news.example.com/{key}", "published_at": first,
            "event_key": key, "first_reported": first, "phase": None, "roles": roles,
            "first": first, "days": [first]}


def test_tier_1_ranks_among_the_primary_items_and_a_told_story_folds_in():
    fx = json.loads(WEEK_FIXTURE.read_text())
    fx["pulse"] = [
        _pulse_row("lly-deal", 1, "deal", {"LLY": "subject"}, "2026-10-03"),
        _pulse_row("pfe-policy", 1, "policy", {"PFE": "subject"}, "2026-10-02"),
        # Roche's readout of the 1st is already ranked from its own announcement.
        _pulse_row("rog-readout", 1, "readout", {"ROG": "subject"}, "2026-10-01"),
        _pulse_row("nvo-readout", 1, "readout", {"NVO": "subject"}, "2026-10-02"),
        _pulse_row("gsk-earnings", 2, "earnings", {"GSK": "subject"}, "2026-10-04"),
        _pulse_row("bmy-across", 1, "approval", {"BMY": "read_across"}, "2026-10-02"),
        _pulse_row("jnj-small", 3, "other", {"JNJ": "subject"}, "2026-10-02"),
        _pulse_row("private", 1, "financing", {}, "2026-10-02"),
    ]
    since = (uc.dt.date(2026, 10, 6) - uc.dt.timedelta(days=uc.NEWS_DAYS)).isoformat()
    today = uc.dt.date(2026, 10, 6)
    rows = uc._week_rows(fx["changes"], fx["companies"], since, today.isoformat())
    items = uc._week_items(fx, fx["companies"], fx["events"], today, rows)
    assert [(i["kind"], i.get("event_key")) for i in items] == [
        ("deal", None), ("pulse", "lly-deal"), ("market", None), ("pulse", "pfe-policy"),
        ("readout", None), ("pulse", "nvo-readout"), ("deal", None), ("readout2", None),
        ("approval", None), ("slips", None), ("regulatory", None), ("notice", None),
        ("pulse", "gsk-earnings"), ("earnings", None), ("filing", None), ("labels", None)]
    assert len(items) == uc.WEEK_ITEMS
    folded = items[4]
    assert folded["tickers"] == ["ROG"] and folded["rows"][-1] == [
        "Daily pulse (AI summary)", "Pulse story rog-readout"]
    pulse_item = items[1]
    assert pulse_item["src"] == "Daily pulse (AI summary)"
    assert pulse_item["verbatim"] is False and pulse_item["fig"] == "tier 1"
    assert pulse_item["url"] == "https://news.example.com/lly-deal"


def test_the_universe_file_lists_each_company_its_names_and_drugs_it_alone_owns(tmp_path):
    path, _folder = _book(tmp_path)
    conn = db.get_connection(path)
    lly = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    nvs = conn.execute("SELECT id FROM companies WHERE ticker = 'NVS'").fetchone()[0]
    conn.executemany("INSERT INTO assets (owner_company_id, generic_name, brand_name,"
                     " internal_code, is_marketed) VALUES (?, ?, ?, ?, ?)",
                     [(lly, "Orforglipron", "Foundayo", "NDA219999", 1),
                      (lly, "Budesonide", None, None, 1),
                      (nvs, "Budesonide", None, None, 1),
                      (nvs, "Pelacarsen", None, "TQJ230", 0)])
    conn.commit()
    got = pulse_universe.build(conn)
    by = {c["ticker"]: c for c in got["companies"]}
    assert by["ROG"]["us_adr_ticker"] == "RHHBY" and by["ROG"]["aliases"] == ["Genentech"]
    assert by["LLY"]["press_names"] == ["Eli Lilly", "Lilly"]
    # A name two companies own is neither's; an application number is no name.
    assert by["LLY"]["brands"] == ["Foundayo", "Orforglipron"]
    assert by["NVS"]["brands"] == ["onasemnogene abeparvovec", "Zolgensma"]
    assert by["NVS"]["pipeline"] == ["Pelacarsen", "TQJ230"]
    assert {"name": "Merck KGaA", "is_not": "MRK"} in got["not_these"]
    json.dumps(got)
