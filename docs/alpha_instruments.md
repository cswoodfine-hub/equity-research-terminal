# Five instruments for the smaller names

Built 2026-11-07, from the question of how to get more out of the small biotechs. Every
figure here is computed from the book; nothing is estimated.

## What the book's own backtest said first

The market front-runs readouts almost completely. Around the 72 labelled readouts in
`trial_readouts`, measured by `backtest` and re-measured here against XBI, since the
module itself still benchmarks against the book's own universe (item 1 says why that
matters):

| | run-up 3mo | run-up 1wk | after 1 day |
|---|---:|---:|---:|
| Phase 3 positive (n=49) | +19.0% | +17.2% | +0.3% |
| Phase 3 negative (n=9) | −32.9% | −13.8% | −3.6% |
| New approval (n=30) | −13.1% | −1.7% | +0.4% |

The figures barely move between the two benchmarks, which is the test the finding had to
pass. By the time the data prints the move has happened. So none of what follows trades the
event. Each asks a different question of the months before it.

## 1. What precedes a move (`event_signal`, `/event-signal`)

`backtest` measures around a real event date and, rightly, leaves out the changes that
carry only a detection time. This measures those forward from the day the book recorded
them, which is the day it could first have acted. The feed's stamps stand up to that:
across the filings it records, a change is detected a mean of 1.37 days after the filing
date and never more than eight.

**It found the benchmark was wrong before it found anything else.** Against the
equal-weight return of the book's own universe, every one of fifteen change types read
positive and the busiest read +3.1% a month at a 64% hit rate. A book of biotech is
dragged by whatever is collapsing inside it, so its own mean is a benchmark almost
anything beats: a random company-day beats it 45% of the time on the mean and loses on
the median. Against XBI, the equal-weight biotech ETF stored since 2016, the same three
types read −0.1%, −0.7% and −1.9%. The effect was the benchmark.

So the benchmark is XBI, the placebo is drawn on the event days themselves at the
frequency they occur, and the count that governs is distinct company-months rather than
events, because two events on one company a week apart share almost all of their forward
window. The change feed starts 2026-07-18, one quarter across 72 companies, and the view
reports not enough history. It accrues.

## 2. The odds the price pays for (`gate_odds`, `/gate-odds`)

For every priced gate, every day, `call_log` already records what the asset is worth per
share if the gate passes, if it fails, and today. Those and the price turn the question
round: not what the company is worth but what probability of passing the price pays
for.

**The obvious inversion is wrong, and it was tried.** The legs are the asset's own
contribution, not the company's conditional value. Retatrutide swings 4.6% of Lilly;
dividing Lilly's gap to the price by that leg reads thirty-seven. So the rest of the
company comes out first, from the same day's `model_calls`, and a gate is reported only
where its swing is a fifth or more of the book's value. That is ten gates on eight
companies, the ones where one readout is the company: Viking's VK2735 swings 148% of
Viking.

**The answer comes in three regimes, and the regime is the finding.**

| | book p | market p | regime |
|---|---:|---:|---|
| QURE AMT-130 | 0.94 | 0.24 | odds (due 2026-11-01, passed) |
| DYN zeleciment basivarsen | 0.53 | 0.61 | odds |
| VKTX VK2735 | 0.64 | 0.75 | odds |
| NAMS obicetrapib | 0.55 | 1.84 | payoff above success |
| PRAX ulixacaltamide | 0.87 | 2.41 | payoff above success |
| STOK zorevunersen | 0.53 | 6.54 | payoff above success |

An implied probability inside [0, 1] is a disagreement about odds, which the readout
settles. Above one, the price exceeds the asset's full-success value plus the rest of
the company: the market disagrees about the payoff, and the readout cannot settle that.
Of ten, three are about odds and six about payoff. "The market pays 184%" is not a
mispriced coin.

Whether the book's odds beat the market's is what `call_log.score` measures as calls
resolve.

## 3. Where the borrowed numbers came from (`comparator_link`, `/comparator-links`)

A small biotech's value turns on three rows, and all three are borrowed: price and peak
uptake graded analogue name a marketed comparator in prose and nowhere else. This reads
the prose into a link, taking it only where the source says it borrowed (the grader's
analogue rule also fires on "workbook", which borrows nothing), and resolving a brand
against the names the book holds rather than inferring one.

284 links across 154 pipeline assets to 126 comparators; 29 rows unresolved, correctly,
because they name a class or a seed file. 252 links have a CMS series behind the
comparator, and 22 have already moved: Leqvio's beneficiaries are up 612% and its
spending per beneficiary 46% since the 2022 figure that Olpasiran's and Lepodisiran's
uptake were taken from. CMS lands a year late, so the drift is annual with a lag; the
link is the part worth having today.

## 4. Funded to the readout (`runway`, two defects fixed)

This already existed: `runway.py` computes runway, cash-out, the next gate and
`funded_to_readout`, against a calibrated dilution table. It had two defects, both from
comparing dates as strings. A quarter of the register's dates are a month, and "2026-11"
sorts before "2026-11-07", so a readout due this month fell out of the runway list as if
it were past; and "2027-12" compared against a cash-out as if it were the first of
December, which made the sign test optimistic by up to thirty days. A date is now a
window, and the sign test reads the window's last day. CABA flips to unfunded; SANA holds
by a month, inside a month-precision date's error.

## 5. When the book is forced to reprice (`refusal_calendar`, `/refusal-calendar`)

Nine products are refused rather than modelled, each in a seed file with no rows and a
line beginning "What would settle it". The condition is kept verbatim and dated only
where it names a reporting year, to the window that year's annual report lands in. Three
are dated, all to the first quarter of 2027; five are conditions without a date; one, a
divestiture, nothing will settle.

## What was ruled out

Trading the readout, which the run-up table settles. The rNPV level on a pre-revenue
name, which is twenty-six rows where three carry the answer and all three are borrowed.
And, after one afternoon, the first version of item 1, which the benchmark had made up.
