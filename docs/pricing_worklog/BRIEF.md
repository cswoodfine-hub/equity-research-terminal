# Pricing a Phase 3 or Phase 2 asset for the equity research terminal

You research ONE pipeline asset and return the asset-level inputs its revenue model needs.
The engine builds: new patients per year from a pool, a logistic launch curve, a net price,
discontinuation, then a DCF risk-adjusted by a probability of success the engine computes
itself. Company-level rows (cost ratios, tax, discount rate) are added later from the
company's existing seeds; do not research them. Do not research probability of success.

House rule, absolute: never fabricate. Every number carries a source a reader can open (URL,
SEC accession, NCT number, or a lookup in the book via the helper below). Where a number is a
judgement (a multiple over an anchor, a choice between two sources), say so in its note and
give the case against it. A field you cannot source is left null with the reason; a null is
better than a guess.

## The helper (read-only copy of the book)

    python3 /tmp/claude-0/price/lookup.py demand <brand>     CMS Part B/D spend, claims, beneficiaries by year
    python3 /tmp/claude-0/price/lookup.py pool <indication>  pools the book already carries for a disease
    python3 /tmp/claude-0/price/lookup.py seed <asset>       every assumption row the book holds for an asset

Use `seed` on the closest already-modelled competitor: its seed is the best template, and
where it has already measured something (a ramp, a discontinuation) reuse it unless the
asset is genuinely different, and say which.

## Fields to return

Asset-level:
- `therapy_mode`: "chronic" (taken continuously, including oncology treated to progression)
  or "one_time" (a single course or dose that is not repeated).
- `list_price_per_patient`: mm USD per patient-year (0.00383 = $3,830). House convention:
  the closest marketed comparator in the same disease and setting, at its CMS Medicare
  spending per beneficiary (`lookup.py demand`), which is gross of rebates. A published
  annual list price beats the convention where one exists and is named.
- `gross_to_net_pct`: the SHARE TAKEN OFF LIST, not the share kept. The house convention
  depends on which part of Medicare the anchor comes from (backend/gross_to_net.py):
  0.5 on a CMS Part D per-beneficiary price (measured: halving lands at a median 96% of
  CMS's own negotiated net prices), and 0.056604 on a Part B one, because Part B pays 106%
  of average sales price, which is already net of discounts, so only the 6% add-on comes
  off (1 - 1/1.06). A published list price (WAC) takes neither; source its discount. A
  value of 0.7 means net is 30% of list. Check the direction before you write it; three
  earlier seeds had it inverted, and eight had 0.5 on a Part B anchor. A biosimilar is
  paid its own ASP plus an add-on of the reference's ASP (SSA 1847A(b)(8): 6%, or 8% for
  five years for one first paid by 2027-12-31). Its net is the reference's Part B figure
  / 1.06 x the biosimilar-to-reference ASP ratio whichever way the list is written: a list
  struck on an ASP ratio takes 0.056604 (the ABP 206 seed); one struck on an allowed-amount
  ratio takes add-on / (ratio + add-on) (the ABP 692 seed). Never take the add-on twice.
- `discontinuation_pct`: share of the treated stock stopping per year. For oncology treated
  to progression, derive from median duration of treatment or PFS in the pivotal or
  comparator trial (1 - exp(-12/median_months) per year is acceptable, say so). One course:
  1.0 with therapy_mode chronic is how the book models a fixed course.
- `forecast_start_year`: the first full year after the current one (2027) unless a launch is
  clearly later; note the expected launch from the primary completion date.
- `exus_multiple`: ex-US revenue per 1.0 of US, from a named comparator's filed geographic
  split, or null.
- `economics_share`: the company's share of the asset if partnered (from a filing), else 1.0.

Per indication (one block per indication you model; model the lead Phase 3 indication, and
a second only if it has its own Phase 3 and a sourced pool):
- `indication`: EXACTLY one of the indication names in the context file.
- `prevalence`, `incidence`: patients and patients per year. If `lookup.py pool` shows the
  book already carries a prevalence for that indication name (epidemiology.csv or another
  asset), set prevalence and incidence to null and say "carried by the book": the book fills
  them, and two assets must never carry two different figures for one disease.
