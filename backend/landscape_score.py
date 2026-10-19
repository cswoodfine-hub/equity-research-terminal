"""Every candidate's clinical record as two scores, so one chart can place them all.

The landscape holds each drug's trials arm by arm: dozens of endpoints in different units,
and a safety record per trial. No single endpoint is shared by every drug in a disease, so
a chart on one measure leaves most of them out. This reads the whole record instead and
turns it into scores from 0 to 100, each built only from what the registry posted. The
method is written out in docs/design/clinical-scorecard-statistics.md; the arithmetic is
in meta_stats.

**One result per drug, trial and endpoint.** A result is the drug's only where an arm
names the drug (its title, or its description as the arm's own treatment) and the
comparator arm does not, by its full name or a shortened one ("Pembro + Placebo"); an arm
that adds another candidate the control lacks is not the drug's alone. Its effect and
standard error come from the sponsor's interval first, then the arms' own spread or
counts, a p-value last; a time to an event needs a posted hazard ratio and is read from
nothing else. A trial of several doses is tested on all of them together and sized on the
best dose, trimmed for having picked the best. Which way helps the patient is read from
the measure (a standard measure or an instrument fixes its own; a count of people with an
event or a harm is lower-is-better, a count of responders higher), then the title, then
the way most drugs moved it; an endpoint whose direction nothing settles is counted as
unscored, never guessed. A result from a trial built to show a drug no worse than its
comparator is left out unless it shows the drug better.

**Efficacy**, the mean of the parts the drug has:

- *Strength.* How far past chance the average trial result is: the mean of its trials'
  z-scores (each result capped at 5), 100 at 3.29 (p = 0.001).
- *Wins.* The mean over trials of the share of that trial's endpoints won, each trial's
  one-sided p corrected for the endpoints that trial tested (Benjamini-Hochberg); a win at
  0.025. Strength and wins from one or two trials are moved toward the mean of every drug
  in the indication, by how little those trials say on their own.
- *Size against peers.* Where three or more drugs were tested on the same measure against
  the same control in trials of about the same length, and the spread between trials on
  that measure rests on five or more degrees of freedom: each drug's trials averaged with
  the measure's one between-trial variance, a class of four or more drugs of one mechanism
  first moved part of the way to its average, then the mean chance of beating each peer.
  A drug added to a regimen is never averaged with one tested instead of it. Where some
  measure here is ranked and a drug is on none, its size counts at 50: size is a mean chance
  of beating peers, which averages 50 over any cell's drugs, so the drug is placed level with
  its peers rather than carried past them on strength and wins, which saturate. Where no
  measure is ranked, efficacy is strength and wins alone for every drug.

**Safety and tolerability.** Withdrawals for side effects and serious adverse events, each
averaged trial by trial against the control of each controlled trial (Mantel-Haenszel risk
difference), against placebo or against active comparators, whichever holds more of the
drug's people. The interval is widened for disagreement between trials, by one factor per
part and kind of control across every drug. Each part scores 75 when equal to control and
loses 5 points per percentage point of excess; the two count equally, a part posted for
under a quarter of the people behind the other is left out and named, less 10 for an FDA
boxed warning. An outcomes trial's serious adverse events are left out, since they are
largely the events it counts as its result. Deaths are reported and never scored: in a
cancer trial they measure the disease, which is efficacy.

**Weight of evidence** is the people treated across a drug's trials with posted safety
counts, on a log scale (100 people 25, 1,000 people 50, 10,000 people 75), plus 20 where
results come from Phase 3. It is the bubble size on the chart. **Overall** is the mean of
the three, so a strong result on one small trial does not outrank a drug proven on
thousands of people.

No score carries an interval. The rank carries one range: where it falls in 95 of 100
redraws of every trial's effect and safety count within its own margin of error. A drug
with no posted result has no score: it is listed, by stage, beside the chart, with the
reason.

Every comparison crosses trials. The scores order the evidence; they are not a
head-to-head result, and the view says so.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict

import landscape_overview as O
import meta_stats as M

# --- constants (specification 2.14) -------------------------------------------------------
Z_FULL = 3.29            # the mean trial z that scores full strength (p = 0.001)
Z_CAP = M.Z_CAP          # 5: a p of zero says no more than "beyond the table"
P_FLOOR = M.P_FLOOR
SHARED_MIN = 3           # drugs on a measure and control before it is ranked
CLASS_MIN = 4            # drugs of one mechanism on a measure and control before a class prior
WIN_LEVEL = 0.025        # one-sided level of a win after the correction: the two-sided 5%
WIN_TOL = 1e-9
AGREE = 0.25             # an analysis estimate against the arms' own difference
OFF_CENTRE = M.OFF_CENTRE
LENGTH_TOL = 0.25        # how near two drugs' trial lengths must come for a gap to be printed
SAME_TRIALS = 0.5        # share of trials in common above which two measures count once
DISAGREE_P = 0.10        # p of a drug's own Q below which its trials "disagree"
DISAGREE_MIN = 3         # trials before that sentence can print
I2_MIN = 5               # trials before I2 is quoted (meta_stats.pool_common)
TAU_DF_MIN = 5           # degrees of freedom the between-trial variance needs before a rank
TAU_DF_FEW = 10          # under this a ranked measure's interval is flagged as likely too narrow
TIE = (0.45, 0.55)       # a chance of beating a peer inside this cannot be called
MOVED_MIN = 0.05         # a move toward the class average smaller than this is not narrated
DOMINANT = 0.5           # share of a safety weight one trial must exceed to be named
PART_MIN_SHARE = 0.25    # a safety part behind fewer people than this share of the other is not scored
THIN_SHARE = 0.20        # safety resting on under this share of the people treated is flagged
LEVEL = 95.0             # level of every interval and of the rank range
DRAWS = 2000
SEED = 20260930
MIN_PARTICIPANTS = 100   # people on the drug's controlled arms below which safety is flagged
SAME_AS_CONTROL = 75.0   # the safety score of a drug no worse than its control
POINTS_PER_PP = 5.0      # score lost per percentage point of excess over control
BOXED_DEDUCTION = 10.0
SIZE_UNKNOWN = 50.0      # size of a drug with no comparable peer where others have one: the scale's average
PHASE3_EVIDENCE = 20.0   # added to the weight of evidence where Phase 3 results exist

# A secondary outcome is often not efficacy at all: exposure, antibodies, or a count of
# adverse events, which the safety score already reads.
_NOT_EFFICACY = re.compile(
    r"adverse event|\bteaes?\b|\bsaes?\b|anti-?drug antibod|immunogenic|pharmacokinetic|"
    r"concentration|\bcmax\b|\bauc\b|trough|half-life|\bpk\b|tolerab|discontinu|"
    r"magnetic resonance|\bfmri\b|activation|dose intensity|mutation burden", re.I)
# "AE", "AEs" and laboratory or examination abnormalities, read from the title.
_AE = re.compile(r"\baes?\b|abnormalit", re.I)
# A time measured to an event, or a stretch free of one: "time to first exacerbation",
# "time from randomization to the occurrence of a bipolar event", "duration of flare-free
# maintenance". Longer is better, unless the event is a good one (relief, response).
_TIME_TO = re.compile(r"\btime to\b|\btime from\b.{0,60}?\bto\b|"
                      r"\bduration of\b.{0,40}?(\bfree\b|-free|\buntil\b|response|remission)",
                      re.I)
_GOOD_EVENT = re.compile(r"relief|onset|respon|remission|recover|resolution|heal|improv|"
                         r"clearance|normali|analges|sustained|cure", re.I)
_BAD_EVENT = re.compile(
    r"exacerbation|relapse|progression|death|\bdied\b|mortality|hospitali[sz]|fracture|stroke|"
    r"infarction|failure|\bevents?\b|recurrence|worsening|rescue|flare", re.I)
# Measures whose instrument fixes the direction whatever its other words say: a pain
# relief sum (SPID, SPRID, TOTPAR), a heart failure or health status score where higher
# is better (KCCQ, SF-36, EQ-5D), lung function; and scores where lower is better.
_INSTR_LOWER = re.compile(r"\bsgrq\b|st\.? george|\bdlqi\b|dermatology life quality|"
                          r"\bmlhfq\b|minnesota living", re.I)
_INSTR_HIGHER = re.compile(
    r"\bspr?id\b|\btotpar\b|pain relief|pain intensity difference|\bkccq\b|"
    r"kansas city cardiomyopathy|\bfev ?1\b|\bfvc\b|peak expiratory|quality of life|\bqol\b|"
    r"\bsf-?36\b|\beq-?5d\b|6[- ]minute walk|\b6mwd?\b", re.I)
_HIGHER = re.compile(
    r"surviv|respon[ds]|remission|achiev|clearance|improvement|normoglyc|normali[sz]|"
    r"benefit rate|disease control|\bos\b|\bpfs\b|\borr\b|"
    r"\bdfs\b|\befs\b|\bdor\b|progression[- ]free|disease[- ]free|event[- ]free", re.I)
# A count of people is a good outcome only where a word says so; otherwise nothing fixes
# its direction here.
_PEOPLE_OF = re.compile(r"(percentage|proportion|number|percent) of (participants|patients|"
                        r"subjects)", re.I)
_RESPONDER = re.compile(r"respon|achiev|remission|\bclear|improv|success|sero|\bfree\b|-free|"
                        r"normali|normoglyc|\bcure|resolution|heal|abstinen|attain|reach|"
                        r"target|[<≤]\s*\d|below|less than", re.I)
# A count of people with a harm or with the disease a vaccine prevents is lower-is-better.
_HARM = re.compile(r"reaction|bleed|haemorrh|hemorrh|hypoglyc|infection|fever|pyrexia|"
                   r"temperature|neoplasia|\bcin ?\d|disability|hyperplasia|solicited|"
                   r"injection[- ]site|gastroenteritis|lower respiratory", re.I)
_LOWER = re.compile(
    r"\bweight\b|\bbmi\b|body mass|waist|hba1c|glyc|glucose|\bldl\b|cholesterol|triglycerid|"
    r"blood pressure|pain|severity|viral load|tumou?r size|lesion|symptom|albuminuria|"
    r"uric acid|\bige\b|eosinophil|plaque|fat mass|liver fat", re.I)
# People counted with an event are lower-is-better, whatever survival word the title holds.
_EVENT_COUNT = re.compile(r"\bevents?\b(?![- ]free)|\bwho died\b|\bdeaths?\b|"
                          r"progression or death", re.I)

# The standard measures, however a sponsor words them: (family, what the title says, the
# class of unit it must be in). A title naming a subgroup stays out of a ranking, so a drug
# is ranked on its whole population and never on its best slice.
_FAMILIES = (
    ("percent change in body weight", re.compile(r"\bweight\b", re.I), "percent"),
    ("share losing 5% or more of body weight",
     re.compile(r"weight.*(5 ?%|5 percent|five percent)|(5 ?%|5 percent).*weight", re.I), "share"),
    ("change in HbA1c",
     re.compile(r"hba1c|\ba1c\b|glycated h(a)?emoglobin|h(a)?emoglobin a1c", re.I), "percent"),
    ("overall survival", re.compile(r"overall survival|\bos\b", re.I), "time"),
    ("progression-free survival",
     re.compile(r"progression[- ]free survival|\bpfs\b", re.I), "time"),
    ("disease-free or event-free survival",
     re.compile(r"(disease|event)[- ]free survival|\bdfs\b|\befs\b", re.I), "time"),
    ("response rate", re.compile(r"(objective|overall) response|\borr\b", re.I), "share"),
    ("percent change in LDL cholesterol", re.compile(r"\bldl\b", re.I), "percent"),
)
# A family fixes its own direction of benefit; the title's other words never do.
FAMILY_SIGN = {"percent change in body weight": -1,
               "share losing 5% or more of body weight": 1,
               "change in HbA1c": -1, "overall survival": 1, "progression-free survival": 1,
               "disease-free or event-free survival": 1, "response rate": 1,
               "percent change in LDL cholesterol": -1}
TIME_FAMILIES = {"overall survival", "progression-free survival",
                 "disease-free or event-free survival"}
SHARE_FAMILIES = {"share losing 5% or more of body weight", "response rate"}
_SUBGROUP = re.compile(
    r"subgroup|sub-group|\btps\b|pd-?l1|positive|negative|mutation|mutant|cohort|\btc\d|"
    r"\bic\d|female|male\b|stratum|population\)?$|-wt\b", re.I)
# The analysis set a title names is who was analysed, not a slice of them: "evaluable
# population", "full analysis set", "ITT population", "per protocol". Taken off before a
# subgroup is looked for, and off the measure a sentence names.
_ANALYSIS_SET = re.compile(
    r"[\s,;:\-–(\[]*\b(evaluable|full analysis|intent(ion)?[- ]to[- ]treat|m?itt|modified itt|"
    r"per[- ]protocol|efficacy|safety|all randomi[sz]ed|completers?|analysis)\b"
    r"[^()\[\]]{0,30}?\b(population|set|analysis|participants)\b[)\]]?\s*$", re.I)
_SURVIVAL = re.compile(r"overall survival|\bos\b|progression[- ]free survival|\bpfs\b|"
                       r"(disease|event)[- ]free survival|\bdfs\b|\befs\b", re.I)
_MONTHS_PER = {"month": 1.0, "week": 1 / 4.345, "day": 1 / 30.44, "year": 12.0}

_PHASE_RANK = {"Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3, "Phase 2/3": 4, "Phase 3": 5,
               "Phase 4": 5}

# What a posted analysis row and an outcome's unit are.
_RATIO = re.compile(r"ratio|\bhr\b|\bor\b|\brr\b|odds|hazard|relative risk|fold", re.I)
_HAZARD = re.compile(r"hazard|\bhr\b", re.I)
_BARE_MEAN = re.compile(r"^\s*(ls|least[- ]squares?|geometric|adjusted)?\s*(mean|median)s?\s*$",
                        re.I)
_TOTAL_ARM = re.compile(r"^\s*(all|total|pooled|combined|overall)\b", re.I)
_ONE_SIDED = re.compile(r"\b(1|one)[- ]?sided\b", re.I)
# A result a trial was built to show is no worse than its comparator, or equivalent to it.
_NON_INFERIOR = re.compile(r"non-?\s?inferior|equivalen", re.I)
_NEGATION = re.compile(r"^(no|none|not\b.*|non[- ]?\w.*|without\b.*|censored)$", re.I)
_PCT_OF_PEOPLE = re.compile(r"^\s*(percentage|percent|proportion|%)\s*(\(%\))?\s*of\s+"
                            r"(participants|patients|subjects)", re.I)
_PEOPLE = re.compile(r"^\s*(number of\s+)?(participants|patients|subjects)\s*$", re.I)
_BARE_PCT = re.compile(r"^\s*(percentage|percent|proportion|%)\s*(\(%\))?\s*$", re.I)
_SHARE_TITLE = re.compile(r"(percentage|percent|proportion)\s+of\s+(participants|patients|"
                          r"subjects)", re.I)
# A change measured from a randomisation that came after treatment began: both arms were on
# the drug before it and the placebo arm is coming off it (STEP 4, SURMOUNT-4).
_WITHDRAWAL = re.compile(r"randomi[sz]ation\s*\(\s*week\s*([1-9]\d*)\s*\)", re.I)

# The control a result was read against, from the control arm's title.
_PAREN = re.compile(r"\([^)]*\)")
_PLACEBO_WORD = re.compile(r"\b(placebo|vehicle|sham|dummy)\b", re.I)
_KEY_DROP = frozenset("""placebo vehicle sham dummy matching matched pooled combined comparator
and plus with or vs to by of the for in on followed then without
arm part cohort group phase treatment sub study substudy global step wise period main base
randomized randomised mtd mg kg ml units unit iu qd qw od bid tid once twice daily weekly monthly
low high dose titrated xr er ir sr oral iv sc injection tablet capsule infusion db dbw ip only
nsclc sclc""".split())
# Words a placebo arm's title carries about who was in it or when, not what it was given.
_KEY_PERIOD = frozenset("""years year old age aged months weeks days season seasons double blind
single bd bds day twice stage stratum strata panel panels matched dbtp dbt induction core
maintenance extension part parts period periods cohort cohorts children adults adolescents
infants participants subjects patients pooled all first second third primary series visit
lead""".split())
# A placebo arm that later switched: "Placebo followed by X", "Placebo - X".
_PLACEBO_THEN = re.compile(r"\b(placebo|vehicle|sham)\b\s*(->|→|-(?=\s)|\bthen\b|"
                           r"\bfollowed by\b|\bswitch(ed)? to\b|\bto\b(?=\s+[a-z]))\s*.*$")
_KEY_GENERIC = frozenset("""chemotherapy chemo soc standard care physician physicians investigator
investigators choice supportive best usual observation control active monotherapy single agent
alone ct tpc background therapy antidiabetic oam experimental doublet platinum taxane""".split())

# An outcomes trial: its primary endpoint counts cardiovascular, kidney or death events.
_OUTCOMES = re.compile(r"cardiovascular|\bcv\b|\bmace\b|major adverse (cardi|kidney|renal)|"
                       r"myocardial infarction|\bstroke\b|heart failure|renal|kidney|"
                       r"end[- ]stage|dialysis|all[- ]cause (death|mortality)", re.I)
_OUTCOME_EVENTS = re.compile(r"time to|time from|occurrence|composite|\bevents?\b|incidence|"
                             r"participants with|hospitali", re.I)

# Safety arms: a period or cohort a title states, and an arm that is not the drug's own
# randomised treatment.
_PERIOD = re.compile(
    r"\b(weeks?|wks?|periods?|parts?|phases?|days?|months?|cohorts?|sub-?stud(?:y|ies))"
    r"\s*((?:\d+|[a-z]\b)"
    r"(?:\s*(?:-|–|to|through|\+|&|and|/)\s*(?:\d+|[a-z]\b))*)|(double[- ]blind)", re.I)
# An arm not randomised to the drug: a crossover, an optional switch after the control
# ("Post Chemotherapy Optional Nivolumab"), an extension. Never the drug's in efficacy.
_CROSSOVER = re.compile(r"cross[- ]?over|switch|optional|extension|rollover|\bole\b|\blte\b",
                        re.I)
_SWITCH = re.compile(r"switch|cross[- ]?over|extension|optional|open[- ]label|\bol\b|\bole\b|\blte\b|"
                     r"rescue|long[- ]term|follow[- ]up|(placebo|control|soc)\s*(/|->|→|to\b|then\b)",
                     re.I)

# The scale an effect is on, as the output names it. "other" is the p-value route: the
# posted difference, never averaged.
_SCALES = ("difference", "share", "log hazard ratio", "log ratio", "other")
_UNSCORED_LABEL = {"not its arm": "no arm names the drug",
                   "in both arms": "the comparator arm also contains the drug",
                   "nothing to test": "nothing posted to test it with",
                   "no hazard ratio": "a time to an event with no hazard ratio posted",
                   "no control": "no arm the book can read as its control",
                   "orientation": "a hazard ratio its medians contradict",
                   "direction": "direction of benefit not clear"}
_PART = {"withdrawn": ("staying_on", "Stopped for side effects"),
         "serious": ("serious", "Serious adverse events")}
_PART_NOUN = {"withdrawn": "withdrawals for side effects", "serious": "serious adverse events"}


# --- p-values, direction and families ------------------------------------------------------
def p_to_z(text) -> float | None:
    """The normal deviate of a reported two-sided p-value, unsigned, or None where the text
    is not one. "<0.001" is read at its bound, which can only understate the result. A
    bound above (">0.05") gives no test statistic at all: none is made up from the middle
    of what it allows."""
    got = M.parse_p(text)
    if got is None or got[1] == "above":
        return None
    return M.z_of_p(got[0])


def _unit_class(unit: str | None, param_type: str | None = None) -> str | None:
    """The class of a unit: a share of participants, a percent change, or a time."""
    u = (unit or "").lower()
    if re.search(r"participant|patient|subject", u):
        return "share"
    if re.search(r"\b(month|week|day|year)s?\b", u):
        return "time"
    if "%" in u or "percent" in u:
        return "percent"
    return None


def family_of(group: dict, whole_population: bool = True) -> str | None:
    """The standard measure an endpoint is a wording of. With ``whole_population`` a
    subgroup stays out, since a subgroup is never ranked; without it the family is still
    named, so its direction of benefit is the family's."""
    title = _ANALYSIS_SET.sub("", group.get("title") or "")
    if whole_population and _SUBGROUP.search(title):
        return None
    cls = _unit_class(group.get("unit"), group.get("param_type"))
    for name, pattern, want in _FAMILIES:
        if cls == want and pattern.search(title):
            return name
    return None


