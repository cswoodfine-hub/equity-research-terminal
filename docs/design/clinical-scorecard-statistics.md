# Clinical scorecard: the statistics underneath, method specification

Status: specification, revision 2, ready to build. Written 2026-09-30 and revised the same day
after two reviews, a biostatistician's and an analyst's. Their 39 findings are answered one by
one in appendix A. Every figure quoted was measured on a backup of the live book taken
2026-09-30 14:58 (`book_r3.db`), read only. The prototype that produced the figures is listed
in section 10.

This document is the contract for one change: the Clinical scorecard at the top of Comps,
Indications, Overview keeps its one chart, its ranked table and its sentences, and the numbers
under them are computed properly. A drug's trials are averaged into one effect with an
interval. Drugs are compared on size only where they were tested against the same control.
A result on one small trial carries the spread a second trial could show. The win rate allows
for the number of tests run. Safety is averaged trial by trial against the control of each
trial. The rank carries a range.

Nothing else changes. No new table, no schema change, no fetcher, no data source, no tab. The
only data read is the trial result data the book already holds. Where a method needs a number a
sponsor did not post, the method is not applied to that result and the words on screen say what
was done instead.

Where this document names a value, a string, a threshold or a field, that is the value.

**What revision 2 changed, in one paragraph.** Revision 1 pooled each drug's trials on their
own (so a one-trial drug looked more certain than a six-trial one), ranked every
placebo-controlled drug "through placebo" whatever the placebo was added to, borrowed strength
from every drug on a measure, combined test statistics in a way that grew with the number of
trials, stood a ratio of medians in for a hazard ratio nobody posted, gave a drug with no
comparable peer a size of 50, and put an interval on every score. The reviews showed each of
these either ran backwards on the book or claimed more than the book holds. Revision 2 is
simpler almost everywhere: one spread between trials per measure, comparison only against the
same control and only where that spread is measured on enough trials, shrinkage only inside a
mechanism class, the average trial result for strength, a posted hazard ratio or nothing for
survival, no invented size, and one range, on the rank. In the six indications that means
drugs are compared on size in obesity and type 2 diabetes, where the book holds enough
placebo-controlled trials to do it, and nowhere in oncology, arthritis or myeloma, where it
does not. Those drugs are scored on strength and wins, as the scorecard scores them today.

---

## 0. Decisions

| # | Decision | Rule | Why, in one line |
|---|---|---|---|
| 1 | Whose result it is | A result is a drug's only where an arm's title names the drug (a filed name, its compound name, either without a salt word, a biologic's name without its FDA suffix where no biosimilar's reference holds it), or its description names it as the arm's own treatment, and the comparator arm does not, by its full name or a shortened one ("Pembro + Placebo"). A combination is named only by its own name or every component. An arm whose title adds another candidate the control lacks is not the drug's alone. No fallback to unnamed arms; a result with no control arm is counted as unscored. | 8 results had the drug in both arms (6 in type 2 diabetes, 2 in lung); 17 trials were read from another drug's arms. |
| 2 | Direction of benefit | A measure family fixes its own direction. A count of people with an event is lower-is-better whatever survival word its title holds. A time to an event is longer-is-better (shorter for a good event); an instrument fixes its own (SPID, KCCQ, FEV1 higher; SGRQ, DLQI lower); a count of people is higher-is-better only with a responder word and lower-is-better with a harm. Then the title. | One mis-signed Phase 2 trial put tirzepatide 8th of 15 on HbA1c in revision 1. |
| 3 | Several dose arms | Tested on all arms together (the unbiased test of "any dose works"). Sized on the most effective arm less what picking the best of k arms adds by chance. | Averaging doses took 2.6 points of real dose response off SURMOUNT-1 to remove at most 0.5 of selection. |
| 4 | Standard error | From the sponsor's interval first, then the arms' own spread or counts, a p-value last. An interval must bracket its estimate near its middle. | The book does not store whether a test was for superiority or non-inferiority. An interval is safe either way; a p-value is not. |
| 5 | Time-to-event measures | Survival and every other time to an event ("time to first exacerbation", "time from randomization to a bipolar event") are read from a posted hazard ratio, with its interval or failing that its p-value, and from nothing else. | Medians mislead when curves cross: IPASS reads 1.02 from its medians where the posted hazard ratio is 0.74. |
| 6 | Averaging a drug's trials | Inverse variance with one between-trial variance per measure, estimated from every drug with two or more trials on it and carried by a one-trial drug too. | Drug by drug, a one-trial drug had no between-trial variance and looked the most certain on the chart. |
| 7 | Strength | The mean of the trial z-scores, one z per trial, as a share of 3.29, moved toward the mean of every drug in the indication by how little the drug's own trials say. | A combined z grows with the number of trials, which weight of evidence already scores. |
| 8 | Wins | Benjamini-Hochberg within each trial on one-sided p, a win at 0.025. Scored as the mean over trials of the share of that trial's endpoints won, moved toward the drugs' mean as strength is. A non-inferiority result counts only where it shows the drug better. | A result against the drug must not loosen the bar for its wins; each trial controls its own error rate; one trial must not supply most of the endpoints. |
| 9 | Size against peers | The mean chance of beating each other drug tested on the same measure against the same control in trials of about the same length, three drugs or more, where the measure's spread between trials rests on 5 or more degrees of freedom. A drug added to a regimen and one tested instead of it are never on one control. No common control, or too few trials to measure the spread, no size. | "Through placebo" is not a common comparator when the placebo is added to a different backbone in each trial; a spread measured on one to three degrees of freedom gives intervals that cover 75% to 88%, not 95%. |
| 10 | Shrinkage | Size: toward the mean of the drug's mechanism class, where four or more drugs of the class share a measure and a control, with a small-sample factor. Strength and wins: toward the mean of every drug in the indication. Never on safety. | A prior fitted on three to nine unlike drugs collapsed real differences and claimed precision the data do not hold. |
| 11 | Safety | Mantel-Haenszel risk difference by trial, controlled trials only, placebo-controlled and active-controlled apart. The kind holding more of the drug's people is scored. The interval is widened for disagreement between trials, one factor per part and kind across every drug. The two parts count equally; a part behind under a quarter of the other's people is left out and named. An outcomes trial's serious events are left out. | Summed rates mixed uncontrolled arms in; a fixed-effect interval was too narrow in 29% of cases; half a score could rest on one small trial, and a thin part vanished under people weights; SELECT's serious events are the events semaglutide prevents. |
| 12 | Uncertainty | The 95% interval of the pooled effect and of each risk difference, in closed form, in the words. One range, on the rank, from a redraw of those estimates. No interval on a score. | A score has no true value for an interval to cover; 12 of 92 drugs sat on the edge of their own interval in revision 1. |
| 13 | Weight of evidence | Stays a third of overall. Counts everyone treated in a trial with posted safety counts, and the text says so. | It measures maturity, which no standard error does. |
| 14 | A drug with no comparable peer | Where some drug in the indication has a size, its size counts at 50, the average of the size scale over any cell's drugs; where none has, efficacy is strength and wins alone for every drug. The table and the chart mark it and its rank line says so. | Size averages 50 by construction, so leaving it out gave an unmeasured drug an edge over every measured one: finerenone ranked first in type 2 diabetes and pramlintide plotted right of tirzepatide. 50 says nothing about the drug; it places it level with its peers. |
| 15 | Words | At most four sentences per drug under the chart. Everything else sits in "What every score rests on". | Revision 1 printed a mean of 10.3 sentences per drug; this prints 3.0 to 4.0. |

---

## 1. What the book supports

### 1.1 The tables

| Table | Rows | Trials | What matters here |
|---|---|---|---|
| `trial_result_outcomes` | 369,982 | 4,760 | value, spread, lower, upper, n per arm; `param_type`; `dispersion_type`; `time_frame`. 97,663 rows are primary outcomes, the only ones the landscape reads. |
| `trial_result_analyses` | 33,901 | 2,899 | estimate, its type, interval and level, p-value, method. No column says whether the test was for superiority or non-inferiority, or one-sided. |
| `trial_result_safety` | 15,223 | 4,759 | serious and deaths per arm; `withdrawn_ae` on 6,084 rows (40%). An arm has a title and no description, and no exposure time. |

What the analysis rows hold, across the whole book:

- An estimate with both interval bounds: 28,404 of 33,901 (84%). One bound only: 100.
- Interval level: 95 on 27,735; 90 on 1,198; 80 on 403; 97.5 on 366; blank on 3,749; 22 rows
  write the level as 0.95.
- A p-value: 26,515 (78%). Of those, 9,661 (36%) are a bound below such as "<0.001" and 38 are a
  bound above such as ">0.05".
