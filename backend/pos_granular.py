"""Probability of success for a big pharma Phase 2 or 3 asset, from where it actually is.

The rate the book used was a likelihood of approval read off one table by therapeutic
area and phase. It is honestly sourced and it is right for an asset that has just
entered its phase, and it is the same number for an asset whose pivotal trial read out
positive last month, which is wrong by a factor of two. Of 330 assets carrying a
probability of their own, 319 are marketed products at 1.0; the pipeline runs almost
entirely on that table.

This does three things the table cannot, and refuses a fourth.

It places the asset at its gate. The published likelihood is the product of the phase
transitions still ahead, and the trials table says which of them have already been
crossed: a Phase 3 with a positive readout on file has only the NDA/BLA-to-approval
transition left. The chain reproduces the table exactly for an asset at its phase's
entry, so nothing moves unless evidence moves it.

It shows a band, not a point pretending to be one. The same report cuts the same
transitions by modality, by oncology tumour type and by disease prevalence, and this
computes the chain under each cut the asset qualifies for and reports the spread. The
point estimate stays on the area cut, which is the best sampled and the one the model
has always used; the band is what the asset's other attributes say about it.

It reads an accepted application. An asset whose marketing application the FDA has
accepted has only the approval transition left, and ``applications.filed_for`` supplies
that fact with the guards that make it safe to act on: the application must be for the
disease this forecast is built on, it must seek a first approval rather than expand an
approved label, and the decision date must still be ahead. A filing that fails any of
those is reported and lifts nothing, which is the honest answer and usually the right
one.

It carries the design of the largest Phase 3 trial, enrolment, allocation and masking,
beside the number, as facts a reader weighs. No free source publishes success rates by
those, so they are shown and never multiplied.

It does not infer a biomarker. The report's strongest cut is patient preselection
biomarkers, which roughly double the Phase 2 transition, and it identified them by
mapping trial-design records this repository does not hold. A title containing a gene
name is not that. The cut applies only where a person has recorded on the asset that
its pivotal trial selected patients on a biomarker, as a ``biomarker_selected`` row.

Big pharma only, and Phase 2 or 3 only, by construction: everywhere else the book
behaves as it did.

Beside the probability, and never inside it, it says what the next gate decides. The
point splits by transition into ``gates`` that multiply back to it exactly;
``next_gate`` names the event, its trial and its date, and is the one gate source for
every view that prices, costs or times a gate; ``legs`` gives the probability if that
gate passes and if it fails. assumptions.load calls ``for_asset`` alone, so none of
this reaches the value.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import pathlib
import re

import engines
import fx
import indication_mapping
import productivity
import applications

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
TRANSITIONS = DATA_DIR / "pos_transitions.csv"

# The transitions ahead of an asset at each gate, in order. A stage names the gate the
# asset stands at now, which is the first transition it still has to make.
CHAIN = ("p1_to_p2", "p2_to_p3", "p3_to_nda", "nda_to_approval")
FROM_PHASE = {"Phase 2": "p2_to_p3", "Phase 2/3": "p2_to_p3", "Phase 3": "p3_to_nda"}

# The event that decides each transition, as a reader names it. The one label map for
# every view of the next gate: the legs, the development cost and the launch floor.
GATE_LABELS = {"p2_to_p3": "Phase 2 readout", "p3_to_nda": "Phase 3 readout",
               "nda_to_approval": "FDA decision"}
_STEP_NAMES = {"p1_to_p2": "Phase 1 to Phase 2", "p2_to_p3": "Phase 2 to Phase 3",
               "p3_to_nda": "Phase 3 to NDA/BLA", "nda_to_approval": "NDA/BLA to approval"}
# Where an asset stands once the gate before this one has passed.
_PLACED_AT = {"p3_to_nda": "at Phase 3 entry", "nda_to_approval": "at the NDA/BLA gate"}
# The registry phases whose readout decides each gate. A seamless Phase 2/3 is read at
# the Phase 2 gate, as the chain reads it, and as a Phase 3 by stage_of.
_GATE_PHASES = {"p2_to_p3": ("Phase 2", "Phase 2/3"), "p3_to_nda": ("Phase 3", "Phase 2/3")}
GATE_PHASES = _GATE_PHASES

# A stated probability this close to the value the asset would carry once its gate
# passed is read as already past it: the analyst has priced a filing the book's phase
# does not carry yet (ABP 206, pozelimab with cemdisiran, giredestrant, povetacicept).
STATED_PAST_GATE = 1e-3

# A band cut is refused where the report's n for any transition it would use is below
# this. Figure 10b puts CAR-T's Phase 3 transition at 66.7% on three programmes and
# ADCs' NDA transition at 100% on twelve; a reader is better served by the area rate
# than by a decimal read off a handful. The area chain itself is never refused on n:
# it is the figure pos_by_area.csv already carries, n and all, and refusing Metabolic
# for its 48 approvals would move the book for no new evidence.
MIN_N = 50

# A Phase 3 that is still open when another has read out negative. The negative is
# one trial's answer and these are the others still asking.
OPEN_STATUSES = ("Recruiting", "Active not recruiting", "Not yet recruiting",
                 "Enrolling by invitation")

# The Orphan Drug Act line, which is also the report's own rare-disease criterion on
# page 13. Chronic high prevalence is its other pole, over one million US patients.
RARE_US_PREVALENCE = 200_000
CHRONIC_US_PREVALENCE = 1_000_000

# The report's area names for this model's, the same map pos_by_area.csv documents.
AREA_TO_REPORT = {
    "Oncology": "Oncology", "Immunology and inflammation": "Autoimmune",
    "Metabolic": "Metabolic", "Neuroscience": "Neurology", "Cardiovascular": "Cardiovascular",
    "Respiratory": "Respiratory", "Haematology": "Hematology", "Urology": "Urology",
    "Ophthalmology": "Ophthalmology", "Infectious disease": "Infectious disease",
    "Endocrine": "Endocrine", "Psychiatry": "Psychiatry", "Allergy": "Allergy",
    "Gastroenterology": "Gastroenterology",
}

# INN stems to the report's modality classes. The stem is the only thing a pipeline
# asset carries before it has a label, and a code number carries nothing, so an asset
# named MK-1045 gets no modality cut and the basis says so. A bispecific is folded
# into the antibody class because the report has no class for it, and that is stated.
_STEMS = (
    (re.compile(r"(vedotin|deruxtecan|tecan|adizutecan|samrotecan|tirumotecan|mafodotin|govitecan)$"),
     "ADCs", "an antibody-drug conjugate by its stem"),
    # -mig is the WHO infix for a bispecific or multispecific immunoglobulin. All
    # seventeen names ending in it across this database are bispecific antibodies, so the
    # whole infix is taken rather than the two spellings that happened to appear first:
    # volrustomig, rilvegostomig and tobemstomig were missed by -tamig and -amig alone.
    (re.compile(r"(mig|xizumab)$"), "Monoclonal antibody",
     "a bispecific antibody by its stem, folded into the report's antibody class"),
    (re.compile(r"(mab)$"), "Monoclonal antibody", "a monoclonal antibody by its stem"),
    (re.compile(r"(siran)$"), "siRNA/RNAi", "an siRNA by its stem"),
    (re.compile(r"(rsen|nersen)$"), "Antisense", "an antisense oligonucleotide by its stem"),
    (re.compile(r"(cept)$"), "Protein", "a fusion protein by its stem"),
    (re.compile(r"(tide|glutide|relin|pressin)$"), "Peptide", "a peptide by its stem"),
    (re.compile(r"autogene|(cel)$"), "Gene therapy", "a gene or cell therapy by its stem"),
    (re.compile(r"(nib|mib|ciclib|lisib|stat|sib|domide|rasib|kibart|parib|degib|"
                r"tinib|ostat|vir|prazole|sartan|gliptin|gliflozin|lutamide)$"),
     "Small molecule", "a small molecule by its stem"),
)

_HEME = re.compile(r"leuk|lymphom|myelom|myelodysplas|hematolog|haematolog|"
                   r"myelofibro|polycyth|thrombocyth", re.I)
_IO = re.compile(r"\bpd-?1\b|\bpd-?l1\b|ctla-?4|checkpoint|immuno-?oncolog|\btigit\b|"
                 r"\blag-?3\b", re.I)


def transitions(path=None) -> dict:
    """{(cut, group, transition): {pos, n, source}} from the published report."""
    source = pathlib.Path(path) if path else TRANSITIONS
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            try:
                out[(row["cut"], row["group"], row["transition"])] = {
                    "pos": float(row["pos"]), "n": int(row["n"] or 0),
                    "source": (row.get("source") or "").strip()}
            except (KeyError, TypeError, ValueError):
                continue
    return out


def modality_of(name: str | None, stored: str | None = None) -> tuple:
    """(report class, how it was read) from the assets row or an INN stem, or (None, why).

    The assets column holds only "small molecule" or "biologic" today. The first is the
    report's own class; the second spans six of them, so it decides nothing and the
    stem is read instead.
    """
    if (stored or "").strip().lower() == "small molecule":
        return "Small molecule", "a small molecule on the assets row"
    text = (name or "").strip().lower()
    if not text:
        return None, "no name on file"
    if re.match(r"^[a-z]{1,4}-?\d{3,}", text):
        return None, "a code number carries no stem"
    for pattern, group, how in _STEMS:
        if pattern.search(text):
            return group, how
    return None, "no recognised stem"


# The registry page a derived readout catalyst points at, which is how a resolved one
# is tied to its trial (catalysts.CTGOV_URL; not imported, so the rNPV path does not
# take on the catalysts module).
_CTGOV_URL = "https://clinicaltrials.gov/study/"


# A readout catalyst joined to the study it points at, through the registry's unique
# index. The study's asset is the one it belongs to: the refresh keeps that mapping
# current, while the catalyst's own asset_id is set once when the row is derived (and is
# empty on a third of the book's readouts).
_READOUT_JOIN = (f"JOIN trials t ON cat.source_url LIKE '{_CTGOV_URL}%'"
                 f" AND t.nct_id = substr(cat.source_url, {len(_CTGOV_URL) + 1})")


def read_out(conn, asset_id: int) -> dict:
    """{nct_id: outcome} for the asset's trials whose readout catalyst has been resolved
    met or missed, any phase, any indication. Such a trial has answered: it is no longer
    one of the studies still asking, whatever the registry lists it as."""
    return {r["nct_id"]: r["status"] for r in conn.execute(
        f"""SELECT t.nct_id, cat.status FROM catalysts cat {_READOUT_JOIN}
             WHERE t.asset_id = ? AND cat.catalyst_type = 'data readout'
               AND cat.status IN ('met', 'missed')
             ORDER BY cat.updated_at, cat.id""", (asset_id,))}


def _resolved_readouts(conn, asset_id: int, modelled_mesh) -> list:
    """Phase 3 readouts resolved by hand on the asset's own studies, as trial_readouts
    rows: met is positive and missed negative, dated the day it was recorded.

    Matched by the study and the asset it is mapped to, never by drug name, and counted
    only where the study is in an indication the forecast values, the same MeSH test that
    prices the gate. A positive Phase 3 in another disease must not lift the modelled
    one."""
    mesh = set(modelled_mesh or ())
    if not mesh:
        return []
    out = []
    for r in conn.execute(
            f"""SELECT cat.id, cat.status, date(cat.updated_at) AS on_day, t.nct_id,
                       t.conditions, t.mesh_terms FROM catalysts cat {_READOUT_JOIN}
                 WHERE t.asset_id = ? AND t.phase LIKE '%3%'
                   AND cat.catalyst_type = 'data readout'
                   AND cat.status IN ('met', 'missed')""", (asset_id,)):
        found = indication_mapping.indications_for(
            r["conditions"], indication_mapping.parse_browse(r["mesh_terms"]))
        if not {t["id"] for t in found} & mesh:
            continue
        out.append({"drug": None, "phase": "3",
                    "outcome": "positive" if r["status"] == "met" else "negative",
                    "event_date": r["on_day"], "accession": None, "nct_id": r["nct_id"],
                    "cite": (f"on {r['on_day']}, resolved {r['status']} by hand "
                             f"(catalyst {r['id']}, {r['nct_id']})")})
    return out


def stage_of(conn, asset_id: int, company_id: int, names: list, today=None,
             lead_indication_id=None, modelled_mesh=None) -> dict:
    """Where the asset stands, from the trials and readouts on file.

    A passed primary completion date with no readout is not evidence of success and
    does not advance the chain; it is reported, because a reader wants to know a
    readout is due. Only a readout does: positive from a Phase 3 moves the asset to the
    NDA/BLA gate, and negative puts it at nil, which is the convention the analyst's
    own hand-typed rows already follow.

    A readout is either a trial_readouts row, matched by drug name, or the asset's own
    Phase 3 readout catalyst resolved met or missed, matched by trial and counted only
    in an indication the forecast values (``modelled_mesh``; none without it).
    """
    today_date = today or dt.date.today()
    today = today_date.isoformat()
    p3 = [dict(r) for r in conn.execute(
        """SELECT nct_id, overall_status, primary_completion_date, enrollment, design,
                  title FROM trials
            WHERE asset_id = ? AND phase LIKE '%3%'
              AND COALESCE(overall_status, '') NOT IN ('Withdrawn')
            ORDER BY COALESCE(enrollment, 0) DESC""", (asset_id,))]
    pivotal = p3[0] if p3 else None
    # A study that has read out is not one still asking, whatever the registry lists.
    answered = set(read_out(conn, asset_id))
    passed = [t for t in p3 if (t["primary_completion_date"] or "9999") <= today
              and t["nct_id"] not in answered]

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    mine = {norm(n) for n in names if n}
    readouts = []
    for r in conn.execute(
            "SELECT drug, phase, outcome, event_date, accession FROM trial_readouts"
            " WHERE company_id = ? ORDER BY event_date DESC", (company_id,)):
        drug = norm(r["drug"])
        if drug in mine or any(len(n) > 4 and n in drug for n in mine):
            readouts.append(dict(r))
    phase3_readouts = [r for r in readouts if str(r["phase"] or "") == "3"]
    resolved = _resolved_readouts(conn, asset_id, modelled_mesh)
    if resolved:
        # Newest first, as the query orders the rest; a stable sort keeps their order.
        phase3_readouts = sorted(phase3_readouts + resolved,
                                 key=lambda r: r["event_date"] or "", reverse=True)

    def cite(r):
        if r.get("cite"):
            return r["cite"]
        return f"on {r['event_date']}" + (f" ({r['accession']})" if r.get("accession") else "")

    positive = next((r for r in phase3_readouts
                     if (r["outcome"] or "").lower() == "positive"), None)
    negative = next((r for r in phase3_readouts
                     if (r["outcome"] or "").lower() == "negative"), None)

    # An accepted application outranks a positive readout, because it is the regulator
    # agreeing the package is reviewable rather than the sponsor reporting a result.
    # Both land on the same gate, so this only decides which evidence the basis names.
    filing = applications.filed_for(conn, asset_id, lead_indication_id, today=today_date)
    if filing and filing.get("lifts") and not negative:
        return {"stage": "filed", "gate": "nda_to_approval", "pivotal": pivotal,
                "filing": filing,
                "evidence": f"application accepted, FDA decision due "
                            f"{filing['date']}"}
    if positive:
        return {"stage": "positive", "gate": "nda_to_approval", "pivotal": pivotal,
                "evidence": f"Phase 3 read out positive {cite(positive)}"}
    if negative:
        # One trial's answer. Volrustomig's lung study was stopped for futility with
        # three other Phase 3 studies recruiting to 2030; the asset is not nil, the
        # remaining studies are at their gate and the downside is.
        remaining = [t for t in p3 if t["overall_status"] in OPEN_STATUSES
                     and t["nct_id"] not in answered
                     and (t["primary_completion_date"] or "9999") > negative["event_date"]]
        if remaining:
            return {"stage": "mixed", "gate": None, "pivotal": remaining[0],
                    "evidence": f"one Phase 3 read out negative {cite(negative)} with "
                                f"{len(remaining)} Phase 3 still listed open on the "
                                f"registry, the largest {remaining[0]['nct_id']} to "
                                f"{remaining[0]['primary_completion_date']}"}
        return {"stage": "negative", "gate": None, "pivotal": pivotal,
                "evidence": f"Phase 3 read out negative {cite(negative)} and no Phase 3 "
                            f"remains open"}
    if passed:
        t = passed[0]
        return {"stage": "reading_out", "gate": None, "pivotal": pivotal,
                "evidence": f"{t['nct_id']} passed primary completion "
                            f"{t['primary_completion_date']} with no readout on file"}
    return {"stage": "entering", "gate": None, "pivotal": pivotal, "filing": filing,
            "evidence": (f"{pivotal['nct_id']} {(pivotal['overall_status'] or '').lower()}"
                         if pivotal else "no Phase 3 on the registry")}


def _chain(table: dict, cut: str, group: str, gates: tuple, min_n: int = MIN_N) -> tuple:
    """(product, [used rows], refused reason). Refuses a cut short of min_n anywhere."""
    product, used = 1.0, []
    for gate in gates:
        row = table.get((cut, group, gate))
        if row is None:
            return None, used, f"{cut} {group} has no {gate} rate"
        if row["n"] < min_n:
            return None, used, f"{cut} {group} rests on n={row['n']} at {gate}"
        product *= row["pos"]
        used.append((gate, row))
    return product, used, None


def _cuts(table: dict, gates: tuple, *, names: list, stored_modality: str | None,
          report_area: str | None, conditions_text: str, prevalence_us: float | None,
          biomarker_selected: bool) -> tuple:
    """(cuts, refused): the chain from ``gates`` under every other cut the asset
    qualifies for. Each is the whole chain under that cut, so the band is what the
    asset's attributes say and not an independence assumption multiplied across them.
    Each cut keeps its per-gate ``rows`` for the gate split; resolve strips them."""
    cuts, refused = [], []
    modality, how = modality_of(names[0] if names else None, stored_modality)
    if modality:
        v, rows, reason = _chain(table, "modality", modality, gates)
        (cuts if v is not None else refused).append(
            {"cut": "modality", "group": modality, "pos": v, "how": how,
             "why": reason, "rows": rows})
    else:
        refused.append({"cut": "modality", "group": None, "pos": None, "how": how,
                        "why": how, "rows": []})
    if report_area == "Oncology":
        sub = ("Hematologic" if _HEME.search(conditions_text) else
               "IO" if _IO.search(conditions_text) else None)
        if sub:
            v, rows, reason = _chain(table, "oncology", sub, gates)
            (cuts if v is not None else refused).append(
                {"cut": "oncology", "group": sub, "pos": v, "why": reason, "rows": rows,
                 "how": "from the registry's conditions and titles"})
    elif prevalence_us is not None:
        # The report's chronic pole is the CMS chronic-conditions list. An infection, a
        # vaccine's at-risk population or a disease of no known area is not on it
        # however many people it counts.
        chronic_ok = (report_area not in (None, "Infectious disease")
                      and modality != "Vaccine")
        group = ("Rare" if prevalence_us < RARE_US_PREVALENCE else
                 "Chronic high prevalence"
                 if prevalence_us > CHRONIC_US_PREVALENCE and chronic_ok else None)
        if group:
            v, rows, reason = _chain(table, "prevalence", group, gates)
            (cuts if v is not None else refused).append(
                {"cut": "prevalence", "group": group, "pos": v, "why": reason,
                 "rows": rows, "how": f"US prevalence {prevalence_us:,.0f} on file"})
    if biomarker_selected:
        v, rows, reason = _chain(table, "biomarker", "Preselection biomarkers", gates)
        (cuts if v is not None else refused).append(
            {"cut": "biomarker", "group": "Preselection biomarkers", "pos": v,
             "why": reason, "rows": rows, "how": "recorded on the asset by hand"})
    return cuts, refused


def _split(used: list, cuts: list) -> list:
    """Each gate's rate: the geometric mean of the area row and every cut's row at that
    gate. A geometric mean of products is the product of geometric means, so these
    multiply back to the central tendency of the chains, which is the point."""
    out = []
    for i, (gate, row) in enumerate(used):
        cut_pos = {c["group"]: c["rows"][i][1]["pos"] for c in cuts}
        rates = [row["pos"], *cut_pos.values()]
        pos = (row["pos"] if len(rates) == 1 else
               math.exp(sum(math.log(r) for r in rates) / len(rates)))
        out.append({"gate": gate, "label": GATE_LABELS.get(gate), "pos": pos,
                    "area_pos": row["pos"], "cut_pos": cut_pos, "n": row["n"],
                    "implied": False})
    return out


def _area_chain(table: dict, report_area: str | None, gates: tuple) -> tuple:
    """(product, used rows, label) for the area, falling back to all indications. The
    area chain is never refused on n; (None, [], None) only where neither has rows."""
    point, used, _ = _chain(table, "area", report_area or "All indications", gates, 0)
    if point is not None:
        return point, used, report_area or "all indications"
    point, used, _ = _chain(table, "area", "All indications", gates, 0)
    if point is not None:
        return point, used, "all indications"
    return None, [], None


def _product(values) -> float:
    total = 1.0
    for v in values:
        total *= v
    return total


def resolve(conn, asset_id: int, *, area: str | None, phase: str | None,
            names: list, company_id: int, prevalence_us: float | None,
            biomarker_selected: bool, conditions_text: str = "",
            stored_modality: str | None = None, lead_indication_id=None,
            today=None, table=None, at_gate: str | None = None,
            modelled_mesh=None) -> dict | None:
    """The probability, its band, and everything it rests on. None where not applicable.

    Applies only from Phase 2, Phase 2/3 or Phase 3, and only where the area chain can
    be computed. The point is the area chain from the asset's gate; the band is the
    same chain under every other cut the asset qualifies for and the report samples
    well enough to trust.

    ``gates`` splits the point by transition, each the geometric mean of the area rate
    and every qualifying cut's rate at that gate, and multiplies back to the unrounded
    point exactly. It is computed after the mixed cap.

    ``at_gate`` places the asset at that gate whatever the registry says, as if the
    gate before it had passed (stage ``if_met``), by the same cut rule. legs() is its
    only caller: it is the value the asset would carry once its next readout passes.

    ``modelled_mesh`` is handed to stage_of so a resolved readout catalyst counts only
    in an indication the forecast values; without it none counts.
    """
    table = table if table is not None else transitions()
    first = FROM_PHASE.get(phase or "")
    if not first or not table:
        return None
    if at_gate is not None:
        if at_gate not in CHAIN[1:]:
            raise ValueError(f"{at_gate} is not a gate an asset can be placed at")
        before = CHAIN[CHAIN.index(at_gate) - 1]
        where = {"stage": "if_met", "gate": at_gate, "pivotal": None, "filing": None,
                 "evidence": f"if its {GATE_LABELS.get(before, before)} passes"}
    else:
        where = stage_of(conn, asset_id, company_id, names, today, lead_indication_id,
                         modelled_mesh=modelled_mesh)
    if where["stage"] == "negative":
        return {"pos": 0.0, "low": 0.0, "high": 0.0, "stage": where["stage"],
                "evidence": where["evidence"], "chain": [], "cuts": [],
                "design": _design(where["pivotal"]), "filing": where.get("filing"),
                "basis": f"nil: {where['evidence']}", "gates": []}
    start = where["gate"] or first
    gates = CHAIN[CHAIN.index(start):]

    report_area = AREA_TO_REPORT.get(area or "", None)
    point, used, label = _area_chain(table, report_area, gates)
    if point is None:
        return None

    attributes = {"names": names, "stored_modality": stored_modality,
                  "report_area": report_area, "conditions_text": conditions_text,
                  "prevalence_us": prevalence_us, "biomarker_selected": biomarker_selected}
    cuts, refused = _cuts(table, gates, **attributes)

    # The point is the central tendency of every published rate this asset belongs to,
    # not the area rate alone.
    #
    # The area chain was the point for as long as the cuts were only a band, and the
    # consequence was that twenty-seven of the fifty-five modelled pipeline assets
    # carried the identical 0.4388, which is Oncology Phase 3 entry. Two drugs were
    # indistinguishable however different their tumour type, their modality or the
    # population they treat, while the module had already computed rates for exactly
    # those attributes and then discarded them.
    #
    # WHAT THE GEOMETRIC MEAN CLAIMS, AND WHAT IT DOES NOT. The report's tables are
    # marginal: it publishes oncology at 47.7% and monoclonal antibodies at 68.1% and
    # never publishes oncology monoclonal antibodies. Multiplying them, or combining them
    # as independent likelihood ratios, would assert a joint rate the source does not
    # carry and would run outside the range of everything it does carry. The geometric
    # mean asserts something weaker and defensible: this asset belongs to each of these
    # published populations, and absent a joint table its rate is their central tendency.
    # It is bounded by the rates themselves, so the point always falls inside the band
    # that the same cuts produce, which is checked by a test rather than asserted here.
    #
    # Weighting by sample size was measured and rejected: it moves the standard deviation
    # across the book by 0.0005 and adds a second thing to explain.
    #
    # An asset qualifying for no cut keeps the area rate, which is the honest answer. It
    # is also why eleven ties remain: a compound named by a code number with no readable
    # stem and no tumour type on its trials has nothing to tell them apart with.
    spread = [point] + [c["pos"] for c in cuts]
    # Not where the asset has read out badly. A drug whose Phase 3 has already failed is
    # not told anything useful by the rate at which its class usually succeeds, and
    # volrustomig proved the point: one Phase 3 stopped for futility, and the bispecific
    # antibody rate of 68.1% pulled its central tendency up from 0.4388 to 0.5340. Its
    # own evidence outranks its class membership, so a mixed stage keeps the chain and
    # the band still floors at nil.
    if cuts and where["stage"] != "mixed":
        point = math.exp(sum(math.log(v) for v in spread) / len(spread))
    capped_at = None
    if where["stage"] == "mixed":
        # A negative readout never raises the probability. Keeping the area chain is
        # right where the cuts sit above it, which is volrustomig's case, but where a cut
        # sits below the area rate (a peptide in metabolic disease, say) the bare chain
        # would put the asset higher after a failed Phase 3 than it stood before one. So
        # the mixed point is never above the point the asset carried entering the phase,
        # the central tendency of the same chain and cuts with no readout at all.
        entering = (math.exp(sum(math.log(v) for v in spread) / len(spread))
                    if cuts else point)
        if entering < point:
            point = capped_at = entering
        spread.append(0.0)
    # .get rather than a subscript: a stage added later must not raise on an asset.
    stage_note = {"positive": "at the NDA/BLA gate: ",
                  "filed": "filed, at the NDA/BLA gate: ",
                  "reading_out": "readout due: ",
                  "mixed": "one Phase 3 negative, the rest at their gate: ",
                  "if_met": f"{_PLACED_AT.get(start, 'past its gate')}: ",
                  "entering": ("seamless Phase 2/3 read at the Phase 2 gate: "
                               if phase == "Phase 2/3" else "")}.get(where["stage"], "")
    steps = " x ".join(f"{gate.replace('_', ' ')} {row['pos']:.1%} (n={row['n']})"
                       for gate, row in used)
    basis = (f"{stage_note}{steps} for {label}, BIO/Informa/QLS 2011-2020; "
             f"{where['evidence']}")
    if cuts:
        basis += ("; taken as the central tendency of that and " +
                  ", ".join(f"{c['group']} {c['pos']:.0%}" for c in cuts) +
                  f", giving {point:.1%}")
    if capped_at is not None:
        basis += (f", capped at the {capped_at:.1%} it carried entering the phase because "
                  f"a negative readout never raises the probability")
    split = (_mixed_split(table, used, point, attributes) if where["stage"] == "mixed"
             else _split(used, cuts))
    return {"pos": round(point, 4), "low": round(min(spread), 4),
            "high": round(max(spread), 4), "stage": where["stage"],
            "evidence": where["evidence"], "area": label,
            "chain": [{"gate": g, "pos": r["pos"], "n": r["n"], "source": r["source"]}
                      for g, r in used],
            "cuts": [{k: v for k, v in c.items() if k != "rows"} for c in cuts],
            "refused": [{k: v for k, v in c.items() if k != "rows"} for c in refused],
            "design": _design(where["pivotal"]), "filing": where.get("filing"),
            "basis": basis, "gates": split}


def _mixed_split(table: dict, used: list, point: float, attributes: dict) -> list:
    """The gates of a mixed point, which is the capped area chain rather than a central
    tendency, so its first gate has no published rate of its own.

    The gates after the first are what the asset faces once that gate passes, by the
    rule a passed readout places it with (its cuts read on the shorter chain). The first
    is whatever the point leaves over them: an implied rate, marked so, and the one the
    success leg's gate odds equal."""
    later = tuple(gate for gate, _ in used[1:])
    tail = []
    if later:
        _, rows, _ = _area_chain(table, attributes["report_area"], later)
        cuts, _ = _cuts(table, later, **attributes)
        tail = _split(rows, cuts)
    gate, row = used[0]
    head = {"gate": gate, "label": GATE_LABELS.get(gate),
            "pos": point / _product(t["pos"] for t in tail), "area_pos": row["pos"],
            "cut_pos": {}, "n": row["n"], "implied": True}
    return [head, *tail]


