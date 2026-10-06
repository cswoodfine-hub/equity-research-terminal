"""Who prescribes a brand in Medicare, which Part D plans cover it, and how often Medicaid
fills it: a read-only view over the four payer tables.

The tables come from four fetchers (``fetchers/codes_rxnav.py``,
``fetchers/prescribers_cms.py``, ``fetchers/utilization_medicaid.py`` and
``fetchers/formulary_cms.py``). This module only reads them. Nothing in a forecast,
valuation, fair value, probability or rating reads it, and
``tests/test_payer_access.py`` holds that by a static guard: every figure here is gross
of rebates or a count of plans, and neither is revenue.

Three blocks, each with its own scope label, period and caveats, kept apart because each
is a different population counted by a different file:

- prescribing, from CMS's Medicare Part D Prescribers files. The national figures count
  every Part D prescriber and beneficiary; the file figures count only prescribers with
  11 or more claims for the drug, and say so.
- formulary, from CMS's monthly Part D formulary file: formularies and plans, not people.
- medicaid, from the State Drug Utilization Data: prescriptions per quarter, before
  rebates.

The Medicare patient count here is the Prescribers file's. The Spending by Drug file that
the demand view reads counts a slightly different set (Eliquis 2024: 4,423,497 here,
4,424,796 there), so the two are never put in one figure; where this view cites Spending
by Drug at all, for the Part B share of a drug's Medicare spend, it names that file.

A block with nothing behind it is None, and ``why_empty`` says why in words taken from
the data: a drug Medicare pays for under Part B, a brand with no RxNorm code yet, a code
with no Medicaid claims. Never "no free data" where the reason is known.

A brand two companies sell (Eliquis, BMS and Pfizer) is shown whole on both pages, with
the label saying so. ``for_company`` lists brands and never totals them, since a total
over a co-marketed brand and a book duplicate would count the same prescriptions twice.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import db
from fetchers.codes_rxnav import ATTRIBUTION

PRESCRIBING_SOURCE = ("CMS Medicare Part D Prescribers, by Geography and Drug (national) "
                      "and by Provider and Drug")
FORMULARY_SOURCE = ("CMS Monthly Prescription Drug Plan Formulary and Pharmacy Network "
                    "Information")
MEDICAID_SOURCE = "Medicaid State Drug Utilization Data"
CODES_SOURCE = "RxNav, U.S. National Library of Medicine"

CO_MARKETED_LABEL = "Brand totals, not this company's share"
FILE_POPULATION = "prescribers with 11 or more claims for the drug (the file population)"
PROXY_LABEL = "a proxy, not a PDC"
# Above 1 is not one story. Lamictal XR (1.04 in 2024), Kuvan and Emflaza are taken
# daily and still pass 1, through overlapping or short fills; Fabrazyme (1.53) is
# infused every two weeks, and each of its fills counts as a full 30-day one.
PROXY_CAVEAT = (
    "Days covered is 30-day fills times 30 over beneficiaries times 365: a proxy, not a "
    "PDC. It falls when patients start or stop during the year as well as when they miss "
    "doses. It can pass 1 where supplies overlap, as when two strengths are filled "
    "together or a refill comes early, and where fills run under 30 days, since CMS "
    "counts each as one 30-day fill, as for a drug given every week or two.")
FILE_CAVEAT = (
    "The provider file leaves out any prescriber with fewer than 11 claims for the drug, "
    "so its figures, the deciles among them, describe that population and not every "
    "prescriber.")
# CMS's methodology leaves these plans out of the file, so the label says so where the
# figures are, not only in the folded caveats.
FORMULARY_EXCLUDES = "excludes employer, PACE and demonstration plans"
FORMULARY_CAVEAT = (
    "Excludes employer, PACE and demonstration plans. Counts formularies and plans, not "
    "people: the file carries no enrolment. Tiers are each plan's own, so only the "
    "specialty tier count compares across plans.")
MEDICAID_CAVEAT = (
    "Fee-for-service and managed care prescriptions. Amounts are before Medicaid rebates, "
    "so this is volume, not revenue.")
SUPPRESSION_CAVEAT = (
    "CMS suppresses small package rows, so a quarter that has any is a lower bound.")

PART_B_ONLY = ("Given in the clinic under Part B, so the Part D files do not carry it")
PART_B_FORMULARY = ("Medicare pays for it mainly under Part B, as a drug given in the "
                    "clinic, so Part D plans do not list it")
NOT_MARKETED = "Not marketed, so Medicare and Medicaid carry no claims for it"
# A Medicaid block with no brand figure to lead on is empty, with the reason, rather than
# a panel with no number in it.
MEDICAID_ALL_SUPPRESSED = ("CMS suppressed every Medicaid count on this brand's product "
                           "codes, as it does for small counts")
MEDICAID_UNBRANDED_ONLY = ("Its Medicaid claims are on unbranded products under its own "
                           "application, such as an authorised generic, which are kept "
                           "apart from the brand")
VACCINE_NOTE = ("A vaccine is given once or in a short series, so days covered says "
                "nothing about adherence")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
           "Dec")
_WORD = re.compile(r"[a-z0-9]+")


# --- small helpers --------------------------------------------------------------------
def _share(part, whole):
    return (part / whole) if part is not None and whole else None


def _month_label(day: str | None) -> str | None:
    try:
        d = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _words(*names) -> set:
    return {w for n in names if n for w in _WORD.findall(n.lower()) if len(w) >= 3}


def _shares_a_word(product_name: str | None, names: set) -> bool:
    """Whether a CMS listing name, cut to ten characters, names this brand or molecule.
    A cut word counts when it is the start of one of the asset's own words."""
    for w in _words(product_name):
        if any(n.startswith(w) or w.startswith(n) for n in names):
            return True
    return False


