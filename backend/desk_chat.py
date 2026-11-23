"""The Ask box: a question about the book, answered from the book.

The terminal answers the questions somebody thought to build a page for. A reader's
question is usually one nobody did: is Dyne funded past its readout, who has been
selling, and what does the price already assume. The figures are all in the book, on
four tabs, and the reading across them is the work.

This hands that reading to a language model, on the terms the rest of the app keeps a
model to. It is given the desk tools (``mcp_tools.py``) and nothing else: each is a read
of the terminal's own API, so every figure in an answer is one the book computed and can
source, and the model is told to say the book has nothing where it has nothing. It does
not value anything. It cannot change an assumption, a catalyst or a price, and the one
thing it can write is a thesis, to the append-only log, when it is asked to in so many
words.

An answer comes back with what was read to make it: each tool called, with what, and
the as-of date the read carried. A reader who doubts a sentence can open the read behind
it, and one who sees no reads knows the answer came from nowhere.

The loop is short on purpose. The model asks for reads, is handed them, and answers; it
gets ``MAX_ROUNDS`` rounds of asking before it is told to answer from what it has, so a
question cannot turn into a walk through the whole universe on somebody's key.

Two things are held back. The reader's own holdings (``lens_portfolio``) are not offered
unless ``CHAT_ALLOW_PORTFOLIO=1`` is set: what the tools return is sent to the model's
provider, and a broker statement is not something to send a third party by default. And
with no provider key the box says so and the app carries on, like every other use of a
model here.

Beside the Trading tab's board the box is also told which panels the reader has open, by
name and company and nothing more (``on_screen``). It is told nothing a panel shows: a
figure still has to be read through a tool.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import llm
import mcp_tools

# The chat is a quality-sensitive read with a long context, so it is pinned the way the
# morning note is and for the same reason. The pin degrades to the normal selection where
# that provider has no key (llm.provider).
CHAT_PROVIDER = (os.getenv("CHAT_LLM_PROVIDER") or "gemini").strip().lower()
MAX_ROUNDS = 6
MAX_CALLS_A_ROUND = 6
MAX_TOKENS = 4096
# Earlier turns of the same conversation, as text. Enough for "and what about its
# runway", not a transcript.
HISTORY_TURNS = 8
HISTORY_CHARS = 4000
QUESTION_CHARS = 2000
HELD_BACK = ("lens_portfolio",)
API_TIMEOUT_S = 240

STYLE = (
    "You are answering inside the terminal, to the analyst who runs the book. "
    "Answer the question asked, first, in a sentence; then the figures behind it. "
    "Keep it short: about 150 words, as a few short paragraphs or one short list, unless "
    "the question asks for the full detail. No headings, no bold section titles, no "
    "tables wider than four columns, and no preamble about what you are going to do. "
    "Write in sentence case, without em dashes, direct and unhedged: lead with the number "
    "or the change. Give money with its currency, rounded to a readable figure with its "
    "unit ($114.0m, not $113,996,479.65); never round a per-share value, a price or a "
    "probability, and give a probability as a percentage. Any other figure takes one "
    "decimal place (24.1 months, not 24.113255). "
    "Say which as-of date the figures carry, once. "
    "If the tools returned nothing for part of the question, say the book holds nothing "
    "on it. Never fill a gap from memory, and never state a figure no tool returned. "
    "You may explain what a figure means and connect one read to another; say plainly "
    "when a sentence is your reading and not the book's figure. "
    "Use the tools before you answer anything about a company, an asset or a date; do not "
    "ask the user for a ticker you can look up with lens_universe."
)


_EM_DASH = re.compile(r"\s*\u2014\s*")


def house_style(text: str) -> str:
    """The answer with the one mark the house style bans taken out. The prompt asks for
    no em dashes and a model writes them anyway, about one answer in two, so the rule is
    kept here and not left to the asking. A comma is what the sentence wanted."""
    return _EM_DASH.sub(", ", text or "").strip()


# The panels of the Trading tab's board that the model may be told are open, and the name
# each goes by. The list is kept here, on the API's side, and a panel is named from it and
# never from what the page sent: the page's words would otherwise go into the system
# prompt as they came. A panel built on the reader's own holdings is not in it and so is
# never named, whatever CHAT_ALLOW_PORTFOLIO says: that switch offers a tool, which the
# model has to ask for, and this would tell it unasked. The frontend's registry
# (frontend/trading_view.PANELS) is held to this list by a test.
ON_SCREEN = {"price": "Price chart", "changes": "What changed", "news": "Company news",
             "catalysts": "Dated ahead"}
ON_SCREEN_MAX = 12
_PANEL_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def on_screen(showing) -> list:
    """What the page says is on the board, as the names the model is told: "Company news
    (LLY)". Anything that is not a known panel and a ticker is dropped, not repaired."""
    named = []
    for entry in showing if isinstance(showing, list) else []:
        if not isinstance(entry, dict):
            continue
        panel, ticker = entry.get("panel"), entry.get("ticker")
        label = ON_SCREEN.get(panel) if isinstance(panel, str) else None
        if not label or not isinstance(ticker, str) or not _PANEL_TICKER.match(ticker):
            continue
        text = f"{label} ({ticker})"
        if text not in named:
            named.append(text)
        if len(named) == ON_SCREEN_MAX:
            break
    return named


