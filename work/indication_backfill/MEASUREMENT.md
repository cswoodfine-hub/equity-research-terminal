# What the measurement said, 2026-10-26

Charles asked for research on ~230 unapproved indications across AZN/PFE/LLY/BMY.
Measuring first changed the job, twice.

## The gate surface

Reproduce: `python3 work/indication_backfill/nogate.py /tmp/out.json`

Before any of today's work: **133 catalysts priced, 340 at `no_gate`.**

`no_gate` is the reason a catalyst carries no dollars at stake. Splitting those 340 by
what is actually missing (`why_nogate.py`):

| cause | count | what fixes it |
|---|---|---|
| the catalyst names no indication | 212 | linking — deterministic, no research |
| the asset carries no model at all | 71 | a whole asset forecast, not a layer |
| a selling product, layer phase, no layer seeds | **57** | **this is the research job** |

So the indication-layer research is worth 57 catalysts across 44 asset-indication
units, not 230. The larger block was never an epidemiology problem.

## The linking, after

Three rules were refusing links. All three are now fixed (commit 9d0bc56):

- a study of **adults and adolescents** was read as paediatric and diverted to a row
  the book does not carry — 21 readouts
- a MeSH **parent descriptor** alongside its own child made a readout ambiguous —
  Obesity/Overweight alone was 38 readouts
- a study the registry **never indexed** was dropped rather than read from its
  condition text — 21 readouts

Measured: **406 unlinked catalysts to 320.** `no_gate` 340 to 332; the difference is
small because a linked catalyst then meets the next blocker, which for most of them is
an asset with no model.

## The worklist

Reproduce: `python3 work/indication_backfill/worklist.py` (idempotent; merges onto
itself and never clobbers a status).

225 asset-indication units on products that already sell something:

| status | count | meaning |
|---|---|---|
| todo | 95 | needs a pool researched and a layer argued |
| reuse_pool | 87 | the disease's pool is already sourced in the book |
| parked | 23 | Phase 1 / Phase 1-2, outside the phases the engine prices |
| seeded | 20 | already carries layer rows (the Lilly work) |

48 of the open units have a pending catalyst behind them. Those are worth most: they
convert directly into priced gates.

`reuse_pool` saves the pool row, not the layer. The eligibility narrowing, the
penetration peak and the overlap still have to be argued per asset.

## Found in passing, not acted on

Seven seed files name a brand the book has no asset for, so `load_seeds` skips every
row in them silently and the file reads as loaded when nothing happened:

    AMGN / Be One          GILD / Symtuza Revenue Share    JNJ / Abiomed
    JNJ / SURGICAL         NVS / Promacta Revolade         NVS / Tafinlar Mekinist
    PFE / Pfizer Centre One

Two are combination spellings of assets that do exist (Promacta, Tafinlar). The rest
are business segments with no asset row. Worth a look, separately.