- Estimate type, by count: a difference of one wording or another 18,946 (the largest, "Mean
  Difference (Final Values)", 3,415); a ratio 8,172, of which hazard ratios 3,049, odds ratios
  2,701 and geometric mean ratios 1,737; blank 4,710.
- Method, by count: ANCOVA 6,021; blank 5,653; mixed models 3,002; Cochran-Mantel-Haenszel
  2,744; logistic regression 2,127; ANOVA 1,960; log rank 1,759; Cox regression 407.
- The method text names a one-sided test on 259 rows and non-inferiority on 26. In the six
  indications below it flags a one-sided test on 6 arm rows and non-inferiority on none, yet
  the insulin trials in type 2 diabetes are non-inferiority trials almost without exception.
  The hypothesis cannot be recovered from the book.

### 1.2 Six indications

Obesity (367), non-small-cell lung carcinoma (20), breast neoplasms (371), type 2 diabetes (1),
rheumatoid arthritis (383) and multiple myeloma (101).

| | Obesity | Lung | Breast | Diabetes | Arthritis | Myeloma |
|---|---|---|---|---|---|---|
| Candidates | 32 | 91 | 71 | 46 | 28 | 28 |
| Trials linked | 211 | 405 | 340 | 558 | 255 | 184 |
| Trials with posted results | 53 | 171 | 185 | 387 | 154 | 60 |
| Arm rows with a comparator, a difference and a direction of benefit | 158 | 129 | 120 | 507 | 106 | 18 |
| Trials by comparator kind: placebo / control / comparator | 43 / 0 / 2 | 28 / 7 / 35 | 31 / 7 / 20 | 161 / 0 / 57 | 33 / 0 / 1 | 4 / 1 / 10 |
| Results with more than one drug arm, all sharing one control arm | 25 | 9 | 5 | 109 | 20 | 0 |
| p-value on the arm row: exact / bound below / none | 17 / 129 / 12 | 72 / 13 / 44 | 69 / 7 / 44 | 66 / 307 / 134 | 32 / 30 / 44 | 8 / 4 / 6 |
| Estimate type: difference / hazard ratio / other ratio / none | 79 / 2 / 60 / 16 | 1 / 92 / 0 / 36 | 7 / 64 / 4 / 45 | 340 / 20 / 20 / 116 | 34 / 0 / 14 / 56 | 0 / 10 / 3 / 5 |
| Interval level where posted | 95 only | 95 on 82; 80, 90, 96, 96.85, 97.38, 99 on 11 | 95 on 64; 80, 90, 96, 97.5, 99 on 10 | 95 on 376; 80 on 5; 95.6 on 3 | 95 only | 95 only |
| Analysis rows per arm pair: none / one / two or more | 11 / 107 / 40 | 35 / 84 / 10 | 42 / 64 / 14 | 113 / 339 / 55 | 37 / 64 / 5 | 5 / 13 / 0 |

What the placebo arm is, which decides who can be compared with whom (section 2.8). In obesity
every placebo arm is placebo alone. In oncology it almost never is: lung overall survival has
placebo with docetaxel, with platinum and etoposide, with paclitaxel and carboplatin, with
pemetrexed and chemotherapy, and placebo alone; breast progression-free survival has placebo
with letrozole, fulvestrant, exemestane, docetaxel, capecitabine, nab-paclitaxel and trastuzumab
with docetaxel. Active comparators are as varied: 40 lung results against 23 distinct
comparator arms, 49 diabetes results against 35, 19 breast results against 14.

Trial length differs inside a measure too. Percent change in body weight in obesity is posted
at 12 weeks (canagliflozin plus metformin), 26 and 28 (canagliflozin, berobenatide), 48
(eloralintide), 44 to 104 (semaglutide) and 52 to 88 (tirzepatide).

### 1.3 Standard-error routes

How often each route can be derived, as a share of arm rows (a row can support several):

| Route | Obesity | Lung | Breast | Diabetes | Arthritis | Myeloma |
|---|---|---|---|---|---|---|
| Analysis row: a difference with its interval | 50% | 1% | 6% | 66% | 32% | 0% |
| Analysis row: a hazard ratio with its interval | 1% | 71% | 52% | 4% | 0% | 56% |
| Analysis row: another ratio with its interval | 38% | 0% | 3% | 4% | 13% | 17% |
| Arms: standard deviation and n | 28% | 0% | 0% | 28% | 0% | 0% |
| Arms: standard error | 23% | 0% | 0% | 41% | 0% | 0% |
| Arms: an interval around each mean | 6% | 1% | 0% | 19% | 0% | 0% |
| Two proportions from counts or a percentage with n | 42% | 13% | 30% | 7% | 72% | 33% |
| Exact p-value with the difference | 11% | 54% | 57% | 13% | 30% | 44% |
| p-value bound below with the difference | 82% | 10% | 6% | 60% | 28% | 22% |

The route each result takes under the rules of section 2, and what is left unscored:

| | Obesity | Lung | Breast | Diabetes | Arthritis | Myeloma | All six |
|---|---|---|---|---|---|---|---|
| Results (drug, trial, outcome) | 67 | 92 | 88 | 222 | 36 | 16 | 521 |
| Interval on a difference | 40 | 1 | 8 | 160 | 15 | 0 | 224 (43%) |
| Hazard ratio interval | 0 | 83 | 55 | 0 | 0 | 11 | 149 (29%) |
| Counts | 24 | 8 | 21 | 18 | 21 | 5 | 97 (19%) |
| Arm spread | 3 | 0 | 0 | 38 | 0 | 0 | 41 (8%) |
| Another ratio's interval | 1 | 0 | 3 | 6 | 0 | 0 | 10 (2%) |
| Hazard ratio with its p-value | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| p-value with the difference | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Results from several dose arms | 20 | 4 | 1 | 78 | 14 | 0 | 117 |
| Results the sponsor posted no test for | 2 | 14 | 18 | 41 | 6 | 3 | 84 (16%) |
| Endpoints left unscored | 10 | 16 | 15 | 41 | 43 | 4 | 129 |
| of which: direction of benefit not clear | 2 | 1 | 6 | 12 | 37 | 2 | 60 |
| of which: no arm names the drug | 8 | 0 | 2 | 13 | 6 | 0 | 29 |
| of which: nothing posted to test it with | 0 | 2 | 3 | 10 | 0 | 1 | 16 |
| of which: survival with no hazard ratio | 0 | 10 | 4 | 0 | 0 | 1 | 15 |
| of which: the comparator arm also holds the drug | 0 | 2 | 0 | 6 | 0 | 0 | 8 |
| of which: a hazard ratio its medians contradict | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| Endpoints scored before / after | 72 / 67 | 78 / 92 | 67 / 88 | 188 / 222 | 31 / 36 | 12 / 16 | 448 / 521 |

(One result pools arms that took two routes and is counted under each.)

Three facts from these tables drive the design:

1. **Every result that can be scored has a standard error from an interval, a spread or a
   count.** The p-value route is never the one taken in these six indications, bar one hazard
   ratio posted with a p-value and no interval. It stays in the order as the last resort for
   other indications.
2. **A p-value bound would be a poor basis.** 82% of obesity rows and 60% of diabetes rows carry
   one. STEP 1 (NCT03548935) posted "<.0001" on a difference of 12.44 points: the bound allows a
   standard error of up to 12.44 / 3.89 = 3.20, where the interval gives 0.47. The bound
   understates the precision seven-fold.
3. **Endpoints that were skipped for want of a p-value can now be tested** from their own
   interval, spread or counts: 448 endpoints scored before, 521 after. 84 of the 521 are tests
   the terminal runs itself because the sponsor posted none, and the first sentence under the
   chart says how many (section 5.1).

### 1.4 Safety counts per trial

| | Obesity | Lung | Breast | Diabetes | Arthritis | Myeloma |
|---|---|---|---|---|---|---|
| Drugs with a safety record | 10 | 46 | 50 | 27 | 22 | 16 |
| Trial strata | 53 | 171 | 185 | 387 | 154 | 60 |
| Strata with a control arm | 47 | 58 | 71 | 212 | 50 | 15 |
| Strata kept under the rules of 2.10 | 47 | 57 | 71 | 207 | 49 | 15 |
| Control kind of those kept: placebo / active | 46 / 1 | 31 / 26 | 38 / 33 | 171 / 36 | 47 / 2 | 3 / 12 |
| Serious events counted in both arms | 47 | 57 | 70 | 204 | 49 | 15 |
| Withdrawals counted in both arms | 22 | 13 | 25 | 119 | 20 | 3 |
| A zero cell, serious / withdrawals | 5 / 6 | 0 / 2 | 1 / 8 | 26 / 22 | 11 / 3 | 0 / 0 |
| Kept strata with more than one drug arm summed | 20 | 15 | 7 | 83 | 20 | 0 |
| Drugs with no controlled stratum | 0 | 21 | 18 | 7 | 6 | 9 |

Three things follow. Two thirds of lung and breast strata have no control arm, and the present
score adds their events to the drug's rate while the control rate comes from the other third.
Withdrawals for adverse events are posted in both arms for under half the controlled strata (202
of 446), so the "staying on treatment" part often rests on one trial and must not count for half
the score. And the registry posts no exposure time: a count is people with an event over each
arm's whole follow-up, so an arm followed for longer reports more. That last point cannot be
fixed from the book. It is stated on screen (5.2) and listed as a limit (9.2).

How far a drug's trials disagree on a safety count, as the ratio of their spread to what their
own sampling error explains (sum of Q over sum of degrees of freedom, across the drugs with two
or more strata; 1 means no more than chance):

| | Obesity | Lung | Breast | Diabetes | Arthritis | Myeloma |
|---|---|---|---|---|---|---|
| Serious events, placebo-controlled | 2.4 | 1.4 | 1.1 | 2.1 | 9.3 | not known |
| Serious events, active-controlled | not known | 2.1 | 1.6 | 1.0 | not known | 2.8 |
| Withdrawals, placebo-controlled | 3.5 | 1.0 | 1.3 | 1.5 | 1.0 | not known |
| Withdrawals, active-controlled | not known | not known | 1.3 | 3.0 | not known | not known |

"Not known" is where no drug has two strata of that kind. A fixed-effect interval is too narrow
wherever the figure is above 1, which is most of the table.

---

## 2. Method

Notation. An *effect* is a drug's difference from its comparator, signed so that more is better
for the patient. *se* is its standard error. `Φ` is the standard normal distribution function
and `z(L)` the normal deviate of a two-sided level L: z(95) = 1.959964.

### 2.1 The unit: one result per drug, trial and outcome

Today `_best_rows` takes, per drug and trial, the arm with the largest benefit across every arm
and every category of an endpoint. That selects on the result, in three ways the statistics
cannot then undo: the best of several doses, the better of two analysis sets, and, where a
sponsor posted "Yes" and "No" as categories, whichever of the two has the favourable sign, so a
drug that lost would be scored as having won.

The replacement is one *result* per (drug, trial, outcome index), built without looking at how
large anything is. Only rows that have a comparator are read; a result posted with no arm
the book can read as its control (a single-arm trial, or arms whose titles do not say which is
the drug's) is counted as unscored, reason `no control`, so `why_not` never says a drug had no
comparator when one existed. In this order:

1. **Direction** (2.2). Not efficacy: skipped and not counted. Unknown: counted as unscored,
   reason `direction`.
2. **A baseline is not a result.** An outcome whose title starts with "baseline" is skipped and
   not counted ("Baseline Hemoglobin A1c (HbA1c)", NCT01059825).
3. **Category.** The first category in the order the sponsor posted that states the result. A
   category is skipped where any part of it (split on "·") reads no, none, not ..., non-...,
   without ... or censored, or where it names the baseline without "change" or "from baseline".
   Of the outcomes with categories in obesity, 13 are yes and no, 9 are two analysis sets
   ("In-trial" then "On-treatment"), and the first listed is the conservative one.
4. **The comparator must not hold the drug.** Where the comparator arm's title names the drug
   (row field `reference_is_drug`), the difference belongs to whatever was added to it, not to
   the drug. Unscored, reason `in both arms`. Sitagliptin had been credited with ipragliflozin's
   effect ("Ipragliflozin + Sitagliptin" against "Placebo + Sitagliptin", NCT02577003). The
   title is also read for a shortened name (`names_drug_short`): a word of four letters or more
   that is the start of one of the drug's names of seven letters or more (name, generic,
   brands) and not the whole of it. "Pembro + Placebo (Maintenance Phase)" names pembrolizumab,
   so NCT03976362 (pembrolizumab with olaparib against pembrolizumab with placebo, as
   maintenance) is olaparib's effect, not pembrolizumab's. A word followed by "placebo" or "dummy", or after
   "matching", names the placebo and not the drug: "Arm B: Nivo Placebo + Chemo" (NCT04109066)
   is placebo for nivolumab. The whole word is left to the full-name test, so "Insulin
   glargine" never names insulin icodec. In the six indications the shortened name catches the
   two pembrolizumab results and one safety stratum, and nothing else.
5. **The arm must name the drug.** The drug's arms are the rows that name the drug (row field
   `arm_names_drug`, section 4.1) and that are not themselves a placebo or a named control
   (`arm_is_control`) nor a crossover, optional switch or extension arm (`_CROSSOVER`: "Post
   Chemotherapy Optional Nivolumab"). Where none does, there is no fallback to the unnamed arms:
   unscored, reason `not its arm`. "Naltrexone + Oxycodone" had been read from the NB16 and NB32
   arms of four naltrexone plus bupropion trials; fulvestrant's leading result was "Cediranib
   45 mg" against "Placebo" (NCT00454805).
6. **Tested arms.** Where the sponsor posted an analysis row against this comparator for some
   of those arms and not others, the tested arms are the comparison. An untested arm is often
   another cohort whose own control is a different arm (enzalutamide, NCT02007512).
7. **A total arm is dropped.** With three or more arms, an arm that is the total of the others
   goes: its title starts all, total, pooled, combined or overall, or its n equals the sum of
   the other arms' n (VERTIS CV, NCT01986881: "All Ertugliflozin" 5,493 = 2,747 + 2,746).
8. **Effect per arm** by the first route of 2.3 that the posted numbers support. No arm with a
   route: unscored, reason `no hazard ratio` for a time-to-event measure, else `nothing to test`. A
   hazard ratio whose medians contradict it: reason `orientation`.
9. **Test and size** (2.4): all arms together for the test statistic z, the top arm less an
   allowance for the size of effect.

What rules 4 and 5 cost and buy, in the six indications: 37 endpoints go unscored, 8 for the
drug in both arms and 29 for no arm naming it. The 29 sit in 22 trials. In 17 of those the arms
were another drug's (naltrexone plus bupropion, omarigliptin, orforglipron read as dulaglutide, a
physician's-choice arm read as eribulin). In 5 the arm is the drug's under an abbreviation or a
code with no description to say so ("IDegLira", "Saxa", "ABA", "AIN457", "Radium-223 +
EXE/EVE"), and those results are lost. Section 9.2 lists them.

### 2.2 Direction of benefit

`benefit_direction` gains two rules ahead of the title patterns it has now. In order:

1. Not efficacy, as now, plus two patterns the present table misses: `\baes?\b` and
   `abnormalit` ("Number of Participants Who Experienced an AE", "... Laboratories Meeting
   Marked Abnormality Criteria"). Five endpoint wordings in the six indications, four of them
   abatacept's.
2. **A family fixes its own sign.** Where the title and unit put the endpoint in a measure
   family (subgroup or not), the sign is the family's: percent change in body weight -1; share
   losing 5% or more of body weight +1; change in HbA1c -1; overall, progression-free and
   disease-free or event-free survival +1; response rate +1; percent change in LDL cholesterol
   -1. The title's other words never override it. "Change From Baseline to Week 26 in HbA1c
   Bayesian Dose Response" (tirzepatide, NCT03131687) was read as higher-is-better because it
   contains "Response".
3. **People counted with an event are lower-is-better**, whatever survival word the title
   holds: the unit is a share or count of participants and the title matches
   `\bevents?\b(?![- ]free)|\bwho died\b|\bdeaths?\b|progression or death`. APHINITY
   (NCT01358877) posts invasive disease-free survival *events*, 7.1% of 2,400 against 8.7% of
   2,404: fewer on the drug, a result for pertuzumab, read as one against it until now. Also
   docetaxel NCT00688740 (287 against 333 disease-free survival events) and bevacizumab
   NCT00528567.
4. **The title** (`_title_direction`), in this order: a time to an event or a stretch free
   of one ("time to", "time from randomization ... to", "duration of flare-free maintenance")
   is +1, or -1 where the event is a good one (relief, onset, response, remission, recovery);
   an instrument that fixes its own direction, lower first (SGRQ, DLQI, MLHFQ) then higher
   (SPID, SPRID, TOTPAR, pain relief, KCCQ, FEV1, FVC, peak expiratory flow, quality of life,
   SF-36, EQ-5D, six-minute walk); a count of people is -1 where it names a bad event or a harm
   (reaction, bleeding, hypoglycaemia, infection, fever or temperature, neoplasia or CIN,
   disability, hyperplasia, solicited or injection-site events, gastroenteritis, lower
   respiratory) and nothing says free of it, +1 only where a responder word says so (respond,
   achieve, remission, clear, improve, success, sero-, free, normal, target, "< 7%"), and
   otherwise unknown; then the higher-is-better words, then the lower-is-better words, where
   "weight" is a whole word so "weighted mean FEV1" is not body weight.
5. The way most drugs moved a measure three or more posted, as now.

Before the review round the catch-all "(percentage|number) of participants" set +1 on 162
results, 87 of them harms or cases of disease: VLA15's local reactions (77% against 24.7%)
scored as wins at z +20.8, ticagrelor's TIMI major bleeding at z +7.47, Cervarix's CIN2+ (5
against 97 cases) as a loss at z -9.17. SPID and SPRID read as pain, lower-is-better, so
naproxen scored 0 on efficacy in pain; "weight" matched "weighted mean FEV1", so umeclidinium
lost twice at z -4.68 and -4.03.

The HbA1c family also gains its other spellings: the pattern becomes
`hba1c|\ba1c\b|glycated h(a)?emoglobin|h(a)?emoglobin a1c`. Revision 1 split sitagliptin's HbA1c
trials across three rankings ("change in HbA1c", "change in hemoglobin A1C (A1C)", "change in
A1C").

### 2.3 The effect and its standard error, by route

`d` is the arms' own difference (arm minus comparator; for a count of participants, the
difference in share of each arm, in percentage points). `sign` is the direction of benefit.

**An interval must be sound before any route uses it** (`interval_is_sound`): lower < estimate <
upper, and the estimate within a quarter of the width of the midpoint, on the log scale for a
ratio. NCT00106704 posted -0.74 (-90.0 to -0.57), a typo that would give a standard error of
22.8. It is the one interval of the 893 with a level on the rows read in the six indications
that fails; the other off-centre ones are rounding and pass. A level must be posted: an interval
with no level is not used.

**For a survival measure** (the unit is a time and the title names overall, progression-free,
disease-free or event-free survival, subgroup or not):

1. *Hazard ratio interval.* An analysis row whose estimate type names a hazard ratio, with a
   sound interval and a level.

   ```
   effect = -ln(HR)          se = (ln(upper) - ln(lower)) / (2 z(level))
   ```

   The hazard ratio is read as drug over comparator. Where the interval excludes 1 and the
   medians point the other way, its orientation is not settled and the result is left unscored
   (one arm row in six indications: irinotecan, NCT00143455, hazard ratio 1.35 with the longer
   median). Scale: log hazard ratio.

   Nivolumab, NCT01642004: HR 0.59, 96.85% interval 0.43 to 0.81. z(96.85) = 2.1507.
   se = (ln 0.81 - ln 0.43) / (2 x 2.1507) = 0.6333 / 4.3014 = 0.1472. effect = -ln 0.59 =
   0.5276. z = 3.58.

2. *Hazard ratio with its p-value.* A hazard ratio posted with a p-value and no usable
   interval: the ratio gives the direction, the p-value the standard error.

   ```
   effect = -ln(HR)          se = |ln(HR)| / z_p
   ```

   z_p as in route 7. Not used for a hazard ratio of exactly 1 or a p-value posted as a bound
   above. The same orientation check, at p < 0.05. Dasatinib, NCT00767520: HR 0.82, p 0.148.
   z_p = 1.4466; effect = 0.1985; se = 0.1372. One result in six indications.

   **Nothing else reads a survival time.** A median or a mean of censored times with its
   interval, a count of events, or a log-rank p-value with no hazard ratio leaves the result
   unscored and counted, reason `no hazard ratio`. Medians mislead when curves cross: IPASS
   (gefitinib, NCT00322452) holds medians of 5.7 and 5.8 months and no analysis row; their ratio
   reads 1.02 where the published hazard ratio is 0.74 in gefitinib's favour. A log-rank
   p-value carries no direction of its own. 15 endpoints go unscored for this, and three drugs
   lose their place on the chart (ramucirumab and gefitinib in lung, abemaciclib in breast).
   That is the honest reading of what the book holds for them.

**For every other measure:**

3. *Interval on a difference.* An analysis row with a sound interval and a level, whose
   estimate is not a ratio (type does not name a ratio, odds, hazard, relative risk or fold) and
   not one arm's own mean, and which reproduces the arms' own difference:

   ```
   se  = (upper - lower) / (2 z(level))
   tol = max(0.25 |d|, se)
   |estimate - d| <= tol  ->  effect = sign x estimate
   |estimate + d| <= tol  ->  effect = -sign x estimate     (sponsor subtracted the other way)
   otherwise the row is on another footing and is not used
   ```

   Where several rows pass, the one closest to `d`. That is also how an analysis row is matched
   to a category, since the table carries no category: STEP 1 posted -12.44 for the in-trial
   set and -14.42 for the on-treatment set, and each category takes the one that reproduces it.
   Of 374 posted differences in diabetes and arthritis, 343 reproduce the arms' difference
   within a quarter, 9 are its mirror image and 22 are on another footing.

   STEP 1, NCT03548935: -12.44 (95% interval -13.37 to -11.51); arms -15.6 against -2.8.
   se = 1.86 / 3.92 = 0.4745. effect = 12.44. z = 26.2.

4. *Arm spread.* Each arm posted a spread around a mean.

   ```
   mean with a standard deviation:       se = sqrt(sd_1^2 / n_1 + sd_0^2 / n_0)
   mean or least-squares mean with a standard error:   se = sqrt(se_1^2 + se_0^2)
   mean or least-squares mean with an interval per arm:
                                         se_i = (upper_i - lower_i) / (2 z(level)), then as above
   effect = sign x d
   ```

   **A least-squares mean posted with a "standard deviation" is not read.** It is a model
   estimate, and the figure beside it is as often its standard error as a spread between
   patients. The one trial that takes this form in the six indications (tirzepatide,
   NCT03131687, posterior means with a "Standard Deviation" of 0.08 to 0.14 on about 45 people
   an arm) would give z above 37 on every arm if divided by n again. Its primary endpoint is
   left unscored and counted, reason `nothing to test`. Where the three kinds this route does
   read can be checked against the sponsor's own interval, they agree: the ratio of the two
   standard errors has a median of 0.97 (mean with standard deviation, 123 rows), 1.01
   (least-squares mean with standard error, 153 rows) and 1.00 (mean with standard error, 38
   rows). A median with an inter-quartile range or a full range gives nothing.

   Semaglutide, NCT05649137, relative change in body weight: -10.7 (sd 8.1, n 97) against -4.0
   (sd 6.2, n 95), no analysis row. se = sqrt(65.61 / 97 + 38.44 / 95) = sqrt(0.6764 + 0.4046) =
   1.0397. effect = 6.7. z = 6.44. This endpoint was unscored before.

5. *Counts.* A count of participants (the outcome's type is a count of participants, or a
   number whose unit is exactly participants, patients or subjects) with each arm's n; or a
   percentage of participants with each arm's n (the unit starts percentage, percent or
   proportion of participants, patients or subjects; or the unit is a bare percentage and the
   title says percentage of participants). A unit starting "proportion" with both values at or
   under one is read as a fraction, not a percentage. A rate per patient-year is not a share and
   is never read as one: `_unit_class` calls "Episodes per 100 years of patient exposure" a
   share because it contains "patient", so this route checks the outcome's type and the unit
   itself.

   ```
   p_i = x_i / n_i        effect = sign x 100 (p_1 - p_0)     percentage points
   se  = 100 sqrt(v_1 + v_0),   v_i = p_i (1 - p_i) / n_i
   ```

   A share of 0 or 1 takes its variance from (x + 0.5) / (n + 1), so an empty cell never claims
   a standard error of zero; the difference itself is left as posted. Semaglutide,
   NCT03552757: 267 of 404 against 107 of 403. p = 0.6609 and 0.2655; effect = 39.54 points;
   se = 100 sqrt(0.00055474 + 0.00048391) = 3.223. z = 12.3.

6. *Another ratio's interval.* An odds, risk or hazard ratio with a sound interval, on a
   measure that is not a survival measure. The ratio's orientation is not knowable in general,
   so its sign comes from the arms: effect = |ln ratio| where `sign x d > 0`, else minus it;
   se = (ln upper - ln lower) / (2 z(level)). It gives z, for strength and wins. It is never
   averaged for size.

7. *p-value with the difference.* z_p is the normal deviate of the posted p: two-sided unless
   the method text says one-sided (then `Φ⁻¹(1 - p)`), p floored at 1e-6, z capped at 5.

   ```
   se = |d| / z_p        effect = sign x d
   ```

   An exact p gives the standard error that makes a Wald test reproduce it. It checks out
   where both exist: liraglutide, NCT02963935, p = 0.0003 on -3.45 gives 3.45 / 3.615 = 0.954
   against 0.949 from the interval. A bound below ("<0.001") gives the largest standard error
   the bound allows, flagged as a bound. **A bound above (">0.05") gives no test statistic at
   all.** None is made up from the middle of what the bound allows, as the present code does:
   the result is counted as an endpoint not won and left out of strength, and the words say so.

Why the interval comes before the p-value. VERTIS CV (NCT01986881) posted a hazard ratio of
0.97 (95.6% interval 0.848 to 1.114) with p "<0.001". The p-value tests non-inferiority. Read
as superiority, as the score does today, it is a win at z = 3.29 for the pooled arm and a loss
at the same strength for the 15 mg arm, whose rate was a shade above placebo. From the interval:
se = (ln 1.114 - ln 0.848) / (2 x 2.014) = 0.0677, z = 0.45. Not a win, which is the truth.
Insulin icodec against glargine (NCT04460885): "<0.0001" for non-inferiority; from the interval
-0.19 (-0.36 to -0.03), z = 2.26.

A level posted as a fraction (0.95) is read as a percentage. The book does not say whether an
interval is one-sided; every level is read as two-sided, and the caveat on screen says so. A row
with one bound only is not used.

### 2.4 Several dose arms: the test and the size

A trial of several doses against one control gives two numbers, and they answer different
questions.

**The test statistic** asks whether the drug works at any dose. It is the arms averaged by arm
size, with the shared control counted once (`combine_arms`). Arm k has effect e_k, standard
error s_k and size n_k; the control has n_0.

```
w_k    = n_k / sum(n)                      (equal weights where an n is missing)
effect = sum(w_k e_k)
c_k    = the control arm's share of s_k^2:
           the posted control variance, where the route gave one (arm spread, counts)
           else s_k^2 n_k / (n_k + n_0)    (its share when both arms vary alike per person)
var    = sum(w_k^2 (s_k^2 - c_k)) + sum(w_k c_k)
z      = effect / sqrt(var)
```

Where an n is missing and no control variance was posted, the arms are taken as fully
correlated: se = sum(w_k s_k), the largest it can be. Arms are combined only with arms on the
same scale; where they differ, the scale most arms are on. An arm with no route is left out and
the others combined. The equal-spread assumption applies to 92 of the 117 multi-arm results (the
interval route posts no control variance) and is stated in the words (5.1).

**The size of effect** asks how much the drug does. Averaging the doses understates it: the gap
between the best arm and the average is 2.4 to 2.8 points in tirzepatide's multi-dose Phase 3
trials, and it falls unevenly, since 4 of tirzepatide's pooled results averaged several doses
and 1 of semaglutide's 17 did. Taking the best arm overstates it, by the luck of picking the
best of k. So the size is the most effective arm less what that pick adds by chance when the
doses do not differ (`top_arm`):

```
b         = the arm with the largest effect
own       = sqrt(s_b^2 - c_b)              the part of its error that is its own; the shared
                                           control moves every arm alike and cannot favour one
allowance = E[max of k standard normals] x own     0.5642, 0.8463, 1.0294, 1.1630, 1.2672
                                                   for k = 2 ... 6
effect    = e_b - allowance          se = s_b
```

Where the control's share is not known the whole s_b is used, the larger allowance. The
allowance is the whole selection bias when there is no dose response and too large when there
is one, so it errs against the drug. It needs no dose parsed from an arm title.

SURMOUNT-1, NCT04184622, percent change in body weight:

| Arm | n | effect | se | c_k |
|---|---|---|---|---|
| 5 mg | 623 | 13.5 | 0.5357 | 0.2870 x 623 / 1258 = 0.1421 |
| 10 mg | 629 | 18.9 | 0.5612 | 0.3150 x 629 / 1264 = 0.1567 |
| 15 mg | 625 | 20.1 | 0.5612 | 0.3150 x 625 / 1260 = 0.1562 |

Placebo n = 635. Test: weights 0.3319, 0.3351, 0.3330; effect = 4.481 + 6.334 + 6.693 = 17.51;
var = (0.1102 x 0.1449 + 0.1123 x 0.1583 + 0.1109 x 0.1588) + 0.1517 = 0.2031; se = 0.451;
z = 38.9. Size: the 15 mg arm; own = sqrt(0.3150 - 0.1562) = 0.3984; allowance = 0.8463 x
0.3984 = 0.337; effect = 20.1 - 0.337 = 19.76, se 0.5612. A Phase 3 trial's top dose stays near
what it posted. Eloralintide's six-arm Phase 2 trial (NCT06230523) gives up more: its best arm
reads 19.70 and its size 18.04, an allowance of 1.66.

**One measure posted more than once by one trial** (`combine_repeats`), for example in-trial
and on-treatment as two outcomes:

```
w_i = 1 / s_i^2     effect = sum(w_i e_i) / sum(w_i)     se = sum(w_i s_i) / sum(w_i)
```

The same patients are behind every repeat, so the repeat buys no precision. Semaglutide,
NCT04998136: 12.99 (se 1.168) and 13.40 (se 1.171) give 13.19 (se 1.170).

### 2.5 The averaged effect per drug, measure and control

A *cell* is one drug on one measure against one control.

- **Measure.** A measure family as now, or an endpoint outside the families under its own key.
- **Scale.** Survival families: log hazard ratio (routes 1 and 2). Share families (share losing
  5% or more of body weight, response rate): percentage points of people (routes 3 and 5). The
  other families: the posted difference (routes 3 and 4). An endpoint outside the families: the
  difference or the share, whichever more of its results are on. A result on another scale
  still counts for strength and wins; it is not averaged.
- **Control.** What the control arm received, read from its title (`control_key`, section 2.8):
  "placebo alone", a named regimen, or, where the title names no regimen two trials could
  share, the trial's own control.
- **A randomised-withdrawal result is not averaged.** Where the outcome's time frame reads
  "randomisation (week N)" with N at least 1 (pattern
  `randomi[sz]ation\s*\(\s*week\s*([1-9]\d*)\s*\)`), both arms were on the drug before
  randomisation and the placebo arm is coming off it. STEP 4 (NCT03548987, "Randomisation (week
  20) to week 68", 14.75 points) and SURMOUNT-4 (NCT04660643, "Randomization (Week 36), Week
  88", 21.4 points) are the two in the six indications. They count for strength and wins and
  stay out of the size of effect.

Per cell, one effect per trial (2.4). Then one between-trial variance per measure, and the
weighted mean:

```
for each cell j of the measure with k_j >= 2 trials, on the trials' own errors:
    w_i = 1 / s_i^2      fixed_j = sum(w_i y_i) / sum(w_i)
    Q_j = sum(w_i (y_i - fixed_j)^2)          C_j = sum(w_i) - sum(w_i^2) / sum(w_i)
tau2 = max(0, (sum Q_j - sum(k_j - 1)) / sum C_j)           (`common_tau2`)

for every cell of the measure, k = 1 included:                (`pool_common`)
    w*_i   = 1 / (s_i^2 + tau2)
    effect = sum(w*_i y_i) / sum(w*_i)        se = sqrt(1 / sum(w*_i))
    interval = effect -/+ z(95) se
```

This is the usual assumption of a network comparison: how far a drug's trials differ from one
another is a property of the measure, not of the drug. It needs no new data and it fixes what
revision 1 got backwards. Drug by drug, tirzepatide's six obesity trials (which span 11 to 24
points) gave it a standard error of 1.96, and eloralintide's single Phase 2 trial of 210 people
had 1.08, because one trial has no spread between trials to show. With the measure's own
variance (7.93 on 22 degrees of freedom, a standard deviation of 2.8 points between trials),
tirzepatide's five averaged trials read 18.76 (se 1.34) and eloralintide's one reads 18.04
(se 3.24).

Where no drug has two trials on a measure, tau2 cannot be estimated. It is not guessed: each
drug keeps its own trial's error for the interval it prints, `tau2` is null, and no drug on
the measure is ranked (2.8): the words say "no drug has two trials on {measure}, so the spread
between trials is not known". Where tau2 is estimated on fewer than `TAU_DF_MIN` = 5 degrees of
freedom it is too loosely measured to compare drugs on, and the measure is not ranked either:
"the spread between trials on {measure} rests on too few trials to compare drugs". From 5 to
9 degrees of freedom (`TAU_DF_FEW` = 10) the measure is ranked and a note says the interval is
likely too narrow. The thresholds come from a simulation of the rule (4,000 simulated measures
per setting, trial se 1, between-trial sd two to three times that, as 39 of the book's 53
multi-trial cells show):

| Degrees of freedom behind tau2 | Coverage of the 95% interval |
|---|---|
| 1 | 75% to 80% |
| 3 | 86% to 88% |
| 5 | 89% |
| 8 | 91% to 92% |
| 11 | 92% to 93% |
| 22 (obesity, percent body weight) | 93% to 94%, for a one-trial drug as for a fifteen-trial one |
| drug by drug, as revision 1 | 47% to 62% for one trial, 75% to 81% for two, 86% to 87% for four |

In the book: HbA1c in diabetes 0.0356 on 110 degrees of freedom; percent body weight in obesity
7.93 on 22; share losing 5% in obesity 97.5 on 16. Those three are ranked. Overall survival in
lung 0.0116 on 3; progression-free survival in lung (0 on 1) and in breast (0.0005 on 1);
percent body weight and the share losing 5% in diabetes on 2 each. Those five are not: a
between-trial variance of zero on one degree of freedom says nothing about how far a drug's
next trial could land from its first, and ranking on it would repeat revision 1's fault of a
one-trial drug looking as certain as its one trial. Oncology has too few drugs with two trials
against one named control for the spread to be measured, which is a fact about the book.

Worked, tirzepatide in obesity, percent change in body weight against placebo, five trials
(SURMOUNT-4 is out): y = 12.125, 24.5, 19.763, 16.94, 20.579; s = 0.6888, 0.8419, 0.5612,
1.4031, 1.301. With tau2 = 7.932, w* = 0.11896, 0.11573, 0.12126, 0.10100, 0.10390, sum
0.56085. effect = 10.5233 / 0.56085 = 18.76. se = sqrt(1 / 0.56085) = 1.335. Interval 16.1 to
21.4. One trial, eloralintide: 18.04, se = sqrt(1.5951^2 + 7.932) = 3.237, interval 11.7 to 24.4.

A cell also carries the interval on the trials' own errors alone (`own_lo`, `own_hi`). For one
trial that is the interval the sponsor's numbers give, and it is the one quoted in the sentence
about that trial (eloralintide: 14.9 to 21.2). The wider one is used wherever the drug is
compared with another.

**When a drug's own trials disagree.** Its own Q on k - 1 degrees of freedom has a chi-square
p-value `q_p`. The sentence "Its trials disagree more than chance explains" prints only where
k is at least `DISAGREE_MIN` = 3 and `q_p` is below `DISAGREE_P` = 0.10. It quotes I2 = max(0,
(Q - (k - 1)) / Q) only from `I2_MIN` = 5 trials; with fewer, I2 has no usable precision and is
null. Revision 1 printed the sentence at I2 of 50% from two trials, which homogeneous trials
reach 16% of the time.

### 2.6 Strength

```
z_c      = the test statistic of each result (2.4), capped to [-5, 5]
z_t      = mean of z_c over the results of trial t      (one z per trial)
strength = clamp(100 x mean(z_t) / 3.29, 0, 100)
```

The mean of the trial z-scores, not a combined z. A combined z (sum over root k) grows with the
number of trials for any drug that works, so it scores how many trials exist, which weight of
evidence already does: under it 54 of 92 placed drugs sat at 100, and the printed figure was the
cap times root k (semaglutide "z = 22.1 across 20 trials" is 5 x sqrt(20)). One z per trial
still stands: co-primary endpoints of one trial are the same patients. A result with no test
statistic (a p-value posted only as a bound above) is left out.

Nivolumab in lung: trial z of 1.61, 1.46, 3.58, 0.48, 3.87, 3.20, 0.82, -1.18. Mean 1.73.
Strength 52.6.

**Moved toward the drugs' mean** (`strengths`, `_toward_mean`). One or two trials say less
than thirteen. Each drug's mean trial z is moved toward the mean of every drug in the
indication with a tested result, by `meta_stats.shrink` (2.9's arithmetic, Morris's factor
included), where a drug's mean of k trials has variance s_w^2 / k and s_w^2 is the spread of
trial z within the drugs with two or more trials, pooled, never under 1 (the sampling variance
of one z). Under four drugs nothing moves. In lung (23 drugs, drugs' mean z 2.0) a one-trial
drug moves 49% of the way and a two-trial drug 33%: cemiplimab's 4.8 is counted at 3.4, still
above 3.29, and pembrolizumab's 13 trials move 7%. Strength stays at 100 for a drug whose
average trial is far past p = 0.001 even after the move; wins carry the rest (2.7). A move
that changes the part by under half a point is not narrated.

Strength is at 100 for 35 of 84 placed drugs: all 9 in obesity, 12 of 17 in diabetes, 6 of 10 in
arthritis, 2 of 19 in lung, 4 of 23 in breast, 2 of 6 in myeloma. In obesity every drug's
average trial is beyond p = 0.001. The part is at its ceiling because the data are; size carries
the ordering there.

### 2.7 Wins, allowing for the number of tests

```
p_c     = 1 - Φ(z_c)                  one-sided, from the capped z of each tested result
adj     = Benjamini-Hochberg(p_1 ... p_m) across the m tested results of one trial:
            sort ascending; adj_(i) = min over j >= i of p_(j) m / j, capped at 1
a win   : adj <= 0.025 + 1e-9         (the two-sided 5%)
share_t = wins in trial t / results of trial t   (a result with no test statistic is not a win)
wins    = 100 x mean over trials of share_t
```

- **One-sided.** Adjusting two-sided p and then keeping the favourable ones lets a strong
  result against the drug loosen the bar for its wins: four results against at p = 0.001 and
  one for at p = 0.04 made the one a win. One-sided, a result against the drug has p near 1 and
  loosens nothing: the same five give the favourable one an adjusted p of 0.10.
- **A posted "<0.05" is a win at the 5% level** when it stands alone; the 1e-9 keeps floating
  point from deciding it. A bound below ("<0.001") sits at its bound, which can only overstate
  its adjusted p, so a bound never creates a win the exact value would not. A bound above is
  never a win.
- **By trial.** One trial supplies a median of 33% and up to 80% of a multi-trial drug's
  endpoints. Averaging each trial's share first gives every trial one vote, as strength does.
  The sentence still prints the plain count ("Won 5 of 10 endpoints in 8 trials").
- **Non-inferiority tests.** Their p-values are never used where an interval, a spread or a
  count exists (2.3). A win is always "better than the comparator", never "not worse". A trial
  built only to show a drug is no worse cannot produce a win, and the words say so where a
  drug's endpoints are against active comparators.
- **Dependence.** Endpoints of one trial are positively correlated, and Benjamini-Hochberg
  holds the false discovery rate under positive dependence.
- **Within each trial.** Each trial controls its own error rate, so the correction allows for
  the endpoints that trial tested, not the programme's (review round two: durvalumab's ARCTIC
  overall survival win was removed by correcting across three trials). The sentence reads
  "allowing for the number each trial tested".
- **Non-inferiority.** A result whose outcome title or analysis method says non-inferiority
  or equivalence, and that does not also clear a superiority win, is left out of strength and
  wins: the margin it had to clear is not in the registry, so the posted test is not of the
  question the trial asked (`_ni_set_aside`). A note counts them; a drug with nothing else has
  no efficacy score and `why_not` says so.
- **Moved toward the drugs' mean**, as strength is (2.6): each trial's share won is the value,
  its spread within drugs with two or more trials pooled, no floor. In lung the drugs' mean
  share won is 44: cemiplimab, one trial won outright, is counted at 56 (moved 78%); osimertinib,
  two trials, at 62 (68%); pembrolizumab's 55 over 13 trials at 52 (28%).

Pertuzumab in breast, seven results, one-sided p sorted: 0.0006, 0.0031, 0.0193, 0.0199, 0.0421,
0.1049, 0.1666. Multiplied by 7 / rank: 0.0042, 0.0109, 0.0450, 0.0348, 0.0589, 0.1224, 0.1666.
Made monotone from the top: 0.0042, 0.0109, 0.0348, 0.0348, 0.0589, 0.1224, 0.1666. Two wins at
0.025, where four cleared it before the correction. The 0.0199 is APHINITY, read the right way
up now (2.2): a raw win for the drug that does not survive seven tests. Across the six
indications 14 wins go, in seven drugs: pembrolizumab in lung 17 to 13 of 28, bevacizumab in
breast 7 to 4 of 16, pertuzumab 4 to 2 of 7, pembrolizumab in breast 4 to 2 of 9, albiglutide 9
to 8 of 12, durvalumab 1 to 0 of 3, enzalutamide 1 to 0 of 2.

Strength and wins are scored over every result, placebo-controlled and active-controlled
together, and the split is printed ("Against placebo it won 23 of 24; against active comparators
6 of 6"). Scoring only the placebo pair would throw away head-to-head superiority trials, which
are the strongest results the book holds.

### 2.8 Size against peers

**What a drug can be compared through** (`control_key`). Two drugs are compared on size only
where they were tested on the same measure against the same control. The key is read from the
control arm's title, which is already on every row (`reference_arm`):

```
lower-case; drop text in brackets; split on anything that is not a letter or a digit
drop words of one letter, words holding a digit, and the words of KEY_DROP
    (placebo, vehicle, sham, dummy, and arm, dose, schedule and form words: the full list is
     in the prototype and is copied as it stands)
nothing left         -> "placebo alone" where the title or the comparator kind says placebo,
                        else no key
any word of KEY_GENERIC left (chemotherapy, standard, care, soc, physician, investigator,
    choice, control, comparator, background ...)   -> no key
otherwise            -> the remaining words, sorted and joined: "docetaxel",
                        "bortezomib + dexamethasone", "glargine + insulin"
```

A placebo arm whose remaining words say only who was in it or when (years, old, season,
double-blind, twice, day, stage, stratum, panel, matched, DBTP, induction, part, period, cohort:
`_KEY_PERIOD`), or what it switched to afterwards ("Placebo followed by Tanezumab", "Placebo -
AIN457A"), or whose label sits before a colon ("RSV Season 1: Placebo"), is placebo alone.
"Placebo/X" is placebo given with X where the drug's own arm names X too (REVEL's
"Ramucirumab/Docetaxel" against "Placebo/Docetaxel"), and placebo switched to X where it does
not ("Placebo/Glimepiride" against "Ertugliflozin 15 mg", whose week-26 difference of 0.85 is
against placebo).

**Added to a regimen, or tested instead of it** (`comparison_key`). "Placebo + Docetaxel 75
mg/m^2" and "Placebo/Docetaxel" against "Ramucirumab + Docetaxel" are one control, docetaxel:
the drug was added to it. "Docetaxel" against "Pembrolizumab" is a different question, the
drug instead of docetaxel, keyed "docetaxel head to head", and the two are never averaged
together. A regimen word, or its start ("Met" in "Sita/Met FDC"), on the drug's own arm makes
it an add-on. Sitagliptin's monotherapy trial against metformin (-0.14) and its add-on to
metformin (+0.60) had been one cell with I2 0.98. "Chemotherapy", "Standard of Care", "Physician's Choice" and "Group B" name no regimen two
trials could share, so such a trial is compared with nothing. In words the control is "placebo"
or the shortest control title the sponsors posted for the key with placebo and dose stripped
("Docetaxel"), so a sentence never prints a name nobody posted.

**Which cells are ranked.** A measure and control with `SHARED_MIN` = 3 or more drugs, on a
measure whose between-trial variance is known and rests on `TAU_DF_MIN` = 5 or more degrees of
freedom (2.5). In the six indications:

| Indication | Measure | Control | Drugs | tau2 on | Ranked |
|---|---|---|---|---|---|
| Obesity | percent change in body weight | placebo alone | 8 | 22 df | yes |
| Obesity | share losing 5% or more of body weight | placebo alone | 4 | 16 df | yes |
| Diabetes | change in HbA1c | placebo alone | 14 | 110 df | yes |
| Diabetes | change in HbA1c | metformin | 4 | 110 df | yes |
| Diabetes | change in HbA1c | insulin glargine | 3 | 110 df | yes |
| Diabetes | change in HbA1c | glimepiride | 3 | 110 df | yes |
| Diabetes | percent change in body weight | placebo alone | 4 | 2 df | no |
| Diabetes | share losing 5% or more of body weight | placebo alone | 3 | 2 df | no |
| Lung | overall survival | docetaxel | 4 | 3 df | no |
| Lung | progression-free survival | docetaxel | 4 | 1 df | no |
| Breast | progression-free survival | exemestane | 3 | 1 df | no |
| Arthritis, myeloma | none | | | | |

That is far fewer than revision 1 ranked, and it is what the book supports. In obesity 8 of 9
placed drugs have a size, in diabetes 15 of 17; in lung, breast, arthritis and myeloma none,
and every drug there is scored on strength and wins (2.13), on one footing. A drug whose lead
cell had three or more drugs on its control and was not ranked says why in its third sentence
(5.1): nivolumab in lung reads "Size against peers not known: the spread between trials on
overall survival rests on too few trials to compare drugs, so efficacy is strength and wins
alone." Decision E of 9.1 gives what ranking the five unranked cells would do.

**The chance of beating a peer.** For two drugs a and b of one cell, with averaged effects
(after any class shrinkage, 2.9) and their standard errors:

```
P(a beats b) = Φ((effect_a - effect_b) / sqrt(se_a^2 + se_b^2))      0.5 on an exact tie
size on the cell = 100 x mean over the other drugs b of P(a beats b)
rank on the cell = 1 + the number of drugs with a larger effect       (equal effects share a rank)
```

100 for a drug certain to beat every peer, 0 for one certain to lose to all, 50 for one the
data cannot place. It replaces the rank percentile, which gave the same 12.5 points to a gap of
0.1 as to a gap of 10. The rank, the gap and the chance all rest on the same effects: revision 1
quoted the pooled effect, ranked on a shrunk one and measured the gap on the unshrunk one.

Obesity, percent change in body weight against placebo, eight drugs:

| Drug | Trials | Weeks | Effect | se | Own interval | Size | Rank |
|---|---|---|---|---|---|---|---|
| Tirzepatide | 5 | 52 to 72 | 18.76 | 1.335 | | 93 | 1 |
| Eloralintide | 1 | 48 | 18.04 | 3.237 | 14.9 to 21.2 | 89 | 2 |
| Berobenatide | 1 | 28 | 13.16 | 3.100 | 10.6 to 15.7 | 69 | 3 |
| Semaglutide | 15 | 44 to 104 | 10.94 | 0.764 | | 59 | 4 |
| Orforglipron | 2 | 72 | 7.64 | 2.112 | | 37 | 5 |
| Canagliflozin | 1 | 26 | 6.56 | 2.947 | 4.9 to 8.3 | 30 | 6 |
| Liraglutide | 4 | 26 to 56 | 4.96 | 1.462 | | 19 | 7 |
| Canagliflozin + Metformin | 1 | 12 | 1.36 | 2.846 | 0.6 to 2.2 | 4 | 8 |

P(tirzepatide beats eloralintide) = Φ(0.72 / sqrt(1.335^2 + 3.237^2)) = Φ(0.72 / 3.50) = 0.58.
P(tirzepatide beats semaglutide) = Φ(7.83 / 1.538), above 0.9999.

**Drugs that cannot be separated.** Where the chance of beating a peer lies between 45% and 55%
(`TIE`), the two cannot be called, and the sentence replaces the ordinal with "cannot be
separated from {n} of the {m} other drugs". Ertugliflozin, canagliflozin and sitagliptin on
HbA1c read 0.710, 0.701 and 0.699.

**The gap to the leader, in words.** Each ranked drug is measured against the cell's leader (the
leader against the runner-up): the difference of the two effects with its 95% interval, from the
same standard errors. It is an unadjusted indirect comparison and the sentence calls it no more
than that ("on that basis"). Two conditions:

- *A head-to-head trial outranks it.* The gap is always to the same drug, the leader (the
  runner-up for the leader). Where either of the two has a trial on the same measure whose
  control arm names the other (row field `head_to_head`), the sentence prints that direct
  result in place of the indirect one, read from whichever record holds the trial and turned
  round where it is the other drug's. Semaglutide's gap to tirzepatide: the indirect figure is
  7.8 points (4.8 to 10.8); the head-to-head trial NCT05822830, in tirzepatide's record, reads
  6.5 points (4.9 to 8.1), and semaglutide's sentence prints "head to head in one trial, 6.5
  percentage points behind Tirzepatide (95% interval 4.9 to 8.1)". The two agree; the direct
  one is five times tighter.
- *Only across trials of about the same length.* Where two drugs' trial lengths (the `weeks`
  field, smallest to largest over the averaged trials) neither overlap nor come within a
  quarter of each other (`LENGTH_TOL` = 0.25), they are not peers: the chance of beating, the
  rank and the gap are taken over the peers of comparable length only (`peers`; `peers_all`
  keeps every drug on the cell). A drug left with fewer than two such peers is not ranked, and
  its third sentence says its trials ran for a different length. A hazard ratio summarises the
  whole curve and carries no length. Weight loss grows with time on drug, so a 12-week trial
  was being scored on its chance of beating 72-week ones while the words said it was not
  compared.

