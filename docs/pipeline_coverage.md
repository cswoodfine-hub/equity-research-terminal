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

**Closed**

1. ~~The Zepbound anchor derived once rather than restated seven times, the 4.5% rounding
   corrected to its own 4.3882%, and consistent grading.~~ 98e6067.
2. ~~Cagrilintide priced in USD inside a DKK book, carried at a sixth of itself.~~
   98e6067. Novo +$7.12 a share.
3. ~~The eight obesity lines each given the whole pool.~~ 0d9c4d4. One pool, counted
   once, stoppers returned to it, two denominators never mixed. VKTX -19.3%, NVO -4.0%,
   AZN -2.1%, LLY -1.9%, AMGN -1.4%, MRK -0.2%. It also found Merck and AstraZeneca
   competing on a breast cancer pool.
4. ~~The price path and the ex-US line.~~ a1ad602 and 473c005. They nearly cancel and
   were applied together. Two defects cleared on the way: the ex-US multiple was in the
   crowding key, so storing one would have dissolved item 3; and the price decline
   compounded past the cliff where the erosion curve already carries price.
5. ~~Lilly's 10% was a contribution, not a rate.~~ 473c005. Its table's three columns sum
   exactly to their printed totals, so the per-unit change is 1.43/1.53 - 1 = -6.54%. And
   a null price was never an abstention: the engine reads it as a flat real price for
   nineteen years. All four blanks now carry 0.05 at grade analogue.
6. ~~Indication tagging, and pooling on the asset-indication pair.~~ 7e062c4. No
   automatic rule shipped: four candidate signals measured at 5.7% to 42% precision over
   all 2,520 pairs, so the seven verified co-morbidities are recorded in
   `asset_indication_overrides` instead. Pooling now keys on the population through
   `indication_groups`, so Viking's Weight Loss asset competes with the seven on Obesity.
   The book did not move, which is correct: no mis-tagged row sat on a modelled asset.

**Open, largest first**

7. **The eight obesity lines still claim an implausible share of the population.** Even
   with one pool counted once, the model's peak has a large share of US obese adults on a
   branded incretin. No asset takes share from another on any clinical ground; the split
   is each analyst's multiple. The plan for fixing that is in
   `docs/pool_share_by_evidence.md`, and it opens with the finding that the evidence does
   not exist yet.
8. **The CagriSema overlap, opened by the currency fix and unquantified.** Cagrilintide is
   the largest line in Novo's book, above Ozempic and Wegovy, and its trials are CagriSema
   studies, which contain semaglutide. The book counts both at full value.
9. **The marketed incumbents are not deducted from the pool, which is 6.0% too large.**
   6.43mm US adults are already on branded obesity therapy, measured from filed regional
   splits, against a pool stated as 107.6mm untreated. Wegovy, Ozempic and Mounjaro run in
   marketed mode off reported revenue and never touch the pool identity. Now unblocked:
   the tagging fix landed, though Wegovy and Zepbound still carry no obesity indication
   row of their own, which is the remaining piece.
10. **United Therapeutics' "Oral Treprostinil" is nebulised Tyvaso's fibrosis filing.**
    $3,093mm, $64.58 a share, 24.2% of the company, with inhaled-treprostinil trials
    attached.
11. **Twenty-four of sixty assets carry no `economics_share` and are valued at 100%.**
    They hold $125,242.7mm, 72.9% of the pipeline book. `asset_economics` is empty for all
    sixty.
12. **Four assets are priced on an indication with no `asset_indications` row**:
    Savolitinib, VX-147, Povetacicept and CD388.

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

Six of the twelve are closed. The remaining order, with the reason for each position.

1. **Item 8, the CagriSema overlap.** The largest single open number, and the currency
   fix made it visible rather than creating it.
2. **Item 9, deducting the incumbents.** Now unblocked by the tagging fix. What remains
   is that Wegovy and Zepbound carry no obesity indication row of their own, so the link
   from a marketed brand to the pool it occupies cannot yet be made automatically.
3. **Items 10, 11 and 12**, which are cheap, self-contained and each wrong in a way that
   is not arguable.
4. **Item 7, clinical share**, only as far as `docs/pool_share_by_evidence.md` says it
   can go: fix the data the registry already publishes and build the comparability gate.
   The score itself waits for readouts that have not happened.
5. **Only then add assets**, starting outside metabolic, and run a duplicate pass first.

## What the price and uptake pass added, 24 September 2026