def _outside_rxnorm_months(year: int, quarter: int, first_ym, last_ym) -> bool:
    """Whether a quarter falls wholly outside the months RxNorm listed the code."""
    q_first, q_last = year * 100 + quarter * 3 - 2, year * 100 + quarter * 3
    try:
        if first_ym and q_last < int(first_ym):
            return True
        if last_ym and q_first > int(last_ym):
            return True
    except ValueError:
        return False
    return False


def _demand_parts(conn, asset_id: int) -> dict:
    """{part: spend} for the newest Spending by Drug year, the file the demand view reads."""
    row = conn.execute("SELECT MAX(year) FROM drug_demand WHERE asset_id = ?",
                       (asset_id,)).fetchone()
    year = row[0] if row else None
    out: dict = {"year": year, "parts": {}, "ever": set()}
    for r in conn.execute("SELECT DISTINCT part FROM drug_demand WHERE asset_id = ?",
                          (asset_id,)):
        out["ever"].add(r["part"])
    if year is not None:
        for r in conn.execute(
                "SELECT part, SUM(total_spending) AS spend FROM drug_demand"
                " WHERE asset_id = ? AND year = ? GROUP BY part", (asset_id, year)):
            out["parts"][r["part"]] = r["spend"]
    return out


def _part_b_only(demand: dict) -> bool:
    return "B" in demand["ever"] and "D" not in demand["ever"]


def _part_b_led(demand: dict) -> bool:
    b, d = demand["parts"].get("B"), demand["parts"].get("D")
    return b is not None and b > (d or 0)


