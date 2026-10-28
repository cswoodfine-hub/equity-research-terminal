# Research that is sound but is not being loaded

Both of these pass the verifier. They are held on a different test: **a number the
author of the file said should not be trusted, which materially moves the answer.**
That is the one judgement the verifier cannot make, and it is the reason a human read
stays in the plan.

Neither is wrong research. Both are one sourced number away from loading.

## amgn_uplizna.csv — the whole file

`discontinuation_pct` = 0.057579, measured the house way (565 mg per beneficiary against
a 600 mg maintenance year). The agent that wrote it put it first on its own list of
least-confident numbers: *"it implies an 11.7-year median time on drug, which nothing
supports. The Medicare population is still growing and first-year patients take three
infusions rather than two, which lifts the ratio. No published Uplizna persistence study
exists."*

It is an asset-level row, so it drives all three Uplizna layers, and the engine's stock
identity makes it the dominant term — steady-state stock is new starts divided by it:

| discontinuation | steady-state stock | autoimmune hepatitis layer peak | npv |
|---|---|---|---|
| 0.0576 as written | 29,899 | 2,999mm | 3,234mm |
| 0.20 | 8,611 | 1,453mm | 2,214mm |
| 0.40 | 4,305 | 841mm | 1,485mm |

A 2 to 3.5-fold swing on a number its own author does not believe. The hand arithmetic
is sound — 71,757 pool x 0.20 eligible x 0.12 penetration is 1,722 new patients a year
— so the pool work is not what is in doubt.

**What would release it:** a published inebilizumab persistence figure, or the 2025 CMS
Part B file, where the Medicare population is less dominated by part-year starters.

## nvs_fabhalta_amd.csv — two layers out of seven

The other five Fabhalta layers loaded; only the two macular degeneration rows are held.
The agent's own words: *"The engine applies Fabhalta's $252,095 orphan price to 247,511
eligible eyes. No payer funds that for a preventive capsule. I set penetration to 0.02
and wrote the reason into the row rather than hiding it in the number — it still peaks
at ~1,075mm against a 505mm base. Read it as an order of magnitude. The honest fix is a
stated AMD price, which would make it its own asset."*

The pool and the eligibility are properly sourced. What is wrong is the price: an orphan
PNH price applied to an ophthalmology population is not a price anyone would pay, and
the layer is really saying what Fabhalta would earn if AMD patients were charged like
PNH patients.

The plain "Macular Degeneration" row goes with it: its penetration was zeroed only to
stop it double-counting the wet AMD layer, so with that layer gone its reason for being
zero goes too.

**What would release it:** a sourced AMD price per patient-year. As the agent says, that
probably makes it a separate asset rather than a layer.

## azn_datroway.csv: the whole file (Phase 1b, 2026-10-28)

The anchor is sound: AstraZeneca's own FY2025 Product Revenue line, $78mm, on the same
basis as the Enhertu seed (Product Sales plus Alliance Revenue). The growth row is what
is held. `revenue_growth_pct` = 1.666667, the 2026 the filed halves imply ($208mm)
against FY2025, with no `revenue_ceiling_musd` to stop it. Faded over five years it
carries AstraZeneca's line from $78mm to $2,157mm in 2030, about $4.95bn of combined
sales with Daiichi Sankyo. The agent put this first on its own list: *"This is the
weakest row."* No published peak could be opened: the GlobalData and press figures it
found, $1.4bn to $5bn, sit on sites this session's network blocks.

**What would release it:** a published peak-sales forecast a reader can open, set as
`revenue_ceiling_musd`, or a rate solved to one, as Jaypirca's is.

## axsm_sunosi.csv: the whole file (Phase 1b, 2026-10-28)

The product half is sound: Axsome's FY2025 10-K names Sunosi product sales of $120.1mm
(Note 14), and the price and discontinuation rate are measured from CMS Part D 2024.
But the book holds no Axsome seed, so there is no company half to copy, and the brief
forbids deriving one inside a product file. Loaded as it stands, the engine refuses to
value Sunosi (no discount rate), so it prices nothing.

**What would release it:** an Axsome company half (cost ratios, tax, discount rate,
other-costs charge), written once as its own seed the way every other company's is.
Axsome has made a pre-tax loss every year to FY2025, so the house effective-rate
method for `tax_rate` has nothing to read and needs a stated alternative.

## axsm_sunosi.csv and axsm_axs_14_esreboxetine.csv: both files (2026-10-28, second round)

The Sunosi file is now complete: the Phase 1b anchor, growth restated to the +11.7% the
filed 2026 quarters imply, an Axsome company half derived from the FY2025 10-K, and three
layers (shift work disorder, binge-eating disorder, paediatric ADHD). The company half is
what is held. On its own lines Axsome spends 89.4% of revenue on SG&A and 28.7% on R&D,
so Sunosi values at -$421mm and its three readouts price as negative stakes: a positive
result would read as destroying value. The AXS-14 file, written by another agent at the
same time, took AbbVie's cost lines instead, the comparator route `rare_crysvita.csv`
takes for a loss-making company. One company cannot carry two answers.

**What would release them:** a decision on Axsome's company half, own 10-K lines or a
profitable comparator's, written into both files identically.

## nbix_nbi_1065845.csv: the whole file (2026-10-28)

NBI-1065845 is osavampator, and two agents modelled it at once, one under each name.
`drafts/nbix_osavampator.csv` is kept; it carries the same Neurocrine company half, the
maintenance readout as well as the acute ones, and the Takeda royalty read at 14%
against this file's 15%. `data/asset_alias_map.csv` now folds the code into the name.

**What would release it:** nothing; it is a duplicate, kept for its sources.

## amgn_evenity_paediatric.csv: the paediatric OI layer (2026-10-28)

The pool is sound (5,412 children, a Swedish paediatric rate on US under-18s), but the
existing Evenity osteogenesis imperfecta layer already prices the same study in the same
children, so both together count them twice.

**What would release it:** setting the existing osteogenesis imperfecta layer's
penetration to 0 in the terminal, after which this layer is the only one on them.

## jnj_inlexzo.csv: the failed SunRISe-2 rows (2026-10-28)

The finding is sound: SunRISe-2 (NCT04658862, muscle-invasive bladder cancer) was stopped
for futility in October 2024. But the rows sit on "Urinary Bladder Neoplasms", which is
also the row Inlexzo's approved non-muscle-invasive business is built on, since MeSH
gives both diseases one descriptor and the label test cannot see the approval. Inlexzo is
modelled from patients, so a stated pos of 0 and overlap of 0 on that row would read as
the whole product failing once patient-mode layers are risked. Taken out of the seed it
was appended to the same day, before the book loaded it.

**What would release it:** a muscle-invasive row of its own on the asset (a curated
addition, as `asset_indication_additions.csv` carries), so the failure lands on the
disease it was in.

## Released 2026-10-28

- `axsm_sunosi.csv` and `axsm_axs_14_esreboxetine.csv`: Axsome's company half is a
  profitable comparator's (AbbVie's, as AXS-14 carried), the house precedent for a
  loss-making filer, written identically into both. Back in `drafts/`.
- `amgn_evenity_paediatric.csv`: the existing osteogenesis imperfecta layer was retired by
  migration 093 (penetration 0), so the paediatric layer is the only one on these
  children. Appended back to `drafts/amgn_evenity.csv`.
