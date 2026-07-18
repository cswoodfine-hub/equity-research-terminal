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

import db
import whatchanged

MODEL = "claude-opus-4-8"
RULES_MODEL = "rules"
MAX_TOKENS = 1024

_SIG_ORDER = ("high", "medium", "low")

# Feed kinds in reading order: what happened, then what is coming, then what expires.
_KIND_SECTIONS = (
    ("change", "Changes since the last refresh"),
    ("catalyst", "Catalysts inside 60 days"),
    ("loe", "Loss of exclusivity ahead"),
)

SYSTEM_PROMPT = """You write a short morning note for an equity research analyst \
covering large-cap pharma.

You are given the ranked change feed for one company: detected changes since the last \
refresh, catalysts inside 60 days, and near-term loss of exclusivity.

Write two short paragraphs, at most ten sentences in total. Open with the single most \
significant item and what it means for the company. Then cover, in this order and only \
where the feed has them: what changed since the last refresh, what is coming inside 60 \
days, and which products lose exclusivity. Close with the one thing worth watching \
next. Give dates for anything forward-looking.

Absolute rule: use only the items supplied. Never invent a number, a date, a drug \
name, or a trial. If something is not in the items, it is not in the note. Where data \
is missing, say "no free data" rather than estimating. Do not infer a cause for a \
change; the feed says what changed, not why.

Style: lead with the number or the change. Direct and unhedged. Specific over \
abstract. Sentence-case headings. No em dashes. Never use the words additionally, \
highlight, underscore, pivotal, showcase, or testament."""


def _scrub(text: str) -> str:
    """Mechanical house-style pass: no em dashes."""
    return text.replace(" — ", ", ").replace("—", ", ").strip()


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
    """The feed as compact text for the model. Facts only, no framing."""
    return "\n".join(
        f"- kind={it['kind']} significance={it.get('significance')} "
        f"date={(it.get('date') or '')[:10]} {it['headline']}"
        for it in items
    )


def _call_anthropic(client, ticker: str, items: list[dict]) -> str:
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (f"Company: {ticker}\n\nRanked change feed:\n"
                        f"{_format_items(items)}\n\nWrite the note."),
        }],
    )
    parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
    return "\n".join(parts).strip()


def _build_client():
    """Return an Anthropic client, or None when the key or the SDK is absent.

    Imported lazily so the app runs with ``anthropic`` uninstalled.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic()


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


def generate_note(db_path=None, ticker: str = "LLY", days: int = 30, client=None,
                  refresh_run_id=None) -> dict:
    """Generate and store one note for ``ticker``.

    Uses the Anthropic API when a key is set and the SDK is installed, otherwise the
    rules note. Any API failure degrades to the rules note and is reported in
    ``error``; it never raises.
    """
    ticker = ticker.upper()
    items = whatchanged.build_feed(db_path, days=days, ticker=ticker)
    change_ids = [it["change_id"] for it in items if it.get("change_id") is not None]

    body = build_rules_note(ticker, items)
    model = RULES_MODEL
    error = None

    if client is None:
        client = _build_client()

    if client is not None and items:
        try:
            generated = _call_anthropic(client, ticker, items)
            if generated:
                body, model = _scrub(generated), MODEL
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