def _co_owners(conn, asset_id: int, owner_id: int) -> list[str]:
    """Other companies whose own asset is this brand: a brand-specific code in common,
    or the same CMS brand rows in the newest prescriber year."""
    rows = conn.execute(
        """
        SELECT DISTINCT c.ticker FROM drug_codes d1
          JOIN drug_codes d2 ON d2.code_type = d1.code_type AND d2.code = d1.code
                            AND d2.asset_id <> d1.asset_id AND d2.brand_specific = 1
          JOIN assets a2 ON a2.id = d2.asset_id
          JOIN companies c ON c.id = a2.owner_company_id
         WHERE d1.asset_id = ? AND d1.brand_specific = 1 AND a2.owner_company_id <> ?
        UNION
        SELECT DISTINCT c.ticker FROM partd_prescribing p1
          JOIN partd_prescribing p2 ON p2.data_year = p1.data_year
                                   AND p2.cms_brands = p1.cms_brands
                                   AND p2.asset_id <> p1.asset_id
          JOIN assets a2 ON a2.id = p2.asset_id
          JOIN companies c ON c.id = a2.owner_company_id
         WHERE p1.asset_id = ? AND a2.owner_company_id <> ?
           AND p1.data_year = (SELECT MAX(data_year) FROM partd_prescribing
                                WHERE asset_id = p1.asset_id)
        """, (asset_id, owner_id, asset_id, owner_id)).fetchall()
    return sorted({r["ticker"] for r in rows})


# --- prescribing ----------------------------------------------------------------------
def _prescribing(conn, asset_id: int, demand: dict) -> dict | None:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM partd_prescribing WHERE asset_id = ? ORDER BY data_year",
        (asset_id,))]
    if not rows:
        return None
    latest = rows[-1]
    year = latest["data_year"]
    status = latest["file_status"]
    # The file figures stand only for a finished pull. A pending brand is one the run
    # budget has not reached yet, or one whose year CMS revised, whose stored figures are
    # the earlier version's; an incomplete one did not reconcile with CMS's row count.
    # Either way they are held back, with the reason, rather than shown as current.
    complete = status == "complete"
    deciles = json.loads(latest["claims_share_by_npi_decile"] or "null")
    specialties = [dict(r) for r in conn.execute(
        "SELECT specialty, prescribers, claims, claims_share"
        "  FROM partd_prescriber_specialties WHERE asset_id = ? AND data_year = ?"
        " ORDER BY (specialty = 'Other'), claims DESC", (asset_id, year))] \
        if complete else []
    share = latest["days_covered_share"]
    vaccine = conn.execute("SELECT 1 FROM asset_themes WHERE asset_id = ?"
                           " AND theme = 'Vaccine'", (asset_id,)).fetchone() is not None
    out = {
        "year": year,
        "scope_label": f"Medicare Part D only, {year}",
        "source": PRESCRIBING_SOURCE,
        "cms_brands": json.loads(latest["cms_brands"] or "[]"),
        "national": {
            # CMS lists some brands by container (Tresiba's vial and two pens) and the
            # fetcher sums them: exact for claims, fills and cost, but a prescriber or
            # patient under two containers is counted twice, so these two are ceilings.
            "upper_bound": bool((latest["presentations"] or 1) > 1),
            "prescribers": latest["national_prescribers"],
            "claims": latest["national_claims"],
            "fills_30d": latest["national_fills_30d"],
            "beneficiaries": latest["national_beneficiaries"],
            "beneficiaries_65_plus": latest["national_benes_ge65"],
            "drug_cost": latest["national_drug_cost"],
            "note": latest["national_note"],
        },
        "days_covered": {
            "value": share, "label": PROXY_LABEL, "above_one": bool(share and share > 1),
            # Held, not dropped: the figure is CMS's, but it measures nothing here.
            "applies": not vaccine, "note": VACCINE_NOTE if vaccine else None,
            "file_value": latest["days_covered_share_file"] if complete else None,
            "file_note": latest["file_note"] if complete else None,
        },
        "file": None,
        "volume_deciles": {"value": json.loads(latest["prescribers_by_volume_decile"]
                                               or "null"),
                           "note": latest["volume_decile_note"]},
        "specialties": specialties,
        "series": [{"year": r["data_year"], "prescribers": r["national_prescribers"],
                    "claims": r["national_claims"],
                    "beneficiaries": r["national_beneficiaries"],
                    "days_covered": r["days_covered_share"]} for r in rows],
        "caveats": [PROXY_CAVEAT],
        "part_b_note": None,
    }
    if status is not None:
        def figure(column):
            return latest[column] if complete else None

        out["file"] = {
            "status": status,
            "population": FILE_POPULATION,
            "why": None if complete else _file_why(status, year),
            "prescribers": figure("file_prescribers"),
            "claims": figure("file_claims"),
            "claims_share": figure("file_claims_share"),
            "deciles": deciles if complete else None,
            "top1pct": figure("top1pct_claims_share"),
            "top10pct": figure("top10pct_claims_share"),
            "prescribers_for_50pct": figure("prescribers_for_50pct"),
            "prescribers_for_80pct": figure("prescribers_for_80pct"),
            "hhi": figure("hhi"),
            "median_claims": figure("median_claims_per_prescriber"),
            "days_per_claim": figure("days_supply_per_claim"),
            "note": latest["file_note"],
        }
        out["caveats"].append(FILE_CAVEAT)
    if _part_b_led(demand):
        b, d = demand["parts"].get("B") or 0.0, demand["parts"].get("D") or 0.0
        out["part_b_note"] = (
            f"CMS Spending by Drug, {demand['year']}: Part B is "
            f"{b / (b + d):.0%} of Medicare's spend on this drug, and these Part D files "
            f"do not cover it.")
    return out


