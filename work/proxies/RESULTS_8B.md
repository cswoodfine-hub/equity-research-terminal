# 8b: runway, raises and dilution

Run 2026-10-29. Reproduce with `ER_TOOL_DB=<copy> python3 work/proxies/tools/runway_study.py`
and `dilution_view.py`.

## Data

- **Sample.** Every company-quarter in `financials` where trailing twelve-month operating
  cash flow is negative: 1,416 across 56 companies, with four quarters after.
- **Months of cash.** Cash plus short- and long-term investments over the trailing burn,
  `runway.py`'s own definition.
- **What followed, over the next four quarters:**
  - growth in weighted average diluted shares;
  - whether financing inflows passed 10% of the cash on hand.
- **Cleaning.** Share moves above +150% or below -50% are left out as IPOs and reverse
  splits, leaving 573 of the 622 quarters with share data. Mostly 2020 on.

## Result

**Months of cash predicts raising strongly, and the gradient is steady.**

| months of cash | n | raised over 10% of cash within 12m | share growth, median | 10%-trimmed average |
|---|---|---|---|---|
| under 12 | 62 | 94% | 21.9% | 27.4% |
| 12 to 18 | 55 | 91% | 19.1% | 25.7% |
| 18 to 24 | 73 | 77% | 13.9% | 18.2% |
| 24 to 36 | 129 | 68% | 8.4% | 13.0% |
| 36 to 60 | 131 | 61% | 8.9% | 10.3% |
| 60 or more | 123 | 46% | 4.8% | 7.5% |

Companies with five years of cash still add about 7.5% a year. That is employee stock,
which the forecast already charges as a cost, so the financing need is the excess over
it: 19.9% under a year of cash, 18.2% at 12 to 18 months, 10.7% at 18 to 24, falling to
nil at five years.

## Why it does not move value

- **A raise at fair value is neutral.** The forecast already charges the burn, so the cash
  a raise brings is cash the value has already netted out.
- **What a raise at market costs a holder depends on the share price:**
  v' = (v + gP) / (1 + g).
  - Where the model values the share above the price, the raise costs value: Intellia
    -5.9%, Kyverna -0.9%.
  - Where it values it below the price, the formula adds value: Summit +142%, Revolution
    +26%.

  Folding that into the base case would pull every biotech's model value toward its share
  price, and no value in the book reads a market price.
- **Underwriting fees and discounts are real costs** but are not measured. One
  observation (Dyne: 431m gross, 405m net, about 6%) is not a rate.

## What went into the terminal

- **`data/runway_dilution.csv`:** the table above, with its source and method.
- **`runway.expected_raise(months)`:** the measured chance of a raise and the extra shares
  for a company's months of cash, on every runway row as `expected_raise`.
- **The runway page:** two new columns, "Raised within 12m, peers" and "Extra shares in
  12m, peers", with their basis in the column help.

## Next, if wanted

- Underwriting fees and discounts: read each raise's gross and net proceeds from its
  prospectus (424B filings on EDGAR). That would give a measured cost of raising that
  could enter value without reading a share price.
- Forward burn from 8a, in years when a company's trial load moves by more than 30%.

## Seen on the way

The model's value per share sits far below the market for many clinical-stage names
(Revolution 17 against 184, Praxis 145 against 267, Vaxcyte 18 against 60, Summit 0.92
against 14.50), and 17 of the 34 have no per-share value at all. That is about pipeline
coverage, not runway, and worth its own look.
