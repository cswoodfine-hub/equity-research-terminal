# Action plan, 2026-11-02

Written after an audit that started from a question: a student's Eli Lilly deck landed
within 4% of the price and this book is 62% below it, so what is the book doing wrong.
The audit answered it, and the answer moved the work.

## What the audit established

**The revenue forecasting is not the problem.** Measured against the companies' own
guidance, the book is within ±10% on 9 of the 11 companies that guide, median gap −1.4%.
Lilly specifically is 1.4% below guidance. The first diagnosis in that session, that the
book was 18% under guidance, was wrong: it compared the products-only line against total
company guidance, ignoring the company lines, the run-rate stand-in and uncovered
revenue, all of which `fair_value.revenue_split` already accounts for.

**98% of the gap to market price is valuation convention, not forecasting.** Across those
11 companies the revenue level explains $28 a share of difference and the conventions
explain $1,084. It is not a uniform low bias either: Merck (−$31), Bristol (−$37) and
Vertex (−$18) are names where the book sits above the price. The bias is concentrated
almost entirely in Lilly, at $848 a share, where the market capitalises the GLP-1 engine
as a perpetuity and this book does not.

**The deck was not better at forecasting.** It was a 39% upside call on a stock that did
45%, and roughly 90% of its value is a 3.0–3.5% terminal growth at a 6.80% WACC, which is
a ~30× terminal multiple. That matched what the market pays for Lilly. One name, one
direction, one period.

**The book could not tell you whether it is right.** That was the real finding, and it is
now being fixed.

## The order of work

### 1. Settle the perpetuity question — SETTLED 2026-11-07, see docs/perpetuity.md

The answer is not a terminal growth rate or a discount rate. It is a revenue ceiling in
`future_pipeline.room()` that nothing on any page named.

**The book holds a company plus its launches to its own best modelled year, in real
terms, for ever.** Lilly's book peaks at $175,431mm in 2031, so the launches may refill
what erodes and may never make the company larger than that, grown at 2.35% expected
inflation. That is the strongest claim in the sum and it was implicit.

It is also the binding constraint on the whole disagreement with the market, which the
launch-productivity break-point reports as unreachable without saying why:

| launch rate | future pipeline | capped away |
|---|---|---|
| 0.4026 (measured) | $191,756mm | 0.0% |
| 0.80 | $300,501mm | 10.6% |
| 1.50 | $308,180mm | 31.3% |
| 3.00 | $315,213mm | 54.1% |

The value asymptotes near **$315bn however productive the research is**, and closing the
gap to Lilly's price needs **$764bn**. So no launch rate reaches the price, and the
break-point is right to return no answer: the ceiling stops it, not the rate.

The future-pipeline module itself is in good order and should not be changed to chase
the market. Its rate is measured, its known downward bias is argued at length against
measured productivity decay, and it names 0.4102 as the top of the range. The problem was
never the rate.

What was done: the ceiling is now published on the sum as `future.cap` (peak, peak year,
long-run rate, the share it caps away and whether it binds) and stated in the bridge's
launches step. Merck's binds on 1.2% today; Lilly's does not bind at the measured rate
and binds hard above it.

**Settled on the evidence, 2026-11-07. Keep the cap.** Ten-year real revenue growth for
US large-cap pharma, 2007 to 2025, deflated by US CPI: +1.00% a year across every window,
and **−0.02% once the four purchase windows are held out** (Schering-Plough, Celgene,
Allergan, Alexion). Organic real growth is zero and the whole of the positive figure is
bought, which the future pipeline line does not model. Conditioned on a peak instead of
any starting point, the median large cap is at 0.95 times its old real peak ten years on.
Gilead, the one prior organic breakout of Lilly's shape, went 2.9 times in two years on
hepatitis C and then fell 4.0% a year for a decade to 0.66 times its peak. The sample is
survivors, so the measured growth is biased up and the true organic figure is at or below
zero. Full working in `docs/perpetuity.md`.