def _file_why(status: str, year: int) -> str:
    """Why a brand's provider-file figures are held back: never 'too few prescribers',
    which is a finished pull's answer."""
    if status == "pending":
        return (f"CMS's {year} provider file is not read for this brand yet; the next "
                f"refresh continues the pull")
    return (f"The {year} provider file did not match CMS's own row count for this brand, "
            f"so its figures are not shown")


def _prescribing_why(conn, asset: dict, demand: dict) -> str:
    if not asset["is_marketed"]:
        return NOT_MARKETED
    if _part_b_only(demand):
        return PART_B_ONLY
    if conn.execute("SELECT 1 FROM partd_prescriber_releases LIMIT 1").fetchone() is None:
        return "The Part D Prescribers files have not been read into this book yet"
    year = conn.execute("SELECT MAX(data_year) FROM partd_prescriber_releases"
                        " WHERE dataset = 'geography'").fetchone()[0]
    return (f"CMS lists no national Part D Prescribers row under this brand's name"
            + (f" through {year}" if year else ""))


# --- formulary ------------------------------------------------------------------------
def _plan_split(conn, asset_id: int, release: str) -> dict | None:
    """Plans listing and carrying each restriction, MA-PD and PDP apart, read from the
    newest release's entries (held for that release only)."""
    held = conn.execute("SELECT 1 FROM partd_formulary_entries WHERE release_date = ?"
                        " LIMIT 1", (release,)).fetchone()
    if held is None:
        return None
    rxcuis = [r[0] for r in conn.execute(
        "SELECT code FROM drug_codes WHERE asset_id = ? AND code_type = 'rxcui'"
        " AND brand_specific = 1", (asset_id,))]
    marks = ",".join("?" * len(rxcuis))
    # Every (formulary, RxCUI) pair through the entries' own key, which leads on the
    # formulary: an RxCUI alone would scan all 205,663 rows of a release.
    per_formulary = {r["formulary_id"]: dict(r) for r in conn.execute(
        f"""
        SELECT formulary_id, MAX(prior_auth) AS pa, MAX(step_therapy) AS st,
               MAX(quantity_limit) AS ql
          FROM partd_formulary_entries
         WHERE formulary_id IN (SELECT DISTINCT formulary_id FROM partd_plans)
           AND rxcui IN ({marks}) AND release_date = ?
         GROUP BY formulary_id
        """, (*rxcuis, release))} if rxcuis else {}
    out = {}
    for r in conn.execute("SELECT plan_type, formulary_id FROM partd_plans"
                          " WHERE suppressed = 0 AND release_date = ?", (release,)):
        t = out.setdefault(r["plan_type"], {"plans": 0, "listing": 0, "pa": 0, "st": 0,
                                            "ql": 0})
        t["plans"] += 1
        f = per_formulary.get(r["formulary_id"])
        if f:
            t["listing"] += 1
            t["pa"] += 1 if f["pa"] else 0
            t["st"] += 1 if f["st"] else 0
            t["ql"] += 1 if f["ql"] else 0
    return out


