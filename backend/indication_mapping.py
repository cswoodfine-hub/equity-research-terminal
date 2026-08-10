"""Assets to indications, which CLAUDE.md calls the unit of analysis.

The table had never held a row, and the reason was vocabulary rather than data. 3,159 of
3,184 trials already carry both an asset and a condition list, but the sponsor's free text
gives 2,061 distinct strings for those 3,184 trials: "Non-Small Cell Lung Cancer" (50),
"Carcinoma, Non-Small-Cell Lung" (49) and "Non-small Cell Lung Cancer" (43) are one
indication scattered three ways, and "Healthy" (65), "Healthy Volunteers" (46) and
"Healthy Participants" (30) are Phase 1 studies with no indication at all.

ClinicalTrials.gov indexes every study against MeSH, so the descriptor is the identity:
D009223 takes "Myotonic Dystrophy Type 1 (DM1)" and "Myotonic Dystrophy" alike.

The trap is that the registry's ``meshes`` list is not the specific term. For NCT06926621
it runs to twelve entries ending in "Nervous System Diseases", while for NCT05027269 it
holds two and the broad ones sit in ``ancestors`` instead. Filing an asset under "Nervous
System Diseases" is filing it under nothing.

What decides specificity is the sponsor's own words: a descriptor counts only where it
overlaps what the company said it was studying. "Type 1 Diabetes" carries "Diabetes
Mellitus, Type 1" and carries nothing about the nervous system.

Refusing every descriptor that is somebody's parent somewhere in the corpus was tried and
is wrong, because the sector's biggest indications have subtypes and are therefore
parents. It lost obesity across 143 trials, systemic lupus across 53, breast cancer across
34 and rheumatoid arthritis across 26, all of them named by the sponsor in plain words.
The sponsor anchor alone leaks only a short tail of top-of-tree terms, and those are named
below rather than inferred, so the rule can be argued with.

Two rules decide what the table means:

- A trial condition is an intention, not a fact. Where a marketed asset has an approved
  indication on its label, that is the better record and it wins.
- The phase is the highest that asset has reached in that indication, across all of its
  studies. A company running Phase 1 and Phase 3 in the same disease is in Phase 3 there.
"""

from __future__ import annotations

import json
import re

import db

# A study population rather than a disease.
_NOT_AN_INDICATION = re.compile(
    r"^(?:healthy|healthy volunteers?|healthy participants?|healthy subjects?|"
    r"normal volunteers?|none|not applicable|n/?a)$", re.I)

# Only words that carry no meaning are dropped. "Type" and the digits stay, because they
# are the whole difference between Type 1 and Type 2 diabetes.
_STOPWORDS = {"the", "of", "and", "in", "with", "for", "a", "to"}

# How much of the shorter phrase the two have to share. At a half, "Anemia, Sickle Cell"
# still answers to "Sickle Cell Disease" while "Nervous System Diseases" answers to
# nothing a sponsor wrote.
MATCH_THRESHOLD = 0.5

# Descriptors that are a branch of the tree and never a forecastable indication, even when
# a sponsor writes one as its condition. Matched exactly, so "Lymphoma, Non-Hodgkin" and
# "Lung Neoplasms" are unaffected while bare "Lymphoma" and "Lung Diseases" are not. Short
# and explicit on purpose: this is the one place the rule is a judgement rather than a
# derivation, and it should be readable as such.
TOO_BROAD = frozenset(x.lower() for x in (
    "Neoplasms", "Carcinoma", "Lymphoma", "Leukemia", "Syndrome", "Infections",
    "Nervous System Diseases", "Immune System Diseases", "Digestive System Diseases",
    "Lung Diseases", "Autoimmune Diseases", "Hematologic Diseases",
    "Musculoskeletal Diseases", "Genetic Diseases, Inborn", "Muscular Diseases",
    "Neuromuscular Diseases", "Neurodegenerative Diseases", "Metabolic Diseases",
    "Kidney Diseases", "Liver Diseases", "Heart Diseases", "Skin Diseases",
    "Endocrine System Diseases", "Respiratory Tract Diseases", "Inflammation",
))

