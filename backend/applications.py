"""An application the FDA has accepted, tied to the asset and the disease it is for.

The probability model places a pipeline asset at its gate from the trials and readouts
on file. It had no way to know an application had been filed at all, so an asset whose
BLA the FDA accepted last month was still priced at its Phase 3 entry, roughly 44% in
oncology against the 92% that is actually left. Six analysts' hand-stated overrides
already carried that knowledge, which is the clearest possible statement that the
database was missing it.

The extractor for this already existed and already worked. ``pdufa.extract`` reads 8-K
and 6-K filings, asks the configured model for the decision date, and refuses anything
it cannot find in the document: the product name must appear in the filing, the quoted
sentence must appear in the filing, and the date must sit in a plausible review window.
It has written ten rows. Every one of them carries ``asset_id`` NULL, because
``catalysts.add_catalyst`` takes a ticker and never an asset. So the gap between a
working extractor and the model that needs it was a join, not a missing fetcher, and
this module is that join plus the guards that make it safe to act on.

The guards are the whole of the difficulty, because the reward for being wrong is large.
A filed stage replaces the two-gate Phase 3 chain with the approval gate alone, which in
oncology is 0.477 x 0.920 = 0.439 becoming 0.920. That is 2.10x on risked value with no
human in the loop, so every rule below refuses rather than guesses.

**An application is for one disease, not for a molecule.** This is the guard that
matters most and it is the repository's first core concept: the unit of analysis is the
asset-indication pair. Fifty of the sixty modelled pipeline assets carry more than one
indication and several span Phase 1 to Phase 3 across them, so lifting a whole asset on
one acceptance would put a Phase 1 line at the approval gate on another disease's
evidence. The live case is Vertex's povetacicept: the accepted BLA is for IgA
nephropathy and the only indication row the asset carries is myasthenia gravis. The
honest answer there is that nothing lifts, and that is what this returns.

**A supplement is not a first approval.** A label expansion for a marketed brand is an
sNDA or an sBLA, and its acceptance says nothing about an unapproved asset. The text
does not reliably say so: AstraZeneca, Bristol and Merck all announce supplemental
applications without the word supplemental anywhere in the sentence. So the test is a
join rather than a regex, and any molecule with a marketed row of its own is refused.

**One asset per row.** A title that matches two assets of the same company is refused
rather than assigned to the first, which is the failure mode that put another product's
decision date on an asset that had just dosed its first Phase 3 subject.

Nothing here writes a probability. It reports a fact and what the fact is attached to,
and ``pos_granular`` decides what to do with it.
"""

from __future__ import annotations

import datetime as dt
import re

# Catalyst kinds that state an accepted application. An advisory committee meeting is
# not one: it is scheduled during a review and says nothing the acceptance did not.
FILED_KINDS = ("PDUFA", "regulatory decision")

# A supplemental application, where the text happens to say so. This never stands alone,
# because the filers that matter do not use the word; it is a cheap first pass in front
# of the join against a marketed row, which is the test that actually works.
_SUPPLEMENTAL = re.compile(
    r"\bs[NB]LA\b|\bsupplement(?:al|ary)?\b|label expansion|new indication for|"
    r"expanded indication", re.I)

# The title pdufa.py writes is "<product> PDUFA, <indication>". Splitting on that comma
# is how the disease comes back out. A product name containing a comma would break this,
# and none does, but the split is bounded to one so a comma in the indication survives.
_TITLE = re.compile(r"^(?P<product>.+?)\s+(?:PDUFA|decision|action date)\b\s*,?\s*"
                    r"(?P<indication>.*)$", re.I)


