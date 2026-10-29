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
