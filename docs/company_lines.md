# Company lines and the launches they pay for

A company line is revenue a filer reports that no product model carries: a basket of older
brands, a royalty, contract manufacturing. Seeds live in `data/company_lines/`, one row per
key with a source on every row, and run through the same engine as a marketed product
(`backend/company_lines.py`). Seeds are insert-only, so an edit to a file reaches a
database only through `company_lines.save` (or `assumptions.save` for an asset seed).

## Which revenue buys launches

The future pipeline (`backend/future_pipeline.py`) values the launches the book's R&D
buys, at a rate measured on human drug launches. A line carries `buys_launches` 0 when its
revenue is not a medicine the filer sells or co-sells:

- royalties, and profit or revenue shares on a medicine another company sells
- contract manufacturing
- distribution and other services
- devices
- medicines for animals

None of these earns the filer a human drug approval, so the line's revenue is not part of
the book the launches refill, and its margins do not cost them. The line is still valued,
costed and counted in coverage.

Its R&D is another matter. Every line is charged the company's R&D ratio, and the launch
rate divides launch revenue by the company's whole R&D, that line's share included. So the
R&D a royalty or contract manufacturing line is charged buys launches like every other
dollar the rate counts: charging it and crediting nothing would rebuild the asymmetry the
horizon section below refuses. Only where the rate divides by a medicines segment's R&D
(Johnson & Johnson's, `data/rd_medicines_segment.csv`) is the line's R&D outside it, and
there it buys nothing.

A medicine the filer co-sells and books as alliance or collaboration revenue keeps buying
launches: Merck's Lynparza, Biogen's Leqembi, Regeneron's Dupixent, which Regeneron
co-promotes. The filer sells it, so it is revenue its launches replace, and the launch rate
counts a co-development's revenue as what R&D buys (`data/partner_funded_launches.csv`).
A line that mixes product sales with collaboration revenue (AbbVie's Imbruvica and Epkinly,
Sanofi's established medicines with industrial sales inside) is a product line and keeps 1.

The same key applies to an asset seed whose revenue is of one of these kinds: Pfizer
CentreOne, Gilead's Symtuza revenue share, Amgen's BeOne profit share, Johnson & Johnson's
Abiomed and surgery business.

Every flag carries a source saying what the revenue is, and
`tests/test_company_lines.py` holds the rule on the seeds.

## A line that is running off keeps running off

A line's terminal growth is the decline its own filings show, not a flat perpetuity. A
basket of older products does not renew itself, the launch line does that, so a basket
held flat for ever both overstated its own value and kept paying R&D into the launches for
sixty years. The rate is the log-linear fit to the years the latest annual report prints
on the line's own like-for-like definition, which on three years is the compound rate from
the first to the last. The near-term rate, sourced as before, fades into it over the
line's fade years.

- Where products joined a basket during the window, the fit is on the products it held
  throughout (Amgen's Other products: the line grew only as Ravicti, Procysbi, Pavblu and
  Wezlana joined it, while the products it held all three years fell 0.94% a year).
- Where one product ended inside the window, the fit leaves it out and says so (Johnson
  & Johnson's tail without the COVID-19 vaccine's fall).
- Where the filings show no decline, the line is left as it is and listed in
  `tests/test_company_lines.py`, so a new flat line has to be read before it is accepted.

## How far spend buys launches

`future_pipeline.simulate` runs sixty years from the valuation year
(`data/future_pipeline_defaults.csv`, `horizon_years`). R&D spent in year s, the book's own
and, past each product's forecast, the R&D its terminal value charges at its final-year
ratio, buys a cohort that launches at s + 8 (`lag_years`) and earns the filer's blended
launch rate on that spend for 12 years (the `unknown` row of `data/loe_defaults.csv`), then
drops 25% and decays 20% a year (`data/erosion_defaults.csv`). The rate is the same for
every vintage. So spend from the first forecast year to the 52nd buys launches, the last of
them landing in the 60th year, and cash is counted to the 60th year with no terminal value.
Two caps hold it: launch revenue fills only the room the book leaves below its best real
year, grown at 10-year breakeven inflation, and the launches' own R&D is credited only as
far as it holds the franchise at that real size.

The horizon is not cut, for three measured reasons.

- The cost runs further than the credit. Every product's terminal value charges its R&D for
  ever, so spend after the 52nd year is charged and buys nothing. Cutting the credit at an
  earlier year while keeping the charge would rebuild the asymmetry the future pipeline
  exists to remove. At Amgen, cutting it at the 12-year cohort term the rate is measured on
  takes the future pipeline from 145.93 to 87.94 a share, while the 34.7 a share of
  after-tax R&D the book charges from 2038 to 2077 stays charged.
- No sourced trend says the next dollar buys less. The module measures revenue per lagged
  R&D dollar falling 5.5% to 6.6% a year across past vintages and uses that decay to set
  today's rate, which nets it against the lag. Carrying it forward is a further claim the
  data does not settle: the late cohort's rate against the early one bootstraps from 0.25
  to 1.19.
- Discounting and the caps already bound it. On 2026-10-06, across the 22 companies with a
  future pipeline, a median 17.5% of its value is bought by spend after 2045 and 7.0% by
  spend after 2055 (Amgen 22.4% and 9.2%).

What made a line pay for fifty years of launches was its own flat perpetuity, which the
terminal rule above corrects: a basket running off spends less R&D each year it falls.
