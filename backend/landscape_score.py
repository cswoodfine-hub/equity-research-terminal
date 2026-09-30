"""Every candidate's clinical record as two scores, so one chart can place them all.

The landscape holds each drug's trials arm by arm: dozens of endpoints in different units,
and a pooled safety record. No single endpoint is shared by every drug in a disease, so a
chart on one measure leaves most of them out. This reads the whole record instead and
turns it into two numbers from 0 to 100, each built only from what the registry posted:

**Efficacy**, the mean of whichever of these the record supports:

- *Strength.* Every endpoint a drug posted against a comparator with a p-value becomes a
  z-score (the normal deviate of a two-sided p), signed positive when the drug moved the
  measure the way that helps the patient. The mean z, as a share of 3.29 (p = 0.001, the
  bound most registry entries stop at). A result at the conventional p = 0.05 scores 60.
- *Wins.* The share of those endpoints won at p < 0.05.
- *Size against peers.* On a measure three or more drugs posted, the drug's rank on the
  size of its effect: 100 for the largest, 0 for the smallest. Sponsors word one measure
  many ways, so the standard ones (percent change in body weight, overall survival,
  progression-free survival, response rate and a few more) are gathered into one family
  each, with months, weeks and days on one scale and a count of responders turned into a
  share of its arm. A subgroup result stays out of the family: a drug is ranked on its
  whole trial population.

**Safety and tolerability**, the mean of whichever of these exist, less ten points for an
FDA boxed warning:

- *Staying on treatment.* The extra share of people who stopped for side effects over the
  same trials' controls. The same as control scores 75, five points more scores 50,
  fifteen more scores 0, five fewer scores 100.
- *Serious events.* The same scale on the extra share with a serious adverse event.

Deaths are reported beside the score and never in it: in a cancer trial they measure the
disease, which is efficacy, and the same number cannot count twice.

**Weight of evidence** is how much the two scores can be trusted: the people treated in the
drug's controlled trials on a log scale (100 people 25, 1,000 people 50, 10,000 people 75),
plus 20 where results come from Phase 3. It is the bubble size on the chart.

**Overall** is the mean of the three, so a strong result on one small trial does not
outrank a drug proven on thousands of people.

Which way helps the patient is not in a registry. It is read from the measure's name
(survival and response up; weight, HbA1c and events down), then from the way most drugs
moved a shared measure, and an endpoint whose direction neither settles is left unscored
and counted, never guessed. A drug with no posted result has no score: it is listed, by
stage, beside the chart.

Every comparison crosses trials. The scores order the evidence; they are not a
head-to-head result, and the view says so.
"""

from __future__ import annotations

import math
import re
import statistics
from statistics import NormalDist

import landscape_overview as O

Z_FULL = 3.29            # the normal deviate of a two-sided p of 0.001: full strength
Z_CAP = 5.0              # a p of zero or 1e-12 says no more than "beyond the table"
Z_WIN = 1.96             # p < 0.05, two-sided
P_FLOOR = 1e-6
SHARED_MIN = 3           # drugs on one measure before a rank on it means anything
MIN_PARTICIPANTS = 100   # a safety score on fewer people is flagged
SAME_AS_CONTROL = 75.0   # the safety score of a drug no worse than its control
POINTS_PER_PP = 5.0      # score lost per percentage point of excess over control
BOXED_DEDUCTION = 10.0
PHASE3_EVIDENCE = 20.0   # added to the weight of evidence where Phase 3 results exist

_NORMAL = NormalDist()

# A secondary outcome is often not efficacy at all: exposure, antibodies, or a count of
# adverse events, which the safety score already reads.
_NOT_EFFICACY = re.compile(
    r"adverse event|\bteaes?\b|\bsaes?\b|anti-?drug antibod|immunogenic|pharmacokinetic|"
    r"concentration|\bcmax\b|\bauc\b|trough|half-life|\bpk\b|tolerab|discontinu|"
    r"magnetic resonance|\bfmri\b|activation|dose intensity|mutation burden", re.I)
# Longer is better for a time to a bad event, whatever the event.
_TIME_TO = re.compile(r"\btime to\b|\bduration of (response|remission)\b", re.I)
_BAD_EVENT = re.compile(
    r"exacerbation|relapse|progression|death|\bdied\b|mortality|hospitali[sz]|fracture|stroke|"
    r"infarction|failure|\bevents?\b|recurrence|worsening|rescue|flare", re.I)
