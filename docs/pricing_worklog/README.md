# Phase 3 pricing worklog

Working state of the pricing step for the 75 Phase 3 assets the sort marked NEW
(`data/pipeline_sort.csv`), saved so a later session can continue it. Nothing here is read
by the app. A seed enters the book only after a second reader has reopened every source,
and only then is it assembled into `data/assumptions/`.

Progress per asset is in `status.md`.

## Method

1. A researcher agent reads `BRIEF.md` and the asset's context file in `ctx/`, and writes
   `research/<TICKER>_<slug>.json`: price, gross to net, uptake, pool, each with a source.
2. A second agent, following the "second reader" section of the brief, reopens every source
   and writes `verified/<same file>` with a verdict per field.
3. `assemble.py verified/<file>.json` writes the seed into `data/assumptions/`, copying the
   company-level rows from the company's existing seed and any pool another asset already
   carries for the same disease. Then load the seeds, build the asset, and fix a price's
   currency where the company reports in euros, pounds or kroner (the seed shape test
   catches it).

## Running it again

The scripts and brief use fixed paths under `/tmp/claude-0/price`. Recreate that layout:

    mkdir -p /tmp/claude-0/price/out
    cp -r docs/pricing_worklog/{BRIEF.md,lookup.py,assemble.py,index.json,ctx,verified} /tmp/claude-0/price/
    cp docs/pricing_worklog/research/*.json /tmp/claude-0/price/out/
    cp backend/er_tool.db /tmp/claude-0/price/book.db     # read-only copy for lookup.py

## Why it stopped

The second reader needs to open sources. This session's web search allowance ran out
(200 of 200) and the container's network reaches GitHub and PyPI only, so the 13 researched
files in `research/` wait on a second reader and 46 assets have not been researched.
