# Does a company exceed its own peak?

Measured 2026-11-07 against the filings on file. Every figure here is computed.

This settles the open judgement left by the valuation audit (`docs/ACTION_PLAN.md`,
item 1): whether a book that can never exceed its own peak is the right model of a
company that went from $34bn in 2023 to a guided $91.5bn in 2026.

**The answer is to keep the cap.** The organic record says large-cap pharma revenue has
not grown in real terms at all, and the one company in the sample that broke out before
gave a third of it back within a decade.

## What the cap claims

`future_pipeline.room()` holds a company plus its launches to the book's own best
modelled year in real terms, grown from it at expected inflation. The claim is
replacement, not growth: products fade and lose exclusivity, launches refill what
erodes, and a company that only refills keeps its real size rather than its nominal one.

So the testable statement is: **real revenue does not exceed its own prior peak.**

## How it was measured

FY `Revenues` from `financials`, 2007 to 2025, each company in its own reporting
currency so no exchange rate enters a growth rate. Deflated by the US CPI annual average
(FRED CPIAUCSL, free and keyless, the same host the discount rates already read).
Inflation over the window ran at 2.47% a year against the 2.35% the book assumes, so
the deflator and the cap's own rate agree to about a tenth of a point.

39 USD reporters carry ten years or more. Nine have a ten-year window starting above
$25bn, which is the size the question is about.

A purchase is not a launch. The future pipeline line values launches bought by the
company's own R&D; an acquisition is capital allocation, and the book values what it
buys separately when it arrives. So windows containing a purchase are held out. Size of
jump does not identify one, so each step year was classified by what actually caused it:

| | | |
|---|---|---|
| MRK 2010, +65% | bought | Schering-Plough, $41bn, closed Nov 2009 |
| BMY 2020, +61% | bought | Celgene, $74bn, closed Nov 2019 |
| ABBV 2020, +36% | bought | Allergan, $63bn, closed May 2020 |
| AZN 2021, +34% | bought | Alexion, $39bn, closed Jul 2021 |
| GILD 2015, +31% | launched | Harvoni and Sovaldi, the hepatitis C ramp |
| LLY 2024, +28% and 2025, +41% | launched | Mounjaro and Zepbound |

Classifying on the size of the jump alone would have thrown out Gilead's and Lilly's
breakouts, which are the organic events the question is about, and biased the answer
toward the cap.

## The result

Ten-year real revenue growth, start above $25bn:

| | companies | windows | pooled median | p25 | p75 |
|---|---:|---:|---:|---:|---:|
| every window | 9 | 42 | **+1.00%** | −0.91% | +3.44% |
| purchases held out | 7 | 32 | **−0.02%** | −1.00% | +1.38% |

One observation per company rather than per window moves it to +0.05%.

**Organic real growth is zero.** The whole of the +1.00% in the first row is bought.

Conditioning on a peak rather than any starting point says the same thing more
sharply. Of the seven US large caps whose real peak came by 2015, three exceeded it by
2025 and the median was **0.95 times** the old peak, a real rate of −0.40% a year. Of
the three that exceeded, Bristol did it by buying Celgene and Amgen substantially by
buying Horizon. One did it organically, and it is Lilly.

Two of the seven need a caveat said out loud. Johnson & Johnson's 0.93 includes the
Kenvue separation in 2023, which took consumer health out of the company: that is a
divestiture, not a decline, and the ratio understates what it kept. Amgen's 1.25 is
substantially Horizon Therapeutics, $28bn in 2023, which no single year flags as a step
because Amgen was already large enough to absorb it. The first reads against the cap and
the second for it, and neither is large enough to move the median.

## The breakout that did not hold

Gilead is the case closest in shape to Lilly's, and it is the reason to keep the cap
rather than loosen it. Real revenue, 2025 dollars:

```
         2013   2014   2015   2016   2017   2018  ...  2023   2024   2025
GILD      15     34     44     41     34     28         29     30     29
BIIB      10     13     15     15     16     17         10     10     10
LLY       32     27     27     28     26     28         36     46     65
```

Hepatitis C took Gilead from $15bn to $44bn in two years, a 2.9 times organic breakout.
It then fell every year for a decade to $29bn, **0.66 times its peak, −4.0% a year**. It
has not approached that level since. Biogen compounded steadily to $18.1bn in 2019 and
is at $9.9bn, 0.55 times its peak.

Lilly's own history is the same shape before the current ramp: a real peak of $34.8bn in
2011, then eleven consecutive years below it, passed again only in 2023.

No company in the sample has had two breakouts. The cap refuses a second one on top of a
first that the modelled book already contains, since Lilly's book peaks at $175bn in
2031 against $65bn of actual 2025 revenue. What is being refused is not the GLP-1 ramp.
It is another ramp of the same size after it.

## The bias runs toward the cap, not against it

The sample is the companies in the universe today. Firms that shrank into an acquisition
are absent, and they are the losers: Schering-Plough, Celgene, Allergan and Alexion
appear here only as the purchases that lifted somebody else's revenue. Their own records
end. So the measured organic growth is biased upward and the true figure is at or below
zero. A survivor-weighted measurement that lands on zero is not an argument for
loosening a conservative assumption.

## What the cap is actually worth

It is worth almost nothing, which is the part of the audit's framing that needs
correcting. Lilly, launch productivity at its measured 0.4026, close $1,373.70:

| cap grows at | real | future line | equity per share | capped away |
|---|---|---:|---:|---:|
| 2.35%, today | 0.0% | $205,681mm | **$523.51** | 0.04% |
| 3.35% | +1.0% | $205,357mm | $523.13 | 0.00% |
| 6.35% | +4.0% | $205,357mm | $523.13 | 0.00% |

Loosening the ceiling by four points of real growth moves the valuation by 38 cents, and
downward. The launches never reach the ceiling at the measured launch rate, so where it
sits does not matter. The small decrease is the peak-year sensitivity `room()` already
documents: at 6.35% the anchor year moves from 2031 to 2030 and the peak it grows from
falls from $175,431mm to $169,830mm, because "best in real terms" deflates later years
harder.

The audit called the ceiling "the binding constraint on the whole disagreement with the
market". That is true only above the measured launch rate. The ceiling is what makes the
value asymptote near $315bn when launch productivity is swept to 3.00, and it explains
why no launch rate reaches the price. At the rate actually measured it costs 0.04%, and
the book is already 62% below the price before it binds at all. The disagreement with
the market is not in this line.

## The decision

**Keep the cap at expected inflation.** It is not a conservative convention chosen for
safety; it is what the filings show, to within a rounding error, once purchases are held
out and organic breakouts are kept in.

Two things to keep saying out loud, since the cap is now published on the sum as
`future.cap`:

- **It describes the median and refuses the tail.** Breakouts happen. Gilead had one and
  Lilly is having one. A book capped at its own peak will read cheap to a market pricing
  the chance of another, and that is a choice rather than an error.
- **Eighteen years is one patent-cliff cycle, not a long-run law.** It happens to be the
  relevant cycle, covering Lipitor through to the GLP-1 era, but the sample is seven
  companies and the filings on file do not reach further back.

## What this does not settle

If the ceiling costs 0.04% and the book is 62% below the price, the gap is somewhere
else. The next question is where, and it is not this one.