_PHASE_ORDER = ("Early Phase 1", "Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3",
                "Phase 3", "Phase 4")
_PHASE_RANK = {p: i for i, p in enumerate(_PHASE_ORDER)}

# A status that says the asset is no longer being developed in that indication. Kept
# rather than deleted: a programme that was dropped is a fact about the asset.
_STOPPED = {"Terminated", "Withdrawn", "Suspended"}


def is_indication(term: str) -> bool:
    """False for a study population, and for a branch of the tree."""
    text = (term or "").strip()
    return bool(text) and not _NOT_AN_INDICATION.match(text) \
        and text.lower() not in TOO_BROAD


def tokens(text: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
            if w and w not in _STOPWORDS}


def _numbers(words: set) -> set:
    """The bare digits in a phrase, which are how a subtype is named."""
    return {w for w in words if w.isdigit()}


def containment(a: set, b: set) -> float:
    """Share of the shorter phrase the two have in common, subtypes permitting.

    Type 1 and type 2 diabetes share "diabetes" and "type", which is two words out of
    three and enough to match on overlap alone. They are different diseases with different
    drugs, so where both phrases number themselves and the numbers disagree, they are not
    the same indication whatever else they share. Where only one carries a number, it does
    not bite: "Myotonic Dystrophy Type 1" is still myotonic dystrophy.
    """
    if not a or not b:
        return 0.0
    na, nb = _numbers(a), _numbers(b)
    if na and nb and not (na & nb):
        return 0.0
    return len(a & b) / min(len(a), len(b))


def parse_browse(raw) -> dict:
    """The stored mesh_terms column, tolerating null, bad JSON and the older list shape."""
    if not raw:
        return {"meshes": [], "ancestors": []}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"meshes": [], "ancestors": []}
    if isinstance(data, list):                     # shape written before ancestors existed
        return {"meshes": data, "ancestors": []}
    if not isinstance(data, dict):
        return {"meshes": [], "ancestors": []}
    clean = lambda key: [t for t in (data.get(key) or [])
                         if isinstance(t, dict) and t.get("id") and t.get("term")]
    return {"meshes": clean("meshes"), "ancestors": clean("ancestors")}


def indications_for(conditions, browse) -> list[dict]:
    """The MeSH descriptors that are this study's actual indications.

    ``conditions`` is the sponsor's free text and ``browse`` the parsed mesh_terms column.
    """
    try:
        sponsor = json.loads(conditions) if isinstance(conditions, str) else (conditions or [])
    except (TypeError, ValueError):
        sponsor = []
    said = [tokens(s) for s in sponsor if is_indication(s)]
    out = []
    for term in browse["meshes"]:
        if not is_indication(term["term"]):
            continue
        mesh = tokens(term["term"])
        if max((containment(mesh, s) for s in said), default=0.0) >= MATCH_THRESHOLD:
            out.append(term)
    return out


def phase_rank(phase: str | None) -> int:
    """Where a phase sits in the order of advance. Unknown phases sort lowest."""
    return _PHASE_RANK.get(phase or "", -1)


def higher_phase(a: str | None, b: str | None) -> str | None:
    """The further along of two phases."""
    return a if phase_rank(a) >= phase_rank(b) else b


def status_for(statuses) -> str:
    """One development status for a pair, from its studies.

    Active beats stopped: an asset with a terminated Phase 2 and a recruiting Phase 3 in
    the same disease is in development there, and reading the terminated study alone would
    retire a live programme.
    """
    live = [s for s in statuses if s and s not in _STOPPED]
    if live:
        for preferred in ("Recruiting", "Active not recruiting",
                          "Enrolling by invitation", "Not yet recruiting"):
            if preferred in live:
                return preferred
        return live[0]
    return next((s for s in statuses if s), None) or "Unknown"


