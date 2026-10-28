# Building a forecast for a clinical-stage asset the book does not model

Read this, then `BRIEF.md` (the layer brief: its price, discontinuation and pool rules
apply here unchanged), then three seeds that already do this job:

- `data/assumptions/smmt_ivonescimab.csv`: an oncology asset, two indications, a
  partner's economics share
- `data/assumptions/nams_obicetrapib.csv`: a chronic cardiovascular asset with a large
  pool and a small penetration
- `data/assumptions/prax_relutrigine.csv`: a rare disease asset priced off an analogue

Copy their shape and the density of their source sentences.

## First, check it is not already modelled

A catalyst can sit on an asset row that is a second name for a product the book already
values: a generic name beside the brand (triheptanoin is Dojolvi), a programme code, a
partner's copy of the same drug (BNT162b2 is Comirnaty), a subcutaneous form filed under
its own brand. Search `data/assumptions/` and the `assets` table before writing anything.
If the product is modelled under another row, **stop**: the fix is a mapping, not a
second model of one drug. Write which row, which seed and why into your report.

## The absolute rule

**Never fabricate a value.** Every number names a source a reader can open. A clinical
asset is mostly judgement, and that is allowed, but a judgement says it is one, gives the
case for it, and says what would replace it. "Analyst consensus" without a document is not
a source.

## The company half

Copy `cogs_pct`, `sga_pct`, `rd_pct`, `other_costs_pct`, `tax_rate`, `risk_free`, `erp`,
`beta`, `cost_of_debt`, `debt_weight` and `terminal_growth_pct` **verbatim, with their
source text**, from a sibling seed of the same company. Where the company has no sibling
seed, derive them from its latest 10-K or 20-F and show the arithmetic; for a company with
no product revenue yet, say so and take the cost ratios from the nearest sibling in the
book with the reason.

## The asset half

- `therapy_mode`: `chronic` for a drug taken continuously, `one_time` for a gene or cell
  therapy or a single course. See how the exemplars carry it.
- `forecast_start_year`: the launch year. Readout plus the FDA review clock
  (`data/fda_review_clock.csv`), stated, never a guess.
- `list_price_per_patient` and `gross_to_net_pct`: an approved analogue's CMS
  per-beneficiary figure where one fits, named, with why it is the analogue.
- `discontinuation_pct`: the analogue's, measured the same way, or a trial's.
- Per indication: `prevalence` and `incidence` (copied verbatim where the book already
  holds the pool: two numbers for one disease fails the suite), `eligible_pct`,
  `penetration_peak_pct`, `ramp_midpoint_year`, `ramp_steepness`.
- `pos`, `pos_success`, `pos_failure`: the published chain from
  `data/pos_transitions.csv` for the area and phase, with the figures and their n.
- `economics_share`: the owner's share where a partner takes part of the economics, from
  the agreement in the filing. 1.0 where nobody does, said so.
- `currency`: the company's reporting currency, as for any seed.

## Format, verify, report

As `BRIEF.md`. One file per asset at `work/indication_backfill/drafts/<ticker>_<slug>.csv`.
If a file of that name already exists anywhere in `drafts/` or `data/assumptions/`, the
book may already model it: read it before writing, and never overwrite a row.