def _formulary(conn, asset_id: int, demand: dict) -> dict | None:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM partd_formulary_access WHERE asset_id = ? ORDER BY release_date",
        (asset_id,))]
    if not rows:
        return None
    a = rows[-1]
    total = a["formularies_total"]
    tiers = json.loads(a["tier_counts"] or "{}")
    month = _month_label(a["release_date"])
    out = {
        "release_date": a["release_date"],
        "contract_year": a["contract_year"],
        "scope_label": (f"Medicare Part D plans only, {month} release, contract year "
                        f"{a['contract_year']}; {FORMULARY_EXCLUDES}"),
        "source": FORMULARY_SOURCE,
        "formularies_total": total,
        "formularies_listing": a["formularies_listing"],
        "pa_formularies": a["pa_formularies"],
        "st_formularies": a["st_formularies"],
        "ql_formularies": a["ql_formularies"],
        "listed_share": _share(a["formularies_listing"], total),
        "pa_share": _share(a["pa_formularies"], total),
        "st_share": _share(a["st_formularies"], total),
        "plans_total": a["plans_total"],
        "plans_listing": a["plans_listing"],
        "mapd": {"plans": a["mapd_plans_total"], "listing": a["mapd_plans_listing"]},
        "pdp": {"plans": a["pdp_plans_total"], "listing": a["pdp_plans_listing"]},
        "pa_plans": a["pa_plans"], "st_plans": a["st_plans"], "ql_plans": a["ql_plans"],
        "by_plan_type": _plan_split(conn, asset_id, a["release_date"]),
        "tiers": [{"tier": int(t), "formularies": n}
                  for t, n in sorted(tiers.items(), key=lambda kv: int(kv[0]))],
        "specialty_plans_listing": a["specialty_plans_listing"],
        "selected_drug": bool(a["selected_drug"]),
        "rxcuis_known": a["rxcuis_known"],
        "rxcuis_listed": a["rxcuis_listed"],
        "note": a["note"],
        "zero_reason": None,
        "history": [{"release_date": r["release_date"],
                     "contract_year": r["contract_year"],
                     "listed_share": _share(r["formularies_listing"],
                                            r["formularies_total"]),
                     "pa_share": _share(r["pa_formularies"], r["formularies_total"]),
                     "st_share": _share(r["st_formularies"], r["formularies_total"])}
                    for r in rows],
        "caveats": [FORMULARY_CAVEAT],
    }
    if not a["formularies_listing"]:
        n = a["rxcuis_known"]
        out["zero_reason"] = (
            PART_B_FORMULARY if (_part_b_led(demand) or _part_b_only(demand)) else
            "Its one brand RxNorm code is on no Part D formulary in this release"
            if n == 1 else
            f"None of its {n} brand RxNorm codes is on a Part D formulary in this "
            f"release")
    return out