def pairs_from_trials(rows) -> dict:
    """(asset_id, mesh_id) -> the pair's phase, statuses, enrolment and first sighting.

    One trial in three indications makes three pairs, which is the point: the unit of
    analysis is the pair, not the study.
    """
    out: dict = {}
    for row in rows:
        asset_id = row.get("asset_id")
        if not asset_id:
            continue
        browse = parse_browse(row.get("mesh_terms"))
        for term in indications_for(row.get("conditions"), browse):
            entry = out.setdefault((asset_id, term["id"]), {
                "term": term["term"], "phase": None, "statuses": [],
                "enrollment": 0, "first_posted": None, "trials": 0})
            entry["phase"] = higher_phase(entry["phase"], row.get("phase"))
            entry["statuses"].append(row.get("overall_status"))
            entry["enrollment"] += row.get("enrollment") or 0
            entry["trials"] += 1
            posted = row.get("first_posted")
            if posted and (entry["first_posted"] is None
                           or posted < entry["first_posted"]):
                entry["first_posted"] = posted
    return out


def _upsert_indications(conn, pairs) -> dict:
    """One indications row per MeSH descriptor. Returns mesh_id -> indication_id."""
    ids = {}
    for (_, mesh_id), entry in pairs.items():
        if mesh_id in ids:
            continue
        row = conn.execute("SELECT id FROM indications WHERE mesh_id = ?",
                           (mesh_id,)).fetchone()
        if row:
            ids[mesh_id] = row[0]
            continue
        ids[mesh_id] = conn.execute(
            "INSERT INTO indications (name, mesh_id) VALUES (?, ?)",
            (entry["term"], mesh_id)).lastrowid
    return ids


def build(db_path=None) -> dict:
    """Derive asset_indications from the trials on file. Returns a count summary.

    Rebuilt wholesale rather than merged, because a pair with no trial behind it should
    stop being asserted. ``first_seen_phase`` survives the rebuild, so a phase advance
    stays visible to the diff engine.
    """
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT asset_id, conditions, mesh_terms, phase, overall_status,
                      enrollment, first_posted
                 FROM trials WHERE asset_id IS NOT NULL
                UNION ALL
               SELECT asset_id, conditions, mesh_terms, phase, NULL, enrollment, NULL
                 FROM completed_trials WHERE asset_id IS NOT NULL""")]
        pairs = pairs_from_trials(rows)
        indication_ids = _upsert_indications(conn, pairs)
        overrides = {(r["asset_id"], r["indication_id"]): dict(r) for r in
                     conn.execute("SELECT * FROM asset_indication_overrides")}
        seen = {(r["asset_id"], r["indication_id"]): r["first_seen_phase"]
                for r in conn.execute("SELECT asset_id, indication_id, first_seen_phase"
                                      " FROM asset_indications")}

        # The lead indication is the furthest advanced, ties going to the larger
        # enrolment, which is the nearest thing to a stated priority a registry holds.
        lead: dict = {}
        for (asset_id, mesh_id), entry in pairs.items():
            key = (phase_rank(entry["phase"]), entry["enrollment"])
            if asset_id not in lead or key > lead[asset_id][0]:
                lead[asset_id] = (key, mesh_id)

        conn.execute("DELETE FROM asset_indications")
        written = excluded = 0
        for (asset_id, mesh_id), entry in sorted(pairs.items()):
            indication_id = indication_ids[mesh_id]
            override = overrides.get((asset_id, indication_id)) or {}
            if override.get("exclude"):
                excluded += 1
                continue
            phase = override.get("phase") or entry["phase"]
            conn.execute(
                """INSERT INTO asset_indications
                       (asset_id, indication_id, phase, development_status, is_lead,
                        region, first_seen_phase, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'US', ?, datetime('now'))""",
                (asset_id, indication_id, phase, status_for(entry["statuses"]),
                 1 if lead.get(asset_id, (None, None))[1] == mesh_id else 0,
                 seen.get((asset_id, indication_id)) or phase))
            written += 1
        conn.commit()
        return {"pairs": written, "indications": len(indication_ids),
                "assets": len({a for a, _ in pairs}),
                "excluded_by_override": excluded}
    finally:
        conn.close()
