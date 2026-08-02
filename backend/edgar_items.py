"""The 8-K item taxonomy, which is what makes a material event readable.

EDGAR's submissions feed carries an ``items`` field on every 8-K: a comma separated
list of item numbers saying what the filing is actually about. The fetcher was throwing
it away, so every filing stored the title "8-K" and the feed read "LLY 8-K: 8-K", which
tells an analyst nothing.

The numbering is the SEC's own, from Form 8-K General Instruction B. Anything not listed
keeps its bare number rather than being guessed at.
"""

from __future__ import annotations

ITEMS: dict = {
    "1.01": "Material agreement signed",
    "1.02": "Material agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.05": "Material cybersecurity incident",
    "2.01": "Acquisition or disposition completed",
    "2.02": "Results of operations",
    "2.03": "Direct financial obligation created",
    "2.04": "Obligation accelerated",
    "2.05": "Exit or disposal costs",
    "2.06": "Material impairment",
    "3.01": "Delisting notice",
    "3.02": "Unregistered equity sold",
    "3.03": "Security holder rights modified",
    "4.01": "Auditor changed",
    "4.02": "Prior financials no longer reliable",
    "5.01": "Change in control",
    "5.02": "Director or officer change",
    "5.03": "Charter or bylaws amended",
    "5.05": "Code of ethics amended",
    "5.07": "Shareholder vote",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits",
}

# Items that move an investment case rather than housekeeping. A completed acquisition,
# a signed material agreement, or a change in control is the M&A signal an analyst
# wants surfaced; an impairment or an exit charge is the same news in reverse.
MATERIAL = frozenset({"1.01", "1.02", "1.03", "2.01", "2.05", "2.06", "3.01",
                      "4.02", "5.01"})

# Exhibits, vote administration, and Regulation FD say nothing on their own, so they
# never lead a headline when something substantive is filed alongside them. Reg FD is a
# disclosure mechanism rather than an event type: it says how, not what.
ROUTINE = frozenset({"9.01", "5.07", "5.03", "5.05", "7.01"})

# A headline naming four items is unreadable. Three is enough to say what happened; the
# count tells the reader there is more in the filing itself.
MAX_LABELS = 3


def parse(items) -> list:
    """Split EDGAR's comma separated item string into codes."""
    if not items:
        return []
    if isinstance(items, (list, tuple)):
        parts = items
    else:
        parts = str(items).split(",")
    return [p.strip() for p in parts if p and p.strip()]


def describe(items, form_type: str = "8-K") -> str:
    """A readable title for a filing, built from its item codes.

    Substantive items lead. When a filing carries only routine ones, those are used
    rather than inventing a description, and a filing with no items at all keeps its
    form type, which is all EDGAR gave us.
    """
    codes = parse(items)
    if not codes:
        return form_type
    substantive = [c for c in codes if c not in ROUTINE]
    chosen = substantive or codes
    labels = []
    for code in chosen:
        label = ITEMS.get(code) or f"Item {code}"
        if label not in labels:
            labels.append(label)
    if not labels:
        return form_type
    if len(labels) > MAX_LABELS:
        return ", ".join(labels[:MAX_LABELS]) + f", and {len(labels) - MAX_LABELS} more"
    return ", ".join(labels)


def is_material(items) -> bool:
    """True when a filing carries an item that moves the investment case."""
    return any(code in MATERIAL for code in parse(items))


MATERIAL_LABELS = tuple(ITEMS[code] for code in sorted(MATERIAL) if code in ITEMS)


RESULTS = "2.02"


def reports_results(title: str) -> bool:
    """Whether a stored filing title includes the results item.

    Item 2.02 is the earnings release, and its exhibit is the densest document a company
    files: the quarter's cash, its burn, its product revenue and what it says about the
    launch, all in one place and months before the equivalent 10-Q figures are tagged.
    """
    return ITEMS[RESULTS].lower() in (title or "").lower()


def is_material_title(title: str) -> bool:
    """Same judgement, read back off a stored title.

    The filings table keeps the description rather than the raw codes, so the diff
    engine recovers materiality from the words it wrote.
    """
    return any(label in (title or "") for label in MATERIAL_LABELS)
