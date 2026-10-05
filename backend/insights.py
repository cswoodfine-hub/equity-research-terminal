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
    ("market", "Market rates"),
    ("policy", "Policy"),
    ("catalyst", "Catalysts inside 60 days"),
    ("loe", "Loss of exclusivity ahead"),
)

# Kinds the model never sees. CLAUDE.md confines the API to the note step and the
# market work is rules only, so these are filtered out of the payload and their
# sentences are appended verbatim afterwards. It is also what the sources require:
# FRED's terms restrict feeding its values into an artificial-intelligence process,
# and the ICE credit index may not be furnished to a third party at all.
UNMODELLED_KINDS = ("market", "fx", "policy")

SYSTEM_PROMPT = """You are a sell-side equity analyst covering large-cap pharma. Write \
the morning note on one company: what a portfolio manager needs to know before the open, \
in your own voice.

You are given two things. First, a company snapshot: recent reported revenue with its \
year-on-year change, net income, R&D, the share-price move, any Phase 2 or Phase 3 \
trial readouts that have reported, each with its result, and any recent deals the \
company announced, taken from its own news headlines. Second, the ranked change feed: \
material 8-K or 6-K events, changes detected since the last refresh, catalysts inside 60 \
days, and near-term loss of exclusivity. Either may be thin or empty.

Write two short paragraphs, at most twelve sentences. Lead with the one thing that most \
moves the investment case right now, whether that is the direction of revenue, a trial \
result, a near-term catalyst, an approval, or an exclusivity loss, and say in the same \
breath why it matters. Then bring in the rest and connect it: a loss of exclusivity \
against the product and revenue it exposes, a trial readout against its programme, a \
catalyst against the franchise it could move, a deal against the capability or franchise it adds, the \
share move against the events around \
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

Recent deals are given with the counterparty, the value where the filing states one, and \
the area, so name them. Say whether it was an acquisition, a licence or a collaboration, \
name the counterparty and, where given, the value and the asset or therapeutic area, and \
say what it adds, a new modality or a franchise it extends, using only what the snapshot \
supports. Do not read a rationale into a deal beyond its words.

Where the snapshot gives deal areas against the pipeline, use them: a deal in an area the \
company already runs extends what it has, and a deal in an area it runs none in is an \
entry into that area, which is worth saying with the compound count behind it. Only the \
areas the snapshot names may be used; a deal with no area given has none, so say nothing \
about where it fits.

Do not report bare counts of risk factors added or removed between filings. A number of \
changed paragraphs is filing churn, not a signal, and means nothing to a reader. Mention \
a filing's risk factors only when the feed says what specifically changed.

Absolute rules. Use only the facts supplied. Never invent a number, a date, a drug, a \
trial, a price, or a counterparty. Name a counterparty only where it is given, the way a \
deal headline gives it; a bare 8-K item names the category of an event, not its terms, so \
never supply a price or a party it does not state. Do not infer why a number moved or why \
a trial succeeded; the data says what, not why. Where a fact is missing, write "no free \
data", never an estimate.

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
    # Market levels are stripped here rather than at the call site, so every caller
    # gets the confinement whether or not it remembered to ask for it.
    seen = [it for it in items if it.get("kind") not in UNMODELLED_KINDS]
    parts.append("Ranked change feed:\n" + _format_items(seen))
    parts.append("Write the note.")
    return "\n\n".join(parts)


def _macro_text(items: list[dict], ticker: str, db_path=None) -> str:
    """The rate paragraphs for this company, composed from levels and measurements.

    Appended to whatever wrote the body, model or rules, rather than being written by
    either. A sentence here states a per-share consequence, and the only honest way to
    get one is to rebuild the book at the old rate: a model paraphrasing a headline
    would be inventing the number.
    """
    said = []
    if any(it.get("kind") == "market" for it in items):
        try:
            import market_signals
            said += market_signals.notes_from(items, ticker, db_path)
        except Exception:
            pass                       # a rate paragraph never fails a note
    said += _policy_text(items, ticker, db_path)
    return ("\n\n" + "\n\n".join(said)) if said else ""


def _policy_text(items: list[dict], ticker: str, db_path=None) -> list[str]:
    """The Medicare selection paragraph, where the company is exposed enough to say so.

    Gated on measured exposure rather than written for every selection: a drug CMS
    names is a fact for the feed whatever its size, and a paragraph in a morning note
    only where Medicare's gross Part D spending on the company's selected drugs reaches
    a share of its revenue worth a reader's attention.
    """
    years = sorted({int((it.get("entity_key") or "|0").split("|")[-1])
                    for it in items
                    if it.get("kind") == "policy"
                    and it.get("change_type") == "ira_selected"
                    and (it.get("entity_key") or "").split("|")[-1].isdigit()})
    if not years:
        return []
    try:
        import db as db_module
        import ira
        conn = db_module.get_connection(db_path)
        try:
            said = [ira.sentence(conn, ticker, year) for year in years]
        finally:
            conn.close()
    except Exception:
        return []
    return [s for s in said if s]


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

    # The snapshot carries revenue, deals and readouts, so a company with a quiet change
    # feed still has a real note to write. Run the model when there is either a feed or a
    # snapshot; fall back to the rules note only when both are empty.
    context = notecontext.company_context(db_path, ticker)
    if llm.provider(NOTE_PROVIDER) is not None and (items or context):
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

    body += _macro_text(items, ticker, db_path)
    out = _store(db_path, ticker, body, model, change_ids, refresh_run_id)
    out["error"] = error
    out["item_count"] = len(items)
    return out


BRIEF_PROMPT = """You are a sell-side equity analyst covering large-cap pharma. Rewrite \
the briefing on one company as the morning note a portfolio manager reads before the open: \
after it, the reader should have the whole picture.