- `eligible_pct`: share of the pool the label reaches (line of therapy, biomarker, severity).
- `penetration_peak_pct`: share of the eligible untreated pool captured per year at peak.
  Solve it back from what a real incumbent measurably captured (CMS beneficiaries over the
  pool, or reported patients), name the incumbent, and label any multiple a judgement.
- `untreated_carryover_pct`: the engine has no exit from the untreated pool. A line of cancer
  therapy takes 0. A chronic disease whose pool would otherwise outgrow its measured
  prevalence is held stationary, retention = pool / (pool + inflow), as the remternetug and
  direclidine seeds do, labelled a judgement.
- `already_treated_patients`: US patients already on a marketed drug for the same label when
  this one launches, from the incumbent's filed sales over its net price. The engine takes
  them out of the opening pool, so a second entrant draws on the untreated remainder instead
  of replaying the incumbent's launch into the whole pool. With it set, take the
  incumbent's measured capture as measured; do not shade it with a multiple for the
  incumbent's presence (DYNE-251 and zodasiran).
- `ramp_steepness` (logistic k) and `ramp_midpoint_year` (years from forecast_start_year to
  half of peak): reuse a measured curve from the closest modelled competitor where possible.

## At Phase 2

The same fields and rules, with four differences:
- Model the indication the company says it will take into Phase 3, or failing that the one
  its largest Phase 2 is in. A second block only with its own Phase 2 and a sourced pool.
- `forecast_start_year`: from the company's filed plan where one exists (a Phase 3 start, a
  filing date). Otherwise the Phase 2's primary completion year plus five: a year to start
  Phase 3, three to its primary completion, and the Phase 3 rule's two calendar years after
  that. Label it a judgement and give the case for earlier (breakthrough designation,
  accelerated approval on a Phase 2) or later.
- Uptake: a Phase 2 asset has not shown whether it will lead or trail its class. Take the
  multiple over the incumbent's measured capture at 0.5 unless the Phase 2 data or the
  class position say otherwise, and say which.
- Refuse early, before any price work, when the mechanism or the intended indication is not
  public (nothing to price: "undisclosed"), when the company holds only an option on
  someone else's programme, or when the Phase 2 has been stopped or its data were negative
  and the company has said it will not go on. Hold, with the reason, an asset that would
  mostly take its revenue from the owner's own marketed product.

## Output

Write `/tmp/claude-0/price/out/<TICKER>_<slug>.json`:

    {"ticker": "...", "name": "<exact asset name from the context>",
     "summary": "3-5 lines: what the asset is, the pivotal trial, the price anchor, the uptake anchor",
     "asset": {"<field>": {"value": ..., "unit": "...", "source": "...", "note": "..."}, ...},
     "indications": [{"indication": "...", "fields": {"<field>": {...}, ...}}],
     "refuse": null or "reason this asset should not be seeded (failed pivotal, no path, no sourceable price)"}

Reply with the output path, the headline price and peak penetration, and every field you
marked a judgement or left null. Do not edit the repository. WebFetch is blocked for most
hosts; use WebSearch and the helper. Keep to roughly 20 searches.

## If you are the second reader

You are given a researcher's JSON. For every non-null field, independently check that the
source says what the field claims (search for it; do not trust the researcher's wording),
that the unit and direction are right (gross_to_net is share OFF list; list price is mm USD
per patient-year), that the pool is the label's, and that the arithmetic holds. Write
`/tmp/claude-0/price/verified/<same filename>` with the same shape, each field gaining
`"verdict": "confirmed" | "corrected" | "withdrawn"` and `"check": "what you checked"`.
Correct a field only with a source; withdraw it (value null) if its source does not hold.
Reply with the count per verdict and every correction, one line each.