def measure_family(group: dict) -> str | None:
    """The standard measure an endpoint is a wording of, or None where it is its own or
    names a subgroup."""
    return family_of(group, whole_population=True)


def _title_direction(title: str, unit: str) -> int | None:
    """The direction the title's words give, where no family and no count of events has
    settled it (specification 2.2). In order: a time to an event (longer is better,
    shorter for a good event such as relief); an instrument that fixes its own direction; a
    count of people, which is a good outcome only where a responder word says so and a
    bad one where it names a harm or an event; then the title's other words."""
    text = f"{title} {unit}"
    # A survival measure reported as a count of events reads the other way up from its
    # name; the two cannot both be trusted, so it is left unscored.
    if re.search(r"surviv", title, re.I) and re.search(r"event", unit, re.I):
        return None
    if _TIME_TO.search(title):
        return -1 if _GOOD_EVENT.search(title) else 1
    if _INSTR_LOWER.search(text):
        return -1
    if _INSTR_HIGHER.search(text):
        return 1
    if _PEOPLE_OF.search(text):
        free = re.search(r"free|without|no (relapse|progression|exacerbation)", text, re.I)
        if (_BAD_EVENT.search(text) or _HARM.search(text)) and not free:
            return -1
        if _RESPONDER.search(text) or _HIGHER.search(text):
            return 1
        return None
    if _HIGHER.search(text):
        return 1
    if _LOWER.search(text) or _BAD_EVENT.search(text) or _HARM.search(text):
        return -1
    return None


def benefit_direction(title: str | None, unit: str | None = None,
                      param_type: str | None = None) -> int | None:
    """+1 where more of the measure helps the patient, -1 where less does, 0 where the
    measure is not efficacy, None where nothing says. In order: not efficacy; a standard
    measure's own sign; a count or share of people with an event, which is lower-is-better
    whatever survival word the title holds; then the title's words."""
    title, unit = title or "", unit or ""
    if _NOT_EFFICACY.search(f"{title} {unit}") or _AE.search(title):
        return 0
    family = family_of({"title": title, "unit": unit, "param_type": param_type},
                       whole_population=False)
    if family:
        return FAMILY_SIGN[family]
    people = _unit_class(unit, param_type) == "share" or param_type == "COUNT_OF_PARTICIPANTS"
    if people and _EVENT_COUNT.search(title):
        return -1
    return _title_direction(title, unit)


def group_directions(groups: list[dict]) -> dict:
    """Each endpoint's direction of benefit: from the measure first, then the way most
    drugs moved it where three or more posted it. None stays None."""
    out = {}
    for g in groups:
        d = benefit_direction(g.get("title"), g.get("unit"), g.get("param_type"))
        if d is None:
            drugs = {r["asset_id"] for r in g["rows"] if r.get("delta") is not None}
            if len(drugs) >= SHARED_MIN:
                d = O.direction(g["rows"])
        out[g["key"]] = d
    return out


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


def is_survival(g: dict) -> bool:
    """A time-to-event measure: a time whose title names overall, progression-free,
    disease-free or event-free survival, or a time to an event ("time to first
    exacerbation", "time from randomization to a bipolar event", "duration of flare-free
    maintenance"). Censored times are read from a posted hazard ratio alone."""
    title = g.get("title") or ""
    return (_unit_class(g.get("unit"), g.get("param_type")) == "time"
            and bool(_SURVIVAL.search(title) or _TIME_TO.search(title)))


def _family_scale(family) -> str:
    if family in TIME_FAMILIES:
        return "log hazard ratio"
    if family in SHARE_FAMILIES:
        return "share"
    return "difference"


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# --- the control, and whose result it is -----------------------------------------------------
def control_key(title, kind, arm=None) -> str | None:
    """What the control arm received, from its title: "placebo alone", the named regimen
    ("docetaxel", "bortezomib + dexamethasone"), or None where the title names no regimen
    two trials could share ("Chemotherapy", "Physician's choice", "Group B"). A placebo
    added to a regimen is left out of the key: what the control arm was given is the
    regimen. A placebo arm whose title says only who was in it or when ("Placebo 13 to
    15 Years Old", "Placebo DBTP", "RSV Season 1"), or what it switched to afterwards
    ("Placebo Followed by Tanezumab", "Placebo - AIN457A"), is placebo alone. "Placebo/X"
    is placebo given with X where the drug's ``arm`` names X too (REVEL's "Placebo/
    Docetaxel"), and placebo switched to X where it does not ("Placebo/Glimepiride"
    against "Ertugliflozin 15 mg"); with no arm given, with X."""
    text = _PAREN.sub(" ", (title or "").lower()).replace("+/-", " ")
    placebo = bool(_PLACEBO_WORD.search(text)) or kind == "placebo"
    if placebo:
        # A label before a colon is the arm's name ("RSV Season 1: Placebo").
        after = text.rsplit(":", 1)[-1]
        if _PLACEBO_WORD.search(after):
            text = after
        text = _PLACEBO_THEN.sub(r"\1", text)
        if arm is not None:
            mine = set(re.split(r"[^a-z0-9]+", (arm or "").lower()))

            def switched(m):
                later = [w for w in re.split(r"[^a-z0-9]+", m.group(2)) if len(w) > 3]
                return m.group(0) if any(w in mine for w in later) else m.group(1)
            text = re.sub(r"\b(placebo|vehicle|sham)\s*/\s*([^/+]*)", switched, text)
    words = [t for t in re.split(r"[^a-z0-9]+", text) if len(t) > 1]
    words = [t for t in words if t not in _KEY_DROP and not any(ch.isdigit() for ch in t)]
    if placebo:
        words = [t for t in words if t not in _KEY_PERIOD]
    if not words:
        return "placebo alone" if placebo else None
    if any(t in _KEY_GENERIC for t in words):
        return None
    return " + ".join(sorted(set(words)))


def comparison_key(title, kind, arm) -> str | None:
    """The cell a result is averaged in: its control's key, kept apart where the drug was
    tested instead of an active regimen rather than added to it. "Pembrolizumab" against
    "Docetaxel" is head to head; "Ramucirumab + Docetaxel" against "Placebo + Docetaxel"
    and "Sitagliptin + Metformin" against "Metformin" are add-ons to the regimen, and the
    two are never averaged together."""
    key = control_key(title, kind, arm)
    if not key or key == "placebo alone" or kind == "placebo":
        return key
    mine = [w for w in re.split(r"[^a-z0-9]+", (arm or "").lower()) if len(w) >= 3]
    # A regimen word, or its start ("Met" in "Sita/Met FDC"), on the drug's own arm.
    if any(r.startswith(w) for r in key.split(" + ") for w in mine):
        return key
    return key + " head to head"


def control_label(key, titles) -> str:
    """The control in words, for a sentence: "placebo"; else the shortest control arm
    title the sponsors posted for it, with any placebo and dose stripped ("Docetaxel" for
    "Placebo + Docetaxel 75 mg/m^2"), so a sentence never prints a name nobody posted."""
    if key == "placebo alone":
        return "placebo"
    clean = []
    for t in titles:
        t = _PAREN.sub(" ", t or "")
        t = re.sub(r"\b(placebo|vehicle|sham|dummy)\b", " ", t, flags=re.I)
        t = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|g|ml|iu|units?)(/\S+)?\b", " ", t, flags=re.I)
        # An arm's label before a spaced hyphen or a colon is not what it was given
        # ("Arm 2 - COPD Standard Therapy").
        t = re.sub(r"^\s*(arm|group|cohort|part|treatment)\s*\w{0,3}\s*(-|–|:)\s+", "", t,
                   flags=re.I)
        t = re.sub(r"\s+[-–]\s+", ", ", t)
        t = re.sub(r"^[\s+/&,:;\-]+|[\s+/&,:;\-]+$", "", re.sub(r"\s+", " ", t))
        # Connectives left dangling once a dose or a placebo is taken out: "Followed by
        # and Pemetrexed", "2 x or", "to PO BID".
        for _ in range(3):
            t = re.sub(r"^(and|plus|with|or|to|in|of|by|followed by|x)\s+|"
                       r"\s+(and|plus|with|or|to|in|of|by|x)$", "", t, flags=re.I).strip()
            t = re.sub(r"\b(followed by|by)\s+and\b", "and", t, flags=re.I)
            t = re.sub(r"^[\s+/&,:;\-]+|[\s+/&,:;\-]+$", "", t)
        if t and re.search(r"[a-z]{3}", t, re.I):
            clean.append(t)
    if not clean:
        return "its control arm"
    return min(clean, key=lambda t: (len(t), t))


def name_tokens(cand: dict) -> frozenset:
    """The long words of a drug's names (seven letters or more): name, generic, brands."""
    names = [cand.get("name"), cand.get("generic"), *(cand.get("brands") or [])]
    out = set()
    for n in names:
        for t in re.split(r"[^a-z]+", str(n or "").lower()):
            if len(t) >= 7:
                out.add(t)
    return frozenset(out)


