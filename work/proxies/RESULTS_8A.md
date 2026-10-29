# 8a: trial spend against reported R&D

Run 2026-10-29. Reproduce with
`python3 work/proxies/tools/trial_spend_study.py --download <dir>`, then
`ER_TOOL_DB=<copy> python3 work/proxies/tools/trial_spend_study.py <dir>`.

## Data

- **Studies.** Every interventional study the 75 universe companies lead, started 2010 on,
  any status, from ClinicalTrials.gov v2 with the book's sponsor map, acquired names
  included. Pfizer 1,745, GSK 1,711, Novartis 1,659 at the top.
- **Load.** A study's enrolment spread evenly over its run from start to primary
  completion, by phase.
- **R&D.** `ResearchLessExpensedIprd` (R&D with acquired in-process R&D taken out), USD
  filers, fiscal years.
- **Sample.** 688 company-years across 69 companies.

## Result

**A real signal, too small to predict R&D with.**

- Year-on-year changes in trial load and in R&D correlate at 0.30 (n=582). The
  elasticity is about 0.18: 10% more load goes with 1.8% more R&D.
- Within a company, the levels of load and R&D correlate at a median 0.70, positively for
  90% of companies (52 with six or more years).
- In dollars, with a free cost per phase, the fit was noise: Phase 1 came out negative.

Next year's R&D level, median absolute error, fitted on fiscal years to 2021 and scored on
2022 on:

| rule | all (n=244) | revenue over $1bn (n=90) | revenue under $1bn (n=154) |
|---|---|---|---|
| R&D flat | 15.9% | 12.7% | 19.9% |
| `rd_pct` × actual revenue | 32.0% | **10.9%** | 71.7% |
| pooled growth | 16.8% | 11.4% | 20.0% |
| pooled growth + trial load | 16.4% | 11.1% | 21.1% |
| company's own trend + load | 20.4% | 13.1% | 23.3% |

In years when the load moved by more than 30%:
- Over $1bn revenue: 10.8% against 13.2% for flat (n=28).
- Under $1bn revenue: 23.1% against 26.2% (n=88).

Leaving one company out at a time gives the same ordering.

## What it means

- **No change to the base case.** For a company with revenue, `rd_pct` × revenue is as good
  as the proxy, and the plan's rule was to replace it only if the proxy won.
- **Most of R&D is not in the registry.** Discovery, manufacturing, headcount and
  partnered spend move R&D year to year more than trial enrolment does.
- **Where it earns a place:**
  - **Forward burn in 8b**, when a company's trial load is about to move by more than
    30%. That is the case trailing burn misses, and here it is about 3 points more
    accurate.
  - **A What Changed flag** when a company's load moves that much.

## Limits

- Look-ahead bias: the registry is today's record, so a completed study's enrolment is
  its actual count, where the company planned on its target.
- Studies with no enrolment or no primary completion date are left out.
- Collaborator-led studies the company pays for are not counted.
