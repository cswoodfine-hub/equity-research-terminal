"""The thematic brief: one modality read across every company that runs it.

The morning note answers "what happened at this company". This answers the other
question an analyst asks, which no company page can: what is happening to this kind of
drug, and who is exposed to it. Cell therapy is a story about Gilead, Legend, Autolus
and Iovance at once, and reading four company notes does not produce it.

Two layers, like the note. The rules brief is deterministic and always available: it
states how many programmes carry the theme, whose they are, the stage mix, and what
moved recently. The model layer turns those facts into a read. Without a key the rules
brief is what you get, and it is labelled as such rather than degraded silently.

Everything given to the model is a stored fact. The prompt says so, and says what to do
about the coverage gap rather than leaving the model to guess at it: a theme's counts
are a floor, because an asset named only by a code number states nothing about itself
and is not tagged.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re

import db
import insights
import llm
import themes_view

BRIEF_PROVIDER = (os.getenv("NOTE_LLM_PROVIDER") or "gemini").strip().lower()
RULES_MODEL = "rules"
# The output cap sits well above the thinking budget, not below it. Reversed, the
# model's reasoning spends the whole allowance and the brief truncates mid-sentence.
MAX_TOKENS = 4096
THINKING_BUDGET = 512

SYSTEM_PROMPT = """You are a sell-side equity analyst covering large-cap pharma. Write \
a thematic brief on one drug modality, read across every company in the coverage \
universe that runs it.

You are given: the theme and how many programmes and companies carry it, the stage mix \
of those programmes, the companies with the most exposure, and the trial changes \
detected in the theme recently. Every figure is a stored fact. Use only these.

Write two short paragraphs, at most ten sentences. Lead with what the shape of the \
theme says: a modality that is mostly Phase 1 and Phase 2 is a story about capital and \
patience, one carrying marketed products is a story about revenue, and one where a \
single company holds most of the programmes is a company story rather than a sector \
one. Say which of those this is, and name the companies that make it so. Then take the \
recent changes and say what they do to that picture, naming the company and the drug. \
Close with what would change the read.

You are given two counts of who is in a theme, and they are not the same count. The \
programme count comes from classifying individual drugs, and it is a floor: an asset \
named only by a code number carries no description in any free source and is not \
classified. The platform list comes from each company's own annual filing describing \
what it does, and it is the better guide to who is in the modality. Beam, Editas and \
CRISPR Therapeutics appear in the gene editing platform list and hold no classifiable \
programme between them.

So lead the question of scale off the platform list, not the programme count, and never \
add the two. Say plainly where the programme count understates the theme and name the \
companies it misses. Never state or imply that a company is absent from a modality \
because it does not appear in a count.

Do not print a title or a heading. The page already names the theme, and a repeated \
title reads as the brief starting twice.