Every averaged effect prints the trial lengths it spans, and the rank sentence prints the span
of the drug and its comparable peers (`rank_weeks`), adding "among those whose trials ran about
as long" where a peer on the cell was set aside for length. This supersedes appendix A, point 2.

**One result stated twice is counted once.** A drug's ranked cells are taken in order (most
drugs first, a family before an own-key measure, then most trials, then most people). A cell that
shares more than half its trials (`SAME_TRIALS` = 0.5, of the smaller cell) with one already
counted is named and not counted: in obesity, all 11 of semaglutide's trials of the share
losing 5% are among its 15 weight trials, and all 5 of tirzepatide's are its 5. Size is the mean
over the cells counted.

**The lead measure** of a drug is its first counted cell, or, for a drug with no ranked cell,
its largest cell by people treated, then by the strength of the averaged result. Before the
review round it was the cell with most peers, which put pembrolizumab's non-significant
progression-free survival against docetaxel (hazard ratio 0.87, 0.72 to 1.07) under the chart
in place of its main results. The pooled sentences are written for it.

### 2.9 Shrinkage toward the mechanism class

Applied to the drugs of one cell that share a mechanism class (`mechanism_label`), where
`CLASS_MIN` = 4 or more of them are on the measure and control. Nowhere else: not toward "every
drug on the measure", which in obesity averages incretins with SGLT2 drugs and in oncology
averages add-ons to different backbones.

For the J drugs of the class, with averaged effects y_j and standard errors s_j (`shrink`):

```
tau2, mean, var(mean)   between the J drugs, by the method of moments on the s_j
factor   = (J - 3) / (J - 1)                      Morris's factor for a prior fitted on J drugs
weight_j = factor x s_j^2 / (s_j^2 + tau2)
shrunk_j = weight_j mean + (1 - weight_j) y_j
se_j^2   = (1 - weight_j) s_j^2 + weight_j^2 var(mean)
           + (2 / (J - 3)) weight_j^2 (y_j - mean)^2
```

The factor keeps a drug from being moved all the way to the mean on the strength of a
between-drug variance estimated as zero from a handful of drugs: with four drugs no result
moves more than a third of the way, with five no more than half. The last term is the
uncertainty in the weight itself. In simulation (20,000 runs at each of 16 settings, four to
nine drugs, drugs differing by nought to two standard errors) the class is never collapsed to
one value, the shrunk 95% interval covers 94.7% to 99.6% across all drugs and 94.6% to 98.5%
for the leading drug, and the mean squared error is 7% to 73% below leaving the results alone.
Without the factor, revision 1's rule gave every drug the mean in 26% to 39% of runs with three
to five drugs and covered 81% to 87% for the leader.

Because a one-trial drug carries the measure's between-trial variance (2.5), its s_j is never
below that of a multi-trial drug with the same within-trial precision, so its weight is never
the smaller: shrinkage runs the right way round.

For a pair shrunk toward one class mean, the chance of 2.8 uses

```
var = (1 - w_a) s_a^2 + (1 - w_b) s_b^2 + (w_a - w_b)^2 var(mean)
      + (2 / (J - 3)) ((w_a (y_a - mean))^2 + (w_b (y_b - mean))^2)
```

since the class mean is common to both and only the part they weigh differently is uncertain
between them. Any other pair adds the two variances.

**How often it applies.** Once for efficacy in the six indications: the five GLP-1 agonists on
HbA1c against placebo in diabetes (class mean 0.99, between-drug variance 0.137, factor 0.5).

| Drug | Trials | Effect | se | Weight | Counted at |
|---|---|---|---|---|---|
| Semaglutide | 15 | 1.299 | 0.061 | 0.013 | 1.295 |
| Albiglutide | 4 | 1.154 | 0.120 | 0.048 | 1.147 |
| Dulaglutide | 6 | 1.024 | 0.100 | 0.034 | 1.023 |
| Liraglutide | 3 | 0.955 | 0.142 | 0.064 | 0.958 |
| Lixisenatide | 10 | 0.534 | 0.067 | 0.016 | 0.541 |

Never for safety. Revision 2 also shrank safety parts toward the class, and in lung that moved
osimertinib's serious events 19% of the way to an "EGFR inhibitor" average made mostly of
cetuximab and necitumumab given with chemotherapy against chemotherapy: another modality and
another control. The brief described shrinkage of small-trial results; efficacy is where it
applies. The user was told small results would be shrunk toward the drug class average; this
is that, and it bites only where a class has four members on one footing. Three would change nothing, since the small-sample
factor is zero at three (9.1 B). A move of under 5% (`MOVED_MIN`) is not narrated.

### 2.10 Safety

Per drug, for withdrawals for adverse events and for serious adverse events separately.

**A stratum** is one trial's counts, the drug's arms against the control arm, over the same
period (`stratum_counts`). From the per-arm rows of section 4.2:

- Only a trial with a control arm has a stratum. No stratum where the control arm's title
  names the drug.
- The drug's side is the arms whose title names the drug (section 4.1's names, salt words and
  suffixes included), summed. Where no arm's title names it, every arm that is not the
  control, as now: a safety arm has no description, so "Sema 2.4 mg" is reached only this way
  (15 of 47 strata in obesity). An arm whose title names another candidate the control arm
  does not ("Nivolumab 1 mg/kg + Ipilimumab 3 mg/kg" against placebo) is never the drug's.
- Never on the drug's side: an arm that is itself a placebo or a named control; an arm whose
  title marks a switch, a crossover, an extension, an open-label, rescue, long-term or
  follow-up period, or "placebo to", "placebo /", "placebo then" (pattern `_SWITCH`).
- Where the control arm's title states a period or a cohort ("Weeks 1-12", "Period 1", "Part
  A", "Cohort 1", "Sub-study A", "double-blind"), only the drug arms that state the same one
  (pattern `_PERIOD`); failing any, the drug arms that state none. Upadacitinib, NCT02706847:
  the control is "Placebo: Weeks 1-12", so the drug's side is the two "Weeks 1-12" arms (21 of
  329), not those plus the "Weeks 1-260" arms (200 of 943 against 0 of 169 in revision 1).
- The kind is `placebo` where the comparator kind is placebo, else `active`.

**An outcomes trial's serious events are set aside** (`outcome_trials`). Where a trial's
primary endpoint counts cardiovascular, kidney or all-cause death events (a title naming
cardiovascular, MACE, myocardial infarction, stroke, heart failure, renal, kidney, end-stage,
dialysis or all-cause death, and an event word: time to, occurrence, composite, events,
incidence, participants with, hospitalisation), its serious adverse events leave the serious
part: they are largely the heart attacks, strokes or kidney events the trial counts as its
result, so benefit leaks into safety. Its withdrawals and deaths stay. A note names the trials.
SELECT (NCT03574597) held 66% of semaglutide's serious-event weight in obesity: -1.8 points
with it, +0.3 without.

**One kind of control is scored.** Placebo-controlled and active-controlled strata are pooled
apart: an excess over placebo and an excess over another drug are not one quantity (24 of 110
drugs mixed the two in one figure in revision 1). For each part the kind scored is the one
holding more of the drug's people on its arms, placebo on a tie. The other is reported, not
scored. Placebo where it exists would be the purer rule, and it fails on the book: fulvestrant
in breast would be scored on one placebo-controlled trial of 31 people (+35.5 points) and not on
four active-controlled ones of 591 (0.0).

**The pooled difference** (`mantel_haenszel_rd`). Stratum i has x1 events among n1 on the drug
and x0 among n0 on control:

```
w_i = n1 n0 / (n1 + n0)
rd  = sum(w_i (x1/n1 - x0/n0)) / sum(w_i)
var = sum(w_i^2 (p1 (1 - p1) / n1 + p0 (1 - p0) / n0)) / sum(w_i)^2
control rate = sum(w_i x0/n0) / sum(w_i)          drug rate = sum(w_i x1/n1) / sum(w_i)
each rate held inside 0 to 1                      (so an arm with no events reads 0.0%, never -0.0%)
```

- **Mantel-Haenszel, not inverse variance,** because the counts are sparse (a zero cell in 43
  of 442 serious strata and 41 of 202 withdrawal strata) and it needs no correction to the
  estimate. For the variance only, an arm with no events (or only events) uses
  (x + 0.5) / (n + 1) for its p, so an empty arm never claims to be certain.