You are given the facts the page shows, as labelled lines: the rating and the 12-month \
value, what today's value is made of and what the price implies for the pipeline and \
future launches, the share price and its moves against the sector, the company news of the \
month, what the value rests on, the levers that would break it, the readouts ahead (marked \
where they are on pipeline compounds), the nearest exclusivity loss, and where the company \
ranks against its peers.

Write three short paragraphs, at most 180 words in all.
1. The call and the reasoning: the rating and the 12-month value against the close, then \
what the price pays for against the model, so the reader sees where the upside or the \
downside sits.
2. The trading: the month and the year, each against the sector where the facts give it, \
and the month's company news set beside the move. You may say a move came despite, with or \
alongside news; never give news as the reason for a move, and never place a move in a week \
or on a day the facts do not give, because the data says what happened, not why. Where the \
facts give no company news, say so.
3. What drives it and what to watch: what the value rests on and when its protection ends, \
the levers that would break the call, whether the next readouts test the pipeline or \
extend products already sold, the nearest exclusivity loss, and the rank against peers \
with what the growth and margin places say together.

Use judgement, but only on the facts given: compare, weigh and conclude from them. Never \
invent a number, a date, a drug, a trial, a price, a counterparty or a reason. Keep every \
figure exactly as given, and keep "est." on every date given as an estimate. Where a fact is \
missing, leave it out.

Voice. Direct, specific, the number first. Write prose, not a list; no headings. Capitalise \
the first word of every sentence and every proper noun. No em dashes. Never use the words \
additionally, highlight, underscore, pivotal, showcase, or testament."""


def brief_hash(facts: str) -> str:
    """The key a rewritten briefing is stored under: the facts it was written from, so a
    rewrite is shown only while the page's figures are still the ones it read."""
    import hashlib
    return hashlib.sha1((facts or "").strip().encode("utf-8")).hexdigest()[:12]


def write_brief(db_path=None, ticker: str = "LLY", facts: str = "") -> dict:
    """Rewrite the page's briefing with the note model, from the facts the page built.

    The page writes the rules briefing itself from the same facts and shows it whenever
    there is no rewrite, so this never falls back to anything: without a model, or on an
    error, it returns no body and says why. A rewrite is stored with the hash of its facts.
    """
    ticker = ticker.upper()
    facts = (facts or "").strip()
    if not facts:
        return {"ticker": ticker, "body": None, "model": None, "error": "no facts given"}
    conn = db.get_connection(db_path)
    try:
        known = conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    finally:
        conn.close()
    if known is None:                   # before the model, so an unknown ticker costs nothing
        return {"ticker": ticker, "body": None, "model": None,
                "error": f"unknown ticker {ticker}"}
    if llm.provider(NOTE_PROVIDER) is None:
        return {"ticker": ticker, "body": None, "model": None,
                "error": "no note model key is set, so the briefing stays as written"}
    try:
        generated = llm.complete(BRIEF_PROMPT, f"Company: {ticker}\n\n{facts}\n\nWrite the note.",
                                 MAX_TOKENS, prefer=NOTE_PROVIDER,
                                 thinking_budget=THINKING_BUDGET)
    except Exception as exc:  # a dead API leaves the briefing as written
        return {"ticker": ticker, "body": None, "model": None,
                "error": f"{type(exc).__name__}: {exc}"}
    body = _scrub(generated) if generated and generated.strip() else ""
    if not body.strip():
        return {"ticker": ticker, "body": None, "model": None,
                "error": "empty response from the model"}
    out = _store(db_path, ticker, body, llm.model_name(NOTE_PROVIDER), [],
                 horizon=f"brief {brief_hash(facts)}")
    out["error"] = None
    return out


def latest_brief(db_path=None, ticker: str = "LLY", facts_hash: str = ""):
    """The newest rewrite of the briefing written from exactly these facts, or None."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT i.id, i.generated_at, i.horizon, i.body, i.model
              FROM insights i JOIN companies c ON i.company_id = c.id
             WHERE c.ticker = ? AND i.horizon = ?
             ORDER BY i.generated_at DESC, i.id DESC
             LIMIT 1
            """,
            (ticker.upper(), f"brief {facts_hash}"),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    out = dict(row)
    out["ticker"] = ticker.upper()
    return out


def latest_note(db_path=None, ticker: str = "LLY"):
    """The most recent stored note for a company, or None. A rewrite of the Key insights
    briefing is not a note: it holds only while the page's figures do, so it is left to
    latest_brief."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT i.id, i.generated_at, i.horizon, i.body, i.model, i.source_change_ids
              FROM insights i JOIN companies c ON i.company_id = c.id
             WHERE c.ticker = ? AND COALESCE(i.horizon, '') NOT LIKE 'brief %'
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