def names_drug_short(title, tokens) -> bool:
    """A word of four letters or more in a control arm's title that is the start of one of
    the drug's names and not the whole of it: "Pembro + Placebo" names pembrolizumab. The
    whole word is left to the full-name test (the row's ``reference_is_drug``), so "Insulin
    glargine" never names insulin icodec. A word followed by "placebo" or "dummy", or after
    "matching", names the placebo and not the drug ("Nivo Placebo + Chemo")."""
    words = re.findall(r"[a-z]+|[+/&,]", (title or "").lower())
    for i, w in enumerate(words):
        if len(w) < 4 or not w.isalpha():
            continue
        after = words[i + 1] if i + 1 < len(words) else ""
        before = words[i - 1] if i else ""
        if after in ("placebo", "placebos", "dummy", "vehicle") or before == "matching":
            continue
        if any(t.startswith(w) and t != w for t in tokens):
            return True
    return False


# --- one arm against its comparator ---------------------------------------------------------
def estimate_kind(text) -> str | None:
    """What a posted estimate is: a hazard ratio, another ratio, one arm's bare mean, or
    (None) a difference."""
    t = (text or "").strip()
    if _HAZARD.search(t):
        return "hazard"
    if _RATIO.search(t):
        return "ratio"
    if _BARE_MEAN.match(t):
        return "bare mean"
    return None


def category_is_result(cat) -> bool:
    """A category that states the result, not its complement or its baseline."""
    if cat is None:
        return True
    parts = [p.strip() for p in str(cat).split("·")]
    if any(_NEGATION.match(p) for p in parts):
        return False
    low = str(cat).lower()
    if "baseline" in low and not re.search(r"change|from baseline", low):
        return False
    return True


def outcome_is_result(title) -> bool:
    """A baseline is not a result."""
    return not (title or "").strip().lower().startswith("baseline")


def _level(text) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text or "")
    return float(m.group(1)) if m else None


def _analyses(r: dict) -> list:
    """The analysis rows the sponsor posted for this arm against its comparator. A row
    written before the land carried them is read as one analysis from its ``p_value``,
    ``estimate`` and ``ci`` with no level, so its interval is never read."""
    got = r.get("analyses")
    if isinstance(got, list):
        return got
    ci = r.get("ci") or [None, None]
    if r.get("p_value") is None and r.get("estimate") is None and not r.get("ci"):
        return []
    return [{"method": None, "param_type": None, "param_value": r.get("estimate"),
             "ci_pct": None, "ci_lower": ci[0] if len(ci) > 0 else None,
             "ci_upper": ci[1] if len(ci) > 1 else None, "p_value": r.get("p_value")}]


def _is_fraction(unit, value, ref) -> bool:
    """A share posted as a fraction of 1: a "proportion" unit with both arms in 0 to 1."""
    return bool((unit or "").strip().lower().startswith("proportion")
                and value is not None and ref is not None
                and 0 <= value <= 1 and 0 <= ref <= 1)


def row_effect(r: dict, g: dict, sign: int) -> dict | None:
    """One arm's effect against its comparator, signed so that more is better, its
    standard error and the route that gave it (specification 2.3). None where nothing
    posted gives one; ``unsettled`` where a hazard ratio's medians contradict it."""
    unit = g.get("unit") or ""
    n, n0 = r.get("n"), r.get("placebo_n")
    value, ref = r.get("value"), r.get("placebo")
    is_count = (r.get("param") == "COUNT_OF_PARTICIPANTS"
                or (r.get("param") == "NUMBER" and bool(_PEOPLE.match(unit))))
    is_pct = r.get("param") == "NUMBER" and (
        bool(_PCT_OF_PEOPLE.search(unit))
        or (bool(_BARE_PCT.match(unit)) and bool(_SHARE_TITLE.search(g.get("title") or ""))))
    share = is_count or is_pct
    raw = r.get("delta")
    if is_count:
        d = (100.0 * (value / n - ref / n0)
             if n and n0 and value is not None and ref is not None else None)
    else:
        d = raw
    analyses = _analyses(r)
    survival = is_survival(g)
    disp = (r.get("dispersion") or "").lower()
    base = {"n": n, "n0": n0, "bound": False, "survival": survival,
            "sponsor_test": any(M.parse_p(a.get("p_value")) for a in analyses)}

    # 1. A survival measure: the posted hazard ratio with its interval, on the log scale.
    if survival:
        for a in analyses:
            if estimate_kind(a.get("param_type")) != "hazard":
                continue
            if not M.interval_is_sound(a.get("param_value"), a.get("ci_lower"),
                                       a.get("ci_upper"), log=True):
                continue
            se = M.se_from_ci(a.get("ci_lower"), a.get("ci_upper"), a.get("ci_pct"), log=True)
            if se is None:
                continue
            # A hazard below 1 helps where the event is a bad one; where it is a good one
            # (time to relief) a hazard above 1 does.
            eff = -math.log(a["param_value"]) * (1 if sign > 0 else -1)
            excludes_one = a["ci_lower"] > 1.0 or a["ci_upper"] < 1.0
            if d not in (None, 0) and excludes_one and (d * sign > 0) != (eff > 0):
                return {**base, "unsettled": True}
            return {**base, "effect": eff, "se": se, "control_var": None,
                    "route": "hazard ratio interval", "scale": "log hazard ratio"}
        # 2. A hazard ratio posted with a p-value and no usable interval: the ratio gives
        #    the direction, the p-value the standard error.
        for a in analyses:
            hr = a.get("param_value")
            if (estimate_kind(a.get("param_type")) != "hazard" or not hr or hr <= 0
                    or hr == 1.0):
                continue
            got = M.parse_p(a.get("p_value"))
            if not got or got[1] == "above":
                continue
            eff = -math.log(hr) * (1 if sign > 0 else -1)
            back = M.se_from_p(eff, got[0], got[1],
                               bool(_ONE_SIDED.search(a.get("method") or "")))
            if not back:
                continue
            if d not in (None, 0) and got[0] < 0.05 and (d * sign > 0) != (eff > 0):
                return {**base, "unsettled": True}
            return {**base, "effect": eff, "se": back[0], "control_var": None,
                    "route": "hazard ratio p-value", "bound": back[1],
                    "scale": "log hazard ratio"}
        # A time to an event is read from a posted hazard ratio and from nothing else.
        # Medians and means of censored times mislead when curves cross (IPASS: medians
        # 5.7 and 5.8 months, hazard ratio 0.74), and a log-rank p-value carries no
        # direction.
        return None

    # 3. The sponsor's own difference with its interval, where it reproduces the arms'.
    if d is not None:
        best = None
        for a in analyses:
            if estimate_kind(a.get("param_type")) is not None or a.get("param_value") is None:
                continue
            if not M.interval_is_sound(a["param_value"], a.get("ci_lower"), a.get("ci_upper")):
                continue
            se = M.se_from_ci(a.get("ci_lower"), a.get("ci_upper"), a.get("ci_pct"))
            if se is None:
                continue
            e = a["param_value"]
            tol = max(AGREE * abs(d), se)
            gap, eff = min((abs(e - d), e), (abs(e + d), -e))
            if gap <= tol and (best is None or gap < best[0]):
                best = (gap, eff, se)
        if best:
            # A proportion posted as a fraction goes on the share scale as percentage
            # points, as the counts route puts it.
            k = (100.0 if share and not is_count and _is_fraction(unit, value, ref) else 1.0)
            return {**base, "effect": k * best[1] * sign, "se": k * best[2], "control_var": None,
                    "route": "interval", "scale": "share" if share else "difference"}

    # 4. The arms' posted spread around a mean. A least-squares mean with a "standard
    #    deviation" is not read: it is a model estimate, and the figure beside it is as
    #    often its standard error as a spread between patients.
    if r.get("param") in ("MEAN", "LEAST_SQUARES_MEAN") and d is not None:
        got = None
        if disp == "standard deviation" and r.get("param") == "MEAN":
            got = M.se_from_spread(r.get("spread"), n, r.get("reference_spread"), n0, "sd")
        elif disp == "standard error":
            got = M.se_from_spread(r.get("spread"), n, r.get("reference_spread"), n0, "se")
        elif "confidence interval" in disp:
            got = M.se_from_arm_ci(r.get("lower"), r.get("upper"), r.get("reference_lower"),
                                   r.get("reference_upper"), _level(disp))
        if got:
            return {**base, "effect": d * sign, "se": got[0], "control_var": got[1],
                    "route": "arm spread", "scale": "difference"}

    # 5. Two shares from their counts. A rate per patient-year is not a share.
    if share and value is not None and ref is not None and n and n0:
        if is_count:
            x, x0 = value, ref
        else:
            full = 1.0 if _is_fraction(unit, value, ref) else 100.0
            x, x0 = ((value / full * n, ref / full * n0)
                     if 0 <= value <= full and 0 <= ref <= full else (None, None))
        got = M.two_proportions(x, n, x0, n0) if x is not None else None
        if got:
            return {**base, "effect": 100.0 * got[0] * sign, "se": 100.0 * got[1],
                    "control_var": 1e4 * got[2], "route": "counts", "scale": "share"}

    # 6. Another ratio with its interval, off a survival measure: a test statistic only,
    #    its sign from the arms, never averaged for size.
    if raw not in (None, 0) and not survival:
        for a in analyses:
            if estimate_kind(a.get("param_type")) not in ("ratio", "hazard"):
                continue
            if not M.interval_is_sound(a.get("param_value"), a.get("ci_lower"),
                                       a.get("ci_upper"), log=True):
                continue
            se = M.se_from_ci(a.get("ci_lower"), a.get("ci_upper"), a.get("ci_pct"), log=True)
            if se is None:
                continue
            size = abs(math.log(a["param_value"]))
            return {**base, "effect": size if raw * sign > 0 else -size, "se": se,
                    "control_var": None, "route": "ratio interval", "scale": "log ratio"}

    # 7. The sponsor's p-value with the difference. A bound above gives no test statistic.
    if raw not in (None, 0):
        for a in analyses:
            got = M.parse_p(a.get("p_value"))
            if not got:
                continue
            p, kind = got
            one = bool(_ONE_SIDED.search(a.get("method") or ""))
            back = M.se_from_p(raw, p, kind, one)
            if back:
                return {**base, "effect": raw * sign, "se": back[0], "control_var": None,
                        "route": "p-value bound" if back[1] else "p-value",
                        "bound": back[1], "scale": "other"}
            if kind == "above":
                return {**base, "effect": None, "se": None, "control_var": None,
                        "route": "p-value above", "scale": None}
    return None


# --- one result per drug, trial and outcome ------------------------------------------------
def _categories(rs: list[dict]) -> dict:
    """The rows of one outcome by category, in the order the sponsor posted them."""
    cats: dict = {}
    order: dict = {}
    for r in rs:
        idx = r.get("category_index")
        if idx is None:
            idx = order.setdefault(r.get("category"), len(order))
        cats.setdefault(idx, []).append(r)
    return cats


def build_result(rs: list[dict], g: dict, sign: int, tokens=frozenset()):
    """(result, None), or (None, the reason it is not scored), for one drug's rows of one
    outcome of one trial (specification 2.1)."""
    cats = _categories(rs)
    chosen = None
    for idx in sorted(cats):
        if category_is_result(cats[idx][0].get("category")):
            chosen = cats[idx]
            break
    if chosen is None:
        return None, "nothing to test"
    if any(r.get("reference_is_drug") or names_drug_short(r.get("reference_arm"), tokens)
           for r in chosen):
        return None, "in both arms"
    named = [r for r in chosen if r.get("arm_names_drug", r.get("arm_is_drug"))
             and not r.get("arm_is_control") and not _CROSSOVER.search(r.get("arm") or "")]
    if not named:
        return None, "not its arm"
    named = [r for r in named if _analyses(r)] or named
    if len(named) >= 3:
        def is_total(r):
            others = [x.get("n") for x in named if x is not r]
            return (bool(_TOTAL_ARM.match(r.get("arm") or ""))
                    or bool(r.get("n") and all(others) and r["n"] == sum(others)))
        named = [r for r in named if not is_total(r)] or named
    effs = [(r, row_effect(r, g, sign)) for r in named]
    unsettled = any(e and e.get("unsettled") for _, e in effs)
    effs = [(r, e) for r, e in effs if e and not e.get("unsettled")]
    if not effs:
        if unsettled:
            return None, "orientation"
        return None, ("no hazard ratio" if is_survival(g) else "nothing to test")
    r0 = effs[0][0]
    h2h = {r.get("head_to_head") for r, _ in effs}
    ni = bool(_NON_INFERIOR.search(g.get("title") or "")) or any(
        _NON_INFERIOR.search(a.get("method") or "") for r, _ in effs for a in _analyses(r))
    base = {"phase": r0.get("phase"), "reference_kind": r0.get("reference_kind"),
            "non_inferiority": ni,
            "control_title": r0.get("reference_arm"),
            "control_key": comparison_key(r0.get("reference_arm"), r0.get("reference_kind"),
                                          r0.get("arm") or ""),
            "weeks": r0.get("weeks"),
            "withdrawal": bool(_WITHDRAWAL.search(r0.get("time_frame") or "")),
            "head_to_head": next(iter(h2h)) if len(h2h) == 1 else None,
            "sponsor_test": any(e["sponsor_test"] for _, e in effs),
            "survival": effs[0][1]["survival"]}
    withse = [(r, e) for r, e in effs if e.get("se")]
    if not withse:
        # Only a p-value posted as "above": no test statistic is made up for it. It is
        # counted as a result not won and left out of strength.
        return {**base, "z": None, "effect": None, "se": None, "scale": None,
                "route": "p-value above", "bound": True, "arms": len(effs),
                "allowance": 0.0, "n": None}, None
    scale = max({e["scale"] for _, e in withse},
                key=lambda s: (sum(1 for _, e in withse if e["scale"] == s),
                               -_SCALES.index(s)))
    use = [(r, e) for r, e in withse if e["scale"] == scale]
    ns = [e["n"] for _, e in use]
    args = ([e["effect"] for _, e in use], [e["se"] for _, e in use],
            ns if all(ns) else None, use[0][1]["n0"], [e["control_var"] for _, e in use])
    test = M.combine_arms(*args)
    top = M.top_arm(*args)
    if test is None or top is None or not test[1] > 0:
        return None, "nothing to test"
    return {**base, "z": test[0] / test[1], "test_effect": test[0], "test_se": test[1],
            "effect": top["effect"], "se": top["se"], "allowance": top["allowance"],
            "arms": len(use), "scale": scale,
            "route": " + ".join(sorted({e["route"] for _, e in use})),
            "bound": any(e["bound"] for _, e in use),
            "n": (sum(ns) if all(ns) else None)}, None