def _norm(text) -> str:
    """Lowercase alphanumerics, the same shape pos_granular matches drug names on."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# Words that carry no disease. "Treatment of patients with metastatic colorectal cancer"
# and "treatment of patients with metastatic gastric cancer" share five of their seven
# long words, so without this an overlap count matches almost any oncology filing to
# almost any oncology indication.
_GENERIC_WORDS = frozenset((
    "treatment", "patients", "patient", "adults", "adult", "with", "advanced",
    "metastatic", "unresectable", "recurrent", "refractory", "relapsed", "previously",
    "treated", "untreated", "first", "line", "second", "therapy", "disease", "disorder",
    "syndrome", "chronic", "acute", "severe", "moderate", "children", "adolescents",
    "years", "older", "locally", "positive", "negative", "stage", "risk", "living",
    "following", "after", "receiving", "combination", "monotherapy", "resistant"))


def _words(text) -> set:
    """The disease-bearing words of a phrase, lowercased. Generic clinical vocabulary is
    dropped, so an overlap count means the two texts name the same disease rather than
    the same kind of sentence."""
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(w) > 3 and w not in _GENERIC_WORDS}


def parse_title(title: str) -> tuple:
    """(product, indication) from a catalyst title, indication None when absent. Pure."""
    match = _TITLE.match((title or "").strip())
    if not match:
        return (title or "").strip() or None, None
    product = (match.group("product") or "").strip() or None
    indication = (match.group("indication") or "").strip() or None
    return product, indication


def match_asset(conn, company_id: int, product: str) -> tuple:
    """(asset_id, why) for the one asset a product name names, or (None, why not).

    Refuses ambiguity rather than taking the first match. A name that reaches two of the
    company's assets is exactly the case where guessing writes another product's
    regulatory date onto this one.
    """
    needle = _norm(product)
    if len(needle) < 5:
        return None, "product name too short to match on"
    hits = []
    for row in conn.execute(
            "SELECT id, generic_name, brand_name, internal_code, is_marketed"
            "  FROM assets WHERE owner_company_id = ?", (company_id,)):
        for field in ("generic_name", "brand_name", "internal_code"):
            name = _norm(row[field])
            if name and len(name) >= 5 and (name in needle or needle in name):
                hits.append(dict(row))
                break
    if not hits:
        return None, "no asset of this company carries that name"
    if len({h["id"] for h in hits}) > 1:
        names = ", ".join(sorted(str(h["generic_name"] or h["brand_name"]) for h in hits))
        return None, f"the name reaches {len(hits)} assets ({names}), so it is ambiguous"
    return hits[0]["id"], "matched on the asset's own name"


def match_indication(conn, asset_id: int, indication: str) -> tuple:
    """(asset_indication_id, why). The disease the application names, among the ones the
    asset carries. None where the text names none or names one the asset does not hold,
    which is the case that must not lift anything."""
    if not indication:
        return None, "the filing names no indication"
    wanted = _words(indication)
    if not wanted:
        return None, "the indication text carries no matchable word"
    # The lead row first. The forecast is built on it, so where the filing names its
    # disease at all that is the row the fact belongs to. An asset can carry the same
    # disease at two granularities, and bepirovirsen carries both "Hepatitis B" as its
    # lead and "Hepatitis B, Chronic" beside it; matching a chronic hepatitis B filing
    # to the more specific row and then refusing it for not being the lead would be a
    # refusal on a technicality.
    rows = [dict(r) for r in conn.execute(
        "SELECT ai.id, ai.is_lead, i.name FROM asset_indications ai"
        "  JOIN indications i ON i.id = ai.indication_id"
        " WHERE ai.asset_id = ? ORDER BY ai.is_lead DESC", (asset_id,))]
    scored = [(len(wanted & _words(r["name"])), r) for r in rows]
    lead = next((r for n, r in scored if n > 0 and r["is_lead"]), None)
    if lead is not None:
        return lead["id"], f"matched '{indication}' to {lead['name']}, the lead line"
    best = max(scored, key=lambda pair: pair[0], default=(0, None))
    if not best[0]:
        return None, f"the asset carries no indication matching '{indication}'"
    return best[1]["id"], f"matched '{indication}' to {best[1]['name']}"


def is_supplemental(conn, asset_id: int, title: str, description: str) -> tuple:
    """(True, why) where the application expands an approved label rather than seeking a
    first approval. The join is the real test; the words are a cheap first pass."""
    text = f"{title or ''} {description or ''}"
    if _SUPPLEMENTAL.search(text):
        return True, "the filing calls the application supplemental"
    row = conn.execute(
        "SELECT generic_name, brand_name, owner_company_id, molecule_id, is_marketed"
        "  FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return True, "the asset is not on file"
    if row["is_marketed"]:
        return True, "the asset is already marketed, so this expands a label"
    # The same molecule held as a separate marketed row. A first approval cannot be
    # sought for a molecule the company already sells.
    generic = _norm(row["generic_name"])
    if generic and len(generic) >= 5:
        for other in conn.execute(
                "SELECT id, generic_name, brand_name FROM assets"
                "  WHERE owner_company_id = ? AND is_marketed = 1 AND id <> ?",
                (row["owner_company_id"], asset_id)):
            if _norm(other["generic_name"]) == generic:
                return True, (f"{other['brand_name'] or other['generic_name']} is the "
                              f"same molecule already marketed")
    return False, "no marketed row for this molecule"


def resolve(conn, today=None) -> dict:
    """Attach an asset and, where the text names one, an indication to every filing
    catalyst that has none. Returns a summary. Writes only the two id columns."""
    today = today or dt.date.today()
    marks = ",".join("?" * len(FILED_KINDS))
    rows = [dict(r) for r in conn.execute(
        f"""SELECT id, company_id, title, description, expected_date, asset_id
              FROM catalysts
             WHERE catalyst_type IN ({marks}) AND asset_id IS NULL""", FILED_KINDS)]
    out = {"seen": len(rows), "asset": 0, "indication": 0, "refused": []}
    for row in rows:
        product, indication = parse_title(row["title"])
        asset_id, why = match_asset(conn, row["company_id"], product or "")
        if asset_id is None:
            out["refused"].append({"id": row["id"], "title": row["title"], "why": why})
            continue
        ai_id, _ = match_indication(conn, asset_id, indication)
        conn.execute("UPDATE catalysts SET asset_id = ?, asset_indication_id = ?,"
                     " updated_at = datetime('now') WHERE id = ?",
                     (asset_id, ai_id, row["id"]))
        out["asset"] += 1
        out["indication"] += 1 if ai_id else 0
    conn.commit()
    return out


def filed_for(conn, asset_id: int, lead_indication_id=None, today=None) -> dict | None:
    """The accepted application that puts this asset at the approval gate, or None.

    Returns None where no filing is on file, and returns a refusal dict where a filing
    exists but must not lift the asset. A refusal is worth reporting: a reader wants to
    know a filing exists and why the number did not move for it.
    """
    today = (today or dt.date.today()).isoformat()
    marks = ",".join("?" * len(FILED_KINDS))
    rows = [dict(r) for r in conn.execute(
        f"""SELECT id, catalyst_type, expected_date, title, description, source_url,
                   asset_indication_id, is_curated
              FROM catalysts
             WHERE asset_id = ? AND catalyst_type IN ({marks})
             ORDER BY expected_date DESC""", (asset_id, *FILED_KINDS))]
    if not rows:
        return None
    row = rows[0]
    _, indication = parse_title(row["title"])
    base = {"date": row["expected_date"], "indication": indication,
            "quote": row["description"], "url": row["source_url"],
            "catalyst_id": row["id"], "is_curated": bool(row["is_curated"])}

    supplemental, why = is_supplemental(conn, asset_id, row["title"], row["description"])
    if supplemental:
        return {**base, "lifts": False, "why": why}
    if row["asset_indication_id"] is None:
        return {**base, "lifts": False,
                "why": (f"the application is for {indication}, which is not an "
                        f"indication this asset carries"
                        if indication else "the filing names no indication")}
    if lead_indication_id is not None and row["asset_indication_id"] != lead_indication_id:
        return {**base, "lifts": False,
                "why": (f"the application is for {indication}, which is not the "
                        f"indication this forecast is built on")}
    if (row["expected_date"] or "") and row["expected_date"] < today:
        return {**base, "lifts": False,
                "why": f"the decision date {row['expected_date']} has passed"}
    return {**base, "lifts": True,
            "why": f"application accepted, decision due {row['expected_date']}"}
