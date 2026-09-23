# Pipeline coverage and correctness

What the pipeline book gets wrong and what it does not hold at all, measured on
2026-09-23 by ten agents with every number independently re-derived. Ordered by value at
stake, not by effort. Nothing here is a forecast; every figure is something the database
or a filing already says.

Done items are struck through with the commit that closed them. Everything else is open.

## The state, in four numbers

| | |
|---|---|
| Unmarketed assets modelled at all | 60 of 1,392 (4.3%) |
| Big pharma Phase 2, 2/3 and 3 modelled | 55 of 370 (14.9%) |
| Named pipeline share of enterprise value | 3.2% |
| Pipeline value resting on one shared anchor | 65.5% |

The depth where an asset is modelled is good: 54 of 59 run a full patient funnel, all 65
indication blocks carry all six pool factors, there is not one placeholder curve and not
one unsourced row. The problem is breadth, and the softness of the four assumptions that
actually set the revenue curve.

## Corrections, ranked by value at stake

1. ~~The Zepbound anchor derived once rather than restated seven times, the 4.5% rounding
   corrected to its own 4.3882%, and consistent grading.~~ Done, 98e6067.
2. ~~Cagrilintide priced in USD inside a DKK book, carried at a sixth of itself.~~
   Done, 98e6067. Novo +$7.12 a share.
3. ~~The eight obesity lines each given the whole pool.~~ Done, 0d9c4d4. `pool_crowding`
   runs the identity once over one shared pool, returns the patients who stop, and
   refuses to pool two denominators. Cost: VKTX -19.3%, NVO -4.0%, AZN -2.1%, LLY -1.9%,
   AMGN -1.4%, MRK -0.2%. It also found Merck and AstraZeneca competing on a breast
   cancer pool.
12. **The marketed incumbents are not deducted from the pool, which is 6.0% too large.**
   Measured from filed regional splits: Zepbound 4.06mm US patients, Wegovy 2.36mm,
   Saxenda 0.01mm, so 6.43mm US adults are already on branded obesity therapy. The
   pipeline's pool is stated as 107.6mm untreated and should be 101.2mm. Wegovy, Ozempic
   and Mounjaro are modelled in marketed mode off reported revenue and never touch the
   pool identity, so nothing deducts them.
   - **Blocked on a data bug, not on judgement.** The incumbents cannot be linked to the
     pool automatically today: Wegovy and Zepbound carry no obesity `asset_indications`
     row at all, while Omvoh, which is mirikizumab, an IL-23 antibody for ulcerative
     colitis, is tagged Obesity. Fix the tagging first, then the deduction is mechanical.
   - **The root cause: a co-morbidity in a trial's enrolment criteria becomes an
     indication.** Omvoh's obesity tag comes from NCT06937086, which studies mirikizumab
     alongside tirzepatide in ulcerative colitis patients whose conditions are listed as
     "Ulcerative Colitis" and "Obesity or Overweight". `indication_mapping` maps every
     condition string, so the second becomes a disease the drug treats. Clazakizumab, an
     IL-6 for transplant rejection, and a milk polar lipid dairy powder are tagged the
     same way. **No valuation moves on this today**, because none of the mis-tagged
     assets is modelled and Omvoh is valued off reported revenue, so it is a data defect
     that blocks the item above rather than a live error.
11. **The CagriSema overlap, opened by the currency fix and unquantified.** Cagrilintide is
   now the largest line in Novo's book at 244,230mm DKK, above Ozempic (201,237) and
   Wegovy (195,972), on a peak of 163,213mm against Wegovy's 110,518mm. Its trials are
   CagriSema studies, which contain semaglutide, so a share of that revenue is Novo
   taking its own franchise. The book counts both at full value. This is the largest open
   question in the pipeline and it was hidden while the currency error held the number
   down.
