"""The scraped route, for the companies that publish no feed.

The fixtures are three real listings as Jina renders them, chosen because they agree on
nothing: Johnson & Johnson puts the date on the list line and the headline on the next,
Merck links the date and the headline separately to the same url, and Roche puts the
headline first with the date under it and lists a German copy of every release. All three
have to come out as the same thing.
"""

import pathlib

import db
import press_pages
from fetchers.press_page import PressPageFetcher

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
JNJ = (FIXTURES / "ir_page_jnj.md").read_text()
MRK = (FIXTURES / "ir_page_mrk.md").read_text()
ROG = (FIXTURES / "ir_page_rog.md").read_text()

JNJ_URL = "https://www.jnj.com/media-center/press-releases"
MRK_URL = "https://www.merck.com/media/news/"
ROG_URL = "https://www.roche.com/media/releases"


# --- reading a listing -----------------------------------------------------

def test_every_layout_yields_release_urls():
    for md, listing in ((JNJ, JNJ_URL), (MRK, MRK_URL), (ROG, ROG_URL)):
        urls = press_pages.release_urls(md, listing)
        assert len(urls) >= 8
        assert all(u.startswith("https://") for u in urls)


def test_a_section_link_is_not_a_release():
    """Johnson & Johnson tags each release with its category, so
    /media-center/press-releases/corporate sits beside the releases and is a section. It
    is told apart by its slug: one word, where a release has several."""
    urls = press_pages.release_urls(JNJ, JNJ_URL)
    assert f"{JNJ_URL}/corporate" not in urls
    assert f"{JNJ_URL}/innovative-medicine" not in urls


def test_a_sibling_section_is_not_a_release():
    """Merck lists /news/<slug> from a page at /media/news/, so a rule keyed on any
    shared path segment lets /media/company-fact-sheet/ through on the strength of
    "media". The listing's own last segment is what a release has to carry."""
    urls = press_pages.release_urls(MRK, MRK_URL)
    assert "https://www.merck.com/media/company-fact-sheet/" not in urls
    assert any("/news/merck-announces-fourth-quarter-2026-dividend" in u for u in urls)


def test_a_headline_with_a_bracket_in_it_is_not_lost():
    """Roche titles one "[Ad hoc announcement pursuant to Art. 53 LR] Roche's strong
    momentum continues", and a pattern that has to cross the link text drops it."""
    urls = press_pages.release_urls(ROG, ROG_URL)
    assert "https://www.roche.com/media/releases/med-cor-2026-07-23" in urls


def test_the_same_release_in_another_language_is_the_same_release():
    """Roche lists a DE link beside every English one, pointing at the same slug under
    /de/. Counted twice it would be two of everything."""
    urls = press_pages.release_urls(ROG, ROG_URL)
    assert not any("/de/" in u for u in urls)
    assert len(urls) == len(set(urls))


def test_another_hosts_links_are_left_alone():
    """The listings carry image CDNs, social buttons and a cookie vendor."""
    for md, listing in ((JNJ, JNJ_URL), (MRK, MRK_URL), (ROG, ROG_URL)):
        host = listing.split("/")[2]
        assert all(u.split("/")[2] == host
                   for u in press_pages.release_urls(md, listing))


# --- reading a release -----------------------------------------------------

PAGE = """Title: FDA grants Priority Review to Roche's Gazyva for membranous nephropathy
URL Source: https://www.roche.com/media/releases/med-cor-2026-07-15
Published Time: 2026-07-15T06:00:00+00:00

Markdown Content:
The submission is based on phase III MAJESTY results.
"""


def test_a_release_gives_its_headline_and_its_date():
    got = press_pages.release(PAGE)
    assert got["title"].startswith("FDA grants Priority Review")
    assert got["published"] == "2026-07-15"


def test_the_site_name_is_taken_off_the_tab_title():
    got = press_pages.release("Title: Press releases | GSK\n\nMarkdown Content:\n")
    assert got["title"] == "Press releases"


def test_a_hyphen_is_left_alone():
    """Stripping on a hyphen the way a pipe is stripped turns "Merck Announces
    Fourth-Quarter 2026 Dividend" into "Merck Announces Fourth"."""
    got = press_pages.release("Title: Merck Announces Fourth-Quarter 2026 Dividend\n")
    assert got["title"] == "Merck Announces Fourth-Quarter 2026 Dividend"


