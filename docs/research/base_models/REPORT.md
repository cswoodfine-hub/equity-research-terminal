# Base models for six marketed assets with no model

Worked 2026-11-16. Drafts in this folder; nothing written to `data/` or the database during the research. Checked on scratch copies: `verify_seeds.py` 6 files, 0 failures; `test_seed_cost_stack.py` 5 of 5 pass with the drafts merged; loading the merged folder wrote 108 rows, 0 refused.

| Asset | Revenue anchor and source | Growth | Refused | Engine result (scratch) |
|---|---|---|---|---|
| ABBV Emrelis | 135.0mm, 2026 run rate of AbbVie's "Other Oncology" US line (10-Q 0001551152-26-000037); a line, not the product, so an upper bound | 0.143872, solved to GlobalData's US $287mm in 2036 (Pharmaceutical Technology, July 2024) | NSCLC layer still needs price and stopping rate | NPV 597.7mm |
| ARWR Redemplo | 6.603mm, FY2026 product revenue, net (10-K 0000879407-26-000078) | 0.879146, Q4 run rate (3,102 thousand, from filed totals) x4 against FY2026 | sHTG layer still needs price and stopping rate | NPV 91.8mm, FCS only |
| GILD Livdelzi | 706.0mm, nine months $503mm plus Q4 at Q3's $203mm (10-Q 0000882095-26-000039) | 0.401189, solved to GlobalData's "over $1.7bn in 2030" (Clinical Trials Arena, 2026-11-06) | none; overlap 1.0 confirmed | NPV 788.4mm |
| BMRN Pombiliti | 112.508mm, FY2025 Pombiliti + Opfolda from Amicus's 10-K 0001178879-26-000005 | 0.601743, FY2025 over FY2024; Q3 2026 vs Q3 2025 is +58.2% | price: CMS 2024 has 13 beneficiaries | NPV 362.8mm |
| VRTX Palsonify | 82.42mm, Crinetics H1 $34.344mm plus Q2's $24.038mm twice (10-Q 0001658247-26-000053) | refused: no filing gives a peak for Palsonify alone with a year | revenue_growth_pct, NOT YET VALUABLE | engine refuses, as intended |
| AMGN Inebilizumab | 655mm FY2025 (528 US + 127 RoW), from `amgn_uplizna.csv` with only the brand changed | 0.934351, now stale (2026 runs at 1,499mm, +128.9%) | nothing new | NPV 15,741mm on an engine-made LOE |

## Findings

1. **Vertex's Crinetics acquisition closed on 2026-09-01.** Crinetics 8-K 0001140361-26-035195 (Items 2.01, 3.01, 5.01), then Form 25 and Form 15; Vertex 10-Q 0000875320-26-000291 Note C: $85.00 a share, $10.0bn equity, $9.0bn net of cash and securities. Vertex funded it partly with a $4.5bn term loan, so the 0.05 debt weight in every VRTX seed ("near-zero debt") is stale.
2. **Uplizna is not an asset in the book.** Same molecule as inebilizumab (Amgen 10-K: "UPLIZNA (inebilizumab-cdon)"). Seven data files keyed "Uplizna" match nothing, among them `disclosed_loe.csv` with the 2034-06-11 exclusivity date. Without it the engine treats the product as launched in 2026 and sets LOE 2038, which inflates the NPV. Recommended: restore the Uplizna asset (BLA 761142) so all seven files resolve, or repoint `disclosed_loe.csv` with the seed.
3. **Livdelzi's LOE and ceiling contradict.** The book's LOE is 2027-09-13 from a substance patent; the exclusivities table holds NCE to 2029-08-14 and orphan to 2031. The line reaches 989mm of the 1,700mm ceiling before LOE.
4. **Seeds are no longer insert-only**, though file headers say so: the reconcile pass corrects or retracts seed-owned rows, and loading a partial seed folder retracts rows. Never point `load_seeds` at a partial folder.
5. Emrelis is anchored on a reported line, not the product. Arrowhead's cost stack is Novartis's, as a comparator. Pombiliti carries the Pombiliti + Opfolda line, so Opfolda (asset 3434) must never carry revenue of its own. `lly_jaypirca.csv`, the asset-model template, loads nowhere.

## Notes per asset

- **Emrelis.** AbbVie's "Other Oncology" US line was nil in 2023 and 2024 and starts the quarter Emrelis was approved: Q2 2025 $2mm, Q3 $11mm, Q4 $20mm, Q1 2026 $24mm, Q2 $33mm, Q3 $39mm. The ceiling predates approval and is US only.
- **Redemplo.** The value is in the sHTG expansion (sNDA in the FDA's STAR pilot, US launch "in the second quarter of 2027"), which the pool file's Hypertriglyceridemia layer carries once it has a price and a stopping rate.
- **Livdelzi.** The only pending catalyst (1289) is ASSURE (NCT03301506), long-term open label inside the label. IDEAL (NCT06060665) enrolled ALP 1.0 to 1.67x ULN; the label sets no ALP threshold, so it is evidence inside the label.
- **Pombiliti.** Close confirmed: BioMarin 8-K 0001193125-26-179243 (Items 1.01 and 2.01), Amicus 8-K 0001140361-26-016968.
- **Palsonify.** Vertex guides "$40 million to $50 million" for September to December. Vertex's "~$5B+" peak covers Palsonify and atumelnant combined. Unusable leads: S&P Global MI (October 2025, "USD1 billion ... by 2034", page returned 403) and a second-hand Goldman $600mm peak with no year.

## Web sources

- https://www.clinicaltrialsarena.com/news/gilead-livdelzi-phase-iii-ideal-pbc-liver-disease-alp/
- https://www.pharmaceutical-technology.com/data-insights/telisotuzumab-vedotin-abbvie-net-present-value