_HIGHER = re.compile(
    r"surviv|respon[ds]|remission|achiev|clearance|improvement|normoglyc|normali[sz]|"
    r"benefit rate|disease control|\bos\b|\bpfs\b|\borr\b|"
    r"\bdfs\b|\befs\b|\bdor\b|progression[- ]free|disease[- ]free|event[- ]free|"
    r"(percentage|proportion|number|percent) of (participants|patients|subjects)", re.I)
_LOWER = re.compile(
    r"weight|\bbmi\b|body mass|waist|hba1c|glyc|glucose|\bldl\b|cholesterol|triglycerid|"
    r"blood pressure|pain|severity|viral load|tumou?r size|lesion|symptom|albuminuria|"
    r"uric acid|\bige\b|eosinophil|plaque|fat mass|liver fat", re.I)

# The standard measures, however a sponsor words them: (family, what the title says, the
# class of unit it must be in). A title naming a subgroup stays out, so a drug is ranked
# on its whole population and never on its best slice.
_FAMILIES = (
    ("percent change in body weight", re.compile(r"\bweight\b", re.I), "percent"),
    ("share losing 5% or more of body weight",
     re.compile(r"weight.*(5 ?%|5 percent|five percent)|(5 ?%|5 percent).*weight", re.I), "share"),
    ("change in HbA1c", re.compile(r"hba1c|glycated h(a)?emoglobin", re.I), "percent"),
    ("overall survival", re.compile(r"overall survival|\bos\b", re.I), "time"),
    ("progression-free survival",
     re.compile(r"progression[- ]free survival|\bpfs\b", re.I), "time"),
    ("disease-free or event-free survival",
     re.compile(r"(disease|event)[- ]free survival|\bdfs\b|\befs\b", re.I), "time"),
    ("response rate", re.compile(r"(objective|overall) response|\borr\b", re.I), "share"),
    ("percent change in LDL cholesterol", re.compile(r"\bldl\b", re.I), "percent"),
)
_SUBGROUP = re.compile(
    r"subgroup|sub-group|\btps\b|pd-?l1|positive|negative|mutation|mutant|cohort|\btc\d|"
    r"\bic\d|female|male\b|stratum|population\)?$|-wt\b", re.I)
_MONTHS_PER = {"month": 1.0, "week": 1 / 4.345, "day": 1 / 30.44, "year": 12.0}

_PHASE_RANK = {"Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3, "Phase 2/3": 4, "Phase 3": 5,
               "Phase 4": 5}


def p_to_z(text) -> float | None:
    """The normal deviate of a reported two-sided p-value, unsigned, or None where the
    text is not one. "<0.001" is read at its bound, which can only understate the
    result; ">0.05" is read at the middle of what it allows, so it never counts as a win."""
    if text is None:
        return None
    s = str(text).strip().lower()
    m = re.search(r"(\d*\.?\d+(?:e-?\d+)?)", s)
    if not m:
        return None
    try:
        p = float(m.group(1))
    except ValueError:
        return None
    if not 0 <= p <= 1:
        return None
    if ">" in s:
        p = (p + 1.0) / 2.0
    p = min(max(p, P_FLOOR), 1.0)
    return min(_NORMAL.inv_cdf(1.0 - p / 2.0), Z_CAP)


def benefit_direction(title: str | None, unit: str | None = None) -> int | None:
    """+1 where more of the measure helps the patient, -1 where less does, 0 where the
    measure is not efficacy, None where its name does not say."""
    text = f"{title or ''} {unit or ''}"
    if _NOT_EFFICACY.search(text):
        return 0
    # A survival measure reported as a count of events reads the other way up from its
    # name; the two cannot both be trusted, so it is left unscored.
    if re.search(r"surviv", title or "", re.I) and re.search(r"event", unit or "", re.I):
        return None
    if _TIME_TO.search(text):
        return 1
    responder = re.search(r"(percentage|proportion|number|percent) of (participants|patients|"
                          r"subjects)", text, re.I)
    if responder and _BAD_EVENT.search(text) and not re.search(
            r"free|without|no (relapse|progression|exacerbation)", text, re.I):
        return -1
    if _HIGHER.search(text):
        return 1
    if _LOWER.search(text) or _BAD_EVENT.search(text):
        return -1
    return None


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _excess_score(drug_rate, control_rate) -> tuple[float | None, float | None]:
    """The score of one safety rate against its control, and the excess in points."""
    if drug_rate is None or control_rate is None:
        return None, None
    excess = (drug_rate - control_rate) * 100.0
    return _clamp(SAME_AS_CONTROL - POINTS_PER_PP * excess), excess