def _design(pivotal: dict | None) -> dict | None:
    """The pivotal trial's shape, as facts. Shown beside the number, never in it: no
    free source publishes success rates by enrolment or masking."""
    if not pivotal:
        return None
    parts = [p.strip() for p in (pivotal.get("design") or "").split(",")]
    return {"nct_id": pivotal.get("nct_id"), "enrollment": pivotal.get("enrollment"),
            "allocation": parts[0] if parts else None,
            "masking": parts[1] if len(parts) > 1 else None,
            "status": pivotal.get("overall_status"),
            "primary_completion": pivotal.get("primary_completion_date"),
            "title": pivotal.get("title")}


def big_pharma(conn, company_id: int) -> bool:
    """Whether the company is read on the pharma engine. The same rule as the universe
    split, so an asset is granular exactly where its owner is a pharma company."""
    row = conn.execute("PRAGMA database_list").fetchone()
    db_path = (row["file"] or None) if row is not None else None
    rates = fx.latest_usd_rates(db_path)
    revenue = productivity.latest_revenue(conn, company_id, rates)
    return engines.assign(conn, company_id, revenue) == engines.PHARMA


def _lead_indication(conn, asset_id: int):
    """The asset_indications row the forecast is built on, by the same rule
    assumptions.load uses for the phase. A filing for any other disease must not lift
    this line."""
    return conn.execute(
        """SELECT id, indication_id FROM asset_indications WHERE asset_id = ?
            ORDER BY is_lead DESC,
                     CASE phase WHEN 'Phase 4' THEN 6 WHEN 'Phase 3' THEN 5
                                WHEN 'Phase 2/3' THEN 4 WHEN 'Phase 2' THEN 3
                                WHEN 'Phase 1/2' THEN 2 WHEN 'Phase 1' THEN 1
                                ELSE 0 END DESC LIMIT 1""", (asset_id,)).fetchone()


