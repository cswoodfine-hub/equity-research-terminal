# Autorun: price every gate that can be priced

Written 2026-10-28, when Charles left with this instruction: *"continually run this and
find solutions until every gate is priced and then give me a summary very clear of what
was done. I also am low on credits so when they expire, continue when the limit
refreshes."* A session resuming cold reads this file top to bottom, then `HANDOVER.md`,
then continues from the first unchecked step. Update the log at the end of every round.

## The rules that do not bend

- Never fabricate a value. "No filed figure", "failed", "already approved" and "cannot be
  sourced" are complete answers, and the gates they leave unpriced are the honest floor.
- Never touch the real book (`backend/er_tool.db` is a symlink to it). Work on copies
  with `ER_TOOL_DB=<copy>`; the scratch disk fills at about 40 copies, so delete old ones.
- Before loading: `verify_seeds.py` over the drafts, then read a sample by hand.
- Load with `integrate.py --load` only. It appends; never make it copy.
- Conventional commits, one concern each. No em dashes; never the words additionally,
  highlight, underscore, pivotal, showcase, testament.
- Seeds are insert-only. A wrong row written today, before the book loaded it, may be
  taken out of its seed the same day (as Inlexzo's was); anything older is a terminal edit
  for Charles, listed under "For Charles".

## How to measure (on a copy of the published book)

```bash
S=<scratchpad>/book                         # holds er_tool.db.backup and release.db.gz
cp $S/r4_post.db.backup $S/x.db.backup       # or the latest loaded copy
ER_TOOL_DB=$S/x.db.backup python3 work/indication_backfill/tools/remap.py   # aliases, trial map, merges, indications
ER_TOOL_DB=$S/x.db.backup python3 work/indication_backfill/nogate.py $S/x.json
ER_TOOL_DB=$S/x.db.backup python3 work/indication_backfill/steps_to_priced.py $S/x.json
```

If the scratch folder is gone (a new container), the copy is the published release's
database: download the release asset the Streamlit app reads (`streamlit_cloud_app.py`,
`ER_DB_REPO`), gunzip it into the scratchpad, and start from that. The copy reads lower
than the book (141 where the book read 142 earlier the same day), so report deltas.

## State at 2026-10-28, end of day

On the copy: **173 catalysts priced** (129 at the start of the day). 243 at `no_gate`:

| what a catalyst still lacks | count |
|---|---|
| link + asset model | 70 |
| asset model | 41 |
| link + layer seeds | 36 |
| layer seeds | 35 |
| link + asset price/disc + layer seeds | 19 |
| nothing (should price on rebuild) | 14 |
| asset price/disc + layer seeds | 12 |
| phase + asset model | 11 |

## Steps

- [x] 1. **Linking round.** DONE 2026-10-28: 87 of 124 readouts linked. Four agents on `linking/WORKLIST_G1..G4.md` (124 readouts, 94
      assets), brief `linking/BRIEF_LINKING.md`. Outputs `linking/G*_additions.csv`,
      `G*_paediatric.csv`, `G*_NOTES.md`. Linking now reads the additions file: a study a
      row names reads out in that pair (commit "a study a curated addition names").
- [x] 2. **Integrate linking.** DONE: 75 addition rows, 2 paediatric rows, 15 trial remaps, 3 aliases; linked 530 to 621, no_gate 243 to 202, priced 173 to 176. Check every MeSH id, no study on two rows of one asset,
      append to `data/asset_indication_additions.csv` and `data/paediatric_indications.csv`,
      remap a copy, measure.
- [ ] 3. **Layer and model round** over what step 2 leaves at one or two steps: re-run
      `tools/open_units.py` and `steps_to_priced.py --phase 1b`. Briefs: `BRIEF.md`
      (layers), `BRIEF_ASSET_MODEL.md` (marketed), `BRIEF_PIPELINE_MODEL.md` (clinical).
      Exclude everything already answered (overlap 1.0, pos 0, held, no filed figure).
- [x] 4. **The 14 "nothing" catalysts.** DONE: second readouts on a priced layer, now labelled same_gate_later (commit "a second readout on a priced layer"). Find why each is not priced (`nogate.py` reason,
      `why_nogate.py`) and fix the rule or the data.
- [ ] 5. **Load, suite, commit.** Full suite on the loaded copy (`-n 4 --timeout 300`),
      compare against the eleven failures that predate 2026-10-28, fix anything new.
- [ ] 6. Repeat 3 to 5 until a round prices nothing new.
- [ ] 7. **Summary for Charles**: what was done, the number at each step, what is left
      and exactly why each remaining gate is unpriced.

## In flight

- Round 2 (step 3), launched 2026-10-28 ~19:30 UTC: layers L5 and L6
  (`round2/LAYERS.md`), marketed models M3, clinical models C4, C5, C6
  (`round2/MODELS.md`). Reference copy: `<scratchpad>/book/r6.db.backup` (linking and
  aliases applied). Not yet loaded and waiting with them: `drafts/jnj_icotyde.csv`,
  `azn_baxfendy.csv`, `axsm_sunosi.csv`, `axsm_axs_14_esreboxetine.csv`, the Evenity
  paediatric rows appended to `amgn_evenity.csv`.

## Earlier in flight

- Layer agent L4: Icotyde (psoriatic arthritis, UC, Crohn's), Baxfendy (primary
  aldosteronism), Vyvgart in Graves disease. Drafts land in `drafts/`.

## For Charles (decisions only he can make, or terminal edits)

1. The patent plan, step 1: correct the exclusivity dates (Wayrilz 2041 against a 2033
   compound patent; Lumakras, Vanrafia; Xofluza has an approved generic since June 2026).
2. DECIDED by Claude at Charles's request: Axsome takes a profitable comparator's company
   half (AbbVie's); Rinvoq Takayasu and Evenity's osteogenesis imperfecta layer corrected
   by migration 093, with Baxfendy's discontinuation.

## Log

- 2026-10-28 evening: linking round (87 readouts), engine fixes (patient-mode layers
  risked, additions link their studies, overlap asked before keys, repeat gates labelled),
  BioNTech to EUR, migration 093, Axsome decided. Round 2 launched.

- 2026-10-28: Phase 1b, Phase 3, paediatric rows, the layer and asset-model round. 129
  to 173 on the copy. Engine fixes: the gate nets a layer's overlap; a layer on a patient
  built product is risked at its own odds; merge survives a readout on a shared pair;
  additions link their studies. BioNTech corrected to EUR.
