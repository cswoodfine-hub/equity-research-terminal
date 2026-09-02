import pytest


def test_an_exhibit_is_found_by_the_type_the_index_page_states():
    """Lilly names its release "q226lillysalesandearningsp.htm", with no "ex99" in it,
    and the name matcher missed every one. The filing's index page types it EX-99.1."""
    from fetchers.filing_text_edgar import exhibits_from_index
    page = (
        '<table class="tableFile"><tr><th>Seq</th><th>Description</th><th>Document</th>'
        '<th>Type</th><th>Size</th></tr>'
        '<tr><td scope="row">1</td><td scope="row">8-K</td><td scope="row">'
        '<a href="/ix?doc=/Archives/edgar/data/59478/000005947826000077/lly-20260805.htm">'
        'lly-20260805.htm</a> &nbsp;&nbsp;<span style="color: green">iXBRL</span></td>'
        '<td scope="row">8-K</td><td scope="row">47310</td></tr>'
        '<tr class="evenRow"><td scope="row">2</td><td scope="row">EX-99.1</td><td scope="row">'
        '<a href="/Archives/edgar/data/59478/000005947826000077/q226lillysalesandearningsp.htm">'
        'q226lillysalesandearningsp.htm</a></td><td scope="row">EX-99.1</td><td scope="row">219998</td></tr>'
        '<tr><td scope="row">7</td><td scope="row"></td><td scope="row">'
        '<a href="/Archives/edgar/data/59478/000005947826000077/logoa31a.jpg">logoa31a.jpg</a></td>'
        '<td scope="row">GRAPHIC</td><td scope="row">14287</td></tr></table>')
    assert exhibits_from_index(page) == [
        "/Archives/edgar/data/59478/000005947826000077/q226lillysalesandearningsp.htm"]
