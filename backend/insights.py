"""Generated morning notes (the note layer over the rules layer).

Two layers, hard separated. ``build_rules_note`` is pure and always available: it
turns the ranked feed for one company into a plain list of the flagged changes.
``generate_note`` upgrades that to a written paragraph via the Anthropic API when a
key is set, and falls back to the rules note when it is not, or when the API errors.
The app never depends on the API being reachable.

Every note is stored in ``insights`` with the ids of the changes that produced it, so
a note can always be traced back to its evidence.
"""

from __future__ import annotations

import json
import os
import re

import db
import llm
import notecontext
import whatchanged

RULES_MODEL = "rules"
# gemini-flash-latest thinks before it writes; the budget must cover the reasoning and
# the note. The thinking cap keeps the reasoning from eating the whole budget and
# truncating the note mid-sentence.
MAX_TOKENS = 4096
THINKING_BUDGET = 512

# The morning note is a quality-sensitive read, so it is pinned to Gemini rather than
# sharing the global LLM_PROVIDER the bulk PDUFA and readout classifiers use. The pin
# degrades to the normal selection if Gemini has no key (see llm.provider).
NOTE_PROVIDER = (os.getenv("NOTE_LLM_PROVIDER") or "gemini").strip().lower()

_SIG_ORDER = ("high", "medium", "low")

# Feed kinds in reading order: what happened, then what is coming, then what expires.
_KIND_SECTIONS = (
    ("filing", "Material events"),
    ("change", "Changes since the last refresh"),
    ("catalyst", "Catalysts inside 60 days"),
    ("loe", "Loss of exclusivity ahead"),
)

SYSTEM_PROMPT = """You are a sell-side equity analyst covering large-cap pharma. Write \
the morning note on one company: what a portfolio manager needs to know before the open, \
in your own voice.

You are given two things. First, a company snapshot: recent reported revenue with its \
year-on-year change, net income, R&D, the share-price move, and any Phase 2 or Phase 3 \
trial readouts that have reported, each with its result. Second, the ranked change feed: \
material 8-K or 6-K events, changes detected since the last refresh, catalysts inside 60 \
days, and near-term loss of exclusivity. Either may be thin or empty.

Write two short paragraphs, at most twelve sentences. Lead with the one thing that most \
moves the investment case right now, whether that is the direction of revenue, a trial \
result, a near-term catalyst, an approval, or an exclusivity loss, and say in the same \
breath why it matters. Then bring in the rest and connect it: a loss of exclusivity \
against the product and revenue it exposes, a trial readout against its programme, a \
catalyst against the franchise it could move, the share move against the events around \
it. Close with the single thing worth watching next and its date. Leave out whatever the \
data does not support; a shorter note beats a padded one.

Turn the numbers into a read. If revenue grew or fell, say by how much and off what base. \
If a product loses exclusivity, say when and what protects it until then. If a trial read \
out, say the phase, the drug, and whether it met its endpoint. A catalyst may carry a \
bracketed detail line with the trial behind it: name the drug and indication, give the \
phase and the NCT identifier, state the comparator when the full title names one, and say \
when a date is estimated or month-only rather than fixed. Write this in prose. Never \
paste the bracketed line or the words "Full title" into the note, and do not narrate \
more than two upcoming trials even when the feed lists more.

Absolute rules. Use only the facts supplied. Never invent a number, a date, a drug, a \
trial, a price, or a counterparty; an 8-K item names the category of an event, not its \
terms, so never state a price or a party that is not given. Do not infer why a number \
moved or why a trial succeeded; the data says what, not why. Where a fact is missing, \
write "no free data", never an estimate.

Voice. Write as an analyst would, not as a machine reading a list. Do not announce the \
note's structure or the ranking of its items: never open with "The most significant item \
is", "Recently", "Several events", or "Worth watching next is". Lead each sentence with \
the fact or the number, not a throat-clearing adverb. Direct and unhedged, specific over \
abstract.

Grammar. Capitalise the first word of every sentence, every proper noun, drug and brand \
name, trial identifier, and month. Copy drug names, identifiers, and acronyms exactly as \
the data spells them. Never write in all lower case.

House style. Sentence-case headings, so a heading reads "What changed", not "what \
changed". No em dashes. Never use the words additionally, highlight, underscore, \
pivotal, showcase, or testament."""


# Adverbs the model reaches for when told to write prose. As a sentence opener each one
# adds nothing and buries the fact the house style says to lead with, so it is stripped
# rather than reworded.
_FILLER = (
    "generally", "normally", "naturally", "basically", "essentially", "actually",
    "obviously", "clearly", "notably", "ultimately", "overall", "currently",
    "typically", "importantly", "interestingly", "fundamentally", "additionally",
    "specifically",
)
# A filler word that opens a sentence: at the start, after a sentence end, or after a
# newline, followed by its comma. The leading boundary is kept, the word and comma go.
_FILLER_RE = re.compile(
    r"(^|(?<=[.!?])\s+|\n\s*)(?:" + "|".join(_FILLER) + r"),\s+",
    re.IGNORECASE,
)
# The first letter of a sentence or a line. A sentence ends on .!? preceded by a letter
# or digit, which skips "U.S." and other mid-sentence abbreviations.
_SENTENCE_START_RE = re.compile(r"(^|(?<=[a-z0-9])[.!?]\s+|\n\s*)([a-z])")


