# Building a marketed forecast for an asset the book does not model

Read this, then your company's file in `work/indication_backfill/asset_dossiers/`.

This is **not** the layer work. A layer is a pool and a penetration on top of a product
that already has a model. This is the model itself, and the book holds 353 of them to
copy the shape from.

## The absolute rule

**Never fabricate a value.** Every number names a source a reader can open. A number you
cannot source is left out with the reason stated. "Analyst consensus", "management
guidance" without a document, "industry typical" are not sources.

## Copy the company half; do not research it

Your dossier names a sibling seed for the same company. Copy `cogs_pct`, `sga_pct`,
`rd_pct`, `other_costs_pct`, `tax_rate`, `risk_free`, `erp`, `beta`, `cost_of_debt`,
`debt_weight` and `terminal_growth_pct` **verbatim, with their source text**. They are
the company's, not the product's. Re-deriving them puts two answers in the book for one
company, and the other-costs charge in particular is a long derivation you must not
restate in your own words.

`data/assumptions/lly_jaypirca.csv` says this out loud in its header and is the file to
imitate: "Ratios, discount rate and the other-costs charge are Lilly's own, from
lly_verzenio.csv."

## The product half, which is the actual work

**`therapy_mode`** = `marketed`.

**`base_revenue`** — the anchor, in **mm of the company's reporting currency**. This is
the one that matters most. In order of preference:
1. a reported full year for the product, from the company's own filing, named;
2. a run rate built from reported halves or quarters, with the arithmetic shown — the
   Jaypirca row is the model: "the first half of 2026 as reported, $357mm, and the
   second half at the second quarter's pace";
3. nothing. If the company folds the product into "other revenue" and names no figure,
   say so and stop. A product with no anchor is not modelled, and that is an honest
   answer that takes an hour rather than a day.

**Currency.** The engine models a company in its reporting currency and converts to
dollars once at the end, so the number is read as that currency whatever the unit label
says. A dollar figure on a sterling or franc filer overstates it by the exchange rate.
If your source is in dollars and the company reports in GBP, CHF, EUR or DKK, convert it
and show the arithmetic and the rate in the source text.

**`revenue_growth_pct`** — either the last reported year over the one before, or a rate
solved to reach a published peak. If solved, say "solved, not observed" and name the
peak and its publisher, as Jaypirca does.

**`revenue_ceiling_musd`** — a published peak-sales forecast with its publisher, where
one exists. Leave it out rather than invent one.

**`growth_fade_years`**, **`forecast_start_year`**, **`forecast_years`** — the horizon.
`forecast_years` should run past the loss of exclusivity the book holds for the product;
say which year you are running past and where that date comes from.

**`pos`** = 1.0, sourced "approved and selling".

**`net_price_per_patient` or `list_price_per_patient`** — where the dossier prints a CMS
per-beneficiary figure, use it, unit `mm <CUR> per patient-year`. It is the book's
convention (`amgn_abp_206.csv`). Pair it with `gross_to_net_pct` of 0.056604 on a Part B
anchor (the statutory 6% add-on, already net of manufacturer discounts) and the house
0.5 on a Part D one (CMS Part D spending is gross of rebates).

**`discontinuation_pct`** — CMS dosage units per beneficiary against a labelled year, or
a published median duration. Name which.

## Rules the verifier enforces

- a key the engine computes with is a **number or absent**, never a word like "not
  sourced". Leave the row out and say so in the header.
- every number names a source; shares sit in 0 to 1.
- a price is labelled in the company's reporting currency.
- two files in one batch may not give one disease two pools.

## Format

Header exactly:
`ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note`

`brand` must match the dossier exactly. `indication` empty for every row here — this is
an asset model, not a layer. `region` = US, `scenario` = base, `year` empty. Open the
file with `#` comment lines saying what the product is, where the anchor came from, and
what you could not source.

One file per asset: `work/indication_backfill/drafts/<ticker>_<brand_slug>.csv`

**If a file of that name already exists, you are adding to a product the book already
models — stop and say so rather than writing it.**

## Verify

```
python3 work/indication_backfill/verify_seeds.py work/indication_backfill/drafts/
```

Fix everything it reports.

## Report

How many assets you modelled, how many you could not anchor and why, and which numbers
you are least confident in. An honest "no reported figure exists for this product" is a
complete answer and is worth more than a guessed anchor.