def modelled_mesh(conn, asset_id: int, lead_indication: int | None = None) -> list:
    """The MeSH descriptors of the indications the forecast values: those carrying the
    asset's base assumption rows, or the lead indication where no row names one (the
    launch-mode seeds, Litifilimab, Pumitamig, Mezigdomide). A study is in a modelled
    indication when its own descriptors meet these, the test every gate view shares."""
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT indication_id FROM assumptions WHERE asset_id = ?"
        "   AND scenario = 'base' AND indication_id IS NOT NULL", (asset_id,))]
    if not ids and lead_indication is not None:
        ids = [lead_indication]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return sorted(r[0] for r in conn.execute(
        f"SELECT DISTINCT mesh_id FROM indications WHERE id IN ({marks})"
        "   AND mesh_id IS NOT NULL", ids))


# The keys of a _gather result that resolve() takes; the rest are for the gate views.
_RESOLVE_KEYS = ("area", "phase", "names", "company_id", "prevalence_us",
                 "biomarker_selected", "conditions_text", "stored_modality",
                 "lead_indication_id", "modelled_mesh")


def _gather(conn, asset_id: int, *, area: str | None, phase: str | None,
            scalars: dict | None = None, big: bool | None = None) -> dict | None:
    """Everything resolve() needs, gathered from the asset's own rows, including
    ``modelled_mesh``, which resolve hands to stage_of and the gate views use for the
    same indication test. None where the asset is outside the gate: marketed, not Phase
    2 or 3, or not big pharma's. ``big`` lets a caller pass a big_pharma answer it has
    already worked out for the owner."""
    if phase not in FROM_PHASE:
        return None
    asset = conn.execute(
        "SELECT owner_company_id, generic_name, brand_name, internal_code, modality,"
        "       is_marketed FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None or asset["is_marketed"]:
        return None
    if not (big if big is not None else big_pharma(conn, asset["owner_company_id"])):
        return None
    names = [n for n in (asset["generic_name"], asset["brand_name"],
                         asset["internal_code"]) if n]
    # The lead indication's US prevalence, from the row the model already holds.
    prevalence = conn.execute(
        """SELECT a.value FROM assumptions a
             JOIN asset_indications ai ON ai.asset_id = a.asset_id
                                      AND ai.indication_id = a.indication_id
            WHERE a.asset_id = ? AND a.key = 'prevalence' AND a.region = 'US'
              AND a.scenario = 'base' AND a.year IS NULL AND a.value IS NOT NULL
              AND a.unit = 'patients' 
            ORDER BY ai.is_lead DESC, a.value DESC LIMIT 1""", (asset_id,)).fetchone()
    # The indication the forecast is built on. A filing for any other disease must not
    # lift this line.
    lead = _lead_indication(conn, asset_id)
    blob = conn.execute(
        "SELECT GROUP_CONCAT(COALESCE(conditions, '') || ' ' || COALESCE(title, ''), ' ')"
        "  FROM trials WHERE asset_id = ?", (asset_id,)).fetchone()[0] or ""
    return {"area": area, "phase": phase, "names": names,
            "company_id": asset["owner_company_id"],
            "prevalence_us": (prevalence["value"] if prevalence else None),
            "biomarker_selected": bool((scalars or {}).get("biomarker_selected")),
            "conditions_text": blob, "stored_modality": asset["modality"],
            "lead_indication_id": (lead["id"] if lead else None),
            "modelled_mesh": modelled_mesh(conn, asset_id,
                                           lead["indication_id"] if lead else None)}


def _resolve_args(gathered: dict) -> dict:
    return {key: gathered[key] for key in _RESOLVE_KEYS}


def for_asset(conn, asset_id: int, *, area: str | None, phase: str | None,
              scalars: dict | None = None, today=None) -> dict | None:
    """The placement assumptions.load hands the forecast. None where the asset is
    outside the gate: marketed, not Phase 2 or 3, or not big pharma's. It computes no
    legs: they sit beside the valuation and never feed it."""
    gathered = _gather(conn, asset_id, area=area, phase=phase, scalars=scalars)
    if gathered is None:
        return None
    return resolve(conn, asset_id, **_resolve_args(gathered), today=today)


# --- the next gate -------------------------------------------------------------------

def _trials(conn, asset_id: int, phases: tuple, mesh: set) -> list:
    """The asset's studies at these registry phases, largest first as stage_of reads
    them, each with its own indications and whether one of them is modelled. A study
    whose readout has been resolved has answered and is left out, as stage_of leaves it
    out of the studies still asking."""
    marks = ",".join("?" * len(phases))
    answered = set(read_out(conn, asset_id))
    out = []
    for r in conn.execute(
            f"""SELECT nct_id, phase, overall_status, primary_completion_date, enrollment,
                       conditions, mesh_terms, title FROM trials
                 WHERE asset_id = ? AND phase IN ({marks})
                   AND COALESCE(overall_status, '') NOT IN ('Withdrawn')
                 ORDER BY COALESCE(enrollment, 0) DESC""", (asset_id, *phases)):
        if r["nct_id"] in answered:
            continue
        found = indication_mapping.indications_for(
            r["conditions"], indication_mapping.parse_browse(r["mesh_terms"]))
        out.append({"nct_id": r["nct_id"], "phase": r["phase"],
                    "status": r["overall_status"],
                    "primary_completion": r["primary_completion_date"],
                    "enrollment": r["enrollment"], "title": r["title"],
                    "indications": [t["term"] for t in found],
                    "modelled": bool({t["id"] for t in found} & mesh)})
    return out


def _held(conn, asset_id: int, placement: dict, trial: dict, today: str) -> dict | None:
    """What the model does after one miss at a Phase 3 gate while other Phase 3s stay
    open: stage_of's mixed rule, which counts every open Phase 3 completing after the
    negative in any indication, and holds the asset at the capped mixed point."""
    after = max(trial.get("primary_completion") or today, today)
    others = [t for t in _trials(conn, asset_id, _GATE_PHASES["p3_to_nda"], set())
              if t["nct_id"] != trial["nct_id"] and t["status"] in OPEN_STATUSES
              and (t["primary_completion"] or "9999") > after]
    if not others:
        return None
    # The same arithmetic resolve's mixed branch runs on the same chain and cuts: the
    # area chain, never above the point the asset carries today.
    area = _product(c["pos"] for c in placement.get("chain") or [])
    entering = _product(g["pos"] for g in placement.get("gates") or [])
    pos = round(min(area, entering), 4)
    return {"open": len(others), "ncts": [t["nct_id"] for t in others],
            "indications": sorted({i for t in others for i in t["indications"]}),
            "pos": pos,
            "note": (f"A miss leaves {len(others)} other Phase 3 open, and the model holds "
                     f"it at {pos:.0%} until they read out.")}


def next_gate(conn, asset_id: int, placement: dict | None, modelled_mesh, today=None, *,
              gate: str | None = None, lead_indication_id=None) -> dict | None:
    """The event that decides the asset next: the one gate source, and GATE_LABELS the
    one label map, for every view that prices or costs a gate.

    The gate is the first transition left in the placement's chain, or ``gate`` where a
    caller has placed the asset elsewhere. At a Phase 3 gate the trial is the passed
    study stage_of named where the asset is reading out, else the soonest open Phase 3
    completing on or after today; at a Phase 2 gate, the soonest open Phase 2 or 2/3.
    Either way only a study in an indication the forecast values counts, the indication
    guard every gate view carries. At the FDA gate there is no trial, and the date is
    the decision date on an accepted application where one lifts. ``why`` says what is
    missing when a trial or a date is not found; ``held`` is the mixed rule at a Phase 3
    gate where other Phase 3s stay open.
    """
    if not placement or placement.get("stage") == "negative":
        return None
    chain = placement.get("chain") or []
    first = chain[0]["gate"] if chain else None
    gate = gate or first
    if gate not in GATE_LABELS:
        return None
    today_date = today or dt.date.today()
    iso = today_date.isoformat()
    out = {"gate": gate, "label": GATE_LABELS[gate], "trial": None, "date": None,
           "date_basis": None, "due": False, "held": None, "why": None}
    if gate == "nda_to_approval":
        filing = placement.get("filing")
        if not (filing or {}).get("lifts"):
            if lead_indication_id is None:
                row = _lead_indication(conn, asset_id)
                lead_indication_id = row["id"] if row else None
            filing = applications.filed_for(conn, asset_id, lead_indication_id,
                                            today=today_date)
        if (filing or {}).get("lifts"):
            out.update(date=filing["date"],
                       date_basis="the FDA decision date on the accepted application")
        else:
            out["why"] = "no accepted application on file, so no decision date is known"
        return out

    mesh = set(modelled_mesh or ())
    if not mesh:
        out["why"] = ("no indication the forecast values carries a MeSH descriptor, so no "
                      "study can be matched to it")
        return out
    trial, note = None, None
    if placement.get("stage") == "reading_out" and gate == first:
        passed = [t for t in _trials(conn, asset_id, _GATE_PHASES["p3_to_nda"], mesh)
                  if (t["primary_completion"] or "9999") <= iso]
        trial = next((t for t in passed if t["modelled"]), None)
        if trial is None and passed:
            note = (f"{passed[0]['nct_id']} passed primary completion in an indication the "
                    f"forecast does not value")
    rows = _trials(conn, asset_id, _GATE_PHASES[gate], mesh)
    open_rows = [t for t in rows if t["status"] in OPEN_STATUSES]
    if trial is None:
        upcoming = sorted((t for t in open_rows if t["modelled"]
                           and (t["primary_completion"] or "") >= iso),
                          key=lambda t: (t["primary_completion"], -(t["enrollment"] or 0)))
        overdue = sorted((t for t in open_rows if t["modelled"] and t["primary_completion"]
                          and t["primary_completion"] < iso),
                         key=lambda t: t["primary_completion"], reverse=True)
        trial = upcoming[0] if upcoming else overdue[0] if overdue else None
    if trial is None:
        phase_word = "Phase 3" if gate == "p3_to_nda" else "Phase 2"
        elsewhere = len([t for t in open_rows if not t["modelled"]])
        out["why"] = "; ".join(filter(None, (
            note, (f"{elsewhere} open {phase_word} "
                   f"{'study' if elsewhere == 1 else 'studies'}, none in an indication the "
                   f"forecast values" if elsewhere else
                   f"no open {phase_word} study on the registry"))))
        return out
    due = (trial["primary_completion"] or "9999") < iso
    out.update(trial={k: trial[k] for k in ("nct_id", "phase", "status",
                                            "primary_completion", "enrollment",
                                            "indications", "title")},
               date=trial["primary_completion"], due=due,
               date_basis=("primary completion on the registry, passed with no readout "
                           "on file" if due else "primary completion on the registry"),
               why=note)
    if gate == "p3_to_nda":
        out["held"] = _held(conn, asset_id, placement, trial, iso)
    return out


# --- success and failure legs --------------------------------------------------------

def _and(words: list) -> str:
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


_FAILURE = "a failure is taken at nil, the model's convention for a failed programme"


def legs(conn, asset_id: int, placement: dict | None, gathered: dict | None, today=None,
         table=None, *, stated_pos: float | None = None) -> dict | None:
    """What the asset is worth, as a probability, if its next gate passes and if it
    fails. Derived beside the valuation and never fed back into it.

    The success leg is the probability resolve() gives the asset placed at the
    following gate, by the same cut rule, so a passed readout recorded later lands on
    it exactly: the NDA/BLA step after a Phase 3 readout, Phase 3 entry after a Phase 2
    readout, and 1.0 after an FDA decision. The failure leg is nil at every gate, graded
    convention: it is the model's own answer for a failed programme, and it is what
    makes the two legs average back to today's value, p_gate x pos_success = pos_now,
    with p_gate left unrounded for that reason. Where other Phase 3s stay open the
    model would hold the asset after one miss rather than drop it, and ``held`` says so
    beside the leg rather than in it.

    ``p_gate`` is published where the asset carries the placement's own point: it is
    then the first gate of the split, to rounding. It is implied where the point is a
    mixed one, and where a stated probability governs (``stated_pos``), which is divided
    by the same success leg. A stated probability at or above the success leg prices a
    filing the book's phase does not carry, so the asset is read at the FDA decision
    instead: success 1.0, failure nil, gate odds the stated probability, labelled
    "stated PoS implies a filing".

    None where there is no placement, the stage is negative, or the probability in
    force is nil: nothing is left to win or lose at a gate.
    """
    if not placement or not gathered or placement.get("stage") == "negative":
        return None
    chain = placement.get("chain") or []
    if not chain:
        return None
    pos_now = placement["pos"] if stated_pos is None else stated_pos
    if not pos_now:
        return None
    table = table if table is not None else transitions()
    first = chain[0]["gate"]
    if first == "nda_to_approval":
        pos_success, success_gates = 1.0, []
    else:
        placed = resolve(conn, asset_id, **_resolve_args(gathered), today=today,
                         table=table, at_gate=CHAIN[CHAIN.index(first) + 1])
        pos_success, success_gates = placed["pos"], placed["gates"]
    stated = stated_pos is not None
    mixed = placement.get("stage") == "mixed"
    common = {"legs_basis": "derived", "pos_now": pos_now, "pos_failure": 0.0,
              "stated": stated}
    where = dict(modelled_mesh=gathered.get("modelled_mesh"),
                 lead_indication_id=gathered.get("lead_indication_id"))

    if stated and first != "nda_to_approval" and pos_now >= pos_success - STATED_PAST_GATE:
        nxt = next_gate(conn, asset_id, placement, today=today, gate="nda_to_approval",
                        **where)
        label = GATE_LABELS[first]
        return {**common, **_event(nxt), "pos_success": 1.0, "p_gate": pos_now,
                "p_gate_published": None, "held": None,
                "placed": "stated PoS implies a filing",
                "passed_gate": first, "pos_success_at_gate": pos_success,
                "gates": [{"gate": "nda_to_approval",
                           "label": GATE_LABELS["nda_to_approval"], "pos": pos_now,
                           "implied": True, "published_pos": None}],
                "evidence": {"p_gate": "implied", "success": "convention",
                             "failure": "convention"},
                "basis": (f"stated PoS implies a filing: the stated {pos_now:.1%} is at or "
                          f"above the {pos_success:.1%} the asset would carry if its "
                          f"{label} passed, so it is read at the FDA decision with gate "
                          f"odds of {pos_now:.1%}, implied, not published; {_FAILURE}")}

    nxt = next_gate(conn, asset_id, placement, today=today, **where)
    p_gate = pos_now / pos_success
    published = None if mixed else (placement.get("gates") or [{}])[0].get("pos")
    implied = stated or mixed
    label = GATE_LABELS[first]
    split = [{"gate": first, "label": label, "pos": p_gate, "implied": implied,
              "published_pos": published}, *success_gates]
    steps = " then ".join(f"{_STEP_NAMES[g['gate']]} {g['pos']:.1%}" for g in split)
    after = " then ".join(f"{_STEP_NAMES[g['gate']]} {g['pos']:.1%}"
                          for g in success_gates) or "approval"
    if stated:
        basis = (f"implied, not published: the stated PoS of {pos_now:.1%} over the "
                 f"{pos_success:.1%} the asset carries if its {label} passes gives gate "
                 f"odds of {p_gate:.1%}"
                 + (f", against {published:.1%} published" if published is not None else "")
                 + f"; {_FAILURE}")
    elif mixed:
        basis = (f"implied, not published: one Phase 3 has read out negative, so the gate "
                 f"odds of {p_gate:.1%} are what the model's {pos_now:.1%} leaves over the "
                 f"{pos_success:.1%} that follows ({after}); {_FAILURE}")
    else:
        groups = [placement.get("area")] + [c["group"] for c in placement.get("cuts") or []]
        basis = (f"{steps} for {_and(groups)}, BIO/Informa/QLS 2011-2020; {_FAILURE}")
    held = nxt.get("held") if nxt else None
    if held and stated:
        held = _stated_held(held)
    return {**common, **_event(nxt), "pos_success": pos_success, "p_gate": p_gate,
            "p_gate_published": published, "held": held, "placed": None,
            "gates": split,
            "evidence": {"p_gate": "implied" if implied else "published",
                         "success": "published" if success_gates else "convention",
                         "failure": "convention"},
            "basis": basis}


def _stated_held(held: dict) -> dict:
    """The held note where a stated probability governs: the model's own rule would hold
    the asset, and the analyst's figure still decides what it is worth."""
    return {**held, "stated_governs": True,
            "note": (f"A miss leaves {held['open']} other Phase 3 open; the model's own "
                     f"rule would hold it at {held['pos']:.0%}, but the stated PoS "
                     f"governs until it is cleared.")}


def held_after(conn, asset_id: int, placement: dict | None, nct_id: str,
               primary_completion: str | None, today=None, *, stated: bool = False):
    """``held`` for a miss on this particular Phase 3, where a view prices a readout
    other than the one next_gate named: the same mixed rule, counted from that study."""
    if not placement or placement.get("stage") == "negative":
        return None
    iso = (today or dt.date.today()).isoformat()
    held = _held(conn, asset_id, placement,
                 {"nct_id": nct_id, "primary_completion": primary_completion}, iso)
    return _stated_held(held) if (held and stated) else held


def legs_for_inputs(conn, asset_id: int, inputs: dict | None, today=None,
                    table=None) -> tuple:
    """(legs, gathered) for a forecast assumptions.load has already put together: its
    own placement and its own scalars, so the legs belong to the build a view shows,
    scenario and all. (None, None) where the asset has no placement. The placement
    exists only for a big pharma asset, so the owner is not asked again."""
    placement = (inputs or {}).get("pos_granular")
    if not placement:
        return None, None
    gathered = _gather(conn, asset_id, area=inputs.get("therapeutic_area"),
                       phase=inputs.get("phase"), scalars=inputs.get("scalars"), big=True)
    if gathered is None:
        return None, None
    return (legs(conn, asset_id, placement, gathered, today, table,
                 stated_pos=stated_pos(inputs.get("scalars"))), gathered)


def in_modelled(conn, nct_id: str, modelled_mesh) -> tuple:
    """(whether the study is in an indication the forecast values, its indications):
    the one MeSH test every gate view and stage_of's resolved readouts share."""
    row = conn.execute("SELECT conditions, mesh_terms FROM trials WHERE nct_id = ?",
                       (nct_id,)).fetchone()
    if row is None:
        return False, []
    found = indication_mapping.indications_for(
        row["conditions"], indication_mapping.parse_browse(row["mesh_terms"]))
    return bool({t["id"] for t in found} & set(modelled_mesh or ())), [t["term"] for t in found]


def _event(nxt: dict | None) -> dict:
    nxt = nxt or {}
    return {key: nxt.get(key) for key in ("gate", "label", "trial", "date", "date_basis",
                                          "due", "why")}


def _phase(conn, asset_id: int) -> str | None:
    """The asset's phase by assumptions.load's own rule: its furthest indication."""
    row = conn.execute(
        """SELECT phase FROM asset_indications WHERE asset_id = ?
            ORDER BY CASE phase WHEN 'Phase 4' THEN 6 WHEN 'Phase 3' THEN 5
                     WHEN 'Phase 2/3' THEN 4 WHEN 'Phase 2' THEN 3
                     WHEN 'Phase 1/2' THEN 2 WHEN 'Phase 1' THEN 1 ELSE 0 END DESC
            LIMIT 1""", (asset_id,)).fetchone()
    return row["phase"] if row else None


def _base_scalars(conn, asset_id: int) -> dict:
    """The asset-level base rows, enough to tell a stated probability and a recorded
    biomarker; assumptions.load's scalars where a caller already holds them."""
    return {r["key"]: (r["value"] if r["value"] is not None else r["text_value"])
            for r in conn.execute(
                "SELECT key, value, text_value FROM assumptions WHERE asset_id = ?"
                "   AND scenario = 'base' AND indication_id IS NULL AND year IS NULL",
                (asset_id,))}


def stated_pos(scalars: dict | None) -> float | None:
    """The probability an analyst has stated, or built from composite factors, which
    the forecast takes ahead of any placement; None where the placement governs."""
    import forecast
    value, basis = forecast.pos(scalars or {})
    return value if basis in ("stated", "composite factors") else None


def legs_for_asset(conn, asset_id: int, *, area: str | None = None,
                   phase: str | None = None, scalars: dict | None = None, today=None,
                   big: bool | None = None, table=None) -> dict | None:
    """legs() for one asset from its own rows. ``area`` defaults to product_areas'
    reading and ``phase`` to assumptions.load's; ``big`` lets a caller pass a big_pharma
    answer it has memoised per company. The probability in force follows the forecast:
    a stated or composite figure first, the placement otherwise."""
    if area is None:
        import product_areas
        area = product_areas.area_for(conn, asset_id)
    phase = phase if phase is not None else _phase(conn, asset_id)
    scalars = scalars if scalars is not None else _base_scalars(conn, asset_id)
    gathered = _gather(conn, asset_id, area=area, phase=phase, scalars=scalars, big=big)
    if gathered is None:
        return None
    table = table if table is not None else transitions()
    placement = resolve(conn, asset_id, **_resolve_args(gathered), today=today,
                        table=table)
    return legs(conn, asset_id, placement, gathered, today, table,
                stated_pos=stated_pos(scalars))