- **A stratum the average cannot read** (a count above its people, NCT03934216's 11 of 10) is
  left out, and `kept` names the strata read, so the trials listed, the trial named as holding
  most of the weight and the redraw's coefficients all follow the same strata.
- **The two rates are on the pooling weights**, so drug rate minus control rate is the
  difference up to rounding. Revision 1 printed summed rates beside the pooled difference: semaglutide
  in obesity read "-1.9 points ...; 21.1% on the drug, 28.6% on control", a 7.5-point gap beside
  1.9. On the weights the rates are 24.9% and 26.8%.
- **Widened for disagreement between trials** (`dispersion`). The variance above is a
  fixed-effect one. Q_j = sum((d_i - rd)^2 / v_i) over a drug's strata, with v_i each stratum's
  own variance, measures how far they disagree. One factor per indication, part and kind,
  across every drug with two or more strata of that kind, whichever kind is scored for the
  drug: phi = max(1, sum Q_j / sum(k_j - 1)). Every fit of that kind, a one-trial drug's and a
  reported other-kind fit included, has its standard error multiplied by sqrt(phi). Where no drug
  has two strata phi is not known, the standard error is the trial's own and the words say so.
  The table of 1.4 gives the factors. Daratumumab in myeloma: six strata from +4.9 to +20.7
  points, Q = 14.5 on 5 degrees of freedom; with carfilzomib's 7.9 on 3, phi = 22.4 / 8 = 2.80;
  se 1.67 x sqrt(2.80) = 2.80; +12.9 points (+7.4 to +18.4), where revision 1 printed +9.7 to
  +16.2.
- **No shrinkage** (2.9).
- **Deaths** are pooled the same way, reported and never scored.

**The score.** Each part reads its risk difference in percentage points on the existing scale:
`clamp(75 - 5 x 100 x rd)`. Same as control 75; five points of excess 50; fifteen 0; five fewer
100. The safety score is the **mean of the parts, counting equally**, less 10 for a boxed
warning. A part posted for fewer than a quarter of the people behind the other
(`PART_MIN_SHARE` = 0.25) is left out of the score, reported, and named in a note. The
interval printed is held to what is possible: the difference cannot run below minus the
control rate or above one less it. A score that rests on under a fifth of the people treated
in the drug's trials (`THIN_SHARE` = 0.20), or on fewer than 100, carries a "Read with care"
note and `read_with_care` in the output.

Semaglutide in type 2 diabetes: four outcomes trials (NCT01720446, NCT02692716, NCT03819153,
NCT03914326) leave the serious part, which then rests on 7,559 people against active
comparators (0.8 points fewer, part 79). Withdrawals rest on one Phase 2 dose-finding trial of
270 people, NCT00696657: 39 of 270 against 0 of 46 (+14.4 points). 270 is under a quarter of
7,559, so withdrawals are left out and named: safety 79, less 10 for the boxed warning, 69.
Revision 2 weighted by people, which let a part that thin vanish silently; in obesity it gave
semaglutide's one withdrawal trial of 407 people 2% of its score and tirzepatide's seven trials
of 4,123 people half of its.

Semaglutide in obesity, serious events, nineteen placebo-controlled trials once SELECT is set
aside: 0.3 points more than placebo (8.5% against 8.2%). Where one trial holds more than half
the weight (`DOMINANT` = 0.5) the words say so.

Where a zero cell matters: semaglutide in diabetes, withdrawals, one stratum: 39 of 270 against
0 of 46. rd = +14.4 points. Control variance from 0.5 / 47: se = 2.62 points, where the raw
formula gives 2.14.

**What this does not fix.** A risk difference scales with how long each arm was followed, and
the book has no exposure time. Daratumumab lands 4th of 6 in myeloma on safety 10, from a
+12.9-point excess of serious events in six add-on trials where the drug arm stays on treatment
far longer than the control. Rituximab in arthritis reads +25.2 points across four trials, two
of which report 49% and 59% on rituximab against 9% and 10%. An analyst would not read either as
toxicity alone. The line "Counts are people with an event over each arm's whole follow-up; an
arm followed for longer reports more" prints for every drug whose scored control is active or
whose stratum summed more than one arm, and the limit is listed in 9.2. These are not called
corrections.

### 2.11 Uncertainty

**Intervals, in closed form, where there is something for an interval to cover.** The 95%
interval of the averaged effect on the lead measure (2.5) and of each safety risk difference
(2.10) are printed in the words and carried in the output. A score gets no interval: strength
and wins are capped and thresholded quantities with no true value an interval could cover, and
revision 1's redraw left 12 of 92 drugs on the edge of their own interval and 3 with a
zero-width one.

**One range, on the rank.** `DRAWS` = 2,000 redraws, `SEED` = 20260930, numpy `PCG64`. Only the
estimates are redrawn:

1. **Effects.** One standard normal draw per (drug, trial), carried through every cell that
   trial feeds. A cell's effect moves by sum(coef_i x draw_i), coef_i = sqrt(w*_i) / sum(w*),
   which has exactly the cell's variance. Two measures that share trials therefore move
   together. Class means are recomputed from the redrawn effects with the weights held. Size is
   recomputed as in 2.8 with the standard errors held.
2. **Safety.** One draw per (drug, trial), shared by withdrawals and serious events. A risk
   difference moves by sqrt(phi) x sum(coef_i x draw_i), coef_i = w_i sqrt(v_i) / sum(w).
   Through the class weights, the clamp, the people weights and the boxed deduction.
3. **Held at what was observed:** strength and wins (as counted after their move toward the
   drugs' mean), and weight of evidence. A drug with no size has no size in its score, so
   nothing of it is redrawn on the efficacy side; a size counted at 50 (2.13) stays at 50 in
   every draw. Safety parts count equally in each draw, as in the score.
4. Overall is recomputed and the placed drugs ranked in each draw. `rank_range` is the 2.5th and
   97.5th percentile of the rank, rounded.

Draws are taken in a fixed order so a rerun gives the same numbers: `rng =
numpy.random.Generator(numpy.random.PCG64(seed))`; an array `rng.standard_normal((draws, E))`
whose columns are the (asset_id, nct_id) pairs feeding any cell, sorted; then
`rng.standard_normal((draws, S))` for the (asset_id, nct_id) pairs feeding a scored safety part,
sorted.

The range is sampling error in effect size and safety, and the method text says exactly that.
It is not a 95% interval of a score, and nothing on screen calls it one. There is no widening
step: the rank lies inside its range for all 84 placed drugs, and a rank outside it would be a
fault to see, so the book guard asserts it (7.3).

The chance of having the largest effect on a measure, which revision 1 printed, is gone: it was
55% for tirzepatide against 45% for eloralintide on the strength of eloralintide's one trial
looking more certain than tirzepatide's six. The chance of beating a named peer (2.8) carries
what is known.

### 2.12 Weight of evidence and overall

Unchanged: `overall = mean(efficacy, safety, evidence)`, evidence as now, and the bubble size
stays the weight of evidence. It counts everyone treated in a trial with posted safety counts,
controlled or not. The text on screen said "People treated in controlled trials", which was
never true of the figure; it becomes "People treated across its trials with posted safety
counts" (5.4). The safety sentence carries the denominator the score does rest on: "averaged
across 23 of its 46 trials and 16,073 of 30,401 people treated".

Weight of evidence stays because no standard error measures maturity. With overall as the mean
of efficacy and safety alone, obesity ranks eloralintide, one Phase 2 trial of 210 people,
first, above semaglutide and tirzepatide.

### 2.13 Efficacy, and a drug with no comparable peer

`efficacy.score` is the mean of the parts the drug has: strength and wins, and size where it
has a counted cell. A drug with results but no test statistic at all has no efficacy score.

A drug with no ranked cell has no size of its own. Where no cell in the indication is ranked,
its efficacy is the mean of strength and wins, as for every drug there. Where some cell is
ranked, its size counts at 50 (`SIZE_UNKNOWN`). This is not a guess about the drug. Size is
the mean chance of beating each peer, and over the drugs of any cell it averages exactly 50,
since each pair's two chances sum to one. A drug scored without it was scored on strength and
wins alone, which saturate at 100 where every trial clears p = 0.001, against drugs whose third
part averages 50: the unmeasured drug was placed ahead of the measured ones by construction.
Pramlintide (efficacy 100 on a 3.9-point weight loss) plotted right of tirzepatide (98), and
finerenone, with no glucose-lowering result, ranked first in type 2 diabetes. A hold at the best
measured drug's efficacy was tried and does not fix it: in type 2 diabetes it binds on no one,
and insulin glargine (efficacy 92, on two trials against lixisenatide) took first place. At 50,
insulin glargine and finerenone sit level with their peers on size, and the chart draws such
a bubble with a dotted outline and a dagger (5.5). `size_basis` is `"ranked"` for a
drug with a size, `"not comparable"` for a drug without one in an indication where some cell is
ranked, and null where no cell in the indication is ranked (lung, breast, arthritis and
myeloma: every drug is on the same two parts). A "not comparable" drug is marked in the table
with a dagger, its third sentence says why, and its rank line says its rank is on strength and
wins alone (5.1, 5.5). Pramlintide was "not comparable" only because "- evaluable population"
was read as a subgroup; an analysis set is now taken off a title before a subgroup is looked
for (`_ANALYSIS_SET`), and pramlintide is ranked on body weight. In type 2 diabetes finerenone
and insulin glargine remain "not comparable".

This settles decision A of section 9.1 (review round two, blocker): 50 is the scale's average,
stated on screen, and nothing about the drug is filled in.

### 2.14 Constants

| Name | Value | Meaning |
|---|---|---|
| `Z_FULL` | 3.29 | the mean trial z that scores full strength (unchanged) |
| `Z_CAP` | 5.0 | cap on one result's z (unchanged) |
| `P_FLOOR` | 1e-6 | floor on a posted p (unchanged) |
| `SHARED_MIN` | 3 | drugs on a measure and control before it is ranked |
| `CLASS_MIN` | 4 | drugs of one mechanism on a measure and control before the class is a prior |
| `WIN_LEVEL` | 0.025 | one-sided level of a win after the correction |
| `WIN_TOL` | 1e-9 | tolerance on that comparison |
| `AGREE` | 0.25 | tolerance for an analysis estimate against the arms' own difference |
| `OFF_CENTRE` | 0.25 | share of its width an estimate may sit from the middle of its interval |
| `LENGTH_TOL` | 0.25 | how near two drugs' trial lengths must come for a gap to be printed |
| `SAME_TRIALS` | 0.5 | share of trials in common above which two measures count once |
| `DISAGREE_P` | 0.10 | p of a drug's own Q below which its trials "disagree" |
| `DISAGREE_MIN` | 3 | trials before that sentence can print |
| `I2_MIN` | 5 | trials before I2 is quoted |
| `TAU_DF_MIN` | 5 | degrees of freedom the between-trial variance must rest on before a measure is ranked |
| `TAU_DF_FEW` | 10 | degrees of freedom under which a ranked measure's interval is flagged as likely too narrow |
| `TIE` | 0.45 to 0.55 | chance of beating a peer inside which two drugs cannot be separated |
| `MOVED_MIN` | 0.05 | class weight under which the move is not narrated |
| `DOMINANT` | 0.5 | share of a safety weight one trial must exceed to be named |
| `LEVEL` | 95.0 | level of every interval and of the rank range |
| `DRAWS` | 2000 | redraws |
| `SEED` | 20260930 | seed of the redraws |
| `MIN_PARTICIPANTS` | 100 | people on the drug's controlled arms below which safety is flagged |
| `PART_MIN_SHARE` | 0.25 | share of the other part's people under which a safety part is left out of the score |
| `THIN_SHARE` | 0.20 | share of the people treated under which a safety score reads "Read with care" |
| `MEASURE_MAX` | 100 | characters a measure's name may run before it is cut to its first clause |
| `SIZE_UNKNOWN` | 50 | size of a drug with no comparable peer where others have one: the size scale's average |

`LENGTH_TOL` now decides who a drug is compared with, not only whether a gap is printed (2.8).
`Z_WIN`, `UNRANKED_SIZE` and `THIN` do not exist; `SIZE_UNKNOWN` is 2.13's rule. The safety scale constants (`SAME_AS_CONTROL`,
`POINTS_PER_PP`, `BOXED_DEDUCTION`) and `PHASE3_EVIDENCE` are unchanged.

---

## 3. Output of `landscape_score.scorecard()`

Signature unchanged: `scorecard(land: dict, draws: int = DRAWS, seed: int = SEED) -> dict`.
Every key the view reads today keeps its name and meaning. Scores are 0 to 100. Effects are
signed so that more is better. Risk differences are fractions (0.034 is 3.4 points). A null
means the input was not posted or the method was not applied; nothing is filled in.

Semaglutide in obesity, as the prototype returns it (lists shortened):

```json
{
  "assets": [
    {
      "asset_id": 589, "name": "Semaglutide", "ticker": "NVO", "stage": "Marketed",
      "is_marketed": true, "mechanism": "GLP-1 agonist", "boxed": true,
      "pos": null, "per_share": null, "trials_with_results": 24,

      "efficacy": {
        "score": 86.3,
        "parts": {"strength": 100.0, "wins": 100.0, "size": 58.8},
        "size_basis": "ranked",
        "endpoints": 36, "trials": 20, "z": 4.93,
        "wins": 36, "wins_unadjusted": 36,
        "wins_by_control": {"placebo": [35, 35], "active": [1, 1]},
        "tested_here": 0,
        "routes": {"interval": 21, "counts": 15},
        "unscored": 1, "unscored_why": {"direction": 1},
        "pooled": [
          {
            "measure": "percent change in body weight", "control": "placebo",
            "scale": "difference", "lead": true, "counted": true,
            "effect": 10.94, "se": 0.764, "lo": 9.44, "hi": 12.43,
            "own_lo": 10.38, "own_hi": 11.16,
            "hazard_ratio": null, "hazard_ratio_lo": null, "hazard_ratio_hi": null,
            "k": 15, "tau2": 7.93, "tau2_df": 22, "q_p": 0.0, "i2": 0.90,
            "participants": 5427, "weeks": [44, 104], "cell_weeks": [12, 104],
            "routes": ["interval"], "top_dose": 1,
            "trials": ["NCT03548935", "..."], "head_to_head": null,
            "shrunk": 10.94, "shrunk_se": 0.764, "weight": 0.0, "prior": null,
            "ranked": true, "score": 58.8, "rank": 4, "of": 8, "tied_with": [],
            "versus": {
              "asset_id": 13, "name": "Tirzepatide",
              "diff": -7.83, "lo": -10.84, "hi": -4.81, "p_better": 0.0000,
              "same_length": true, "weeks": [52, 72],
              "direct": {"nct_ids": ["NCT05822830"], "diff": -6.5, "lo": -8.1, "hi": -4.9}
            }
          },
          {"measure": "share losing 5% or more of body weight", "control": "placebo",
           "ranked": true, "counted": false, "...": "..."}
        ],
        "lines": ["Won 36 of 36 endpoints in 20 trials, after allowing for the 36 tests run.",
                  "10.9 percentage points better than placebo on percent change in body weight, averaged across 15 trials of 44 to 104 weeks, larger trials counting more (95% interval 9.4 to 12.4).",
                  "Size of effect: 4th of 8 drugs tested against placebo on percent change in body weight, in trials of 12 to 104 weeks; head to head in one trial, 6.5 percentage points behind Tirzepatide (95% interval 4.9 to 8.1)."],
        "notes": ["..."],
        "top": {"z": 26.2, "measure": "change in body weight (%)", "effect": 12.44, "se": 0.474,
                "scale": "difference", "route": "interval", "unit": "Percentage point",
                "nct_id": "NCT03548935", "phase": "Phase 3", "arms": 1,
                "reference_kind": "placebo"}
      },

      "safety": {
        "score": 73.7,
        "parts": {"staying_on": 57.8, "serious": 84.4},
        "part_weights": {"staying_on": 407, "serious": 16984},
        "withdrawn": {
          "kind": "placebo", "rd": 0.0345, "se": 0.0317, "se_own": 0.0169,
          "dispersion": 3.51, "lo": -0.0278, "hi": 0.0967, "k": 1,
          "drug_rate": 0.0639, "control_rate": 0.0294, "n_drug": 407, "n_control": 204,
          "top_share": 1.0, "top_trial": "NCT03611582", "summed_arms": false,
          "shrunk": 0.0345, "shrunk_se": 0.0317, "weight": 0.0, "prior": null,
          "trials": ["NCT03611582"]
        },
        "serious": {
          "kind": "placebo", "rd": -0.0187, "se": 0.0079, "se_own": 0.0051,
          "dispersion": 2.40, "lo": -0.0342, "hi": -0.0032, "k": 20,
          "drug_rate": 0.2489, "control_rate": 0.2676, "n_drug": 16984, "n_control": 12258,
          "top_share": 0.66, "top_trial": "NCT03574597", "summed_arms": true,
          "shrunk": -0.0187, "shrunk_se": 0.0079, "weight": 0.0, "prior": null,
          "trials": ["..."]
        },
        "deaths": {"kind": "placebo", "rd": -0.0067, "lo": -0.0119, "hi": -0.0014, "k": 20,
                   "drug_rate": 0.0285, "control_rate": 0.0351, "...": "..."},
        "other_control": {"serious": null, "withdrawn": null},
        "withdrawn_excess": 3.45, "serious_excess": -1.87,
        "control_kind": "placebo",
        "participants": 17594, "trials": 24,
        "controlled_participants": 16984, "controlled_trials": 20,
        "lines": ["Serious adverse events: -1.9 points against placebo (24.9% against 26.8%), averaged across 20 of its 24 trials and 16,984 of 17,594 people treated (95% interval -3.4 to -0.3)."],
        "notes": ["..."]
      },

      "evidence": {"score": 100.0, "participants": 17594, "phase": "Phase 3",
                   "confidence": "high"},
      "placed": true, "overall": 86.7, "rank": 1, "rank_range": [1, 1],
      "rank_line": "Semaglutide ranks 1 of 9 scored drugs.",
      "why_not": null
    }
  ],
  "placed": 9,
  "total": 32,
  "method": {"efficacy": "...", "safety": "...", "evidence": "...", "overall": "...",
             "uncertainty": "...", "caveat": "..."},
  "simulation": {"draws": 2000, "seed": 20260930, "level": 95.0}
}
```

Field notes.

| Field | New | Type and unit | Null or absent when |
|---|---|---|---|
| `efficacy.parts.size` | no | 0 to 100 | absent when the drug has no counted cell |
| `efficacy.size_basis` | yes | `"ranked"`, `"not comparable"` or null | no efficacy score, or no cell in the indication is ranked |
| `efficacy.endpoints` | no | results scored (drug, trial, outcome) | 0 |
| `efficacy.trials` | yes | trials behind strength and wins | no scored result |
| `efficacy.z` | yes | the mean trial z, each result capped at 5 first | no result with a test statistic |
| `efficacy.wins`, `wins_unadjusted` | yes | endpoints won after and before the correction | no scored result |
| `efficacy.wins_by_control` | yes | `{"placebo": [won, of], "active": [won, of]}` | a kind with no result is absent |
| `efficacy.tested_here` | yes | results with no sponsor p-value on the arm's analysis rows | — |
| `efficacy.routes` | yes | route name to count of results: `interval`, `hazard ratio interval`, `hazard ratio p-value`, `arm spread`, `counts`, `ratio interval`, `p-value`, `p-value bound`, `p-value above`. A result from arms on two routes counts under each | — |
| `efficacy.unscored_why` | yes | reason to count: `direction`, `not its arm`, `in both arms`, `nothing to test`, `no hazard ratio`, `orientation` | empty |
| `efficacy.pooled[]` | yes | one entry per measure and control the drug has an averaged effect on, ranked or not, in the order of 2.8; `lead` marks the one the sentences are written for | empty list |
| `pooled[].scale` | yes | `"difference"`, `"share"` (percentage points of people) or `"log hazard ratio"` | — |
| `pooled[].effect, se, lo, hi` | yes | averaged with the measure's between-trial variance; more is better | — |
| `pooled[].own_lo, own_hi` | yes | the same on the trials' own errors alone; quoted for a one-trial drug | — |
| `pooled[].hazard_ratio*` | yes | exp(-effect), exp(-hi), exp(-lo) | scale is not log hazard ratio |
| `pooled[].tau2, tau2_df` | yes | the measure's between-trial variance and its degrees of freedom | no drug has two trials on the measure |
| `pooled[].q_p` | yes | chi-square p of the drug's own trials' disagreement | one trial |
| `pooled[].i2` | yes | 0 to 1 | fewer than five trials |
| `pooled[].participants` | yes | people on the drug's arms, each trial once | an n was not posted |
| `pooled[].weeks, cell_weeks` | yes | shortest and longest trial, the drug's and the cell's | a length was not posted for every trial |
| `pooled[].top_dose` | yes | results sized on their top arm less the allowance | — |
| `pooled[].head_to_head` | yes | the other candidate the control arm names | the control names no other candidate |
| `pooled[].shrunk, shrunk_se, weight, prior` | yes | after class shrinkage; `prior` is `{label, n, mean}` | `weight` 0 and `prior` null where no class of four shares the cell |
| `pooled[].ranked, counted` | yes | ranked cell; counted in size (2.8) | — |
| `pooled[].score, rank, of, tied_with` | yes | size on the cell 0 to 100; rank, equal effects sharing one; drugs within the tie band | not ranked |
| `pooled[].versus` | yes | the gap to the leader (the runner-up for the leader) on the shrunk effects, its interval and `p_better`; `same_length`; `direct` where a head-to-head trial exists | not ranked |
| `efficacy.top` | changed | the result with the largest z; `effect` and `se` are the test statistic's; `delta`, `p_value` and `arm` are gone | no scored result |
| `efficacy.lines`, `notes` | yes, split | at most three sentences under the chart; the rest on demand (5.1) | no efficacy score |
| `safety.withdrawn`, `serious` | yes | the pooled risk difference of the kind scored, fractions; `se` widened by `dispersion`, `se_own` before; rates on the pooling weights | no controlled trial posted that count in both arms |
| `safety.deaths` | yes | the same, reported and not scored | as above |
| `safety.other_control` | yes | the part on the kind not scored, reported | that kind has no stratum |
| `safety.part_weights` | yes | people on the drug's arms behind each part | — |
| `safety.withdrawn_excess`, `serious_excess` | changed | 100 x the pooled `rd`, percentage points | as the part |
| `safety.control_kind` | changed | `"placebo"`, `"active"` or `"mixed"` (the two parts scored on different kinds) | no part |
| `safety.controlled_participants`, `controlled_trials` | yes | the people and trials the score rests on | no part |
| `safety.lines`, `notes` | yes, split | one sentence under the chart; the rest on demand (5.2) | no safety score |
| `rank_range` | yes | [lo, hi] overall rank | not placed |
| `rank_line` | yes | the open company's line under the table | not placed |
| `why_not` | changed wording | see 5.3 | placed |
| `simulation` | yes | what the rank range rests on | — |

Gone from revision 1: `efficacy.interval`, `safety.interval`, `efficacy.p_best`,
`pooled[].p_best`, `pooled[].model`, `UNRANKED_SIZE`. `placed`, `overall`, `rank` and
`evidence` are computed as now.

---

## 4. What `landscape.py` must pass

No query changes beyond reading columns already selected (`SELECT *`). All additions are in the
in-memory `land` dict. Existing keys stay, so the Evidence and Safety views and the overview are
untouched except as 5.6 says.

### 4.1 `endpoints()`: new keys on each row

| Key | From | Note |
|---|---|---|
| `outcome_index` | `trial_result_outcomes.outcome_index` | the result's identity within its trial |
| `outcome_type` | `outcome_type` | always PRIMARY today; carried so a later read of secondaries cannot go unnoticed |
| `category_index` | position of the row's category in the order the outcome's rows were read | first category is 0 |
| `param` | the outcome row's `param_type` | MEAN, LEAST_SQUARES_MEAN, MEDIAN, COUNT_OF_PARTICIPANTS, NUMBER ... The group-level `param_type` is the first trial's only |
| `lower`, `upper` | the arm's `lower`, `upper` | the arm's own interval |
| `reference_spread`, `reference_lower`, `reference_upper` | the comparator arm's `spread`, `lower`, `upper` | |
| `arm_is_control` | `is_placebo(title, identity)` or (`_CONTROL` matches the title and the title does not mention the drug or any part of it) | an arm that is itself a placebo or a control is never the drug's arm |
| `arm_names_drug` | (`names_drug(title, identity)` or `_described(description, identity)`) and not `claimed_by_other(title, comparator title)` | the title names the drug; or the description names it outside a placebo, dummy, matching, premedication, co-administration, background, rescue or switch setting ("Placebo for ixekizumab", "Dexamethasone coadministered", "rescued with baricitinib" do not); never an arm whose title names another candidate the control lacks ("Nivolumab + Ipilimumab" against placebo; "Liraglutide 1.8 mg" in a semaglutide trial) |
| `reference_is_drug` | the comparator arm's title mentions the drug or any part of it | the shortened-name test of 2.1 runs in the scorer, on `reference_arm` |
| `head_to_head` | the other candidate whose name the comparator arm's title holds and this arm's does not | only where the comparator kind is not placebo |
| `analyses` | every `trial_result_analyses` row whose `group_ids` are exactly this arm and the comparator, in id order | list of `{method, param_type, param_value, ci_pct, ci_lower, ci_upper, p_value}` |

**The drug's names** (`drug_identity`, `identities`). `whole`: the filed names (brand,
generic, code, active ingredients) and the compound name, each also without a salt word
("Osimertinib Mesylate" is named by "Osimertinib 80 mg"). `plain`: a biologic's name without
its FDA suffix ("Cemiplimab" for cemiplimab-rwlc), struck where another candidate holds it as a
whole name (Avastin holds "Bevacizumab", so Mvasi and Zirabev are not named by it). `parts`: a
combination's components, which name it only all together; a filed name that is one component
alone is not a whole name (Xultophy's generic "Insulin Degludec"). `mentions_drug` (whole,
plain or any one part) decides what is never a clean control; `names_drug` (whole, plain or
every part) decides what is the drug's arm.

