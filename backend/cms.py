"""CMS Medicare Spending by Drug, the real-world demand proxy.

Company revenue says what a drug earned; this says how many people took it. CMS
publishes two datasets, Part D for retail pharmacy drugs and Part B for the ones given
in a clinic, each with per-drug, per-year total spending, prescription claims and
distinct beneficiaries. The data API returns them as JSON with a column per metric per
year (Tot_Spndng_2024, Tot_Benes_2024, and so on).

This is the pure half: it turns a payload row into one record per year, and it holds
the brand matching every CMS reader shares. CMS names a drug the same way in Spending by
Drug and in the Part D Prescribers files, so the rules for reading that name live here
rather than in one fetcher, and no fetcher imports another. The network fetch lives in
each fetcher. A metric CMS suppressed for a small count comes back empty; it is read as
null, never zero.
"""

from __future__ import annotations

import re

# The two datasets, resolved from the CMS DCAT catalogue. Part D is filtered to the
# Overall rows, which total a brand across its manufacturers; Part B has no
# manufacturer split.
PART_D_URL = ("https://data.cms.gov/data-api/v1/dataset/"
              "7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data")
PART_B_URL = ("https://data.cms.gov/data-api/v1/dataset/"
              "76a714ad-3a2c-43ac-b76d-9dadf8f7d890/data")

_YEAR = re.compile(r"Tot_Spndng_(\d{4})$")


def years_in(row: dict) -> list[int]:
    """The years a payload row carries, read from its spending columns."""
    return sorted(int(m.group(1)) for k in row
                  for m in [_YEAR.match(k)] if m)


def parse_row(row: dict, part: str) -> list[dict]:
    """One record per year for a CMS drug row: brand, part, and the four volume metrics.
    A year with no spending figure is skipped; a suppressed metric is null."""
    brand = (row.get("Brnd_Name") or "").strip()
    if not brand:
        return []
    out = []
    for year in years_in(row):
        spending = _num(row.get(f"Tot_Spndng_{year}"))
        if spending is None:
            continue                       # a year the drug was not on the programme
        out.append({
            "brand": brand,
            "part": part,
            "year": year,
            "total_spending": spending,
            "total_claims": _int(row.get(f"Tot_Clms_{year}")),
            "total_beneficiaries": _int(row.get(f"Tot_Benes_{year}")),
            "total_dosage_units": _num(row.get(f"Tot_Dsg_Unts_{year}")),
        })
    return out


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


# --- brand matching -----------------------------------------------------------------
# Shared by fetchers/demand_cms.py and fetchers/prescribers_cms.py, moved here unchanged
# so that neither fetcher imports the other.

# CMS decorates a brand with a footnote marker, and sometimes with the billing code it
# reports the line under. Neither is part of the name, and an exact match against the
# decorated string silently dropped 110 of the 799 Part B lines, $6,890mm of 2024
# spending, including Prolia, Orencia, Comirnaty, Botox and the whole infliximab series.
CODE_SUFFIX = re.compile(r"\s*\((?:[A-Z]?\d{4,5})\)\s*$")


def norm(name: str) -> str:
    """A CMS drug name reduced to the name itself: footnote marker and trailing billing
    code removed, whitespace collapsed, lowercased."""
    # The marker can sit either side of the code ("Afluria Trivalent (90657)*"), so both
    # are stripped until neither is left.
    text = (name or "").strip()
    for _ in range(3):
        stripped = CODE_SUFFIX.sub("", text.rstrip("*").strip()).strip()
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).lower()


# CMS names a Part D brand by the container it ships in, and often by nothing else. There
# is no "Repatha" row: there is Repatha Sureclick, Repatha Syringe and Repatha Pushtronex.
# An exact match therefore lost the whole molecule for Repatha, Dupixent and Praluent, and
# half of it for Fasenra and Adbry, which is how a drug with 382,461 Medicare
# beneficiaries came to have no demand series at all.
#
# These words name a container a patient could have had instead of another one, so the
# counts are alternatives and add up. Three kinds of name are left unmatched on purpose.
# A different product: a route ("IV", "Intrathecal"), a salt ("Sodium", "Decanoate"), a
# release profile ("ER", "XL"), a strength ("Arthrotec 50"), a separate long-acting depot
# ("Invega Trinza"). A different ingredient under the same brand, which CMS keys
# separately and which each fetcher handles rather than here. And a phase of one course
# rather than an alternative to it: a starter pack, a titration kit or a refill is what
# the same patient takes before or after the maintenance pack, so adding its beneficiary
# count to the maintenance count counts nearly every patient twice and makes the drug look
# cheaper per patient than it is. Venclexta reads $43,064 a beneficiary on its own row and
# $36,408 with its starting pack added, and the second number is an artefact. The list
# grows by evidence, one CMS name at a time.
PRESENTATION_WORDS = (
    r"pens?|syringes?|auto-?injector|sureclick|pushtronex|flexpen|flextouch|kwikpen|"
    r"solostar|sensoready|unoready|actpen|clickject|onpro|on-body|mini|pumpcart|tempo|"
    r"nuspin|system|packs?|pak|u-\d{2,3}|\d+-pak")