def _formulary_why(conn, asset: dict, demand: dict) -> str:
    if not asset["is_marketed"]:
        return NOT_MARKETED
    if _part_b_only(demand):
        return PART_B_ONLY
    release = conn.execute("SELECT MAX(release_date) FROM partd_formulary_releases"
                           ).fetchone()[0]
    if release is None:
        return "The Part D formulary file has not been read into this book yet"
    has_code = conn.execute(
        "SELECT 1 FROM drug_codes WHERE asset_id = ? AND code_type = 'rxcui'"
        " AND brand_specific = 1 LIMIT 1", (asset["id"],)).fetchone()
    if has_code is None:
        looked = conn.execute("SELECT 1 FROM drug_code_lookups WHERE asset_id = ?",
                              (asset["id"],)).fetchone()
        return ("No RxNorm code yet, so plan coverage cannot be read" if looked else
                "Not looked up in RxNorm yet, so plan coverage cannot be read")
    return (f"Its RxNorm codes arrived after the {_month_label(release)} release was "
            f"read, so the next release carries it")


# --- medicaid -------------------------------------------------------------------------
def _medicaid(conn, asset: dict) -> tuple:
    """(block, reason): the brand's Medicaid prescriptions, or None and why there is no
    brand figure when rows are on file but none can lead (the reason is None when there
    are no rows at all, and _medicaid_why answers)."""
    names = _words(asset["brand_name"], asset["generic_name"])
    rows = [dict(r) for r in conn.execute(
        """
        SELECT m.ndc9, m.year, m.quarter, m.utilization_type, m.prescriptions,
               m.total_reimbursed, m.packages, m.packages_suppressed, m.product_name,
               d.brand_specific, d.first_ym, d.last_ym
          FROM medicaid_utilization m
          JOIN drug_codes d ON d.code_type = 'ndc9' AND d.code = m.ndc9
         WHERE d.asset_id = ?
        """, (asset["id"],))]
    if not rows:
        return None, None
    kept, dropped = [], {"rows": 0, "prescriptions": 0, "codes": set()}
    for r in rows:
        # A product code reused for another drug: outside the months RxNorm listed it
        # under this brand, and CMS's own listing name names something else.
        if (_outside_rxnorm_months(r["year"], r["quarter"], r["first_ym"], r["last_ym"])
                and not _shares_a_word(r["product_name"], names)):
            dropped["rows"] += 1
            dropped["prescriptions"] += r["prescriptions"] or 0
            dropped["codes"].add(r["ndc9"])
            continue
        kept.append(r)

    def quarters(brand_specific: int) -> list[dict]:
        out: dict = {}
        for r in kept:
            if r["brand_specific"] != brand_specific:
                continue
            q = out.setdefault((r["year"], r["quarter"]), {
                "year": r["year"], "quarter": r["quarter"], "prescriptions": None,
                "ffsu": None, "mcou": None, "reimbursed": None, "lower_bound": False,
                "codes": set()})
            q["codes"].add(r["ndc9"])
            if r["packages_suppressed"]:
                q["lower_bound"] = True
            if r["prescriptions"] is not None:
                q["prescriptions"] = (q["prescriptions"] or 0) + r["prescriptions"]
                key = "ffsu" if r["utilization_type"] == "FFSU" else "mcou"
                q[key] = (q[key] or 0) + r["prescriptions"]
            if r["total_reimbursed"] is not None:
                q["reimbursed"] = (q["reimbursed"] or 0.0) + r["total_reimbursed"]
        series = [dict(v, codes=len(v["codes"])) for _, v in sorted(out.items())]
        return series

    brand = quarters(1)
    unbranded = quarters(0)
    if not brand and not unbranded:
        return None, None
    by_key = {(q["year"], q["quarter"]): q for q in brand}
    latest = next((q for q in reversed(brand) if q["prescriptions"] is not None), None)
    if latest is None:
        # Every brand quarter suppressed, or only unbranded products on file: no figure
        # to lead on, and the panel says which.
        return None, (MEDICAID_ALL_SUPPRESSED if brand else MEDICAID_UNBRANDED_ONLY)
    growth = None
    if latest:
        prior = by_key.get((latest["year"] - 1, latest["quarter"]))
        if prior and prior["prescriptions"]:
            growth = latest["prescriptions"] / prior["prescriptions"] - 1
    full_years = {r["year"] for r in conn.execute(
        "SELECT year FROM medicaid_sdud_releases WHERE fetched_at IS NOT NULL"
        " AND full_year = 1")}
    years = []
    for year in sorted({q["year"] for q in brand}):
        qs = [q for q in brand if q["year"] == year]
        rx = [q["prescriptions"] for q in qs if q["prescriptions"] is not None]
        reimbursed = [q["reimbursed"] for q in qs if q["reimbursed"] is not None]
        years.append({"year": year, "full_year": year in full_years,
                      "quarters": len(qs), "prescriptions": sum(rx) if rx else None,
                      "reimbursed": sum(reimbursed) if reimbursed else None,
                      "lower_bound": any(q["lower_bound"] for q in qs)})
    for i in range(1, len(years)):
        a, b = years[i - 1], years[i]
        b["growth"] = (b["prescriptions"] / a["prescriptions"] - 1
                       if a["prescriptions"] and b["prescriptions"] is not None
                       and a["quarters"] == b["quarters"] == 4 else None)
    if years:
        years[0].setdefault("growth", None)
    return {
        "scope_label": "Medicaid only, before rebates",
        "source": MEDICAID_SOURCE,
        "quarters": brand,
        "latest": ({"year": latest["year"], "quarter": latest["quarter"],
                    "prescriptions": latest["prescriptions"], "growth": growth,
                    "lower_bound": latest["lower_bound"]} if latest else None),
        "years": years,
        "unbranded": unbranded,
        "unbranded_note": ("Unbranded products under the brand's own application, such as "
                           "an authorised generic, are kept apart from the brand"
                           if unbranded else None),
        "reused_codes": ({"rows": dropped["rows"],
                          "prescriptions": dropped["prescriptions"],
                          "codes": sorted(dropped["codes"]),
                          "note": "Left out: product codes CMS lists under another drug's "
                                  "name in quarters RxNorm does not list them for this "
                                  "brand"} if dropped["rows"] else None),
        "caveats": [MEDICAID_CAVEAT, SUPPRESSION_CAVEAT],
    }, None