**The comparator** (`comparator`): a placebo arm (one that mentions the drug is its dummy,
"Pramlintide + Placebo"); else an arm the sponsor names as the control; else, among the
randomised arms (a crossover, extension, open-label or rollover arm is not counted:
"Extension Phase of Docetaxel Arm: Nivolumab"), the one arm that does not name the drug where
at least one does ("Semaglutide 1 mg" against three doses of tirzepatide in SURPASS-2). None
where the drug is named only by a plain name and the other arm carries a development code
("Bevacizumab" against "ABP 215": a biosimilar against its reference product). Before the
review round the salt and suffix names were not read here, so osimertinib (AURA3), cemiplimab
and alectinib lost every two-arm trial against chemotherapy and read "results posted, none
against a comparator".

**The trials** (`candidates`). A condition that carries "non" and one that does not are never
one disease (`condition_matches`): "Small Cell Lung Cancer" had matched "Carcinoma,
Non-Small-Cell Lung" on four of five words, bringing CheckMate 451 and the cabazitaxel and
ipilimumab small cell trials into the non-small cell landscape.

`p_value`, `estimate` and `ci` stay as they are (the first analysis row), for the views that
show them. `dispersion`, `spread`, `n`, `placebo_n`, `value`, `placebo`, `reference_kind`,
`reference_arm`, `time_frame` and `weeks` are already passed.

A row written by an older fixture with no `analyses` key is read as one analysis built from its
`p_value`, `estimate` and `ci` with `ci_pct` null. An interval with no level is never used
(2.3), so such a row takes the p-value route only and nothing is assumed about its interval.

### 4.2 `safety()`: one new key per drug

`strata`: a list, one entry per trial of the drug that has safety rows:

```json
{"nct_id": "NCT02706847", "phase": "Phase 3", "kind": "placebo", "arms": 5,
 "control_title": "Placebo: Weeks 1-12", "control_is_drug": false,
 "control": {"serious": [0, 169], "withdrawn": [0, 0], "deaths": [0, 169]},
 "arm_rows": [
   {"title": "Upadacitinib 15 mg: Weeks 1-12", "is_control": false,
    "serious": [9, 164], "withdrawn": [0, 0], "deaths": [0, 164]},
   {"title": "Upadacitinib 30 mg: Weeks 1-12", "is_control": false,
    "serious": [12, 165], "withdrawn": [0, 0], "deaths": [1, 165]},
   {"title": "Upadacitinib 15 mg: Weeks 1-260", "is_control": false,
    "serious": [87, 236], "withdrawn": [0, 0], "deaths": [9, 236]},
   {"title": "Upadacitinib 30 mg: Weeks 1-260/Switch", "is_control": false,
    "serious": [71, 240], "withdrawn": [0, 0], "deaths": [5, 240]},
   {"title": "Upadacitinib 15 mg After Switch", "is_control": false,
    "serious": [21, 138], "withdrawn": [0, 0], "deaths": [2, 138]}
 ]}
```

Under the rules of 2.10 this stratum is serious events 21 of 329 against 0 of 169 (the two
"Weeks 1-12" arms), deaths 1 of 329 against 0 of 169, and no withdrawals, which were not posted.

Each pair is [events, at risk], with the arm rules the function uses now (the "total" row
dropped, the comparator from `comparator()`). `arm_rows` are the drug's candidate arms one by
one (the arms that name the drug, or every arm that is not the control where none does), so the
scorer can apply the period and switch rules of 2.10; `is_control` marks an arm that is itself a
placebo or a named control. `control` is null and `kind` is null where the trial has no control
arm. `control_is_drug` is the full-name test on the control arm's title. The summed rates the
Safety view shows stay.

### 4.3 Size

The endpoint rows gain eleven scalars and a short list. Lung, the largest, has 2,438 rows; the
overview response grows by well under a megabyte. No cache key changes.

---

## 5. Sentences and the chart

House style throughout: sentence case, number first, no em dash in prose (the dash only as the
null glyph in a table cell), none of the banned words. Every sentence ends with a full stop.

Two lists per side. `lines` are printed under the chart and in the tooltip: at most three for
efficacy and one for safety, four in all. `notes` are printed only inside the existing "What
every score rests on" expander, after the lines. Measured on the prototype: 3.0 to 4.0 lines per
placed drug by indication (revision 1: a mean of 10.3), and 4.8 to 10.2 notes on demand.

### 5.1 Efficacy

`{u}` is "percentage points" for a share or a percent measure, else the unit in lower case.
`{control}` is the control in words (2.8). `{span}` is " of {x} weeks" or " of {x} to {y}
weeks" from the averaged trials' `weeks`, empty for a hazard ratio. Plurals follow the number.

**Lines, in this order.**

| # | When | Template |
|---|---|---|
| 1 | always | `Won {w} of {m} endpoint{s} in {k} trial{s}` + (`, allowing for the number each trial tested` where a trial tested more than one) + (`; {h} of {m} tested here from the posted counts, spread or interval, where the sponsor posted no test` if h > 0) + `.` |
| 2 | lead entry, difference or share | `{abs(effect)} {u} {better or worse} than {control} on {measure}, {where} (95% interval {lo} to {hi}).` with `{where}` = `averaged across {k} trials{span}, larger trials counting more`, or `in one trial{span}` and the interval `own_lo` to `own_hi`. For "worse" the interval is negated and turned round, so both ends read in the word's direction; a share's interval is held to 100 points either way. One place where the largest of the three figures is 1 or more, two down to 0.1, three below; never a negative zero |
| 2 | lead entry, log hazard ratio | `Hazard ratio {hr:.2f} against {control} on {measure}, {where} (95% interval {lo:.2f} to {hi:.2f}).` |
| 3 | lead entry ranked | `Size of effect: {ordinal} of {of} drugs tested against {control} on {measure}` + (`, in trials of {x} to {y} weeks` where the lengths of the drug and its peers differ) + (`, among those whose trials ran about as long` where a drug on the cell was set aside for length) + one tail, below, + `.` |
| 3 | lead entry ranked, tied with a peer | `Size of effect: cannot be separated from {n} of the {m} other drugs tested against ...` + tail |
| 3 | lead entry not ranked, where `size_basis` is "not comparable" or the lead cell had three drugs on a named control | `Size against peers not known: {why}, ` + (`so its size counts at 50, what the average drug scores against its peers` for "not comparable", else `so efficacy is strength and wins alone`) + `.` |
| 3 | no lead entry, `size_basis` "not comparable" | `Size against peers not known: none of its results is on a scale that can be averaged, so its size counts at 50, what the average drug scores against its peers.` |

The tail of line 3, first that applies: a head-to-head trial with the drug it is measured
against (2.8): `; head to head {in one trial or across {n} trials}, {gap}`; that drug is one it
cannot be separated from: nothing; otherwise `; on that basis {gap}`, or
for a hazard ratio `; on that basis, hazard ratio {r:.2f} against {name} (95% interval {..} to
{..})`.

`{gap}`: `{d:.1f} {u} ahead of {name} (95% interval {lo:.1f} to {hi:.1f})` where the interval
is above zero; `{d:.1f} {u} behind {name} (95% interval {..} to {..})` where it is below; else
`{d:.1f} {u} {ahead of or behind} {name}, a gap that could be nothing (95% interval {x} behind
to {y} ahead)`.

`{why}`: `its control arm names no regimen another trial shares`; `its trials, {x} weeks, ran
for a different length from those of the other drugs tested against {control} on {measure}`;
`no drug has two trials on {measure}, so how far trials differ is not known`; `how far trials
differ on {measure} rests on too few trials to compare drugs`; `fewer than three drugs were
tested against {control} on this measure`.

**Notes, in this order.**

| # | When | Template |
|---|---|---|
| 1 | always | `Strength, how far past chance its one trial's result is: z of {z}` or `Strength, how far past chance its average trial result is: z of {z} across {k} trials` + `, where 1.96 is p = 0.05 and 3.29 (p = 0.001) scores 100.` A z of 4.95 or more prints as "5 or more" |
| 1a | strength moved by half a point or more (2.6) | `Strength counted at z {z}: moved {w:.0%} of the way to the average of the {n} drugs here ({mean}), since its one trial says less on its own` (or `its {k} trials say less on their own`) + `.` |
| 1b | wins moved by half a point or more (2.7) | `Wins counted at {x} of 100, from {y}: moved {w:.0%} of the way to the average of the drugs here ({mean}), since ...` + `.` |
| 2 | a win lost to the correction | `{raw} endpoint{s} cleared p = 0.05 before allowing for the number each trial tested.` |
| 2a | non-inferiority results set aside | `{n} result{s} from trials built to show the drug is no worse than its comparator, and not shown better: left out of strength and wins, since the margin each had to clear is not posted.` |
| 3 | both kinds of control | `Against placebo it won {a} of {b}; against active comparators {c} of {d}.` |
| 3 | active only | `Every endpoint is against an active comparator.` |
| 4 | lead k >= 3 and q_p < 0.10 | `Its trials disagree more than chance explains on {measure}` + (`: {i2:.0%} of the variation between them is beyond chance` from five trials) + `.` |
| 5 | lead ranked, one trial, tau2 above 0 | `One trial: its range is widened by how much trials of other drugs varied on this measure.` |
| 6 | lead ranked, or lead averaging two or more trials, tau2 on fewer than 10 df | `Few drugs have two trials on {measure}, so how far trials differ rests on {df} degree{s} of freedom and the interval is likely too narrow.` |
| 7 | lead class weight >= 0.05 | `Counted at {shrunk}: moved {w:.0%} of the way to the average of the {n} {label} drugs on this measure.` |
| 8 | each further counted cell | `Also ranked {ordinal} of {of} against {control} on {measure}.` |
| 9 | each cell not counted as a twin | `Also posted {measure} against {control}, from most of the same trials, so not counted a second time.` |
| 10 | a result from several arms | `{n} result{s} from trials of several doses: tested on all doses together, sized on the best dose, trimmed for having picked the best. Several doses against one placebo arm: the placebo is counted once.` |
| 11 | a randomised-withdrawal result | `{n} result{s} measured from a randomisation after treatment began, where the placebo arm is coming off the drug: counted for strength and wins, not for size.` |
| 12 | a result on a p-value bound below | `{n} result{s} rest on a p-value posted as a bound, read at the bound, which can only understate them.` |
| 13 | a result with only a bound above | `{n} result{s} posted only a p-value above a bound: counted as not won, left out of strength.` |
| 14 | unscored > 0 | `{n} posted endpoint{s} not scored: ` + reasons joined by "; ", each `{label} ({count})` + `.` Labels: no arm names the drug; the comparator arm also contains the drug; nothing posted to test it with; a time to an event with no hazard ratio posted; no arm the book can read as its control; a hazard ratio its medians contradict; direction of benefit not clear |

Semaglutide in obesity, under the chart: "Won 36 of 36 endpoints in 20 trials, after allowing for
the 36 tests run. 10.9 percentage points better than placebo on percent change in body weight,
averaged across 15 trials of 44 to 104 weeks, larger trials counting more (95% interval 9.4 to
12.4). Size of effect: 4th of 8 drugs tested against placebo on percent change in body weight,
in trials of 12 to 104 weeks; head to head in one trial, 6.5 percentage points behind
Tirzepatide (95% interval 4.9 to 8.1)."

Eloralintide in obesity: "Won 1 of 1 endpoint in 1 trial; 1 of 1 tested here from the posted
counts, spread or interval, where the sponsor posted no test. 18.0 percentage points better than
placebo on percent change in body weight, in one trial of 48 weeks (95% interval 14.9 to 21.2).
Size of effect: 2nd of 8 drugs tested against placebo on percent change in body weight, in
trials of 12 to 104 weeks; on that basis 0.7 percentage points behind Tirzepatide, a gap that
could be nothing (95% interval 7.6 behind to 6.1 ahead)."

Nivolumab in lung: "Won 5 of 10 endpoints in 8 trials, after allowing for the 10 tests run; 1
of 10 tested here from the posted counts, spread or interval, where the sponsor posted no test.
Hazard ratio 0.72 against Docetaxel on overall survival, averaged across 3 trials, larger trials
counting more (95% interval 0.60 to 0.86). Size against peers not known: the spread between
trials on overall survival rests on too few trials to compare drugs, so efficacy is strength
and wins alone."

Tirzepatide in type 2 diabetes: "Won 11 of 12 endpoints in 10 trials, after allowing for the 12
tests run; 1 of 12 tested here from the posted counts, spread or interval, where the sponsor
posted no test. 1.7 percentage points better than placebo on change in HbA1c, averaged across 5
trials of 13 to 40 weeks, larger trials counting more (95% interval 1.5 to 2.0). Size of effect:
1st of 14 drugs tested against placebo on change in HbA1c, in trials of 12 to 52 weeks; on that
basis 0.4 percentage points ahead of Orforglipron, a gap that could be nothing (95% interval 0.1
behind to 0.9 ahead)."

### 5.2 Safety

**Line.** The scored part with the most people on the drug's arms behind it:

`{Stopped for side effects or Serious adverse events}: {x} points {more or fewer} than {placebo
or active comparators} ({drug:.1f}% against {control:.1f}%), {where} (95% interval {a} {more or
fewer} to {b} {more or fewer}).` A difference that rounds to 0.0 reads `level with {placebo or
active comparators}`, and an interval end that rounds to 0.0 reads `0.0`. The interval is held
to what is possible (2.10).

`{where}`: where the part rests on every trial the drug has safety rows for, `in its one trial of
{n} people` or `averaged across its {k} trials and {n} people`; otherwise `in 1 of its {T}
trials and {n} of {N} people treated` or `averaged across {k} of its {T} trials and {n} of {N}
people treated`. Points are 100 x the risk difference; the two rates are on the pooling weights,
so they differ by exactly the points quoted.

**Notes, in this order.**

| # | When | Template |
|---|---|---|
| 1 | the other part, scored or not | the line's template for it |
| 2 | a part left out (2.10) | `{Part} left out of the score: posted for {n} people, under a quarter of the {m} behind {other part}.` |
| 3 | k > 1 and one trial holds more than half the weight | `{share:.0%} of the figure for {part} rests on one trial ({nct_id}).` |
| 4 | no dispersion factor for the kind | `No drug here has two controlled trials counting {part}: how far trials differ is not known, so the interval is the trial's own.` |
| 5 | the other kind of control has the part | `{Part}: {x} points {more or fewer} than {placebo or active comparators} in {k} trial{s} and {n} people (95% interval ...), not scored: fewer people than the figure above.` |
| 5a | an outcomes trial set aside | `Serious adverse events leave out {n} outcomes trial{s} ({nct ids}), whose serious events are largely the heart attacks, strokes or kidney events the trial counts as its result.` |
| 6 | both parts scored | `Stopped for side effects and serious adverse events count equally.` |
| 7 | a scored kind is active, or a stratum summed several arms | `Counts are people with an event over each arm's whole follow-up; an arm followed for longer reports more.` |
| 8 | boxed | `FDA boxed warning, 10 points off: {headline}.` The headline is the label's first sentence as a clause (`_boxed_text`): an all-capitals heading the text repeats is dropped, a brand name the label runs on at its end is taken off, words in capitals are put in sentence case |
| 9 | deaths | `Deaths, reported and not scored: {x} points {more or fewer} than control ({drug:.1f}% against {control:.1f}%) {in one trial or across {k} trials}.` |
| 10 | people on the drug's controlled arms under 100 | `Read with care: {n} people treated in its controlled trials.` |
| 10 | else the score rests on under a fifth of the people treated | `Read with care: the safety score rests on {n} of the {N} people treated in its trials ({share:.0%}).` Also `read_with_care` in the output and the tooltip |

Semaglutide in obesity, under the chart: "Serious adverse events: -1.9 points against placebo
(24.9% against 26.8%), averaged across 20 of its 24 trials and 16,984 of 17,594 people treated
(95% interval -3.4 to -0.3)." On demand: "Stopped for side effects: +3.4 points against placebo
(6.4% against 2.9%), in 1 of its 24 trials and 407 of 17,594 people treated (95% interval -2.8
to +9.7). 66% of the figure for serious adverse events rests on one trial (NCT03574597). The two
parts count by the people behind each: 407 for stopping, 16,984 for serious events. Counts are
people with an event over each arm's whole follow-up; an arm followed for longer reports more.
FDA boxed warning, 10 points off: Risk of thyroid C-cell tumors. Deaths, reported and not
scored: -0.7 points against control (2.8% against 3.5%) across 20 trials."

### 5.3 `why_not`

| Was | Becomes |
|---|---|
| `no posted results` | unchanged |
| `results posted, none against a comparator` | `results posted, none against a control arm the book can identify`, only where `no control` is the commonest unscored reason |
| `no efficacy endpoint with a p-value against a comparator` | `only results from trials built to show it no worse than a comparator` where every result was set aside (2.7); else the commonest reason among its unscored endpoints: `no result on an arm that is the drug's alone` (not its arm, in both arms), `time-to-event results with no hazard ratio posted`, `no endpoint whose direction of benefit is clear`, else `no efficacy endpoint that can be tested against a comparator` |
| `no safety figure against a control` | `no controlled trial with safety counts` |

### 5.4 `method`

- `efficacy`: "Mean of strength, wins and size against peers. Strength: how far past chance the average trial result is; 100 at p = 0.001, a drug with one or two trials moved toward the average of the drugs here. Wins: the average share of a trial's endpoints won, allowing for the number that trial tested. Size: the chance of beating each drug tested against the same control on the same measure in trials of about the same length, from its trial results averaged. Where four or more drugs of one mechanism class share a measure and a control, each is first moved part of the way to the class average. Where no measure here is ranked, efficacy is strength and wins alone; where some are and a drug is on none, its size counts at 50, what the average drug scores against its peers. A result from a trial built to show a drug no worse than its comparator is left out unless it shows it better."
- `safety`: "Stopped for side effects and serious adverse events, each the difference from control averaged trial by trial over controlled trials, against placebo or against active comparators, whichever holds more of the drug's people: 75 when equal to control and 5 points per percentage point of excess. The two count equally; a part posted for under a quarter of the people behind the other is left out and named. An outcomes trial's serious adverse events are left out, since they are largely the events it counts as its result. Less 10 for an FDA boxed warning. Deaths are reported, not scored."
- `evidence`: "People treated across its trials with posted safety counts, on a log scale (100 people 25, 1,000 people 50, 10,000 people 75), plus 20 for Phase 3 results." The figure is
  unchanged; the words were wrong before ("in controlled trials").
- `overall`: "The mean of efficacy, safety and weight of evidence."
- `uncertainty` (new): "The chart shows scores, not measurements, so it draws no error bars. The range beside a rank is where it falls 95 times in 100 when every trial's effect size and safety count is varied within its margin of error."
- `caveat`: "Scores cross trials that differ in who they enrolled, for how long and against what. Drugs are compared on size only where they were tested against the same control; the book cannot see the background treatment behind a placebo, or how long each arm was followed for safety. A result with no sponsor test is tested here from its posted counts, spread or interval, every interval read as two-sided, an arm with no events given half an event for its margin of error, and a hazard ratio read as the drug against its comparator. The scores order the evidence; they are not a head-to-head result."

### 5.5 The chart, the table and the tooltip

The view stays one chart, one table and the words under them.

- **Chart** (`score_map`). No interval cross: a score has no interval (2.11), and the words
  say "The chart shows scores, not measurements, so it draws no error bars". Each bubble
  carries its rank in the table, so the two read together without a label; the bubble runs
  from radius 6 to 15 by weight of evidence so the number fits. The top five by rank are
  labelled first, then the open company's drugs, then peers best first while room lasts; a
  label that cannot sit beside its bubble goes to free space further out with a thin leader
  line, or is left off (the fallback that clamped a label back over its own bubble is gone).
  The open company's bubbles are ringed with the page colour, so two that overlap stay two. A
  "not comparable" drug is drawn with a dotted outline and a dagger after its name, with a key
  entry "† size not compared". Where no measure in the indication is ranked the axis reads
  "efficacy score (strength and wins, no size)".
- **Tooltip.** The head becomes `{name} ({ticker}), {stage}. Overall {o:.0f}, rank {rank}` +
  (` (could sit {lo} to {hi})` where lo differs from hi) + `: efficacy {e:.0f}, safety {s:.0f},
  evidence {v:.0f}.` Then the drug's lines, as now.
- **Table.** One narrow column after the rank, headed "range", reading `{lo} to {hi}` in the
  muted style, and the rank itself where the two are equal ("1"). A drug whose `size_basis` is
  "not comparable" carries a dagger after its efficacy figure, and one muted line under the
  table explains it wherever a dagger shows: "† Size of effect not compared: no peer was
  tested against the same control on the same measure in trials of about the same length, so
  its size counts at 50, what the average drug scores against its peers."
- **Header.** "efficacy, safety and weight of evidence, averaged · posted results only".
- **How to read it** adds that the scorecard averages a drug's trials while the cards below it
  quote a single best result, so the two figures for one drug can differ (tirzepatide in
  obesity: 18.8 points averaged across five trials, 24.4 in its best).
- **Not on the chart.** "Not on the chart, because a score is never guessed." then each reason
  as its own sentence, so no capital follows a colon.
