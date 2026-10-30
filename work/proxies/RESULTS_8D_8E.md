# 8d and 8e: safety signal and deal appetite

Run 2026-10-29. Tools: `work/proxies/tools/safety_study.py` and `deal_appetite_study.py`.

## 8d: safety signal

**Not testable on the book's data. The reason is survivorship, not safety.**

- **Sample.** 146 completed Phase 2 studies with posted results, a single placebo or
  standard-of-care arm, an asset in the book, and three years since completion.
- **Imbalance.** Serious adverse events and deaths, the drug arms pooled less the
  comparator.
- **Outcome.** A Phase 3 or an approval for the asset within three years.

| serious adverse events, drug less comparator | n | went on |
|---|---|---|
| lower by over 5 points | 14 | 86% |
| lower by up to 5 | 33 | 85% |
| higher by up to 5 | 62 | 85% |
| higher by 5 to 10 | 20 | 90% |
| higher by over 10 | 17 | 94% |
| deaths higher in the drug arm | 8 | 100% |

87% went on, with no gradient. The book holds the assets that are still current, so a
programme that died after a bad Phase 2 is mostly not in it, and the test cannot see the
attrition it is meant to measure.

**What would test it:**
- **For pipeline studies:** every Phase 2 the companies ran, read from ClinicalTrials.gov
  with intervention names and posted safety results (the 2010-on history from 8a, plus
  those two fields), then whether the same intervention reached Phase 3.
- **For marketed drugs:** label history. The book's label snapshots start in September
  2026, but DailyMed keeps every version of a label, so the date a boxed warning was added
  can be read. That can then be set against Part D prescriber counts before and after.

Until then the safety figures are a display: the drug arm's excess over the comparator
on the landscape and drug cards, moving no value.

### Retest without survivorship (2026-10-30)

Tool: `work/proxies/tools/safety_history_study.py`. It reads every Phase 2 and Phase 3
the companies' lead sponsors registered from 2008, from ClinicalTrials.gov, with arms,
interventions and posted adverse-event groups: 11,969 studies across 75 sponsors.

- **Sample.** 606 Phase 2 studies covering 462 compounds, with a placebo or sham arm,
  posted events, and three years since completion. A compound already in a Phase 3
  when the Phase 2 started is left out. 88% name no compound the book holds, so the
  programmes that died are now in the sample.
- **Outcome.** A Phase 3 of the same sponsor naming the compound, within three years.
  28% reached one, close to the industry's usual Phase 2 success rate.

| serious adverse events, drug less comparator | n | reached Phase 3 | study terminated |
|---|---|---|---|
| lower by over 5 points | 51 | 47% | 27% |
| lower by up to 5 | 159 | 31% | 14% |
| higher by up to 5 | 292 | 25% | 20% |
| higher by 5 to 10 | 63 | 22% | 22% |
| higher by over 10 | 41 | 20% | 39% |

The rank correlation of the imbalance with stopping is +0.089 (one-sided permutation p
0.012, 2,000 shuffles).

**A signal, but not one to put in value.**

- **Small studies carry it.** With 100 or more patients at risk the three bands (drug
  lower, higher by up to 5, higher by 5 or more) reach Phase 3 at 36%, 31% and 29%.
  Under 100 at risk they read 33%, 17% and 16%.
- **The high band is not stable.** It reached Phase 3 at 31% for studies completed to
  2015 and 13% for those completed since.
- **It is partly efficacy.** In many diseases the serious events are the disease
  itself (exacerbations, hospitalisations), so a drug arm with fewer of them is often a
  drug that worked. The strongest band, drug lower by over 5 points, is the one that
  reads most like efficacy.
- **Name matching undercounts Phase 3s.** A compound renamed between phases, or
  licensed to another sponsor, counts as stopped. That pulls every band down alike.

So the safety figures stay a display. If they are to move value, the one defensible
use is a modest cut to the Phase 2 to Phase 3 probability for a study with 5 or more
points of excess serious events: 21% against a 28% base, about three quarters. That
needs agreement and a value delta on a copy first.

Label history for marketed drugs is not read. FDA's Drug Safety-related Labeling
Changes database dates boxed warning changes from 2016, and would be the source.

## 8e: deal appetite

**No predictive signal in the data the book holds.**

- **Gap.** The share of US product revenue (the SEC data sets' product lines, fiscal 2016
  on, matched to book assets) whose LOE falls in the next five years.
- **Deal spend.** Acquisitions net of cash acquired, acquired intangibles and acquired
  in-process R&D, over the next two years, as a share of revenue.
- **Sample.** 75 company-years across 13 companies.

| gap third | gap, median | deal spend over two years, median | mean |
|---|---|---|---|
| smallest | 0% | 2.8% of revenue | 13.7% |
| middle | 8% | 16.3% | 28.7% |
| largest | 37% | 8.3% | 18.4% |

The rank correlation is +0.09 overall and +0.10 within a company (7 companies with four
or more years). The deals table from headlines is thinner still before 2025. Companies do
not visibly buy in proportion to the cliff ahead. Timing, price and opportunity dominate
a five-year window.

**Use:** a descriptive screen only. Who has the most revenue at risk and the cash to act,
matched by therapy area. No takeover probability or premium enters any case.