def tools() -> list:
    """The desk tools as a model is offered them here."""
    held = () if os.getenv("CHAT_ALLOW_PORTFOLIO") == "1" else HELD_BACK
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["input_schema"]}
            for t in mcp_tools.catalogue() if t["name"] not in held]


def system_prompt(context: dict | None = None, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    lines = [mcp_tools.INSTRUCTIONS, STYLE, f"Today is {today.isoformat()}."]
    ticker = ((context or {}).get("ticker") or "").strip().upper()
    if ticker:
        name = ((context or {}).get("name") or "").strip()
        lines.append(f"The analyst is on the page for {ticker}"
                     + (f" ({name})" if name else "")
                     + ". A question that names no company is about this one.")
    panels = on_screen((context or {}).get("showing"))
    if panels:
        lines.append("Open on the analyst's board now: " + ", ".join(panels) + ". These "
                     "are the names of the panels on screen and nothing they show. Read "
                     "the book with the tools for any figure, as for any other question.")
    return "\n\n".join(lines)


def api_fetch(base: str):
    """A ``fetch`` for mcp_tools that asks the terminal's own API at ``base``."""
    base = base.rstrip("/")

    def fetch(method, path, params, body):
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url, data=data, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_S) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            return status, json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            return status, None

    return fetch


_DATE_KEYS = ("as_of", "price_date", "close_date", "period", "today", "gate_odds_as_of",
              "cash_as_of")


def _as_of(payload) -> str | None:
    """The date a read carries, where it states one near the top. Looked for one level
    down as well, since several tools wrap a payload under its own name."""
    if not isinstance(payload, dict):
        return None
    for key in _DATE_KEYS:
        if isinstance(payload.get(key), str) and payload[key][:4].isdigit():
            return payload[key][:10]
    for value in payload.values():
        if isinstance(value, dict):
            for key in _DATE_KEYS:
                if isinstance(value.get(key), str) and value[key][:4].isdigit():
                    return value[key][:10]
    return None


def _titles() -> dict:
    return {t["name"]: t["title"] for t in mcp_tools.catalogue()}


def _history(conversation, history) -> None:
    """Earlier turns as plain text, newest kept, each cut: the reads behind them are
    gone, and the model is told to read again rather than trust a figure it once said."""
    for turn in (history or [])[-HISTORY_TURNS:]:
        text = " ".join(str(turn.get("text") or "").split())[:HISTORY_CHARS]
        if not text:
            continue
        if turn.get("role") == "assistant":
            conversation.assistant(text)
        else:
            conversation.user(text)