4. **The price path is flat on five of eight obesity assets, worth about $30bn.**
   Maridebart, AZD6234, Elecoglipron, Cagrilintide and VK2735 hold no
   `net_price_decline_pct` and run $3,321 unchanged for nineteen years. Retatrutide,
   Eloralintide and Berobenatide carry -5.7% from Lilly's own filings. Same class, same
   price basis, same market, and no stated reason for the asymmetry. Applying the book's
   own accepted -5.7% costs $30,331mm. Lilly's 8-K exhibit 0000059478-26-000077 says US
   price would have fallen about 9% excluding adjustments, which would cost a further
   $13,997mm. This is a decision, not a bug, and it points the opposite way from item 5.
5. **No ex-US on seven of eight obesity assets, worth about $79bn the other way.** Thirty
   of the sixty modelled assets carry an `exus_multiple`, median 0.68. Seven of the eight
   obesity lines carry none and are valued on the US alone. Applying the book's own median
   adds $79,475mm. Whether these assets earn ex-US revenue is an evidence question, not a
   modelling one, and it should be answered per asset rather than by applying a median.
6. **The anchor is measured on a pool the engine does not use, worth about $12bn.** The
   rate divides by the untreated pool; `forecast.patients_for_indication` multiplies
   penetration by pool plus incidence. `capture_anchor` can compute either, and the
   engine convention gives 4.20% against 4.39%. Changing it is a decision with a measured
   cost, now visible rather than buried.
7. **The eight obesity lines together claim an implausible share of the population.** The
   model's own peak new starts sum to 31.087mm a year, and the largest simultaneous US
   figure is 29.106mm in 2045, 27.1% of the pool, against a treated stock of 44.829mm,
   41.7% of all US obese adults on a branded incretin. No competitor takes share from
   another in this book: each asset is given the whole pool. That is the structural form
   of items 3 to 6 and the one worth settling first, because it decides whether the
   multiples mean anything.
8. **United Therapeutics' "Oral Treprostinil" is nebulised Tyvaso's fibrosis filing.**
   $3,093mm, $64.58 a share, 24.2% of the company. The two trials on it are inhaled
   treprostinil studies. A naming and scope error on a quarter of a company's value.
9. **Twenty-four of sixty assets carry no `economics_share` and are valued at 100%.**
   They hold $125,242.7mm, 72.9% of the pipeline book. The `asset_economics` table is
   empty for all sixty. Where a partner exists and is not recorded, the book keeps
   revenue that is not the filer's.
10. **Four assets are priced on an indication with no `asset_indications` row**:
    Savolitinib, VX-147, Povetacicept and CD388. Povetacicept's probability comes from a
    stated row so the stale phase never reaches its number, but the other three should be
    checked.

## Coverage, and why the obvious way to close it makes the book worse

317 of 372 late-stage big pharma assets carry no assumption row. Sixteen of those are not
gaps: five are already-marketed products, two are lines the book values elsewhere, and
twelve are duplicate rows that fold into nine. `asset_merge` finds none of them, because
it matches on names and these differ by development code.

That leaves about 301 real gaps, and **29 of them are metabolic assets that would be
valued off the same Zepbound anchor that already carries 65.5% of pipeline value**.
Closing the gap in the obvious order concentrates the book further rather than
diversifying it, so items 3 to 7 come first.

Seven companies hold 161 late-stage assets and no pipeline model at all: Bayer, Gilead,
GSK, Novartis, Regeneron, Roche and Sanofi. Bayer and Roche have no valuation of any kind,
because neither files with the SEC and the book has no share count for them.

## The order to work in

1. Settle item 7, the shared pool, because items 3 to 6 are all consequences of it.
2. Then item 3, the CagriSema overlap, which is the largest single open number.
3. Then items 4 and 5 together, since they point in opposite directions and netting them
   is the only honest way to present either.
4. Then items 8, 9 and 10, which are cheap and self-contained.
5. Only then add assets, starting outside metabolic, and run a duplicate pass first.
