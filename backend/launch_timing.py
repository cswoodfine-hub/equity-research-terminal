"""The earliest a pipeline asset can be approved, beside the year the model starts it.

Every pipeline forecast starts on a seeded ``forecast_start_year``, the first full year on
sale, and 82 of the book's seeds for unmarketed assets say only "the first full year after
the current one". Nothing checked that year against what the registry and the FDA allow.
This does, and does nothing else: it is a flag. Nothing here feeds forecast.build,
assumptions.load or any valuation, and it never writes.

The floor is the most lenient reading the evidence on file allows, so a flag is a seed the
evidence cannot reach rather than one it merely makes unlikely:

- the strongest evidence wins: an accepted application (a PDUFA or regulatory-decision
  catalyst that is not a supplement) whose decision date is ahead; else a positive Phase 3
  readout, as ``pos_granular.stage_of`` reads one (its name-matched readouts and the
  resolved readout catalysts it counts in a modelled indication); else the registry's
  earliest primary completion among the asset's live Phase 3 and Phase 2/3 studies, in
  any indication, so a study missing its MeSH descriptor can never create a flag;
- the submission goes in the day that evidence lands, with no lag, because no free source
  measures the lag;
- the review is a priority one, the shortest statutory clock for the pathway, from
  ``data/fda_review_clock.csv`` (the PDUFA VII letter: 8 months from receipt for a new
  molecule or original biologic, 6 for a new indication of a marketed one).

The year a standard review gives is reported beside it for context and decides nothing.

The seed is a first full year, so a seed before the year of the earliest decision starts
selling before any approval could land: ``before_floor``, red. Where the seed's own source
cites a filing or a readout the database does not hold, the reader is told to record it
instead: ``before_floor_cited``, amber. A seed equal to the decision year starts in the
approval year itself (``part_year``), which some seeds do on purpose and is information
only. Everything else is ``clear``. A passed decision on an asset still unmarketed, an
asset with nothing to date from, a pathway with no clock on file and a nil probability are
reported and never flagged.

The pathway is read from the asset's name and rows, and says how: an Amgen ABP code or the
word biosimilar is a biosimilar (no clock on file until the BsUFA letter is read), a
molecule its company already sells is an efficacy supplement, anything else a new
molecule or original biologic. A non-NME NDA cannot be told apart from what the database
holds, so its rows in the clock file are carried and never selected.

The next gate is pos_granular's, through the legs the verdict prices, so the earliest
approval from that gate sits beside the gate's own odds; where the study that sets the
floor is not the gate study, the message names the gate study.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import pathlib
import re

import applications
import pos_granular

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
CLOCK = DATA_DIR / "fda_review_clock.csv"
VOUCHERS = DATA_DIR / "national_priority_vouchers.csv"

# The flagged statuses and their colour. Every other status is information.
FLAGS = {"before_floor": "red", "before_floor_cited": "amber"}
STATUSES = ("before_floor", "before_floor_cited", "part_year", "clear", "decision_passed",
            "no_registry_basis", "no_clock", "not_assessed")
# Red first, as the route and the check tool list them.
STATUS_ORDER = {status: i for i, status in enumerate(STATUSES)}

# The registry phases a filing can rest on, and the statuses that mean a study is not.
REGISTRY_PHASES = ("Phase 3", "Phase 2/3")
NOT_LIVE = ("Withdrawn", "Terminated", "Suspended")
# A study the daily fetch has not returned for this long has left the registry's active
# list, most often because it completed; its last row stays and is marked so.
STALE_DAYS = 10

PATHWAY_WORDS = {"nme_nda_or_original_bla": "a new molecule or original biologic",
                 "efficacy_supplement": "a new indication of a marketed molecule",
                 "non_nme_nda": "a non-NME NDA", "biosimilar_351k": "a biosimilar"}

# What a seed's own source can cite that the database may not hold. Only ever softens a
# red flag to amber: a match never creates a flag.
_FILING = re.compile(
    r"PDUFA|target action date|action date|\baccepted\b|\bsubmitted\b|"
    r"regulatory submission|under (?:priority )?review|National Priority Voucher|"
    r"accelerated approval|launch opportunit|first submission", re.I)
_READOUT = re.compile(r"met (?:its|the) primary|positive (?:topline|results|readout)|"
                      r"interim analysis", re.I)
# "No filing, acceptance or PDUFA date is stated" cites nothing.
_NEGATED = re.compile(r"\b(?:no|not)\s", re.I)
NEGATION_WINDOW = 40

_BIOSIMILAR = re.compile(r"^ABP\s?\d|biosimilar", re.I)

_UNSET = object()


# --- dates ---------------------------------------------------------------------------

def parse_date(text) -> dt.date | None:
    """A registry or catalyst date. 'YYYY-MM' is the 1st of the month and 'YYYY' the 1st
    of January, the lenient end of each; None where it is not a date."""
    raw = str(text or "").strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        if len(raw) == size:
            try:
                return dt.datetime.strptime(raw, fmt).date()
            except ValueError:
                return None
    return None


def add_months(day: dt.date, months: int) -> dt.date:
    """Calendar months, the day clamped to the month's last: never days x 30."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month(day: dt.date | None) -> str | None:
    return day.strftime("%b %Y") if day else None


