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
