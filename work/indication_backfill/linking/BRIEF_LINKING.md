# Linking a readout to the disease it reads out in

A pending readout is priced only once it names one of its asset's indication rows. The
readouts in `WORKLIST.md` name none, for one of four reasons, printed against each:

- **ambiguous**: the registry indexes the study under two or more of the asset's rows.
- **registry indexed no MeSH term**: the registry gave the study no descriptor at all.
- **registry terms match none of the asset's rows**: the study is in a disease the asset
  has no row for, or the registry's descriptor is broader or narrower than the row.
- **paediatric title**: the title says children, and the asset has no paediatric row for
  that disease.

## What you write

Read each study's record (`https://clinicaltrials.gov/api/v2/studies/NCTxxxxxxxx`: the
conditions, the eligibility, the arms and the primary outcome) and decide which one
disease it reads out in. Then write a row, in one of two files under
`work/indication_backfill/linking/`, named after your group:

1. `<group>_additions.csv`, header exactly `ticker,asset,mesh_id,term,nct_ids,basis`, the
   shape of `data/asset_indication_additions.csv` (read its rows: they are the standard).
   - The study's disease is one of the asset's existing rows: name that row's MeSH id and
     term exactly as `WORKLIST.md` prints it, and the study. The readout then links to it.
   - The asset has no row for it: name the real MeSH descriptor (check it at
     `https://id.nlm.nih.gov/mesh/lookup/descriptor?label=...` or the MeSH browser,
     `https://meshb.nlm.nih.gov`) and term. The row creates the pair.
   - Several studies of one asset in one disease go on one row, NCT ids space-separated.
   - Never name one study on two rows of the same asset: that decides neither.
2. `<group>_paediatric.csv`, header exactly
   `ticker,asset,mesh_id,term,adult_mesh_id,nct_ids,label_from_age,basis`, the shape of
   `data/paediatric_indications.csv`, for a study that enrols only children: the label's
   approved lower age (DailyMed is reachable) and the registry's ages, both cited.

`asset` is exactly the name `WORKLIST.md` prints after the ticker. `basis` cites what you
read and where, in a sentence or two, as the existing rows do.

## Complete answers that are not a row

Write these into `<group>_NOTES.md`, one line per readout:

- the study genuinely reads out in two diseases at once (a basket, an extension across
  indications): no row, and say which;
- the study is not a readout of this asset at all (it tests another drug, the asset is
  background therapy or a comparator): say which asset it belongs to, with the evidence;
- the study enrols adults and children together and the label already covers both;
- it could not be established, and what would settle it.

## Rules

- Never fabricate. A MeSH id you have not seen on a MeSH page or in the registry record is
  not written.
- Do not choose the disease that would be worth most; choose the one the protocol says.
- Do not edit any file outside `work/indication_backfill/linking/`, do not touch any
  database, do not commit or push.
- House style for prose: no em dashes; never the words additionally, highlight,
  underscore, pivotal, showcase, testament.

## Report

Rows written by file, readouts covered, readouts with no row and why, and any you are
unsure of.
