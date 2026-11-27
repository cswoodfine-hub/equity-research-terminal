# Lilly: the seven gaps of 2026-11-27, closed, and the checks that report the next

Date: 2026-11-27. Book: the published database of 2026-11-27 (release `data-latest`,
digest 5345966651e8…), restored into `backend/er_tool.db` and read through the API before
anything was changed. Branch `claude/lilly-coverage-gaps-stufah`, seventeen commits on top
of `f8622d7`. Nothing went to `main`.

Out of scope on instruction, and untouched: the other-costs charge, the Mounjaro,
Zepbound and Foundayo ceilings, tirzepatide's 2036 exclusivity. Part 6 reports what was
found about them.

## Part 1. Before and after

Measured on the same book, the before column through the API on the untouched database,
the after column through the same modules once every register change had been applied by
hand in the refresh's own order (alias map, merge, programme names, arm pruning,
indication pairs, seeds, lines, ledger, settled readouts).

| Measure | Before | After |
|---|---|---|
| Fair value, sum of the parts, mid ($ a share) | 509.61 | 511.78 |
| Products on sale | 299.05 | 298.83 |
| Named pipeline | 36.68 | 45.86 |
| Other revenue lines | 29.79 | 24.10 |
| Launches the model assumes | 212.39 | 211.43 |
| Plant for growth, roll-forward, net debt | −68.29 | −68.43 |
| Coverage of FY2025 revenue | 97.16% | 95.61% |
| Assets with a forecast | 36 | 43 |
| Refused with a seed | 1 (mazdutide) | 0 |
| Phase 3 rows with no forecast | 4 | 1 (SPLASH, by decision) |
| Phase 2 rows with no forecast | 6 | 3 (gandotinib, LY3537021, VTX2735, each with its reason) |
| Seed files unattached | 1 | 0 |
| Catalysts priced / unpriced | 23 / 46 | 23 / 46 |
| of which unexplained (`no_free_data`, `past_gate`, `needs_layer`) | 12 | 7, all re-checked and dated |
| Acquisition rows since 2025 / with terms | 22 / 0 (9 wrong) | 18 / 17 (Adverum's aggregate is in no Lilly filing) |
| Modelled 2026 ($m, products, run rates, lines) | 88,400 | 89,613 |
| Plus prior-year revenue no row tags | 1,854 | 2,863 |
| Expected 2026 against guidance $91.0bn to $92.0bn | 90,254 (−1.4%) | 92,476 (+1.1%) |

Coverage falls while the model improves. The coverage metric counts FY2025 revenue the
SEC data sets tag plus the company lines' anchors, and the Other immunology line's anchor
fell from $1,020m to $37m because it had carried Olumiant a second time (Part 2, gap 6).
Olumiant is modelled on a 10-K line the data sets do not tag, so netting it out of the
line reads as 1.5 points of coverage lost and $1.0bn of double count gone.

## Part 2. The change in fair value, split by gap

The per-share value moved $2.17. The attribution is by component on the one after
book rather than by re-reading the book after each commit, because each read of Lilly's
fair value takes minutes and the components separate cleanly.

| Source of the move | $ a share | What moved it |
|---|---|---|
| Gaps 1 to 4: seven new forecasts | +7.90 | EloraTZP 5.16, tersolisib 0.77, bimagrumab 0.75, mazdutide 0.66, amezosvatein 0.41, BPL-003 0.13, LY4515100 0.02 |
| Gap 3, a side effect on the shared obesity pool | +1.28 | retatrutide +0.64, eloralintide +0.45, LY4086940 +0.08, macupatide +0.06, LY3457263 +0.06. The refused mazdutide seed already held pool rows, so `pool_crowding` counted it as a rival at the odds of an asset with no phase; completed at 0.1685 it claims less, and the share of its claim each Lilly claimant keeps rose from 86.5% to 91.1% |
| Gap 6: anchors re-struck | −0.22 on products | Mounjaro +1.49, Zepbound +1.86, Trulicity +0.78, Verzenio −2.46, Taltz −2.43, Jardiance −0.06 |
| Gap 6: Olumiant netted from Other immunology | −5.69 on lines | the line's anchor from $1,020m to $37m; the other four lines moved $0.1 together |
| Gap 6: the assumed launches and plant | −1.25 | the launch productivity rule reads the revenue the book now carries |
| Gaps 5 and 7 | 0 | settling a readout and correcting a note move no value |
| Residual (roll-forward and rounding) | +0.15 | |

## Part 3. Every new seed

Each file carries the company-level rows verbatim from `lly_ly3457263.csv`, every row its
source, and every judgement marked as one on its row.

| Asset (file) | Phase | Pool and price | Launch | Odds | Exclusivity (engine) | Risked value, $m | Per share | Judgements |
|---|---|---|---|---|---|---|---|---|
| EloraTZP (`lly_eloratzp.csv`) | Phase 3, two studies to 2029-10 | US obesity, incretin median $8,839, half off | 2031, primary completion plus two years | 0.5452, derived | 2043 | 4,641 | 5.16 | the 0.5x capture multiple |
| Tersolisib (`lly_tersolisib.csv`) | Phase 3, NCT07174336 to 2029-05 | 160,000 metastatic HR+/HER2− x 0.40 PIK3CA x 0.70 on endocrine therapy; Truqap Part D $81,962 a beneficiary | 2031 | 0.4727, derived | 2043 | 694 | 0.77 | uptake at the class's Medicare-only count, multiple 1.0 |
| Bimagrumab (`lly_bimagrumab.csv`) | Phase 2 complete | US obesity, incretin median | 2032 | 0.1918, derived | 2044 | 676 | 0.75 | launch year; the incretin price for an infused antibody |
| Mazdutide (`lly_ly3305677.csv`) | Phase 2 complete, no active study | US obesity, incretin median; pool rows were already there | 2032 | 0.1685, stated from the gate model's own chain because the asset has no phase to place | 2046 | 593 | 0.66 | launch year; modelled rather than retired |
| Amezosvatein (`lly_amezosvatein.csv`) | Phase 2 complete | 123.3m US adults 50 and over (Census Vintage 2024), 56.4% unvaccinated (NHIS 2024); Shingrix $242.67 a dose (CDC list, 1 July 2026), two doses, 19% off | 2032 | 0.2283, derived | 2044 | 368 | 0.41 | launch year; a quarter of Shingrix's measured yearly reach |
| BPL-003 (`lly_bpl_003.csv`) | Phase 2b complete, Phase 3 begun by the target's account | 2.8m US adults with TRD (Zhdanava 2021, PMID 33989464); Spravato Part D $23,121 a beneficiary, half off | 2031 | 0.1253, derived | 2043 | 118 | 0.13 | launch year; Spravato's yearly spend as a course price; half its measured reach |
| LY4515100 (`lly_ly4515100.csv`, rebound) | Phase 2 | the seed as written on 2026-09-28, unchanged | 2031 | 0.1253, derived | 2043 | 14 | 0.02 | none new |

Launch years follow the book's convention where a Phase 3 exists (earliest primary
completion plus two calendar years) and are judgements with the case for and against on
the row where none does.