def results(land: dict, skipped: list | None = None) -> tuple[list[dict], dict]:
    """Every scored result, and per drug the posted endpoints left unscored, by reason.
    Where ``skipped`` is a list, each unscored endpoint is appended to it as {asset_id,
    nct_id, outcome_index, why}."""
    groups = land.get("endpoints") or []
    directions = group_directions(groups)
    tokens = {c["asset_id"]: name_tokens(c) for c in land.get("candidates") or []}
    out, unscored = [], defaultdict(Counter)
    for g in groups:
        sign = directions.get(g["key"])
        if sign == 0 or not outcome_is_result(g.get("title")):
            continue
        by, bare = defaultdict(list), defaultdict(list)
        for r in g["rows"]:
            key = (r["asset_id"], r["nct_id"], r.get("outcome_index"))
            (by if r.get("reference_kind") else bare)[key].append(r)
        # A result posted with no arm the book can read as its control (a single-arm
        # trial, or arms whose titles do not say which is the drug's) is counted, not
        # dropped, so a drug is never said to have no comparator when it had one.
        for (aid, nct, index), rs in bare.items():
            if (aid, nct, index) in by or not any(r.get("value") is not None for r in rs):
                continue
            unscored[aid]["no control"] += 1
            if skipped is not None:
                skipped.append({"asset_id": aid, "nct_id": nct, "outcome_index": index,
                                "why": "no control"})
        if sign is None:
            for (aid, nct, index), rs in by.items():
                if any(r.get("delta") is not None for r in rs):
                    unscored[aid]["direction"] += 1
                    if skipped is not None:
                        skipped.append({"asset_id": aid, "nct_id": nct, "outcome_index": index,
                                        "why": "direction"})
            continue
        family = family_of(g)
        measure = clean_measure(g.get("title"))
        for (aid, nct, index), rs in by.items():
            res, why = build_result(rs, g, sign, tokens.get(aid, frozenset()))
            if res is None:
                if any(r.get("delta") is not None for r in rs):
                    unscored[aid][why] += 1
                    if skipped is not None:
                        skipped.append({"asset_id": aid, "nct_id": nct, "outcome_index": index,
                                        "why": why})
                continue
            res.update({"asset_id": aid, "nct_id": nct, "outcome_index": index,
                        "key": g["key"], "family": family, "measure": measure,
                        "unit": g.get("unit"), "title": g.get("title")})
            out.append(res)
    return out, unscored


_DANGLING = re.compile(r"[\s,;:]+(at|of|by|to|from|in|on|through|over|up to|for|and|or|"
                       r"with|the)$", re.I)
_CLAUSE = re.compile(r":|;|\s+consisting of\b|\s+defined as\b|\s+including\b", re.I)
MEASURE_MAX = 100


def clean_measure(title) -> str:
    """The measure as a sentence names it: the time point and baseline out, the analysis
    set off, no spaced hyphen standing in for a comma, no word left dangling where a
    time point was cut ("rate at"), and a long composite cut to its first clause."""
    t = _ANALYSIS_SET.sub("", title or "")
    t = O._endpoint_title(t).rstrip(" .;:,")
    t = re.sub(r"\s+[-–]\s+", ", ", t)
    for _ in range(3):
        t = _DANGLING.sub("", t).rstrip(" .;:,")
    if len(t) > MEASURE_MAX:
        m = _CLAUSE.search(t, 20)
        if m and m.start() <= MEASURE_MAX:
            t = t[:m.start()]
        else:
            cut = t.rfind(",", 20, MEASURE_MAX)
            t = t[:cut] if cut > 0 else t[:t.rfind(" ", 20, MEASURE_MAX)]
        for _ in range(3):
            t = _DANGLING.sub("", t).rstrip(" .;:,")
    return t or "the measure"


def lengths_comparable(a: dict, b: dict) -> bool:
    """Two averaged effects are compared only over trials of similar length: their ranges
    of weeks overlap, or lie within LENGTH_TOL of each other. A hazard ratio summarises the
    whole curve and carries no length. Where a length was not posted for one of them the
    condition cannot be tested and is not applied."""
    if a["scale"] == "log hazard ratio":
        return True
    if a["weeks"] is None or b["weeks"] is None:
        return True
    (alo, ahi), (blo, bhi) = a["weeks"], b["weeks"]
    return ahi >= blo * (1.0 - LENGTH_TOL) and bhi >= alo * (1.0 - LENGTH_TOL)


# --- safety strata ---------------------------------------------------------------------------
def _periods(title) -> frozenset:
    """The periods an arm's title states, each as one token: "Weeks 1-12" is week1-12,
    "Period 1+2" is period1+2 and not period1."""
    out = set()
    for m in _PERIOD.finditer(title or ""):
        if m.group(3):
            out.add("double-blind")
            continue
        word = m.group(1).lower().replace("-", "").replace("studies", "study")
        word = word.rstrip("s").replace("wk", "week")
        out.add(word + re.sub(r"\s+", "", m.group(2).lower()))
    return frozenset(out)


def stratum_counts(stratum: dict) -> dict | None:
    """One trial's safety counts, drug against control, over the same period
    (specification 2.10).

    The drug's side is never an arm that is itself a placebo or a named control, nor one
    whose title marks a switch, a crossover, an extension, an open-label or a rescue
    period; and where the control arm's title states a period or a cohort ("Weeks 1-12",
    "Period 1", "Part A", "Cohort 1", "Sub-study A", "double-blind") only arms that state
    the same one. No stratum where the control arm itself names the drug, or where no arm
    is left."""
    if stratum.get("control") is None or stratum.get("control_is_drug"):
        return None
    arms = [a for a in stratum.get("arm_rows") or []
            if not a.get("is_control") and not _SWITCH.search(a.get("title") or "")]
    want = _periods(stratum.get("control_title"))
    if want:
        same = [a for a in arms if _periods(a.get("title")) == want]
        arms = same or [a for a in arms if not _periods(a.get("title"))]
    if not arms:
        return None
    out = {"nct_id": stratum["nct_id"], "arms": len(arms),
           "kind": "placebo" if stratum.get("kind") == "placebo" else "active"}
    for part in ("withdrawn", "serious", "deaths"):
        x1 = sum(a[part][0] for a in arms if a[part][1])
        n1 = sum(a[part][1] for a in arms)
        x0, n0 = stratum["control"][part]
        out[part] = (x1, n1, x0, n0) if n1 and n0 else None
    return out


# --- the scorecard -----------------------------------------------------------------------------
# ---- the regimen columns: how the drug was given in the trials that scored it -------------
# Read from the drug's own arm titles and descriptions as posted, never scored. A column the
# arms do not state stays null, so the table prints the null dash rather than a guess.
_DOSE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(mg/kg|mg/m2|mg/m\^2|mg|mcg|µg|ug|g|iu|units?)\b",
                   re.I)
_FREQUENCIES = (
    ("twice daily", re.compile(r"\btwice (a |per )?day\b|\btwice daily\b|\bbid\b|\bb\.i\.d\b", re.I)),
    ("three times daily", re.compile(r"\bthree times (a |per )?day\b|\btid\b", re.I)),
    ("daily", re.compile(r"\bonce (a |per )?day\b|\bonce daily\b|\bdaily\b|\bqd\b|\bq\.d\b|\bod\b", re.I)),
    ("weekly", re.compile(r"\bonce (a |per )?week(ly)?\b|\bweekly\b|\bqw\b|\bq1w\b|\bevery week\b", re.I)),
    ("every 2 wk", re.compile(r"\bq2w\b|\bevery (2|two) weeks\b|\bbiweekly\b|\bevery other week\b", re.I)),
    ("every 3 wk", re.compile(r"\bq3w\b|\bevery (3|three) weeks\b", re.I)),
    ("every 4 wk", re.compile(r"\bq4w\b|\bevery (4|four) weeks\b", re.I)),
    ("monthly", re.compile(r"\bmonthly\b|\bonce (a |per )?month\b|\bevery month\b", re.I)),
    ("every 8 wk", re.compile(r"\bq8w\b|\bevery (8|eight) weeks\b", re.I)),
)
_ROUTES = {"ORAL": "oral", "SUBCUTANEOUS": "SC", "INTRAVENOUS": "IV",
           "INTRAMUSCULAR": "IM", "RESPIRATORY (INHALATION)": "inhaled",
           "INHALATION": "inhaled", "TOPICAL": "topical", "OPHTHALMIC": "eye",
           "INTRAVITREAL": "eye injection", "NASAL": "nasal", "TRANSDERMAL": "skin patch"}
_ROUTE_WORDS = (("oral", re.compile(r"\btablets?\b|\bcapsules?\b|\boral(ly)?\b|\bp\.?o\.?\b", re.I)),
                ("SC", re.compile(r"\bsubcutaneous(ly)?\b|\bs\.?c\.?\b|\bpen\b", re.I)),
                ("IV", re.compile(r"\bintravenous(ly)?\b|\bi\.?v\.?\b|\binfusion\b", re.I)),
                ("inhaled", re.compile(r"\binhal(ed|ation|er)\b", re.I)))


def _fmt_dose(value: float) -> str:
    return f"{value:g}"


def _near_names(text: str, names: list[str], width: int = 70) -> str:
    """The stretch of a description that follows a mention of the drug, where its own dose
    and schedule are written; a description also names the comparator's."""
    low = (text or "").lower()
    out = []
    for n in names:
        n = (n or "").lower().strip()
        if len(n) < 3:
            continue
        start = 0
        while True:
            i = low.find(n, start)
            if i < 0:
                break
            out.append(text[i:i + len(n) + width])
            start = i + len(n)
    return " ".join(out)


def _doses_in(texts) -> dict:
    doses: dict = {}
    for t in texts:
        for value, unit in _DOSE.findall(t or ""):
            u = unit.lower().replace("µg", "mcg").replace("ug", "mcg").replace("mg/m^2", "mg/m2")
            u = "units" if u in ("unit", "iu") else u
            doses.setdefault(u, set()).add(float(value))
    return doses


def _schedule_in(texts) -> Counter:
    seen = Counter()
    for t in texts:
        for label, pattern in _FREQUENCIES:
            if pattern.search(t or ""):
                seen[label] += 1
                break
    return seen


def regimen(rows: list[dict], cand: dict, weeks=None, participants=None) -> dict:
    """How the drug was given in its posted trials: the doses its own arms name, the
    form, the dosing frequency and the trial length, each from the posted text or null
    with the reason. ``rows`` are the drug's endpoint rows; ``weeks`` is the span of the
    trials its lead measure averages, used ahead of the rows' own time points."""
    own = [r for r in rows if r.get("arm_names_drug") or r.get("arm_is_drug")]
    names = [cand.get("name"), cand.get("generic")] + list(cand.get("brands") or [])
    titles = list(dict.fromkeys(r.get("arm") or "" for r in own))
    near = list(dict.fromkeys(_near_names(r.get("arm_description") or "", names) for r in own))
    # Dose: what the arm titles name, else what the descriptions write next to the drug's
    # name, in the unit most of them use.
    doses = _doses_in(titles) or _doses_in(near)
    dose = None
    if doses:
        unit = max(doses, key=lambda u: len(doses[u]))
        vals = sorted(doses[unit])
        dose = (f"{_fmt_dose(vals[0])} {unit}" if len(vals) == 1
                else f"{_fmt_dose(vals[0])}\u2013{_fmt_dose(vals[-1])} {unit}")
    # Frequency: the schedule the titles name most often, else the descriptions'.
    seen = _schedule_in(titles) or _schedule_in(near)
    frequency = seen.most_common(1)[0][0] if seen else None
    # Form: what the arm titles say, else the words right after the drug's name in the
    # descriptions, else the label's routes (a compound's label can carry a form its trials
    # here never used, so it comes last).
    def _words(texts):
        c = Counter(label for t in texts for label, pat in _ROUTE_WORDS if pat.search(t))
        return [w for w, _ in c.most_common(2)]
    labelled = [_ROUTES.get(str(x).upper(), str(x).lower()) for x in (cand.get("route") or [])]
    close = [_near_names(r.get("arm_description") or "", names, width=40) for r in own]
    labelled = list(dict.fromkeys(r for r in labelled if r))
    by_title, by_text = _words(titles), _words(close)[:1]
    if by_title:
        # A title names a form only where it is not the usual one ("oral semaglutide"), so
        # the label's forms stand beside it.
        routes, form_source = list(dict.fromkeys(by_title + labelled))[:2], "arm titles and label"
    elif by_text:
        routes, form_source = by_text, "arm descriptions"
    else:
        routes, form_source = labelled[:2], "label"
    form = " or ".join(routes) if routes else None
    duration_span = None
    # Trial length: the lead measure's span, else the primary endpoints' time points (four
    # weeks to ten years: a baseline or a decade of follow-up is not a trial's length).
    span = sorted(w for w in (weeks or []) if w)
    if not span:
        span = sorted({round(r["weeks"]) for r in own
                       if r.get("weeks") and 4 <= r["weeks"] <= 520
                       and (r.get("outcome_type") or "").upper() == "PRIMARY"})
    duration = None
    if span:
        lo, hi = span[0], span[-1]
        duration_span = f"{lo:.0f} to {hi:.0f} weeks"
        if round(lo) == round(hi):
            duration = f"{lo:.0f} wk"
        elif hi <= 3 * lo:
            duration = f"{lo:.0f}\u2013{hi:.0f} wk"
        else:
            # A wide spread reads as its middle; the full span is on hover.
            duration = f"~{statistics.median(span):.0f} wk"
    return {
        "participants": participants, "dose": dose, "form": form, "frequency": frequency,
        "duration": duration, "duration_span": duration_span,
        "form_source": form_source if form else None,
        "why": {"dose": None if dose else "no dose named for the drug in its arms",
                "form": None if form else "no route in the arms or on the label",
                "frequency": None if frequency else "no schedule named for the drug in its arms",
                "duration": None if duration else "no primary time point posted"},
    }


def scorecard(land: dict, draws: int = DRAWS, seed: int = SEED) -> dict:
    """One record per candidate: its efficacy, safety and evidence scores with what each
    rests on, its overall rank and the range of it, or the reason it has none."""
    return _build(land, draws, seed)["out"]


