"""How well each assumption is evidenced, as a grade the terminal can reason with.

Every row already names its source, and the source usually says what kind of evidence it
is: an accession number, a CMS series, a published trial, "reused from" another seed,
"convention", "judgement". Read as free text that is only useful to someone reading the
row. A board question is different: "this works if A, B and C hold; we have evidence for
A, partial evidence for B, and C is an assumption". Answering it means the grade has to
be a field, so a break-point can say which kind of number it rests on.

Six grades, strongest first:

- ``filed``: the company's own filings, or arithmetic on them (10-K, 10-Q, 8-K, 20-F, 6-K,
  results exhibits, the SEC data sets).
- ``measured``: computed from a public data series (CMS Part B and D, FRED, market
  returns, SEER, NHANES, the registry, the FDA and EMA books).
- ``published``: a study, report or statute someone else stands behind (a DOI, a journal,
  ICER, BIO/Informa, Damodaran, the U.S. Code).
- ``analogue``: borrowed from another product or seed, or fitted to another launch.
- ``convention``: a modelling convention or an engine default.
- ``judgement``: an analyst's call.

A row that names more than one kind takes the weakest, because a price reused from
another seed is an analogue however well that seed was sourced. The first three are
evidence, an analogue is partial evidence, and the last two are assumptions (``CLASS``).
Grades written by these rules are marked unreviewed until an analyst confirms them.
"""

from __future__ import annotations

import re

GRADES = ("filed", "measured", "published", "analogue", "convention", "judgement")
CLASS = {"filed": "evidence", "measured": "evidence", "published": "evidence",
         "analogue": "partial evidence", "convention": "assumption",
         "judgement": "assumption"}

# Weakest first: the first rule a text matches is its grade.
_RULES = (
    ("judgement", re.compile(
        r"\bjudg(e)?ment\b|set against what .{0,24}has to displace|analyst curve|"
        r"\banalyst'?s? (call|view|estimate|input)\b", re.I)),
    ("convention", re.compile(
        r"(?<!not a )\bconvention\b|engine's terminal value|the year after the last reported|"
        r"\bplaceholder\b|phase default|curated default|\bdefault:|\bby construction\b|"
        r"no exclusivity on file|^\s*assumed\s*$|feeding the same pool|incidence is the pool|"
        r"the year after the \d{4} run rate|held at the \d{4} run rate", re.I)),
    ("analogue", re.compile(
        r"reused from|\banalogue\b|\banalog\b|\bas [\w./ -]+ carries it\b|"
        r"\bfitted\b|own launch|comparator|borrowed from|taken from [\w./-]+\.csv|"
        r"\b\w+_\w+\.csv\b|workbook", re.I)),
    ("published", re.compile(
        r"\bdoi\b|doi\.org|\bet al\b|N Engl J Med|\bNEJM\b|\bJAMA\b|Lancet|"
        # A PubMed identifier is a citation whether or not the row wrote "et al": one row
        # named all four authors of a BMC Medicine paper and graded as nothing at all.
        r"\bPMC\d{6,8}\b|\bPMID\b|BMC Medicine|\bBMJ\b|"
        r"J Clin Oncol|\bASCO\b|\bICER\b|BIO/Informa|Damodaran|U\.S\.C\.|"
        r"Directive \d|journal|Cancer Facts|American Cancer Society|\bstudy\b|"
        r"\blabel\b|prescribing information|\banalysts put\b|"
        # A peak forecast a named research house or bank has published, with the
        # publication named beside it, is published evidence. Without this a row sourced
        # to GlobalData's own consensus forecast graded as nothing at all.
        r"peak sales (?:potential|estimates?)|consensus (?:forecast|estimate|peak|"
        r"risk-adjusted)|\bGlobalData\b|\bEvaluate Pharma\b|\bLeerink\b|"
        r"Bank of America|\bBofA\b", re.I)),
    ("measured", re.compile(
        r"\bCMS\b|Part [BD]\b|\bFRED\b|weekly returns|drug_demand|\bSEER\b|NHANES|"
        r"Census|\bCDC\b|ClinicalTrials|\bNCT\d{8}\b|\bregistry\b|openFDA|Orange Book|"
        r"Purple Book|\bEMA\b|\bICE BofA\b|Treasury|primary completion", re.I)),
    ("filed", re.compile(
        r"\b\d{10}-\d{2}-\d{6}\b|\b10-[KQ]\b|\b8-K\b|\b20-F\b|\b6-K\b|annual report|"
        r"results exhibit|product axis|sec_fsds|filed lines|patent table|"
        r"financial statement data sets|free cash flow|\bfiled\b|approved and selling|"
        r"effective rate|pre-tax income|reported product revenue|WAC Disclosure|"
        r"balance sheet", re.I)),
)

# Keys that set the shape of a model rather than a fact about the product. Where the row's
# text names no evidence, they are conventions, not unsourced numbers.
_STRUCTURE = {"therapy_mode", "forecast_years", "growth_fade_years", "terminal_growth_pct",
              "forecast_start_year", "terminal_mode"}


def grade(source: str | None, note: str | None = None, key: str | None = None) -> str | None:
    """The grade the row's own words give it. A structural key with no evidence named is a
    convention; any other row whose words name no kind of evidence is None, ungraded,
    which the terminal reads as weaker than a judgement."""
    text = " ".join(t for t in ((source or "").strip(), (note or "").strip()) if t)
    if (source or "").strip():
        for name, pattern in _RULES:
            if pattern.search(text):
                return name
    return "convention" if key in _STRUCTURE else None


def weakest(grades) -> str | None:
    """The weakest of several grades; an ungraded row is weaker than any."""
    seen = list(grades)
    if not seen or any(g is None for g in seen):
        return None
    return max(seen, key=GRADES.index)


def evidence_class(g: str | None) -> str:
    """Evidence, partial evidence or assumption, as a board sentence puts it."""
    return CLASS.get(g, "assumption")


def backfill(conn) -> dict:
    """Grade every row the rules may grade: those no analyst has reviewed. Re-run on each
    refresh, so a rule grade follows its source text when the text changes. Returns
    counts per grade."""
    counts: dict = {}
    for table in ("assumptions", "company_lines"):
        rows = conn.execute(
            f"SELECT id, key, source, note FROM {table}"
            f" WHERE COALESCE(evidence_reviewed, 0) = 0").fetchall()
        for row in rows:
            g = grade(row["source"], row["note"], row["key"])
            conn.execute(f"UPDATE {table} SET evidence = ? WHERE id = ?", (g, row["id"]))
            counts[g] = counts.get(g, 0) + 1
    return counts