def _when(text) -> str | None:
    """A stored date as a reader says it: '30 Nov 2026' where the day is known, else the
    month."""
    day = parse_date(text)
    if day is None:
        return None
    return (f"{day.day} {day.strftime('%b %Y')}" if len(str(text).strip()) == 10
            else _month(day))


# --- the curated files ---------------------------------------------------------------

def _rows(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(line for line in handle
                                   if not line.lstrip().startswith("#")))


def review_clock(path=None) -> dict:
    """{(pathway, review): row} from data/fda_review_clock.csv, months as an int. A
    missing file is an empty clock, and every asset then reads ``no_clock``."""
    out = {}
    for row in _rows(pathlib.Path(path) if path else CLOCK):
        try:
            months = int(row["months_from_receipt"])
        except (KeyError, TypeError, ValueError):
            continue
        out[(row["pathway"].strip(), row["review"].strip())] = {
            **{k: (v or "").strip() for k, v in row.items()}, "months": months}
    return out


def vouchers(path=None) -> list[dict]:
    """The national priority voucher holders transcribed from FDA's announcements."""
    return [r for r in _rows(pathlib.Path(path) if path else VOUCHERS)
            if (r.get("asset_name_match") or "").strip()]


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# --- what the asset is ---------------------------------------------------------------

def pathway_of(conn, asset: dict) -> tuple:
    """(pathway, how it was read). Read from the asset's own name and rows, and says so,
    so a reader can argue with it."""
    names = [asset.get(k) for k in ("generic_name", "brand_name", "internal_code")]
    if any(_BIOSIMILAR.search(n or "") for n in names):
        return "biosimilar_351k", "read from the asset's name, which is a biosimilar's"
    supplemental, why = applications.is_supplemental(conn, asset["id"], "", "")
    if supplemental:
        return "efficacy_supplement", f"{why}, so a new indication is a supplement"
    return ("nme_nda_or_original_bla",
            "no marketed row for this molecule, so read as a new molecule or original "
            "biologic")


def seed_basis(text) -> dict:
    """What the seed's own source cites: a filing, a readout or nothing. A match preceded
    within 40 characters by 'no' or 'not' cites nothing."""
    source = text or ""
    for kind, pattern in (("filing", _FILING), ("readout", _READOUT)):
        for match in pattern.finditer(source):
            before = source[max(0, match.start() - NEGATION_WINDOW):match.start()]
            if _NEGATED.search(before):
                continue
            return {"cites": kind, "match": match.group(0)}
    return {"cites": None, "match": None}


def _seed(conn, asset_id: int, scenario: str = "base"):
    """(year, source, scenario) of the asset-level start year: the scenario's own row,
    else base's, as a scenario inherits."""
    for wanted in dict.fromkeys((scenario, "base")):
        row = conn.execute(
            """SELECT value, source FROM assumptions
                WHERE asset_id = ? AND key = 'forecast_start_year' AND scenario = ?
                  AND indication_id IS NULL AND year IS NULL AND value IS NOT NULL
                ORDER BY region = 'US' DESC LIMIT 1""", (asset_id, wanted)).fetchone()
        if row is not None:
            return int(row["value"]), (row["source"] or "").strip(), wanted
    return None