def _build(land: dict, draws: int = DRAWS, seed: int = SEED) -> dict:
    """The scorecard and the working behind it (the results, the averaged cells and the
    trial effects under them), which the book guard reads."""
    cands = {c["asset_id"]: c for c in land.get("candidates") or []}
    safe = {s["asset_id"]: s for s in land.get("safety") or []}
    skipped: list = []
    res, unscored = results(land, skipped)
    by_asset = defaultdict(list)
    for c in res:
        by_asset[c["asset_id"]].append(c)

    # ---- the averaged effect per drug, measure and control ---------------------------------
    tally = defaultdict(Counter)
    for c in res:
        if not c["family"] and c.get("scale") in ("difference", "share"):
            tally[c["key"]][c["scale"]] += 1
    own_scale = {k: max(sorted(v), key=lambda s: v[s]) for k, v in tally.items()}
    raw_cells = defaultdict(lambda: defaultdict(list))   # (measure, control) -> drug -> results
    for c in res:
        if c.get("se") is None or c["withdrawal"]:
            continue
        want = _family_scale(c["family"]) if c["family"] else own_scale.get(c["key"])
        if c["scale"] != want:
            continue
        mkey = c["family"] or ("own", c["key"], c["measure"])
        ckey = c["control_key"] or ("own control", c["nct_id"])
        raw_cells[(mkey, ckey)][c["asset_id"]].append(c)

    trial_level = {}                  # (cell, drug) -> per-trial effects
    by_measure = defaultdict(list)
    for cell, by in raw_cells.items():
        for aid, cs in by.items():
            per = defaultdict(list)
            for c in cs:
                per[c["nct_id"]].append(c)
            ncts = sorted(per)
            pairs = [M.combine_repeats([c["effect"] for c in per[t]],
                                       [c["se"] for c in per[t]]) for t in ncts]
            weeks = [max((c["weeks"] for c in per[t] if c["weeks"]), default=None) for t in ncts]
            people = [max((c.get("n") or 0) for c in per[t]) for t in ncts]
            trial_level[(cell, aid)] = {
                "ncts": ncts, "y": [p[0] for p in pairs], "s": [p[1] for p in pairs],
                "weeks": weeks, "cs": cs, "n": sum(people), "n_known": all(people)}
            by_measure[cell[0]].append((trial_level[(cell, aid)]["y"],
                                        trial_level[(cell, aid)]["s"]))
    tau = {m: M.common_tau2(cells) for m, cells in by_measure.items()}

    pooled = defaultdict(dict)        # cell -> drug -> entry
    for (cell, aid), t in trial_level.items():
        mkey, ckey = cell
        fit = tau[mkey]
        p = M.pool_common(t["y"], t["s"], fit["tau2"] if fit else None, LEVEL)
        own = M.pool_common(t["y"], t["s"], 0.0, LEVEL)
        have = [w for w in t["weeks"] if w]
        c0 = t["cs"][0]
        h2h = {c["head_to_head"] for c in t["cs"]}
        p.update({
            "own_lo": own["lo"], "own_hi": own["hi"],
            "measure": mkey if isinstance(mkey, str) else mkey[2], "mkey": mkey, "ckey": ckey,
            "named_control": isinstance(ckey, str), "control": None,
            "control_title": c0["control_title"], "scale": c0["scale"], "unit": c0["unit"],
            # People on the drug's arms, each trial once; null where a trial posted no n,
            # so a partial count is never printed as the whole. The partial count still
            # orders a drug's cells ("then most people").
            "trials": t["ncts"], "people_known": t["n"],
            "participants": (t["n"] or None) if t["n_known"] else None,
            "weeks": (min(have), max(have)) if len(have) == len(t["weeks"]) and have else None,
            "tau2": fit["tau2"] if fit else None, "tau2_df": fit["df"] if fit else None,
            "routes": sorted({c["route"] for c in t["cs"]}),
            "top_dose": sum(1 for c in t["cs"] if c["arms"] > 1),
            "head_to_head": h2h.pop() if len(h2h) == 1 else None,
            "shrunk": p["effect"], "shrunk_se": p["se"], "weight": 0.0, "prior": None,
            "asset_id": aid, "peers": [], "ranked": False})
        pooled[cell][aid] = p

    for cell, by in pooled.items():
        titles = [c["control_title"] for aid in by for c in trial_level[(cell, aid)]["cs"]]
        label = control_label(cell[1] if isinstance(cell[1], str) else None, titles)
        have = [e["weeks"] for e in by.values() if e["weeks"]]
        for e in by.values():
            e["control"] = label
            e["cell_weeks"] = ((min(w[0] for w in have), max(w[1] for w in have))
                               if len(have) == len(by) else None)

    # ---- shrinkage toward the mechanism class, then size against peers ---------------------
    for cell, by in pooled.items():
        if not isinstance(cell[1], str):
            continue
        klass = defaultdict(list)
        for aid in sorted(by):
            label = O.mechanism_label(cands.get(aid) or {})
            if label:
                klass[label].append(aid)
        for label, members in klass.items():
            if len(members) < CLASS_MIN:
                continue
            f = M.shrink([by[a]["effect"] for a in members], [by[a]["se"] for a in members])
            if f is None:
                continue
            for i, a in enumerate(members):
                by[a].update({"shrunk": f["shrunk"][i], "shrunk_se": f["se"][i],
                              "weight": f["weight"][i],
                              "prior": {"label": label, "n": len(members), "mean": f["mean"],
                                        "mean_se": f["mean_se"], "members": members,
                                        "mean_weight": f["mean_weight"]}})

    def pair_var(a: dict, b: dict) -> float:
        """The variance of the difference of two shrunk effects. Two drugs shrunk toward one
        class mean share it, so only the part they weigh differently is uncertain between
        them (specification 2.9). Any other pair adds the two variances."""
        if a["prior"] and b["prior"] and a["prior"]["members"] is b["prior"]["members"]:
            pr = a["prior"]
            j = pr["n"]
            wa, wb = a["weight"], b["weight"]
            return ((1 - wa) * a["se"] ** 2 + (1 - wb) * b["se"] ** 2
                    + (wa - wb) ** 2 * pr["mean_se"] ** 2
                    + (2.0 / (j - 3.0)) * ((wa * (a["effect"] - pr["mean"])) ** 2
                                           + (wb * (b["effect"] - pr["mean"])) ** 2))
        return a["shrunk_se"] ** 2 + b["shrunk_se"] ** 2

    ranked_any = False
    for cell, by in pooled.items():
        named = isinstance(cell[1], str)
        for aid, e in by.items():
            everyone = [o for o in sorted(by) if o != aid] if named else []
            # A drug is compared only with the peers whose trials ran about as long as its
            # own: weight loss at 12 weeks is not weight loss at 72.
            peers = [o for o in everyone if lengths_comparable(e, by[o])]
            e["peers"], e["peers_all"] = peers, everyone
            have = [by[o]["weeks"] for o in [aid, *peers]]
            e["rank_weeks"] = ((min(w[0] for w in have), max(w[1] for w in have))
                               if all(have) else None)
            e["ranked"] = (len(peers) >= SHARED_MIN - 1 and bool(e["tau2_known"])
                           and (e["tau2_df"] or 0) >= TAU_DF_MIN)
            if not e["ranked"]:
                continue
            ranked_any = True
            prob = {o: M.p_above(e["shrunk"] - by[o]["shrunk"], pair_var(e, by[o]))
                    for o in peers}
            e["pair_sd"] = {o: math.sqrt(pair_var(e, by[o])) for o in peers}
            e["score"] = 100.0 * statistics.fmean(prob.values())
            e["rank"] = 1 + sum(1 for o in peers if by[o]["shrunk"] > e["shrunk"] + 1e-12)
            e["of"] = len(peers) + 1
            e["tied_with"] = sorted(o for o in peers if TIE[0] <= prob[o] <= TIE[1])
            ahead = [o for o in peers if by[o]["shrunk"] > e["shrunk"] + 1e-12]
            versus = (max(ahead, key=lambda o: by[o]["shrunk"]) if ahead
                      else max(peers, key=lambda o: by[o]["shrunk"]))
            sd = e["pair_sd"][versus]
            diff = e["shrunk"] - by[versus]["shrunk"]
            e["versus"] = {"asset_id": versus, "name": (cands.get(versus) or {}).get("name"),
                           "diff": diff, "lo": diff - M.Z95 * sd, "hi": diff + M.Z95 * sd,
                           "p_better": prob[versus],
                           "same_length": lengths_comparable(e, by[versus]),
                           "weeks": by[versus]["weeks"], "direct": None}
    for cell, by in pooled.items():
        for e in by.values():
            if e["ranked"]:
                e["versus"]["direct"] = _direct(e, pooled)

    # ---- safety, averaged trial by trial within one kind of control ------------------------
    strata = {aid: [x for x in (stratum_counts(st) for st in s.get("strata") or []
                                if not names_drug_short(st.get("control_title"),
                                                        name_tokens(cands.get(aid) or {})))
                    if x]
              for aid, s in safe.items()}
    # An outcomes trial's serious adverse events are largely the heart attacks, strokes or
    # kidney events it counts as its result, so benefit would leak into safety: its serious
    # events are set aside from the scored figure, as deaths are everywhere.
    outcomes_trials = outcome_trials(land)
    all_fits = defaultdict(lambda: defaultdict(dict))   # drug -> part -> kind -> fit
    set_aside = defaultdict(list)                       # drug -> outcomes trials set aside
    for aid, rows in strata.items():
        for part in ("withdrawn", "serious", "deaths"):
            for k in ("placebo", "active"):
                rs = [r for r in rows if r["kind"] == k and r[part]]
                if part == "serious":
                    out_ = [r["nct_id"] for r in rs if r["nct_id"] in outcomes_trials]
                    set_aside[aid] += [t for t in out_ if t not in set_aside[aid]]
                    rs = [r for r in rs if r["nct_id"] not in outcomes_trials]
                fit = M.mantel_haenszel_rd([r[part] for r in rs], LEVEL)
                if not fit:
                    continue
                # Only the strata the average could read: a count above its people is left
                # out, and every list here follows the strata kept.
                kept = [rs[i] for i in fit["kept"]]
                fit.update({"kind": k, "trials": [r["nct_id"] for r in kept],
                            "summed_arms": any(r["arms"] > 1 for r in kept),
                            "top_trial": max(kept, key=lambda r: r[part][1] * r[part][3]
                                             / (r[part][1] + r[part][3]))["nct_id"],
                            "dispersion": None, "se_own": fit["se"]})
                all_fits[aid][part][k] = fit
    # One dispersion factor per part and kind of control, across every drug with two or
    # more strata of that kind, whichever kind is scored for it; every fit of that kind is
    # widened by it, the reported other-kind fits included.
    for part in ("withdrawn", "serious", "deaths"):
        for kind in ("placebo", "active"):
            group = [all_fits[a][part][kind] for a in sorted(all_fits)
                     if kind in all_fits[a][part]]
            phi = M.dispersion(group)
            for f in group:
                f["dispersion"] = phi
                f["se"] = f["se_own"] * math.sqrt(phi) if phi else f["se_own"]
                f["lo"], f["hi"] = f["rd"] - M.Z95 * f["se"], f["rd"] + M.Z95 * f["se"]
    fits = defaultdict(dict)          # drug -> part -> fit of the kind scored
    other = defaultdict(dict)         # drug -> part -> fit of the other kind, reported
    for aid, parts in all_fits.items():
        for part, byk in parts.items():
            if not byk:
                continue
            people = {k: f["n_drug"] for k, f in byk.items()}
            kind = ("placebo" if people.get("placebo", 0) >= people.get("active", 0)
                    else "active")
            fits[aid][part] = byk[kind]
            for k, f in byk.items():
                if k != kind:
                    other[aid][part] = f

    # ---- one record per candidate ----------------------------------------------------------
    strength = strengths(by_asset)
    efficacy = {aid: _efficacy(aid, by_asset.get(aid, []), unscored.get(aid, Counter()),
                               pooled, ranked_any, strength) for aid in cands}
    assets = []
    # Each drug's endpoint rows, for the regimen columns.
    asset_rows = defaultdict(list)
    for g in land.get("endpoints") or []:
        for r in g.get("rows") or []:
            asset_rows[r["asset_id"]].append(r)
    for aid, c in cands.items():
        s_ = safe.get(aid) or {}
        rec = {"asset_id": aid, "name": c.get("name"), "ticker": c.get("ticker"),
               "stage": c.get("stage"), "is_marketed": bool(c.get("is_marketed")),
               "mechanism": O.mechanism_label(c), "boxed": bool(c.get("boxed_warning")),
               "pos": (c.get("model") or {}).get("pos"),
               "per_share": (c.get("model") or {}).get("per_share"),
               "trials_with_results": c.get("with_results") or 0}
        rec["efficacy"] = efficacy[aid]
        rec["safety"] = _safety(c, s_, fits.get(aid, {}), other.get(aid, {}),
                                set_aside.get(aid, []))
        phase_rank = max((_PHASE_RANK.get(x.get("phase"), 0) for x in by_asset.get(aid, [])),
                         default=0)
        ev = evidence_score(s_.get("participants"), phase_rank)
        eff, saf = rec["efficacy"]["score"], rec["safety"]["score"]
        rec["evidence"] = {
            "score": ev, "participants": s_.get("participants"),
            "phase": next((p for p, r in _PHASE_RANK.items()
                           if r == phase_rank and p != "Phase 4"), None),
            "confidence": (_confidence(s_.get("participants"), phase_rank)
                           if (eff is not None or saf is not None) else None)}
        rec["placed"] = eff is not None and saf is not None
        rec["overall"] = (statistics.fmean([eff, saf, ev if ev is not None else 0.0])
                          if rec["placed"] else None)
        rec["rank_range"] = None
        rec["rank_line"] = None
        if rec["placed"]:
            rec["why_not"] = None
        elif not rec["trials_with_results"] and eff is None and saf is None:
            rec["why_not"] = "no posted results"
        elif eff is None:
            why = rec["efficacy"]["unscored_why"]
            top = max(sorted(why), key=lambda k: why[k]) if why else None
            rec["why_not"] = (
                "only results from trials built to show it no worse than a comparator"
                if rec["efficacy"]["non_inferiority"] and not rec["efficacy"]["endpoints"] else
                "results posted, none against a control arm the book can identify"
                if top == "no control" else
                "no result on an arm that is the drug's alone"
                if top in ("not its arm", "in both arms") else
                "time-to-event results with no hazard ratio posted" if top == "no hazard ratio" else
                "no endpoint whose direction of benefit is clear" if top == "direction" else
                "no efficacy endpoint that can be tested against a comparator")
        else:
            rec["why_not"] = "no controlled trial with safety counts"
        lead = next((p for p in (rec["efficacy"].get("pooled") or []) if p.get("lead")), None)
        rec["regimen"] = regimen(asset_rows.get(aid, []), c,
                                 weeks=(lead or {}).get("weeks"),
                                 participants=rec["evidence"].get("participants"))
        assets.append(rec)

    placed = sorted((a for a in assets if a["placed"]), key=lambda a: -a["overall"])
    for i, a in enumerate(placed, 1):
        a["rank"] = i
    rest = sorted((a for a in assets if not a["placed"]),
                  key=lambda a: (-(_stage_rank(a["stage"])), a["ticker"] or "", a["name"] or ""))
    if placed and draws:
        _rank_ranges(placed, pooled, trial_level, fits, draws, seed)
    for a in placed:
        _rank_line(a, len(placed))
    for a in placed + rest:
        a["efficacy"] = _public_efficacy(a["efficacy"])
        a["safety"] = _public_safety(a["safety"])
    out = {"assets": placed + rest, "placed": len(placed), "total": len(assets),
           "method": dict(METHOD), "simulation": {"draws": draws, "seed": seed, "level": LEVEL}}
    return {"out": out, "results": res, "unscored": unscored, "skipped": skipped,
            "pooled": pooled, "trial_level": trial_level, "tau": tau}