House style: sentence case, no em dashes, no bullet points, direct and \
unhedged, specific over abstract, lead with the number or the change. Do not use the \
words additionally, highlight, underscore, pivotal, showcase or testament. Do not \
invent a figure, a drug name or a company that is not given to you."""


def _plural(count: int, word: str, plural: str | None = None) -> str:
    """"1 programme", "8 programmes". The brief is read by a person, and "1 programmes"
    reads as a bug in the data rather than a bug in the sentence."""
    return f"{count} {word}" if count == 1 else f"{count} {plural or word + 's'}"


def context(db_path=None, theme: str = "", days: int = 90, today=None) -> str:
    """The facts behind one theme, as the block the model reads.

    Built from the same view the tab renders, so the brief and the screen can never
    disagree about how many programmes there are.
    """
    rows = themes_view.build(db_path, days=days, today=today)
    row = next((r for r in rows if r["theme"] == theme), None)
    if row is None:
        return ""
    detail = themes_view.detail(theme, db_path, days=days, today=today)
    cover = themes_view.coverage(db_path)

    blocks = [
        f"Theme: {theme}."
        + (f" A sub-theme of {row['parent']}." if row["parent"] else ""),
        f"Scale: {row['assets']} programmes across {row['companies']} companies, "
        f"{row['marketed']} of them marketed.",
        "Stage mix: " + ", ".join(f"{k} {v}" for k, v in row["stage_mix"].items()) + ".",
        "Most exposed: " + ", ".join(
            f"{c['ticker']} {c['assets']}" for c in row["top_companies"]) + ".",
    ]

    marketed = [a for a in detail["assets"] if a["is_marketed"]][:8]
    if marketed:
        blocks.append("Marketed products carrying this theme: " + ", ".join(
            f"{a['name']} ({a['ticker']})" for a in marketed if a["name"]) + ".")
    clinical = [a for a in detail["assets"] if not a["is_marketed"] and a["phase"]][:8]
    if clinical:
        blocks.append("Clinical programmes: " + ", ".join(
            f"{a['name']} ({a['ticker']}, {a['phase']})"
            for a in clinical if a["name"]) + ".")

    moves = detail["changes"][:10]
    if moves:
        blocks.append("Trial changes in the last "
                      f"{days} days: " + " ".join(
                          f"{m['ticker']} {m['name']}: {m['change_type']} "
                          f"{m['old_value']} to {m['new_value']}."
                          for m in moves if m["name"]))
    else:
        blocks.append(f"No trial changes detected in this theme in {days} days.")

    # The second axis, stated separately and never added to the first. A company theme
    # is read from the company's own filing; an asset theme from one drug's name or
    # label. Beam says it runs a base editing platform and holds no drug any free source
    # describes, so it appears in one count and not the other.
    if row["platform_companies"]:
        blocks.append(
            f"Companies whose own annual filing describes this platform: "
            + ", ".join(row["platform_companies"]) + ".")
    if row["platform_only"]:
        blocks.append(
            "Of those, these hold no programme any free source classifies, so they "
            "appear in no programme count above: " + ", ".join(row["platform_only"])
            + ".")

    # Stated every time, because the model must not read a company's absence from these
    # counts as a company that does not work in the modality.
    blocks.append(
        f"Coverage: {cover['tagged']} of {cover['assets']} assets state what they are, "
        f"and {cover['companies_on_platform']} of {cover['companies']} companies "
        "describe a platform in their filing. Programme counts are a floor; the "
        "platform list is the better guide to who is in this modality.")
    return "\n".join(blocks)


def build_rules_brief(theme: str, db_path=None, days: int = 90, today=None) -> str:
    """The brief with no model: the shape of the theme, stated plainly.

    Always available and always true. It reads as a summary rather than a view, which is
    the honest difference between a rules layer and an analyst.
    """
    rows = themes_view.build(db_path, days=days, today=today)
    row = next((r for r in rows if r["theme"] == theme), None)
    if row is None:
        return f"No programmes on file carry the {theme.lower()} theme."

    lead = (f"{theme} covers {_plural(row['assets'], 'programme')} across "
            f"{_plural(row['companies'], 'company', 'companies')}, "
            f"{row['marketed']} of them marketed.")
    mix = ", ".join(f"{k.lower()} {v}" for k, v in row["stage_mix"].items())
    shape = f"The stage mix is {mix}."
    top = row["top_companies"]
    # Whether this is a company story is judged on both axes. Gene editing holds one
    # classifiable programme, at Vertex, and fifteen companies whose filings describe
    # the platform: reading the programme count alone called that a company story,
    # which is the opposite of true. So concentration is stated as what it actually
    # measures, the classified programmes, and the platform reach qualifies it rather
    # than being folded in.
    reach = len({c["ticker"] for c in top} | set(row["platform_companies"]))
    if not top:
        concentration = ""
    elif row["companies"] == 1 or top[0]["assets"] * 2 > row["assets"]:
        concentration = (
            f"{top[0]['ticker']} holds {top[0]['assets']} of the "
            f"{_plural(row['assets'], 'classified programme')}"
            + (f", though {reach} companies describe the platform in total, so the "
               "concentration is in what can be classified rather than in the modality."
               if reach > 2 else
               ", so this reads as a company story rather than a sector one."))
    else:
        holders = ", ".join(f"{c['ticker']} with {c['assets']}" for c in top[:3])
        concentration = f"Exposure is spread, led by {holders}."
    moved = (f"{_plural(row['changes'], 'trial change')} "
             f"{'was' if row['changes'] == 1 else 'were'} detected in the last "
             f"{days} days."
             if row["changes"] else
             f"No trial changes were detected in the last {days} days.")
    platform = ""
    if row["platform_only"]:
        platform = (
            f"{_plural(len(row['platform_only']), 'further company', 'further companies')} "
            f"describe this platform in their own filing while holding no programme any "
            f"free source classifies: {', '.join(row['platform_only'][:8])}.")
    elif row["platform_companies"]:
        platform = ("Their own filings describe this platform at "
                    + ", ".join(row["platform_companies"][:8]) + ".")
    cover = themes_view.coverage(db_path)
    gap = (f"Programme counts are a floor: {cover['untagged']} of {cover['assets']} "
           "assets state nothing about their modality.")
    return " ".join(p for p in (lead, shape, concentration, moved, platform, gap) if p)


def _clean(text: str) -> str:
    """The note's house-style pass, plus the markdown heading a model adds anyway.

    The prompt asks for no title and the model supplies one about half the time, which
    renders as the brief announcing itself twice under a heading the page already shows.
    """
    text = re.sub(r"(?m)^\s*#{1,6}\s*.*$", "", text or "")
    return insights._scrub(text).strip()


def _store(db_path, theme: str, body: str, model: str, days: int) -> dict:
    conn = db.get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO briefs (theme, body, model, horizon_days) VALUES (?, ?, ?, ?)",
            (theme, body, model, days))
        conn.commit()
        row = conn.execute(
            "SELECT id, theme, generated_at, body, model, horizon_days FROM briefs"
            "  WHERE theme = ? ORDER BY id DESC LIMIT 1", (theme,)).fetchone()
    finally:
        conn.close()
    return dict(row)


def generate(db_path=None, theme: str = "", days: int = 90, today=None) -> dict:
    """Write and store the brief for one theme.

    A model failure degrades to the rules brief and is reported, never raised, which is
    the same contract the morning note keeps.
    """
    body = build_rules_brief(theme, db_path, days=days, today=today)
    model = RULES_MODEL
    error = None
    facts = context(db_path, theme, days=days, today=today)
    if llm.provider(BRIEF_PROVIDER) is not None and facts:
        try:
            generated = llm.complete(
                SYSTEM_PROMPT, f"Theme: {theme}\n\n{facts}", MAX_TOKENS,
                prefer=BRIEF_PROVIDER, thinking_budget=THINKING_BUDGET)
            if generated:
                body, model = _clean(generated), llm.model_name(BRIEF_PROVIDER)
            else:
                error = "empty response from the model"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    out = _store(db_path, theme, body, model, days)
    out["error"] = error
    return out


def latest(db_path=None, theme: str = ""):
    """The most recent stored brief for a theme, or None."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, theme, generated_at, body, model, horizon_days FROM briefs"
            "  WHERE theme = ? ORDER BY generated_at DESC, id DESC LIMIT 1",
            (theme,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None
