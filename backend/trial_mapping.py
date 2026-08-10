"""Map trials to the asset they study, by intervention name.

The unit of analysis is the asset, so a trial that is not bound to one cannot appear in a
product's profile or count toward its pipeline. ClinicalTrials.gov names the study drug
in free text and the registry, the Orange Book and the SEC each spell it differently, so
the match is on a normalised name against every name an asset is known by: brand, generic
and internal code.

Three rules keep it honest.

The match is scoped to the trial's sponsor. A generic name is not unique across the
universe, and without the sponsor constraint a Novartis study of a shared molecule would
bind to a Pfizer asset. Only the sponsor's own assets are candidates.

Longer names win. "Insulin" is a substring of most of a diabetes portfolio, so a short
name that merely appears inside an intervention string is a weak signal; the longest
asset name that matches is the specific one and takes the trial.

A curated override always wins. ``trial_asset_map`` is the analyst's answer for the
studies the string match cannot reach, and this never overwrites it.

A trial that matches nothing is left unmapped rather than guessed at, and the counts
returned say how many, so the gap stays visible rather than reading as full coverage.
"""

from __future__ import annotations

import re

import assets_util
import db

# A name shorter than this is too generic to match as a substring of a longer
# intervention string ("HIV", "ASA"). It still matches when the whole name is equal.
MIN_SUBSTRING_LEN = 5

# The Orange Book names a drug by its salt or hydrate ("Orforglipron Calcium"), the
# registry by the base molecule ("Orforglipron"). Stripping a trailing salt gives the
# asset a second name to be known by, which is what binds those two spellings. Only a
# trailing token is stripped, so a molecule whose own name ends in one of these words is
# untouched, and the full name is always kept as well.
SALT_SUFFIXES = {
    "calcium", "sodium", "potassium", "magnesium", "hydrochloride", "hcl",
    "sulfate", "sulphate", "tartrate", "bitartrate", "maleate", "mesylate",
    "besylate", "acetate", "phosphate", "citrate", "fumarate", "succinate",
    "erbumine", "dihydrate", "monohydrate", "hydrate", "bromide", "chloride",
    "nitrate", "oxalate", "lactate", "gluconate", "carbonate", "malate",
}


# Interventions that name no compound: the control arm, the background regimen, the
# delivery vehicle. These are study design, not a drug programme. Placebo is matched
# anywhere in the name, not only at the front: "Oral Lenacapavir Placebo" is the control
# arm of a study, not a second compound alongside the drug it is matched against.
NOT_A_COMPOUND = re.compile(
    r"\bplacebo\b|\bsham\b|\bvehicle\b"
    r"|^(saline|comparator|control|standard of care|soc"
    r"|rescue medication|rescue medications|best supportive care"
    r"|normal saline|dextrose|water|diluent|no intervention|observation)\b")

# Route, formulation and strength words. The registry names the same molecule a dozen
# ways, once per arm: "Oral Lenacapavir", "Lenacapavir Injection", "Subcutaneous (SC)
# Lenacapavir (LEN)". Left alone, each spelling became its own programme, so one Gilead
# compound read as ten. Stripping these collapses the arms back to the molecule.
FORM_WORDS = {
    "oral", "orally", "injection", "injectable", "injections", "tablet", "tablets",
    "capsule", "capsules", "infusion", "iv", "intravenous", "intravenously",
    "subcutaneous", "subcutaneously", "sc", "im", "intramuscular", "solution",
    "suspension", "cream", "gel", "patch", "inhaled", "inhalation", "topical",
    "ophthalmic", "spray", "powder", "sachet", "syrup", "drops", "prefilled",
    "syringe", "autoinjector", "pen", "fdc", "sublingual", "buccal", "nasal",
    "extended", "release", "immediate", "delayed", "modified", "coated",
    "dose", "doses", "low", "high", "medium", "adult", "adults", "paediatric",
    "pediatric", "strength", "arm", "group", "cohort", "regimen", "therapy",
    "treatment", "combination", "monotherapy", "single", "multiple", "ascending",
    # The words a protocol adds to say how a compound is being given rather than what
    # it is: "Asciminib single agent" and "Asciminib Adult formulation" are Scemblix,
    # and each was standing in the pipeline as a programme of its own.
    "agent", "agents", "formulation", "formulations", "substance", "alone",
    "escalation", "expansion", "titration", "maintenance", "induction", "comparator",
    "reference", "control", "standard", "care", "matching", "matched",
    "drug", "drugs",
}
UNIT_WORDS = {"mg", "mcg", "ug", "g", "ml", "l", "iu", "u", "kg", "mg/kg", "percent"}