def _medicaid_why(conn, asset: dict) -> str:
    if not asset["is_marketed"]:
        return NOT_MARKETED
    if conn.execute("SELECT 1 FROM medicaid_sdud_releases WHERE fetched_at IS NOT NULL"
                    " LIMIT 1").fetchone() is None:
        return "The Medicaid State Drug Utilization Data has not been read into this book yet"
    has_code = conn.execute(
        "SELECT 1 FROM drug_codes WHERE asset_id = ? AND code_type = 'ndc9' LIMIT 1",
        (asset["id"],)).fetchone()
    if has_code is None:
        return "No product codes yet, so Medicaid claims cannot be matched"
    return "No Medicaid claims on file for this brand's NDCs"


# --- codes ----------------------------------------------------------------------------
def _codes(conn, asset_id: int) -> dict:
    counts = {(r["code_type"], r["brand_specific"]): r["n"] for r in conn.execute(
        "SELECT code_type, brand_specific, COUNT(*) AS n FROM drug_codes"
        " WHERE asset_id = ? GROUP BY code_type, brand_specific", (asset_id,))}
    lookup = conn.execute(
        "SELECT basis, rxnorm_version, looked_up_at, note FROM drug_code_lookups"
        " WHERE asset_id = ?", (asset_id,)).fetchone()
    return {
        "source": CODES_SOURCE,
        "brand_rxcuis": counts.get(("rxcui", 1), 0),
        "brand_ndc9s": counts.get(("ndc9", 1), 0),
        "unbranded_ndc9s": counts.get(("ndc9", 0), 0),
        "basis": lookup["basis"] if lookup else None,
        "rxnorm_version": lookup["rxnorm_version"] if lookup else None,
        "looked_up_at": lookup["looked_up_at"] if lookup else None,
        "attribution": ATTRIBUTION,
    }


