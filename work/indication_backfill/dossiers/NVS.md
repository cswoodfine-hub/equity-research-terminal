# NVS: 16 indication layers to research

## Cosentyx  (asset_id 605)
- mode **marketed**, revenue anchor 6,668mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Polymyalgia Rheumatica   [Phase 3, Active not recruiting]
- unit key `605:225`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT06331312  Phase 3, Active not recruiting, n=162, primary completion 2028-05-08
    Open-label, Long-term Safety Study of Secukinumab in Polymyalgia Rheumatica (PMR)
- **pending catalyst** 2028-05-08 (data readout): Phase 3, Cosentyx

## Fabhalta  (asset_id 57)
- mode **marketed**, revenue anchor 505mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Atypical Hemolytic Uremic Syndrome   [Phase 3, Recruiting]
- unit key `57:226`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05935215  Phase 3, Recruiting, n=50, primary completion 2028-07-21
    Efficacy and Safety of Switching From Anti-C5 Antibody Treatment to Iptacopan Treatment in Study Participants With Atypical Hemolytic Uremic Syndrome 
- trial NCT05795140  Phase 3, Recruiting, n=65, primary completion 2032-07-16
    Evaluate Long-term Safety, Tolerability and Efficacy of Iptacopan in Study Participants With aHUS
- **pending catalyst** 2028-07-21 (data readout): Phase 3, Fabhalta

### Myasthenia Gravis   [Phase 3, Active not recruiting]
- unit key `57:93`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 82,715 patients per year
      source: convention: the pool is stated equal to the prevalence and read as the patients eligible to start each year
    - `prevalence` = 82,715 patients
      source: 'approximately 82,715 US adults living with MG in 2021' (Ye Y et al., Front Neurol 2024;15:1339167, DOI 10.3389/fneur.2024.1339167)
- trial NCT06517758  Phase 3, Active not recruiting, n=146, primary completion 2027-04-30
    A Phase III Study to Investigate Efficacy, Safety and Tolerability of Iptacopan Compared With Placebo in Participants Aged 18 to 85 Years With gMG.
- **pending catalyst** 2027-04-30 (data readout): Phase 3, Fabhalta

### Anti-Neutrophil Cytoplasmic Antibody-Associated Vasculitis   [Phase 2, Active not recruiting]
- unit key `57:426`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT06388941  Phase 2, Active not recruiting, n=84, primary completion 2026-12-30
    Iptacopan in Patients With ANCA Associated Vasculitis

### Glomerulonephritis, IGA   [Phase 3, Recruiting]
- unit key `57:212`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 6,973 patients a year
      source: DeCongelio M et al., Clin Nephrol 2025: 2.1 new IgAN diagnoses per 100,000 a year (Komodo Health), applied to the same 332,031,554
    - `prevalence` = 198,887 patients
      source: DeCongelio M et al., Clin Nephrol 2025;103(1):19-25 (doi:10.5414/CN111489): IgAN biopsy rates extrapolated to Komodo Health claims give 59.9 per 100,000, which on the 2021 US population of 332,031,554 is 198,887 people; Oracle claims give 208,184
- trial NCT06797518  Phase 2, Recruiting, n=20, primary completion 2027-11-27
    Study to Evaluate the Impact of Iptacopan on Top of SOC on Biopsy Changes in Kidneys of Adult Patients With IgAN
- trial NCT06994845  Phase 3, Recruiting, n=31, primary completion 2030-06-28
    Study to Assess the Efficacy, Pharmacokinetics, Safety and Tolerability of Iptacopan in Pediatric Patients With Primary IgAN
- trial NCT04557462  Phase 3, Recruiting, n=540, primary completion 2030-12-04
    A Rollover Extension Program (REP) to Evaluate the Long-term Safety and Tolerability of Open Label Iptacopan/LNP023 in Participants With Primary IgA N