**And the framing below needs correcting.** The ceiling is not the binding constraint on
the disagreement with the market at the launch rate actually measured. Sweeping the cap
from 0.0% to +4.0% real moves Lilly by 38 cents, from $523.51 to $523.13, because the
launches never reach the ceiling at 0.4026 and where it sits is irrelevant. It costs
0.04%. The ceiling is what makes the value asymptote near $315bn when launch productivity
is swept to 3.00, and that is a different statement. The book is 62% below the price
before the cap binds at all, so the gap is not in this line. Finding where it is, is now
the open question.

### 1b. The original framing, kept for the record

This is the whole gap. The book values a portfolio to its patent cliffs and adds one
`future` line for launches beyond the modelled pipeline ($206bn for Lilly). The market
pays closer to $700bn for the same engine. Neither side is obviously right and the book
currently asserts its side silently.

What to do, in order:

- Read `_future_pipeline` against what it is standing in for. It is the book's answer to
  the perpetuity and it has never been tested against realised launch economics.
- Decide whether it is a floor or an estimate, and say which on the page. A floor that
  reads as an estimate is the thing that makes every large-cap look cheap to nobody and
  dear to the market.
- Consider publishing the implied terminal multiple beside the sum, so a reader can see
  the book is paying 2.45× final-year cash flow where a flat perpetuity is 11.9× and the
  market is near 30×. That one line would make the disagreement explicit instead of
  structural.

Do not "fix" this by raising terminal growth to match the market. The architecture is the
more honest one; what it lacks is the disclosure that it is a choice.

### 2. Let the backtest accrue, then read it

`valuation_history` now records one call per company per price date, refusals included
with their reasons, and `/valuation-backtest` reads them against forward abnormal returns
bucketed by the call. It will say "not enough history" for months and should.

- **3 months:** first readable 1-month window. Expect noise.
- **6 months:** 3-month window worth reading.
- **12 months:** the window that answers the question.

Until then no conclusion about the book being too low is available, and claiming one
would be the same error as the deck's.

### 3. Work the coverage board down

`/completeness`, and the Coverage view on the Universe tab. Today: 54 complete,
7 partial, 6 with nothing they sell modelled, 8 refused, **$8,322mm carried at nothing**.

Sorted by revenue carried at nothing, which is the order to work in:

| | | |
|---|---|---|
| BMRN | $2,924mm | 5 products, none modelled |
| NBIX | $2,815mm | Ingrezza, Crenessity |
| LNTH | $1,458mm | Pylarify, Definity, Techne Lite, Neuraceq |
| IOVA | $264mm | Amtagvi, Proleukin |

A company needs most of its products done or none: one model out of five re-creates the
exact problem the refusal exists to prevent.

Three products stay refused on purpose — Niktimvo, Aucatzyl and PENMENVY each carry
`# NOT YET VALUABLE: revenue_growth_pct is left out`. Supplying that number overwrites a
decision someone made. Leave them until there is a published peak to solve to.

### 4. Keep guidance fresh, because it is the anchor that moves

`guidance.extract()` runs inside the refresh and reads the earnings releases already in
`filing_sections`. It had not run here because a refresh died partway, and Lilly's
guidance sat at $86.0bn from August while the company was guiding $91.5bn. One run caught
up 7 figures across the book.

The coverage board now reports guidance older than 135 days as stale. Watch that column:
one stale row today, and a quarter is when a raise or a cut has already happened.

### 5. The lesson that generalises

Four separate things in this audit looked like defects and were a **stale local book**:
the duplicate asset rows, the unloaded aliases, the unloaded seeds, and the stale
guidance. Every one of them was fixed by running a pass the refresh already runs.

Before calling anything here a defect, run:

```
programme_alias.load_curated  →  asset_merge.merge  →  assumptions.load_seeds
other_claims.store            →  guidance.extract
```

A partial refresh leaves the book looking broken in ways that are not real.

## What is deliberately not on this list

- **Raising terminal growth to match the market.** That is fitting the answer.
- **Modelling the 21 remaining products quickly.** Most carry one year of revenue, so the
  growth rate would be invented. The house convention refuses, and it is right to.
- **A beat-and-raise guidance convention.** Proposed on the wrong diagnosis and withdrawn:
  the book anchors on reported revenue with per-product growth, not on guidance midpoints.
  Only one seed used a midpoint, and it has been corrected to the current figure.
