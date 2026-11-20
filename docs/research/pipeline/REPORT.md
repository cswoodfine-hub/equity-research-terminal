# Six catalysts on assets with no base model: identity first, then the model

Worked 2026-11-16. Every number below is cited to a named, dated, free source. Nothing was written to `backend/er_tool.db` or `data/` during the research: database reads used read-only connections, and the one test build ran on a scratch copy.

| File | What it is | Applies to |
|---|---|---|
| `mrna_mrna_1982_model_rows.csv` | 23 model rows for `data/assumptions/mrna_mrna_1982.csv` | MRNA mRNA-1982 |
| `programme_names_rows.csv` | 2 rename rows for `data/programme_names.csv` | LLY LY3305677, RGNX RGX-121-3102 |
| `trial_asset_map_rows.csv` | 1 pin for `data/trial_asset_map.csv` | LLY master protocol NCT06143956 |
| `asset_alias_map_fix.csv` | 1 corrected row for `data/asset_alias_map.csv` | PCVX infant arm label |
| `discontinued_programmes_candidate.csv` | 1 candidate row, with a rule caveat | SGMOQ ST-503 |

## Verdicts

| Asset | Identity | Outcome | Reason |
|---|---|---|---|
| LLY LY3305677 | Mazdutide (NCT06124807 lists "Mazdutide", other name "LY3305677") | Model refused; rename; repoint the catalyst | Obesity readout already out (NCT06124807, completed 2025-01-22, results posted 2026-04-21). The 2027-09 date is the macupatide and eloralintide appendix (NCT07589608), already catalyst 784 on Macupatide. No Phase 3 to date a launch from |
| MRNA mRNA-1982 | Moderna's monovalent OspA Lyme mRNA vaccine | Model drafted | Active Phase 2 (NCT07561294), wholly Moderna's |
| RGNX RGX-121-3102 | RGX-121 (clemidsogene lanparvovec) under the protocol number of NCT07236606; the book's only RGX-121 row (asset 3052) | Model refused; rename to the INN | Clinical hold since 2026-08-24; company "does not expect to resubmit the RGX-121 Biologics License Application ('BLA') in the near term" (8-K 0001193125-26-363786); Nippon Shinyaku holds US rights for a royalty |
| SGMOQ ST-503 | A real Sangamo programme | Retire candidate (rule caveat) | Chapter 11 (Case 26-10989, D. Del.); ST-503 drew no bid at the 2026-08-10 auction; NCT06980948 suspended "while Sangamo seeks a new sponsor" |
| PFE "Vaccine Candidate #1" | Arm A of six unnamed Pfizer mRNA flu candidates in C6481001 (NCT07431853) | Refused, no repoint target | No source joins the study to PF-07252220, and the book holds no such asset |
| PCVX "0.5 mL of the low dose V..." | Registry arm label for VAX-31 (NCT06720038) | Repoint by fixing the alias | Alias row says "31 valent"; the asset and seed say "31-valent"; the loader needs an exact match |

## mRNA-1982 model, as verified on a database copy

load_seeds wrote 23 rows, refused 0. asset_forecast is ok with nothing missing: revenue $14.9mm in 2034 rising to $425.9mm in 2039; NPV $585.6mm unrisked, $133.7mm risked at a 9.11% WACC; catalyst 1576 priced at $133.7mm now, $348.1mm on success, nil on failure.

Key choices: chronic mode with discontinuation 1.0 (the RGX-202 method, so cost of sales is charged); list price per course from `pfe_vla15.csv` (four doses at TicoVac's CMS Part D 2024 $298.05) with its gross-to-net 0.5; forecast_start_year 2034, labelled JUDGEMENT from VLA15's own registry intervals; pos 0.22831 from BIO/Informa/QLS 2011-2020 infectious disease (0.384 x 0.640 x 0.929); exus_multiple 0.0 because Moderna's FY2025 10-K gives Europe to mRNA-1975; company keys copied from `mrna_mrna_1403.csv`.

## Findings passed on

1. `data/pipeline_sort.csv` says Lilly has no mazdutide trial outside China since January 2025; NCT06817356 (US Phase 2, alcohol use disorder) completed 2026-03-19. Mazdutide is absent from the FY2025 10-K (0000059478-26-000013); silence is not a discontinuation.
2. `programme_alias.load_curated` skips an unmatched alias without saying so.
3. 13 seeds run `therapy_mode` one_time with no `cogs_per_patient`, so `forecast.py` ignores `cogs_pct` and charges no cost of goods (mRNA-1403, mRNA-1018-H5, GSK mRNA flu, Sanofi PCV21, Menquadfi, Fluzone, MK-6916, bepirovirsen among them).
4. Sangamo's ST-506 went to Lilly (closed 2026-09-04, 8-K 0001104659-26-105905) and ST-920 to PTC (closed 2026-09-17, 8-K 0001193125-26-396644); both still sit under SGMOQ.
5. The RGX-121 note in `data/pipeline_sort.csv` says the company plans to resubmit; the 2026-08-24 8-K says not in the near term.
6. `assumptions.load_seeds` matches a seed's brand against brand_name or generic_name only, so a rename must ship with a re-key of the seed file.
7. The book has no row for Pfizer's PF-07252220 (mRNA flu, adults, Phase 2, Pfizer pipeline 2026-11-03).

## Sources and limits

ClinicalTrials.gov API v2 (read 2026-11-16); SEC EDGAR filings and full-text search; PubMed (Ji L et al., EClinicalMedicine 2022;54:101691, PMID 36247927, for the mazdutide code); Pfizer's Q3 2026 pipeline PDF. Not verified: the China NMPA approval of mazdutide that `data/pipeline_sort.csv` cites to Wikipedia.
