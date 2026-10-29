# LOE dates against launches that happened

Run 2026-10-29 on a copy of the published book, with the two new sources loaded (the
FDA Paragraph IV list as a spreadsheet, the USPTO's extension lists). Reproduce with
`ER_TOOL_DB=<copy> python3 work/patents/tools/backtest_dates.py`.

## The ground truth

The Paragraph IV list records, for each reference drug, the date the first challenger
began selling its generic. 332 reference drugs carry one. 122 of them join, by trade
name, to a USPTO extension certificate, which gives the molecule patent's extended
expiry. That pair (molecule date, launch date) is history and needs no archived Orange
Book. The list also gives each drug's "last qualifying patent", the far end of the stack.

Biases, stated rather than corrected: the list holds only drugs a generic challenged, and
the first challenger's launch can trail a generic that entered without one, so the truth
leans late. The trade-name join misses renamed and combination products.

## The rules, scored

| rule | bias (+ = launch later) | median error | within 6 months | within 1 year |
|---|---|---|---|---|
| molecule (extended) patent, no paediatric extension | +0.78y | 1.75y | 25% | 39% |
| molecule patent + 6 months paediatric | +0.28y | 1.64y | 31% | 44% |
| fitted point, 15% of the way to the last patent (half-split, held out) | -0.19y | 1.43y | 20% | 39% |
| last qualifying patent | -3.54y | 3.54y | 13% | 25% |
| **the filer's own disclosed date** (10 products with both) | small | **0.38y** | | 70%, most misses year-only dates read as 31 December |

On the 99 drugs whose last patent ran more than a year past the molecule patent, launch
came a median 28% of the way through the gap, spread almost evenly: 31 near the molecule
date, 34 in the next quarter to half, 32 in the back half, 2 after the last patent.

What cannot be scored: the book's current rule, the latest drug substance patent, because
expired patents leave the Orange Book and the list does not say which patents were
substance patents.

## What it means

1. **No patent-only rule dates a launch to within six months.** The best is a year and a
   half out, typically. The plan's bar of 80% within six months is not reachable from
   patents, and the plan is revised to say so.
2. **The molecule patent is the floor.** With its paediatric extension it is nearly
   unbiased on this sample, but its misses are long and mostly late: later patents and
   settlements held a generic off on half the drugs.
3. **The last patent is not the date.** Generics launched a median five years before it.
4. **A filer's disclosure is four times more accurate than any patent rule.** It knows the
   settlements. So the highest-value accuracy work is not a better patent rule; it is a
   disclosure for every large product still dated from patents.

## Checked by hand

- Farxiga: molecule patent plus paediatric extension 2026-04-04, generic launch
  2026-04-06.
- Januvia and Janumet: first generic 2026-05-28; the book read 2026-11-24 off a substance
  patent. Corrected by the launch rule.
- Revlimid: a 2022 launch under volume limits; BMS's 2026-01-31 is the cliff. The launch
  rule sits beneath a disclosure for this reason.
- Saxenda: disclosed 2023, launched 2025-08-28. The disclosure stands, since a launch only
  pulls a date earlier.
- Xeljanz XR: the list records a 22 mg launch on 2021-08-19, the same day as its approval,
  while the compound patent ran to 2025. Read as a probable list error; Pfizer's
  disclosure holds the date, so it moves nothing.
- Genvoya: its listed extended patents are elvitegravir's and cobicistat's, to 2027;
  tenofovir alafenamide's patents run to 2032 and its own extended patent is not listed on
  Genvoya. A combination's floor must read each component's own product, not only the
  patents listed on the combination.

## Where the date is weakest

123 marketed products not yet past their LOE rest on a patent rather than a filer's
date, holding 1,218bn of NPV on the copy. The largest:

| NPV mm | product | date now | basis | molecule floor |
|---|---|---|---|---|
| 200,947 | Ozempic | 2031-12-05 | curated compound patent | 2031-12-05 |
| 195,653 | Wegovy | 2031-12-05 | curated compound patent | 2031-12-05 |
| 133,301 | Mounjaro | 2036-05-13 | curated compound patent | 2036-05-13 |
| 65,186 | Zepbound | 2036-05-13 | curated compound patent | 2036-05-13 |
| 59,010 | Rinvoq | 2036-10-17 | drug substance patent | 2033-08-16 |
| 58,034 | NovoRapid / NovoLog | none on file | | |
| 37,048 | Awiqli | none on file | | |
| 29,426 | Alyftrek | 2040-08-13 | drug substance patent | |
| 28,672 | Foundayo | 2037-09-26 | drug substance patent | |
| 20,388 | Trikafta | 2037-12-08 | drug substance patent | |
| 19,983 | Kisqali | 2031-11-09 | drug substance patent | 2031-09-13 |
| 17,545 | Pluvicto | 2036-03-23 | drug substance patent | 2036-03-23 |
| 16,592 | Erleada | 2033-06-04 | drug substance patent | 2032-02-14 |
| 16,384 | Tagrisso | 2032-08-08 | drug substance patent | |
| 16,187 | Spravato | 2040-02-18 | latest patent (use) | 2033-03-05 |
| 16,132 | Camzyos | 2036-04-28 | drug substance patent | |
| 13,620 | Icotyde | 2041-01-14 | drug substance patent | |
| 12,818 | Verzenio | 2031-09-28 | drug substance patent | 2031-09-28 |
| 10,998 | Venclexta | 2032-01-29 | drug substance patent | |
| 10,959 | Vraylar | 2029-09-17 | drug substance patent | 2030-03-17 |

The floor column is empty where no extension certificate has issued yet (recent
approvals) or none is listed on the product.

## What moved on the copy

With the floor reported and not applied, 11 of 376 products changed date, from the
launch rule. Three changed value:

| product | before | after | NPV change | reading |
|---|---|---|---|---|
| Symbicort | no LOE on file, flat for ever | generic marketed 2023-07-31 | -8,300mm | date right (Breyna); the oral small-molecule curve on a global inhaler line overstates the fall, which is step 3's job |
| Zytiga | no date, default cliff in 2025 | generic marketed 2018-11-21 | +1,531mm | a correction: the default charged a cliff on revenue that had already fallen |
| Tasigna | "expired", no date | generic marketed 2025-05-23 | -812mm | the curve now runs from the launch |