## Part 4. What stays unvalued, and the exact input each lacks

- **[Lu-177]-PNT2002 (SPLASH).** Primary completion 2023-11-01, rPFS met, no submission.
  Lantheus declined to file, Lilly's FY2024 and FY2025 10-Ks list no PNT2002, and EDGAR
  full-text search returns nothing from Lilly on it in 2026. Lacks a filing or a Lilly
  statement of intent to file. Recorded in `settled_readouts.csv` as `no_free_input`.
- **VTX3232 (Ventyx).** Both Phase 2s are complete and sit in `completed_trials`
  (NCT06771115 obesity and cardiovascular risk, NCT06556173 Parkinson's), so no asset row
  exists; Lilly has started nothing. Lacks a next study, a declared indication, and a
  price analogue: no NLRP3 inhibitor is sold, and the Ventyx proxy's projections are
  partnership royalties, not product sales.
- **VTX2735 (Zomagen, bought with Ventyx).** Phase 2 in recurrent pericarditis, now an
  asset row through the ledger's sponsor names. Lacks a price and a capture: the one
  marketed drug in the disease, Arcalyst, is Kiniksa's, outside the universe, so the book
  holds no comparator seed. The bought-and-unvalued read names it.
- **KLN-1010, ORN-252, MER511, AJ1-11095, STC-004 (as such), LimmaTech's and Vaccine
  Company's programmes.** Phase 1 or earlier: ledger rows, no forecast, by the rule.
- **Gandotinib (LY2784544).** One Phase 2 that completed in 2015 and nothing since;
  named so the row reads as a molecule, left unmodelled on purpose.
- **LY3537021.** Settled `no_free_input` on 2026-11-16; re-checked, still no Lilly filing
  names it.
- **Jardiance's re-struck growth rate did not reach the book.** The file carries 0.4837;
  the book holds 0.0272 while its ledger says the seed wrote 0.0966, so
  `reconcile_seeds` treats the row as an analyst's and leaves it. The fade did move to
  five years. Set the rate in the terminal, or the row stays at 2.7%: that is $1.57bn of
  2026 revenue (5,092 against 3,525) and about $0.9 a share.

## Part 5. The gaps, what was found and what was done

**1. Acquisitions.** `deals.enrich` took figures from any exhibit within five days of a
headline that mentioned the party anywhere, and Lilly furnishes no 8-K for an
acquisition, so the only exhibit was the earnings release: nine rows carried Boehringer
Ingelheim's Jardiance milestone or the guidance raise as their terms, and a filled
`headline_usd` kept them from being read again. The same defect had filled 78 rows across
the universe. The parser now binds a figure only where the party is named in its sentence
or the one before, and clears every misread fill. The terms themselves live in the 10-Q
acquisitions note, which nothing stored, so `data/acquisitions.csv` is the ledger: 24
Lilly rows from Akouos (2022) to LoQus23, each from the 10-Q or 10-K that states its
consideration, cash paid net of cash acquired, maximum contingent consideration or
acquired IPR&D charge, with the announcement where the filing has not caught up (Calytrix
agreed, LoQus23 announced, Merida's split unfiled, Adverum's aggregate in no Lilly
filing). The loader folds the headline and filing duplicates into the one row and names
the sponsors a target registers under, which is how BPL-003 (Beckley Psytech Limited)
and VTX2735 (Zomagen Biosciences Ltd.) reached the book.

**2. The Phase 3 rows.** Tersolisib was three rows (Tersolisib, STX-478, LY4064809);
two alias rows fold them. EloraTZP is LY900043 with its own two Phase 3s and is an asset
of its own on the CagriSema precedent. The abemaciclib dose arm of ADAPTcycle routes to
Verzenio, and its readout now reads `already_approved`. SPLASH stays unvalued (Part 4).
Of the six Phase 2 rows: bimagrumab is seeded; LY3016859 ISA was already retired by the
discontinued register; gandotinib and amezosvatein are named; LY3537021 was already
settled; LY4515100 is gap 4.

**3. Mazdutide.** Lilly holds the rights outside China (Innovent's 2019 licence is China
only; the February 2026 Innovent collaboration is oncology and immunology). Both Lilly
Phase 2s are complete and in `completed_trials`, which is why the asset had no phase and
no pair, and the FY2025 10-K lists no Phase 2 compound at all, so its absence there is
not a discontinuation. Modelled, not retired, with the probability stated from the gate
model's own chain for a Phase 2 metabolic peptide.

**4. The unattached seed.** `asset_merge.find_code_duplicates` kept the row with more
trials, which was the mass-balance arm `[14C]-LY4515100 IV`, and the seed written to
"LY4515100 via SAD" bound to nothing from 2026-10-29. The programme is named LY4515100
through `programme_names.csv`, the file follows, and the merge now prefers a row named
for the compound (Part B3).

**5. The catalysts.** The seven `no_free_data` rows were already settled; each is
re-checked and dated. The four retatrutide `past_gate` rows are Phase 3b and comorbidity
studies inside the obesity population the seed values and read `in_label`. SPLASH is
recorded. Priced stays at 23: no new source appeared, and that is the finding.

**6. 2026 revenue.** Every anchor re-struck on nine months as filed plus a fourth quarter
at the third quarter's pace; the launch products' growth rates re-solved to their
published peaks; the five lines re-struck on nine months against nine months. Jardiance's
fourth quarter is taken at the third quarter's pace less the $410m milestone Lilly calls
the last. The bridge then reads $92.5bn against $91.0bn to $92.0bn, and the lines explain
it: the model's 2026 is $89.6bn ($77.4bn products, $3.4bn launch run rates, $8.8bn
lines), to which `revenue_split` adds $2.9bn of FY2025 revenue no asset row tags. About
$1.0bn of that is Olumiant, which the model carries as a product at $994m, so it is
counted twice in the bridge; $1.6bn is the launch products' FY2025, which Lilly never
files as full years (the Q4 2025 release tables Mounjaro, Zepbound and Verzenio only) and
which their 2026 run rates already contain; and $1.6bn is the Jardiance rate the book did
not take. Net of those, the model sits at the top of the range. Two defects found on the
way: the Other immunology line carried Olumiant beside the Olumiant model (fixed), and
`company_lines.load_seeds` only ever inserted, so a line re-struck in its file never
reached a built book (fixed, with a test).