Eleven seeds written, ten of which build, for $13,963mm of risk-adjusted value the book
was not carrying. SNY +5,660, AZN +3,230, GSK +2,692, BMY +882, NVS +766, REGN +733.

Four assets were researched to the same depth and deliberately not seeded, which is the
more important half of the result. Ziltivekimab: ZEUS missed at a hazard ratio of 0.99
(0.88 to 1.11). Pelacarsen: Lp(a)HORIZON missed in 8,323 patients and Novartis has stated
no filing intent, so it carries a price and no uptake curve and the engine refuses to
build it. Astegolimab: ARNASA missed and Roche has stated no submission, so a launch curve
has nothing to be measured from. Giredestrant: no pool, because SEER publishes no free
complete prevalence by hormone-receptor status.

Three things the pass found that were larger than the fourteen assets it was about.

**The price basis was right and is now measured rather than asserted.** Almost every
pipeline asset is priced off a comparator's CMS spending per Medicare beneficiary, cut by
a gross-to-net share, and both halves of that are wrong in opposite directions: CMS
spending is gross of rebates, while spending per beneficiary is not a year of therapy,
because the denominator is everyone who filled the drug at any point in the year. Coverage
measured against each drug's own schedule runs from 48% of a year on Verzenio and Xtandi
to 124% on Leqvio. Against CMS's own Maximum Fair Prices for the nine cycle-one IRA drugs
that carry a demand row, the convention lands at a median 96% of a real negotiated net
annual price, so the two errors cancel (`backend/gross_to_net.py`). The spread is 65% on
Imbruvica to 167% on Januvia, so it is sound for a book and loose for one asset. Three
verifiers independently recommended annualising every price, which would have put the book
50% above CMS's own negotiated prices. It was not done.

**A drug CMS names only by its container had no demand series at all.** There is no
"Repatha" row in the CMS Part D file, only Sureclick, Syringe and Pushtronex, so the whole
molecule was dropped for Repatha, Dupixent, Praluent, Kesimpta and Taltz and half of it
for Fasenra and Adbry. Repatha has 459,932 Medicare beneficiaries and $1,962mm of 2024
Part D spending and carried nothing. 83 rows recovered, 15 assets that had no series now
have one, 97 existing 2024 rows corrected, and underneath it a silent defect where any
asset CMS listed twice carried whichever row the payload happened to end with: Cellcept
Part B held 24 beneficiaries against the molecule's 42,875.

**An asset drew its success rate from the wrong disease.** The therapeutic area that picks
the precedent transition rate was resolved by classifying every trial an asset had ever
run as one blob, so tozorakimab was an infectious disease on its SARS-CoV-2 trials while
the line in the book is COPD, and REGN7508 was oncology on a cancer-associated thrombosis
trial while the line is atrial fibrillation. Nine of 393 modelled assets change area and
every one is a correction.

**Open, added to the list above**

13. **Roche and Bayer can hold no valuation at all, and Roche has 25 late-stage assets.**
    Neither files with the SEC, so no fetcher reads their financials: Roche has 101 assets,
    3,915 price rows and zero financial rows, so a beta is derivable and a cost structure
    is not. Trontinemab is the concrete loss. Its research survived verification in full,
    with a price corroborated within 2.7% by an announced list and an uptake anchor
    measured in Leqembi and Kisunla patient-years rather than beneficiary counts, and it
    cannot be seeded because there is no company block to put it on. This is the single
    largest unvaluable block in the book and it is one fetcher, not one asset.
14. **Amlitelimab and tozorakimab carry a 0.94 probability on one positive readout.**
    `pos_granular` places an asset at its own gate, and a single positive Phase 3 filing
    moves it to the NDA/BLA transition. Amlitelimab's Phase 3 programme has five trials
    reading out into 2026, so one positive result is not the whole programme at the filing
    gate. The behaviour is consistent across the book and is not obviously right.
15. **`data/assumptions/vk2735.csv` has a 14-column row** where every other row has 12,
    on `economics_share`. Pre-existing and tolerated by the loader, which reads by index.
16. **The Part D gross-to-net convention is loose per asset by design.** 65% to 167% of a
    negotiated price across nine drugs. An asset whose comparator has a published annual
    list price should use it: admilparant, AZD0780 and efimosfermin now do, and the rest
    of the book does not.

**The gap that remains**

208 late-stage assets at companies holding five or more still carry nothing, of 397. The
five largest gaps are NVS 43, GSK 32, ROG 25, LLY 20 and SNY 18. ROG's 25 are blocked on
item 13 rather than on research.