def test_a_release_with_no_date_keeps_none():
    """The day it was published is the fact. The day it was read is not, and filling the
    gap with today would date a 2019 release to this morning."""
    got = press_pages.release("Title: Something happened\n\nMarkdown Content:\n")
    assert got["published"] is None


def test_a_page_with_no_title_is_refused():
    """What a consent wall or an error page renders as."""
    assert press_pages.release("Markdown Content:\n\nAccess denied") is None
    assert press_pages.release("") is None


# --- the fetcher -----------------------------------------------------------

def _fetcher(tmp_path, monkeypatch, listing=ROG_URL, pages=None):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name, ir_news_url)"
                 " VALUES ('ROG', 'Roche', ?)", (listing,))
    conn.commit(); conn.close()
    pages = pages if pages is not None else {}

    def read(url, timeout=None):
        if url == listing:
            return ROG
        if url in pages:
            return pages[url]
        return (f"Title: Release {url.rsplit('/', 1)[-1]}\n"
                f"Published Time: 2026-07-15T06:00:00+00:00\n\nMarkdown Content:\n")

    monkeypatch.setattr("fetchers.press_page._read", read)
    monkeypatch.setattr("fetchers.press_page.time.sleep", lambda s: None)
    return PressPageFetcher("ROG", db_path=path), path


def _rows(path, sql, args=()):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def test_the_releases_land_as_news(tmp_path, monkeypatch):
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    result = fetcher.run()
    assert result.errors == []
    news = _rows(path, "SELECT title, url, published_at, source FROM news")
    assert news
    assert {n["source"] for n in news} == {"press_page"}
    assert all(n["published_at"] == "2026-07-15" for n in news)


def test_a_run_pays_only_for_what_is_new(tmp_path, monkeypatch):
    """Each release costs a request, and the free tier allows about twenty a minute. A
    second run over an unchanged listing must fetch none of them."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    fetcher.run()
    seen = []
    listing = ROG_URL

    def read(url, timeout=None):
        seen.append(url)
        if url == listing:
            return ROG
        return "Title: x\n"

    monkeypatch.setattr("fetchers.press_page._read", read)
    again = PressPageFetcher("ROG", db_path=path)
    again.force = True
    assert again.run().rows_fetched == 0
    assert seen == [listing]        # the listing, and not one release


def test_the_number_read_per_run_is_capped(tmp_path, monkeypatch):
    from fetchers import press_page
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    fetcher.run()
    assert len(_rows(path, "SELECT id FROM news")) <= press_page.MAX_RELEASES


def test_one_bad_release_does_not_lose_the_others(tmp_path, monkeypatch):
    listing = ROG_URL
    urls = press_pages.release_urls(ROG, listing)

    def read(url, timeout=None):
        if url == listing:
            return ROG
        if url == urls[1]:
            raise OSError("HTTP Error 422: Unprocessable Entity")
        return f"Title: Release {url.rsplit('/', 1)[-1]}\n"

    fetcher, path = _fetcher(tmp_path, monkeypatch)
    monkeypatch.setattr("fetchers.press_page._read", read)
    result = fetcher.run()
    assert result.rows_fetched >= 5
    assert any("422" in e for e in result.errors)


def test_a_listing_that_matches_nothing_says_so(tmp_path, monkeypatch):
    """Nine of the fourteen pages draw their list with script, and Jina returns a
    navigation bar. That is a failure and it never raises, so it has to be spoken."""
    fetcher, path = _fetcher(tmp_path, monkeypatch)
    monkeypatch.setattr("fetchers.press_page._read",
                        lambda url, timeout=None: "Title: Press releases\n\n[Home](/)")
    result = fetcher.run()
    assert result.rows_fetched == 0
    assert result.errors == []
    assert "listed no releases" in " ".join(result.notes)


def test_a_company_with_no_page_reports_nothing_and_fails_nothing(tmp_path, monkeypatch):
    fetcher, path = _fetcher(tmp_path, monkeypatch, listing="")
    result = fetcher.run()
    assert result.errors == []
    assert result.rows_fetched == 0
    assert "no IR page" in " ".join(result.notes)
