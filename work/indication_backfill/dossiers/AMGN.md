# AMGN: 9 indication layers to research

## Blincyto  (asset_id 417)
- mode **marketed**, revenue anchor 1,559mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Precursor Cell Lymphoblastic Leukemia-Lymphoma   [Phase 3, Active not recruiting]
- unit key `417:430`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT04521231  Phase 1/2, Active not recruiting, n=181, primary completion 2027-11-24
    A Study of Subcutaneous Blinatumomab Administration in Participants With R/R and MRD+ B-ALL
- trial NCT07223190  Phase 3, Not yet recruiting, n=560, primary completion 2031-12-30
    A Study Evaluating Subcutaneous Versus Intravenous Blinatumomab in Newly Diagnosed Adults With B-cell Precursor Acute Lymphoblastic Leukaemia

## Evenity  (asset_id 459)
- mode **marketed**, revenue anchor 2,100mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Osteogenesis Imperfecta   [Phase 3, Active not recruiting]
- unit key `459:97`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05972551  Phase 3, Active not recruiting, n=111, primary completion 2027-05-04
    Study to Evaluate Efficacy and Safety of Romosozumab Compared With Bisphosphonates in Children and Adolescents With Osteogenesis Imperfecta

## Imdelltra  (asset_id 452)
- mode **marketed**, revenue anchor 627mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Small Cell Lung Carcinoma   [Phase 3, Recruiting]
- unit key `452:70`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 226,650 patients a year
      source: lung cancer incidence is the pool: diagnosed and treated each year rather than accumulated
    - `prevalence` = 226,650 patients
      source: 226,650 new US lung cancers in 2025 (SEER), the base the volrustomig and sacituzumab tirumotecan seeds build their lung pools on
- trial NCT05740566  Phase 3, Active not recruiting, n=509, primary completion 2025-01-29
    Study Comparing Tarlatamab With Standard of Care Chemotherapy in Relapsed Small Cell Lung Cancer
- trial NCT03319940  Phase 1, Active not recruiting, n=269, primary completion 2026-12-31
    Study Evaluating Safety, Tolerability and Pharmacokinetics (PK) of Tarlatamab in Adults With Small Cell Lung Cancer (SCLC)
- trial NCT06598306  Phase 1, Recruiting, n=220, primary completion 2027-04-24
    Subcutaneous Tarlatamab in Participants With Extensive Stage Small Cell Lung Cancer (DeLLphi-308)
- trial NCT06211036  Phase 3, Active not recruiting, n=563, primary completion 2027-07-05
    Study Comparing Tarlatamab and Durvalumab Versus Durvalumab Alone in First-Line Extensive-Stage Small-Cell Lung Cancer (ES-SCLC) Following Platinum, E
- trial NCT07778316  Phase 3, Recruiting, n=400, primary completion 2027-09-24
    Phase 3 Trial of Tarlatamab (SC vs IV) in Extensive-Stage Small Cell Lung Cancer After Platinum Based First-line Chemotherapy (ES-SCLC)
- trial NCT05060016  Phase 2, Active not recruiting, n=222, primary completion 2027-12-30
    A Phase 2 Study of Tarlatamab in Patients With Small Cell Lung Cancer (SCLC)
- **pending catalyst** 2027-07-05 (data readout): Phase 3, Imdelltra
- **pending catalyst** 2027-12-30 (data readout): Phase 2, Imdelltra
- **pending catalyst** 2027-09-24 (data readout): Phase 3, Imdelltra

## Otezla  (asset_id 189)
- mode **marketed**, revenue anchor 2,265mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Arthritis, Juvenile   [Phase 3, Recruiting]
- unit key `189:43`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 1,300 patients a year
      source: JIA incidence 11.9 per 100,000 in the same cohort, 8,660 a year, at the same 15% for the two categories
    - `prevalence` = 4,900 patients
      source: JIA at 44.7 per 100,000 US children (managed-care cohort, PMC5657479) against 72.8 million under 18 is 32,500 with JIA; enthesitis-related arthritis is 5% to 10% of JIA and juvenile psoriatic arthritis 2% to 15% (StatPearls NBK554605), so the two categories COSPIRIT-JIA enrolled are taken at 15% of JIA together
- trial NCT04804553  Phase 3, Recruiting, n=60, primary completion 2028-03-21
    Apremilast Pediatric Study in Children With Active Juvenile Psoriatic Arthritis
- trial NCT05767047  Phase 3, Recruiting, n=48, primary completion 2036-03-17
    A Study of Apremilast in Children With Oral Ulcers Associated With Behçet's Disease or Juvenile Psoriatic Arthritis
- **pending catalyst** 2028-03-21 (data readout): Phase 3, Otezla

### Behcet Syndrome   [Phase 3, Recruiting]
- unit key `189:582`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT04528082  Phase 3, Recruiting, n=60, primary completion 2030-02-07
    Apremilast Pediatric Study in Children With Active Oral Ulcers Associated With Behçet's Disease
- trial NCT05767047  Phase 3, Recruiting, n=48, primary completion 2036-03-17
    A Study of Apremilast in Children With Oral Ulcers Associated With Behçet's Disease or Juvenile Psoriatic Arthritis

## Uplizna  (asset_id 2969)
- mode **marketed**, revenue anchor 655mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Arthritis, Rheumatoid   [Phase 2, Recruiting]
- unit key `2969:383`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 1,456,723 patients a year
      source: stated equal to the data/epidemiology.csv prevalence (Hunter TM et al., Rheumatology International 2017, 1,456,723), which sets the engine's carryover to zero: each year's eligible pool is the whole ACPA-positive population and the penetration is the share of it started that year. The convention azn_tozorakimab.csv uses for COPD
- trial NCT06570798  Phase 2, Recruiting, n=220, primary completion 2028-08-06
    A Phase 2 Master Protocol Assessing Inebilizumab and Blinatumomab in Autoimmune Diseases

### Glomerulonephritis, Membranous   [Phase 3, Recruiting]
- unit key `2969:574`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07851220  Phase 3, Recruiting, n=159, primary completion 2031-09-27
    A Phase 3 Study of Inebilizumab in Participants With Primary Membranous Nephropathy

### Hepatitis, Autoimmune   [Phase 3, Recruiting]
- unit key `2969:98`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07598825  Phase 3, Recruiting, n=180, primary completion 2031-07-30
    A Trial of Inebilizumab in Participants With Autoimmune Hepatitis

### Lupus Erythematosus, Systemic   [Phase 2, Recruiting]
- unit key `2969:411`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 14,263 patients a year
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic', the same CDC registries row
    - `prevalence` = 204,295 patients
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic': CDC national lupus registries programme, the five state registries, age-standardised to the US population
- trial NCT06570798  Phase 2, Recruiting, n=220, primary completion 2028-08-06
    A Phase 2 Master Protocol Assessing Inebilizumab and Blinatumomab in Autoimmune Diseases

