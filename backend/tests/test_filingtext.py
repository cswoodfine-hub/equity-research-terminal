"""Filing text: HTML to text, the two sections out of a document, and the paragraph
diff. Pure, no network."""

from pathlib import Path

import filingtext

_HTML = (Path(__file__).resolve().parent / "fixtures" / "filing_10k.html").read_text()


def test_html_to_text_strips_tags_and_keeps_lines():
    text = filingtext.html_to_text("<div>One</div><p>Two</p>")
    assert "One" in text and "Two" in text and "<" not in text


def test_extract_sections_skips_the_contents_and_takes_the_real_section():
    sections = filingtext.extract_sections(filingtext.html_to_text(_HTML))
    risk = sections["risk_factors"]
    mdna = sections["mdna"]
    # The real risk factors section, not the one-line table of contents entry.
    assert "carefully consider the following risks" in risk
    assert "patent protection" in risk
    assert "Unresolved Staff Comments" not in risk       # ended at the next item
    assert "discussion and analysis of the financial condition" in mdna
    assert "market risk" not in mdna                      # ended before Item 7A


def test_diff_sections_counts_and_returns_added_passages():
    prior = ("The company depends on a small number of products for most revenue.\n"
             "Patent expiration would allow generic competition and reduce revenue.")
    current = ("The company depends on a small number of products for most revenue.\n"
               "Patent expiration would allow generic competition and reduce revenue.\n"
               "A new government pricing law could materially lower the prices we charge.")
    diff = filingtext.diff_sections(prior, current)
    assert diff["added"] == 1 and diff["removed"] == 0 and diff["changed"] is True
    assert "government pricing law" in diff["added_passages"][0]


def test_diff_sections_no_change_reads_flat():
    text = "The company depends on a small number of products for most of its revenue."
    diff = filingtext.diff_sections(text, text)
    assert diff["changed"] is False and diff["added"] == 0 and diff["ratio"] == 1.0


def test_patent_passages_harvests_only_dated_patent_lines():
    text = (
        "This is an ordinary sentence about the business that mentions no dates at all.\n"
        "Patents covering pembrolizumab in the United States expire in 2032, we believe.\n"
        "Our regulatory exclusivity for the product runs through 2029 in the US market.\n"
        "The company was founded many years ago and employs thousands of people today.\n"
        "A biosimilar competitor launched in 2019, well before the period covered here.\n")
    passages = filingtext.patent_passages(text)
    lines = passages.split("\n")
    assert any("pembrolizumab" in ln and "2032" in ln for ln in lines)
    assert any("regulatory exclusivity" in ln and "2029" in ln for ln in lines)
    # A line with no future year and one that is just prose are both left out.
    assert not any("founded many years ago" in ln for ln in lines)
    assert not any("launched in 2019" in ln for ln in lines)   # 2019 is not a future year
