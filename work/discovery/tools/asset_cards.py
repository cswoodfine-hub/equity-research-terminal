"""An asset card for a paper: what a diligence reader wants out of the abstract, each fact
with the sentence it came from.

    python3 work/discovery/tools/asset_cards.py <papers.json> <out.json> [limit]

Claude reads the title and abstract and returns the card as JSON. Two rules keep it
honest. A fact is kept only if its quote is found in the text, word for word, so nothing
can be invented; what fails is dropped and counted. And a field the abstract does not
state is left out, never guessed.

The key is read from ``DISCOVERY_ANTHROPIC_API_KEY`` (not ``ANTHROPIC_API_KEY``, which a
Claude Code session reads for itself). Without it the script stops and says so: the rest
of the Discovery work runs with no model at all.
"""

import html
import json
import os
import pathlib
import re
import sys

import anthropic

MODEL = "claude-opus-5-5"
# Dollars per million tokens (input, output), as listed on 2026-11-03. Only used to report
# what a run cost; the token counts are the record. A card is priced at the model that
# wrote it: when a safety classifier declines a paper on MODEL the API hands it to another
# model in the same call, and on 2026-11-20 that happened to cell and gene therapy
# abstracts often enough to matter. The declined attempt's own cost is not in the count.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-opus-5": (5.00, 25.00),
          "claude-opus-4-8": (5.00, 25.00)}
FIELDS = ["vector_or_vehicle", "payload_or_target", "indication", "target_tissue",
          "cell_source", "model_or_species", "sample_size", "route", "dose", "durability",
          "efficacy", "safety", "manufacturing", "comparator"]
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "modality", "facts", "red_flags", "open_questions",
                 "commercial_note"],
    "properties": {
        "summary": {"type": "string"},
        "modality": {"type": ["string", "null"]},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["field", "value", "quote"],
            "properties": {"field": {"type": "string", "enum": FIELDS},
                           "value": {"type": "string"}, "quote": {"type": "string"}}}},
        "red_flags": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["flag", "why", "quote"],
            "properties": {"flag": {"type": "string"}, "why": {"type": "string"},
                           "quote": {"type": ["string", "null"]}}}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "commercial_note": {"type": ["string", "null"]},
    },
}
SYSTEM = """You read cell and gene therapy papers for an investor doing early diligence. \
You are given a title and an abstract and nothing else.

Return a card with:
- summary: one sentence saying what was done and found.
- modality: the kind of therapy, in a few words (for example "AAV gene therapy", \
"CAR-T", "base editing", "LNP mRNA"), or null if the abstract does not say.
- facts: the diligence facts the abstract states. Each has a field, a short value in \
your own words keeping every number and unit as written, and a quote. The quote is the \
exact passage of the title or abstract that states it, copied character for character \
and kept short. Give a fact only when the text states it. Leave a field out when it does \
not; never infer a dose, a species, a sample size or a duration.
- red_flags: concerns an experienced reader would raise. Either something the text says \
(give the quote) or something a paper at this stage would be expected to report and this \
abstract does not (quote is null, and say plainly that the abstract does not state it). \
Typical ones: no immunogenicity data, no durability beyond weeks, very high vector dose, \
a payload near a vector's packaging limit, efficacy only in vitro, no manufacturing or \
yield data, small or unstated group sizes, a single model.
- open_questions: up to three questions to put to the authors.
- commercial_note: one sentence on why this could or could not matter commercially, \
using only what the abstract says, or null if it gives no basis.

Write plainly. No em dashes. Do not use the words additionally, highlight, underscore, \
pivotal, showcase or testament. Do not praise the work."""


def _readable(text):
    """The text without its markup: Europe PMC leaves tags and entities in titles."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


def _plain(text):
    return _readable(text).lower()


def card(client, paper):
    text = f"Title: {_readable(paper['title'])}\n\nAbstract: {_readable(paper['abstract'])}"
    response = client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a safety classifier declines, the API retries on another model in the same call.
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": text}])
    usage = {"input": response.usage.input_tokens, "output": response.usage.output_tokens}
    if response.stop_reason != "end_turn":
        return {"id": paper["id"], "error": f"stopped: {response.stop_reason}",
                "usage": usage, "model": response.model}
    got = json.loads(next(b.text for b in response.content if b.type == "text"))
    source = _plain(text)
    stated = lambda quote: bool(quote) and _plain(quote) in source      # noqa: E731
    kept = [f for f in got["facts"] if stated(f["quote"])]
    flags = [f for f in got["red_flags"] if f["quote"] is None or stated(f["quote"])]
    return {"id": paper["id"], "title": _readable(paper["title"]), "model": response.model,
            "summary": got["summary"], "modality": got["modality"], "facts": kept,
            "red_flags": flags, "open_questions": got["open_questions"][:3],
            "commercial_note": got["commercial_note"],
            "dropped": {"facts": len(got["facts"]) - len(kept),
                        "red_flags": len(got["red_flags"]) - len(flags)},
            "usage": usage}


def main(source, out, limit=None):
    key = (os.environ.get("DISCOVERY_ANTHROPIC_API_KEY") or "").strip()
    if not key:
        sys.exit("DISCOVERY_ANTHROPIC_API_KEY is not set, so no card can be written")
    client = anthropic.Anthropic(api_key=key)
    papers = json.loads(pathlib.Path(source).read_text())[:int(limit) if limit else None]
    cards = []
    for paper in papers:
        try:
            cards.append(card(client, paper))
        except anthropic.AuthenticationError:
            sys.exit("the key was refused by the API")
        except anthropic.RateLimitError as exc:
            cards.append({"id": paper["id"], "error": f"rate limited: {exc.message}"})
        except anthropic.APIStatusError as exc:
            cards.append({"id": paper["id"], "error": f"{exc.status_code}: {exc.message}"})
        except anthropic.APIConnectionError as exc:
            cards.append({"id": paper["id"], "error": f"no connection: {exc}"})
        print(cards[-1]["id"], cards[-1].get("error") or
              f"{len(cards[-1]['facts'])} facts, {cards[-1]['dropped']['facts']} dropped",
              flush=True)
    done = [c for c in cards if "usage" in c]
    tokens_in, tokens_out = (sum(c["usage"][k] for c in done) for k in ("input", "output"))
    cost = sum(c["usage"]["input"] / 1e6 * PRICES.get(c["model"], PRICES[MODEL])[0]
               + c["usage"]["output"] / 1e6 * PRICES.get(c["model"], PRICES[MODEL])[1]
               for c in done)
    served = {m: sum(c["model"] == m for c in done) for m in sorted({c["model"] for c in done})}
    pathlib.Path(out).write_text(json.dumps({
        "model": MODEL, "written_by": served, "papers": len(papers), "cards": cards,
        "tokens": {"input": tokens_in, "output": tokens_out},
        "cost_usd": round(cost, 4),
        "cost_per_paper_usd": round(cost / max(1, len(done)), 4),
        "prices_per_million": PRICES}, indent=1))
    print(f"{len(done)} cards, {tokens_in:,} tokens in, {tokens_out:,} out, "
          f"${cost:.3f} in all, ${cost / max(1, len(done)):.4f} a paper; written by {served}",
          flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