# --- public ---------------------------------------------------------------------------
def _asset(conn, asset_id: int):
    row = conn.execute(
        "SELECT a.id, a.brand_name, a.generic_name, a.is_marketed, a.owner_company_id,"
        "       c.ticker FROM assets a JOIN companies c ON c.id = a.owner_company_id"
        " WHERE a.id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def for_asset(conn, asset_id: int) -> dict | None:
    """{prescribing, formulary, medicaid, codes, why_empty, ...} for one asset, or None
    when the asset does not exist."""
    asset = _asset(conn, asset_id)
    if asset is None:
        return None
    demand = _demand_parts(conn, asset_id)
    medicaid, medicaid_reason = _medicaid(conn, asset)
    blocks = {"prescribing": _prescribing(conn, asset_id, demand),
              "formulary": _formulary(conn, asset_id, demand),
              "medicaid": medicaid}
    why = {"prescribing": None if blocks["prescribing"] else
           _prescribing_why(conn, asset, demand),
           "formulary": None if blocks["formulary"] else
           _formulary_why(conn, asset, demand),
           "medicaid": None if blocks["medicaid"] else
           medicaid_reason or _medicaid_why(conn, asset)}
    co = _co_owners(conn, asset_id, asset["owner_company_id"])
    return {
        "asset_id": asset_id, "ticker": asset["ticker"], "brand": asset["brand_name"],
        "generic": asset["generic_name"],
        **blocks,
        "codes": _codes(conn, asset_id),
        "why_empty": why,
        "co_marketed": ({"owners": co, "label": CO_MARKETED_LABEL} if co else None),
        "attribution": ATTRIBUTION,
    }


def asset_view(db_path, asset_id: int) -> dict | None:
    conn = db.get_connection(db_path)
    try:
        return for_asset(conn, asset_id)
    finally:
        conn.close()


def for_company(conn, ticker: str) -> dict | None:
    """One row per marketed brand the company owns, with the headline figure of each
    block. Brands are listed, never totalled. None for an unknown ticker."""
    company = conn.execute("SELECT id, ticker FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
    if company is None:
        return None
    brands = []
    for r in conn.execute(
            "SELECT id FROM assets WHERE owner_company_id = ? AND is_marketed = 1"
            " ORDER BY id", (company["id"],)):
        view = for_asset(conn, r["id"])
        p, f, m = view["prescribing"], view["formulary"], view["medicaid"]
        if not (p or f or m):
            continue
        brands.append({
            "asset_id": view["asset_id"], "brand": view["brand"],
            "prescribing_year": p["year"] if p else None,
            "prescribers": p["national"]["prescribers"] if p else None,
            "prescribers_upper_bound": p["national"]["upper_bound"] if p else None,
            "claims": p["national"]["claims"] if p else None,
            "days_covered": p["days_covered"]["value"] if p else None,
            "release_date": f["release_date"] if f else None,
            "formularies_listing": f["formularies_listing"] if f else None,
            "formularies_total": f["formularies_total"] if f else None,
            "pa_formularies": f["pa_formularies"] if f else None,
            "medicaid_latest": m["latest"] if m else None,
            "co_marketed": view["co_marketed"],
            "why_empty": view["why_empty"],
        })
    brands.sort(key=lambda b: (-(b["claims"] or 0), b["brand"] or ""))
    return {"ticker": company["ticker"], "brands": brands,
            "labels": {"prescribing": "Medicare Part D only",
                       "formulary": f"Medicare Part D plans only; {FORMULARY_EXCLUDES}",
                       "medicaid": "Medicaid only, before rebates",
                       "co_marketed": CO_MARKETED_LABEL},
            "caveats": [PROXY_CAVEAT, FORMULARY_CAVEAT, MEDICAID_CAVEAT],
            "attribution": ATTRIBUTION}


def company_view(db_path, ticker: str) -> dict | None:
    conn = db.get_connection(db_path)
    try:
        return for_company(conn, ticker)
    finally:
        conn.close()
