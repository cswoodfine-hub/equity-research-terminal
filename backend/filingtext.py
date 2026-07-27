"""Filing text diff, the qualitative counterpart to the numeric change engine.

The numbers in a 10-K change on their own schedule; the words change once a year and say
what management is worried about. A new risk factor, or a rewritten one, is a real
signal and there is no structured field for it. This module pulls two sections out of a
filing, Risk Factors and Management's Discussion, and measures what moved between one
filing and the last of the same form.

It is the pure half: HTML to text, the two sections out of that text, and a
paragraph-level diff. The download and the change write live in the fetcher and the diff
engine. Nothing here needs a model; the diff is structural, and a model summary is a
later, optional layer.

Section extraction is the hard part. A 10-K names each section twice, once in the table
of contents and once for real, so every candidate start is tried and the longest run of
text wins, which is the real section rather than the one-line contents entry. The item
numbers differ by form (Risk Factors is Item 1A in both, MD&A is Item 7 in a 10-K and
Item 2 in a 10-Q), so the patterns allow either.
"""

from __future__ import annotations

import difflib
import html as _html
import re

_DROP = re.compile(r"(?is)<(script|style|ix:header)\b[^>]*>.*?</\1>")
_BLOCK = re.compile(r"(?i)</(p|div|tr|h[1-6]|li)\s*>|<br\s*/?>")
_TAG = re.compile(r"(?s)<[^>]+>")

RISK_START = re.compile(r"item\s*1a\b[.:\s\-]{0,12}risk\s+factors", re.I)
RISK_END = re.compile(r"item\s*1b\b|unresolved\s+staff\s+comments", re.I)
MDNA_START = re.compile(
    r"item\s*[27]\b[.:\s\-]{0,12}management.{0,3}s\s+discussion\s+and\s+analysis", re.I)
# The next section's own title, not an item number: a 10-K's MD&A prose cross-references
# Item 8 and Item 1A many times, so ending on "item 8" cut it off at the first mention.
# "Quantitative and Qualitative Disclosures" is Item 7A in a 10-K and Item 3 in a 10-Q,
# and reads only as that heading, so it ends the section where it actually ends.
MDNA_END = re.compile(r"quantitative\s+and\s+qualitative\s+disclosures", re.I)

SECTIONS = ("risk_factors", "mdna")

# A 20-F is the foreign filer's annual report and is not laid out like a 10-K. Its risk
# factors are Item 3.D and its financial review is Item 5, but the item numbers alone are
# not enough: AstraZeneca's Item 5 is four pages of cross-references and the review it
# points at sits later in the same document, incorporated from the annual report. So the
# financial review is kept whole rather than cut to an item span, and the reader that
# wants the revenue table finds it by its own anchors.
RISK_START_20F = re.compile(
    r"item\s*3\.?\s*d\b[.:\s\-]{0,12}risk\s+factors|\brisk\s+factors\b", re.I)
RISK_END_20F = re.compile(
    r"item\s*4\b[.:\s\-]{0,12}information\s+on\s+the\s+company", re.I)
SECTIONS_20F = ("risk_factors", "financial_review")
FINANCIAL_REVIEW_MAX = 700_000

# A drug's patent cliff is rarely a clean section: companies scatter it through Item 1's
# patent discussion, a patent table, and MD&A, by brand or by generic name. Rather than
# find a section, harvest every line that pairs patent, exclusivity or biosimilar
# language with a future year, which is where a stated cliff lives wherever it sits.
_PATENT_LINE = re.compile(r"patent|exclusivit|biosimilar", re.I)
_FUTURE_YEAR = re.compile(r"\b20(2[5-9]|[34]\d)\b")


def patent_passages(text: str, max_chars: int = 40000) -> str:
    """The lines of a filing that state a patent or exclusivity year, harvested from the
    whole document and joined. Bounded, so a long patent table cannot crowd out the rest.
    Empty when the filing states none."""
    out, size = [], 0
    for line in (text or "").split("\n"):
        norm = re.sub(r"\s+", " ", line).strip()
        if len(norm) < 40 or not _PATENT_LINE.search(norm) or not _FUTURE_YEAR.search(norm):
            continue
        out.append(norm)
        size += len(norm) + 1
        if size >= max_chars:
            break
    return "\n".join(out)


# Zero-width spaces and joiners, which a filer's HTML puts between the digits of a
# table. AstraZeneca's 20-F carries sixteen thousand of them, and they are invisible in
# the text and fatal to any pattern that expects a number followed by whitespace.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff\u00ad]")


def html_to_text(source: str) -> str:
    """Readable text from an EDGAR HTML document. Block tags become line breaks so the
    paragraph structure survives; inline XBRL and scripts are dropped."""
    text = _INVISIBLE.sub("", source or "")
    text = _DROP.sub(" ", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = _html.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_20f_sections(text: str) -> dict:
    """A 20-F's risk factors, and its financial review kept whole.

    Whole because the item span does not hold it: the review a foreign filer's Item 5
    points to is printed further down the same document, and cutting at Item 6 throws
    the revenue table away with it.
    """
    return {
        "risk_factors": _longest_span(text, RISK_START_20F, RISK_END_20F),
        "financial_review": (text or "")[:FINANCIAL_REVIEW_MAX],
    }


def extract_sections(text: str) -> dict:
    """The two tracked sections, each the longest run of text that follows its header."""
    return {
        "risk_factors": _longest_span(text, RISK_START, RISK_END),
        "mdna": _longest_span(text, MDNA_START, MDNA_END),
    }


def _longest_span(text: str, start_re: re.Pattern, end_re: re.Pattern) -> str:
    best = ""
    for match in start_re.finditer(text or ""):
        rest = text[match.end():]
        end = end_re.search(rest)
        chunk = rest[: end.start()] if end else rest
        if len(chunk) > len(best):
            best = chunk
    return best.strip()


def _paragraphs(text: str) -> list[str]:
    """Comparable paragraphs: real sentences of prose, whitespace normalised so spacing
    and stray page numbers do not read as changes, case kept so the passage is readable.
    Short lines, which are headings and page furniture, are dropped."""
    out = []
    for line in (text or "").split("\n"):
        norm = re.sub(r"\s+", " ", line).strip()
        if len(norm) >= 60:                    # a sentence, not a heading or a number
            out.append(norm)
    return out


def diff_sections(prior_text: str, current_text: str, max_passages: int = 8) -> dict:
    """What moved between two versions of a section: the count of paragraphs added and
    removed, a similarity ratio, and the passages themselves for review. A reworded
    paragraph reads as one of each, which is the honest reading of a structural diff."""
    prior, current = _paragraphs(prior_text), _paragraphs(current_text)
    matcher = difflib.SequenceMatcher(None, prior, current, autojunk=False)
    added = removed = 0
    added_passages, removed_passages = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added += j2 - j1
            added_passages.extend(current[j1:j2])
        if tag in ("delete", "replace"):
            removed += i2 - i1
            removed_passages.extend(prior[i1:i2])
    return {"added": added, "removed": removed,
            "ratio": round(matcher.ratio(), 4),
            "changed": added > 0 or removed > 0,
            "prior_paragraphs": len(prior), "current_paragraphs": len(current),
            "added_passages": added_passages[:max_passages],
            "removed_passages": removed_passages[:max_passages]}
