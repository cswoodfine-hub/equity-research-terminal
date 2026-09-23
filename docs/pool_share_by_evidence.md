# Deciding pool share on evidence rather than judgement

When several drugs are modelled against one population, something has to decide how much
of it each one gets. Today that is each analyst's stated penetration multiple, and where
the pool runs short every claimant is cut by the same factor. The multiple is a
judgement: retatrutide is set at 1.0 times the incumbent's observed capture, eloralintide
at 0.5, and the reasoning is a sentence about salesforces and dosing.

Replacing it with science means efficacy, tolerability, dosing and mechanism. This is the
plan for that, and it opens with the finding that decides its shape.

## 1. The answer

**A clinical share model cannot be built on free data today, and it is not close.** Of
the eight obesity assets, three have a posted weight-loss result, at different timepoints
and on different endpoints. Across the whole modelled pipeline, 46 of 63 assets have no
posted result of any kind. A share model fed by efficacy would be deciding eight
companies' valuations from three numbers, two of which are Phase 1 or Phase 2b and one of
which is a 28-week interim readout rolling into a second part.

What is buildable now is the scaffolding that would make such a model possible later, and
several mechanical corrections that are worth more than the clinical layer would be. So
the plan is ordered by what is decidable, not by what is interesting.

**What the evidence supports today**

| asset | posted weight result | dosing interval on file | earliest Phase 3 completion |
|---|---|---|---|
| LLY Eloralintide | -20.1% at week 48 | route only | 2028-01 |
| PFE Berobenatide | -12.45% at week 28 | once weekly | 2027-09 |
| AMGN Maridebart | Phase 1 adverse events only | not on file | 2027-01 |
| LLY Retatrutide | none of 11 trials | route only | 2026-04 |
| NVO Cagrilintide | none of 17 | once weekly | 2027-03 |
| AZN Elecoglipron | none of 11 | oral once daily | 2027-06 |
| VKTX VK2735 | none of 2 | once weekly | 2027-07 |
| AZN AZD6234 | none of 8 | once weekly | 2028-08 |

The comparator is better served: tirzepatide's SURMOUNT-1 posts -22.5% at week 72 against
-2.4% on placebo, with adverse-event discontinuation of 0.95% against 0.93%. So the
incumbent can be characterised and the challengers mostly cannot.

**Two things make the table worse than it looks.** The endpoints are not comparable:
week 28, week 48 and week 72 are different questions, and for several assets the lead
Phase 3 endpoint is not weight at all, one of elecoglipron's being a renal composite.
And the asset the book calls cagrilintide is in practice CagriSema: 12 of its 17 trials
name semaglutide, so its efficacy is a combination's, not a molecule's.

## 2. What is missing that should not be

The registry holds far more than the book stores. On a synonym sweep of intervention
names: retatrutide has 34 registered studies against 11 on file, cagrilintide 44 against
17, maridebart 28 against 15, elecoglipron 27 against 11. The fetcher queries by sponsor,
so a study run under a partner or an older code name is missed.

openFDA returns about 28 narrative label sections for a marketed product where the
database stores one. Every comparative safety statement a reader would want about the
incumbents is in sections the book does not keep.

`modality`, `mechanism` and `target` are null on all eight assets, though every one of
them has a mechanism stated plainly in its own trial titles.

## 3. The builds

**Build 1. Fix pool membership so it follows the indication.** `pool_crowding` groups
claimants on an identical prevalence figure, which is a proxy that happens to work. Two
drugs treating the same disease with prevalence rows sourced differently would not pool,
and two treating different diseases with the same population size would. Membership
should be the asset-indication pair, which is this repository's own unit of analysis.

Blocked on a data defect first: a co-morbidity listed in a trial's enrolment criteria
becomes an indication, so Omvoh, an interleukin-23 antibody for ulcerative colitis, is
tagged Obesity from a trial that studies it alongside tirzepatide in colitis patients who
are also obese. Fix `indication_mapping` to refuse a condition that the trial's own title
does not treat, then pool on the indication. Tested by asserting Omvoh is not in the
obesity pool and that the eight are.

**Build 2. Store what the registry already publishes.** Widen the trials fetcher from
sponsor-only to an intervention-name sweep, and store the results section where one is
posted: outcome measures, measured values, units, timepoints, and the participant-flow
adverse-event drops. This is the input every later build needs and it is free. Tested
against a saved fixture for one asset with posted results and one without.

**Build 3. A comparability gate, not a score.** Before any efficacy number is used,
something must decide whether two results answer the same question. Store the endpoint,
the timepoint, the comparator arm and the population with every result, and refuse a
comparison where they differ. Expect this to refuse most pairs, which is the correct
outcome and the reason to build it before the score rather than after.

**Build 4. Order of entry, which is measurable now.** The one differentiator that needs
no clinical data is who arrives first: earliest Phase 3 primary completion, then filing,
then approval. The shared-pool solve already rewards early entrants, because a later one
finds the pool drawn down. Make that explicit and evidenced rather than incidental, and
report each asset's implied position.

**Build 5. The share model, only where the gate passes.** A multi-factor score over
efficacy, tolerability and dosing convenience, each factor evidenced, each with a stated
weight, applied only between assets whose results the gate has admitted as comparable.
Everywhere else the split falls back to the analyst's multiple, which is what it is
today, and the asset says which of the two it is on.

## 4. How it must degrade

**An asset with no published result must not be scored at all.** Scoring it as average
flatters a failure and scoring it low punishes a company for not having read out yet.
Both are inventions. An unreported asset keeps its analyst multiple, and the interface
says so, in the same way the probability model reports a filing it refused to act on.

**A score must never be the only thing that moved a number.** If a valuation changes
because a weight changed, the weight is a judgement wearing a lab coat. Every factor
carries its source and its grade, and the composite takes the weakest, exactly as the
assumption rows do.

## 5. What not to build

**Do not infer efficacy from a trial title or a mechanism.** A triple agonist is not
necessarily better than a dual one, and this repository has already refused to infer a
biomarker from a gene name in a title for the same reason.

**Do not use adverse-event report counts as a tolerability measure.** The FAERS database
is spontaneous reporting: counts track prescriptions and publicity, not risk, and a
newly launched drug looks safe because nobody has reported it yet.

**Do not build a head-to-head comparison where none exists.** Cross-trial weight loss at
different timepoints against different placebos is not a comparison, and presenting it as
one would be the most dangerous number in the terminal.

## 6. Open decisions

- Whether cagrilintide should be modelled as CagriSema, which is what its trials study,
  and if so how its revenue relates to Novo's separately modelled semaglutide lines.
- Whether the weights in build 5 are set once and held, or restated per disease area.
- Whether an asset that reads out badly should move its share immediately or wait for a
  filing, given the probability model already handles a negative readout separately.
