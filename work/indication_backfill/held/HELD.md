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
