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


# --- current reports -------------------------------------------------------------------

# The shape of every 8-K: a page and a half of cover boilerplate, then the items.
EIGHT_K = """8-K
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 8-K
CURRENT REPORT
Check the appropriate box below if the Form 8-K filing is intended to simultaneously
satisfy the filing obligation of the registrant under any of the following provisions:
Item 2.02 Results of Operations and Financial Condition.
On July 29, 2026, Dyne Therapeutics, Inc. issued a press release announcing the
Company's financial results for the quarter ended June 30, 2026. A copy of the press
release is furnished as Exhibit 99.1 to this Current Report on Form 8-K.
Item 9.01 Financial Statements and Exhibits.
"""


def test_a_current_report_starts_at_its_first_item():
    body = filingtext.extract_current_report(EIGHT_K)["body"]
    assert body.startswith("Item 2.02")
    assert "Check the appropriate box" not in body


def test_a_current_report_with_no_item_heading_is_kept_whole():
    """A 6-K is a furnished press release with no item structure at all."""
    text = "Roche reports strong first-half sales growth of 7% at constant exchange rates."
    assert filingtext.extract_current_report(text)["body"] == text


def test_a_current_report_is_bounded():
    body = filingtext.extract_current_report("Item 1.01 x" + "y" * 400_000)["body"]
    assert len(body) == filingtext.CURRENT_REPORT_MAX
