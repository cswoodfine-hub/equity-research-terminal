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

import json
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
    r"|normal saline|dextrose|water|diluent|no intervention|observation)\b"
    # A numbered dose regimen is the study's own labelling of its arms, not a compound:
    # "Tozorakimab Dose Regimen 1" and "Tozorakimab Dose Regimen 2" are one programme.
    r"|\bdose (regimen|level|cohort|escalation)\b"
    )

# Words that make a name a regimen rather than a molecule. Tested against the canonical
# key, not the raw name, because normalising drops the "+" that joins them: "Durvalumab +
# Chemotherapy" arrives here as "durvalumab chemotherapy". The molecule in such a name
# already has a row of its own, and taking the whole string made a second programme out
# of the protocol's shorthand for what it was given alongside.
REGIMEN_WORDS = re.compile(
    r"\b(chemotherapy|chemo|chemoradiation|radiotherapy|soc|rchop|chop|"
    r"carboplatin|cisplatin|paclitaxel|docetaxel|pemetrexed|rituximab|"
    r"lenalidomide|dexamethasone|bortezomib|fulvestrant)\b")

# Route, formulation and strength words. The registry names the same molecule a dozen
# ways, once per arm: "Oral Lenacapavir", "Lenacapavir Injection", "Subcutaneous (SC)
# Lenacapavir (LEN)". Left alone, each spelling became its own programme, so one Gilead
# compound read as ten. Stripping these collapses the arms back to the molecule.
FORM_WORDS = {
    "oral", "orally", "injection", "injectable", "injections", "tablet", "tablets",
    "capsule", "capsules", "infusion", "iv", "intravenous", "intravenously",
    # Delivery devices, which name how a dose is given rather than what is in it.
    "mdi", "dpi", "hfo", "aerosphere", "autoinjector", "pen", "vial", "syringe",
    "prefilled", "implant", "odt", "nebulized", "nebulised",
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
    # A strength written as a ratio names a fixed-dose combination's arm rather than a
    # molecule: "BGF MDI 320/14.4/9.6 ug" is one inhaler at one strength, not a compound
    # called BGF MDI 320. The ratio goes before the dose, since it carries the unit.
    text = re.sub(r"\b\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+\s*"
                  r"(?:mg|mcg|ug|\u00b5g|\u03bcg|g|ml|l|iu|kg|%)?\b", " ", text,
                  flags=re.IGNORECASE)
    # The micro sign and the Greek mu are both used for micrograms and neither was in
    # this list, so "Glycopyrronium bromide 25ug" lost its dose and "25 \u03bcg" kept it.
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|\u00b5g|\u03bcg|g|ml|l|iu|kg|%)\b",
                  " ", text, flags=re.IGNORECASE)
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


# What joins two compounds in one intervention name: "Naltrexone SR 32 mg/bupropion SR
# 360 mg/day", "Oxycodone and Naltrexone". A slash between two numbers is a strength, not
# a join, since "320/14.4/9.6 ug" is one inhaler's dose.
COMBINATION_JOIN = re.compile(
    r"\s*(?:\+|&|;|\bplus\b|\band\b|\bwith\b|(?<!\d)/|/(?!\d))\s*", re.IGNORECASE)

# Words left beside a compound once its dose is gone, which say how often or how fast it
# is given: the "day" of "360 mg/day", the "SR" of "Naltrexone SR".
SCHEDULE_WORDS = {
    "day", "days", "daily", "d", "week", "weekly", "wk", "month", "monthly", "hour",
    "hours", "h", "hr", "once", "twice", "per", "bid", "tid", "qid", "qd", "qw", "qod",
    "sr", "er", "xr", "cr", "la", "xl", "dr", "ir",
}


def components(raw: str) -> list[str]:
    """The compounds an intervention combines, each reduced to its molecule, or an empty
    list when it names one compound or none.

    The normalised name cannot answer this, since normalising turns the slash that joins
    two drugs into the same space that separates a drug from its dose. So the raw name is
    split first, and a piece that is only a schedule, a strength or a placebo is dropped.
    """
    text = re.sub(r"\([^)]*\)", " ", raw or "")
    parts = []
    for piece in COMBINATION_JOIN.split(text):
        if not piece.strip() or NOT_A_COMPOUND.search(normalise(piece)):
            continue
        key = " ".join(w for w in canonical(piece).split()
                       if w not in SCHEDULE_WORDS and re.search(r"[a-z]", w))
        if key:
            parts.append(key)
    parts = list(dict.fromkeys(parts))
    return parts if len(parts) > 1 else []