def answer(question: str, history: list | None = None, context: dict | None = None,
           fetch=None, conversation_factory=None, today: dt.date | None = None) -> dict:
    """One question answered. {"ok", "answer", "steps", "model", "provider", "rounds"},
    or {"ok": False, "reason"} where it could not be: no key, an empty question, or a
    provider that failed. Never raises on those, so the box can say what happened."""
    question = " ".join((question or "").split())
    if not question:
        return {"ok": False, "reason": "Ask a question."}
    question = question[:QUESTION_CHARS]
    offered = tools()
    allowed = {t["name"] for t in offered}
    factory = conversation_factory or (
        lambda system, tool_list: llm.conversation(system, tool_list, prefer=CHAT_PROVIDER,
                                                   max_tokens=MAX_TOKENS))
    try:
        conversation = factory(system_prompt(context, today), offered)
    except RuntimeError as exc:
        return {"ok": False, "no_provider": True,
                "reason": f"The Ask box needs a model key and none is set: {exc}."}
    _history(conversation, history)
    conversation.user(question)

    titles, steps, text, rounds = _titles(), [], "", 0
    try:
        for rounds in range(1, MAX_ROUNDS + 1):
            out = conversation.step()
            text = out.get("text") or ""
            calls = out.get("calls") or []
            if not calls:
                break
            results = []
            for call in calls[:MAX_CALLS_A_ROUND]:
                name, args = call.get("name") or "", call.get("args") or {}
                step = {"tool": name, "title": titles.get(name, name), "args": args}
                try:
                    if name in mcp_tools.BY_NAME and name not in allowed:
                        raise mcp_tools.ToolError(f"{name} is not offered here")
                    data = mcp_tools.call(name, args, fetch)
                    step.update(ok=True, as_of=_as_of(data),
                                chars=len(json.dumps(data, default=str)))
                    content, failed = data, False
                except mcp_tools.ToolError as exc:
                    step.update(ok=False, error=str(exc))
                    content, failed = {"error": str(exc)}, True
                steps.append(step)
                results.append({"id": call.get("id"), "name": name, "content": content,
                                "is_error": failed})
            for call in calls[MAX_CALLS_A_ROUND:]:
                # Every call the model made must be answered or the provider refuses the
                # next turn; the ones over the limit are answered with the limit.
                results.append({"id": call.get("id"), "name": call.get("name") or "",
                                "content": {"error": "too many reads asked for at once; "
                                                     "ask for fewer"}, "is_error": True})
            conversation.results(results)
        else:
            # Out of rounds with reads still being asked for: the answer the reads so
            # far support, and a line saying it was cut short.
            out = conversation.step(final=True)
            text = (out.get("text") or "").strip()
            if text:
                text += ("\n\nThis answer was drawn up after the limit on reads was "
                         "reached, so it may be incomplete. Ask a narrower question for "
                         "the rest.")
    except Exception as exc:
        return {"ok": False, "steps": steps,
                "reason": f"The model could not answer: {type(exc).__name__}: {exc}"}
    if not text.strip():
        return {"ok": False, "steps": steps,
                "reason": "The model returned no answer. Ask again, or more narrowly."}
    return {"ok": True, "answer": house_style(text), "steps": steps, "rounds": rounds,
            "provider": getattr(conversation, "provider", None),
            "model": getattr(conversation, "model", None)}


def status() -> dict:
    """Whether the box can answer, and on what, for the page to say before it is used."""
    active = llm.provider(CHAT_PROVIDER)
    return {"ready": active is not None, "provider": active,
            "model": llm.model_name(CHAT_PROVIDER),
            "tools": len(tools()),
            "holdings_offered": os.getenv("CHAT_ALLOW_PORTFOLIO") == "1"}
