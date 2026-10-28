# AMGN: 7 indication layers to research

## Blincyto  (asset_id 417)
- mode **marketed**, revenue anchor 1,559mm USD
- **CMS Part B 2024** (Blincyto): $86,227,273 over 357 beneficiaries = **$241,533 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
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
- **CMS Part B 2024** (Evenity (2 Syringes)): $639,373,585 over 52,146 beneficiaries = **$12,261 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **CMS Part D 2024** (Evenity (2 presentations)): $94,003,185 over 8,293 beneficiaries = **$11,335 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Osteogenesis Imperfecta   [Phase 3, Active not recruiting]
- unit key `459:97`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05972551  Phase 3, Active not recruiting, n=111, primary completion 2027-05-04
    Study to Evaluate Efficacy and Safety of Romosozumab Compared With Bisphosphonates in Children and Adolescents With Osteogenesis Imperfecta

## Otezla  (asset_id 189)
- mode **marketed**, revenue anchor 2,265mm USD
- **CMS Part D 2024** (Otezla): $1,045,029,751 over 31,045 beneficiaries = **$33,662 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
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

## Uplizna  (asset_id 2969)
- mode **marketed**, revenue anchor 655mm USD
- **CMS Part B 2024** (Uplizna): $52,835,926 over 201 beneficiaries = **$262,865 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **CMS Part D 2024** (Uplizna): $15,033,602 over 64 beneficiaries = **$234,900 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
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