def _combination_products(conn, company_id: int) -> dict[int, set[str]]:
    """asset_id -> the molecules it holds, for each of one company's products that holds
    more than one.

    The ingredient list is drugsfda's, where the approvals fetch stored one. A generic
    name is not read for it: "Tetanus Toxoid, Reduced Diphtheria Toxoid and Acellular
    Pertussis Vaccine" is one vaccine, not three products. A single-agent product is
    absent, since its generic name binds a study of that molecule given alongside
    anything.
    """
    out: dict[int, set[str]] = {}
    for row in conn.execute(
            "SELECT id, active_ingredients FROM assets"
            " WHERE owner_company_id = ?", (company_id,)):
        try:
            listed = json.loads(row["active_ingredients"] or "[]")
        except (TypeError, ValueError):
            listed = []
        held = {canonical(str(i)) for i in listed if i} - {""}
        if len(held) > 1:
            out[row["id"]] = held
    return out


def _holds(asset_id: int, matched: str, parts, names, combinations) -> bool:
    """Whether a match on one ingredient's name stands when the intervention combines
    compounds.

    Troxyca ER is oxycodone with naltrexone, filed under naltrexone. "Naltrexone SR 32
    mg/bupropion SR 360 mg/day" is Contrave, a different combination sharing one molecule
    with it, and the shared molecule named the product. Where the name that matched is
    one ingredient of a combination product, every compound in the intervention now has
    to be one the product holds, by an ingredient or by one of its own names.

    Nothing else is tested. A product holding one molecule is not, so "Durvalumab +
    Tremelimumab" still binds to Imfinzi. Nor is a match on a name that is the product's
    own rather than one ingredient's, a brand, a code or "E/C/F/TAF", since that names
    the product whatever else the arm lists.
    """
    held = combinations.get(asset_id) if combinations else None
    if not parts or not held or canonical(matched) not in held:
        return True
    known = held | {n for n, a in names if a == asset_id}
    return all(any(f" {k} " in f" {p} " for k in known) for p in parts)


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
    # Where two of a company's rows answer to the same name, they are the same molecule
    # under two brands: Ozempic and Wegovy are both semaglutide. The molecule's holder
    # takes it, so the study lands on the row the drug has been known by longest instead
    # of on whichever was fetched first. The siblings reach it through molecule_id.
    holders = {r[0] for r in conn.execute(
        "SELECT id FROM assets WHERE molecule_id = id")}
    best: dict = {}
    for name, asset_id in names:
        current = best.get(name)
        if current is None or (asset_id in holders and current not in holders) \
                or (asset_id < current and (current not in holders
                                            or asset_id in holders)):
            best[name] = asset_id
    names = sorted(best.items(), key=lambda n: len(n[0]), reverse=True)
    return names


def match_intervention(intervention_norm: str, names: list[tuple[str, int]],
                       parts=(), combinations=None) -> int | None:
    """The asset an intervention names, or None.

    An exact match wins outright. Otherwise the longest asset name that appears in the
    intervention as a whole word takes it, so "Tirzepatide 5 mg" and "LY3437943 injection"
    both bind while "insulin" does not sweep up a whole portfolio. Where the intervention
    combines compounds (``parts``, from ``components``) a combination product is only
    named when it holds them all (``_holds``). Pure, so the rule is testable without a
    database.
    """
    if not intervention_norm:
        return None
    for norm, asset_id in names:
        if norm == intervention_norm and _holds(asset_id, norm, parts, names,
                                                     combinations):
            return asset_id
    for norm, asset_id in names:
        if len(norm) < MIN_SUBSTRING_LEN:
            continue
        if re.search(rf"(?:^|\s){re.escape(norm)}(?:\s|$)", intervention_norm) \
                and _holds(asset_id, norm, parts, names, combinations):
            return asset_id
    return None