PRESENTATION_TAIL = re.compile(
    r"(?:\s*\(?\s*(?:\d+\s+)?(?:" + PRESENTATION_WORDS + r")\s*\)?)+$")
_HAS_LETTER = re.compile(r"[a-z]")


def base_brand(name: str) -> str | None:
    """The brand a CMS presentation row belongs to, or None if the name is not one.

    "repatha sureclick" is Repatha in a different autoinjector; "lyrica cr" is not Lyrica
    in a different box. Only a trailing run of container words is removed, the run has to
    carry at least one word rather than only digits, and what is left has to still look
    like a name.
    """
    match = PRESENTATION_TAIL.search(name or "")
    if not match or match.start() == 0:
        return None
    if not _HAS_LETTER.search(match.group(0)):
        return None                        # "arthrotec 50" is a strength, not a pack
    head = name[:match.start()].strip()
    # "kisqali femara co-pack" strips to "kisqali femara co-", which is not a name.
    return head if head and not head.endswith("-") else None


def brand_map(conn) -> dict:
    """{normalised name: asset_id}, by brand and then by generic name.

    CMS names a clinician-administered line by its ingredient where the code covers
    several brands: J1745 is "Infliximab*", not Remicade. A generic is only used
    where exactly one asset carries it, so an ingredient two companies both sell
    (Dupixent under Regeneron and Sanofi) resolves to neither rather than the wrong
    one. Brands always win over generics.
    """
    brands, generics, seen = {}, {}, {}
    for row in conn.execute(
        "SELECT id AS asset_id, brand_name, generic_name FROM assets"):
        if row["brand_name"]:
            brands.setdefault(norm(row["brand_name"]), row["asset_id"])
        if row["generic_name"]:
            key = norm(row["generic_name"])
            seen[key] = seen.get(key, 0) + 1
            generics.setdefault(key, row["asset_id"])
    for key, count in seen.items():
        if count == 1 and key not in brands:
            brands[key] = generics[key]
    return brands


def brand_assets(conn) -> dict:
    """{normalised name: [asset_id, ...]}: every asset a CMS brand belongs to.

    ``brand_map`` keeps one asset per name, which is right for a table keyed on the asset
    and wrong for a co-marketed brand: Eliquis is carried by Bristol-Myers Squibb and by
    Pfizer, Dupixent by Regeneron and by Sanofi, and a brand-level fact belongs on both
    pages. So every asset carrying the brand is returned, but only where it is the same
    molecule as the one ``brand_map`` chose: two assets that share a brand name and not
    an ingredient are a naming accident, and the second one gets nothing rather than a
    figure for a drug it is not.
    """
    first = brand_map(conn)
    generic_of, by_name = {}, {}
    for row in conn.execute(
            "SELECT id, brand_name, generic_name FROM assets ORDER BY id"):
        generic_of[row["id"]] = norm(row["generic_name"] or "")
        if row["brand_name"]:
            by_name.setdefault(norm(row["brand_name"]), []).append(row["id"])
    out = {}
    for key, chosen in first.items():
        molecule = generic_of.get(chosen)
        siblings = [a for a in by_name.get(key, [])
                    if a == chosen or (molecule and generic_of.get(a) == molecule)]
        out[key] = siblings or [chosen]
    return out


def own_names(conn) -> dict:
    """{asset_id: (own brand, own generic)}, both normalised: what a candidate row has
    to carry to count as the asset itself rather than something CMS lists near it."""
    return {row["id"]: (norm(row["brand_name"] or row["generic_name"] or ""),
                        norm(row["generic_name"] or ""))
            for row in conn.execute(
                "SELECT id, brand_name, generic_name FROM assets")}


def match_brand(raw_name: str, names: dict):
    """(what the CMS name matched, the brand it was read as), or (None, name).

    An exact match on the normalised name first, then the brand left once a trailing
    container is removed. ``names`` is ``brand_map`` or ``brand_assets``; the first
    value comes back as that map holds it.
    """
    name = norm(raw_name)
    hit = names.get(name)
    if hit is None:
        head = base_brand(name)
        if head:
            hit = names.get(head)
            if hit is not None:
                return hit, head
    return hit, name


def is_generic_row(brnd: str, gnrc: str) -> bool:
    """True when CMS lists the drug under its own ingredient name: a generic row.

    Brand prescribing is the question the Part D Prescribers files answer here, and a
    blend of Crestor and generic rosuvastatin answers nothing (the reasoning in
    ``fetchers/demand_cms._combine_presentations``). A row with no generic name is not
    called generic on a guess.
    """
    brand, generic = norm(brnd), norm(gnrc)
    return bool(brand) and bool(generic) and brand == generic

