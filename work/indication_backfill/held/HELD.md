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

## azn_datroway.csv — the whole file (Phase 1b, 2026-10-28)

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

## axsm_sunosi.csv — the whole file (Phase 1b, 2026-10-28)

The product half is sound: Axsome's FY2025 10-K names Sunosi product sales of $120.1mm
(Note 14), and the price and discontinuation rate are measured from CMS Part D 2024.
But the book holds no Axsome seed, so there is no company half to copy, and the brief
forbids deriving one inside a product file. Loaded as it stands, the engine refuses to
value Sunosi (no discount rate), so it prices nothing.

**What would release it:** an Axsome company half (cost ratios, tax, discount rate,
other-costs charge), written once as its own seed the way every other company's is.
Axsome has made a pre-tax loss every year to FY2025, so the house effective-rate
method for `tax_rate` has nothing to read and needs a stated alternative.
