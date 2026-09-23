"""Loading, saving and seeding the assumption layer the forecast engine computes from.

The engine (``forecast.py``) is pure; this module is everything around it: reading an
asset's assumption rows into the nested dict the engine takes, upserting edits, the
curated seed CSV that carries the CASGEVY workbook's numbers with their own stated
sources, the phase and erosion default files, and the xlsx export an analyst can vet in
Excel. The bargain throughout is the one the roadmap fixed: the analyst owns every
number and every number carries its source; the terminal computes and never invents.
"""

from __future__ import annotations

import datetime as dt
import csv
import json
import pathlib
import re

import db
import evidence
import forecast
import product_profile
import pool_crowding
import pos_granular
import product_areas
import regional_loe

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
SEED_DIR = DATA_DIR / "assumptions"
POS_DEFAULTS = DATA_DIR / "pos_defaults.csv"
POS_BY_AREA = DATA_DIR / "pos_by_area.csv"
LAUNCH_RAMP = DATA_DIR / "launch_ramp.csv"
EROSION_DEFAULTS = DATA_DIR / "erosion_defaults.csv"
CURVE_DEFAULTS = DATA_DIR / "curve_defaults.csv"
LOE_DEFAULTS = DATA_DIR / "loe_defaults.csv"

# What the empty state asks for, per mode. Everything else refines rather than gates.
TEMPLATE = {
    "one_time": (
        ("therapy_mode", "one_time", "text"),
        ("net_price_per_patient", "net price per patient, mm USD", "value"),
        ("net_price_decline_pct", "annual fall in that net price, before any loss of "
                                  "exclusivity, which is applied separately. Omit to "
                                  "hold the price flat", "value"),
        ("cogs_per_patient", "cost of goods per patient, mm USD", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("other_costs_pct", "everything between the filed expense lines and the cash the company reports: amortisation of acquired intangibles, restructuring, the rest. Zero where they already reconcile", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate, or supply risk_free/erp/beta/cost_of_debt/debt_weight",
         "value"),
        ("forecast_start_year", "first DCF year", "value"),
        ("forecast_years", "DCF horizon, default 10", "value"),
        ("new_patients", "per indication, one row per year; or supply the pool inputs "
         "prevalence/eligible_pct/incidence/penetration_peak_pct/ramp_midpoint_year/"
         "ramp_steepness", "series"),
        ("pos_success", "PoS if the next catalyst reads out well; with pos_failure, "
         "prices the catalyst's value swing", "value"),
        ("pos_failure", "PoS if it reads out badly", "value"),
    ),
    "marketed": (
        ("therapy_mode", "marketed", "text"),
        ("base_revenue", "last reported full year of product revenue, mm", "value"),
        ("revenue_growth_pct", "near-term annual growth, before LOE erosion", "value"),
        ("terminal_growth_pct", "long-run growth the near-term rate fades to; omit to "
                                "hold the rate flat", "value"),
        ("growth_fade_years", "years over which growth fades to the long-run rate, "
                              "default 5", "value"),
        ("revenue_ceiling_musd", "the most this product can earn in a year, mm; a "
                                 "bounded market a growth rate would otherwise grow "
                                 "through. Optional", "value"),
        ("cogs_pct", "cost of goods as a share of revenue", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("other_costs_pct", "everything between the filed expense lines and the cash the company reports: amortisation of acquired intangibles, restructuring, the rest. Zero where they already reconcile", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate or CAPM components", "value"),
        ("forecast_start_year", "first DCF year", "value"),
    ),
    "franchise": (
        ("therapy_mode", "franchise", "text"),
        ("franchise_revenue", "the pool this product takes a share of, last reported "
                              "full year, mm", "value"),
        ("franchise_growth_pct", "annual growth of the pool, not of this product",
         "value"),
        ("share_now", "this product's share of the pool in the base year", "value"),
        ("share_plateau", "the share it settles at; the judgement", "value"),
        ("share_ramp_pct", "rate the gap to the plateau closes each year. Every member "
                           "of one franchise must use the same one, which is what keeps "
                           "their shares summing to one", "value"),
        ("terminal_growth_pct", "long-run growth of the pool the near-term rate fades "
                                "to", "value"),
        ("growth_fade_years", "years over which the pool's growth fades, default 5",
         "value"),
        ("cogs_pct", "cost of goods as a share of revenue", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("other_costs_pct", "everything between the filed expense lines and the cash the company reports: amortisation of acquired intangibles, restructuring, the rest. Zero where they already reconcile", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate or CAPM components", "value"),
        ("forecast_start_year", "first DCF year", "value"),
    ),
    "chronic": (
        ("therapy_mode", "chronic", "text"),
        ("net_price_per_patient", "annual net price per patient", "value"),
        ("net_price_decline_pct", "annual fall in that net price, before any loss of "
                                  "exclusivity, which is applied separately. Omit to "
                                  "hold the price flat", "value"),
        ("cogs_pct", "cost of goods as a share of revenue", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("other_costs_pct", "everything between the filed expense lines and the cash the company reports: amortisation of acquired intangibles, restructuring, the rest. Zero where they already reconcile", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate or CAPM components", "value"),
        ("discontinuation_pct", "share of the treated stock that stops each year; "
                                "chronic revenue is the stock on therapy, not new starts",
         "value"),
        ("opening_treated_patients", "patients already on therapy before the first "
                                     "forecast year; omit for a launch", "value"),
        ("forecast_start_year", "first DCF year", "value"),
        ("new_patients", "patients STARTING per year, per indication; the stock on therapy is derived from these and discontinuation_pct", "series"),
    ),
}


def _defaults(path, key_field):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out = {}
    for row in csv.DictReader(rows):
        entry = dict(row)
        for field in ("pos", "year1_pct", "decay_pct", "late_decay_pct",
                      "late_from_year"):
            # An empty cell is an absent figure, not a zero and not a string: a modality
            # with no late decay rate has to reach the engine as None.
            entry[field] = (float(entry[field])
                            if entry.get(field) not in (None, "") else None)
        out[row[key_field]] = entry
    return out


def pos_defaults() -> dict:
    """The curated phase ramp, keyed by phase, each row carrying its source."""
    return _defaults(POS_DEFAULTS, "phase")


def _approval_year(conn, asset_id: int):
    import approval_dates
    date, _route = approval_dates.first_approval(conn, asset_id)
    try:
        return int(str(date)[:4]) if date else None
    except ValueError:
        return None


def pos_by_area(path=None) -> dict:
    """{(area, phase): {pos, sample_size, note}} from the published study, so a phase 3
    oncology asset takes oncology's likelihood of approval rather than the book's."""
    source = pathlib.Path(path) if path else POS_BY_AREA
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            area, phase = (row.get("area") or "").strip(), (row.get("phase") or "").strip()
            try:
                value = float(row["pos"])
            except (TypeError, ValueError, KeyError):
                continue
            if area and phase:
                out[(area, phase)] = {"pos": value,
                                      "sample_size": (row.get("sample_size") or "").strip(),
                                      "note": (row.get("note") or "").strip()}
    return out


def launch_ramp(path=None) -> dict:
    """{curve: [(share of the climb, share of peak)], products, years_to_peak}: the
    average launch's path to its peak, measured from the launches that have made it."""
    source = pathlib.Path(path) if path else LAUNCH_RAMP
    if not source.exists():
        return {}
    curve, products = [], 0
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            try:
                curve.append((float(row["share_of_climb"]), float(row["share_of_peak"])))
                products = max(products, int(row.get("products") or 0))
            except (TypeError, ValueError, KeyError):
                continue
    # The median years from launch to peak across the same launches, which the file's
    # header states and an asset overrides with years_to_peak where its forecast names one.
    return {"curve": sorted(curve), "products": products, "years_to_peak": 9}


def loe_defaults() -> dict:
    """{modality: {years_from_launch, source, note}}, the exclusivity a product that has
    not launched yet is given from its launch year, where nothing on file sets one."""
    out = _defaults(LOE_DEFAULTS, "modality")
    for entry in out.values():
        if entry.get("years_from_launch") not in (None, ""):
            entry["years_from_launch"] = int(float(entry["years_from_launch"]))
    return out


def curve_defaults() -> dict:
    """{therapy_mode: {penetration_peak_pct, ramp_midpoint_year, source, note}}, the
    placeholder uptake curve for an indication that has every other pool input."""
    return _defaults(CURVE_DEFAULTS, "therapy_mode")


def erosion_defaults() -> dict:
    """The curated erosion shapes, keyed by modality, each row carrying its source."""
    return _defaults(EROSION_DEFAULTS, "modality")


# --- reading an asset's assumptions -----------------------------------------

def rows(conn, asset_id: int, scenario: str = "base") -> list[dict]:
    """Every assumption row for one asset and scenario, for the editor."""
    return [dict(r) for r in conn.execute(
        """SELECT a.id, a.asset_id, a.indication_id, i.name AS indication,
                  a.region, a.scenario, a.key, a.year, a.value, a.text_value,
                  a.unit, a.source, a.note, a.as_of, a.updated_at, a.evidence,
                  a.evidence_reviewed
             FROM assumptions a LEFT JOIN indications i ON i.id = a.indication_id
            WHERE a.asset_id = ? AND a.scenario = ?
            ORDER BY a.indication_id IS NOT NULL, i.name, a.key, a.year""",
        (asset_id, scenario))]


# The legs whose vintage a reader needs, because they are no longer the same age: two
# are the market's on the day they were fetched and one is a monthly published estimate.
DATED_KEYS = ("risk_free", "cost_of_debt", "erp")
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def dated(source: str | None) -> str | None:
    """The day a source says it was struck, from the first ISO date it carries.

    Read out of the source text rather than a column, because the seed CSVs have no
    date column and a value rebuilt from seed must carry the same vintage as one
    restated in place. It also means the date and the citation cannot drift apart:
    there is one string to edit.
    """
    found = _ISO.search(source or "")
    return found.group(1) if found else None


# Which stored CAPM leg each fetched series stands in for. The premium is absent on
# purpose: it is a published estimate refreshed monthly, not a rate anyone quotes, so
# it stays a stored row and is never overridden from a market series.
LIVE_RATES = {"risk_free": "DGS10", "cost_of_debt": "BAMLC0A3CAEY"}


def live_rates(conn, scalars: dict) -> dict:
    """The scalars with the fetched rates in place of the seeded ones, dated.

    Every discount rate in the book was built on a risk-free rate read by hand on one
    day and written into 382 rows. It aged: the ten-year was 4.66% when the book was
    built and 5.01% seven weeks later, and nobody refreshed it. The series has been
    fetched daily the whole time.

    The seed stays the fallback rather than the source, so an empty ``market_rates``
    still values the book, which is what every test database does. A leg the product
    does not carry is not given one: a missing row is a gap in the model and filling it
    from a market series would hide that.

    Each replaced leg leaves its vintage behind under ``<key>_as_of`` and ``<key>_series``
    so the WACC can say which day it read rather than which day it was written.
    """
    from fetchers import rates_fred

    newest = rates_fred.latest(None, conn=conn)
    if not newest:
        return scalars
    out = scalars
    for key, series in LIVE_RATES.items():
        found = newest.get(series)
        if not found or found.get("value") is None or out.get(key) is None:
            continue
        if out is scalars:
            out = dict(scalars)
        out[key] = found["value"]
        out[f"{key}_as_of"] = found["as_of"]
        out[f"{key}_series"] = series
    return out


def load(conn, asset_id: int, scenario: str = "base") -> dict:
    """The engine's input dict for one asset: scalars, indications, LOE, actuals, phase.

    Scenario rows fall back to base where the scenario does not restate them, which is
    how a bear case can change three numbers without copying forty.
    """
    merged: dict = {}
    for row in rows(conn, asset_id, "base") + (
            rows(conn, asset_id, scenario) if scenario != "base" else []):
        key = (row["indication_id"], row["region"], row["key"], row["year"])
        merged[key] = row

    scalars: dict = {}
    indications: dict = {}
    for (indication_id, _region, key, year), row in merged.items():
        value = row["value"] if row["value"] is not None else row["text_value"]
        if indication_id is None:
            if year is None:
                scalars[key] = value
            continue
        entry = indications.setdefault(
            indication_id, {"name": row["indication"], "indication_id": indication_id,
                            "scalars": {}, "series": {}})
        if year is None:
            entry["scalars"][key] = value
        else:
            entry["series"].setdefault(key, {})[int(year)] = value

    asset = conn.execute(
        "SELECT modality, brand_name, generic_name, owner_company_id, is_marketed"
        " FROM assets WHERE id = ?", (asset_id,)).fetchone()
    # The valuation rule, not the profile's: orphan exclusivity holds one indication and
    # not the molecule, so it is left out here as it is in the cliff. Kesimpta carried a
    # 2023 orphan date into the engine and was eroded from year one while growing 30%.
    # A product costs what its kind of product costs to make, not what the company's
    # whole book averages. The factor is normalised on the company's own mix, so the
    # blended ratio in the anchor year is unchanged and only its split moves
    # (modality_costs).
    # The vintage each dated leg was struck on, from its own row. live_rates replaces
    # the two it fetches and their dates with it; whatever it does not reach keeps the
    # date the analyst wrote down.
    for (indication_id, _region, key, year), row in merged.items():
        if indication_id is None and year is None and key in DATED_KEYS:
            when = dated(row["source"])
            if when:
                scalars[f"{key}_as_of"] = when

    scalars = live_rates(conn, scalars)

    import modality_costs
    if asset and scalars.get("cogs_pct") is not None:
        moved, why = modality_costs.for_asset(conn, asset["owner_company_id"],
                                              asset["modality"], scalars["cogs_pct"],
                                              asset["generic_name"])
        if moved is not None:
            scalars["cogs_pct_blended"] = scalars["cogs_pct"]
            scalars["cogs_pct"] = moved
            scalars["cogs_pct_basis"] = why

    import loe as loe_module
    found = loe_module.for_assets(conn, [asset_id], exclude_orphan=True).get(asset_id)
    loe = ({"loe": found.get("date"), "basis": found["basis"],
            "past": bool(found.get("past"))} if found else {})
    loe_year = int(loe["loe"][:4]) if loe.get("loe") else None
    actuals = [dict(r) for r in conn.execute(
        "SELECT fiscal_year, period, value FROM asset_revenue"
        " WHERE asset_id = ? ORDER BY fiscal_year, period", (asset_id,))]
    # Actuals are stored in dollars; assumptions and the workbook run in millions.
    for row in actuals:
        row["value"] = row["value"] / 1e6 if row["value"] is not None else None
    phase = conn.execute(
        """SELECT phase FROM asset_indications WHERE asset_id = ?
            ORDER BY CASE phase WHEN 'Phase 4' THEN 6 WHEN 'Phase 3' THEN 5
                     WHEN 'Phase 2/3' THEN 4 WHEN 'Phase 2' THEN 3
                     WHEN 'Phase 1/2' THEN 2 WHEN 'Phase 1' THEN 1 ELSE 0 END DESC
            LIMIT 1""", (asset_id,)).fetchone()

    # The year the valuation stands in, so a forecast that opens later is discounted for
    # the wait rather than treated as though it opened next year.
    #
    # The last COMPLETED year, which is not the same as the latest one any filer has
    # tagged: a company on a broken fiscal year has already reported an FY2026, and
    # taking that made the current year the anchor, which gave the first forecast year a
    # period of minus a half and discounted it backwards. Casgevy gained 10% of its
    # value from a sign.
    reported = conn.execute(
        "SELECT MAX(fiscal_year) y FROM financials WHERE metric = 'Revenues'"
        "  AND period_type = 'FY' AND fiscal_year < ?",
        (dt.date.today().year,)).fetchone()

    # Several drugs can be modelled against one population, and the pool identity in
    # forecast.derive_new_patients depletes the pool by this asset's patients alone. Run
    # once per competitor it hands each of them a private copy of the same people: eight
    # obesity assets between them claimed 36% of every obese adult in the United States
    # in a single year, before the marketed incumbents. The factor below is what this
    # asset keeps once the population is counted once, and it is applied here rather than
    # written into a seed so that it recomputes when any competitor's curve moves.
    crowding = []
    for entry in indications.values():
        scalars_here = entry["scalars"]
        prevalence = scalars_here.get("prevalence")
        peak = scalars_here.get("penetration_peak_pct")
        if prevalence is None or peak is None or not entry.get("indication_id"):
            continue
        factor = pool_crowding.ratios(
            conn, entry["indication_id"], scenario).get(asset_id)
        if factor is None:
            continue
        scalars_here["penetration_peak_pct"] = peak * factor
        crowding.append({"indication": entry["name"], "factor": factor,
                         "stated": peak, "applied": peak * factor})

    therapeutic_area = product_areas.area_for(conn, asset_id) if asset else None
    return {
        "scalars": scalars,
        "indications": list(indications.values()),
        # A loss known to be past with no date is carried as that, not as a year.
        "loe": ({"year": loe_year, "basis": loe.get("basis")} if loe_year
                else {"year": None, "basis": loe.get("basis"), "in_base": True}
                if loe.get("past") else None),
        "is_marketed": bool(asset["is_marketed"]) if asset else None,
        # Each region the product reports sales in, with its own exclusivity date, so a
        # market that opens early or late is eroded when it does (regional_loe).
        "regions": regional_loe.for_asset(conn, asset_id) if asset else [],
        "loe_defaults": loe_defaults(),
        "actuals": actuals,
        "valuation_year": reported["y"] if reported and reported["y"] else None,
        "phase": phase["phase"] if phase else None,
        # What each shared-pool indication kept, so the forecast can say so.
        "crowding": crowding,
        "modality": asset["modality"] if asset else None,
        "pos_defaults": pos_defaults(),
        # The area the asset's own label or trials put it in, and the published success
        # rates for it: an oncology phase 3 asset is not the same bet as a haematology one.
        "therapeutic_area": therapeutic_area,
        "pos_by_area": pos_by_area(),
        # A big pharma Phase 2 or 3 asset is placed at its gate rather than at its
        # phase's entry, with the band its modality and disease say (pos_granular).
        # None everywhere else, and the book behaves as it did.
        "pos_granular": pos_granular.for_asset(
            conn, asset_id, area=therapeutic_area,
            phase=(phase["phase"] if phase else None), scalars=scalars) if asset else None,
        # The year the product was first approved, so a marketed product with no
        # exclusivity on file can still be given the statutory term from it rather than
        # running flat for ever.
        "approval_year": _approval_year(conn, asset_id),
        "launch_ramp": launch_ramp(),
        "erosion_defaults": erosion_defaults(),
        "curve_defaults": curve_defaults(),
    }


# --- writing -----------------------------------------------------------------

def save(conn, asset_id: int, incoming: list[dict]) -> int:
    """Upsert assumption rows for one asset. Returns rows written.

    A row is identified by (indication, region, scenario, key, year); writing one that
    exists replaces its value and provenance. A row whose value and text are both empty
    deletes, which is how the editor removes a line.
    """
    written = 0
    for row in incoming:
        key = (row.get("key") or "").strip()
        if not key:
            raise ValueError("an assumption row needs a key")
        indication_id = row.get("indication_id")
        region = (row.get("region") or "US").strip()
        scenario = (row.get("scenario") or "base").strip()
        year = row.get("year")
        value, text = row.get("value"), (row.get("text_value") or "").strip() or None
        if value is None and text is None:
            conn.execute(
                """DELETE FROM assumptions WHERE asset_id = ?
                    AND IFNULL(indication_id, 0) = IFNULL(?, 0) AND region = ?
                    AND scenario = ? AND key = ? AND IFNULL(year, 0) = IFNULL(?, 0)""",
                (asset_id, indication_id, region, scenario, key, year))
            continue
        # A grade the analyst states is reviewed and kept; otherwise the rules read one
        # off the row's own source, unreviewed, so it follows the text when it changes.
        stated = (row.get("evidence") or "").strip().lower() or None
        if stated is not None and stated not in evidence.GRADES:
            raise ValueError(f"'{stated}' is not an evidence grade")
        grade = stated or evidence.grade(row.get("source"), row.get("note"), key)
        conn.execute(
            """INSERT INTO assumptions
                   (asset_id, indication_id, region, scenario, key, year, value,
                    text_value, unit, source, note, as_of, evidence, evidence_reviewed,
                    updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(asset_id, IFNULL(indication_id, 0), region, scenario, key,
                           IFNULL(year, 0))
               DO UPDATE SET value = excluded.value, text_value = excluded.text_value,
                             unit = excluded.unit, source = excluded.source,
                             note = excluded.note, as_of = excluded.as_of,
                             evidence = CASE WHEN excluded.evidence_reviewed = 1
                                              OR assumptions.evidence_reviewed = 0
                                             THEN excluded.evidence
                                             ELSE assumptions.evidence END,
                             evidence_reviewed = MAX(assumptions.evidence_reviewed,
                                                     excluded.evidence_reviewed),
                             updated_at = datetime('now')""",
            (asset_id, indication_id, region, scenario, key, year, value, text,
             row.get("unit"), row.get("source"), row.get("note"), row.get("as_of"),
             grade, 1 if stated else 0))
        written += 1
    return written


def snapshot(conn, asset_id: int, scenario: str, result: dict) -> None:
    """Write the (assumptions, outputs) pair to the snapshots table.

    Source 'forecast', so forecast history sits beside every other history the terminal
    keeps and is never overwritten. This is what a later build diffs pre-event against.
    """
    payload = {
        "scenario": scenario,
        "assumptions": rows(conn, asset_id, scenario),
        "rnpv": result.get("rnpv"), "npv": result.get("npv"),
        "wacc": result.get("wacc"), "pos": result.get("pos"),
        "revenue": result.get("revenue_after_loe"), "years": result.get("years"),
    }
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
        " VALUES ('forecast', 'asset', ?, ?)",
        (str(asset_id), json.dumps(payload)))


# --- the curated seed --------------------------------------------------------

def load_seeds(conn, directory=None) -> dict:
    """Load every CSV under data/assumptions/ into the table. Returns counts.

    Follows the asset_alias_map pattern: the file resolves ticker and brand to an asset,
    and an indication by name, so a rebuilt database reseeds itself. Rows only carry what
    an analyst wrote down; a file for a product not on file is skipped, not an error.

    The file bootstraps and never overwrites: a key that already has a row keeps it, so
    an edit made in the terminal survives every later reseed. Changing a seeded number
    therefore means editing it where it lives, not editing the file and waiting.
    """
    source_dir = pathlib.Path(directory) if directory else SEED_DIR
    written = skipped = 0
    if not source_dir.exists():
        return {"written": 0, "skipped": 0}
    for path in sorted(source_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            ticker = (row.get("ticker") or "").strip().upper()
            brand = (row.get("brand") or "").strip()
            # Brand or generic. A compound in development has no brand yet: retatrutide,
            # milvexian and every other Phase 3 asset carries a generic name and a null
            # brand, so a loader that only matched brand could seed marketed products and
            # nothing in the pipeline, which is where a forecast is worth most. Brand still
            # wins where both match, so a launched product is never shadowed by a compound
            # sharing its ingredient name.
            asset = conn.execute(
                """SELECT a.id FROM assets a JOIN companies c
                     ON c.id = a.owner_company_id
                    WHERE c.ticker = ?
                      AND (LOWER(TRIM(a.brand_name)) = LOWER(?)
                           OR LOWER(TRIM(a.generic_name)) = LOWER(?))
                    ORDER BY (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)) DESC,
                             a.is_marketed DESC, a.id LIMIT 1""",
                (ticker, brand, brand, brand)).fetchone()
            if not asset:
                skipped += 1
                continue
            indication_id = None
            if (row.get("indication") or "").strip():
                ind = conn.execute(
                    "SELECT id FROM indications WHERE LOWER(name) = LOWER(?)",
                    (row["indication"].strip(),)).fetchone()
                if not ind:
                    skipped += 1
                    continue
                indication_id = ind["id"]
            value = row.get("value")
            year = int(row["year"]) if (row.get("year") or "").strip() else None
            exists = conn.execute(
                """SELECT 1 FROM assumptions WHERE asset_id = ?
                    AND IFNULL(indication_id, 0) = IFNULL(?, 0) AND region = ?
                    AND scenario = ? AND key = ? AND IFNULL(year, 0) = IFNULL(?, 0)""",
                (asset["id"], indication_id, row.get("region") or "US",
                 row.get("scenario") or "base", row.get("key"), year)).fetchone()
            if exists:
                continue
            written += save(conn, asset["id"], [{
                "indication_id": indication_id,
                "region": row.get("region") or "US",
                "scenario": row.get("scenario") or "base",
                "key": row.get("key"),
                "year": year,
                "value": float(value) if value not in (None, "") else None,
                "text_value": row.get("text_value"),
                "unit": row.get("unit"), "source": row.get("source"),
                "note": row.get("note"), "as_of": row.get("as_of"),
                "evidence": row.get("evidence"),
            }])
    conn.commit()
    return {"written": written, "skipped": skipped}


# --- the Excel handoff -------------------------------------------------------

def export_xlsx(conn, asset_id: int, scenario: str, result: dict | None) -> bytes:
    """The canonical two-sheet workbook: Assumptions to vet, Forecast to read.

    The assumptions sheet round-trips: its columns are the seed CSV's, so a vetted copy
    can come straight back in through the uploader.
    """
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Assumptions"
    header = ("indication", "region", "scenario", "key", "year", "value", "text_value",
              "unit", "source", "note")
    sheet.append(header)
    for row in rows(conn, asset_id, scenario):
        sheet.append(tuple(row.get(k) if k != "indication" else row.get("indication")
                           for k in header))

    if result:
        out = book.create_sheet("Forecast")
        out.append(("year",) + tuple(result["years"]))
        out.append(("new patients",) + tuple(
            round(v, 1) for v in result["patients"]["total"]))
        out.append(("revenue, mm",) + tuple(
            round(v, 1) for v in result["revenue_after_loe"]))
        out.append(())
        for label, key in (("wacc", "wacc"), ("pos", "pos"), ("npv, mm", "npv"),
                           ("rnpv, mm", "rnpv")):
            out.append((label, result.get(key)))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
