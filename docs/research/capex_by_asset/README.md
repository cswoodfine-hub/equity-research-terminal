# Plant spending tied to named products

Researched 2026-11-17, to see whether any asset should carry its own plant rate
(`growth_investment_pct`) in place of the pooled one. `commitments.csv` beside this file
is the register: 46 filed commitments (Lilly 23, Novo Nordisk 16, Amgen 6, Legend 1), each
with the filing's own words and its accession number.

## The answer

No asset earns a rate of its own. Filings give site budgets, never a product's share of
them, and for the two companies building most (Lilly and Novo Nordisk) the plant is mostly
not in service yet, so capex over revenue added is a build-out and not a steady rate.

| Family | Verdict | Why |
|---|---|---|
| Tirzepatide (Mounjaro, Zepbound) | record only | 0.383 capex above depreciation per dollar added, 2022 to 2025, but 77% of it is construction in progress and it is all of Lilly's capex, so an upper bound |
| Foundayo | record only | no site names it; launched Q2 2026, so no revenue window |
| Retatrutide | nothing filed | |
| Semaglutide (Ozempic, Wegovy, Rybelsus) | record only | 0.641 to 0.717, but 99% of the gap is assets under construction, and Novo has since impaired DKK 3.6bn of them |
| CagriSema, cagrilintide | nothing filed | |
| MariTide | nothing filed | Amgen's plants are described as multi-product; no revenue yet |
| Carvykti (Legend's half) | record only | 0.281, within 0.035 of the pool |

## What the research found about the pooled rate

The pooled capex rate the valuation charges, 0.316 per dollar of revenue added across 15
filers, is half incretin build-out. Lilly and Novo Nordisk are 29% of the revenue the
pool added and 49% of its capex above depreciation. Without them the rate is about 0.23.
Checked against `growth_investment.pooled` on 2026-11-17: the pool's capex gap is $73.6bn
on $232.5bn added; Lilly and Novo are $36.4bn on $67.0bn.

So the open question is not whether an incretin should be charged more than the pool. It
is whether every other company is being charged an incretin's plant. Splitting the pool
would be a change to the engine and would move every valuation, so it is a decision, not
a data row.

## A gap the register shows

A rate on revenue added charges nothing for plant already committed unless the forecast
adds the revenue to match. Lilly has announced about $63bn and spent $29.3bn from 2020 to
September 2026. Novo Nordisk has DKK 67.5bn left on named projects while guiding lower
sales. Neither is in the valuation as a commitment.

## A check on the forecast capex rule

Amgen guides about $2.6bn of capex for 2026. The Forecast tab's rule (plant upkeep at the
company's depreciation over revenue, plus 0.316 per dollar of revenue added) draws $2.2bn.