def match_name(raw: str, names, combinations=None) -> int | None:
    """``match_intervention`` on a raw intervention name, which is what carries the join
    between the compounds of a combination."""
    return match_intervention(normalise(raw), names, components(raw), combinations)


def first_match(raw_names, names, combinations=None) -> int | None:
    """The asset the first of a study's interventions to name one names, or None."""
    return next((a for a in (match_name(r, names, combinations) for r in raw_names)
                 if a), None)


def _refuted(current, raw_names, names, combinations) -> bool:
    """Whether a study bound to a combination product named it only through a different
    combination that shares one of its molecules, so the binding does not stand.

    Only such a binding is undone. One made by the analyst, by a brand split or by any
    name this test does not reach is left as it is.
    """
    if current is None or current not in (combinations or {}):
        return False
    own = [(n, a) for n, a in names if a == current]
    hits = [r for r in raw_names if match_intervention(normalise(r), own) == current]
    return bool(hits) and not any(
        match_name(r, own, combinations) == current for r in hits)


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
            if (not key or NOT_A_COMPOUND.search(normalise(row["name"]))
                    or REGIMEN_WORDS.search(key)):
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
        # Every column that points at a row, including the assets table's own
        # molecule_id: a row named as the head of a molecule cannot be deleted out from
        # under the rows naming it, which is the foreign key that stopped the daily
        # refresh for five days one function over.
        guards = "".join(
            f"\n               AND NOT EXISTS (SELECT 1 FROM {table} x"
            f" WHERE x.{column} = assets.id"
            + (" AND x.id <> assets.id" if table == "assets" else "") + ")"
            for table, column in assets_util.referring_columns(conn))
        cur = conn.execute(
            f"DELETE FROM assets WHERE is_marketed = 0{guards}")
        conn.commit()
        return {"pruned": cur.rowcount}
    finally:
        conn.close()


def _studies(conn, table: str) -> list:
    """Every sponsored study in one table with its binding and its drugs' raw names.

    Raw names rather than the stored normalised ones, since only the raw name still says
    which words are two compounds joined and which are one compound and its dose.
    """
    studies: dict = {}
    for row in conn.execute(
            f"""
            SELECT t.nct_id, t.sponsor_company_id AS cid, t.asset_id, i.name
              FROM {table} t
              JOIN trial_interventions i ON i.nct_id = t.nct_id
             WHERE t.sponsor_company_id IS NOT NULL
             ORDER BY t.nct_id, i.id
            """):
        entry = studies.setdefault(row["nct_id"], {
            "nct_id": row["nct_id"], "cid": row["cid"], "asset_id": row["asset_id"],
            "names": []})
        if row["name"]:
            entry["names"].append(row["name"])
    return list(studies.values())


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

        names_by_company: dict[int, tuple] = {}

        def known(cid):
            if cid not in names_by_company:
                names_by_company[cid] = (_asset_names(conn, cid),
                                         _combination_products(conn, cid))
            return names_by_company[cid]

        matched = unbound = 0
        for row in _studies(conn, "trials"):
            if row["nct_id"] in overrides:
                continue                      # the analyst has already answered this one
            names, combinations = known(row["cid"])
            asset_id = first_match(row["names"], names, combinations)
            if asset_id is not None:
                conn.execute("UPDATE trials SET asset_id = ? WHERE nct_id = ?",
                             (asset_id, row["nct_id"]))
                matched += 1
            elif _refuted(row["asset_id"], row["names"], names, combinations):
                conn.execute("UPDATE trials SET asset_id = NULL WHERE nct_id = ?",
                             (row["nct_id"],))
                unbound += 1
        conn.commit()

        # Completed studies are bound by the same rule and from the same stored names,
        # so an improvement to the cleaner reaches a product's record as well as its
        # pipeline without anything being fetched again. A bound study is looked at again
        # only to undo a binding the combination rule refutes.
        completed_matched = 0
        for row in _studies(conn, "completed_trials"):
            names, combinations = known(row["cid"])
            if row["asset_id"] is not None:
                if not _refuted(row["asset_id"], row["names"], names, combinations):
                    continue
                asset_id = first_match(row["names"], names, combinations)
                conn.execute("UPDATE completed_trials SET asset_id = ? WHERE nct_id = ?",
                             (asset_id, row["nct_id"]))
                unbound += asset_id is None
                completed_matched += asset_id is not None
                continue
            asset_id = first_match(row["names"], names, combinations)
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
            "combination_unbound": unbound,
            "mapped": mapped, "total": total,
            "unmapped": total - mapped, "curated": len(overrides),
            "no_interventions": no_interventions}