def _group_directions(groups: list[dict]) -> dict:
    """Each endpoint's direction of benefit: its name first, then the way most drugs
    moved it where enough drugs posted it. None stays None."""
    out = {}
    for g in groups:
        d = benefit_direction(g.get("title"), g.get("unit"))
        if d is None:
            drugs = {r["asset_id"] for r in g["rows"] if r.get("delta") is not None}
            if len(drugs) >= SHARED_MIN:
                d = O.direction(g["rows"])
        out[g["key"]] = d
    return out


def _unit_class(unit: str | None, param_type: str | None) -> str | None:
    """The class of a unit: a share of participants, a percent change, or a time."""
    u = (unit or "").lower()
    if re.search(r"participant|patient|subject", u):
        return "share"
    if re.search(r"\b(month|week|day|year)s?\b", u):
        return "time"
    if "%" in u or "percent" in u:
        return "percent"
    return None


def measure_family(group: dict) -> str | None:
    """The standard measure an endpoint is a wording of, or None where it is its own."""
    title = group.get("title") or ""
    if _SUBGROUP.search(title):
        return None
    cls = _unit_class(group.get("unit"), group.get("param_type"))
    for name, pattern, want in _FAMILIES:
        if cls == want and pattern.search(title):
            return name
    return None


def comparable_delta(row: dict, group: dict) -> float | None:
    """A row's difference from its comparator on the family's one scale: months for a
    time, a share of the arm for a count of participants, the posted figure otherwise.
    None where the conversion needs a number the registry did not post."""
    delta = row.get("delta")
    if delta is None:
        return None
    unit = (group.get("unit") or "").lower()
    cls = _unit_class(group.get("unit"), group.get("param_type"))
    if cls == "time":
        for word, factor in _MONTHS_PER.items():
            if re.search(rf"\b{word}s?\b", unit):
                return delta * factor
        return None
    if cls == "share" and "percent" not in unit and "%" not in unit and "proportion" not in unit:
        # A count of participants: comparable only as a share of each arm.
        n, n0 = row.get("n"), row.get("placebo_n")
        value, control = row.get("value"), row.get("placebo")
        if not n or not n0 or value is None or control is None:
            return None
        return 100.0 * (value / n - control / n0)
    return delta


def _best_rows(group: dict, sign: int) -> dict:
    """Per drug and trial, the arm with the largest benefit on this measure. An arm the
    drug is named in is preferred over one labelled by letter."""
    by: dict = {}
    for r in group["rows"]:
        if r.get("delta") is None:
            continue
        by.setdefault((r["asset_id"], r["nct_id"]), []).append(r)
    out: dict = {}
    for (aid, _nct), rows in by.items():
        named = [r for r in rows if r.get("arm_is_drug")] or rows
        out.setdefault(aid, []).append(max(named, key=lambda r: r["delta"] * sign))
    return out


def _size_ranks(best: dict) -> dict:
    """Each drug's rank on the size of its best effect, 100 for the largest and 0 for
    the smallest, where three or more drugs posted the measure. ``best`` is the largest
    benefit per drug, on one scale."""
    if len(best) < SHARED_MIN:
        return {}
    values = sorted(best.values())
    n = len(values)
    out = {}
    for aid, v in best.items():
        below = sum(1 for x in values if x < v)
        ties = sum(1 for x in values if x == v)
        out[aid] = {"pct": 100.0 * (below + (ties - 1) / 2.0) / (n - 1),
                    "rank": 1 + sum(1 for x in values if x > v), "of": n}
    return out


def evidence_score(participants, phase_rank: int) -> float | None:
    """How much a drug's scores can be trusted, 0 to 100: people treated on a log scale,
    plus a step for Phase 3 results."""
    if not participants or participants <= 0:
        return None
    base = 25.0 * math.log10(participants) - 25.0
    if phase_rank >= _PHASE_RANK["Phase 3"]:
        base += PHASE3_EVIDENCE
    return _clamp(base)


def _confidence(participants, phase_rank: int) -> str:
    n = participants or 0
    if n >= 500 and phase_rank >= _PHASE_RANK["Phase 3"]:
        return "high"
    if n >= MIN_PARTICIPANTS:
        return "medium"
    return "low"


