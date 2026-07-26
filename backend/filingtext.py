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


def html_to_text(source: str) -> str:
    """Readable text from an EDGAR HTML document. Block tags become line breaks so the
    paragraph structure survives; inline XBRL and scripts are dropped."""
    text = _DROP.sub(" ", source or "")
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = _html.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


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
