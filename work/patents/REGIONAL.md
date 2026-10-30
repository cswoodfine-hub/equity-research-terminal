# Step 5: regional dates, the EU SPC limit

Run 2026-10-29 on a copy of the book. Reproduce the date test with
`ER_TOOL_DB=<copy> python3 work/patents/tools/regional_backtest.py`, and the value delta
with `work/patents/tools/baseline.py` before and after the change.

## The rule

A supplementary protection certificate extends the molecule patent by up to five years,
and never past fifteen years from the substance's first EU authorisation (Regulation (EC)
No 469/2009, Art. 13). So a European region with no date of its own now takes:

- the filer's stated date where one is printed (unchanged; the cap never replaces it);
- otherwise the US date, held between two statutory bounds from the first EU
  authorisation in the EMA data:
  - **floor, 10 years:** data and market protection (unchanged);
  - **cap, 15 years:** the SPC limit (new).

`regional_loe.SPC_CAP_YEARS` sets the cap; `forecast.build` applies it in the regional
loop. A region carries `cap_year` and `cap_basis`, and the note names the regulation and
the authorisation it counts from.

## Date test: 120 products whose filers state an EU date

Each rule sees only what the book holds for a product with no stated date: the US date
and the first EU authorisation. Error is against the filer's stated EU year.

| rule | within one year | mean years out | median |
|---|---|---|---|
| inherit the US date | 57% | 1.77 | 1.0 |
| floor alone (the rule before) | 57% | 1.82 | 1.0 |
| cap alone | 63% | 1.57 | 1.0 |
| **floor beneath the cap (now)** | **63%** | **1.62** | 1.0 |

The cap alone scores slightly better on the mean. The floor stays because it is law,
not a fit: no generic can be marketed on the dossier inside ten years, and the cost on this
sample is 0.05 years.

Bias, stated: filers print regional dates mostly for their largest products, which carry
the most later patents, so the sample leans to products whose protection runs long.

## Value delta on the copy

9 of 376 products move; -2,511mm in total (book 2,606,574mm, -0.1%).

| ticker | product | US date | region (share) | cap | NPV before | after | change |
|---|---|---|---|---|---|---|---|
| ABBV | Rinvoq | 2036 | outside the US (29%) | 2034 | 56,685 | 54,585 | -2,100 |
| ABBV | Venclexta | 2032 | outside the US (53%) | 2031 | 10,270 | 9,685 | -584 |
| JNJ | Spravato | 2040 | outside the US (12%) | 2034 | 16,157 | 15,671 | -486 |
| ROG | Evrysdi | 2041 | Europe (35%) | 2036 | 7,081 | 6,612 | -469 |
| MRK | Zerbaxa | 2034 | outside the US (40%) | 2030 | 1,363 | 1,186 | -177 |
| AZN | Lokelma | 2035 | Europe (19%) | 2033 | 2,845 | 2,767 | -78 |
| MRK | Dificid | 2027 | outside the US (18%) | 2026 | 46 | 44 | -2 |
| AMGN | Enbrel | 2028 | outside the US (1%) | 2015 | 2,917 | 2,988 | +71 |
| ROG | Actemra | 2025 | Europe (24%) | 2024 | 1,206 | 2,520 | +1,314 |

**The two rises are a double count removed, not a lever running backwards.** A cap is
the latest a loss can be, so a past cap is a loss the reported revenue already carries.
Before, Europe inherited the US date and was cut again from it: Actemra's European sales
from 2025, though tocilizumab biosimilars launched in Europe in 2024; Enbrel's from 2028,
though etanercept biosimilars have sold in Europe since 2016. The floor works the other
way (a minimum, so a past floor is in the base only when the US record is), and that
branch is unchanged.

Checked: Actemra and Enbrel valued across US dates 2023 to 2035 rise in every year, so an
earlier date is never worth more. `test_loe_in_base` holds both cases.

## Limits, and what is not done