def _scrub(text: str) -> str:
    """Mechanical house-style pass: strip em dashes and the filler adverbs the model
    opens sentences with, then capitalise every sentence and line start so the note
    reads as prose even on a run that comes back lower case."""
    text = text.replace(" — ", ", ").replace("—", ", ")
    text = _FILLER_RE.sub(lambda m: m.group(1), text)
    text = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return text.strip()


def _dated(item: dict) -> str:
    """Headline with its date appended, unless the headline already carries one."""
    date = (item.get("date") or "")[:10]
    return f"{item['headline']} ({date})" if date and date not in item["headline"] \
        else item["headline"]


def build_rules_note(ticker: str, items: list[dict]) -> str:
    """The always-on fallback: the flagged items grouped by kind, ranked within each.

    Grouped rather than one flat list so the note reads as a briefing: what changed,
    then what is coming, then what expires. Items of an unrecognised kind land in a
    catch-all section, so nothing in the feed is silently dropped.

    Pure. No key, no network, no database, no clock.
    """
    ticker = ticker.upper()
    if not items:
        return (f"{ticker}: no flagged changes. The feed compares snapshots between "
                "refreshes, so it fills in once a refresh detects one.")

    counts = {sig: sum(1 for it in items if it.get("significance") == sig)
              for sig in _SIG_ORDER}
    lead = ", ".join(f"{counts[sig]} {sig}" for sig in _SIG_ORDER if counts[sig])
    noun = "item" if len(items) == 1 else "items"
    lines = [f"{ticker}: {len(items)} flagged {noun} ({lead}).",
             f"Most significant: {_dated(items[0])}."]

    known = {kind for kind, _ in _KIND_SECTIONS}
    sections = list(_KIND_SECTIONS)
    if any(it.get("kind") not in known for it in items):
        sections.append((None, "Other flagged items"))

    for kind, heading in sections:
        group = [it for it in items
                 if (it.get("kind") == kind if kind else it.get("kind") not in known)]
        if not group:
            continue
        lines += ["", f"{heading} ({len(group)})"]
        lines += [f"- [{it.get('significance', 'low')}] {_dated(it)}" for it in group]
    return "\n".join(lines)


def _format_items(items: list[dict]) -> str:
    """The feed as compact text for the model. Facts only, no framing.

    A catalyst carries a ``detail`` line with the trial behind it, appended so the note
    can name the phase, indication, and identifier rather than paraphrase a headline.
    """
    lines = []
    for it in items:
        lines.append(f"- kind={it['kind']} significance={it.get('significance')} "
                     f"date={(it.get('date') or '')[:10]} {it['headline']}")
        if it.get("detail"):
            lines.append(f"    {it['detail']}")
    return "\n".join(lines)


def _user_content(ticker: str, items: list[dict], context: str = "") -> str:
    parts = [f"Company: {ticker}"]
    if context:
        parts.append("Company snapshot:\n" + context)
    parts.append("Ranked change feed:\n" + _format_items(items))
    parts.append("Write the note.")
    return "\n\n".join(parts)


def _store(db_path, ticker: str, body: str, model: str, change_ids: list,
           refresh_run_id=None, horizon="on_demand") -> dict:
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
        if row is None:
            raise ValueError(f"unknown ticker {ticker}")
        cur = conn.execute(
            """
            INSERT INTO insights (company_id, horizon, body, source_change_ids, model,
                                  refresh_run_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["id"], horizon, body, json.dumps(change_ids), model, refresh_run_id),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT id, generated_at, horizon, body, model FROM insights WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    finally:
        conn.close()
    out = dict(stored)
    out["ticker"] = ticker.upper()
    out["source_change_ids"] = change_ids
    return out


def generate_note(db_path=None, ticker: str = "LLY", days: int = 30,
                  refresh_run_id=None) -> dict:
    """Generate and store one note for ``ticker``.

    Uses whichever model provider has a key (see ``llm``), otherwise the rules note. Any
    model failure degrades to the rules note and is reported in ``error``; it never
    raises.
    """
    ticker = ticker.upper()
    items = whatchanged.build_feed(db_path, days=days, ticker=ticker)
    change_ids = [it["change_id"] for it in items if it.get("change_id") is not None]

    body = build_rules_note(ticker, items)
    model = RULES_MODEL
    error = None

    if llm.provider(NOTE_PROVIDER) is not None and items:
        context = notecontext.company_context(db_path, ticker)
        try:
            generated = llm.complete(SYSTEM_PROMPT,
                                     _user_content(ticker, items, context),
                                     MAX_TOKENS, prefer=NOTE_PROVIDER,
                                     thinking_budget=THINKING_BUDGET)
            if generated:
                body, model = _scrub(generated), llm.model_name(NOTE_PROVIDER)
            else:
                error = "empty response from the model"
        except Exception as exc:  # a dead API degrades the note, it never fails it
            error = f"{type(exc).__name__}: {exc}"

    out = _store(db_path, ticker, body, model, change_ids, refresh_run_id)
    out["error"] = error
    out["item_count"] = len(items)
    return out


def latest_note(db_path=None, ticker: str = "LLY"):
    """The most recent stored note for a company, or None."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT i.id, i.generated_at, i.horizon, i.body, i.model, i.source_change_ids
              FROM insights i JOIN companies c ON i.company_id = c.id
             WHERE c.ticker = ?
             ORDER BY i.generated_at DESC, i.id DESC
             LIMIT 1
            """,
            (ticker.upper(),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    out = dict(row)
    out["ticker"] = ticker.upper()
    out["source_change_ids"] = json.loads(out["source_change_ids"] or "[]")
    return out
