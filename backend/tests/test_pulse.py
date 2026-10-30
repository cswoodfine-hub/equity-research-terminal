"""The daily pulse's files read into news, the change feed and the sector feed. The
fixture is invented test data in the file's shape (example.com links), since it covers
the cases a real briefing may or may not carry; no network."""

import datetime as dt
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

import db
import main
import materiality
import pulse
import seed
from fetchers.news_pulse import PulseNewsFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "pulse"
TODAY = dt.date(2026, 10, 30)


def _payload():
    return json.loads((FIXTURES / "2026-10-30.json").read_text())


def test_items_need_a_link_and_dates_are_checked():
    got, problems = pulse.parse(_payload(), "2026-10-30.json")
    assert [i["url"].rsplit("/", 1)[1] for i in got["items"]] == [
        "lilly-testco", "roche-regeneron", "merck-kgaa", "privateco", "vertex"]
    assert problems == ["2026-10-30.json item 4: no headline or no link"]
    by = {i["url"].rsplit("/", 1)[1]: i for i in got["items"]}
    # A source dated after the briefing is a misread date.
    assert by["privateco"]["published"] is None
    assert by["vertex"]["tier"] is None and by["vertex"]["kind"] == "other"
    # A file whose date is not its name is refused whole.
    assert pulse.parse(_payload(), "2026-10-31.json")[0] is None
    assert pulse.date_of("notes.json") is None


