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