def _filings(conn, asset_id: int, today: str) -> dict:
    """The asset's accepted applications that seek a first approval: the earliest one
    still ahead, the latest one passed, and the supplements left out with why."""
    marks = ",".join("?" * len(applications.FILED_KINDS))
    ahead, passed, supplements = [], [], []
    for row in conn.execute(
            f"""SELECT id, catalyst_type, expected_date, title, description, source_url,
                       status, is_curated FROM catalysts
                 WHERE asset_id = ? AND catalyst_type IN ({marks})
                 ORDER BY expected_date, id""", (asset_id, *applications.FILED_KINDS)):
        row = dict(row)
        supplemental, why = applications.is_supplemental(conn, asset_id, row["title"],
                                                         row["description"])
        if supplemental:
            supplements.append({"catalyst_id": row["id"], "why": why})
            continue
        if parse_date(row["expected_date"]) is None:
            continue
        if (row["expected_date"] >= today
                and (row["status"] or "pending") not in ("met", "missed")):
            ahead.append(row)
        else:
            passed.append(row)
    return {"ahead": ahead[0] if ahead else None,
            "passed": passed[-1] if passed else None, "supplements": supplements}


def _registry(conn, asset_id: int) -> list[dict]:
    """The asset's live Phase 3 and 2/3 studies, any indication, earliest primary
    completion first. A study whose readout was resolved missed has answered and is out."""
    missed = {nct for nct, status in pos_granular.read_out(conn, asset_id).items()
              if status == "missed"}
    marks = ",".join("?" * len(REGISTRY_PHASES))
    out = []
    for row in conn.execute(
            f"""SELECT nct_id, phase, overall_status, primary_completion_date,
                       primary_completion_type, enrollment, title, conditions,
                       mesh_terms, fetched_at FROM trials
                 WHERE asset_id = ? AND phase IN ({marks})""",
            (asset_id, *REGISTRY_PHASES)):
        if (row["overall_status"] or "") in NOT_LIVE or row["nct_id"] in missed:
            continue
        day = parse_date(row["primary_completion_date"])
        if day is None:
            continue
        out.append({**dict(row), "day": day})
    return sorted(out, key=lambda t: (t["day"], -(t["enrollment"] or 0)))


def _slip(conn, nct_id: str, months: int, decision_year: int) -> dict | None:
    """The governing study's last move of primary completion, and the floor either side."""
    row = conn.execute(
        """SELECT old_value, new_value, change_type, detected_at FROM changes
            WHERE entity_type = 'trial' AND entity_key = ?
              AND field = 'primary_completion_date'
            ORDER BY detected_at DESC, id DESC LIMIT 1""", (nct_id,)).fetchone()
    if row is None:
        return None
    old = parse_date(row["old_value"])
    return {"detected_at": row["detected_at"], "change_type": row["change_type"],
            "old": row["old_value"], "new": row["new_value"],
            "floor_before": add_months(old, months).year if old else None,
            "floor_after": decision_year}


# --- the floor -----------------------------------------------------------------------

def _gate_floor(legs: dict | None, months: int | None, governing_nct: str | None) -> dict | None:
    """The earliest approval from the next gate pos_granular names, beside its odds."""
    if not legs or not legs.get("gate"):
        return None
    trial = legs.get("trial") or {}
    out = {"gate": legs["gate"], "label": legs.get("label"),
           "nct_id": trial.get("nct_id"), "date": legs.get("date"),
           "due": bool(legs.get("due")), "decision_date": None,
           "first_possible_year": None, "first_full_year": None, "why": None,
           "same_as_governing": bool(trial.get("nct_id")
                                     and trial.get("nct_id") == governing_nct)}
    day = parse_date(legs.get("date"))
    if legs["gate"] == "p2_to_p3":
        out["why"] = "a Phase 2 readout leads to a Phase 3, not to a filing"
        return out
    if day is None:
        out["why"] = legs.get("why") or "the gate carries no date"
        return out
    if legs["gate"] == "nda_to_approval":
        decision = day
    elif months is None:
        out["why"] = "no review clock on file for this pathway"
        return out
    else:
        decision = add_months(day, months)
    out.update(decision_date=decision.isoformat(), first_possible_year=decision.year,
               first_full_year=decision.year + 1)
    return out


