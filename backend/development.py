"""What it costs to reach a pipeline asset's next gate, beside what passing it is worth.

A view beside the valuation, never in it. The company's R&D ratio (rd_pct x revenue in
forecast.fcff, and book_rd in the future pipeline) already pays for today's trials, so a
development cost taken off an asset's rNPV would count the same spend twice. Nothing on
the value path imports this module: not forecast, assumptions, forecast_view's sum of the
parts, company_score, breakpoints or fair_value, and a test holds that.

The gate and its odds are pos_granular's, through the legs build 2 prices
(``legs_for_inputs``): the next gate next_gate names, its chance (``p_gate``), and what the
asset is worth if it passes (the success leg, npv x pos_success at the company's share).
The headline is the user's own wording: the expected value at the next milestone less the
cost of getting there, ``p_gate x success leg - cost to reach the gate``. Because
p_gate x pos_success is the probability in force, that is today's rNPV at the company's
share less the cost to the gate. The ladder behind it runs every gate in the split to
approval and takes each later stage's cost off too, "after later trial costs".

Costs come from two published sources in ``data/development_costs.csv``, every row graded
analogue and labelled in its own price year, with no inflation step because the book holds
no price index:

- the point, Sertkaya et al. 2024 (HHS ASPE), 2018 dollars, by therapeutic area:
  - a study on the registry costs its enrolment x the area's per-patient rate for its
    phase x the share of its run still ahead, on a straight line from its start to its
    primary completion; money already spent is sunk and never counted;
  - a Phase 3 not yet registered costs the median total Phase 3 enrolment of at least
    MIN_PEERS other assets in the same MeSH indication x the Phase 3 per-patient rate, or,
    with fewer peers, Sertkaya's Phase 3 programme cost for the area, spread over the
    area's Phase 3 duration from the Phase 2 readout;
  - the FDA review is $2.6mm;
- the high bound, DiMasi, Grabowski and Hansen 2016, as its per-phase ratio to Sertkaya's
  All row. DiMasi's phase cost includes long-term animal testing and the cost of compounds
  that fail within the phase.

Only studies in an indication the forecast values count. A study in another disease, or
one whose MeSH terms match no indication, is listed and its remaining cost shown as one
separate figure, never in the headline. Where no open study at the gate sits in an
indication the forecast values, and none has been sunk into it, the cost to reach the gate
is not read: it is None with the reason, never a nil that would read as a free gate, and
the company view lists the line under ``uncosted``.

Costs are converted from US dollars into the
asset's reporting currency at the latest ECB rate, taken after tax at the asset's tax rate
where the owner is on the pharma engine, at the company's economics share (a partner's
cost is assumed to follow its share of the economics), and discounted at the asset's
WACC to 31 December of the valuation year, the anchor rNPV is discounted to.

Refused, as data and never as a guess: a marketed asset, one with no forecast, one with no
gate split (pos_granular places big pharma Phase 2 and 3 assets only), a nil probability,
stated success and failure legs, a vaccine (neither source has a vaccine class), and a
currency with no rate on file.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import pathlib
import re
import statistics

import assumptions as assumptions_module
import db
import engines
import evidence
import forecast
import forecast_view
import fx
import indication_mapping
import pos_granular
import productivity

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
COSTS = DATA_DIR / "development_costs.csv"

# The model's therapeutic areas in Sertkaya's own words. Sertkaya has no metabolic class,
# so the endocrine rates stand in for it: a mapping judgement, said in the basis. An area
# with no counterpart (Renal and hepatic, Healthy volunteers, Other, unknown) takes All.
AREA_TO_SOURCE = {
    "Oncology": "Oncology",
    "Immunology and inflammation": "Immunomodulation",
    "Metabolic": "Endocrine",
    "Neuroscience": "Central nervous system",
    "Cardiovascular": "Cardiovascular",
    "Infectious disease": "Anti-infective",
    "Respiratory": "Respiratory system",
    "Haematology": "Hematology",
    "Urology": "Genitourinary system",
    "Ophthalmology": "Ophthalmology",
}
AREA_JUDGEMENT = {"Metabolic": "Sertkaya has no metabolic class, so the endocrine rates "
                               "stand in for it"}
ALL = "All"
SOURCE_PRICE_YEAR = 2018
# The registry phase whose per-patient rate a study takes. Phase 1 and 1/2 are never
# counted: the book prices Phase 2 and 3 gates only.
RATE_PHASE = {"Phase 2": "2", "Phase 2/3": "3", "Phase 3": "3"}
# The stage each gate closes, for the DiMasi ratio.
STAGE_PHASE = {"p2_to_p3": "2", "p3_to_nda": "3", "nda_to_approval": "review"}
MIN_PEERS = 3
DAYS_A_YEAR = 365.25
REFUSALS = ("marketed", "no_forecast", "no_gate_split", "no_gate", "no_indication",
            "stated_legs", "vaccine", "no_fx_rate", "cost_table")
SERTKAYA = ("Sertkaya A, Beleche T, Jessup A, Sommers BD. Costs of Drug Development and "
            "Research and Development Intensity in the US, 2000-2018. JAMA Netw Open "
            "2024;7(6):e2415445, doi:10.1001/jamanetworkopen.2024.15445, Table 1, 2018 "
            "dollars")
DIMASI = ("DiMasi JA, Grabowski HG, Hansen RW. Innovation in the pharmaceutical industry: "
          "new estimates of R&D costs. J Health Econ 2016;47:20-33, "
          "doi:10.1016/j.jhealeco.2016.01.012, Table 2, 2013 dollars")
_VACCINE = re.compile(r"vaccin", re.I)
HIGH_LABEL = ("at DiMasi 2016's per-phase level, which includes long-term animal testing "
              "and the cost of compounds that fail within the phase; 2013 against 2018 "
              "dollars, so the ratio is if anything low")
PORTION_NOTE = "cost split assumed to follow economics_share"
PAID_NOTE = ("Already paid inside the company's R&D ratio, so none of it is taken off the "
             "value.")


class CostTableError(ValueError):
    """A row of data/development_costs.csv that cannot be read as a sourced figure."""


# --- the published figures -----------------------------------------------------------

def costs_table(path=None) -> dict:
    """{(source_id, area, phase, measure): row} from data/development_costs.csv, value as
    a float. A row without a source or a price year, or with a value that is not a
    number, is refused: the whole file is, since a cost view on part of a table would
    silently fall back to another area's rate."""
    source = pathlib.Path(path) if path else COSTS
    out = {}
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
        for number, row in enumerate(reader, start=1):
            row = {k: (v or "").strip() for k, v in row.items()}
            key = (row.get("source_id"), row.get("area"), row.get("phase"),
                   row.get("measure"))
            if not row.get("source") or not row.get("price_year"):
                raise CostTableError(f"row {number} {key}: no source or price year")
            try:
                value = float(row["value"])
                year = int(row["price_year"])
            except (KeyError, TypeError, ValueError):
                raise CostTableError(f"row {number} {key}: value or price year is not a "
                                     f"number") from None
            out[key] = {**row, "value": value, "price_year": year,
                        "n": int(row["n"]) if row.get("n") else None}
    return out