def _book(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    seed.load_companies(path)
    folder = tmp_path / "pulse"
    folder.mkdir()
    shutil.copy(FIXTURES / "2026-10-30.json", folder)
    return path, folder


def _run(path, folder):
    fetcher = PulseNewsFetcher(path, folder=folder, today=TODAY)
    rows = fetcher.normalise(fetcher.fetch())
    return fetcher.upsert(rows)


def test_every_item_reaches_news_and_universe_ones_reach_the_feed(tmp_path):
    path, folder = _book(tmp_path)
    result = _run(path, folder)
    assert result.rows_fetched == 5 and result.errors == []
    assert result.notes == ["2026-10-30.json item 4: no headline or no link"]
    conn = db.get_connection(path)
    news = {r["url"].rsplit("/", 1)[1]: r["ticker"] for r in conn.execute(
        "SELECT n.url, c.ticker FROM news n LEFT JOIN companies c ON c.id = n.company_id"
        " WHERE n.source = 'pulse'")}
    # Private rounds and companies outside the universe stay in, with no company.
    assert news == {"lilly-testco": "LLY", "roche-regeneron": "ROG", "merck-kgaa": None,
                    "privateco": None, "vertex": "VRTX"}
    # Merck KGaA is not Merck & Co: names are matched whole.
    changes = sorted((r["entity_key"].split("|")[0], r["change_type"], r["significance"])
                     for r in conn.execute("SELECT * FROM changes"))
    assert changes == [("LLY", "pulse_deal", "high"), ("REGN", "pulse_deal", "medium"),
                       ("ROG", "pulse_deal", "medium"), ("VRTX", "pulse_other", "low")]
    assert materiality.change_reason("pulse_deal") == "daily pulse (AI summary), deal"
    # The same file read again adds nothing.
    assert _run(path, folder).rows_fetched == 0
    assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 4


def test_an_old_briefing_reaches_news_but_not_the_feed(tmp_path):
    path, folder = _book(tmp_path)
    fetcher = PulseNewsFetcher(path, folder=folder, today=TODAY + dt.timedelta(days=30))
    fetcher.upsert(fetcher.normalise(fetcher.fetch()))
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM news WHERE source = 'pulse'").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0


def test_a_changed_file_is_read_again_and_updates_its_items(tmp_path):
    path, folder = _book(tmp_path)
    _run(path, folder)
    payload = _payload()
    payload["items"][0]["tier"] = 2
    (folder / "2026-10-30.json").write_text(json.dumps(payload))
    assert _run(path, folder).rows_fetched == 0             # updated, not new
    conn = db.get_connection(path)
    assert conn.execute("SELECT tier FROM pulse_items WHERE url LIKE '%lilly-testco'"
                        ).fetchone()[0] == 2


def test_the_sector_feed_and_both_companies_of_a_deal(tmp_path, monkeypatch):
    path, folder = _book(tmp_path)
    _run(path, folder)
    monkeypatch.setattr(db, "DB_PATH", path)
    client = TestClient(main.app)
    got = client.get("/pulse?days=100000").json()
    assert got["label"] == "Daily pulse (AI summary)"
    assert got["reads"][0]["read"].startswith("A test briefing")
    assert [i["tier"] for i in got["items"]] == [1, 2, 2, 3, None]
    assert got["items"][1]["tickers"] == ["ROG", "REGN"]
    assert got["items"][3]["companies"] == ["Privateco"]
    # Regeneron is the second company of a deal stored under Roche, and still sees it.
    regn = client.get("/companies/REGN/news").json()["news"]
    assert [n["url"] for n in regn if n["source"] == "pulse"] == [
        "https://news.example.com/roche-regeneron"]
    rog = client.get("/companies/ROG/news").json()["news"]
    assert sum(n["url"].endswith("roche-regeneron") for n in rog) == 1


def test_what_changed_prints_the_item_as_written_and_dated_by_its_article(tmp_path,
                                                                          monkeypatch):
    path, folder = _book(tmp_path)
    _run(path, folder)
    monkeypatch.setattr(db, "DB_PATH", path)
    feed = TestClient(main.app).get("/changes").json()
    lilly = next(i for i in feed if i.get("change_type") == "pulse_deal"
                 and i["ticker"] == "LLY")
    assert lilly["headline"] == "LLY Lilly agrees to buy Testco Bio for $2.1bn"
    assert lilly["reason"] == "daily pulse (AI summary), deal"
    assert lilly["date"].startswith("2026-10-29")
    regn = next(i for i in feed if i.get("change_type") == "pulse_deal"
                and i["ticker"] == "REGN")
    assert regn["date"].startswith("2026-10-29")


def test_the_panel_names_its_source_and_folds_older_briefings():
    import ast
    import html
    import re
    import sys
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "frontend"))
    app = root / "frontend" / "streamlit_app.py"
    tree = ast.parse(app.read_text(), feature_version=(3, 9))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in ("_pulse_html", "html_escape"))
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_PULSE_TIERS" for t in n.targets))]
    space = {"html": html, "re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(app), "exec"), space)
    got = {"reads": [{"pulse_date": "2026-10-30", "read": "Risk-on & <busy>."}],
           "items": [
               {"pulse_date": "2026-10-30", "tier": 1, "kind": "deal",
                "headline": "Lilly agrees to buy Testco", "detail": "$1.5bn upfront",
                "url": "https://news.example.com/a", "tickers": ["LLY"],
                "companies": ["Eli Lilly", "Testco"]},
               {"pulse_date": "2026-10-30", "tier": 3, "kind": "financing",
                "headline": "Privateco raises $120m", "detail": None,
                "url": "https://news.example.com/b", "tickers": [],
                "companies": ["Privateco"]},
               {"pulse_date": "2026-10-29", "tier": 2, "kind": "other",
                "headline": "Older item", "url": "https://news.example.com/c",
                "tickers": [], "companies": []}]}
    markup = space["_pulse_html"](got)
    assert "Risk-on &amp; &lt;busy&gt;." in markup
    assert 'href="https://news.example.com/a"' in markup and ">T1<" in markup
    # A private round with no covered company still shows, under its own name.
    assert "Privateco raises $120m" in markup and ">Privateco · financing<" in markup
    # The older briefing is folded.
    assert '<details class="pt-more"><summary>2026-10-29 · 1 item<' in markup
    assert space["_pulse_html"]({"items": []}) == ""