def _direct(e: dict, pooled) -> dict | None:
    """The head-to-head trial between a ranked drug and the one its gap is measured to, on
    the same measure, read from whichever record holds it and turned round where it is the
    other drug's: {entry, flip}. None where no such trial was posted."""
    v = e["versus"]
    direct, flip = None, 1.0
    for cell, drugs in pooled.items():
        if cell[0] != e["mkey"]:
            continue
        x, y = drugs.get(e["asset_id"]), drugs.get(v["asset_id"])
        if x is not None and x is not e and x["head_to_head"] == v["asset_id"]:
            direct, flip = x, 1.0
            break
        if y is not None and y["head_to_head"] == e["asset_id"] and direct is None:
            direct, flip = y, -1.0
    if direct is None:
        return None
    lo, hi = ((direct["own_lo"], direct["own_hi"]) if direct["k"] == 1
              else (direct["lo"], direct["hi"]))
    diff = flip * direct["effect"]
    lo, hi = (lo, hi) if flip > 0 else (-hi, -lo)
    return {"nct_ids": list(direct["trials"]), "diff": diff, "lo": lo, "hi": hi,
            "k": direct["k"], "scale": direct["scale"], "unit": direct["unit"]}


# --- efficacy ---------------------------------------------------------------------------------
def _ni_set_aside(x: dict) -> bool:
    """A result from a trial built to show the drug is no worse than its comparator (or
    equivalent to it) that does not also show it better: the posted test is not of the
    question the trial asked, and the margin it had to clear is not in the registry."""
    return bool(x.get("non_inferiority")) and not (
        x.get("z") is not None and M.p_one_sided(x["z"]) <= WIN_LEVEL + WIN_TOL)


def _trial_z(mine) -> dict:
    """{trial: the mean of its tested results' z, each capped at 5}."""
    per = defaultdict(list)
    for x in mine:
        if x.get("z") is not None and not _ni_set_aside(x):
            per[x["nct_id"]].append(max(-Z_CAP, min(Z_CAP, x["z"])))
    return {t: statistics.fmean(v) for t, v in sorted(per.items())}


def _trial_wins(mine) -> tuple[dict, dict, int]:
    """({trial: share of its endpoints won, as a percentage}, {id(result): won}, the wins
    before correction). A win is judged within its own trial: each trial controls its own
    error rate, so the correction allows for the endpoints that trial tested, not the
    programme's."""
    scored = [x for x in mine if not _ni_set_aside(x)]
    won, raw, share = {}, 0, {}
    for t in sorted({x["nct_id"] for x in scored}):
        every = [x for x in scored if x["nct_id"] == t]
        xs = [x for x in every if x.get("z") is not None]
        ps = [M.p_one_sided(max(-Z_CAP, min(Z_CAP, x["z"]))) for x in xs]
        adj = M.benjamini_hochberg(ps) if ps else []
        raw += sum(1 for p in ps if p <= WIN_LEVEL + WIN_TOL)
        won.update({id(x): (a <= WIN_LEVEL + WIN_TOL) for x, a in zip(xs, adj)})
        share[t] = 100.0 * sum(1 for x in every if won.get(id(x))) / len(every)
    return share, won, raw


def _toward_mean(per: dict, floor: float = 0.0) -> dict:
    """Each drug's mean over its trials moved toward the mean of every drug here by how
    little its own trials say (specification 2.6). One trial's value varies about its
    drug's level by the spread measured within the drugs with two or more trials (never
    under ``floor``), so a mean of k trials has that spread over k; the drugs' mean and
    the spread between them are fitted by ``meta_stats.shrink``. Under four drugs, or
    with no spread within drugs to measure, nothing moves.
    {asset_id: {mean, counted, weight, towards, n}}."""
    per = {aid: v for aid, v in per.items() if v}
    num = sum((len(v) - 1) * statistics.variance(v) for v in per.values() if len(v) > 1)
    den = sum(len(v) - 1 for v in per.values() if len(v) > 1)
    within = max(floor, num / den) if den else floor
    aids = sorted(per)
    ys = [statistics.fmean(per[a]) for a in aids]
    fit = (M.shrink(ys, [math.sqrt(within / len(per[a])) for a in aids])
           if aids and within > 0 else None)
    return {a: {"mean": ys[i], "counted": fit["shrunk"][i] if fit else ys[i],
                "weight": fit["weight"][i] if fit else 0.0,
                "towards": fit["mean"] if fit else None, "n": len(aids)}
            for i, a in enumerate(aids)}


def strengths(by_asset: dict) -> dict:
    """Strength and wins for every drug, each moved toward the drugs' mean
    (``_toward_mean``): strength on the scale of a trial's z, whose sampling spread is 1,
    and wins on the share of a trial's endpoints won. {asset_id: {"z": ..., "wins": ...}}."""
    z = _toward_mean({aid: list(_trial_z(m).values()) for aid, m in by_asset.items()}, 1.0)
    w = _toward_mean({aid: list(_trial_wins(m)[0].values()) for aid, m in by_asset.items()})
    return {aid: {"z": z.get(aid), "wins": w.get(aid)} for aid in by_asset}


def _efficacy(aid, mine, skipped: Counter, pooled, ranked_any: bool,
              strength: dict | None = None) -> dict:
    """A drug's efficacy: strength, wins and size against peers, with the averaged entries
    behind them and the words (specification 2.6 to 2.8, 2.13). Where some measure in the
    indication is ranked and this drug is on none, its size is not known and counts at 50,
    the average of the size scale over any cell's drugs, so strength and wins alone never
    carry it past drugs that were measured. Where no measure is ranked, efficacy is
    strength and wins alone for every drug."""
    ni = [x for x in mine if _ni_set_aside(x)]
    scored = [x for x in mine if not _ni_set_aside(x)]
    tested = [x for x in scored if x.get("z") is not None]
    parts = {}
    trial_ids = sorted({x["nct_id"] for x in scored})
    detail = {"trials": None, "z": None, "z_counted": None, "z_weight": 0.0, "z_mean": None,
              "z_drugs": None, "wins_share": None, "wins_counted": None, "wins_weight": 0.0,
              "wins_mean": None, "wins": None, "wins_unadjusted": None,
              "wins_by_control": {}, "top": None, "non_inferiority": len(ni),
              "tested_here": sum(1 for x in mine if not x["sponsor_test"]),
              "routes": dict(Counter(r for x in mine for r in x["route"].split(" + ")))}
    if tested:
        trial_z = _trial_z(scored)
        mean_z = statistics.fmean(trial_z.values())
        share, won, raw = _trial_wins(scored)
        mean_w = statistics.fmean(share.values())
        st = ((strength or {}).get(aid) or {}).get("z") or {
            "mean": mean_z, "counted": mean_z, "weight": 0.0, "towards": None, "n": None}
        sw = ((strength or {}).get(aid) or {}).get("wins") or {
            "mean": mean_w, "counted": mean_w, "weight": 0.0, "towards": None, "n": None}
        parts["strength"] = _clamp(100.0 * st["counted"] / Z_FULL)
        parts["wins"] = _clamp(sw["counted"])
        by_kind = {}
        for kind in ("placebo", "active"):
            group = [x for x in scored
                     if (x["reference_kind"] == "placebo") == (kind == "placebo")]
            if group:
                by_kind[kind] = [sum(1 for x in group if won.get(id(x))), len(group)]
        top = max(tested, key=lambda x: x["z"])
        detail.update({
            "z": mean_z, "z_counted": st["counted"], "z_weight": st["weight"],
            "z_mean": st["towards"], "z_drugs": st["n"], "trials": len(trial_ids),
            "wins_share": mean_w, "wins_counted": sw["counted"], "wins_weight": sw["weight"],
            "wins_mean": sw["towards"],
            "wins": sum(won.values()), "wins_unadjusted": raw, "wins_by_control": by_kind,
            "top": {"z": top["z"], "measure": top["measure"], "effect": top["test_effect"],
                    "se": top["test_se"],
                    "scale": "difference" if top["scale"] == "other" else top["scale"],
                    "route": top["route"], "unit": top["unit"], "nct_id": top["nct_id"],
                    "phase": top["phase"], "arms": top["arms"],
                    "reference_kind": top["reference_kind"]}})
    entries = sorted((by[aid] for by in pooled.values() if aid in by),
                     key=lambda e: (-len(e["peers"]), not isinstance(e["mkey"], str), -e["k"],
                                    -(e["people_known"] or 0), e["measure"], str(e["ckey"])))
    # Two ranked measures that share more than half their trials are one result stated
    # twice: the drug is ranked on the one with more peers and the other is named.
    counted, also = [], []
    for e in entries:
        if not e["ranked"]:
            continue
        mine_t = set(e["trials"])
        twin = any(len(mine_t & set(o["trials"])) > SAME_TRIALS * min(len(mine_t), len(o["trials"]))
                   for o in counted)
        (also if twin else counted).append(e)
    if counted:
        parts["size"] = statistics.fmean(e["score"] for e in counted)
    elif ranked_any and "strength" in parts:
        # Size is the mean chance of beating each peer, so over the drugs of any cell it
        # averages 50: each pair's two chances sum to one. A drug with no size is counted
        # at that average, level with its peers, rather than scored on strength and wins
        # alone, which saturate and would carry it past drugs that were measured.
        parts["size"] = SIZE_UNKNOWN
    score = statistics.fmean(parts.values()) if parts and "strength" in parts else None
    basis = None
    if score is not None:
        basis = "ranked" if counted else ("not comparable" if ranked_any else None)
    # The result quoted under the chart: the ranked one where the drug is ranked, else its
    # largest result by people treated, then the strongest.
    lead = counted[0] if counted else (
        max(entries, key=lambda e: ((e["people_known"] or 0),
                                    abs(e["effect"] / e["se"]) if e["se"] else 0.0))
        if entries else None)
    out = {"score": score, "parts": parts, "size_basis": basis,
           "endpoints": len(scored), "unscored": sum(skipped.values()),
           "unscored_why": dict(skipped), "entries": entries, "lead": lead,
           "counted": counted, "also": also, **detail}
    out["lines"], out["notes"] = _efficacy_words(out, scored, ni)
    return out


def _u(entry) -> str:
    unit = (entry.get("unit") or "").strip().lower()
    if entry["scale"] == "share" or "percent" in unit or "%" in unit:
        return "percentage points"
    return unit or "units"


def _weeks(w) -> str:
    lo, hi = round(w[0]), round(w[1])
    if lo == hi:
        return "1 week" if lo == 1 else f"{lo} weeks"
    return f"{lo} to {hi} weeks"


def _span(entry) -> str:
    w = entry.get("weeks")
    if not w or entry["scale"] == "log hazard ratio":
        return ""
    return " of " + _weeks(w)


def _plural(n, word="s") -> str:
    return "" if n == 1 else word


def _places(*values) -> int:
    """Decimal places for figures printed together: one where the largest is 1 or more,
    two down to 0.1, three below, so a small rate difference never prints as 0.0."""
    m = max((abs(v) for v in values if v is not None), default=0.0)
    return 1 if m >= 1 else 2 if m >= 0.1 else 3


def _f(v: float, places: int = 1) -> str:
    """A figure at these places, never a negative zero."""
    text = f"{v:.{places}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def _effect_line(lead: dict) -> str:
    """The lead result in words, its interval the right way round for the word used."""
    k_, span = lead["k"], _span(lead)
    where = (f"averaged across {k_} trials{span}, larger trials counting more" if k_ > 1
             else f"in one trial{span}")
    # One trial is quoted with its own interval, as posted; several with the interval of
    # their average, which allows for how far they differ.
    e_lo, e_hi = ((lead["own_lo"], lead["own_hi"]) if k_ == 1 else (lead["lo"], lead["hi"]))
    if lead["scale"] == "log hazard ratio":
        hr, lo, hi = (math.exp(-lead["effect"]), math.exp(-e_hi), math.exp(-e_lo))
        return (f"Hazard ratio {hr:.2f} against {lead['control']} on {lead['measure']}, "
                f"{where} (95% interval {lo:.2f} to {hi:.2f}).")
    if lead["scale"] == "share":
        # A share cannot move by more than 100 points either way.
        e_lo, e_hi = max(e_lo, -100.0), min(e_hi, 100.0)
    if lead["effect"] >= 0:
        word, lo, hi = "better", e_lo, e_hi
    else:
        word, lo, hi = "worse", -e_hi, -e_lo
    k = _places(lead["effect"], lo, hi)
    return (f"{_f(abs(lead['effect']), k)} {_u(lead)} {word} than {lead['control']} "
            f"on {lead['measure']}, {where} (95% interval {_f(lo, k)} to {_f(hi, k)}).")


