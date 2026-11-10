# Where the gap actually is

Measured 2026-11-07. Written after the perpetuity question was settled and the ceiling
turned out to be worth 38 cents, which left the audit pointing at a line that explains
nothing and the real question open.

**There is no systematic gap. There is one disagreement, about one company, and the
book's side of it is the side with the evidence.**

## There is no general bias

The audit started from the premise that this book reads low against the market. Across
the sixteen large caps it does not:

| | | | | |
|---|---|---|---|---|
| BMY +62.0% | GSK +55.3% | NVO +33.0% | REGN +31.8% | INCY +29.7% |
| MRK +24.5% | NVS +11.3% | AZN +4.1% | BIIB +2.9% | AMGN −7.8% |
| GILD −14.7% | PFE −18.6% | ABBV −23.2% | JNJ −25.6% | ROG −52.1% |
| **LLY −61.9%** | | | | |

Median **+3.5%**, nine above the price and seven below. Excluding Lilly, +4.1%. Across
all 47 companies the book priced on its last recorded date the median is −8.7%, twenty
above and twenty-seven below, p10 −52% and p90 +118%.

A book centred on the market that disagrees hard in both directions is taking positions,
not carrying a bias. Lilly is one of those positions, and the question is whether it is
the right one, not what is broken.

## What Lilly's gap is not

$850.19 a share, which is $764,572mm of enterprise value. Four candidates are ruled out
by measurement rather than by argument.

**Not the revenue forecast.** Modelled revenue for the guided year is $90,241mm against
guidance of $91,500mm, a gap of 1.4%. Matching it exactly moves equity from $523.51 to
$525.95. **The revenue level explains $2.44 of $850.19.**

**Not the revenue ceiling.** Sweeping `future_pipeline.room()` from nil real growth to
4% moves the valuation 38 cents, and downward. It caps away 0.04%. See
`docs/perpetuity.md`.

**Not conservative peak sales.** The book has Mounjaro peaking at $72,000mm and Zepbound
at $37,680mm, so $110bn for tirzepatide alone, plus orforglipron (Foundayo) at $18,000mm
and retatrutide at $18,234mm. That is about $146bn of peak GLP-1 revenue, which is close
to the whole global market anyone forecasts, handed to one company. Nothing here is shy.

**Not a missing asset.** Every Lilly programme that matters is modelled: 12 marketed
products and 24 pipeline assets, orforglipron among them as a newly approved product.
Nothing the company sells is carried at nothing.

## What it would take

`breakpoints.company` solves every assumption for the value at which the book meets the
price, running the real engine each time. **Forty-five of fifty-one levers cannot reach
the price at any value inside their bounds.** Among the ones that cannot:

| lever | pushed to | still short |
|---|---|---|
| Mounjaro's discount rate | 2.0%, the floor | yes |
| Mounjaro's LOE | 2066, forty years out | yes |
| Mounjaro's year-one erosion | 0%, no generic at all | yes |
| Mounjaro's peak uptake | its bound | yes |

Setting Mounjaro's patent cliff forty years away *and* giving it no generic erosion at
all still does not reach $1,373.70.

Six levers do reach it, and each says the same thing in a different unit:

- **the growth fade at 9.8 years against the modelled 5.8**, which takes Mounjaro to
  **$369,777mm at peak against $72,000mm**, roughly five times the book and several
  times the global GLP-1 market;
- every revenue ceiling in the company at **14.73 times** its modelled peak;
- Taltz growing at **177.72%** a year against 9.29%.

None of those is an assumption anyone would defend. The price is not reachable by moving
one thing the book got wrong, because there is no one thing.

## The gap in a single number

Lilly's book peaks at $175,431mm of revenue in 2031 on a 24.0% after-tax margin, so
$42,103mm of free cash flow, five years out, at the book's own 7.75% WACC:

| | enterprise value | times peak free cash flow | implied perpetual growth | real |
|---|---:|---:|---:|---:|
| the book | $515,414mm | 12.2 | 2.12% | **−0.23%** |
| the market | $1,279,986mm | 30.4 | 5.48% | **+3.13%** |

A flat perpetuity at the book's own discount rate would be 12.9 times. **So the whole
apparatus, twenty-year product forecasts, patent cliffs, erosion to nothing and a
$206bn future pipeline line, nets out to almost exactly a zero-real-growth perpetuity
on peak cash flow.** That is the book's real claim, and it has never been stated in one
number before.

The price requires **3.13% real growth, for ever.**

Measured organic ten-year real revenue growth for US large-cap pharma, 2007 to 2025,
once purchases are held out: **−0.02%** (`docs/perpetuity.md`). The book is calibrated to
the historical record to within a quarter of a point. The market is three points above it.

## So what

The gap is a disagreement about one rate, held in perpetuity, on one company. Nothing in
the book is broken, and nothing here should be changed to close it. Changing it would be
fitting to a price, which is the error the student's deck made: that deck put roughly 90%
of its value in a 3.0 to 3.5% terminal growth at a 6.80% WACC, a ~30 times terminal
multiple, which is the market's 30.4 times read back.

Two things follow.

**Publish the implied growth beside the sum.** The book's claim is a number, −0.23% real
in perpetuity, and a reader cannot see it anywhere today. The action plan proposed this
as "the implied terminal multiple beside the sum" and it is now measurable for every
company. That one line turns a structural disagreement into an explicit one.

**Let the backtest settle it.** This is exactly the question `valuation_history` was
built to answer, and it cannot be answered by more analysis today. Lilly is one name in
one direction over one period, which is all the student's deck ever was.

## What was ruled out along the way

- The ceiling in `future_pipeline.room()`: worth 38 cents, and correct on the evidence.
- The revenue forecast: 1.4% from guidance, worth $2.44.
- Every individual product assumption: 45 of 51 cannot reach the price at any value.