def _modelled_floor(conn, registry: list, governing: dict, months: int, mesh) -> dict | None:
    """Where the study that sets the floor is in a disease the forecast does not value,
    the earliest study that is, and its floor. Display only: the asset-wide floor decides
    the status, so a missing descriptor can never create a flag."""
    if not mesh:
        return None
    modelled, _ = pos_granular.in_modelled(conn, governing["nct_id"], mesh)
    if modelled:
        return None
    for trial in registry:
        ok, indications = pos_granular.in_modelled(conn, trial["nct_id"], mesh)
        if ok:
            decision = add_months(trial["day"], months)
            return {"nct_id": trial["nct_id"],
                    "primary_completion": trial["primary_completion_date"],
                    "indications": indications, "decision_date": decision.isoformat(),
                    "first_possible_year": decision.year,
                    "first_full_year": decision.year + 1}
    return {"nct_id": None, "why": "no live Phase 3 in an indication the forecast values"}


def for_asset(conn, asset_id: int, today=None, *, scenario: str = "base", legs=_UNSET,
              clock: dict | None = None, voucher_rows: list | None = None,
              big: bool | None = None) -> dict | None:
    """The launch floor for one unmarketed asset with a seeded start year, or None.

    ``legs`` is pos_granular's legs for the asset where the caller holds them (the verdict
    and the forecast payload do); left unset they are worked out here, and None means the
    asset has no gate. Reads only; never calls assumptions.load or forecast.build.
    """
    today_date = today or dt.date.today()
    iso = today_date.isoformat()
    asset = conn.execute(
        "SELECT id, owner_company_id, generic_name, brand_name, internal_code, is_marketed"
        "  FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None or asset["is_marketed"]:
        return None
    asset = dict(asset)
    seeded = _seed(conn, asset_id, scenario)
    if seeded is None:
        return None
    seed_year, seed_source, seed_scenario = seeded
    clock = review_clock() if clock is None else clock
    voucher_rows = vouchers() if voucher_rows is None else voucher_rows
    basis = seed_basis(seed_source)
    out = {"asset_id": asset_id,
           "name": asset["brand_name"] or asset["generic_name"] or asset["internal_code"],
           "status": None, "flag": None, "seed_year": seed_year,
           "seed_source": seed_source, "seed_scenario": seed_scenario,
           "seed_basis": basis, "first_possible_year": None, "first_full_year": None,
           "decision_date": None, "standard": None, "evidence": None, "clock": None,
           "voucher": None, "if_filed_today": None, "slip": None, "gate": None,
           "modelled_floor": None, "trials_considered": 0, "message": None}

    def done(status, message):
        out.update(status=status, flag=FLAGS.get(status), message=message)
        return out

    scalars = pos_granular._base_scalars(conn, asset_id)
    stated = pos_granular.stated_pos(scalars)
    if stated is not None and stated <= 0:
        return done("not_assessed", "Nil probability in force, so no floor is drawn.")
    names = [n for n in (asset["generic_name"], asset["brand_name"],
                         asset["internal_code"]) if n]
    lead = pos_granular._lead_indication(conn, asset_id)
    mesh = pos_granular.modelled_mesh(conn, asset_id, lead["indication_id"] if lead else None)
    where = pos_granular.stage_of(conn, asset_id, asset["owner_company_id"], names,
                                  today_date, lead["id"] if lead else None,
                                  modelled_mesh=mesh)
    if where["stage"] == "negative" and stated is None:
        return done("not_assessed",
                    "Its Phase 3 read out negative and none remains open, so no floor is "
                    "drawn.")

    if legs is _UNSET:
        legs = pos_granular.legs_for_asset(conn, asset_id, today=today_date, big=big)

    pathway, how = pathway_of(conn, asset)
    priority = clock.get((pathway, "priority"))
    standard = clock.get((pathway, "standard"))
    held = next((v for v in voucher_rows
                 if _norm(v["asset_name_match"]) in {_norm(n) for n in names}), None)
    if held is not None:
        programme = clock.get(("cnpv", "any"))
        out["voucher"] = {**held, "applied": programme is not None,
                          "note": (None if programme else
                                   "a national priority voucher is on file; no clock row "
                                   "for the programme, so the priority clock stands")}
        priority = programme or priority
    if priority:
        out["clock"] = {"pathway": pathway, "pathway_how": how,
                        "review": priority["review"], "months": priority["months"],
                        "basis": priority["basis"], "source": priority["source"],
                        "carries_to": priority.get("carries_to"),
                        "cross_check": priority.get("cross_check"),
                        "extension_months": (clock.get(("major_amendment_extension", "any"))
                                             or {}).get("months")}
    months = priority["months"] if priority else None

    filings = _filings(conn, asset_id, iso)
    registry = _registry(conn, asset_id)
    out["trials_considered"] = len(registry)
    readout = where.get("readout") if where["stage"] == "positive" else None

    if filings["ahead"]:
        row = filings["ahead"]
        decision = parse_date(row["expected_date"])
        out["evidence"] = {"kind": "accepted", "catalyst_id": row["id"],
                           "date": row["expected_date"], "title": row["title"],
                           "quote": row["description"], "source_url": row["source_url"],
                           "curated": bool(row["is_curated"])}
        if out["clock"]:
            out["clock"]["applied"] = False
        sentence = (f"The FDA decision on the accepted application is due "
                    f"{_when(row['expected_date'])}.")
        governing_nct, governing_day = None, None
    elif filings["passed"]:
        row = filings["passed"]
        out["evidence"] = {"kind": "accepted", "catalyst_id": row["id"],
                           "date": row["expected_date"], "title": row["title"],
                           "quote": row["description"], "source_url": row["source_url"],
                           "curated": bool(row["is_curated"])}
        out["gate"] = _gate_floor(legs, months, None)
        return done("decision_passed",
                    f"The FDA decision on the accepted application was due "
                    f"{_when(row['expected_date'])} and the asset is still unmarketed on "
                    f"the book, so no floor is drawn.")
    elif readout and parse_date(readout.get("event_date")):
        governing_day = parse_date(readout["event_date"])
        governing_nct = readout.get("nct_id")
        out["evidence"] = {"kind": "readout", "nct_id": governing_nct,
                           "date": readout["event_date"], "date_type": "actual",
                           "accession": readout.get("accession"), "cite": readout.get("cite")}
        decision = None
        sentence = None
    elif registry:
        trial = registry[0]
        governing_day, governing_nct = trial["day"], trial["nct_id"]
        fetched = parse_date(str(trial["fetched_at"] or "")[:10])
        stale = bool(fetched and (today_date - fetched).days > STALE_DAYS)
        out["evidence"] = {"kind": "registry", "nct_id": governing_nct,
                           "date": trial["primary_completion_date"],
                           "date_type": trial["primary_completion_type"],
                           "phase": trial["phase"], "status": trial["overall_status"],
                           "enrollment": trial["enrollment"], "title": trial["title"],
                           "source_url": f"https://clinicaltrials.gov/study/{governing_nct}",
                           "fetched_at": trial["fetched_at"], "stale": stale}
        decision = None
        sentence = None
    else:
        out["gate"] = _gate_floor(legs, months, None)
        return done("no_registry_basis",
                    "No live Phase 3 on the registry, no positive Phase 3 readout and no "
                    "accepted application, so no floor is drawn.")

    if out["evidence"]["kind"] != "accepted":
        if months is None:
            out["gate"] = _gate_floor(legs, None, governing_nct)
            return done("no_clock",
                        f"No FDA review clock is on file for {PATHWAY_WORDS[pathway]}, so "
                        f"no floor is drawn"
                        + (": the BsUFA goals have not been read." if
                           pathway == "biosimilar_351k" else "."))
        out["clock"]["applied"] = True
        decision = add_months(governing_day, months)
        if governing_day < today_date:
            out["if_filed_today"] = add_months(today_date, months).isoformat()
        review = (f"a priority review of {PATHWAY_WORDS[pathway]} takes {months} months "
                  f"from receipt")
        if out["evidence"]["kind"] == "readout":
            sentence = (f"Its Phase 3 read out positive {_when(readout['event_date'])} and "
                        f"{review}.")
        else:
            verb = "completes" if governing_day >= today_date else "reached primary completion"
            kind = out["evidence"]["date_type"] or "date type not stated"
            sentence = (f"{governing_nct} {verb} {_when(out['evidence']['date'])} ({kind}) "
                        f"and {review}.")
            out["slip"] = _slip(conn, governing_nct, months, decision.year)
            out["modelled_floor"] = _modelled_floor(conn, registry, registry[0], months,
                                                    mesh)
        if standard:
            later = add_months(governing_day, standard["months"])
            out["standard"] = {"review": "standard", "months": standard["months"],
                               "decision_date": later.isoformat(),
                               "first_possible_year": later.year,
                               "first_full_year": later.year + 1}

    out.update(decision_date=decision.isoformat(), first_possible_year=decision.year,
               first_full_year=decision.year + 1)
    out["gate"] = _gate_floor(legs, months, governing_nct)
    gate_sentence = _gate_sentence(out["gate"])

    first = decision.year
    if seed_year < first:
        status = "before_floor_cited" if basis["cites"] else "before_floor"
        lead_in = (f"{seed_year} in the model, but the earliest approval is "
                   f"{_month(decision)}, so the first full year is {first + 1} at the "
                   f"soonest.")
        cited = (f" The seed's source cites a {basis['cites']} the database does not hold: "
                 f"record it." if basis["cites"] else "")
        return done(status, f"{lead_in} {sentence}{gate_sentence}{cited}")
    if seed_year == first:
        return done("part_year",
                    f"{seed_year} in the model is the approval year itself, a part year: "
                    f"the earliest approval is {_month(decision)}. {sentence}{gate_sentence}")
    return done("clear",
                f"{seed_year} in the model is clear of the earliest approval, "
                f"{_month(decision)}. {sentence}{gate_sentence}")


def _gate_sentence(gate: dict | None) -> str:
    """The gate study, named where it is not the study that sets the floor."""
    if not gate or not gate.get("nct_id") or gate.get("same_as_governing"):
        return ""
    when = _when(gate.get("date")) or "no date on file"
    if gate["gate"] == "p2_to_p3":
        return f" The next gate is a Phase 2 readout, {gate['nct_id']}, due {when}."
    timing = f"due since {when}" if gate.get("due") else f"completing {when}"
    tail = (f", which puts the earliest approval from it at "
            f"{_month(parse_date(gate['decision_date']))}" if gate.get("decision_date")
            else "")
    return f" The gate study is {gate['nct_id']}, {timing}{tail}."


def summary(launch: dict | None) -> dict | None:
    """The compact form a rollup line carries."""
    if not launch:
        return None
    evidence = launch.get("evidence") or {}
    return {key: launch.get(key) for key in (
        "status", "flag", "seed_year", "first_possible_year", "first_full_year",
        "decision_date", "message")} | {
        "evidence_kind": evidence.get("kind"), "nct_id": evidence.get("nct_id"),
        "evidence_date": evidence.get("date")}


def for_company(conn, company_id: int, today=None) -> list[dict]:
    """Every unmarketed asset of the company with a seeded start year, retired
    programmes left out, red first."""
    retired = {r[0] for r in conn.execute("SELECT asset_id FROM retired_programmes")}
    ids = [r[0] for r in conn.execute(
        """SELECT DISTINCT a.id FROM assets a JOIN assumptions s ON s.asset_id = a.id
            WHERE a.owner_company_id = ? AND a.is_marketed = 0
              AND s.key = 'forecast_start_year' AND s.scenario = 'base'
              AND s.indication_id IS NULL AND s.year IS NULL
            ORDER BY a.id""", (company_id,))]
    clock, held = review_clock(), vouchers()
    big = pos_granular.big_pharma(conn, company_id) if ids else None
    out = [found for asset_id in ids if asset_id not in retired
           for found in [for_asset(conn, asset_id, today, clock=clock, voucher_rows=held,
                                   big=big)] if found]
    return sorted(out, key=lambda d: (STATUS_ORDER.get(d["status"], 99),
                                      d.get("name") or ""))