def prune_arms(db_path=None, dry_run: bool = False) -> dict:
    """Retire asset rows that are a study's arm rather than a compound.

    The rules above decide what a name means, and they have grown as the registry showed
    what it contains. Rows created under the older, looser rules are still here: a dose
    in micrograms the unit list did not know, a fixed-dose strength written as a ratio,
    a numbered dose regimen, a molecule named with the chemotherapy it was given
    alongside. Each became its own programme, so AstraZeneca's pipeline counted five
    inhaler strengths as five assets.

    Only rows anchored by nothing are considered. An approval, a revenue figure, an
    assumption or an exclusivity means something outside the registry vouches for the
    asset, and none of those is overruled by a name.

    Two outcomes, and no third. Where the name now canonicalises onto another asset of
    the same company, the trials move to it and the arm goes, because they are one
    programme spelled twice. Where it canonicalises onto nothing, the arm goes and its
    trials keep their own records and lose the mapping, which is what this module already
    does with a trial mapped to the wrong row.
    """
    import db as db_module

    conn = db_module.get_connection(db_path)
    merged = retired = 0
    moved_trials = 0
    detail = []
    try:
        loose = conn.execute(
            """
            SELECT a.id, a.owner_company_id,
                   COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name
              FROM assets a
             WHERE NOT EXISTS (SELECT 1 FROM approvals x WHERE x.asset_id = a.id)
               AND NOT EXISTS (SELECT 1 FROM asset_revenue x WHERE x.asset_id = a.id)
               AND NOT EXISTS (SELECT 1 FROM assumptions x WHERE x.asset_id = a.id)
               AND NOT EXISTS (SELECT 1 FROM exclusivities x WHERE x.asset_id = a.id)
            """).fetchall()
        # Every asset's canonical key, so an arm can find the programme it belongs to.
        keys = {}
        for row in conn.execute(
                "SELECT id, owner_company_id, brand_name, generic_name, internal_code"
                "  FROM assets"):
            for spelling in (row["brand_name"], row["generic_name"],
                             row["internal_code"]):
                key = canonical(spelling or "")
                if key:
                    keys.setdefault((row["owner_company_id"], key), row["id"])

        for row in loose:
            name = row["name"] or ""
            key = canonical(name)
            rejected = (not key or NOT_A_COMPOUND.search(normalise(name))
                        or REGIMEN_WORDS.search(key))
            target = keys.get((row["owner_company_id"], key)) if key else None
            if target == row["id"]:
                target = None
            if not rejected and target is None:
                continue                       # a compound this module still recognises
            if target is not None:
                n = conn.execute(
                    "UPDATE trials SET asset_id = ? WHERE asset_id = ?",
                    (target, row["id"])).rowcount
                moved_trials += n
                merged += 1
                detail.append((name, "merged", n))
            else:
                retired += 1
                detail.append((name, "retired", 0))
            for table, nullable in _arm_tables(conn):
                if nullable:
                    conn.execute(
                        f"UPDATE {table} SET asset_id = NULL WHERE asset_id = ?",
                        (row["id"],))
                else:
                    conn.execute(f"DELETE FROM {table} WHERE asset_id = ?", (row["id"],))
            conn.execute("DELETE FROM assets WHERE id = ?", (row["id"],))
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return {"merged": merged, "retired": retired, "trials_moved": moved_trials,
            "detail": detail}


def _arm_tables(conn) -> list:
    """(table, whether asset_id may be null) for every table keyed on an asset."""
    out = []
    for name in [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]:
        if not any(fk[2] == "assets" and fk[3] == "asset_id"
                   for fk in conn.execute(f'PRAGMA foreign_key_list("{name}")')):
            continue
        nullable = not any(c[1] == "asset_id" and c[3]
                           for c in conn.execute(f'PRAGMA table_info("{name}")'))
        out.append((name, nullable))
    return out