def _figure(table: dict, area: str, phase: str, measure: str) -> dict:
    """Sertkaya's figure for the area, else its All column."""
    return (table.get(("sertkaya2024", area, phase, measure))
            or table[("sertkaya2024", ALL, phase, measure)])


def dimasi_ratio(table: dict) -> dict:
    """{phase: DiMasi's mean phase cost over Sertkaya's All programme cost}."""
    return {phase: table[("dimasi2016", ALL, phase, "phase_mean_musd")]["value"]
            / table[("sertkaya2024", ALL, phase, "programme_oop_musd")]["value"]
            for phase in ("2", "3")}


def cost_area(area: str | None) -> tuple:
    """(Sertkaya's area, how it was read)."""
    mapped = AREA_TO_SOURCE.get(area or "")
    if mapped is None:
        return ALL, (f"{area or 'no area on file'} has no counterpart in Sertkaya, so the "
                     f"All column is used")
    note = AREA_JUDGEMENT.get(area)
    return mapped, (f"{area} read as Sertkaya's {mapped}" + (f": {note}" if note else ""))


# --- dates and money -----------------------------------------------------------------

def _day(text) -> dt.date | None:
    """A registry date; a month-only date is the 1st, as launch_timing reads it."""
    raw = str(text or "").strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7)):
        if len(raw) == size:
            try:
                return dt.datetime.strptime(raw, fmt).date()
            except ValueError:
                return None
    return None


def add_months(day: dt.date, months: float) -> dt.date:
    """A duration in months as days, since Sertkaya's durations are fractional."""
    return day + dt.timedelta(days=round(months * DAYS_A_YEAR / 12))


def anchor_of(valuation_year, today: dt.date) -> tuple:
    """(anchor date, basis): 31 December of the valuation year, the point rNPV is
    discounted to (forecast.periods_from), else of the last completed calendar year."""
    if valuation_year:
        return dt.date(int(valuation_year), 12, 31), "31 December of the valuation year"
    return (dt.date(today.year - 1, 12, 31),
            "31 December of the last completed year: no valuation year on file")


def pv_even(amount: float, start: dt.date, end: dt.date, rate: float,
            anchor: dt.date) -> float:
    """The present value at ``anchor`` of ``amount`` spent evenly from start to end."""
    a = (start - anchor).days / DAYS_A_YEAR
    b = (end - anchor).days / DAYS_A_YEAR
    if rate <= -1:
        raise ValueError("rate at or below -100%")
    growth = math.log1p(rate)
    if b - a < 1e-9 or growth == 0:
        return amount * (1.0 + rate) ** -((a + b) / 2)
    return amount * ((1.0 + rate) ** -a - (1.0 + rate) ** -b) / ((b - a) * growth)


def within(amount: float, start: dt.date, end: dt.date, frm: dt.date, to: dt.date) -> float:
    """The part of an even spend that falls between frm and to."""
    if end <= start:
        return amount if frm <= start <= to else 0.0
    lo, hi = max(start, frm), min(end, to)
    return amount * max(0.0, (hi - lo).days) / (end - start).days


# --- the studies ---------------------------------------------------------------------

