"""What a deal actually pays, out of the sentence that says so.

A deal captured from a headline is a fact with no size: "Johnson & Johnson Announces
Collaboration with Sail Biomedicines" tells a reader that something happened and nothing
about whether it matters. The press release furnished with the same day's 8-K says:

    Under the terms of the agreements, Johnson & Johnson would make total initial payments
    of $785 million, including a $465 million equity investment, and additional contingent
    payments of $140 million if certain development milestones are achieved. Subject to
    Johnson & Johnson's decision to exercise the option, Johnson & Johnson would make an
    additional payment of $2.58 billion.

Four figures, four different meanings, and a single "value" field flattens them into one
number that is wrong whichever one it picks. 785m is what is being spent now, of which
465m buys equity rather than rights; 140m is contingent on data; 2.58bn only happens if
the option is exercised. An analyst reads those as four different commitments.

So each figure is labelled by the words around it rather than by its position. Pharma
business development writes these sentences to a formula, which is what makes the labels
readable: upfront, equity, milestone, option. Nothing is computed and nothing is summed:
where the text says a total that is the total, and where it does not there is none. The
485m inside the 785m is not double counting, it is what the filing says, and the display
has to say it the same way.

Rules only, no model. The deal classifier upstream uses one where a key is present; this
runs whatever is configured, because a number in a press release does not need inference.
"""

from __future__ import annotations

import re

_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9,
          "million": 1e6, "mn": 1e6, "m": 1e6}
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|bn|b|million|mn|m)\b", re.I)

# What a figure is for, judged by the phrase nearest to it. Ordered most specific first,
# because "an option to acquire Sail for $2.58 billion" contains the word "acquire" and is
# not an acquisition price, and a milestone payment is a payment.
ROLES = (
    ("option", (r"option to (?:acquire|purchase|buy)",
                r"exercis\w*\s+(?:of\s+)?(?:the|its)\s+option",
                r"subject to .{0,40}option")),
    ("equity", (r"equity investment", r"equity stake", r"equity financing",
                r"purchase .{0,40}\bshares\b", r"invest\w* .{0,20}\bequity\b")),
    ("milestones", (r"milestone", r"contingent payment", r"earn[- ]?out",
                    r"upon (?:the )?achievement")),
    ("upfront", (r"upfront", r"up[- ]front", r"initial payment", r"total initial",
                 r"payable (?:at|upon) clos", r"cash payment")),
    # The plain price of a company bought outright: "for $1 billion in cash". No bare
    # "for $" pattern, because "an option to acquire Sail for $2.58 billion" also reads
    # that way and the option is the more specific fact about the same figure.
    ("total", (r"\bin cash\b", r"purchase price", r"transaction valued at",
               r"all[- ]cash", r"cash consideration", r"acquisition price")),
)

# How far from a figure a role phrase can sit and still describe it. One clause.
WINDOW = 90

# A figure that is not a deal term. Per-share prices are the price of a share, not the
# size of the deal, and a market capitalisation or a revenue figure in the same release
# is background.
_NOT_A_TERM = re.compile(
    r"per share|per[- ]diluted|earnings per|revenue|net income|market cap|"
    r"annual sales|peak sales|in \d{4} (?:revenue|sales)", re.I)

FIELDS = ("upfront", "equity", "milestones", "option", "total")

# The words a filing uses when it is stating the whole size of the deal at once.
_TOTAL = re.compile(r"total (?:deal |transaction |consideration )?value|"
                    r"total potential (?:value|consideration)|"
                    r"aggregate (?:consideration|value)|"
                    r"up to \$", re.I)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _figures(body: str) -> list:
    """Every money figure in the text, with its position, minus the ones that are not
    deal terms. A price per share is the price of a share, and the test is tight against
    the figure rather than the clause: "at $72.50 per share, valuing the transaction at
    $4.9 billion" states one of each, and a loose test threw away both."""
    out = []
    for match in _MONEY.finditer(body):
        if _NOT_A_TERM.search(body[match.end(): match.end() + 24]):
            continue
        amount = float(match.group(1).replace(",", "")) * _SCALE[match.group(2).lower()]
        out.append((match.start(), amount))
    return out


# Where one commitment ends and the next begins. A press release states them in a list,
# and the clause is what keeps a role word with its own figure: in "we will pay $50
# million upfront and up to $450 million in milestones", "upfront" is eleven characters
# from the wrong figure and twelve from the right one, so distance alone cannot decide it
# and the comma can.
_CLAUSE = re.compile(r",|;|\band\b|\bplus\b|\bincluding\b", re.I)


