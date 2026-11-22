"""The rules that read a press headline for an outcome, kept from the proposals block.

``proposals`` matched a headline to every priced gate on an asset it named, and is gone:
on 2026-11-22 it held 17 proposals from four headlines and none decided the gate it stood
against. ``landed_readouts`` ties a report to a study by registry number or by the study's
own name and records it, or holds it and says why. What stays here is what other modules
read: the test for a headline that announces an event to come (``ANNOUNCEMENT``), the
looser outcome words ``submissions`` follows (``classify``), and the press rows worth
reading (``recent_press``). The account below is the block's original one.

A readout in the news, matched to the gate it decides, proposed for confirmation.

The loop the terminal was missing. A result lands on a company's press page, the fetcher
files it, the diff engine writes a change row, and there it stopped: a human had to
notice the headline, remember which gate it decided, and resolve that gate by hand. The
book carried 110 priced binary events and no way to tell when one of them had happened.

The design is proposal, never decision, and the reason is in the feed itself. Beside
"Lilly's Omvoh meets primary endpoint of clinical remission" sit "Revolution Medicines
Begins Treating Patients in Phase 3 RASolve 308" and "Biogen to Present New Data", both
filed as data readouts. One is a result, one is an enrolment, one is a diary entry. A
classifier confident enough to act on that feed would be wrong about the model's biggest
numbers, so this one is built to abstain:

* An announcement of a future event is rejected before anything else is tested. A
  headline that says a trial has begun or that data will be presented is not a result,
  whatever else it contains.
* A miss is tested before a hit, because "did not meet its primary endpoint" contains
  the word "meet" and the cheerful reading of that sentence is the expensive one.
* Only a headline that names the outcome in the words the industry uses is classified at
  all. "Significantly reduced proteinuria" is a good result and is not proposed, because
  the sentence the model would have to write to act on it is one no rule can defend.
* A proposal has to name the asset the gate is on. A company headline that matches no
  asset carrying a gate proposes nothing.

What a proposal is worth needs no simulation: a priced gate already carries both legs,
so the before and after are read off the stake rather than computed by running the
engine twice.

The match is the weak link and says so. A headline naming the trial by its registry
number decides that trial; a headline naming only the asset says a company reported
something about a product that has an open gate, which is not the same claim. One
company can run six studies on one molecule and report a maintenance study the week a
registrational gate is still a year out. Every proposal carries whether it matched the
trial or only the name, and how far the gate still is, so the reader can see which kind
of claim is in front of them before confirming anything.
"""

from __future__ import annotations

import datetime as dt
import re

import db

# Press kinds worth reading for an outcome. A deal, a dividend and a quarterly results
# diary entry decide no gate.
READ_KINDS = ("press_data_readout", "press_approval", "press_regulatory")

# Tested first and wins outright: a headline announcing an event that has not happened.
# This is most of what the readout feed actually carries.
ANNOUNCEMENT = re.compile(
    r"\b(?:to (?:present|report|host|showcase|share)|will (?:present|report|host)"
    r"|begins?|initiat\w+|start(?:s|ed|ing)?\b|dos(?:es|ed|ing) (?:the )?first"
    r"|enroll(?:s|ed|ing) (?:the )?first|scheduled (?:for|to)|to be (?:presented|held)"
    r"|upcoming|invit\w+|webcast|conference call|announces? (?:presentation|participation))\b",
    re.I)

# A miss, tested before a hit.
MISSED = re.compile(
    r"\b(?:did not (?:meet|achieve|demonstrate)|does not meet|fail(?:s|ed) to"
    r" (?:meet|achieve|demonstrate)|miss(?:es|ed) (?:its |the )?(?:primary|key)"
    r"|discontinu(?:es|ed|ing)|halt(?:s|ed|ing)|terminat(?:es|ed|ing) (?:the |its )?"
    r"(?:trial|study|programme|program|development)"
    r"|not (?:statistically )?significant)\b", re.I)

# A hit, in the words the industry actually uses.
MET = re.compile(
    r"\b(?:meets?|met|achiev(?:es|ed)) (?:its |the |all |both |co-?)?"
    r"(?:primary|co-primary|key secondary)\b"
    r"|\bprimary (?:endpoint|end ?point|outcome)[^.]{0,30}\b(?:met|achieved)\b"
    r"|\bpositive top-?line\b"
    r"|\b(?:fda )?approv(?:es|ed|al)\b[^.]{0,40}\b(?:in the us|by the fda)\b"
    r"|\bis now approved\b", re.I)


def classify(headline: str | None) -> tuple[str | None, str | None]:
    """met, missed, or nothing, with the words that decided it.

    Returns no outcome far more often than it returns one, which is the point. The words
    are returned so a reader can check the rule against the sentence rather than trust it.
    """
    text = (headline or "").strip()
    if not text:
        return None, None
    hit = ANNOUNCEMENT.search(text)
    if hit:
        return None, None
    hit = MISSED.search(text)
    if hit:
        return "missed", hit.group(0)
    hit = MET.search(text)
    if hit:
        return "met", hit.group(0)
    return None, None


def _names(gate: dict) -> list[str]:
    """The names a headline could use for the asset this gate is on."""
    out = []
    for key in ("asset_name",):
        value = (gate.get(key) or "").strip()
        if len(value) >= 4:
            out.append(value)
    return out


def _mentions(headline: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", headline, re.I) is not None


def _days_between(detected_at, expected_date) -> int | None:
    """Days from the detection to the gate's expected date, or None where the date is a
    month or a half rather than a day."""
    try:
        seen = dt.date.fromisoformat(str(detected_at)[:10])
        due = dt.date.fromisoformat(str(expected_date)[:10])
    except (TypeError, ValueError):
        return None
    return (due - seen).days


def _resolved_already(description: str | None) -> bool:
    return "| resolved" in (description or "")


def recent_press(conn, ticker: str | None, since: str) -> list[dict]:
    """Press-derived change rows worth reading, newest first."""
    args: list = [since]
    where = ["c.change_type IN (%s)" % ", ".join("?" * len(READ_KINDS)),
             "c.detected_at >= ?"]
    args = list(READ_KINDS) + [since]
    if ticker:
        where.append("c.entity_key LIKE ?")
        args.append(f"{ticker.upper()}|%")
    rows = conn.execute(
        f"""SELECT entity_key, new_value AS headline, change_type, detected_at,
                   significance
              FROM changes c WHERE {' AND '.join(where)}
             ORDER BY detected_at DESC""", args).fetchall()
    out = []
    for r in rows:
        key = str(r["entity_key"] or "")
        who, _, url = key.partition("|")
        out.append({"ticker": who.strip().upper(), "url": url or None,
                    "headline": r["headline"], "kind": r["change_type"],
                    "detected_at": r["detected_at"],
                    "significance": r["significance"]})
    return out