def indication_fit(conditions, mesh_terms, modelled_mesh) -> tuple:
    """('modelled' | 'other' | 'unmapped', indications, why). A study counts only in an
    indication the forecast values, the indication guard every gate view carries."""
    browse = indication_mapping.parse_browse(mesh_terms)
    found = indication_mapping.indications_for(conditions, browse)
    terms = [t["term"] for t in found]
    if {t["id"] for t in found} & set(modelled_mesh or ()):
        return "modelled", terms, None
    blind = pos_granular.unread(terms, bool(browse["meshes"]))
    if blind:
        return "unmapped", terms, f"it {blind}"
    return "other", terms, "in an indication the forecast does not value"


def study_cost(trial: dict, per_patient: dict, today: dt.date) -> dict:
    """One registry study: its full cost at the per-patient rate, and the share of its run
    still ahead on a straight line from its start to its primary completion. What has
    been spent is sunk. A study that has not started, or has no start date, has all of
    its run ahead."""
    rate = per_patient["value"]
    enrolled = trial.get("enrollment") or 0
    full = enrolled * rate / 1e6
    start, end = _day(trial.get("start_date")), _day(trial.get("primary_completion_date"))
    if end is None:
        share, basis = None, "no primary completion date on file, so it cannot be timed"
    elif end <= today:
        share, basis = 0.0, "passed primary completion, so its cost is sunk"
    elif start is None or start >= today:
        share = 1.0
        basis = ("no start date on file, so all of its run is taken as ahead"
                 if start is None else "not started, so all of its run is ahead")
    else:
        share = (end - today).days / (end - start).days
        basis = (f"{share:.0%} of its run from {start.isoformat()} to {end.isoformat()} "
                 f"is ahead, on a straight line")
    ahead = full * (share or 0.0)
    return {"nct_id": trial["nct_id"], "phase": trial.get("phase"),
            "status": trial.get("overall_status"), "title": trial.get("title"),
            "enrollment": enrolled, "start": trial.get("start_date"),
            "primary_completion": trial.get("primary_completion_date"),
            "per_patient_usd": rate, "full_usd_mm": full, "share_ahead": share,
            "ahead_usd_mm": ahead,
            "spend_from": max(start, today).isoformat() if (start and end and share)
            else (today.isoformat() if share else None),
            "spend_to": end.isoformat() if (end and share) else None,
            "grades": {"per_patient": "analogue", "enrollment": "measured",
                       "remaining": "convention"},
            "basis": basis}


def _asset_studies(conn, asset_id: int, phases: tuple, mesh, skip: set) -> list:
    """The asset's open studies at these phases, largest first, each with its fit."""
    marks = ",".join("?" * len(phases))
    states = ",".join("?" * len(pos_granular.OPEN_STATUSES))
    out = []
    for row in conn.execute(
            f"""SELECT nct_id, phase, overall_status, start_date, primary_completion_date,
                       enrollment, conditions, mesh_terms, title FROM trials
                 WHERE asset_id = ? AND phase IN ({marks})
                   AND overall_status IN ({states})
                 ORDER BY COALESCE(enrollment, 0) DESC, nct_id""",
            (asset_id, *phases, *pos_granular.OPEN_STATUSES)):
        if row["nct_id"] in skip:
            continue
        fit, terms, why = indication_fit(row["conditions"], row["mesh_terms"], mesh)
        out.append({**dict(row), "fit": fit, "indications": terms, "fit_why": why})
    return out


def peer_index(conn) -> dict:
    """{mesh_id: {asset_id: {nct_id: enrolment}}} over every Phase 3 and 2/3 study mapped
    to an asset, active (trials) and completed (completed_trials), each study once."""
    seen, out = set(), {}
    for table in ("trials", "completed_trials"):
        for row in conn.execute(
                f"""SELECT nct_id, asset_id, conditions, mesh_terms, enrollment
                      FROM {table} WHERE asset_id IS NOT NULL
                       AND phase IN ('Phase 3', 'Phase 2/3')
                       AND COALESCE(enrollment, 0) > 0"""):
            if row["nct_id"] in seen:
                continue
            seen.add(row["nct_id"])
            found = indication_mapping.indications_for(
                row["conditions"], indication_mapping.parse_browse(row["mesh_terms"]))
            for term in found:
                out.setdefault(term["id"], {}).setdefault(row["asset_id"], {})[
                    row["nct_id"]] = row["enrollment"]
    return out


def peer_enrolment(index: dict, mesh_id: str, asset_id: int) -> dict:
    """The median of each other asset's total Phase 3 enrolment in the indication."""
    totals = sorted(sum(studies.values()) for peer, studies in
                    (index.get(mesh_id) or {}).items() if peer != asset_id)
    return {"mesh_id": mesh_id, "peers": len(totals),
            "median": statistics.median(totals) if totals else None}


# --- the stages ----------------------------------------------------------------------

def _spend(studies: list) -> list:
    return [(s["ahead_usd_mm"], _day(s["spend_from"]), _day(s["spend_to"]))
            for s in studies if s["ahead_usd_mm"] and s["spend_from"] and s["spend_to"]]