def _clause_spans(body: str) -> list:
    """(start, end) of each clause, in order."""
    spans, start = [], 0
    for match in _CLAUSE.finditer(body):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(body)))
    return spans


def _bind(body: str, figures: list) -> list:
    """(role, distance, position, amount) for each role phrase and the figure it describes.

    Read from the phrase to the figure, and within one clause first. A role phrase
    describes one amount; reading it the other way round let a word already spoken for
    claim a second figure. Where a phrase's own clause holds no figure it falls back to the
    nearest anywhere in range, which is what "commercial milestones." trailing its clause
    needs.
    """
    bound = []
    clauses = _clause_spans(body)
    for name, patterns in ROLES:
        for pattern in patterns:
            for match in re.finditer(pattern, body, re.I):
                clause = next((c for c in clauses
                               if c[0] <= match.start() < c[1]), (0, len(body)))
                for scope in (clause, (0, len(body))):
                    nearest, distance = None, None
                    for position, amount in figures:
                        if not scope[0] <= position < scope[1]:
                            continue
                        gap = (match.start() - position if position < match.start()
                               else position - match.end())
                        if abs(gap) <= WINDOW and (distance is None or abs(gap) < distance):
                            nearest, distance = (position, amount), abs(gap)
                    if nearest:
                        bound.append((name, distance, nearest[0], nearest[1]))
                        break
    return bound


def parse(text: str) -> dict:
    """{upfront, equity, milestones, option, total, evidence} in USD, any of them None.

    ``evidence`` is the sentence the figures were read from, so a reader who does not
    believe "465m of the 785m is equity" can see the clause that said it.
    """
    out = {field: None for field in FIELDS}
    out["evidence"] = None
    body = _clean(text)
    if not body:
        return out

    figures = _figures(body)
    # Nearest binding first, so where two role words reach the same figure the closer one
    # owns it: "additional contingent payments of $140 million if certain development
    # milestones are achieved" is one amount described twice.
    claimed: dict = {}
    for name, distance, position, amount in sorted(_bind(body, figures),
                                                   key=lambda b: b[1]):
        claimed.setdefault(position, (name, amount))

    for position, (name, amount) in claimed.items():
        # The largest statement of each role wins. A release states the option price twice,
        # once in the bullets and once in the terms, and a milestone total often appears
        # after a smaller near-term figure.
        if out[name] is None or amount > out[name]:
            out[name] = amount
            if out["evidence"] is None or name in ("upfront", "total"):
                out["evidence"] = _terms_sentence(body, position) or out["evidence"]

    # A figure no role word reached is the headline size where the sentence frames it as
    # one, and otherwise is some other number in the release.
    for position, amount in figures:
        if position in claimed:
            continue
        around = body[max(0, position - WINDOW): position + WINDOW]
        if _TOTAL.search(around) and (out["total"] is None or amount > out["total"]):
            out["total"] = amount
            out["evidence"] = out["evidence"] or _terms_sentence(body, position)
    return out


def _terms_sentence(body: str, at: int) -> str | None:
    """The sentence a figure sits in."""
    start = body.rfind(". ", 0, at)
    end = body.find(". ", at)
    return body[(start + 2) if start >= 0 else 0: end + 1 if end >= 0 else len(body)].strip()


def headline(terms: dict) -> float | None:
    """The one number that best states the size, for sorting and for a one-line summary.

    The option price where there is one, because that is what the deal is worth if it
    runs; otherwise the stated total; otherwise what is being paid now plus what is
    contingent, which is the "up to" figure a press release would print.
    """
    if terms.get("option"):
        return terms["option"]
    if terms.get("total"):
        return terms["total"]
    parts = [terms.get("upfront"), terms.get("milestones")]
    stated = [p for p in parts if p]
    return sum(stated) if stated else None


def summary(terms: dict) -> str:
    """The structure in one line, in the order an analyst reads it."""
    def money(value):
        if value >= 1e9:
            return f"${value / 1e9:.2f}".rstrip("0").rstrip(".") + "bn"
        return f"${value / 1e6:,.0f}m"

    parts = []
    for field, label in (("upfront", "upfront"), ("equity", "equity"),
                         ("milestones", "milestones"), ("option", "option to acquire"),
                         ("total", "total")):
        if terms.get(field):
            parts.append(f"{money(terms[field])} {label}")
    return ", ".join(parts)
