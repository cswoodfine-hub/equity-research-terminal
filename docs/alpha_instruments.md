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

## Credibility, 2026-11-07: three things that turn instruments into a record

Instruments with no track record are not credible, however good the calls. These three
are what make the calls scorable.

### Catalysts resolve (`catalyst_outcomes`, `/catalyst-resolutions`)

Every one of the 814 catalysts on file was pending, and not because none had happened.
`derive_readouts` deletes a derived readout once its date passes; a PDUFA row stays
pending for ever; nothing read the approvals table or the announced readouts back
against the calendar. Zilganersen was approved on 2026-09-03 under NDA220210 and its
PDUFA, due 2026-09-22, was still pending. So `call_log` had scored no gate and the Brier
calibration had never run.

The resolver runs inside the refresh before the derivation that would delete the
evidence, with four outcomes and a stated rule for each: met or missed from an approval
row or an announced result dated inside the window; slipped where a PDUFA was superseded
by a later row (deramiocel's three rows for 2026-08-22, extended to 2026-11-22) or the
registry moved a readout's date, in which case the slip is logged and the row stays
pending because `derive_readouts` updates it in place; unknown where a window closed 45
days ago with nothing found, kept rather than deleted. A regulatory catalyst with no
approval is never missed, because there is no free register of complete response
letters. The resolution is dated by the market's event, which is what `call_log` reads.

**The first dry run was wrong, and reading the announcement properly is the finding.**
An announced readout carries no trial id and is matched on company, drug and phase. GSK
had two pending Jemperli Phase 2 readouts and Novartis six pending Rhapsido Phase 3s, and
one announcement fitted all of them; the unguarded resolver picked one. The fix is to
read the announcement itself, in three tiers. First the NCT numbers it names: a named
trial that is a pending catalyst resolves, and where the release names several they all
do, because Phase 3 programmes run as twins and report as one result. Named trials that
are no catalyst at all mean the announcement is about something else, logged as
*elsewhere*. Then the registry's own words for each sibling, its conditions, MeSH terms
and primary outcome, against the text: GSK's says dMMR/MSI-H rectal cancer and cCR12,
which of its three Jemperli studies (rectal, lung, head and neck) fits only AZUR-1, and
that one resolves met. Where no body is stored the press release is fetched once from
its SEC URL and cached. A word two siblings share cannot tell them apart, so any word in
more than one sibling is dropped, and what is left is weighted by how rare it is across
the whole register. Only words that fit every sibling alike leave a readout ambiguous.
One announcement is one result: once it has closed a catalyst or been read and found to
fit none, it is spent, and the sibling left pending after twins were named cannot take
it as its own.

**The register gap, found 2026-11-07 and closed 2026-11-08.** Novartis's release named
NCT05147220 and NCT05156281, REMODEL-1 and -2, and the resolver logged it *elsewhere*
because neither was a catalyst. Both were in `trials` all along, at a July 2026
completion. The calendar had dropped them: `derive_readouts` began at today and withdrew
a derived row the day after its date passed, so a trial that had completed before the
book first looked never became a catalyst, and one that completed in the book's sight
was deleted before its result could be matched to it. The resolver's 45-day grace never
ran in production. The derivation now reads two years back as well as forward, as far
back as the labelled announcements go (`trial_readouts` holds them from 2024), and keeps
a past-dated row pending until the resolver closes it. No view of what is coming shows
such a row, since every one filters on the date; the resolver and the backtest are what
read them. The pipeline fetch never deletes, so a trial that completes on the registry
keeps its last live status and its final date, which is what makes it visible at all;
"Completed" is admitted too, so a fetch that ever records it makes a readout rather than
a withdrawal. Unknown is the one resolution that is not an observation, so a row closed
unknown whose registry date later moves ahead reopens as pending at the new date; met
and missed never do.

On a copy of the book on 2026-11-08 the lookback admits 337 past readouts (261 Phase 3)
and the resolver closes 10 met, 3 slipped and 265 unknown, with 5 ambiguous and 68 still
inside their grace. The met rows are ulixacaltamide (PRAX), aleniglipron (GPCR),
tozorakimab and Tezspire (AZN), venglustat (SNY), REMODEL-1 and -2 (NVS, both on the one
release), AZUR-1 (GSK) and the two approvals already on the ledger. No fair value moves, and
none should: the position model had already read every one of these announcements from
the labelled register by drug name, and on the live book `pos_granular.stage_of` gives
ulixacaltamide, venglustat and remibrutinib as "positive, NDA to approval" citing the
same accessions the resolver does, while the seeded probabilities carry the readouts
too. The stage is identical on both databases. What the resolution adds is the record
pinned to its trial and dated by the market, which is what the scoreboard reads. Of the 265 unknown, 171 have a filing by the company
inside the window that the reader had on file as stating no result, and the ledger names
those filings on each such row.

**The reader, not the labelling, was the next constraint.** A `trial_readouts` row that
says "none" is a filing the extractor read and found no Phase 2 or 3 result in. 1,287 of
the 1,359 rows say so, and 251 of them were read from a cover under 6,000 characters
with no result language; for 52 of those the exhibit already on file carries one. The
first reader followed an 8-K to its EX-99 exhibit only when the cover lacked the cheap
hint, never followed a 6-K at all, and an 8-K whose cover said "Phase 3" in its item
line passed the hint and was read as if the cover were the release. Those rows were
"did not look", recorded as "no result". Fixed 2026-11-08 in three parts. `readout_text`
follows either form to its exhibit whenever the primary is short or states no result,
and joins the two rather than swapping them so a drug named only on the cover still
validates. `trial_readouts.reread` reads each such row once more through the same
classifier and the same validation, the drug and the quoted sentence still required in
the text the model read, stamps the row whatever it finds, and takes first the rows a
catalyst closed unknown or pending past its date is waiting on. And the resolver lets a
result labelled later overturn an unknown to met or missed, on the announced tier only;
the unknown stays on the ledger beside it. In production the reading runs on the model
the refresh has a key for, which today is Groq's Llama 3.3 70B; the Gemini key is local
only.

Measured on a copy of the book on 2026-11-08, with Gemini. The queue of "none" rows a
catalyst was waiting on was 503 filings; the second reading took 13 minutes, labelled
15 of them (14 positive, 1 negative), 10 of the 15 from text found only in the exhibit,
and a guard added the same afternoon took three of the 15 back: a sentence that reports
a result as already known, "as previously reported", "the designation is based on data
from", is a restatement dated to the wrong filing and can settle a sibling the original
already settled. Of the 12 that stand, one overturns an unknown: argenx's Vyvgart
Hytrulo readout, due 2026-01-12, closed unknown and is met on the 2026-02-26 ADAPT
OCULUS release, which the registry's words ("ocular", "myasthenia", "gravis") fit to
NCT06558279 alone among six Vyvgart studies. The other eleven are results for trials the
register never held as catalysts, Phase 2 cohorts and studies under another sponsor, or
for catalysts already met. So the reader fault was real and the yield on the scoreboard
is small: the 265 unknowns are mostly trials whose result was not announced in a filing
inside the window at all. The constraint that remains is the announcement register's
reach, not the reader.

The copy also exposed three faults in the resolver's second pass, each fixed with a
test. The sibling set was pending rows only, so an unknown row was judged against its
future siblings and not itself, and the first version closed a 2027 Phase 2 Vyvgart study
met on a 2025 Phase 3 CIDP release. The sibling phase was read off the trial's registry
title, which rarely states one, rather than the catalyst's own, which is why that Phase 2
was a sibling of a Phase 3 result at all. And a release judged ambiguous ended the row's
turn, so the February release that was the argenx row's own was never read when the
October one came first; an ambiguous release is now recorded and passed over. On the
second pass only the row under test may win: a release that fits a pending sibling better
is that sibling's to take on its own turn.

### The register widened beyond the SEC (`press_readouts`, `registry_readouts`)

The announced results were read from 8-K and 6-K filings alone, and that was the
ceiling. Roche and Bayer file neither; Roche alone carried 30 of the 271 readouts that
fell due in the last two years. AstraZeneca, with the most unresolved readouts of all,
publishes every result on its own site and furnishes a 6-K late or not at all; 438
investor-relations releases already in the news table had a result in their title and
none had been read as a readout. And a trial stopped for futility is the result the
filings least often carry: ten negatives on file against sixty-two positives.

Two readers, built 2026-11-08. `press_readouts` reads the companies' own releases from
the news table, those whose title states a result, through the same classifier and the
same validation as the filings; a release that restates a result already labelled from a
filing, the same company, drug and phase within ten days, is kept as a duplicate and is
never a second event. The page is fetched with the browser-shaped agent the feed fetcher
uses and, where a site refuses, through the Jina reader the press-page fetcher already
depends on. `registry_readouts` asks ClinicalTrials.gov by NCT id about every derived
readout that has fallen due: a termination whose stated reason is futility or lack of
efficacy is a negative pinned to its trial, with the registry's sentence as the quote; a
stop for enrolment or a sponsor decision is not a result and only brings the trial's
status up to date; a date that moved is written to the trial so the slip tier sees it.
Each row carries its source and, where the source states it, the trial's NCT, and a
result pinned to its trial resolves that catalyst with no matching on drug or phase. A
registry-dated resolution follows the event by weeks, so for those the gate scoring
counts a call as a prediction only if it was made before the trial's own due date.

Measured on a copy on 2026-11-08. The registry answered for all 348 due readouts in
13 seconds: 2 futility stops (a GSK Phase 2, Ultragenyx's Phase 3), 10 stops for other
reasons, and 78 trials whose status or date had moved, which surfaced 12 slips the book
had not seen. The press reader took 217 releases in 13 minutes and labelled 125; a
restatement guard took back 10, the conference presentation and the journal publication
of a result announced earlier, leaving 115, 98 positive and 17 negative, with 16
duplicates of filings. Negatives on file went from 10 to 29. Of the readouts that fell
due in the last two years, 16 are now met and 4 missed, against 10 and 0 before; 11 of
the met and 2 of the missed come from press releases, 2 missed from the registry. 251
remain unknown and 18 readings are ambiguous, 10 of them AstraZeneca releases that fit
several AstraZeneca studies alike.

The run exposed two more rules that were wrong, each fixed with a test. The twin rule
let a release naming several studies resolve all of them; AstraZeneca's Saphnelo release
named five, due between 2025 and 2028, and all five closed met. Twins are now at most two
studies due within ninety days of each other, and otherwise only the named study whose
window held the release resolves. And a press row's body was fetched through the EDGAR
path with the EDGAR agent, which astrazeneca.com refuses, so the tie-break read the
quoted sentence alone; it now fetches the way the press reader does.

What is left is not the register. The 251 unknowns are now mostly trials whose result
was announced nowhere the book can read for free, or not at all, or whose release fits
several of a company's studies alike. Calibration still reads nil, correctly: no
resolved readout has a gate call on file, because every resolution predates the first
gate call on 2026-10-08. Ivonescimab on 11-14 and deramiocel on
11-22 will be the first scored gates. The ledger travels in git.

### One benchmark (`benchmark_series`)

Four modules measured against three things: `backtest` and `valuation_history` against
the book's own universe, `call_log.score` against PPH, `event_signal` against XBI. All
four now read XBI through one module, with the universe only as a stated fallback where
XBI's series does not reach. XBI and IBB were never in the benchmark fetcher and had
stopped at 2026-10-07; they are in it now and current.

### The book against the street (`street`, `/street`)

Agreement, not accuracy. Of 71 companies with a consensus target, 32 are readable (three
or more analysts, a same-day call). Thirteen have book and street both above the price,
three both below, and **sixteen have the book below the price and the street above it**.
The book never stands above the street alone. Median gap of book to street mid: −21.9%.
The sixteen include Lilly (book $474.50, street $1,396.75, 22 analysts), Viking, Praxis,
NewAmsterdam and Capricor, which are the gate-odds names. Accuracy is `call_log.score`'s
question and its first scorable horizon closes 2026-11-07.