def _registry_stage(gate, studies, rates, today, *, date=None, date_basis=None):
    counted = [s for s in studies if s["fit"] == "modelled"]
    costed = [{**study_cost(s, rates[RATE_PHASE[s["phase"]]], today),
               "fit": s["fit"], "indications": s["indications"]} for s in counted]
    outside = [{**study_cost(s, rates[RATE_PHASE[s["phase"]]], today), "fit": s["fit"],
                "indications": s["indications"], "why": s["fit_why"]}
               for s in studies if s["fit"] != "modelled"]
    if date is None and costed:
        date = costed[0]["primary_completion"]
        date_basis = "primary completion of the stage's largest counted study"
    return {"gate": gate, "label": pos_granular.GATE_LABELS[gate], "route": "registry",
            "studies": costed, "outside": outside, "spend": _spend(costed),
            "cost_usd_mm": sum(s["ahead_usd_mm"] for s in costed),
            "full_usd_mm": sum(s["full_usd_mm"] for s in costed),
            "date": date, "date_basis": date_basis,
            "grade": evidence.weakest(g for s in costed for g in s["grades"].values())
            or "convention",
            "basis": (f"{len(costed)} open {'study' if len(costed) == 1 else 'studies'} in "
                      f"an indication the forecast values, at enrolment x the area's "
                      f"per-patient rate x the share of each run still ahead"
                      if costed else "no open study in an indication the forecast values "
                                     "has cost ahead of it")}


def _future_phase3(conn, asset_id, mesh, first_studies, rates, table, area_src, start,
                   peers, today, skip):
    """The Phase 3 stage after a Phase 2 gate. Per indication the forecast values: the
    registered Phase 3s if any; nil where the Phase 2 gate study is a seamless Phase 2/3;
    else the peer median enrolment, or Sertkaya's programme cost with fewer peers."""
    registered = [s for s in _asset_studies(conn, asset_id, ("Phase 3",), mesh, skip)]
    stage = _registry_stage("p3_to_nda", registered, rates, today)
    stage["route"] = "registry" if stage["studies"] else None
    covered = set()
    for study in registered:
        if study["fit"] == "modelled":
            covered |= _mesh_ids(study, mesh)
    seamless = set()
    for study in first_studies:
        if study["phase"] == "Phase 2/3" and study["fit"] == "modelled":
            seamless |= _mesh_ids(study, mesh)
    duration = _figure(table, area_src, "3", "duration_months")
    programme = _figure(table, area_src, "3", "programme_oop_musd")
    end = add_months(start, duration["value"])
    parts = []
    for mesh_id in sorted(set(mesh) - covered):
        named = conn.execute("SELECT name FROM indications WHERE mesh_id = ? ORDER BY id"
                             " LIMIT 1", (mesh_id,)).fetchone()
        disease = named["name"] if named else mesh_id
        if mesh_id in seamless:
            parts.append({"mesh_id": mesh_id, "indication": disease, "route": "seamless",
                          "cost_usd_mm": 0.0,
                          "basis": (f"{disease}: the Phase 2 gate study is a seamless Phase "
                                    f"2/3, so its Phase 3 is already counted")})
            continue
        peer = peer_enrolment(peers, mesh_id, asset_id)
        if peer["peers"] >= MIN_PEERS:
            cost = peer["median"] * rates["3"]["value"] / 1e6
            parts.append({"mesh_id": mesh_id, "indication": disease, "route": "peer",
                          "cost_usd_mm": cost, "peers": peer["peers"],
                          "median_enrollment": peer["median"],
                          "basis": (f"{disease}: no Phase 3 registered, so the median total "
                                    f"Phase 3 enrolment of {peer['peers']} other assets in "
                                    f"it, {peer['median']:,.0f}, x {rates['3']['value']:,.0f} "
                                    f"a patient")})
        else:
            parts.append({"mesh_id": mesh_id, "indication": disease, "route": "benchmark",
                          "cost_usd_mm": programme["value"], "peers": peer["peers"],
                          "basis": (f"{disease}: no Phase 3 registered and {peer['peers']} "
                                    f"peer {'asset' if peer['peers'] == 1 else 'assets'} "
                                    f"with one, under {MIN_PEERS}, so Sertkaya's Phase 3 "
                                    f"programme cost for the area, "
                                    f"${programme['value']:.1f}mm")})
    priced = [p for p in parts if p["cost_usd_mm"]]
    for part in priced:
        stage["spend"].append((part["cost_usd_mm"], start, end))
    stage["parts"] = parts
    stage["cost_usd_mm"] += sum(p["cost_usd_mm"] for p in parts)
    stage["full_usd_mm"] += sum(p["cost_usd_mm"] for p in parts)
    if priced:
        stage["route"] = "+".join(filter(None, (stage["route"], *sorted(
            {p["route"] for p in priced}))))
        stage["grade"] = evidence.weakest(
            ([stage["grade"]] if stage["studies"] else []) + ["analogue"])
        later = max([end] + [_day(s["primary_completion"]) for s in stage["studies"]
                             if _day(s["primary_completion"])])
        stage["date"], stage["date_basis"] = later.isoformat(), (
            f"the Phase 2 readout plus Sertkaya's {duration['value']:.1f}-month Phase 3 "
            f"for the area" + (", or the registered studies' own completion where later"
                               if stage["studies"] else ""))
    elif not stage["studies"]:
        stage["route"] = "seamless" if parts else "registry"
        stage["date"], stage["date_basis"] = start.isoformat(), (
            "no further Phase 3 cost: the seamless study carries it")
    stage["basis"] = "; ".join(filter(None, [stage["basis"] if stage["studies"] else None]
                                      + [p["basis"] for p in parts]))
    return stage


