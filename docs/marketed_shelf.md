# Is it actually still being sold?

Measured 2026-11-02 against the live book, 1,524 marketed products. Every figure here is
computed from `backend/shelf.py`, not estimated.

## The question

"Marketed" in this book meant "was approved and nobody has said otherwise", which put
three different things under one word and one blank revenue column: a product the company
stopped selling, a product that sells and that no free source breaks out, and a product
nobody has modelled. They look identical on the page and need opposite responses.

## The reading that settles it

openFDA states a `marketing_status` on every application and `fetchers/approvals_openfda.py`
had read it since the fetcher was written and thrown it away. It is now stored
(`approvals.marketing_status`, migration 103) and resolved per asset in
`backend/marketing_status.py`. Across the book: 958 applications Prescription, 564
Discontinued, 38 over-the-counter, 1 unresolved.

The status of an asset is the **strongest** across every application it holds, not the
latest one's. Reading the newest application alone withdrew $11.7bn of selling revenue,
because a brand whose superseded formulation is discontinued and whose current one is not
is still sold.

## The six states

| state | products | revenue $mm | carrying no revenue |
|---|---:|---:|---:|
| selling, protected | 448 | 625,479 | 259 |
| selling, off patent | 161 | 86,702 | 105 |
| selling, exclusivity unknown | 276 | 11,367 | 265 |
| withdrawn in the US, still earning | 5 | 8,525 | 0 |
| withdrawn in the US | 416 | 0 | 416 |
| status unknown | 218 | 205,528 | 99 |

**416 products are not sold in the US and every one of them earns nothing.** That is the
bulk of the blank revenue column, and the blank was the answer rather than the gap.

**161 products earning $86.7bn are already past their exclusivity**, so generics or
biosimilars are on the market against them today.

Two unknowns are kept apart on purpose. A product the FDA says is on sale whose
exclusivity the book does not hold is a gap in the patent data; one whose status the FDA
does not resolve is a gap in the registry. Together they put $216.9bn under one word that
meant neither. The 218 with no status are mostly the filers who register outside the
United States.

## Why the fourth state exists

The reading is American and the revenue line beside it is worldwide, so the two can
disagree, and where they do the product gets its own state rather than being filed under
either.

Five products, $8,525mm: Pfizer's Vyndaqel ($6,380mm), GSK's Ventolin ($703mm),
AstraZeneca's Pulmicort ($518mm), Bayer's Adalat ($503mm) and GSK's Flovent ($421mm).

They are not one thing. Adalat and Flovent are genuinely ex-US: Bayer and GSK withdrew
them here and sell them in Europe and Japan. Vyndaqel is not. Pfizer holds two tafamidis
applications, NDA211996 (Vyndaqel, Discontinued) and NDA212161 (Vyndamax, Prescription),
and the whole family's $6,380mm sits on the first because that is the row the filer tags.
Calling the state "withdrawn" would read as $6.4bn of dead revenue; calling it "selling"
would contradict the FDA. It is both, and the state is the pair.

## What this changed in the valuation

One rule, in `loe.for_assets`: **a product the FDA says is not on sale here cannot lose
US exclusivity, so a date still ahead of it is not a cliff.** Vizimpro sat in the 2032
column of the cliff chart on a patent protecting a product Pfizer stopped selling in 2023.

Narrow on purpose, two ways:

- **Only a future date.** A protection that already lapsed is history and reporting it
  costs nothing.
- **Only where the row earns nothing.** Revenue is the evidence that something under the
  row is still sold. Vyndaqel keeps its 2026-12-31 date, because the tafamidis molecule
  patent gates the family the row actually contains, and dropping it would hand a real
  cliff back five years of annuity.

Five assets lose a cliff they could not have: Recarbrio, Vizimpro, Lartruvo, Ryzodeg
70/30 and Duaklir Pressair. None carries revenue, so **no valuation moves**; what moves is
the cliff chart and every view that reads the same rule.

## What is deliberately not done

- **Inventing an ex-US exclusivity date.** Adalat's and Flovent's revenue is European and
  Japanese and the book holds no date for it. `backend/regional_loe.py` already erodes a
  reported region on its own stated date, with an EU statutory floor and SPC cap and a
  Japanese re-examination floor underneath, and it covers a region only where the filer
  prints the split. Where the filer does not, the region is absent rather than guessed.
- **Splitting a family revenue row across its applications.** Pfizer tags one row for
  tafamidis and the book does not know the Vyndaqel/Vyndamax split. The state names the
  ambiguity; it does not resolve it with a ratio nobody published.