def scorecard(land: dict) -> dict:
    """One record per candidate: its efficacy and safety scores with what each rests on,
    or the reason it has none."""
    cands = {c["asset_id"]: c for c in land.get("candidates") or []}
    groups = land.get("endpoints") or []
    safety = {s["asset_id"]: s for s in land.get("safety") or []}
    directions = _group_directions(groups)

    zs: dict = {}           # asset -> [signed z]
    unscored: dict = {}     # asset -> endpoints with a result but no usable direction or p
    sizes: dict = {}        # asset -> [{pct, rank, of, measure}]
    phase_seen: dict = {}
    top: dict = {}          # asset -> the strongest single result, for the tooltip

    families: dict = {}     # measure -> {asset: largest benefit on the family's scale}
    for g in groups:
        sign = directions.get(g["key"])
        touched = {r["asset_id"] for r in g["rows"] if r.get("delta") is not None}
        if sign == 0:
            continue
        if sign is None:
            for aid in touched:
                unscored[aid] = unscored.get(aid, 0) + 1
            continue
        measure = O._endpoint_title(g.get("title") or "")
        family = measure_family(g)
        bucket = families.setdefault(family or ("own", g["key"], measure), {})
        for aid, rows in _best_rows(g, sign).items():
            for r in rows:
                scaled = comparable_delta(r, g) if family else r["delta"]
                if scaled is not None:
                    bucket[aid] = max(bucket.get(aid, float("-inf")), scaled * sign)
                phase_seen[aid] = max(phase_seen.get(aid, 0), _PHASE_RANK.get(r.get("phase"), 0))
                z = p_to_z(r.get("p_value"))
                if z is None:
                    unscored[aid] = unscored.get(aid, 0) + 1
                    continue
                signed = z if r["delta"] * sign > 0 else -z
                zs.setdefault(aid, []).append(signed)
                if aid not in top or signed > top[aid]["z"]:
                    top[aid] = {"z": signed, "measure": measure, "delta": r["delta"],
                                "unit": g.get("unit"), "p_value": r.get("p_value"),
                                "nct_id": r.get("nct_id"), "phase": r.get("phase"),
                                "arm": r.get("arm"),
                                "reference_kind": r.get("reference_kind")}

    for key, best in families.items():
        name = key if isinstance(key, str) else key[2]
        for aid, rank in _size_ranks(best).items():
            sizes.setdefault(aid, []).append({**rank, "measure": name})

    assets = []
    for aid, c in cands.items():
        s = safety.get(aid) or {}
        record = {"asset_id": aid, "name": c.get("name"), "ticker": c.get("ticker"),
                  "stage": c.get("stage"), "is_marketed": bool(c.get("is_marketed")),
                  "mechanism": O.mechanism_label(c), "boxed": bool(c.get("boxed_warning")),
                  "pos": (c.get("model") or {}).get("pos"),
                  "per_share": (c.get("model") or {}).get("per_share"),
                  "trials_with_results": c.get("with_results") or 0}

        # Efficacy.
        parts, lines = {}, []
        mine = zs.get(aid) or []
        if mine:
            mean_z = statistics.fmean(mine)
            wins = sum(1 for z in mine if z >= Z_WIN)
            parts["strength"] = _clamp(100.0 * mean_z / Z_FULL)
            parts["wins"] = 100.0 * wins / len(mine)
            lines.append(f"Beat its comparator on {wins} of {len(mine)} "
                         f"endpoint{'s' if len(mine) != 1 else ''} at p < 0.05.")
            lines.append(f"Mean strength of result z = {mean_z:.1f} "
                         f"(1.96 is p = 0.05, 3.29 is p = 0.001).")
        ranks = sizes.get(aid) or []
        if ranks:
            parts["size"] = statistics.fmean(r["pct"] for r in ranks)
            lead = min(ranks, key=lambda r: (r["rank"], -r["of"]))
            lines.append(f"Size of effect: {_ordinal(lead['rank'])} of {lead['of']} on "
                         f"{lead['measure']}"
                         + (f", and ranked on {len(ranks) - 1} more shared "
                            f"measure{'s' if len(ranks) != 2 else ''}" if len(ranks) > 1 else "")
                         + ".")
        efficacy = statistics.fmean(parts.values()) if parts else None
        skipped = unscored.get(aid, 0)
        if skipped:
            lines.append(f"{skipped} posted endpoint{'s' if skipped != 1 else ''} not scored: "
                         "no p-value, or a measure whose direction of benefit is not clear.")
        record["efficacy"] = {"score": efficacy, "parts": parts, "endpoints": len(mine),
                              "unscored": skipped, "lines": lines, "top": top.get(aid)}

        # Safety and tolerability.
        sparts, slines = {}, []
        wd, wd_ex = _excess_score(s.get("withdrawn_rate"), s.get("placebo_withdrawn_rate"))
        se, se_ex = _excess_score(s.get("serious_rate"), s.get("placebo_serious_rate"))
        if wd is not None:
            sparts["staying_on"] = wd
            slines.append(f"Stopped for side effects: {s['withdrawn_rate'] * 100:.1f}% against "
                          f"{s['placebo_withdrawn_rate'] * 100:.1f}% on control "
                          f"({wd_ex:+.1f} points).")
        if se is not None:
            sparts["serious"] = se
            slines.append(f"Serious adverse events: {s['serious_rate'] * 100:.1f}% against "
                          f"{s['placebo_serious_rate'] * 100:.1f}% on control "
                          f"({se_ex:+.1f} points).")
        saf = statistics.fmean(sparts.values()) if sparts else None
        if saf is not None and record["boxed"]:
            saf = _clamp(saf - BOXED_DEDUCTION)
            head = O._boxed_headline(c.get("boxed_warning") or "",
                                     [c.get("name"), c.get("generic")])
            slines.append(f"FDA boxed warning, {BOXED_DEDUCTION:.0f} points off: "
                          f"{head.rstrip('.')}.")
        if s.get("deaths_rate") is not None and s.get("placebo_deaths_rate") is not None:
            slines.append(f"Deaths, reported and not scored: {s['deaths_rate'] * 100:.1f}% "
                          f"against {s['placebo_deaths_rate'] * 100:.1f}% on control.")
        participants = s.get("participants")
        if saf is not None and (participants or 0) < MIN_PARTICIPANTS:
            slines.append(f"Read with care: {participants or 0} people treated.")
        record["safety"] = {"score": saf, "parts": sparts, "lines": slines,
                            "withdrawn_excess": wd_ex, "serious_excess": se_ex,
                            "control_kind": s.get("control_kind"),
                            "participants": participants, "trials": s.get("trials")}

        rank = phase_seen.get(aid, 0)
        ev = evidence_score(participants, rank)
        record["evidence"] = {
            "score": ev,
            "participants": participants,
            "phase": next((p for p, r in _PHASE_RANK.items() if r == rank and p != "Phase 4"),
                          None),
            "confidence": _confidence(participants, rank) if (efficacy is not None
                                                                 or saf is not None) else None}
        record["placed"] = efficacy is not None and saf is not None
        record["overall"] = (statistics.fmean([efficacy, saf, ev if ev is not None else 0.0])
                             if record["placed"] else None)
        if record["placed"]:
            record["why_not"] = None
        elif not record["trials_with_results"] and efficacy is None and saf is None:
            record["why_not"] = "no posted results"
        elif efficacy is None and saf is None:
            record["why_not"] = "results posted, none against a comparator"
        elif efficacy is None:
            record["why_not"] = "no efficacy endpoint with a p-value against a comparator"
        else:
            record["why_not"] = "no safety figure against a control"
        assets.append(record)

    placed = sorted((a for a in assets if a["placed"]), key=lambda a: -a["overall"])
    for i, a in enumerate(placed, 1):
        a["rank"] = i
    rest = sorted((a for a in assets if not a["placed"]),
                  key=lambda a: (-(_stage_rank(a["stage"])), a["ticker"] or "", a["name"] or ""))
    return {
        "assets": placed + rest, "placed": len(placed), "total": len(assets),
        "method": {
            "efficacy": ("Mean of strength (the mean z of every endpoint posted against a "
                         "comparator, as a share of 3.29), wins (the share won at p < 0.05) "
                         "and size against peers (rank on each measure three or more drugs "
                         "posted)."),
            "safety": ("Mean of staying on treatment and serious events, each 75 when equal "
                       "to control and 5 points per percentage point of excess, less 10 for "
                       "an FDA boxed warning. Deaths are reported, not scored."),
            "evidence": ("People treated in controlled trials on a log scale (100 people 25, "
                         "1,000 people 50, 10,000 people 75), plus 20 for Phase 3 results."),
            "overall": "The mean of efficacy, safety and weight of evidence.",
            "caveat": ("Scores cross trials that differ in who they enrolled, for how long "
                       "and against what. They order the evidence; they are not a "
                       "head-to-head result.")}}


def _stage_rank(stage: str | None) -> int:
    s = stage or ""
    if s == "Marketed":
        return 6
    if s.startswith("Marketed"):
        return 5
    if "Phase 3" in s or "Phase 2/3" in s:
        return 4
    if "Phase 2" in s:
        return 3
    return 1


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