def _unread(stage: dict) -> dict:
    """The first stage when no open study at the gate's phases sits in an indication the
    forecast values. Nothing has been sunk into the gate and nothing is counted towards
    it, so its cost is not nil but unknown: no free data, never a zero that would read as
    a gate costing nothing to reach."""
    n = len(stage["outside"])
    where = (f": {n} open {'study sits' if n == 1 else 'studies sit'} outside them, in the "
             f"separate figure" if n else "")
    return {"unread": True, "cost_usd_mm": None, "full_usd_mm": None, "spend": [],
            "grade": None,
            "basis": ("no open study at this gate is in an indication the forecast values, "
                      "so what reaching it costs cannot be read from the registry" + where)}


def _mesh_ids(study, mesh) -> set:
    found = indication_mapping.indications_for(
        study["conditions"], indication_mapping.parse_browse(study["mesh_terms"]))
    return {t["id"] for t in found} & set(mesh)


def stages(conn, asset_id: int, legs: dict, table: dict, area_src: str, today: dt.date,
           mesh, peers: dict | None = None) -> list:
    """One stage per gate in the legs' split, each with the cost ahead of it in 2018
    dollars, pre-tax, unrisked and undiscounted, and the windows it is spent over."""
    rates = {phase: _figure(table, area_src, phase, "per_patient_usd") for phase in ("2", "3")}
    review = table[("sertkaya2024", ALL, "review", "review_oop_musd")]
    skip = set(pos_granular.read_out(conn, asset_id))
    gates = legs.get("gates") or []
    out, previous, first_studies = [], None, []
    for k, gate in enumerate(gates):
        g = gate["gate"]
        if g == "nda_to_approval":
            when = max(_day(previous) or today, today) if k else today
            not_needed = []
            if k == 0:
                not_needed = [{**study_cost(s, rates[RATE_PHASE[s["phase"]]], today),
                               "fit": s["fit"], "indications": s["indications"],
                               "why": "not needed for this gate"}
                              for s in _asset_studies(conn, asset_id, ("Phase 3", "Phase 2/3"),
                                                      mesh, skip)]
            stage = {"gate": g, "label": pos_granular.GATE_LABELS[g], "route": "review",
                     "studies": [], "outside": not_needed,
                     "spend": [(review["value"], when, when)],
                     "cost_usd_mm": review["value"], "full_usd_mm": review["value"],
                     "date": (legs.get("date") if k == 0 else None),
                     "date_basis": (legs.get("date_basis") if k == 0 else
                                    "the FDA decision follows the review; no date is "
                                    "computed here"),
                     "grade": "analogue",
                     "basis": (f"Sertkaya's FDA review out of pocket, "
                               f"${review['value']:.1f}mm, spent as the review starts")}
        elif k == 0:
            studies = _asset_studies(conn, asset_id, pos_granular.GATE_PHASES[g], mesh, skip)
            first_studies = studies
            stage = _registry_stage(g, studies, rates, today, date=legs.get("date"),
                                    date_basis=legs.get("date_basis"))
            if not stage["studies"]:
                stage.update(_unread(stage))
            elif legs.get("due") and not stage["cost_usd_mm"]:
                stage["basis"] = ("the gate study has passed primary completion, so what "
                                  "it cost is sunk and nothing is left to spend on it")
        elif g == "p3_to_nda":
            start = max(_day(previous) or today, today)
            stage = _future_phase3(conn, asset_id, mesh, first_studies, rates, table,
                                   area_src, start, peers if peers is not None
                                   else peer_index(conn), today, skip)
        else:
            # A Phase 2 gate is only ever the first in the split.
            stage = {"gate": g, "label": pos_granular.GATE_LABELS[g], "route": None,
                     "studies": [], "outside": [], "spend": [], "cost_usd_mm": 0.0,
                     "full_usd_mm": 0.0, "date": None, "date_basis": None,
                     "grade": "convention", "basis": "a Phase 2 gate after the first"}
        stage["p"] = gate["pos"]
        stage["p_implied"] = bool(gate.get("implied"))
        out.append(stage)
        previous = stage["date"] or previous
    return out


# --- the value -----------------------------------------------------------------------

def _money(stage: dict, *, rate: float, anchor: dt.date, to_ccy: float, keep: float,
           scale: float = 1.0) -> float:
    """A stage's cost as the valuation counts money: its spend discounted to the anchor
    at the asset's WACC, in the reporting currency, after tax, at the company's share."""
    usd = sum(pv_even(amount * scale, start, end, rate, anchor)
              for amount, start, end in stage["spend"])
    return usd * to_ccy * keep