- **The open company's line** under the table is `rank_line`: `{name} ranks {rank} of {n}
  scored drugs` + (`, and could sit anywhere from {lo} to {hi}` where lo differs from hi) +
  (`, with its size of effect not comparable with peers and counted at 50, the average` for a
  "not comparable" drug) + `.`
- **Under the table**, for up to four of the open company's drugs, the lines only. The
  expander "What every score rests on" prints every placed drug's lines and then its notes.
- **How it is scored** gains `method.uncertainty` after the overall sentence.

### 5.6 The overview under the scorecard

The "Easiest and hardest to tolerate" card and the "Benefit against tolerability" chart sit
directly under the scorecard and read `withdrawn_rate` minus `placebo_withdrawn_rate` from
`land["safety"]`, summed across trials. After this change they would disagree with the
scorecard on the same screen (liraglutide in obesity: +6.9 points summed, +2.2 pooled). One
function changes, on data already held:

- `landscape_overview.overview(land, endpoint_key=None, scorecard=None)`. `main.py` computes
  the scorecard once and passes it. Where it is given, each drug's stopping figure is its
  scorecard `safety.withdrawn`: `rd` for the chart's y (`dropout_excess`, in points), the two
  rates on the pooling weights for the card, and the drug is included where `n_drug` is at
  least `MIN_PARTICIPANTS`. The card's detail names what each figure rests on: `{name}:
  {drug:.1f}% stopped because of side effects against {control:.1f}% on control, {in one trial
  or averaged across {k} trials} of {n} people ({rd:+.1f} points).` Without a scorecard it
  reads as now, so no other caller changes.
- The "Most effective" card and the ranked bars keep each drug's best dose, which is what they
  say they show. The bars' basis line gains one sentence: "The scorecard above sizes a trial of
  several doses on its most effective dose less an allowance for picking it, so its figure can
  be lower."

What the card reads, before and after:

| Indication | Easiest, summed | Easiest, pooled | Hardest, summed | Hardest, pooled |
|---|---|---|---|---|
| Obesity | eloralintide -0.9 | eloralintide -0.9 | naltrexone + oxycodone +11.2 | naltrexone + oxycodone +11.8 |
| Lung | osimertinib -5.8 | necitumumab -5.5 | aflibercept +12.6 | aflibercept +12.6 |
| Breast | olaparib -15.3 | denosumab -1.7 | ribociclib +14.5 | sorafenib +14.4 |
| Type 2 diabetes | canagliflozin + metformin -0.3 | ertugliflozin -0.6 | naltrexone + oxycodone +14.0 | semaglutide +14.4 |
| Arthritis | tofacitinib -6.8 | tofacitinib -2.7 | tocilizumab +6.6 | secukinumab +5.5 |
| Myeloma | elotuzumab -12.0 | vorinostat 0.0 | carfilzomib +2.1 | carfilzomib +2.0 |

Two of these need the words the card now carries. Semaglutide is hardest to stay on in type 2
diabetes on one Phase 2 dose-finding trial of 270 people (NCT00696657, 39 of 270 against 0 of
46), and the card says "in one trial of 270 people". Naltrexone + oxycodone is an upstream
mislabel (9.2).

---

## 6. `backend/meta_stats.py`

Pure functions. No database, no knowledge of drugs. Standard library only, except
`normal_draws`, which uses numpy (installed; scipy and statsmodels are not and are not needed).
Python 3.9: `from __future__ import annotations`. A function returns None where an input it needs
is missing; it never fills one in. The prototype file can be copied as it stands.

Module constants: `Z95 = 1.959964`, `Z_CAP = 5.0`, `P_FLOOR = 1e-6`, `OFF_CENTRE = 0.25`.

Each function below has its contract and cases worked by hand, which are also its tests.

### 6.1 Levels and p-values

`z_of_level(ci_pct) -> float | None`: the normal deviate of a two-sided level; a value between
0.5 and 1 is a fraction; None outside (50, 100) or for None.
Cases: 95 → 1.959964; 90 → 1.644854; 0.95 → 1.959964; 96.85 → 2.150699; 100 → None.

`parse_p(text) -> tuple[float, str] | None`: (p, kind), kind `exact`, `below` or `above`.
Cases: "<0.001" → (0.001, "below"); "0.0003" → (0.0003, "exact"); ">0.05" → (0.05, "above");
"NA" → None; "1.4" → None.

`z_of_p(p, one_sided=False) -> float`: unsigned deviate, p floored at `P_FLOOR`, capped at
`Z_CAP`. Cases: 0.05 → 1.959964; 0.001 → 3.290527; (0.025, one-sided) → 1.959964; 0 →
4.891638; 0.0003 → 3.615300.

`p_one_sided(z) -> float`: 1 - Φ(z). Cases: 1.959964 → 0.025; 0 → 0.5; -1.644854 → 0.95.

`p_above(diff, var) -> float`: Φ(diff / sqrt(var)); 0.5 on an exact tie with no variance.
Cases: (1, 4) → 0.691462; (0, 0) → 0.5; (2, 0) → 1.0; (-1, 1) → 0.158655.

### 6.2 Standard-error routes

`interval_is_sound(estimate, lower, upper, log=False) -> bool`: lower < estimate < upper and the
estimate within `OFF_CENTRE` of the width of the midpoint, on the log scale for a ratio.
Cases: (-12.44, -13.37, -11.51) → True; (-0.74, -90.0, -0.57) → False; (0.59, 0.43, 0.81, log)
→ True; (2.0, 1.0, 1.5) → False; (None, 1, 2) → False; (0.97, 0.848, 1.114, log) → True.

`se_from_ci(lower, upper, ci_pct, log=False) -> float | None`: width over 2 z(level). None
without both bounds, a level, a positive width, or (log) positive bounds.
Cases: (-13.37, -11.51, 95) → 0.474499; (0.43, 0.81, 96.85, log) → 0.147219; (0.848, 1.114,
95.6, log) → 0.067731; (None, 1, 95), (1, 1, 95), (-0.1, 0.8, 95, log), (1, 2, None) → None.

`se_from_spread(spread, n, ref_spread, ref_n, kind) -> tuple[float, float] | None`: (se,
control variance); `kind` "sd" needs both n. Cases: (0.66, 194, 0.63, 188, "se") → (0.912414,
0.3969); (8.1, 97, 6.2, 95, "sd") → (1.039723, 0.404632); (10.1, None, 6.5, 655, "sd") → None.

`se_from_arm_ci(lower, upper, ref_lower, ref_upper, ci_pct)`: each arm's se from its own
interval. Case: (1.0, 3.0, 0.0, 1.0, 95) → (0.570436, 0.065079).

`two_proportions(x, n, ref_x, ref_n) -> tuple[float, float, float] | None`: (risk difference,
se, control variance), fractions; a share of 0 or 1 takes (x + 0.5) / (n + 1) for its variance.
Cases: (267, 404, 107, 403) → (0.395382, 0.032228, 0.000484); (39, 270, 0, 46) → (0.144444,
0.026201, 0.000229); (5, 4, 1, 10) → None.

`se_from_p(delta, p, kind="exact", one_sided=False) -> tuple[float, bool] | None`: (|delta| /
z_p, is_bound). None for a zero or missing delta, a bound above, or z_p under 0.01.
Cases: (3.45, 0.0003) → (0.954278, False); (12.44, 0.0001, "below") → (3.197457, True); (1.0,
0.05, "above") → None; (0, 0.01) → None; (2.0, 0.025, "exact", True) → (1.020427, False);
(-ln 0.82, 0.148) → (0.137181, False).

### 6.3 One result per trial

`combine_arms(effects, ses, ns=None, ref_n=None, control_vars=None) -> tuple[float, float] |
None`: the test statistic of 2.4. Cases: SURMOUNT-1 ([13.5, 18.9, 20.1], [0.5357, 0.5612,
0.5612], [623, 629, 625], 635) → (17.507246, 0.450593); ([4.0, 6.0], [1.0, 2.0]) → (5.0, 1.5),
fully correlated; ([4.0, 6.0], [1.0, 1.0], [100, 100], 100, [0.5, 0.5]) → (5.0, 0.866025).

`expected_max_normal(k) -> float`: E[max of k standard normals], by Simpson's rule. Cases: 1 →
0; 2 → 0.564190; 3 → 0.846284; 4 → 1.029375; 5 → 1.162964; 6 → 1.267206.

`top_arm(effects, ses, ns=None, ref_n=None, control_vars=None) -> dict | None`: the size of 2.4,
`{effect, se, index, arms, allowance}`. Cases: SURMOUNT-1 → effect 19.76284, se 0.5612,
allowance 0.33716; ([4.0, 6.0], [1.0, 2.0]) → effect 4.871621, se 2.0, allowance 1.128379;
([4.0, 6.0], [1.0, 1.0], [100, 100], 100, [0.5, 0.5]) → effect 5.601058, allowance 0.398942;
([3.0], [0.5]) → effect 3.0, allowance 0.

`combine_repeats(effects, ses)`: precision-weighted mean, se the weighted mean of the se.
Case: ([12.99, 13.40], [1.1684, 1.1709]) → (13.194562, 1.169647).

### 6.4 Between trials

`chi2_sf(q, df) -> float | None`: upper tail of chi-square, by the incomplete gamma function.
Cases: (3.841459, 1) → 0.05; (16, 2) → 0.000335; (0, 3) → 1.0; (22, 22) → 0.459889; (9.95, 1)
→ 0.001608.

`heterogeneity(effects, ses) -> dict | None`: `{q, df, c}`, None under two trials. Cases: ([10,
6, 2], [1, 1, 2]) → q 16.0, df 2, c 1.333333; ([5, 5.2], [0.5, 0.5]) → q 0.08, df 1, c 4.0.

`common_tau2(cells) -> dict | None`: `{tau2, q, df, cells}` from every cell with two or more
trials; None where none has. Cases: the two cells above plus ([3.0], [0.5]) → tau2 (16.08 - 3)
/ 5.333333 = 2.4525, q 16.08, df 3, cells 2; ([3.0], [0.5]) and ([4.0], [1.0]) → None; ([5, 5.2],
[0.5, 0.5]) alone → tau2 0.

`pool_common(effects, ses, tau2, level=95.0) -> dict | None`: `{effect, se, lo, hi, k,
tau2_known, q, q_p, i2, coef}` (2.5). Cases with tau2 = 2.4525: ([10, 6, 2], [1, 1, 2]) →
effect 6.733608, se 1.167004, q_p 0.000335, i2 None; ([5, 5.2], [0.5, 0.5]) → effect 5.1, se
1.162433; ([3.0], [0.5]) → effect 3.0, se 1.643928 (sqrt(0.25 + 2.4525)). With tau2 None:
([3.0], [0.5]) → se 0.5, `tau2_known` False. Orforglipron, ([7.975, 7.236], [0.5153, 1.3597],
7.932) → effect 7.63804, se 2.111806.

### 6.5 Many endpoints

`benjamini_hochberg(pvalues) -> list[float]`: adjusted p in the order given.
Cases: the pertuzumab one-sided p of 2.7 → [0.0042, 0.01085, 0.034825, 0.034825, 0.05894,
0.122383, 0.1666]; [0.04] → [0.04]; [0.01, 0.04, 0.03] → [0.03, 0.04, 0.04]; four results
against the drug (one-sided p 0.9995) and one for it at z 2.054 → the last 0.099939, and the
same 0.099939 with four flat results at 0.5: results against the drug loosen nothing.

### 6.6 Shrinkage

`shrink(effects, ses) -> dict | None`: 2.9, `{mean, mean_se, tau2, factor, shrunk, se, weight,
mean_weight}`; None under four drugs.
Case: ([10, 6, 2, 7], [1, 1, 2, 1]) → tau2 5.666667, mean 6.607477, factor 1/3, weight 0.05,
0.05, 0.137931, 0.05, shrunk 9.830374, 6.030374, 2.635514, 6.980374, se 1.006014, 0.977938,
2.07133, 0.977388. Drugs that agree, ([5, 5.2, 4.9, 5.1], [0.5] x 4) → tau2 0, every weight
1/3 (never 1), shrunk 5.016667, 5.15, 4.95, 5.083333, se 0.417333 to 0.422624, each above
sqrt(2/3) x 0.5 = 0.408. Three drugs → None.

`bucher(effect_a, se_a, effect_b, se_b, level=95.0) -> dict`: `{diff, se, lo, hi, p_better}`.
Cases: tirzepatide against semaglutide (18.763, 1.335, 10.937, 0.764) → diff 7.826, se 1.538155,
lo 4.811271, hi 10.840729; tirzepatide against eloralintide (18.763, 1.335, 18.040, 3.237) →
diff 0.723, se 3.501485, lo -6.139784, hi 7.585784, p_better 0.581794.

### 6.7 Safety

`mantel_haenszel_rd(strata, level=95.0) -> dict | None`: 2.10, `{rd, se, lo, hi, k, drug_rate,
control_rate, n_drug, n_control, q, df, top_share, coef}`; `se` before widening.
Cases: [(10, 100, 5, 100), (30, 200, 10, 100)] → rd 0.05, se 0.02747, drug_rate 0.128571,
control_rate 0.078571, q 0, top_share 0.571429; [(10, 100, 5, 100), (60, 200, 10, 100)] → rd
0.135714, se 0.029821, q 7.462537; daratumumab's six strata [(186, 346, 117, 354), (289, 364,
262, 365), (205, 283, 148, 281), (142, 197, 131, 195), (29, 96, 22, 98), (56, 193, 38, 196)] →
rd 0.129269, se 0.016715, drug_rate 0.612432, control_rate 0.483163, q 14.501981, df 5;
[(0, 50, 0, 50)] → rd 0, se 0.019706; [(39, 270, 0, 46)] → rd 0.144444, se 0.026201.

`dispersion(fits) -> float | None`: max(1, sum q / sum df) over fits with two or more strata.
Cases: the second case and daratumumab → (7.462537 + 14.501981) / 6 = 3.660753; one fit of one
stratum → None; the first case alone → 1.0.

### 6.8 Simulation

`normal_draws(n, size, seed)`: an n by size array from `numpy.random.Generator(PCG64(seed))`.
`interval(values, level=95.0) -> tuple[float, float]`: the central share by linear
interpolation. Cases: (0, 1, ..., 100) → (2.5, 97.5); [1.0] → (1.0, 1.0).

The redraw itself (2.11) lives in `landscape_score`, since it knows what a drug and a trial
are.

---

## 7. Tests

### 7.1 `backend/tests/test_meta_stats.py` (new)

One test per function asserting every case of section 6 to four decimal places
(`pytest.approx(..., abs=1e-4)`), and these properties:

1. `se_from_ci` on a level written 0.95 equals the same call at 95.
2. `two_proportions` is antisymmetric: swapping the arms negates the difference and keeps the se.
3. `combine_arms` with one arm returns it; its se never falls below sqrt of the control variance.
4. `top_arm` with one arm returns it with allowance 0; the allowance grows with k at equal
   errors; the effect never exceeds the best arm's.
5. `common_tau2` is None when no cell has two trials and 0 when every cell agrees;
   `pool_common` with tau2 0 is the inverse-variance answer, and a one-trial pool has se^2 =
   s^2 + tau2.
6. **A one-trial drug is never the more certain.** Two cells on one measure with every trial's
   se 1.0, one of three trials and one of one: after `common_tau2` and `pool_common` the
   one-trial cell's se is the larger, and passed to `shrink` with two more drugs its weight is
   the larger.
7. `chi2_sf` is 0.05 at 3.841459 on 1 df and decreasing in q.
8. `benjamini_hochberg` returns values no smaller than its inputs, no larger than 1, in input
   order, monotone in p; adding results with p near 1 never lowers another result's adjusted p.
9. `shrink` returns None under four drugs; moves every effect toward the mean and never past it;
   no weight exceeds (J - 3) / (J - 1); every se is at least sqrt(1 - weight) times the drug's own.
10. `p_above(d, v) + p_above(-d, v) == 1`.
11. `mantel_haenszel_rd`: one stratum equals `two_proportions` on the same counts; strata sharing
    one difference return it with q 0; a stratum with a missing n is dropped; **drug_rate minus
    control_rate equals rd to 1e-12 for any strata**.
12. `dispersion` is None with no fit of two strata and never below 1.
13. `normal_draws` with one seed is equal across calls and differs with another; over 100,000
    draws its mean is within 0.02 of 0 and its sd within 0.02 of 1. No test hard-codes a draw.
14. No function raises on None inputs.
15. The module imports without scipy or statsmodels (neither in `sys.modules` after importing it
    in a fresh interpreter).

### 7.2 `backend/tests/test_landscape_score.py` (updated)

Tests that stay: the p-value parsing, the measure families, `comparable_delta`, the drug with no
posted result, the chart drawing. The `_land()` fixture gains the row keys of 4.1 and `strata`.
New or rewritten:

1. **Doses: tested together, sized on the top arm.** Alpha has two arms in one trial, -20 (95%
   interval -22 to -18) and -10 (-12 to -8), 100 people each and 100 on placebo. The test
   statistic is 15.0 (se 0.8837); the size is 20 - 0.5642 x sqrt(1.0412 - 0.5206) = 19.593, se
   1.0204; the trial counts once.
2. **A complement is never the result**: "No" then "Yes" scores the "Yes" row.
3. **A baseline is not scored.**
4. **An arm that is a control is never pooled**; an arm with no analysis row is left out when
   another arm has one.
5. **A total arm is dropped**: n 200, 100, 100 pools the last two.
6. **The interval outranks the p-value**: a hazard ratio of 0.97 (95.6% interval 0.848 to
   1.114) with p "<0.001" scores z = 0.45 and is not a win.
7. **Spread**: -1.56 (sd 1.09, n 225) against -1.22 (sd 1.16, n 222) gives z = 3.19; a
   least-squares mean posted with a "Standard Deviation" is unscored and counted, reason
   `nothing to test`.
8. **A rate is not a share**: "Episodes per 100 patient-years" never takes the counts route.
9. **A family fixes the sign**: "Change From Baseline to Week 26 in HbA1c Bayesian Dose
   Response" is lower-is-better. **Events are lower-is-better**: "Percentage of Participants With
   Invasive Disease-Free Survival (IDFS) Event", 7.1% of 2,400 against 8.7% of 2,404, is a result
   for the drug (z about 2.06).
10. **A1C is HbA1c**: "Change From Baseline in Hemoglobin A1C (A1C)" and "Change in A1C" join
    "change in HbA1c".
11. **Survival needs a hazard ratio**: medians with intervals and no analysis row leave the
    result unscored, reason `no hazard ratio`; a drug with only such results has `why_not`
    "survival results with no hazard ratio posted"; no route is named "ratio of medians".
12. **Whose result**: a comparator titled "Placebo + Sitagliptin" or "Pembro + Placebo" makes
    the result unscored, reason `in both arms`, for sitagliptin and pembrolizumab; "Arm B: Nivo
    Placebo + Chemo" and "Insulin Glargine" do not, for nivolumab and insulin icodec; a result
    where no arm names the drug is unscored, reason `not its arm`, with no fallback.
13. **Strength is the mean trial z**: two trials at z 2.77 and 2.62 give strength 81.9, and
    so do two endpoints of one trial at the same values; ten trials at z 5 give 100 and `z` 5.
14. **Wins**: the pertuzumab p-values give 2 wins of 7 and `wins_unadjusted` 4; four results
    against the drug at z -3.29 and one for it at z 2.054 give no win; a lone posted "<0.05"
    is a win; wins is the mean over trials of each trial's share.
15. **One between-trial variance**: drugs A (three trials) and B (one trial) with every trial se
    1.0 on one measure: B's pooled se^2 is 1 + tau2 and above A's.
16. **The control key**: "Placebo + Docetaxel 75 mg/m^2", "Placebo/Docetaxel" and "Docetaxel"
    give "docetaxel"; "Chemotherapy" and "Physician's Choice" give None; "Placebo" gives
    "placebo alone"; three drugs against placebo with letrozole and three against placebo alone
    make two cells.
17. **The ranking floor**: three drugs on one control, the measure's tau2 on 2 degrees of
    freedom: no rank, no size, and line 3 reads "the spread between trials ... rests on too few
    trials to compare drugs"; with five more drugs of two trials each on the measure (5 degrees
    of freedom), the three are ranked.
18. **Twins count once**: a drug's two ranked cells sharing more than half their trials count the
    one with more drugs and name the other.
19. **Class only at four**: four drugs of one class plus two others: `prior` on the four only,
    each weight at most 1/3; three of a class: no prior anywhere.
20. **Ties**: equal effects share a rank; a chance of beating a peer between 0.45 and 0.55 prints
    "cannot be separated".
21. **Head to head**: A leads, B is second and B's record holds a trial against A on the
    measure: B's line 3 prints the direct result, and A's prints the same trial turned round;
    trials of 28 against 52 to 72 weeks print "not compared with".
22. **No size is filled in**: a drug with no ranked cell in an indication with one has no `size`,
    `size_basis` "not comparable", efficacy the mean of strength and wins, and its `rank_line`
    ends "on strength and wins alone: its effect size cannot be compared with peers."
23. **Safety**: daratumumab's strata give `rd` 0.1293 before widening; a drug with placebo and
    active strata scores the kind with more people and reports the other; an arm titled
    "Placebo to Upadacitinib" or "Open-label extension" is never on the drug's side; a control
    titled "Placebo: Weeks 1-12" takes only the "Weeks 1-12" drug arms; a control naming the
    drug gives no stratum; with no controlled trial the drug has no safety score and `why_not`
    reads "no controlled trial with safety counts".
24. **Parts count by people**: parts of 13 on 270 people and 85 on 16,073 give 83.8 before the
    boxed deduction.
25. **Rank range**: every placed drug has one containing its rank; a second call returns identical
    values; `draws=200` returns; there is no `efficacy.interval` or `safety.interval`.
26. **Words**: at most three efficacy lines and one safety line; no line contains an em dash or a
    banned word; every line and note ends with a full stop.
27. **Old fixtures**: a row with only `p_value`, `delta` and `ci` and no `analyses` is scored by
    the p-value route, and its `ci` is not read.
28. **The overview reads the scorecard**: `overview(land, scorecard=sc)` puts each drug's pooled
    stopping figure on the card and the chart; without `scorecard` it reads as today.

### 7.3 Book guard

One test on the `book` fixture, run off a backup with `ER_TOOL_DB`, over the six indications
(367, 20, 371, 1, 383, 101). For every indication:

- every placed drug's rank lies inside its `rank_range`;
- drug rate minus control rate equals `rd` to 1e-12 for every safety part and deaths;
- no averaged effect has a standard error of zero or below;
- no result on the arm-spread route has |z| above 40 before the cap;
- no averaged effect whose own I2 (from its Q, at any k of two or more) is above 0.95 has trial
  effects of both signs;
- no route is named "ratio of medians";
- at most four lines per placed drug, in house style;
- the call takes under two seconds.

And by indication:

- **Obesity (367)**: at least eight drugs placed; semaglutide and tirzepatide the top two;
  tirzepatide's averaged percent change in body weight against placebo between 14 and 22 with
  `k` at least 5.
- **Type 2 diabetes (1)**: tirzepatide first on change in HbA1c against placebo (1.73, k 5).
- **Lung (20)**: osimertinib and pembrolizumab in the top three; NCT03976362 unscored for
  pembrolizumab, reason `in both arms`.
- **Myeloma (101)**: the rank order is printed with each drug's safety score, asserting nothing,
  so a reviewer sees daratumumab 4th of 6 on safety 10 before this ships (2.10, 9.1 D).

All of these hold on the prototype.

---

## 8. Before and after on six indications

The tables of this section are revision 2's, before the second review round. Appendix B gives
what that round changed and the top five it leaves in obesity, lung, breast and type 2
diabetes.

Before is `landscape_score.scorecard` as committed (last changed in 87f95f5). After is the
prototype of this specification on the same land, with the constants of 2.14. Scores are
rounded. The rank range is where the rank falls in 95 of 100 redraws (2.11); a single figure
means it never moved. A dagger marks a drug whose efficacy is strength and wins alone in an
indication where some measure is ranked (2.13). The second table of each indication names every
drug that moves more than ten points on efficacy, safety or overall, or gains or loses its
place, with the parts that moved most (eight points or more).

### Obesity (indication 367)

10 drugs placed before, 9 after, of 32 candidates.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Semaglutide | 1 → 1 | 92 → 86 | 73 → 74 | 88 → 87 | 1 |
| Tirzepatide | 2 → 2 | 99 → 98 | 63 → 61 | 83 → 82 | 2 to 3 |
| Liraglutide | 7 → 3 | 71 → 73 | 35 → 59 | 65 → 74 | 3 to 6 |
| Pramlintide | 4 → 4 | 88 → 100 † | 67 → 67 | 68 → 72 | 3 to 7 |
| Orforglipron | 3 → 5 | 83 → 79 | 62 → 61 | 72 → 71 | 3 to 7 |
| Eloralintide | 6 → 6 | 88 → 96 | 78 → 78 | 66 → 69 | 3 to 9 |
| Berobenatide | 8 → 7 | 88 → 90 | 67 → 67 | 62 → 63 | 4 to 9 |
| Canagliflozin | 9 → 8 | 79 → 77 | 68 → 68 | 59 → 58 | 6 to 9 |
| Canagliflozin + Metformin | 10 → 9 | 67 → 68 | 64 → 64 | 56 → 56 | 7 to 9 |
| Naltrexone + Oxycodone | 5 → — | 73 → — | 45 → 49 | 67 → — | — |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Liraglutide | 71 → 73 | 35 → 59 | 65 → 74 | staying on treatment 40 → 64; serious events 49 → 72 |
| Pramlintide | 88 → 100 | 67 → 67 | 68 → 72 | strength 75 → 100 |
| Naltrexone + Oxycodone | 73 → — | 45 → 49 | 67 → — | no longer placed: no result on an arm that is the drug's alone (8 endpoints read from naltrexone plus bupropion arms) |

### Non-small-cell lung carcinoma (indication 20)

21 drugs placed before, 19 after, of 91 candidates. No measure is ranked (2.8), so every drug is
scored on strength and wins.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Osimertinib | 1 → 1 | 98 → 100 | 89 → 81 | 87 → 85 | 1 to 2 |
| Pembrolizumab | 2 → 2 | 77 → 57 | 45 → 61 | 73 → 72 | 1 to 3 |
| Atezolizumab | 3 → 3 | 72 → 63 | 44 → 47 | 69 → 67 | 2 to 4 |
| Durvalumab | 6 → 4 | 30 → 24 | 64 → 83 | 56 → 60 | 3 to 10 |
| Crizotinib | 10 → 5 | 90 → 100 | 0 → 0 | 48 → 51 | 4 to 7 |
| Ipilimumab | 8 → 6 | 56 → 39 | 19 → 26 | 51 → 47 | 4 to 11 |
| Nivolumab | 12 → 7 | 42 → 45 | 0 → 0 | 46 → 47 | 4 to 9 |
| Necitumumab | 4 → 8 | 47 → 34 | 68 → 35 | 62 → 47 | 4 to 12 |
| Abemaciclib | 13 → 9 | 0 → 0 | 100 → 100 | 45 → 45 | 7 to 19 |
| Vandetanib | 9 → 10 | 34 → 20 | 39 → 41 | 50 → 39 | 8 to 14 |
| Sunitinib | 14 → 11 | 22 → 5 | 58 → 58 | 44 → 38 | 6 to 18 |
| Cabazitaxel | 15 → 12 | 2 → 0 | 90 → 90 | 39 → 38 | 10 to 19 |
| Niraparib | 16 → 13 | 0 → 0 | 51 → 51 | 36 → 36 | 6 to 18 |
| Bevacizumab | 5 → 14 | 37 → 25 | 61 → 1 | 57 → 33 | 5 to 16 |
| Sorafenib | 18 → 15 | 8 → 2 | 25 → 26 | 34 → 32 | 10 to 18 |
| Denosumab | 17 → 16 | 5 → 0 | 68 → 68 | 34 → 32 | 10 to 19 |
| Cetuximab | 19 → 17 | 20 → 18 | 0 → 0 | 30 → 30 | 10 to 18 |
| Aflibercept | 20 → 18 | 3 → 0 | 10 → 11 | 25 → 25 | 12 to 19 |
| Selumetinib | 21 → 19 | 8 → 0 | 0 → 0 | 14 → 11 | 14 to 19 |
| Ramucirumab | 7 → — | 44 → — | 52 → 61 | 55 → — | — |
| Gefitinib | 11 → — | 18 → — | 58 → 60 | 48 → — | — |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Pembrolizumab | 77 → 57 | 45 → 61 | 73 → 72 | size no longer scored (was 100); staying on treatment 41 → 66; wins 59 → 43; serious events 48 → 60 |
| Durvalumab | 30 → 24 | 64 → 83 | 56 → 60 | size no longer scored (was 56); serious events 64 → 83; strength 35 → 48 |
| Ipilimumab | 56 → 39 | 19 → 26 | 51 → 47 | size no longer scored (was 62); wins 50 → 25 |
| Necitumumab | 47 → 34 | 68 → 35 | 62 → 47 | size no longer scored (was 54); wins 50 → 33; serious events 36 → 28 |
| Vandetanib | 34 → 20 | 39 → 41 | 50 → 39 | size no longer scored (was 34); strength now scored (40); wins now scored (0) |
| Sunitinib | 22 → 5 | 58 → 58 | 44 → 38 | size no longer scored (was 35); strength 30 → 9; staying on treatment 50 → 61; serious events 87 → 76 |
| Bevacizumab | 37 → 25 | 61 → 1 | 57 → 33 | serious events 61 → 1; size no longer scored (was 62) |
| Ramucirumab | 44 → — | 52 → 61 | 55 → — | no longer placed: survival results with no hazard ratio posted (2) |
| Gefitinib | 18 → — | 58 → 60 | 48 → — | no longer placed: survival results with no hazard ratio posted (3; IPASS among them) |

### Breast neoplasms (indication 371)

25 drugs placed before, 23 after, of 71 candidates. No measure is ranked.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Exemestane | 2 → 1 | 76 → 64 | 64 → 78 | 79 → 80 | 1 to 4 |
| Elacestrant | 8 → 2 | 78 → 99 | 68 → 68 | 67 → 74 | 1 to 9 |
| Olaparib | 3 → 3 | 81 → 99 | 85 → 54 | 78 → 74 | 1 to 11 |
| Palbociclib | 6 → 4 | 98 → 100 | 54 → 53 | 73 → 73 | 1 to 7 |
| Sacituzumab govitecan | 12 → 5 | 73 → 100 | 47 → 48 | 61 → 70 | 1 to 10 |
| Talazoparib | 10 → 6 | 88 → 100 | 50 → 50 | 65 → 69 | 1 to 14 |
| Ribociclib | 5 → 7 | 100 → 88 | 27 → 17 | 73 → 65 | 4 to 10 |
| Pertuzumab | 7 → 8 | 57 → 49 | 55 → 54 | 68 → 65 | 5 to 10 |
| Docetaxel | 20 → 9 | 0 → 86 | 19 → 15 | 37 → 65 | 5 to 9 |
| Everolimus | 14 → 10 | 80 → 93 | 16 → 10 | 58 → 61 | 9 to 12 |
| Bevacizumab | 1 → 11 | 71 → 45 | 94 → 39 | 86 → 59 | 6 to 16 |
| Trastuzumab | 4 → 12 | 86 → 55 | 48 → 19 | 78 → 58 | 9 to 13 |
| Atezolizumab | 13 → 13 | 44 → 35 | 59 → 45 | 60 → 53 | 12 to 16 |
| Pembrolizumab | 9 → 14 | 47 → 34 | 74 → 46 | 66 → 52 | 9 to 19 |
| Ramucirumab | 18 → 15 | 22 → 26 | 54 → 56 | 48 → 50 | 12 to 18 |
| Pegylated liposomal doxorubicin (PLD) | 17 → 16 | 0 → 0 | 100 → 100 | 49 → 49 | 14 to 20 |
| Alpelisib | 21 → 17 | 17 → 49 | 24 → 24 | 36 → 47 | 14 to 18 |
| Fulvestrant | 11 → 18 | 32 → 7 | 84 → 71 | 63 → 43 | 15 to 20 |
| Paclitaxel | 19 → 19 | 2 → 1 | 80 → 85 | 37 → 39 | 18 to 22 |
| Enzalutamide | 16 → 20 | 61 → 23 | 62 → 58 | 53 → 38 | 14 to 23 |
| Sorafenib | 24 → 21 | 8 → 4 | 24 → 28 | 30 → 30 | 19 to 23 |
| Dasatinib | 25 → 22 | 17 → 18 | 22 → 27 | 25 → 28 | 18 to 23 |
| Vandetanib | — → 23 | — → 0 | 44 → 44 | — → 19 | 20 to 23 |
| Abemaciclib | 15 → — | 34 → — | 88 → 46 | 57 → — | — |
| Radium-223 dichloride (Xofigo, BAY88-8223) | 22 → — | 11 → — | 57 → 57 | 32 → — | — |
| Eribulin | 23 → — | 0 → — | 48 → 48 | 30 → — | — |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Exemestane | 76 → 64 | 64 → 78 | 79 → 80 | size no longer scored (was 100); staying on treatment 46 → 70 |
| Elacestrant | 78 → 99 | 68 → 68 | 67 → 74 | size no longer scored (was 35) |
| Olaparib | 81 → 99 | 85 → 54 | 78 → 74 | staying on treatment no longer scored (was 100); size no longer scored (was 47); serious events 70 → 54 |
| Sacituzumab govitecan | 73 → 100 | 47 → 48 | 61 → 70 | size no longer scored (was 18) |
| Talazoparib | 88 → 100 | 50 → 50 | 65 → 69 | size no longer scored (was 65) |
| Ribociclib | 100 → 88 | 27 → 17 | 73 → 65 | size no longer scored (was 100); serious events 52 → 13; staying on treatment 3 → 29; wins 100 → 75 |
| Docetaxel | 0 → 86 | 19 → 15 | 37 → 65 | wins 0 → 100; strength 0 → 73 |
| Everolimus | 80 → 93 | 16 → 10 | 58 → 61 | size no longer scored (was 82); strength 83 → 99; wins 75 → 88 |
| Bevacizumab | 71 → 45 | 94 → 39 | 86 → 59 | serious events 94 → 39; size no longer scored (was 53); wins 80 → 33; strength 81 → 58 |
| Trastuzumab | 86 → 55 | 48 → 19 | 78 → 58 | staying on treatment no longer scored (was 66); size no longer scored (was 59); wins 100 → 50; strength 100 → 60 |
| Atezolizumab | 44 → 35 | 59 → 45 | 60 → 53 | size no longer scored (was 45); wins 38 → 29 |
| Pembrolizumab | 47 → 34 | 74 → 46 | 66 → 52 | wins 50 → 17; size no longer scored (was 31); serious events 74 → 46; strength 61 → 51 |
| Alpelisib | 17 → 49 | 24 → 24 | 36 → 47 | strength 15 → 49; wins 20 → 50 |
| Fulvestrant | 32 → 7 | 84 → 71 | 63 → 43 | size no longer scored (was 71); serious events 96 → 75; strength 26 → 13; staying on treatment 72 → 61 |
| Enzalutamide | 61 → 23 | 62 → 58 | 53 → 38 | size no longer scored (was 88); wins 50 → 0 |
| Vandetanib | — → 0 | 44 → 44 | — → 19 | newly placed: its endpoints carry no sponsor test and are tested here from their counts |
| Abemaciclib | 34 → — | 88 → 46 | 57 → — | no longer placed: survival results with no hazard ratio posted (1) |
| Radium-223 dichloride (Xofigo, BAY88-8223) | 11 → — | 57 → 57 | 32 → — | no longer placed: no result on an arm that is the drug's alone (1) |
| Eribulin | 0 → — | 48 → 48 | 30 → — | no longer placed: no result on an arm that is the drug's alone (1; a physician's-choice arm) |

### Type 2 diabetes (indication 1)

19 drugs placed before, 17 after, of 46 candidates.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Finerenone | 6 → 1 | 91 → 91 † | 64 → 84 | 83 → 90 | 1 to 4 |
| Semaglutide | 3 → 2 | 92 → 94 | 66 → 74 | 86 → 89 | 1 to 3 |
| Ertugliflozin pidolate | 5 → 3 | 82 → 82 | 78 → 83 | 85 → 87 | 1 to 6 |
| Tirzepatide | 1 → 4 | 100 → 96 | 76 → 65 | 92 → 87 | 2 to 5 |
| Canagliflozin | 4 → 5 | 78 → 75 | 82 → 79 | 86 → 84 | 2 to 9 |
| Dapagliflozin | 9 → 6 | 74 → 76 | 77 → 75 | 82 → 82 | 4 to 10 |
| Dulaglutide | 10 → 7 | 92 → 92 | 58 → 64 | 79 → 81 | 5 to 12 |
| Saxagliptin | 7 → 8 | 80 → 75 | 71 → 73 | 82 → 81 | 5 to 12 |
| Sitagliptin | 2 → 9 | 84 → 69 | 77 → 74 | 87 → 81 | 6 to 11 |
| Orforglipron | 11 → 10 | 86 → 95 | 66 → 61 | 79 → 80 | 5 to 13 |
| Albiglutide | 12 → 11 | 66 → 76 | 76 → 72 | 76 → 78 | 7 to 13 |
| Liraglutide | 13 → 12 | 80 → 87 | 54 → 55 | 74 → 77 | 7 to 14 |
| Lixisenatide | 8 → 13 | 75 → 65 | 79 → 73 | 82 → 77 | 9 to 13 |
| Insulin icodec | 14 → 14 | 52 → 49 | 82 → 80 | 73 → 71 | 13 to 15 |
| Insulin degludec + Liraglutide | 15 → 15 | 31 → 30 | 75 → 67 | 69 → 66 | 15 to 16 |
| Canagliflozin + Metformin | 17 → 16 | 73 → 75 | 76 → 76 | 62 → 63 | 14 to 17 |
| Insulin glargine | 19 → 17 | 0 → 8 † | 78 → 79 | 54 → 57 | 16 to 17 |
| Metformin + Sitagliptin | 16 → — | 58 → — | 60 → 66 | 67 → — | — |
| Naltrexone + Oxycodone | 18 → — | 67 → — | 42 → 42 | 56 → — | — |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Finerenone | 91 → 91 | 64 → 84 | 83 → 90 | staying on treatment 28 → 65; serious events 100 → 85 |
| Tirzepatide | 100 → 96 | 76 → 65 | 92 → 87 | serious events 100 → 75; wins 100 → 90 |
| Sitagliptin | 84 → 69 | 77 → 74 | 87 → 81 | size 64 → 18; serious events 86 → 74; strength 91 → 100 |
| Albiglutide | 66 → 76 | 76 → 72 | 76 → 78 | strength 56 → 80; size 71 → 86 |
| Metformin + Sitagliptin | 58 → — | 60 → 66 | 67 → — | no longer placed: no result on an arm that is the drug's alone (6 not its arm, 1 in both arms) |
| Naltrexone + Oxycodone | 67 → — | 42 → 42 | 56 → — | no longer placed: no result on an arm that is the drug's alone (2) |

### Rheumatoid arthritis (indication 383)

9 drugs placed before, 10 after, of 28 candidates. No measure is ranked.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Baricitinib | 1 → 1 | 100 → 100 | 39 → 77 | 77 → 89 | 1 to 2 |
| Upadacitinib | 6 → 2 | 100 → 100 | 25 → 50 | 73 → 81 | 1 to 5 |
| Sarilumab | 3 → 3 | 100 → 100 | 45 → 49 | 74 → 76 | 2 to 6 |
| Tocilizumab | 2 → 4 | 100 → 100 | 25 → 22 | 75 → 74 | 2 to 6 |
| Etanercept | 7 → 5 | 95 → 100 | 26 → 57 | 60 → 72 | 2 to 8 |
| Abatacept | 5 → 6 | 71 → 54 | 54 → 61 | 73 → 70 | 3 to 6 |
| Rituximab | — → 7 | — → 100 | 27 → 2 | — → 62 | 6 to 8 |
| Secukinumab | 4 → 8 | 100 → 63 | 53 → 47 | 74 → 53 | 6 to 10 |
| Adalimumab | — → 9 | — → 28 | 65 → 35 | — → 41 | 8 to 10 |
| Ustekinumab | 8 → 10 | 23 → 25 | 70 → 70 | 40 → 40 | 8 to 10 |
| Methotrexate | 9 → — | 21 → — | 10 → 86 | 27 → — | — |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Baricitinib | 100 → 100 | 39 → 77 | 77 → 89 | serious events 21 → 77; staying on treatment 58 → 78 |
| Upadacitinib | 100 → 100 | 25 → 50 | 73 → 81 | serious events 0 → 57 |
| Etanercept | 95 → 100 | 26 → 57 | 60 → 72 | serious events 0 → 58; strength 90 → 100 |
| Abatacept | 71 → 54 | 54 → 61 | 73 → 70 | wins 71 → 50; serious events 43 → 56; strength 70 → 58 |
| Rituximab | — → 100 | 27 → 2 | — → 62 | newly placed: endpoints tested here from their counts; serious events 13 → 0 |
| Secukinumab | 100 → 63 | 53 → 47 | 74 → 53 | wins 100 → 50; strength 100 → 76; staying on treatment 58 → 47 |
| Adalimumab | — → 28 | 65 → 35 | — → 41 | newly placed: strength 55, wins 0; staying on treatment 63 → 24; serious events 88 → 66 |
| Methotrexate | 21 → — | 10 → 86 | 27 → — | no longer placed: no result on an arm that is the drug's alone (2) |

### Multiple myeloma (indication 101)

5 drugs placed before, 6 after, of 28 candidates. No measure is ranked.

| Drug | Rank | Efficacy | Safety | Overall | Rank range |
|---|---|---|---|---|---|
| Plerixafor | — → 1 | — → 100 | 68 → 81 | — → 79 | 1 to 3 |
| Vorinostat | 4 → 2 | 59 → 89 | 61 → 80 | 61 → 77 | 1 to 3 |
| Venetoclax | 3 → 3 | 92 → 88 | 53 → 53 | 66 → 64 | 1 to 6 |
| Daratumumab | 1 → 4 | 100 → 88 | 54 → 10 | 78 → 59 | 3 to 6 |
| Carfilzomib | 2 → 5 | 70 → 63 | 55 → 30 | 70 → 59 | 3 to 6 |
| Elotuzumab | 5 → 6 | 62 → 59 | 50 → 61 | 51 → 53 | 3 to 6 |

| Drug | Efficacy | Safety | Overall | What moved |
|---|---|---|---|---|
| Plerixafor | — → 100 | 68 → 81 | — → 79 | newly placed: one endpoint tested here from its counts; serious events 68 → 81 |
| Vorinostat | 59 → 89 | 61 → 80 | 61 → 77 | serious events 48 → 84; size no longer scored (was 0) |
| Daratumumab | 100 → 88 | 54 → 10 | 78 → 59 | serious events 54 → 10; wins 100 → 75 |
| Carfilzomib | 70 → 63 | 55 → 30 | 70 → 59 | size no longer scored (was 83); serious events 45 → 19 |
| Elotuzumab | 62 → 59 | 50 → 61 | 51 → 53 | size no longer scored (was 67); serious events 0 → 22 |

### What the tables show

- **84 drugs placed, against 89.** Four gain a place because their endpoints can now be tested
  from their own posted numbers (vandetanib in breast, rituximab and adalimumab in arthritis,
  plerixafor in myeloma). Nine lose one: six because no result is on an arm that is the drug's
  alone (naltrexone + oxycodone twice, metformin + sitagliptin, radium-223, eribulin,
  methotrexate), three because their only survival results are medians with no hazard ratio
  (ramucirumab and gefitinib in lung, abemaciclib in breast).
- **27 drugs move more than ten points on efficacy, 27 on safety, 16 on overall.**
- **The top of each list holds where the data are strong.** Obesity keeps semaglutide and
  tirzepatide first and second; lung keeps osimertinib, pembrolizumab and atezolizumab in the
  same order; arthritis keeps baricitinib first; tirzepatide leads type 2 diabetes on HbA1c
  against placebo (1.73 points across five trials). Where the top changes the reason is named:
  in breast the old leader's safety rested on uncontrolled arms (bevacizumab 94 → 39); in
  diabetes finerenone leads on strength and wins alone (decision A); in myeloma plerixafor
  leads on one endpoint tested here (decision C) and daratumumab falls on unadjusted follow-up
  (decision D).
- **Efficacy in oncology is now on one footing.** No measure in lung or breast is ranked, so
  every drug there is scored on strength and wins; the old size part (a rank percentile, "was
  100" for exemestane, ribociclib and pembrolizumab) is gone. Most of the large efficacy moves
  in those two indications involve that part leaving.
- **Direction and attribution fixes move single drugs a long way, and rightly.** Docetaxel in
  breast goes 0 → 86: its one result, 287 against 333 disease-free survival events
  (NCT00688740), was read as a loss because the title names survival. Pembrolizumab in lung
  gains 16 on safety once the maintenance trial where it sat in both arms (NCT03976362) leaves
  its record.
- **Safety moves are of two kinds, and only one is a correction.** Removing uncontrolled arms
  and mismatched periods corrects baricitinib (39 → 77), etanercept (26 → 57), upadacitinib (25
  → 50), liraglutide in obesity (35 → 59), bevacizumab and olaparib in breast. Daratumumab (54
  → 10), rituximab in arthritis (27 → 2) and bevacizumab in lung (61 → 1) fall on serious-event
  excesses in add-on or long-follow-up designs that the book cannot adjust for; the scorecard
  says so under each (5.2, note 7) and decision D puts it to the lead.
- **The rank ranges are wide where they should be.** In breast the second to sixth drugs each
  have a range seven or more places wide; in lung the ninth to nineteenth overlap almost
  entirely. The scorecard cannot order them, and says so.

---

## 9. Limits, and decisions for the user

### 9.1 Decisions to confirm

A. **A drug with no comparable peer is scored on strength and wins alone**, as the scorecard
   does today, marked with a dagger, its rank line saying so. Revision 1 filled in a size of 50;
   that was a guessed value and is gone. Three drugs are affected in the six indications, and
   the most visible is finerenone, first in type 2 diabetes on two cardiorenal outcome trials
   (efficacy 91 from strength 81 and wins 100) above drugs that also carry a size. The two
   honest alternatives: (a) where an indication ranks any measure, list such a drug beside the
   chart with the unscored drugs, reason "no measure shared with enough peers" (obesity loses
   pramlintide, diabetes finerenone and insulin glargine; no other indication changes); (b)
   keep it on the chart and out of the rank, its table row showing "not ranked". The default is
   today's rule because it invents nothing and changes the least.

B. **The class average applies only where four drugs of one class share a measure and a
   control.** The user was told small results would be shrunk toward the drug class average.
   In the six indications that happens once for efficacy (the five GLP-1 agonists on HbA1c in
   diabetes, moving no drug more than 6.4% of the way) and four times for safety. Three drugs
   would not change it: with Morris's small-sample factor (J - 3) / (J - 1), a class of three
   moves nothing, which is the honest reading of a between-drug variance on two degrees of
   freedom. This needs telling, not deciding.

C. **Endpoints with no sponsor test are tested here** from their own interval, spread or counts:
   84 of 521 results, stated on every drug's first line. Four drugs gain a place. Plerixafor
   then ranks first of six in myeloma on one stem-cell mobilisation endpoint (efficacy 100, rank
   range 1 to 3): a question of who is a candidate, not of the statistics. The alternative is
   to require at least one sponsor-tested result for a drug's place, which removes the four.

D. **Safety counts are not adjusted for follow-up**, because the book holds no exposure time.
   Daratumumab ranks fourth of six in myeloma on safety 10 (+12.9 points of serious events
   across six add-on trials, 95% interval +7.4 to +18.4); rituximab in arthritis reads safety 2.
   The note "Counts are people with an event over each arm's whole follow-up; an arm followed
   for longer reports more" prints for every drug whose scored control is active or whose
   strata summed arms. The alternative, scoring safety only where the control is placebo, was
   measured and fails on the book (fulvestrant would be scored on one trial of 31 people and
   not on four of 591, 2.10). The book guard prints the myeloma order so this is seen before it
   ships.

E. **Size is ranked only where the spread between trials rests on five or more degrees of
   freedom** (`TAU_DF_MIN`). Below that the interval covers 75% to 88% where it says 95%, and a
   one-trial drug would again look as certain as its one trial. It leaves oncology with no
   size at all. With `TAU_DF_MIN` = 0, measured on the prototype: lung ranks overall and
   progression-free survival against docetaxel (nivolumab 45 → 58 on efficacy, 7th → 5th;
   atezolizumab 63 → 67; aflibercept 0 → 6; selumetinib 0 → 15) and breast ranks
   progression-free survival against exemestane (everolimus 93 → 95); 13 of 19 lung drugs and
   20 of 23 breast drugs become "not comparable", mixing two footings in one chart; diabetes
   also ranks body weight on two degrees of freedom (semaglutide 94 → 87, liraglutide 87 → 78,
   orforglipron 95 → 89). The default is 5.

The overview's tolerability card, which revision 1 left as decision F, is now part of this
change (5.6).

### 9.2 Known limits, none of them new data

1. **The hypothesis is not stored.** Superiority, non-inferiority and one-sided tests cannot be
   told apart. The interval-first order makes the score safe against it wherever an interval, a
   spread or a count exists, which is every scored result in the six indications bar one.
2. **Interval sides are not stored.** Every level is read as two-sided. A one-sided 97.5%
   interval read as two-sided gives a standard error 12% too small; 366 rows post 97.5.
3. **No exposure time.** Safety counts are people with an event over each arm's whole follow-up
   (decision D). A rate per patient-year cannot be formed.
4. **Withdrawals are thin.** Posted in both arms for 202 of 446 controlled strata. The part
   counts by the people behind it, so a thin one weighs little, and its line says what it rests
   on.
5. **Few trials.** From 5 to 9 degrees of freedom a ranked measure's interval covers about 89%
   to 92%, and a note says so; the six indications have no ranked measure in that band.
6. **Heterogeneity is modelled, not explained.** Trials of one drug differ in who they enrolled,
   for how long and at which doses; the average carries that spread in its interval, and the
   note on disagreement says when it is more than chance. Trial length is printed and a gap is
   withheld across unlike lengths, but the ranking itself is not split by length (appendix A,
   point 2).
7. **Families beyond HbA1c are unchanged.** Rheumatoid arthritis has no family for ACR20, which
   is worded too many ways; a family would let arthritis rank on size. It is a change to the
   families, not to the statistics.
8. **Arm and comparator identification are upstream.** Five results are lost because the drug's
   arm is named only by an abbreviation or a code with no description ("IDegLira", "Saxa",
   "ABA", "AIN457", "Radium-223 + EXE/EVE"). "Naltrexone + Oxycodone (PFE)" carries the safety
   of four naltrexone plus bupropion trials, which the tolerability card shows (5.6); its
   efficacy is now off the chart. `endpoints()` gives each trial's efficacy to one candidate
   (`trial_owner`) while `safety()` counts the trial for every candidate linked to it:
   daratumumab's efficacy rests on 4 trials and its safety on 6 of 13. None needs a new table;
   each is a fix to linking.
9. **Evidence counts everyone treated**, in controlled trials or not, and the text now says so.
   The safety score rests on the controlled arms only, and its line gives both figures.
10. **Primary outcomes only**, as today.
11. **A class is only as good as its label.** Shrinkage uses `mechanism_label`; a drug with no
    label is never shrunk.

---

## 10. Prototype

Under the session scratchpad,
`/private/tmp/claude-501/-Users-charleswoodfine-Documents-WORK-Projects-ER-Tool--claude-worktrees-reverent-borg-5f3beb/6d18b4ba-ea38-4b11-8d77-43ead66a9954/scratchpad/stats_proto/`.
Nothing in it writes to the book. `meta_stats.py` can be copied to `backend/` as it stands.

| File | What it is |
|---|---|
| `meta_stats.py` | the pure functions of section 6 |
| `cases_v2.py` | every case of section 6 (`cases_v2_out.txt`) |
| `ext_land.py` | the land dict with the fields of section 4, built by patching `landscape.endpoints` and `landscape.safety` in memory; `land_*.pkl` its cache |
| `score_v2.py` | the scorecard of sections 2 and 5, one method, no switches bar `TAU_DF_MIN` |
| `report_v2.py` | section 8 (`report_final.txt`) |
| `variant_df.py` | decision E, the scorecard with `TAU_DF_MIN` = 0 or any other value (`variant_df5_out.txt` holds the run that set the default) |
| `guard.py` | the book guard of 7.3 and the counts of 2.6 and 5 (`guard_final.txt`) |
| `ex_v2.py`, `ex2_v2.py` | the counts of section 1 and the worked examples (`ex_final.txt`, `ex2_final.txt`) |
| `show.py` | every placed drug with its parts, lines and notes (`show_final.txt`) |
| `dump_one.py` | one drug's record, for section 3 |
| `sim_tau.py`, `sim_shrink.py` | the simulations behind 2.5 and 2.9 |
| `chk_b.py`, `chk_c.py` | the shortened-name test and the tolerability card of 5.6 |
| `v1/` | revision 1's prototype, kept for the before and after of appendix A |

Names that differ between the prototype and this specification, the specification's being the
ones to build: `all_analyses` is `analyses`; `post`, `post_se` are `shrunk`, `shrunk_se`;
`tied` is `tied_with`; the scale codes `diff`, `share`, `loghr` are `difference`, `share`, `log
hazard ratio`; the safety fit's `se_raw` is `se_own`; the `lead` entry is marked with `lead: true`
on `pooled[]` rather than held apart; the prototype's `_pooled`, `_tau` and `_trial_level`
output keys are for the guard only and are not built. The `hazard_ratio` keys and the `direct`
block of `versus` are specified here and computed in the sentences there. The prototype draws in
the fixed order of 2.11, so the built rank ranges match section 8.

---

## Appendix A. Resolved review points

Two reviews, a biostatistician's (B) and an analyst's (A), raised 39 points. Each was checked
against the book before it was acted on. Where a point was right the rule changed; where part of
it did not hold, the rule stayed and the reason is here. Numbers are the prototype's on
`book_r3.db`.

| # | Point | Verdict | What changed, or why not |
|---|---|---|---|
| 1 | B. A one-trial drug carries no between-trial variance, so shrinkage and the thin-record flag ran backwards | Accepted | One variance per measure from every multi-trial drug, carried by every drug (2.5). Eloralintide's se goes 1.08 → 3.24, tirzepatide's 1.96 → 1.34. The thin-record sentence and the chance of the largest effect are gone. Where no drug has two trials the measure is not ranked. Test 7.1 (6). |
| 2 | B. "Through placebo" is not a common comparator; durations and designs differ | Accepted | Controls are keyed on what the control arm received (2.8): placebo with docetaxel is docetaxel, and a drug is compared only with drugs on the same key. Randomised-withdrawal results (STEP 4, SURMOUNT-4) stay out of size. Every averaged effect prints its trial lengths, and no gap or interval is quoted between drugs whose lengths do not come within a quarter of each other. The ranking itself is not split by length, which the review did not ask for either: in obesity the lengths chain from drug to drug (liraglutide 26 to 56 weeks, semaglutide 44 to 104, tirzepatide 52 to 72, orforglipron 72), so no cut into bands keeps each drug's own trials together; the rank sentence names the span instead. |
| 3 | B. The new routes scored results the wrong way round and misread a spread | Accepted | A family fixes its sign; a count of people with events is lower-is-better; a least-squares mean with a "Standard Deviation" is not read (2.2, 2.3). Not accepted: reading that spread as a standard error when z would be implausible. Leaving the one trial unscored is simpler and guesses nothing. Book guard added. Pertuzumab example replaced: APHINITY is now a raw win that does not survive seven tests. |
| 4 | B. Averaging dose arms changes the estimand | Accepted | Tested on all arms, sized on the top arm less the expected maximum of k null draws (2.4). SURMOUNT-1 sizes at 19.76, not 17.51. |
| 5 | B. DerSimonian-Laird on two to five trials does not give 95%, and "its trials disagree" fires on chance | Accepted, and taken further | Common variance (point 1). Disagreement prints at k of 3 or more and chi-square p below 0.10; I2 only from five trials. The same coverage argument, applied to the common variance, is why a measure whose variance rests on under five degrees of freedom is not ranked (decision E): 75% to 88% coverage in lung and breast. |
| 6 | B. Empirical Bayes on three to nine drugs collapses real differences | Accepted | Shrinkage only toward the mechanism class at four or more drugs, with Morris's factor, never toward all drugs on a measure (2.9). No collapse in 320,000 simulated measures; coverage 94.7% to 99.6%. One basis (the shrunk effects) for rank, gap and chance. |
| 7 | B. Safety used a fixed-effect interval across unlike trials and control kinds | Accepted in part | The Mantel-Haenszel se is widened by one dispersion factor per indication, part and kind, a one-trial drug's included; kinds are pooled apart; one trial holding over half the weight is named; follow-up is a stated limit. Not accepted: "score the placebo kind where it exists". Fulvestrant would be scored on one trial of 31 people over four of 591; the kind with more people is scored and the other reported. Not accepted either: a factor drug by drug, which from two strata is noise and leaves a one-trial drug unwidened, the fault of point 1. |
| 8 | B. The safety sentence printed crude summed rates | Accepted | Rates on the pooling weights, so they differ by the difference quoted (semaglutide in obesity 24.9% against 26.8%, not 21.1% against 28.6%). Deaths the same, reported. Test 7.1 (11) and the book guard. |
| 9 | B. The score intervals had no target | Accepted, and taken further | No interval on any score. Closed-form intervals on the averaged effect and each risk difference, in the words. One rank range, from a redraw of those estimates only, one draw per trial across every measure and part it feeds. No widening step; the guard asserts the rank sits in its range. Not accepted: drawing an unranked drug's size over 0 to 100. Such a drug has no size in its score (point 22), so there is nothing to draw. |
| 10 | B. Stouffer's Z saturated strength and rewarded the number of trials | Accepted | Strength is the mean trial z (2.6): 35 of 84 placed drugs at 100, against 54 of 92 under Stouffer. Not accepted: a guard that no more than half the placed drugs sit at a bound. All nine obesity drugs have an average trial beyond p = 0.001; the part is at its ceiling because the data are, and size orders them. |
| 11 | B. Active-controlled results were given a chance of beating a peer with no common comparator | Accepted | Ranked only within one named control (2.8), docetaxel in lung being the review's own example of a real network. With the floor of decision E the only cells ranked on a named control are three HbA1c cells in diabetes (metformin, insulin glargine, glimepiride), whose spread rests on 110 degrees of freedom; lung's docetaxel cells rest on 1 and 3 and are not ranked. |
| 12 | B. One trial counted in several ranked measures; HbA1c split three ways; wins by endpoint | Accepted | Twins count once (2.8); A1C joins the HbA1c family; wins are the mean over trials of each trial's share (2.7); one draw per trial in the redraw. |
| 13 | B. Effects attributed to a drug in both arms or in neither | Accepted | No result where the comparator names the drug, by full or shortened name; no fallback to unnamed arms (2.1). 8 results go for the first reason (6 in diabetes, 2 in lung from the pembrolizumab maintenance trial NCT03976362), 29 for the second. The shortened-name test was added in this pass after it was found that "Pembro + Placebo" escaped the full-name test; "Nivo Placebo + Chemo", placebo for nivolumab, is excluded by rule. |
| 14 | B. The anchor split applied to size only | Accepted in part | Wins by kind of control are printed (5.1 note 3). Not accepted: scoring strength and wins within the placebo pair. Head-to-head superiority trials are the strongest results the book holds, and a trial built to show a drug is no worse cannot win under either rule, which the note says. |
| 15 | B. Benjamini-Hochberg on two-sided p let results against the drug loosen the bar | Accepted | One-sided p, a win at 0.025 with a 1e-9 tolerance; the sentence on bounds corrected (2.7). No drug's win count changes in the six indications, as the review said. |
| 16 | B. An invented z for a bound above, an assumed level, no interval check | Accepted | A bound above gives no z and counts as not won; a row with no level never has its interval read; an interval must bracket its estimate near the middle, which removes the one typo (NCT00106704) and nothing else. |
| 17 | B. The arithmetic checks out | Noted | The three examples built on wrong inputs are replaced: pertuzumab in 2.7, the tirzepatide diabetes row in section 8, and the 55% and 45% chance of the largest effect, now gone. |
| 18 | A. One mis-signed result wrecked tirzepatide's HbA1c pool | Accepted | As point 3. Tirzepatide is first of 14 on HbA1c against placebo at 1.73 across five trials (95% interval 1.50 to 1.96 with the measure's spread, 1.57 to 1.86 on its trials' own errors); the book guard asserts it. |
| 19 | A. The ratio of medians was printed as a hazard ratio nobody posted | Accepted | Removed. A survival result needs a posted hazard ratio; 15 endpoints go unscored and three drugs lose their place (2.3). Decision C of revision 1 is gone. |
| 20 | A. Safety pooled by trial still reads follow-up as toxicity | Accepted in part | Switch, extension and open-label arms are never summed onto the drug's side, and periods are matched (upadacitinib 25 → 50); the follow-up note prints; "every large move is a correction" is withdrawn (section 8); the guard prints the myeloma order. The rule stays: the book has no exposure time, and decision D puts it to the lead with daratumumab 4th of 6. |
| 21 | A. Half the safety score could rest on one small trial | Accepted | The parts count by the people behind each (2.10): semaglutide in diabetes 49 → 84 before its boxed deduction. The line says what it rests on. |
| 22 | A. A size of 50 for a drug on no shared measure is a guessed value | Accepted | Removed; strength and wins alone, marked, with the two alternatives measured in decision A. |
| 23 | A. "Through placebo" in lung and breast | Accepted | As point 2. |
| 24 | A. Rank, effect and gap were quoted from different estimates; ties got distinct ranks | Accepted | One basis; equal effects share a rank; a chance between 45% and 55% reads "cannot be separated". The gap is always to the leader (the runner-up for the leader), direct where a head-to-head trial exists in either record. |
| 25 | A. "Thin or uneven record" fired on the best-evidenced drugs | Accepted | Removed. Its three causes are said apart: one trial (note 5), no spread known or too few trials (line 3), trials that disagree (note 4); the class average names its drugs and count. |
| 26 | A. The score intervals do not mean what the chart says | Accepted | As point 9: no cross on the chart, no "long line is a thin record", no zero-width interval anywhere. |
| 27 | A. Stouffer's Z saturated strength | Accepted | As point 10. |
| 28 | A. A fifth of wins are tests run here and the words did not say so | Accepted | Line 1 says how many of a drug's results were tested here (84 of 521 in all); "at p < 0.05" is gone from the single-result form. |
| 29 | A. Crude rates contradicted the pooled difference | Accepted | As point 8. |
| 30 | A. Bubble size counts everyone treated while safety rests on controlled strata | Accepted | The safety line carries both denominators ("20 of its 24 trials and 16,984 of 17,594 people treated"); the evidence text now describes the figure it has always been (5.4). Evidence itself is unchanged: it measures maturity. |
| 31 | A. The cards under the scorecard would disagree with it | Accepted | Brought into scope as a one-function change (5.6); the best-dose bars keep their basis and say how the scorecard differs. |
| 32 | A. Words per drug nearly doubled | Accepted | At most four sentences under the chart (measured 3.0 to 4.0 by indication), the rest in the existing expander. |
| 33 | A. Terms an analyst would look up | Accepted | Plain wordings throughout 5.1 and 5.2: "after allowing for the {m} tests run", "averaged across {k} trials, larger trials counting more", "on that basis", "a gap that could be nothing"; a z above 5 prints as "5 or more"; the range is defined in words. |
| 34 | A. Assumptions applied silently | Accepted | The dose note states the shared-control assumption; the caveat states two-sided intervals, half an event for an empty arm and the orientation of a hazard ratio; a legacy row takes no level. A proportion at or under one read as a fraction is tested (7.2). |
| 35 | A. HbA1c split across three rankings | Accepted | As point 12. |
| 36 | A. The indirect sentence ignored a head-to-head trial and hid the time point | Accepted | As point 24; every averaged effect prints its trial lengths. |
| 37 | A. The book guard covered obesity only | Accepted | Extended to all six indications with checks for diabetes, lung and myeloma (7.3); every sentence of section 5 is built and read in the prototype. |
| 38 | A. Upstream mislabels the new sentences would repeat | Accepted in part | Naltrexone + oxycodone's efficacy and pembrolizumab's maintenance trial are no longer read as theirs (point 13). The linking faults themselves are listed by name in 9.2 (8) and are out of scope. |
| 39 | A. No new table, source, fetcher or tab | Confirmed | Section 4 adds keys to the in-memory `land` only; the overview response grows by the analysis lists. |


## Appendix B. Review round two: what changed and why

Each finding was reproduced on the backup book before it was fixed; the fix is at the root,
with a test (`tests/test_landscape_score.py` 28 to 44, `tests/test_landscape.py` "whose arm it
is", `tests/test_meta_stats.py`). No table, schema, fetcher, source or tab was added.

| # | Finding | Outcome | Where |
|---|---|---|---|
| 1 | Salt and suffix names hid the drug, so two-arm trials lost their comparator (AURA3, cemiplimab, alectinib) and "Pramlintide + Placebo" was a control | Fixed. `drug_identity` reads each filed name without its salt word and a biologic's name without its FDA suffix, the latter struck where another candidate holds it whole or where the other arm carries a development code (a biosimilar trial). A result with no control arm is counted, reason `no control` | 4.1, 2.1 |
| 2 | Safety dispersion pooled only over drugs whose scored kind matched | Fixed to the spec's words: every drug with two or more strata of the kind; the reported other-kind fits are widened too | 2.10 |
| 3 | Direction misread: SPID, "weighted", KCCQ, time from randomisation, flare-free duration, the participants catch-all, harms | Fixed: time-to, instruments, responder and harm words before the word lists | 2.2 |
| 4 | Other drugs' arms credited through the description; combinations credited on one component | Fixed: a description counts only as the arm's own treatment; an arm naming another candidate the control lacks is not the drug's; a combination needs every component or its own name | 4.1 |
| 5 | The rank redraw crashed when the Mantel-Haenszel average dropped a stratum | Fixed: `kept` names the strata read and every list follows it | 2.10, 6.7 |
| 6 | Time-to-event measures outside the four survival families sized from censored means | Fixed: every time to an event is read from a hazard ratio alone, its sign by whether the event is good or bad | 2.3, 2.2 |
| 7 | Placebo arms named for an age, period or schedule became named controls with nonsense labels | Fixed: `_KEY_PERIOD`, colon labels, switches; dangling connectives stripped from labels | 2.8 |
| 8 | A proportion read from its interval stayed on the 0 to 1 scale | Fixed: put in percentage points, as the counts route does | 2.3 route 3 |
| 9 | Rates printed as -0.0%, intervals past the possible, no caveat on an unranked average on one degree of freedom | Fixed: each rate its own weighted mean held in 0 to 1; intervals held to the possible range; figures never print a negative zero; the few-degrees note covers any lead averaging two or more trials | 2.10, 5.1 |
| 10 | Obesity: SELECT's serious events and missing withdrawal counts fixed semaglutide at rank 1 | Fixed: outcomes trials' serious events set aside; the parts count equally and a part behind under a quarter of the other's people is left out and named; a fixed rank shows as its number in the range column. Semaglutide and tirzepatide now both read rank range 1 to 2 | 2.10, 5.5 |
| 11 | Nivolumab's safety 0 came from nivolumab plus ipilimumab arms in a small cell trial; CheckMate 017 and 057 lost their comparator; small cell trials in the non-small cell landscape | Fixed: combination arms with another candidate left out of the stratum; extension arms not counted in the comparator rule; "non" must match on both sides of a condition; a safety score on under a fifth of the people treated reads "Read with care". Nivolumab's safety is now 62 on six trials and 1,624 people, flagged at 16% | 2.10, 4.1 |
| 12 | A drug with no comparable peer skipped size and landed on top (finerenone first in type 2 diabetes; pramlintide right of tirzepatide) | Fixed: an analysis set is not a subgroup (pramlintide is ranked); size counts at 50, the scale's average, where others are ranked; dotted outline and dagger on the chart. A hold at the best measured drug was tried and rejected (2.13) | 2.13, 5.5 |
| 13 | Lung efficacy measured how often trials hit; pembrolizumab's headline was a non-significant secondary result; the correction ran across the programme | Fixed: the lead is the largest result by people when unranked; the correction is within each trial; strength and wins from few trials move toward the drugs' mean; the axis says when no size is in the score | 2.6, 2.7, 2.8, 5.5 |
| 14 | Non-inferiority trials counted as losses; a "worse" line printed its interval with the other sign | Fixed: non-inferiority results left out of strength and wins unless superior; the interval negated and turned round | 2.7, 5.1 |
| 15 | Size compared trials of very different lengths while the words said it did not | Fixed: peers are those of comparable length only | 2.8 |
| 16 | Chart labels on bubbles, far from their own, focal bubbles merged | Fixed: rank inside each bubble, leader lines, top five labelled first, a ring round the open company's bubbles, the clamp fallback removed | 5.5 |
| 17 | SURPASS-2 had no comparator; combination arms to the wrong candidate | Fixed by 1 and 4: the one unnamed randomised arm is the comparator | 4.1 |
| 18 | Safety pulled toward a class mixing a TKI with antibodies given with chemotherapy | Fixed: no shrinkage on safety | 2.9 |
| 19 | Statistics phrases an analyst cannot follow | Rewritten in outcome terms throughout 5.1, 5.4 and the view | 5.1, 5.4 |
| 20 | Text defects: "1 endpoints", "rate at,", " - evaluable population", raw boxed warnings, 30-word composites, a capital after a colon, the header's "×", "Staying on treatment", signed points | Fixed: plurals; `clean_measure`; `_boxed_text`; "Not on the chart ... guessed." then sentences; "efficacy, safety and weight of evidence, averaged"; one name for the withdrawal part; "points more" and "points fewer" | 5.1, 5.2, 5.5 |
| 21 | Two figures for one drug and measure on one page (scorecard 18.8, card 24.4) | Fixed in the scorecard's words: its figures average a drug's trials, the cards below quote a single best result. The card itself is the overview's (landscape_overview.py), outside this change | 5.5 |
| 22 | The methods reproduce from the raw book; the sweep is clean | No change needed | |
| 23 | `.claude/launch.json` and `cre.html` are unrelated working-tree changes | Left for the lead to keep out of the commit | |

Two readings the review offered were weighed and one taken. For a drug with no comparable
peer, a size of 50 and a hold at the best measured drug's efficacy were both measured: the hold
binds on no one in type 2 diabetes and leaves insulin glargine first on two trials against
lixisenatide, so the average of the scale is used (2.13).

**Top five after the round** (backup book of 2026-09-30; overall, then efficacy, safety and
evidence; the rank range in brackets):

Obesity: semaglutide 83.3 (86.2, 63.5, 100) [1 to 2]; tirzepatide 81.8 (97.2, 60.7, 87.4) [1 to
2]; orforglipron 69.8 (76.3, 61.5, 71.6) [3 to 6]; eloralintide 68.8 (95.0, 78.3, 33.1) [3 to 8];
liraglutide 68.7 (72.5, 59.4, 74.2) [3 to 7].

Non-small cell lung: osimertinib 78.0 (80.9, 81.5, 71.6) [1 to 8]; pembrolizumab 73.6 (63.0,
61.0, 96.7) [1 to 7]; nivolumab 69.1 (50.7, 61.6, 95.0) [1 to 9]; cemiplimab 68.4 (78.1, 62.1,
65.0) [1 to 9]; ceritinib 68.1 (80.9, 55.9, 67.5) [1 to 9].

Breast: denosumab 75.9 (81.5, 63.0, 83.1) [1 to 4]; exemestane 73.6 (46.0, 77.6, 97.1) [1 to 5];
pertuzumab 69.0 (61.7, 54.0, 91.2) [3 to 7]; palbociclib 67.9 (83.1, 55.3, 65.2) [2 to 10];
olaparib 65.7 (75.4, 53.8, 68.0) [1 to 20].

Type 2 diabetes: tirzepatide 88.0 (96.2, 68.8, 99.1) [1 to 3]; semaglutide 86.5 (90.7, 68.8,
100) [1 to 4]; insulin glargine 85.8 (78.3†, 87.3, 91.7) [1 to 8]; finerenone 83.5 (73.8†, 83.3,
93.4) [1 to 17]; canagliflozin 82.1 (74.1, 73.5, 98.7) [3 to 9].

The sweep over all 426 indications: 184 with a placed drug, 755 placed drugs, no exception, no
value that is not finite, every rank inside its range.