def _efficacy_words(e: dict, mine, ni=()) -> tuple[list[str], list[str]]:
    """At most three sentences under the chart, and the rest for "What every score rests
    on" (specification 5.1)."""
    lines, notes = [], []
    if e["score"] is None:
        return lines, notes
    m, k = e["endpoints"], e["trials"]
    here = e["tested_here"]
    many = any(sum(1 for x in mine if x["nct_id"] == t) > 1 for t in {x["nct_id"] for x in mine})
    text = (f"Won {e['wins']} of {m} endpoint{_plural(m)} in {k} trial{_plural(k)}"
            + (", allowing for the number each trial tested" if many else ""))
    if here:
        text += (f"; {here} of {m} tested here from the posted counts, spread or interval, "
                 "where the sponsor posted no test")
    lines.append(text + ".")

    lead = e["lead"]
    if lead:
        lines.append(_effect_line(lead))
        if lead["ranked"]:
            lines.append(_rank_sentence(lead))
        elif (e["size_basis"] == "not comparable"
              or (lead["named_control"] and len(lead["peers_all"]) >= SHARED_MIN - 1)):
            # Said also where no measure in the indication is ranked, when three drugs did
            # share this control: the comparison was weighed and declined.
            lines.append(_no_rank_sentence(lead, e["size_basis"] == "not comparable"))
    elif e["size_basis"] == "not comparable":
        lines.append("Size against peers not known: none of its results is on a scale that "
                     "can be averaged, so its size counts at 50, what the average drug scores "
                     "against its peers.")

    # --- the rest, for "What every score rests on" ---
    z = "5 or more" if e["z"] >= 4.95 else _f(e["z"])
    notes.append((f"Strength, how far past chance its one trial's result is: z of {z}"
                  if k == 1 else
                  f"Strength, how far past chance its average trial result is: z of {z} "
                  f"across {k} trials")
                 + ", where 1.96 is p = 0.05 and 3.29 (p = 0.001) scores 100.")
    says = (f"since {'its one trial says' if k == 1 else f'its {k} trials say'} less on "
            f"{'its' if k == 1 else 'their'} own")
    moved_z = abs(_clamp(100.0 * e["z_counted"] / Z_FULL) - _clamp(100.0 * e["z"] / Z_FULL))
    if e["z_weight"] >= MOVED_MIN and e["z_mean"] is not None and moved_z >= 0.5:
        notes.append(f"Strength counted at z {e['z_counted']:.1f}: moved {e['z_weight']:.0%} of "
                     f"the way to the average of the {e['z_drugs']} drugs here "
                     f"({e['z_mean']:.1f}), {says}.")
    if (e["wins_weight"] >= MOVED_MIN and e["wins_mean"] is not None
            and abs(e["wins_counted"] - e["wins_share"]) >= 0.5):
        notes.append(f"Wins counted at {e['wins_counted']:.0f} of 100, from "
                     f"{e['wins_share']:.0f}: moved {e['wins_weight']:.0%} of the way to the "
                     f"average of the drugs here ({e['wins_mean']:.0f}), {says}.")
    if e["wins_unadjusted"] != e["wins"]:
        w = e["wins_unadjusted"]
        notes.append(f"{w} endpoint{_plural(w)} cleared p = 0.05 before allowing for the "
                     "number each trial tested.")
    if ni:
        n = len(ni)
        notes.append(f"{n} result{_plural(n)} from trials built to show the drug is no worse "
                     "than its comparator, and not shown better: left out of strength and "
                     "wins, since the margin each had to clear is not posted.")
    kinds = e["wins_by_control"]
    if len(kinds) == 2:
        notes.append(f"Against placebo it won {kinds['placebo'][0]} of {kinds['placebo'][1]}; "
                     f"against active comparators {kinds['active'][0]} of {kinds['active'][1]}.")
    elif "active" in kinds:
        notes.append("Every endpoint is against an active comparator.")
    if lead:
        if lead["k"] >= DISAGREE_MIN and lead["q_p"] is not None and lead["q_p"] < DISAGREE_P:
            notes.append("Its trials disagree more than chance explains on "
                         f"{lead['measure']}"
                         + (f": {lead['i2']:.0%} of the variation between them is beyond "
                            "chance" if lead["i2"] is not None else "") + ".")
        if lead["ranked"] and lead["k"] == 1 and lead["tau2_known"] and lead["tau2"] > 0:
            notes.append("One trial: its range is widened by how much trials of other drugs "
                         "varied on this measure.")
        if (lead["tau2_known"] and lead["tau2_df"] < TAU_DF_FEW
                and (lead["ranked"] or lead["k"] >= 2)):
            notes.append(f"Few drugs have two trials on {lead['measure']}, so how far trials "
                         f"differ rests on {lead['tau2_df']} degree{_plural(lead['tau2_df'])} "
                         "of freedom and the interval is likely too narrow.")
        if lead["prior"] and lead["weight"] >= MOVED_MIN:
            pr = lead["prior"]
            fig = (f"hazard ratio {math.exp(-lead['shrunk']):.2f}"
                   if lead["scale"] == "log hazard ratio"
                   else f"{lead['shrunk']:.1f} {_u(lead)}")
            notes.append(f"Counted at {fig}: moved {lead['weight']:.0%} of the way to the "
                         f"average of the {pr['n']} {pr['label']} drugs on this measure.")
    for o in e["counted"][1:]:
        notes.append(f"Also ranked {_ordinal(o['rank'])} of {o['of']} against {o['control']} "
                     f"on {o['measure']}.")
    for o in e["also"]:
        notes.append(f"Also posted {o['measure']} against {o['control']}, from most of the "
                     "same trials, so not counted a second time.")
    doses = sum(1 for x in mine if x["arms"] > 1)
    if doses:
        notes.append(f"{doses} result{_plural(doses)} from trials of several doses: tested on "
                     "all doses together, sized on the best dose, trimmed for having picked "
                     "the best. Several doses against one placebo arm: the placebo is counted "
                     "once.")
    off = sum(1 for x in mine if x["withdrawal"])
    if off:
        notes.append(f"{off} result{_plural(off)} measured from a randomisation after treatment "
                     "began, where the placebo arm is coming off the drug: counted for "
                     "strength and wins, not for size.")
    bound = sum(1 for x in mine if x["bound"] and x["z"] is not None)
    if bound:
        notes.append(f"{bound} result{_plural(bound)} rest on a p-value posted as a bound, "
                     "read at the bound, which can only understate them.")
    above = sum(1 for x in mine if x["z"] is None)
    if above:
        notes.append(f"{above} result{_plural(above)} posted only a p-value above a bound: "
                     "counted as not won, left out of strength.")
    why = e["unscored_why"]
    if why:
        n = sum(why.values())
        notes.append(f"{n} posted endpoint{_plural(n)} not scored: "
                     + "; ".join(f"{_UNSCORED_LABEL[r]} ({v})" for r, v in sorted(why.items()))
                     + ".")
    return lines, notes


def _rank_sentence(lead) -> str:
    """Line 3 for a ranked lead measure: its rank, or the drugs it cannot be separated
    from, and its gap to the leader (the runner-up for the leader), direct where a
    head-to-head trial exists."""
    peers = len(lead["peers"])
    basis = f"tested against {lead['control']} on {lead['measure']}"
    span = lead.get("rank_weeks")
    if span and lead["scale"] != "log hazard ratio" and round(span[0]) != round(span[1]):
        basis += f", in trials of {_weeks(span)}"
    if len(lead.get("peers_all") or []) > peers:
        basis += ", among those whose trials ran about as long"
    if lead["tied_with"]:
        n = len(lead["tied_with"])
        head = (f"Size of effect: cannot be separated from {n} of the {peers} other drugs "
                f"{basis}")
    else:
        head = f"Size of effect: {_ordinal(lead['rank'])} of {lead['of']} drugs {basis}"
    v = lead["versus"]
    direct = v.get("direct")
    if direct:
        name, n = v["name"], direct["k"]
        where = "in one trial" if n == 1 else f"across {n} trials"
        if direct["scale"] == "log hazard ratio":
            tail = (f"head to head {where}, hazard ratio {math.exp(-direct['diff']):.2f} "
                    f"against {name} (95% interval {math.exp(-direct['hi']):.2f} to "
                    f"{math.exp(-direct['lo']):.2f})")
        else:
            tail = f"head to head {where}, " + _gap(direct["diff"], direct["lo"], direct["hi"],
                                                     _u(direct), name)
        return f"{head}; {tail}."
    if v["asset_id"] in lead["tied_with"]:
        return f"{head}."
    if lead["scale"] == "log hazard ratio":
        tail = (f"on that basis, hazard ratio {math.exp(-v['diff']):.2f} against {v['name']} "
                f"(95% interval {math.exp(-v['hi']):.2f} to {math.exp(-v['lo']):.2f})")
    else:
        tail = "on that basis " + _gap(v["diff"], v["lo"], v["hi"], _u(lead), v["name"])
    return f"{head}; {tail}."


def _gap(diff, lo, hi, unit, name) -> str:
    """A difference from another drug in words, with its interval the right way round."""
    k = _places(diff, lo, hi)
    if lo > 0:
        return (f"{_f(diff, k)} {unit} ahead of {name} (95% interval {_f(lo, k)} to "
                f"{_f(hi, k)})")
    if hi < 0:
        return (f"{_f(-diff, k)} {unit} behind {name} (95% interval {_f(-hi, k)} to "
                f"{_f(-lo, k)})")
    side = "ahead of" if diff >= 0 else "behind"
    return (f"{_f(abs(diff), k)} {unit} {side} {name}, a gap that could be nothing "
            f"(95% interval {_f(-lo, k)} behind to {_f(hi, k)} ahead)")


def _no_rank_sentence(lead, counted_middle: bool = False) -> str:
    everyone = lead.get("peers_all") or []
    if not lead["named_control"]:
        why = "its control arm names no regimen another trial shares"
    elif len(everyone) >= SHARED_MIN - 1 and len(lead["peers"]) < SHARED_MIN - 1:
        span = f", {_weeks(lead['weeks'])}," if lead.get("weeks") else ""
        why = (f"its trials{span} ran for a different length from those of the other drugs "
               f"tested against {lead['control']} on {lead['measure']}")
    elif len(everyone) >= SHARED_MIN - 1 and not lead["tau2_known"]:
        why = (f"no drug has two trials on {lead['measure']}, so how far trials differ "
               "is not known")
    elif len(everyone) >= SHARED_MIN - 1:
        why = (f"how far trials differ on {lead['measure']} rests on too few trials "
               "to compare drugs")
    else:
        why = f"fewer than three drugs were tested against {lead['control']} on this measure"
    tail = ("so its size counts at 50, what the average drug scores against its peers"
            if counted_middle else "so efficacy is strength and wins alone")
    return f"Size against peers not known: {why}, {tail}."


# --- safety -------------------------------------------------------------------------------------
def _more_fewer(v: float, versus: str) -> str:
    """A difference in percentage points as words: "1.9 points fewer than placebo",
    "3.4 points more than control", "level with placebo"."""
    if round(abs(v), 1) == 0:
        return f"level with {versus}"
    return f"{abs(v):.1f} points {'more' if v > 0 else 'fewer'} than {versus}"


def _ends(lo: float, hi: float) -> str:
    """An interval of differences in percentage points, each end in words."""
    def one(v):
        return "0.0" if round(abs(v), 1) == 0 else f"{abs(v):.1f} {'more' if v > 0 else 'fewer'}"
    return f"95% interval {one(lo)} to {one(hi)}"


def _rd_bounds(f: dict) -> tuple[float, float]:
    """A risk difference's interval held to what is possible: the drug's rate cannot fall
    below 0 or rise above 1, so the difference stays within -control to 1 - control."""
    c = f["control_rate"]
    return max(f["lo"], -c), min(f["hi"], 1.0 - c)


def outcome_trials(land: dict) -> set:
    """The trials whose primary endpoint counts cardiovascular, kidney or all-cause death
    events: outcomes trials (SELECT, FIDELIO)."""
    out = set()
    for g in land.get("endpoints") or []:
        title = g.get("title") or ""
        if _OUTCOMES.search(title) and _OUTCOME_EVENTS.search(title):
            out.update(r["nct_id"] for r in g["rows"])
    return out


def _boxed_text(head: str, names) -> str:
    """A label's boxed warning as a clause: an all-capitals heading that the text repeats
    is dropped, a brand name the label runs on at the end is taken off, and words in
    capitals are put in sentence case."""
    t = re.sub(r"\s+", " ", head or "").strip().rstrip(".")
    m = re.match(r"^([A-Z][A-Z ,/&-]{3,}?)\s+(?=[A-Z][a-z])", t)
    if m and t[m.end():].lower().startswith(m.group(1).strip().lower()[:8]):
        t = t[m.end():]
    words = t.split()
    low = {str(n).lower() for n in names if n}
    while words and words[-1].strip(".,;").lower() in low and len(words) > 1:
        words.pop()
    t = " ".join(w.capitalize() if i == 0 and w.isupper() and len(w) > 4 else
                 (w.lower() if w.isupper() and len(w) > 4 else w)
                 for i, w in enumerate(words))
    return (t[:1].upper() + t[1:]).rstrip(" ,;")


def _safety(c, s_, fits, other, set_aside=()) -> dict:
    """A drug's safety score from its averaged parts, with the words (specification 2.10,
    5.2). A part posted for fewer than a quarter of the people behind the other is left
    out of the score and named; the parts scored count equally."""
    parts, weights, lines, notes = {}, {}, [], []
    total_trials, total_people = s_.get("trials") or 0, s_.get("participants") or 0
    sentences = {}
    have = {part: fits[part] for part in _PART if fits.get(part)}
    big = max((f["n_drug"] for f in have.values()), default=0)
    used = [p for p, f in have.items() if f["n_drug"] >= PART_MIN_SHARE * big]
    for part, f in have.items():
        key, label = _PART[part]
        versus = "placebo" if f["kind"] == "placebo" else "active comparators"
        if f["k"] == total_trials:
            where = (f"in its one trial of {f['n_drug']:,} people" if f["k"] == 1 else
                     f"averaged across its {f['k']} trials and {f['n_drug']:,} people")
        else:
            where = ((f"in 1 of its {total_trials} trials" if f["k"] == 1 else
                      f"averaged across {f['k']} of its {total_trials} trials")
                     + f" and {f['n_drug']:,} of {total_people:,} people treated")
        lo, hi = _rd_bounds(f)
        sentences[part] = (
            f"{label}: {_more_fewer(100 * f['rd'], versus)} "
            f"({100 * f['drug_rate']:.1f}% against {100 * f['control_rate']:.1f}%), {where} "
            f"({_ends(100 * lo, 100 * hi)}).")
        if part in used:
            parts[key] = _clamp(SAME_AS_CONTROL - POINTS_PER_PP * 100.0 * f["rd"])
            weights[key] = 1.0 / len(used)
    score = None
    if parts:
        score = sum(parts[k] * weights[k] for k in parts)
        if c.get("boxed_warning"):
            score = _clamp(score - BOXED_DEDUCTION)
    # Under the chart: the scored part with the most people behind it. The rest on demand.
    order = sorted(used, key=lambda p: -fits[p]["n_drug"])
    order += sorted((p for p in have if p not in used), key=lambda p: -fits[p]["n_drug"])
    if order:
        lines.append(sentences[order[0]])
        notes.extend(sentences[p] for p in order[1:])
    for part in order:
        f, label = fits[part], _PART_NOUN[part]
        if part not in used:
            keep = next(p for p in used)
            notes.append(f"{_PART[part][1]} left out of the score: posted for "
                         f"{f['n_drug']:,} people, under a quarter of the "
                         f"{fits[keep]['n_drug']:,} behind {_PART_NOUN[keep]}.")
        if f["k"] > 1 and f["top_share"] > DOMINANT:
            notes.append(f"{f['top_share']:.0%} of the figure for {label} rests on one trial "
                         f"({f['top_trial']}).")
        if f["dispersion"] is None:
            notes.append(f"No drug here has two controlled trials counting {label}: how far "
                         "trials differ is not known, so the interval is the trial's own.")
        o = other.get(part)
        if o:
            what = "placebo" if o["kind"] == "placebo" else "active comparators"
            olo, ohi = _rd_bounds(o)
            notes.append(f"{_PART[part][1]}: {_more_fewer(100 * o['rd'], what)} in "
                         f"{o['k']} trial{_plural(o['k'])} and {o['n_drug']:,} people "
                         f"({_ends(100 * olo, 100 * ohi)}), not scored: fewer people than "
                         "the figure above.")
    if set_aside:
        n = len(set_aside)
        notes.append(f"Serious adverse events leave out {n} outcomes trial{_plural(n)} "
                     f"({', '.join(set_aside)}), whose serious events are largely the heart "
                     "attacks, strokes or kidney events the trial counts as its result.")
    if len(parts) == 2:
        notes.append("Stopped for side effects and serious adverse events count equally.")
    if any(fits[p]["kind"] == "active" or fits[p]["summed_arms"] for p in order):
        notes.append("Counts are people with an event over each arm's whole follow-up; an arm "
                     "followed for longer reports more.")
    if score is not None and c.get("boxed_warning"):
        head = O._boxed_headline(c.get("boxed_warning") or "", [c.get("name"), c.get("generic")])
        text = _boxed_text(head, [c.get("name"), c.get("generic"), *(c.get("brands") or [])])
        notes.append(f"FDA boxed warning, {BOXED_DEDUCTION:.0f} points off: {text}.")
    d = fits.get("deaths")
    if d:
        notes.append(f"Deaths, reported and not scored: {_more_fewer(100 * d['rd'], 'control')} "
                     f"({100 * d['drug_rate']:.1f}% against "
                     f"{100 * d['control_rate']:.1f}%) "
                     + ("in one trial." if d["k"] == 1 else f"across {d['k']} trials."))
    controlled = max((fits[p]["n_drug"] for p in used), default=0)
    care = None
    if score is not None and controlled < MIN_PARTICIPANTS:
        care = f"Read with care: {controlled} people treated in its controlled trials."
    elif score is not None and total_people and controlled < THIN_SHARE * total_people:
        care = (f"Read with care: the safety score rests on {controlled:,} of the "
                f"{total_people:,} people treated in its trials "
                f"({controlled / total_people:.0%}).")
    if care:
        notes.append(care)
    kinds = {fits[p]["kind"] for p in used}
    return {"score": score, "parts": parts, "part_weights": weights,
            "fits": fits, "other": other, "used": {p: 1.0 / len(used) for p in used},
            "withdrawn_excess": 100 * fits["withdrawn"]["rd"] if "withdrawn" in fits else None,
            "serious_excess": 100 * fits["serious"]["rd"] if "serious" in fits else None,
            "control_kind": (next(iter(kinds)) if len(kinds) == 1
                             else ("mixed" if used else None)),
            "participants": s_.get("participants"), "trials": s_.get("trials"),
            "controlled_participants": controlled or None,
            "controlled_trials": len({t for p in used for t in fits[p]["trials"]}) or None,
            "read_with_care": care, "set_aside": list(set_aside),
            "lines": lines, "notes": notes}