def ladder(stages_: list, success_leg: float, costs: list) -> dict:
    """Backward induction from approval, every later stage's cost taken off.

    ``costs`` is each stage's cost as the valuation counts money. The value if gate k
    passes is V_k = p_(k+1) x V_(k+1) - C_(k+1), the value on approval at the top. That
    top is the success leg over the later gates' odds, so the value before later costs at
    the first gate is the success leg itself, the figure every view shows as 'if it
    passes'; it equals npv x share to the success leg's four-place rounding, and taking
    it this way keeps the reconciliation exact: today, after every stage's cost, is
    rNPV x share less the risked cost of all stages ahead. ``value_if_passed_floored`` is
    the same induction with any stage a sponsor would not fund taken at nil.

    Only the first stage's cost can be None (``_unread``): the values if each gate passes
    rest on later costs alone and still read, while that stage's net, break-even and the
    totals that need its cost are None rather than computed on a nil."""
    n = len(stages_)
    odds_after = math.prod(s["p"] for s in stages_[1:])
    top = success_leg / odds_after if odds_after > 0 else 0.0
    gross, later, floored = [0.0] * n, [0.0] * n, [0.0] * n
    gross[-1] = floored[-1] = top
    for k in range(n - 2, -1, -1):
        p, cost = stages_[k + 1]["p"], costs[k + 1]
        gross[k] = p * gross[k + 1]
        later[k] = p * later[k + 1] + cost
        floored[k] = max(0.0, p * floored[k + 1] - cost)
    values = [g - c for g, c in zip(gross, later)]
    rows = []
    for k, stage in enumerate(stages_):
        value, p, cost = values[k], stage["p"], costs[k]
        net = (p * value - cost) if cost is not None else None
        rows.append({"gate": stage["gate"], "label": stage["label"], "date": stage["date"],
                     "p": p, "cost": cost, "value_if_passed": value,
                     "ev_at_gate": p * value, "net": net,
                     "breakeven_p": (cost / value) if cost is not None and value > 0
                     else None,
                     "funds": (net >= 0) if net is not None else None,
                     "value_if_passed_floored": floored[k],
                     "floored": abs(floored[k] - value) > 1e-9 * max(1.0, abs(value))})
    first = costs[0]
    return {"label": "after later trial costs", "rows": rows, "value_on_approval": top,
            "risked_cost": (first + stages_[0]["p"] * later[0]) if first is not None
            else None,
            "value_today": (stages_[0]["p"] * values[0] - first) if first is not None
            else None}


def _refuse(base: dict, reason: str, why: str) -> dict:
    return {**base, "ok": False, "reason": reason, "why": why}