### Glomerulonephritis, Membranoproliferative   [Phase 3, Recruiting]
- unit key `57:219`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05795140  Phase 3, Recruiting, n=65, primary completion 2032-07-16
    Evaluate Long-term Safety, Tolerability and Efficacy of Iptacopan in Study Participants With aHUS
- trial NCT03955445  Phase 3, Recruiting, n=225, primary completion 2036-05-30
    Long-term Efficacy, Safety and Tolerability of Iptacopan in C3G or IC-MPGN

### Lupus Erythematosus, Systemic   [Phase 2, Recruiting]
- unit key `57:411`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 14,263 patients a year
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic', the same CDC registries row
    - `prevalence` = 204,295 patients
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic': CDC national lupus registries programme, the five state registries, age-standardised to the US population
- trial NCT05268289  Phase 2, Recruiting, n=240, primary completion 2026-03-19
    Study of Efficacy and Safety of LNP023 in Participants With Active Lupus Nephritis Class III-IV, +/- V

### Lupus Nephritis   [Phase 2, Recruiting]
- unit key `57:120`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05268289  Phase 2, Recruiting, n=240, primary completion 2026-03-19
    Study of Efficacy and Safety of LNP023 in Participants With Active Lupus Nephritis Class III-IV, +/- V

### Macular Degeneration   [Phase 2, Active not recruiting]
- unit key `57:432`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05230537  Phase 2, Active not recruiting, n=168, primary completion 2026-09-30
    A Masked, Placebo-controlled Study to Assess Iptacopan in Age-related Macular Degeneration

### Wet Macular Degeneration   [Phase 2, Active not recruiting]
- unit key `57:107`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 24,664 patients a year
      source: the net growth of the pool, not new diagnoses: wet AMD prevalence held at 1.2% to 1.3% of enrollees aged 65 and over through 2018 to 2021 (Saundankar 2025), so the prevalent pool grows with that population, which rose 3.1% from 2023 to 2024 (Census Bureau, Vintage 2024). 3.1% of 795,600 is 24,664
    - `prevalence` = 795,600 patients
      source: Saundankar V et al., J Manag Care Spec Pharm 2025;31(1):88-94 (Medicare Advantage claims, 2.9 million enrollees aged 65 and over): an annual wet AMD prevalence of 1.3% in 2021, applied to the 61.2 million Americans aged 65 and over in the Census Bureau's Vintage 2024 estimates (press release of 26 June 2025)
- trial NCT05230537  Phase 2, Active not recruiting, n=168, primary completion 2026-09-30
    A Masked, Placebo-controlled Study to Assess Iptacopan in Age-related Macular Degeneration

## Kisqali  (asset_id 263)
- mode **marketed**, revenue anchor 4,783mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Breast Neoplasms, Male   [Phase 3, Active not recruiting]
- unit key `263:587`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05827081  Phase 3, Active not recruiting, n=1464, primary completion 2029-09-07
    Phase IIIb Study of Ribociclib + ET in Early Breast Cancer

## Kymriah  (asset_id 358)
- mode **marketed**, revenue anchor 381mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Burkitt Lymphoma   [Phase 3, Recruiting]
- unit key `358:198`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT04094311  Phase 3, Recruiting, n=200, primary completion 2027-03-31
    Study of Out of Specification for Tisagenlecleucel
- trial NCT03876769  Phase 2, Active not recruiting, n=121, primary completion 2027-10-19
    Study of Efficacy and Safety of Tisagenlecleucel in HR B-ALL EOC MRD Positive Patients

## Leqvio  (asset_id 160)
- mode **marketed**, revenue anchor 1,198mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Cardiovascular Diseases   [Phase 3, Active not recruiting]
- unit key `160:379`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 849,539 patients per year
      source: congenital, so the inflow is demographic rather than clinical: 4,247,694 US births registered in 2008 (CDC NCHS, Births: Final Data for 2008), the cohort turning 18 in 2026, times the 20% carrying elevated Lp(a)
    - `prevalence` = 53,395,654 patients
      source: NHLBI 2024: roughly 1 in 5 adults carry Lp(a) above 50 mg/dL, applied to the US resident population 18+, 266,978,268, Census SCPRC-EST2024-18+POP, 1 Jul 2024