# --- the rank range -------------------------------------------------------------------------------
def _rank_ranges(placed, pooled, trial_level, fits, draws, seed) -> None:
    """Where each drug's overall rank falls when every estimate is redrawn within its own
    sampling error (specification 2.11): the averaged effects behind size and the risk
    differences behind safety. One draw per trial, carried through every measure that
    trial feeds, and one per trial for its safety counts, carried through both parts.
    Strength, wins and evidence are held at what was observed. A drug with no size against
    peers has no size in its score, so nothing of it is redrawn on the efficacy side."""
    import numpy as np
    rng = np.random.Generator(np.random.PCG64(seed))
    n = len(placed)

    def cdf(x):
        return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))

    # Efficacy: every (drug, trial) that feeds an averaged effect gets one column.
    eff_trials = sorted({(aid, t) for (cell, aid), tl in trial_level.items() for t in tl["ncts"]})
    col = {key: i for i, key in enumerate(eff_trials)}
    e_draw = rng.standard_normal((draws, max(len(eff_trials), 1)))
    y_star = {}
    for cell in sorted(pooled, key=str):
        for aid in sorted(pooled[cell]):
            e = pooled[cell][aid]
            cols = [col[(aid, t)] for t in e["trials"]]
            y_star[(cell, aid)] = e["effect"] + e_draw[:, cols] @ np.array(e["coef"])
    post_star = {}
    for cell in sorted(pooled, key=str):
        by = pooled[cell]
        for aid in sorted(by):
            e = by[aid]
            if e["prior"]:
                pr = e["prior"]
                mean = sum(u * y_star[(cell, m)] for u, m in zip(pr["mean_weight"], pr["members"]))
                post_star[(cell, aid)] = e["weight"] * mean + (1 - e["weight"]) * y_star[(cell, aid)]
            else:
                post_star[(cell, aid)] = y_star[(cell, aid)]
    eff = np.zeros((draws, n))
    for j, a in enumerate(placed):
        ef = a["efficacy"]
        cols = [np.full(draws, ef["parts"]["strength"]), np.full(draws, ef["parts"]["wins"])]
        if ef["counted"]:
            sizes = []
            for e in ef["counted"]:
                cell = (e["mkey"], e["ckey"])
                mine = post_star[(cell, a["asset_id"])]
                probs = []
                for o in e["peers"]:
                    sd = e["pair_sd"][o]
                    diff = mine - post_star[(cell, o)]
                    probs.append(cdf(diff / sd) if sd > 0 else (diff > 0) + 0.5 * (diff == 0))
                sizes.append(100.0 * np.mean(probs, axis=0))
            cols.append(np.mean(sizes, axis=0))
        elif "size" in ef["parts"]:
            cols.append(np.full(draws, ef["parts"]["size"]))
        eff[:, j] = np.mean(cols, axis=0)

    # Safety: one column per (drug, trial), shared by withdrawals and serious events.
    saf_trials = sorted({(aid, t) for aid, fs in fits.items() for p in _PART if p in fs
                         for t in fs[p]["trials"]})
    scol = {key: i for i, key in enumerate(saf_trials)}
    s_draw = rng.standard_normal((draws, max(len(saf_trials), 1)))
    rd_star = {}
    for aid in sorted(fits):
        for part in _PART:
            f = fits[aid].get(part)
            if not f:
                continue
            cols = [scol[(aid, t)] for t in f["trials"]]
            wide = math.sqrt(f["dispersion"]) if f["dispersion"] else 1.0
            rd_star[(aid, part)] = f["rd"] + wide * (s_draw[:, cols] @ np.array(f["coef"]))
    saf = np.zeros((draws, n))
    for j, a in enumerate(placed):
        aid, total = a["asset_id"], 0.0
        for part, weight in a["safety"]["used"].items():
            rd = rd_star[(aid, part)]
            total = total + weight * np.clip(SAME_AS_CONTROL - POINTS_PER_PP * 100.0 * rd,
                                             0, 100)
        s_ = total
        if a["boxed"]:
            s_ = np.clip(s_ - BOXED_DEDUCTION, 0, 100)
        saf[:, j] = s_
    ev = np.array([a["evidence"]["score"] or 0.0 for a in placed])
    overall = (eff + saf + ev[None, :]) / 3.0
    ranks = (-overall).argsort(axis=1).argsort(axis=1) + 1
    for j, a in enumerate(placed):
        lo, hi = M.interval(ranks[:, j].tolist(), LEVEL)
        a["rank_range"] = [int(round(lo)), int(round(hi))]


def _rank_line(a, n) -> None:
    """The open company's line under the table."""
    lo, hi = a.get("rank_range") or (a["rank"], a["rank"])
    a["rank_line"] = (f"{a['name']} ranks {a['rank']} of {n} scored drugs"
                      + (f", and could sit anywhere from {lo} to {hi}" if lo != hi else "")
                      + (", with its size of effect not comparable with peers and counted at "
                         "50, the average" if a["efficacy"]["size_basis"] == "not comparable"
                         else "")
                      + ".")


# --- the output ----------------------------------------------------------------------------------
def _pair(x) -> list | None:
    return [x[0], x[1]] if x else None


def _public_entry(e: dict, lead) -> dict:
    """One averaged effect as the output carries it (specification 3)."""
    hr = e["scale"] == "log hazard ratio"
    ranked = e["ranked"]
    v = e.get("versus") if ranked else None
    return {
        "measure": e["measure"], "control": e["control"], "scale": e["scale"],
        "lead": e is lead, "counted": bool(e.get("counted")),
        "effect": e["effect"], "se": e["se"], "lo": e["lo"], "hi": e["hi"],
        "own_lo": e["own_lo"], "own_hi": e["own_hi"],
        "hazard_ratio": math.exp(-e["effect"]) if hr else None,
        "hazard_ratio_lo": math.exp(-e["hi"]) if hr else None,
        "hazard_ratio_hi": math.exp(-e["lo"]) if hr else None,
        "k": e["k"], "tau2": e["tau2"], "tau2_df": e["tau2_df"],
        "q_p": e["q_p"], "i2": e["i2"], "participants": e["participants"],
        "weeks": _pair(e["weeks"]), "cell_weeks": _pair(e.get("cell_weeks")),
        "rank_weeks": _pair(e.get("rank_weeks")) if ranked else None,
        "peers_all": len(e.get("peers_all") or []),
        "routes": list(e["routes"]), "top_dose": e["top_dose"], "trials": list(e["trials"]),
        "head_to_head": e["head_to_head"],
        "shrunk": e["shrunk"], "shrunk_se": e["shrunk_se"], "weight": e["weight"],
        "prior": ({"label": e["prior"]["label"], "n": e["prior"]["n"],
                   "mean": e["prior"]["mean"]} if e["prior"] else None),
        "ranked": ranked,
        "score": e.get("score") if ranked else None,
        "rank": e.get("rank") if ranked else None,
        "of": e.get("of") if ranked else None,
        "tied_with": list(e.get("tied_with") or []) if ranked else None,
        "versus": ({"asset_id": v["asset_id"], "name": v["name"], "diff": v["diff"],
                    "lo": v["lo"], "hi": v["hi"], "p_better": v["p_better"],
                    "same_length": v["same_length"], "weeks": _pair(v["weeks"]),
                    "direct": ({k: v["direct"][k] for k in ("nct_ids", "diff", "lo", "hi")}
                               if v["direct"] else None)} if v else None)}


def _public_efficacy(ef: dict) -> dict:
    lead = ef.get("lead")
    counted = ef.get("counted") or []
    entries = []
    for e in ef.get("entries") or []:
        e["counted"] = any(e is x for x in counted)
        entries.append(_public_entry(e, lead))
    keep = ("score", "parts", "size_basis", "endpoints", "trials", "z", "z_counted",
            "z_weight", "z_mean", "wins_share", "wins_counted", "wins_weight", "wins_mean",
            "wins", "wins_unadjusted", "wins_by_control", "tested_here",
            "routes", "unscored", "unscored_why", "non_inferiority")
    return {**{k: ef.get(k) for k in keep}, "pooled": entries,
            "lines": ef["lines"], "notes": ef["notes"], "top": ef.get("top")}


def _public_fit(f: dict | None) -> dict | None:
    """One averaged safety part as the output carries it: fractions, the se widened for
    disagreement between trials and ``se_own`` before, the rates on the pooling weights."""
    if not f:
        return None
    pr = f.get("prior")
    return {"kind": f["kind"], "rd": f["rd"], "se": f["se"], "se_own": f.get("se_own", f["se"]),
            "dispersion": f.get("dispersion"), "lo": f["lo"], "hi": f["hi"], "k": f["k"],
            "drug_rate": f["drug_rate"], "control_rate": f["control_rate"],
            "n_drug": f["n_drug"], "n_control": f["n_control"],
            "top_share": f["top_share"], "top_trial": f["top_trial"],
            "summed_arms": f["summed_arms"],
            "shrunk": f.get("shrunk", f["rd"]), "shrunk_se": f.get("shrunk_se", f["se"]),
            "weight": f.get("weight", 0.0),
            "prior": ({"label": pr["label"], "n": pr["n"], "mean": pr["mean"]} if pr else None),
            "trials": list(f["trials"])}


def _public_safety(sf: dict) -> dict:
    fits, other = sf.get("fits") or {}, sf.get("other") or {}
    return {"score": sf["score"], "parts": sf["parts"], "part_weights": sf["part_weights"],
            "withdrawn": _public_fit(fits.get("withdrawn")),
            "serious": _public_fit(fits.get("serious")),
            "deaths": _public_fit(fits.get("deaths")),
            "other_control": {"serious": _public_fit(other.get("serious")),
                              "withdrawn": _public_fit(other.get("withdrawn"))},
            **{k: sf[k] for k in ("withdrawn_excess", "serious_excess", "control_kind",
                                  "participants", "trials", "controlled_participants",
                                  "controlled_trials", "lines", "notes")},
            "read_with_care": sf.get("read_with_care"), "set_aside": sf.get("set_aside") or []}


# --- evidence, stage and words ---------------------------------------------------------------------
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


METHOD = {
    "efficacy": ("Mean of strength, wins and size against peers. Strength: how far past "
                 "chance the average trial result is; 100 at p = 0.001, a drug with one or "
                 "two trials moved toward the average of the drugs here. Wins: the average "
                 "share of a trial's endpoints won, allowing for the number that trial "
                 "tested. Size: the chance of beating each drug tested against the same "
                 "control on the same measure in trials of about the same length, from its "
                 "trial results averaged. Where four or more drugs of one mechanism class "
                 "share a measure and a control, each is first moved part of the way to the "
                 "class average. Where no measure here is ranked, efficacy is strength and "
                 "wins alone; where some are and a drug is on none, its size counts at 50, "
                 "what the average drug scores against its peers. A result from a trial "
                 "built to show a drug no worse than its comparator is left out unless it "
                 "shows it better."),
    "safety": ("Stopped for side effects and serious adverse events, each the difference "
               "from control averaged trial by trial over controlled trials, against placebo "
               "or against active comparators, whichever holds more of the drug's people: 75 "
               "when equal to control and 5 points per percentage point of excess. The two "
               "count equally; a part posted for under a quarter of the people behind the "
               "other is left out and named. An outcomes trial's serious adverse events are "
               "left out, since they are largely the events it counts as its result. Less "
               "10 for an FDA boxed warning. Deaths are reported, not scored."),
    "evidence": ("People treated across its trials with posted safety counts, on a log "
                 "scale (100 people 25, 1,000 people 50, 10,000 people 75), plus 20 for "
                 "Phase 3 results."),
    "overall": "The mean of efficacy, safety and weight of evidence.",
    "uncertainty": ("The chart shows scores, not measurements, so it draws no error bars. "
                    "The range beside a rank is where it falls 95 times in 100 when every "
                    "trial's effect size and safety count is varied within its margin of "
                    "error."),
    "caveat": ("Scores cross trials that differ in who they enrolled, for how long and "
               "against what. Drugs are compared on size only where they were tested "
               "against the same control; the book cannot see the background treatment "
               "behind a placebo, or how long each arm was followed for safety. A result "
               "with no sponsor test is tested here from its posted counts, spread or "
               "interval, every interval read as two-sided, an arm with no events given half "
               "an event for its margin of error, and a hazard ratio read as the drug against "
               "its comparator. The scores order the evidence; they are not a head-to-head "
               "result."),
}