**7. The stale note.** Mounjaro said 2041 against 2036, and so did Zepbound (2039),
Taltz (2028 against 2030), Trulicity (2026 against 2027) and Jardiance (none against
2029). All five corrected. Measured across the universe, 98 of 210 horizon notes
disagreed with the engine; the 91 outside Lilly are listed in
`data/loe_note_disagreements.txt` with both years, for reading one by one.

## Part B. What the book now reports itself

- `backend/book_gaps.py`: bought and unvalued (per company, with the acquisition rows
  carrying no terms), late-stage and unmodelled with the engine's reason, stale anchors,
  arm names, and the guidance gap flagged beyond 3% of the midpoint. In the run's health
  detail as a `gaps` block with its own line in the job log, and on `/completeness` as
  `gaps` and `guidance.flagged`. Lilly today: one late-stage (SPLASH), one bought
  (VTX2735), no stale anchor, seven arm-named rows (LY4057996 IV, LY4152199 - IV,
  LY3839056 IV, MER511 (IV), Lispro SC, LY3016859 ISA, AAVAnc80-antiVEGF via Akouos
  Delivery Device). The universe: 49 late-stage unmodelled, 147 acquisition rows with no
  terms, 158 stale anchors, 44 arm-named rows, 5 bought and unvalued.