- **Outside the US as one region.** Where a filer reports only US and the rest, the rest
  takes Europe's date and bounds, as it already did for the floor. Japan inside it has no
  fifteen-year cap: its term extension runs up to five years from the patent.
- **Paediatric extension, measured and not applied (2026-10-30).** An SPC with a
  paediatric extension runs six months longer (Regulation (EC) No 1901/2006, Art. 36).
  - The EMA's PIP report (`medicines-output-paediatric_investigation_plans-output-json-report_en.json`)
    gives 401 plans a positive compliance check, the condition for the extension. The
    extension itself is granted country by country and is in no EMA record.
  - Tested on 125 products with a stated EU date, 41 of them with a positive check:
    a cap of 15.5 years from the authorisation date where the check is positive moves
    7 caps, 3 toward the stated date (both Jakavi rows, Eylea HD) and 4 away (Kalydeco,
    Veklury, Benlysta, Lutathera).
  - Exact years fall from 30% to 29% and the mean error rises from 1.568 to 1.576
    years. Filers appear to state the SPC year without the extension, so the cap stays
    at fifteen.
- **The extra year for a new indication** (Directive 2001/83/EC, Art. 10(1), the "+1" of
  8+2+1) is not applied. Neither EMA report records whether it was granted: the
  medicines report carries no such field, and the grant sits only in each product's
  Commission decision text.

## Japan: the re-examination floor (2026-10-30)

A new active ingredient approved in Japan is re-examined after eight years, ten for an
orphan drug, and no generic can be filed before then (Act on Pharmaceuticals and Medical
Devices, Art. 14-4). It is the counterpart of Europe's ten-year floor. Japan has no
counterpart of the SPC's fifteen-year cap.

- **Source.** The PMDA's English "List of Approved Products" (New Drugs, April 2004 to
  February 2026), one 3 MB PDF linked from
  `pmda.go.jp/english/review-services/reviews/approved-information/drugs/0002.html`.
  - `fetchers/approvals_pmda.py` reads it into `jp_approvals` (migration 100): 2,324
    rows, 750 of them new active ingredients, 479 marked orphan.
  - A release already read is never downloaded again (`jp_approval_releases`).
- **Match.** `regional_loe.first_jp_approval` takes the earliest row naming the
  product's generic (without the FDA's four-letter suffix) or brand. That row must
  itself be the new ingredient row. Where the product appears earlier in another
  kind of row, its first approval predates the list or shares a row with another
  substance, and no date is given.
- **Rule.** A Japanese region (`JP`) carries `floor_year`, first approval plus 8 (10 for
  an orphan), and the engine applies it as it does Europe's: it pushes a US date that
  falls earlier, and pushes a stated date that falls earlier. Asia Pacific and the rest
  of the world, which take Japan's stated date, do not take the floor, since the statute
  is Japan's alone.

Date test, `work/patents/tools/jp_backtest.py`, on 67 products with a stated JP date
(11 more lack a US date or a first approval in the list):

| rule | within one year | exact | mean years out |
|---|---|---|---|
| inherit the US date (the rule before) | 48% | 31% | 1.81 |
| floor, 8 years | 51% | 33% | 1.67 |
| **floor, 8 years, 10 for an orphan (now)** | **52%** | **34%** | **1.64** |

The floor moves four of them, and each moves toward the stated date:

| product | US date | floor | stated JP |
|---|---|---|---|
| Talzenna | 2029 | 2032 | 2034 |
| Truqap | 2030 | 2032 | 2033 |
| Reblozyl | 2031 | 2034 | 2034 |
| Tukysa | 2031 | 2034 | 2034 |

Value delta: +9mm in all, on Roche. Only Roche reports a Japanese line among the valued
products with no stated JP date (19 products, through Chugai). The floor binds on two:

- **Gazyva:** Japanese approval 2018-07-02, floor 2026 against a US date of 2025.
- **Pulmozyme:** an orphan drug approved 2012-03-30, floor 2022, which is past and in
  the base either way.
