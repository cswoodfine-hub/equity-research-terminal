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
# delivery vehicle. These are study design, not a drug programme.
NOT_A_COMPOUND = re.compile(
    r"^(placebo|saline|vehicle|sham|comparator|control|standard of care|soc"
    r"|rescue medication|rescue medications|best supportive care|matching placebo"
    r"|normal saline|dextrose|water|diluent|no intervention|observation)\b")


def normalise(text: str) -> str:
    """A name reduced for matching: lowercase, punctuation to spaces, collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def strip_salt(norm: str) -> str:
    """A normalised name without a trailing salt or hydrate token, or unchanged."""
    parts = norm.split()
    if len(parts) > 1 and parts[-1] in SALT_SUFFIXES:
        return " ".join(parts[:-1])
    return norm


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

        rows = conn.execute(
            """
            SELECT i.norm, MIN(i.name) AS name,
                   COUNT(DISTINCT t.sponsor_company_id) AS sponsors,
                   MIN(t.sponsor_company_id) AS company_id,
                   COUNT(DISTINCT t.nct_id) AS trials
              FROM trial_interventions i
              JOIN trials t ON t.nct_id = i.nct_id
             WHERE t.asset_id IS NULL AND t.sponsor_company_id IS NOT NULL
                   AND i.norm IS NOT NULL AND i.norm != ''
             GROUP BY i.norm
            """).fetchall()

        created = 0
        for row in rows:
            norm = row["norm"]
            if NOT_A_COMPOUND.match(norm):
                continue                       # study design, not a compound
            if aliases(row["name"]) & marketed:
                continue                       # someone's marketed drug, so a comparator
            if row["sponsors"] > 1:
                continue                       # a shared backbone, not one programme
            conn.execute(
                "INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                "  VALUES (?, ?, 0)", (row["company_id"], row["name"]))
            created += 1
            marketed |= aliases(row["name"])    # so a later spelling does not duplicate it
        conn.commit()
    finally:
        conn.close()
    return {"created": created}


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

        total = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        mapped = conn.execute(
            "SELECT COUNT(*) FROM trials WHERE asset_id IS NOT NULL").fetchone()[0]
        no_interventions = conn.execute(
            "SELECT COUNT(*) FROM trials t WHERE NOT EXISTS"
            " (SELECT 1 FROM trial_interventions i WHERE i.nct_id = t.nct_id)"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"matched": matched, "mapped": mapped, "total": total,
            "unmapped": total - mapped, "curated": len(overrides),
            "no_interventions": no_interventions}