def for_asset(db_path, ticker: str, asset_id: int, today=None, *, peers=None,
              table=None) -> dict | None:
    """The cost to the asset's next gate beside what the gate is worth, or a refusal as
    data. None where the ticker is unknown or the company cannot see the asset."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        company = forecast_view._company(conn, ticker)
        if company is None:
            return None
        asset = forecast_view._accessible(conn, company["id"], asset_id, ticker)
        if asset is None:
            return None
        return _for_asset(conn, company, asset, today, peers=peers, table=table)
    finally:
        conn.close()


def _for_asset(conn, company, asset, today, *, peers=None, table=None) -> dict:
    asset_id = asset["id"]
    name = asset["brand_name"] or asset["generic_name"]
    base = {"ticker": company["ticker"], "asset_id": asset_id, "name": name,
            "price_year": SOURCE_PRICE_YEAR}
    row = conn.execute("SELECT is_marketed, generic_name, brand_name, internal_code,"
                       " owner_company_id FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if row["is_marketed"]:
        return _refuse(base, "marketed", "A marketed product has no gate ahead of it.")
    try:
        table = table if table is not None else costs_table()
    except (OSError, CostTableError) as err:
        return _refuse(base, "cost_table", f"The published cost table cannot be read: {err}.")
    inputs = assumptions_module.load(conn, asset_id, "base")
    try:
        built = forecast.build(inputs)
    except forecast.ForecastError as err:
        return _refuse(base, "no_forecast", "No forecast builds: missing "
                       + ", ".join(err.missing) + ".")
    scalars = inputs.get("scalars") or {}
    if all(scalars.get(k) is not None for k in forecast_view.LEGS):
        return _refuse(base, "stated_legs",
                       "Stated success and failure legs are on file; the cost view reads "
                       "the derived gates only.")
    if not inputs.get("pos_granular"):
        return _refuse(base, "no_gate_split",
                       "The probability is not placed by gate: pos_granular places big "
                       "pharma Phase 2 and 3 assets only.")
    legs, gathered = pos_granular.legs_for_inputs(conn, asset_id, inputs, today=today)
    if not legs or not legs.get("gates"):
        return _refuse(base, "no_gate", "No gate is left to price: the probability in "
                                        "force is nil or the Phase 3 read out negative.")
    names = [row["generic_name"], row["brand_name"], row["internal_code"],
             ((legs.get("trial") or {}).get("title"))]
    if any(_VACCINE.search(n or "") for n in names):
        return _refuse(base, "vaccine",
                       "A vaccine: neither published source has a vaccine class, and the "
                       "anti-infective rate would cost a 57,000-subject efficacy study at "
                       "well over a billion dollars.")
    unit = forecast_view.price_unit_rate(conn, row["owner_company_id"])
    if unit["currency"] != "USD" and not unit["rate"]:
        return _refuse(base, "no_fx_rate",
                       f"No exchange rate on file for {unit['currency']}.")
    to_ccy = 1.0 if unit["currency"] == "USD" else 1.0 / unit["rate"]

    share = built.get("economics_share")
    owned = row["owner_company_id"] == company["id"]
    if owned:
        portion = share if share is not None else 1.0
    else:
        portion = 1.0 - (share if share is not None else 1.0)
    rates = fx.latest_usd_rates(forecast_view._db_of(conn))
    engine = engines.assign(conn, row["owner_company_id"],
                            productivity.latest_revenue(conn, row["owner_company_id"],
                                                        rates))
    tax = scalars.get("tax_rate")
    after_tax = engine == engines.PHARMA and tax is not None
    keep = portion * ((1.0 - tax) if after_tax else 1.0)
    wacc = built["wacc"]
    anchor, anchor_basis = anchor_of(inputs.get("valuation_year"), today)
    area_src, area_basis = cost_area(inputs.get("therapeutic_area"))
    mesh = gathered.get("modelled_mesh") or []
    if not mesh:
        return _refuse(base, "no_indication",
                       "No indication the forecast values carries a MeSH descriptor, so no "
                       "study can be counted against it.")

    stages_ = stages(conn, asset_id, legs, table, area_src, today, mesh, peers)
    # A stage whose cost cannot be read stays None all the way to the headline.
    costs = [None if s.get("unread") else
             _money(s, rate=wacc, anchor=anchor, to_ccy=to_ccy, keep=keep) for s in stages_]
    ratio = dimasi_ratio(table)
    high_costs = [None if s.get("unread") else
                  _money(s, rate=wacc, anchor=anchor, to_ccy=to_ccy, keep=keep,
                         scale=ratio.get(STAGE_PHASE[s["gate"]], 1.0)) for s in stages_]
    shares = forecast_view._diluted_shares(conn, company["id"])

    def per_share(mm):
        return (mm * 1e6 / shares) if (shares and mm is not None) else None

    npv = built["npv"]
    success_leg = npv * legs["pos_success"] * portion
    p_gate = legs["p_gate"]
    first = stages_[0]

    def headline(cost):
        if cost is None:
            return {"cost": None, "cost_per_share": None, "net": None,
                    "net_per_share": None, "breakeven_p": None, "funds": None}
        net = p_gate * success_leg - cost
        return {"cost": cost, "cost_per_share": per_share(cost), "net": net,
                "net_per_share": per_share(net),
                "breakeven_p": (cost / success_leg) if success_leg > 0 else None,
                "funds": net >= 0}

    point, high = headline(costs[0]), headline(high_costs[0])
    lad = ladder(stages_, success_leg, costs)
    lad_high = ladder(stages_, success_leg, high_costs)
    for row_ in lad["rows"] + lad_high["rows"]:
        for key in ("cost", "value_if_passed", "net"):
            row_[f"{key}_per_share"] = per_share(row_[key])

    outside = [s for st in stages_ for s in st["outside"]]
    outside_stage = {"spend": _spend(outside)}
    outside_cost = _money(outside_stage, rate=wacc, anchor=anchor, to_ccy=to_ccy, keep=keep)
    year_ahead = today + dt.timedelta(days=365)
    named = [s for st in stages_ for s in st["studies"]]
    next_12m_usd = sum(within(a, f, t, today, year_ahead)
                       for a, f, t in _spend(named))
    trial = legs.get("trial") or {}
    return {
        **base, "ok": True, "currency": unit["currency"],
        "fx": unit, "portion": portion,
        "portion_basis": (PORTION_NOTE if share is not None else "the owner's own asset"),
        "tax_rate": tax if after_tax else None, "after_tax": after_tax,
        "tax_basis": (f"after tax at the asset's {tax:.1%}, the owner being on the "
                      f"pharma engine" if after_tax else
                      "pre-tax: no tax rate on file" if engine == engines.PHARMA else
                      "pre-tax: the deduction is taken only where the owner is on the "
                      "pharma engine, where it can be used now"),
        "wacc": wacc, "anchor": anchor.isoformat(), "anchor_basis": anchor_basis,
        "area": inputs.get("therapeutic_area"), "cost_area": area_src,
        "area_basis": area_basis,
        "gate": {
            "gate": legs["gate"], "label": legs["label"], "date": legs.get("date"),
            "date_basis": legs.get("date_basis"), "due": bool(legs.get("due")),
            "trial": ({k: trial.get(k) for k in ("nct_id", "phase", "status",
                                                 "primary_completion", "enrollment",
                                                 "indications")} if trial else None),
            "p": p_gate, "p_evidence": (legs.get("evidence") or {}).get("p_gate"),
            "p_published": legs.get("p_gate_published"),
            "stated_pos": legs.get("stated"), "placed": legs.get("placed"),
            "pos_success": legs["pos_success"], "pos_now": legs["pos_now"],
            "success_leg": success_leg, "success_leg_per_share": per_share(success_leg),
            "ev": p_gate * success_leg, "ev_per_share": per_share(p_gate * success_leg),
            "rnpv": built["rnpv"] * portion, "rnpv_per_share": per_share(built["rnpv"] * portion),
            **point,
            "cost_usd_mm": first["cost_usd_mm"], "full_usd_mm": first["full_usd_mm"],
            "unread": bool(first.get("unread")),
            "route": first["route"], "grade": first["grade"], "basis": first["basis"],
            "high": {**high, "label": HIGH_LABEL},
            "held": legs.get("held"), "legs_basis": legs.get("basis"),
        },
        "ladder": {**lad, "rnpv": built["rnpv"] * portion, "npv": npv * portion,
                   "value_today_per_share": per_share(lad["value_today"]),
                   "risked_cost_per_share": per_share(lad["risked_cost"]),
                   "high": {"rows": lad_high["rows"], "risked_cost": lad_high["risked_cost"],
                            "value_today": lad_high["value_today"], "label": HIGH_LABEL}},
        "stages": [{k: v for k, v in s.items() if k != "spend"} for s in stages_],
        "outside": {"studies": outside,
                    "cost_usd_mm": sum(s["ahead_usd_mm"] for s in outside),
                    "cost": outside_cost, "cost_per_share": per_share(outside_cost),
                    "note": ("Studies outside the indications the forecast values, and any "
                             "open Phase 3 not needed for an FDA gate: their remaining "
                             "cost, never in the headline.")},
        "next_12m": {"named_usd_mm": next_12m_usd,
                     "named": next_12m_usd * to_ccy * portion,
                     "basis": ("registry studies' spend in the next 12 months, pre-tax, "
                               "unrisked, undiscounted, at the company's share")},
        "sources": [SERTKAYA, DIMASI], "paid_note": PAID_NOTE,
    }


def for_company(db_path, ticker: str, today=None) -> dict | None:
    """Every counted pipeline line's next gate, failing gates first, and what the named
    trials spend in the next 12 months against the R&D the book charges its marketed
    lines in the first forecast year."""
    today = today or dt.date.today()
    rollup = forecast_view.company_rollup(db_path, ticker)
    if rollup is None:
        return None
    conn = db.get_connection(db_path)
    try:
        company = forecast_view._company(conn, ticker)
        table = costs_table()
        peers = peer_index(conn)
        rows, refused = [], []
        for line in rollup["lines"]:
            if line["is_marketed"] or not line["counted"]:
                continue
            asset = forecast_view._accessible(conn, company["id"], line["asset_id"], ticker)
            got = _for_asset(conn, company, asset, today, peers=peers, table=table)
            (rows if got["ok"] else refused).append(got)
        unit = forecast_view.price_unit_rate(conn, company["id"])
    finally:
        conn.close()
    currency = unit["currency"]
    # Each row's 12-month spend in the company's own currency, whoever owns the asset.
    to_ccy = 1.0 if currency == "USD" or not unit["rate"] else 1.0 / unit["rate"]
    marketed = [l for l in rollup["lines"] if l["is_marketed"] and l["counted"]]
    pnl_rows = [(y, r) for l in marketed + rollup["streams"]
                for y, r in zip(l.get("dcf_years") or [], l.get("pnl_share") or [])]
    first_year = min((y for y, _ in pnl_rows), default=None)
    book_rd = sum(r.get("rd") or 0.0 for y, r in pnl_rows if y == first_year)
    spend = sum(r["next_12m"]["named_usd_mm"] * r["portion"] * to_ccy for r in rows)
    ratio = (spend / book_rd) if book_rd else None
    failing = sorted((r for r in rows if r["gate"]["funds"] is False),
                     key=lambda r: r["gate"]["net"])
    passing = sorted((r for r in rows if r["gate"]["funds"] is True),
                     key=lambda r: -(r["gate"]["net_per_share"] if r["gate"]["net_per_share"]
                                     is not None else r["gate"]["net"]))
    # No open study at the gate sits in a modelled indication: the cost is not read.
    uncosted = sorted((r for r in rows if r["gate"]["funds"] is None),
                      key=lambda r: r["name"] or "")
    sentence = None
    if rows and book_rd:
        sentence = (f"The modelled pipeline's registered trials spend about "
                    f"{_mm(spend, currency)} on these gates in the next 12 months at 2018 "
                    f"prices, {ratio:.1%} of the R&D the book charges its marketed lines in "
                    f"{first_year}. The R&D ratio already pays for it, so none of it is "
                    f"taken off the value.")
    return {"ticker": rollup["ticker"], "currency": currency, "price_year": SOURCE_PRICE_YEAR,
            "failing": failing, "rows": passing, "uncosted": uncosted, "refused": refused,
            "reconciliation": {"named_spend_12m": spend, "book_rd": book_rd,
                               "book_rd_year": first_year, "ratio": ratio,
                               "basis": ("registered studies' spend in the next 12 months at "
                                         "the company's share, pre-tax and unrisked, against "
                                         "the R&D charge on the marketed lines and streams "
                                         "in the first forecast year"),
                               "sentence": sentence}}


def _mm(value: float, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5"}.get(
        currency, f"{currency} ")
    return (f"{symbol}{value / 1000:,.1f}bn" if abs(value) >= 1000
            else f"{symbol}{value:,.0f}mm")