- `trial_mapping.reads_as_arm`: the derivation prefers a spelling that reads as a
  compound and reports the programmes every spelling of which is an arm; the merge keeps
  the compound-named row.
- `tests/test_seed_notes_loe.py`: a horizon note's year against the engine's, with the
  known list.

## Part 6. In passing, on the three judgements that are not mine

- **Zepbound's ceiling and cliff coincide.** The seed's note carried a 2039 horizon; the
  engine uses the 2036 compound patent, and the $37.68bn ceiling is reached in 2036, the
  year the erosion begins. The re-struck 2026 ($19.8bn) is 53% of the ceiling.
- **Mounjaro's ceiling arithmetic no longer describes the quarters.** The $72bn rests on
  a US share of 48.5% read off the second quarter; the third quarter's release has
  outside-US Mounjaro at $5.7bn of $10.7bn, 53%, up 93% on the year. The re-struck 2026
  ($40.1bn) is 56% of the ceiling.
- **Foundayo** reached $184m in the third quarter and $281m in nine months; the CHMP's
  positive opinion adds the EU, which the US-priced seed does not carry. The growth rate
  re-solved to the $18bn peak by 2030 is 256% a year from the $465m run rate.
- **Tirzepatide's exclusivity** is stated by the engine as 2036 in both brands; the
  Mounjaro and Zepbound notes now say so, and the horizon-note test holds them there.
- **The other-costs charge** of 16.87% is carried verbatim on 40 Lilly files, the six new
  seeds included; a change to it is a 40-file edit.

## Part 7. Pre-existing failures the suite shows on this book

- `test_assumptions.py::test_no_seed_file_is_silently_unloaded`: `sny_brinsupri.csv` and
  `sny_arikayce_kit.csv` resolve to no asset on the 2026-11-27 book, because the Insmed
  products have not yet arrived under Sanofi's name. Not from this work.
- `test_asset_merge.py::test_a_split_model_is_named_in_the_alias_map`: two AstraZeneca
  strays (`Dapagliflozin 10 mg/day (oral)`, `Ticagrelor + Aspirin`) are unnamed on the
  pristine book too. Both are arm names the new rule now reports.

## Sources

Lilly 10-Q for the quarter to 2026-09-30 (0000059478-26-000108), Notes 2 and 4; 10-Q to
2026-06-30 (0000059478-26-000081); 10-Q to 2026-03-31 (0000059478-26-000045); FY2025 10-K
(0000059478-26-000013); FY2024 10-K (0000059478-25-000067); 10-Q to 2025-09-30
(0000059478-25-000254); the results exhibits 0000059478-26-000104, -000077, -000043,
-000008 and 0000059478-25-000251. AtaiBeckley 8-K 0001140361-26-028604; Adverum 8-Ks
0001193125-25-249438 and 0001193125-25-312722; Ventyx 8-K 0001193125-26-006520; Centessa
8-K 0001193125-26-134656; Alkermes 10-Q 0001193125-26-319022. ClinicalTrials.gov API v2,
read 2026-11-27, for every study named. CDC Adult Vaccine Price List of 1 July 2026; CDC
NHIS adult vaccination coverage 2023 and 2024; Census Vintage 2024
nc-est2024-agesex-res.csv. PubMed: Turner et al. 2024 (doi 10.1056/NEJMoa2404625),
Zhdanava et al. 2021 (doi 10.4088/JCP.20m13699), Moein et al. 2024
(doi 10.1007/s00280-024-04690-4), Berdeja et al. 2018 (doi 10.1016/j.leukres.2018.06.014).
Press, where no filing yet states a deal: BioSpace's copy of Lilly's release of
2026-05-26, Business Wire releases of CrossBridge Bio (2026-04-14) and Engage Bio
(2026-05-20), Fierce Biotech on Calytrix (2026-11-16), BioPharma Dive on LoQus23
(2026-11-23).