def normalise(text: str) -> str:
    """A name reduced for matching: lowercase, punctuation to spaces, collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def strip_salt(norm: str) -> str:
    """A normalised name without a trailing salt or hydrate token, or unchanged."""
    parts = norm.split()
    if len(parts) > 1 and parts[-1] in SALT_SUFFIXES:
        return " ".join(parts[:-1])
    return norm


def canonical(raw: str) -> str:
    """A drug name reduced to the molecule it names, or empty when it names none.

    Parentheticals go first, since they hold the study's own abbreviation, "(LEN)" or
    "(SG)", which differs per protocol. Then the biologic suffix, the salt, and every
    route, formulation and strength word, which describe how a compound is given rather
    than which compound it is. What survives is the thing being developed, so every arm
    of every study collapses onto one programme instead of one each.
    """
    text = re.sub(r"\([^)]*\)", " ", raw or "")          # study abbreviations
    text = re.sub(r"-[a-z]{4}\b", " ", text, flags=re.IGNORECASE)   # biologic suffix
    # A dose is a number with a unit on it, and only that pair is dropped. A bare number
    # is usually half a compound's name, so removing every digit turned LOXO-435 into
    # "loxo" and BAY 3547922 into "bay", collapsing a company's whole numbered series
    # into one programme.
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|g|ml|l|iu|kg|%)\b", " ", text,
                  flags=re.IGNORECASE)
    words = [w for w in normalise(text).split()
             if w not in FORM_WORDS and w not in UNIT_WORDS]
    # A trailing single letter labels a variant, not a molecule: "Evolocumab Drug
    # Substance A". Only ever trailing, and only when a name survives without it, so
    # a compound actually called by one letter is untouched.
    while len(words) > 1 and len(words[-1]) == 1:
        words.pop()
    return strip_salt(" ".join(words))


def aliases(raw: str) -> set[str]:
    """Every normalised spelling a drug name should be recognised by.

    Three sources spell the same molecule three ways. The registry writes the base
    molecule, "Donanemab". The FDA appends a four-letter suffix to a biologic's generic
    name, "donanemab-azbt". The Orange Book names the salt, "Orforglipron Calcium".
    Reducing all of them to a common set is what stops an approved product being read as
    a second, unapproved programme of the same name.
    """
    text = (raw or "").strip()
    if not text:
        return set()
    # The suffix is exactly four letters after a hyphen, so this cannot eat a real word.
    base = re.sub(r"-[a-z]{4}$", "", text, flags=re.IGNORECASE)
    out = set()
    for candidate in (text, base):
        norm = normalise(candidate)
        if norm:
            out.add(norm)
            out.add(strip_salt(norm))
    out.add(canonical(text))
    return {a for a in out if a}


def _asset_names(conn, company_id: int) -> list[tuple[str, int]]:
    """(normalised name, asset_id) for every name one company's assets are known by,
    longest first so the most specific match is tried before a shorter, vaguer one."""
    rows = conn.execute(
        "SELECT id, brand_name, generic_name, internal_code FROM assets"
        "  WHERE owner_company_id = ?", (company_id,)).fetchall()
    seen: set[tuple[str, int]] = set()
    names: list[tuple[str, int]] = []
    for row in rows:
        for field in ("brand_name", "generic_name", "internal_code"):
            for candidate in aliases(row[field]):
                key = (candidate, row["id"])
                if key not in seen:
                    seen.add(key)
                    names.append(key)
    # Names the product answers to that appear nowhere on its own row: the development
    # name it was trialled under, whether the filings gave it up or an analyst wrote it
    # down. Casgevy is the case that needs the second kind, since its studies are filed
    # under CTX001 and nothing on record joins that to the brand.
    for row in conn.execute(
            "SELECT al.internal_code, al.asset_id FROM asset_aliases al"
            "  JOIN assets a ON a.id = al.asset_id"
            " WHERE a.owner_company_id = ?", (company_id,)):
        for candidate in aliases(row[0]):
            key = (candidate, row[1])
            if key not in seen:
                seen.add(key)
                names.append(key)
    names.sort(key=lambda n: len(n[0]), reverse=True)
    return names


def match_intervention(intervention_norm: str, names: list[tuple[str, int]]) -> int | None:
    """The asset an intervention names, or None.

    An exact match wins outright. Otherwise the longest asset name that appears in the
    intervention as a whole word takes it, so "Tirzepatide 5 mg" and "LY3437943 injection"
    both bind while "insulin" does not sweep up a whole portfolio. Pure, so the rule is
    testable without a database.
    """
    if not intervention_norm:
        return None
    for norm, asset_id in names:
        if norm == intervention_norm:
            return asset_id
    for norm, asset_id in names:
        if len(norm) < MIN_SUBSTRING_LEN:
            continue
        if re.search(rf"(?:^|\s){re.escape(norm)}(?:\s|$)", intervention_norm):
            return asset_id
    return None


def derive_pipeline_assets(db_path=None) -> dict:
    """Create an unmarketed asset for each compound a company is trialling but does not
    yet sell, so the pipeline is a set of programmes rather than a list of loose studies.

    The hard part is not finding names, it is not attributing someone else's drug. A
    trial names its comparator and its background regimen alongside the study drug, so
    three rules decide what counts as one company's programme, and each is answered from
    the data rather than a hand-kept list.

    A name that is study design and not a compound is dropped: placebo, saline, rescue
    medication. A name that is already a marketed product of any company in the universe
    is dropped, since it is that company's drug appearing here as a comparator, which is
    how Merck's pembrolizumab shows up in a Lilly study. A name studied by more than one
    sponsor is dropped, because a compound several rivals run trials with is a shared
    backbone like paclitaxel or prednisone, not one company's programme.

    What survives is a compound only its sponsor studies and nobody sells. It is written
    unmarketed and without a brand, because it has neither yet, and never given an
    approval or expiry it does not have.
    """
    conn = db.get_connection(db_path)
    try:
        # Every name any universe company already sells, so a comparator is recognised.
        marketed: set[str] = set()
        for row in conn.execute(
                "SELECT brand_name, generic_name, internal_code FROM assets"):
            for field in ("brand_name", "generic_name", "internal_code"):
                marketed |= aliases(row[field])
        # A development name already folded into the product it became. Without this the
        # next run derives the pipeline row again from the same intervention, and the
        # merge that recognised it is undone every refresh.
        for row in conn.execute("SELECT internal_code FROM asset_aliases"):
            marketed |= aliases(row[0])

        rows = conn.execute(
            """
            SELECT i.name, t.sponsor_company_id AS company_id, t.nct_id
              FROM trial_interventions i
              JOIN trials t ON t.nct_id = i.nct_id
             WHERE t.asset_id IS NULL AND t.sponsor_company_id IS NOT NULL
                   AND i.name IS NOT NULL AND i.name != ''
            """).fetchall()

        # Group by the molecule rather than the spelling, so every arm of every study
        # lands on one programme. The display name is the shortest spelling seen, which
        # is the one without the route and the protocol's abbreviation attached.
        groups: dict = {}
        for row in rows:
            key = canonical(row["name"])
            if not key or NOT_A_COMPOUND.search(normalise(row["name"])):
                continue                       # study design, not a compound
            entry = groups.setdefault(key, {"names": set(), "sponsors": set(),
                                            "trials": set()})
            entry["names"].add(row["name"])
            entry["sponsors"].add(row["company_id"])
            entry["trials"].add(row["nct_id"])

        created = 0
        for key, entry in groups.items():
            if key in marketed or any(aliases(n) & marketed for n in entry["names"]):
                continue                       # someone's marketed drug, so a comparator
            if len(entry["sponsors"]) > 1:
                continue                       # a shared backbone, not one programme
            display = min(entry["names"], key=lambda n: (len(n), n))
            conn.execute(
                "INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                "  VALUES (?, ?, 0)", (next(iter(entry["sponsors"])), display))
            created += 1
            marketed.add(key)                  # so a later spelling does not duplicate it
        conn.commit()
    finally:
        conn.close()
    return {"created": created}


def prune_orphan_pipeline_assets(db_path=None) -> dict:
    """Delete derived pipeline assets that ended up with no trial bound to them.

    A name can produce an asset and then lose its own trials to a longer, more specific
    match, which left most of the derived rows attached to nothing. They are invisible in
    the pipeline view, which joins through trials, but they are still wrong: they inflate
    any count taken from the assets table. Only unmarketed rows carrying no approval, no
    exclusivity, no revenue and no trial are removed, so nothing an analyst or a source
    put there can be caught by this.
    """
    conn = db.get_connection(db_path)
    try:
        # Nothing may point at a row before it is removed. The tables that could are
        # read from the schema, so a table added later is respected without an edit.
        guards = "".join(
            f"\n               AND NOT EXISTS (SELECT 1 FROM {table} x"
            f" WHERE x.asset_id = assets.id)"
            for table in assets_util.referring_tables(conn))
        cur = conn.execute(
            f"DELETE FROM assets WHERE is_marketed = 0{guards}")
        conn.commit()
        return {"pruned": cur.rowcount}
    finally:
        conn.close()


def map_trials(db_path=None) -> dict:
    """Bind every unmapped trial to an asset where its intervention names one.

    Idempotent, and safe to re-run after a refresh: a trial already mapped by the analyst
    through ``trial_asset_map`` keeps that answer, and a trial that matches nothing is
    left null. Returns the counts, including how many are still unmapped, so a caller can
    see the coverage rather than assume it.
    """
    conn = db.get_connection(db_path)
    try:
        # The curated overrides first; they outrank anything derived here.
        overrides = dict(conn.execute(
            "SELECT nct_id, asset_id FROM trial_asset_map WHERE asset_id IS NOT NULL"))
        for nct_id, asset_id in overrides.items():
            conn.execute("UPDATE trials SET asset_id = ? WHERE nct_id = ?",
                         (asset_id, nct_id))

        rows = conn.execute(
            """
            SELECT t.nct_id, t.sponsor_company_id AS cid,
                   GROUP_CONCAT(i.norm, '||') AS norms
              FROM trials t
              JOIN trial_interventions i ON i.nct_id = t.nct_id
             WHERE t.sponsor_company_id IS NOT NULL
             GROUP BY t.nct_id
            """).fetchall()

        names_by_company: dict[int, list] = {}
        matched = 0
        for row in rows:
            if row["nct_id"] in overrides:
                continue                      # the analyst has already answered this one
            cid = row["cid"]
            if cid not in names_by_company:
                names_by_company[cid] = _asset_names(conn, cid)
            names = names_by_company[cid]
            asset_id = next(
                (a for a in (match_intervention(n, names)
                             for n in (row["norms"] or "").split("||")) if a), None)
            if asset_id is not None:
                conn.execute("UPDATE trials SET asset_id = ? WHERE nct_id = ?",
                             (asset_id, row["nct_id"]))
                matched += 1
        conn.commit()

        # Completed studies are bound by the same rule and from the same stored names,
        # so an improvement to the cleaner reaches a product's record as well as its
        # pipeline without anything being fetched again.
        completed = conn.execute(
            """
            SELECT ct.nct_id, ct.sponsor_company_id AS cid,
                   GROUP_CONCAT(i.norm, '||') AS norms
              FROM completed_trials ct
              JOIN trial_interventions i ON i.nct_id = ct.nct_id
             WHERE ct.sponsor_company_id IS NOT NULL AND ct.asset_id IS NULL
             GROUP BY ct.nct_id
            """).fetchall()
        completed_matched = 0
        for row in completed:
            cid = row["cid"]
            if cid not in names_by_company:
                names_by_company[cid] = _asset_names(conn, cid)
            asset_id = next(
                (a for a in (match_intervention(n, names_by_company[cid])
                             for n in (row["norms"] or "").split("||")) if a), None)
            if asset_id is not None:
                conn.execute("UPDATE completed_trials SET asset_id = ? WHERE nct_id = ?",
                             (asset_id, row["nct_id"]))
                completed_matched += 1
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        mapped = conn.execute(
            "SELECT COUNT(*) FROM trials WHERE asset_id IS NOT NULL").fetchone()[0]
        no_interventions = conn.execute(
            "SELECT COUNT(*) FROM trials t WHERE NOT EXISTS"
            " (SELECT 1 FROM trial_interventions i WHERE i.nct_id = t.nct_id)"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"matched": matched, "completed_matched": completed_matched,
            "mapped": mapped, "total": total,
            "unmapped": total - mapped, "curated": len(overrides),
            "no_interventions": no_interventions}
