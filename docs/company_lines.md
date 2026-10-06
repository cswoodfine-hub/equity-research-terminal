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

None of these earns the filer a human drug approval, so the future pipeline leaves the line
out. Its R&D buys no launches, its revenue is not part of the book the launches refill, and
its margins do not cost them. The line is still valued, costed and counted in coverage.

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