- trial NCT05360446  Phase 3, Active not recruiting, n=610, primary completion 2026-10-26
    Coronary Computed Tomography Study to Assess the Effect of Inclisiran in Addition to Maximally Tolerated Statin Therapy on Atherosclerotic Plaque Prog
- trial NCT07102628  Phase 3, Recruiting, n=300, primary completion 2027-02-11
    Evaluation of Efficacy and Safety of Early in Hospital Initiation of Inclisiran Treatment in Patients With Acute Coronary Syndromes
- trial NCT07684469  Phase 4, Not yet recruiting, n=300, primary completion 2027-02-28
    Comparative Assessment of Inclisiran on Top of Standard of Care Versus Standard of Care Alone for LDL-C Evaluation in Acute Coronary Syndrome Patients
- trial NCT06941792  Phase 4, Active not recruiting, n=1590, primary completion 2027-04-30
    Inclisiran Effectiveness in China: a Pragmatic Randomized Trial
- trial NCT05030428  Phase 3, Active not recruiting, n=17004, primary completion 2027-05-10
    Study of Inclisiran to Prevent Cardiovascular (CV) Events in Participants With Established Cardiovascular Disease
- trial NCT06597019  Phase 3, Recruiting, n=60, primary completion 2028-03-21
    Study to Evaluate Efficacy and Safety of Inclisiran in Children With Heterozygous Familial Hypercholesterolemia
- **pending catalyst** 2027-05-10 (data readout): Phase 3, Leqvio

### Coronary Artery Disease   [Phase 3, Active not recruiting]
- unit key `160:211`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 1,135,700 patients a year
      source: equal to Lipfendra's row on the same pool: 605,000 first heart attacks a year (CDC Heart Disease Facts) plus 87% of 610,000 first strokes (CDC Stroke Facts: 'About 610,000 of these are first or new strokes'; 'About 87% of all strokes are ischemic strokes'): 605,000 + 530,700 = 1,135,700
    - `prevalence` = 23,761,066 patients
      source: the ASCVD pool the book's cardiovascular seeds carry (Lipfendra and AZD0780 on Hypercholesterolemia): 8.9% of US adults with clinical ASCVD (American Heart Association 2025 statistics) x 266,978,268 residents aged 18 and over (Census Vintage 2024, nc-est2024-agesex-res, POPESTIMATE2024 summed from age 18) = 23,761,066. data/epidemiology.csv has no Atherosclerosis row
- trial NCT05360446  Phase 3, Active not recruiting, n=610, primary completion 2026-10-26
    Coronary Computed Tomography Study to Assess the Effect of Inclisiran in Addition to Maximally Tolerated Statin Therapy on Atherosclerotic Plaque Prog
- trial NCT05739383  Phase 3, Active not recruiting, n=14012, primary completion 2029-04-16
    A Study of Inclisiran to Prevent Cardiovascular Events in High-risk Primary Prevention Patients.
- **pending catalyst** 2026-10-26 (data readout): Phase 3, Leqvio

## Sandostatin  (asset_id 639)
- mode **marketed**, revenue anchor 1,213mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Gastro-enteropancreatic neuroendocrine tumor   [Phase 3, Recruiting]
- unit key `639:247`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT06784752  Phase 3, Recruiting, n=240, primary completion 2028-12-08
    Study to Evaluate the Efficacy and Safety of [177Lu]Lu-DOTA-TATE in Patients With Grade 1 and Grade 2 Advanced GEP-NET

## Zolgensma  (asset_id 361)
- mode **marketed**, revenue anchor 1,232mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Bulbo-Spinal Atrophy, X-Linked   [Phase 3, Active not recruiting]
- unit key `361:222`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05335876  Phase 3, Active not recruiting, n=20, primary completion 2031-04-29
    Long-term Follow-up of Patients With Spinal Muscular Atrophy Treated With OAV101 in Clinical Trials

