# ABBV: 13 indication layers to research

## Ozurdex  (asset_id 942)
- mode **marketed**, revenue anchor 493mm USD
- **CMS Part B 2024** (Ozurdex): $47,962,972 over 15,038 beneficiaries = **$3,189 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **CMS Part D 2024** (Ozurdex): $1,873,498 over 622 beneficiaries = **$3,012 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Multiple Myeloma   [Phase 3, Recruiting]
- unit key `942:101`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 36,000 patients a year
      source: SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026. Prevalence equals incidence here by this book's oncology convention: a line of therapy treats the year's diagnoses rather than an accumulating pool, so a patient not started this year has started something else and left the line
    - `prevalence` = 36,000 patients
      source: SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026. Prevalence equals incidence here by this book's oncology convention: a line of therapy treats the year's diagnoses rather than an accumulating pool, so a patient not started this year has started something else and left the line
- trial NCT03539744  Phase 3, Active not recruiting, n=265, primary completion 2026-08
    A Study Designed to Evaluate the Safety and Efficacy of Venetoclax Plus Dexamethasone (VenDex) Compared With Pomalidomide Plus Dexamethasone (PomDex) 
- trial NCT06953960  Phase 1/2, Recruiting, n=325, primary completion 2030-12
    A Study to Assess Adverse Events and Change in Disease Activity of Oral Surzetoclax Alone or in Combination With Subcutaneous and/or Oral Antimyeloma 
- trial NCT03314181  Phase 2, Active not recruiting, n=156, primary completion 2031-05
    A Study of Combination Therapy With Venetoclax, Daratumumab and Dexamethasone (With and Without Bortezomib) in Participants With Relapsed or Refractor

## Qulipta  (asset_id 296)
- mode **marketed**, revenue anchor 1,036mm USD
- **CMS Part D 2024** (Qulipta): $260,307,144 over 45,046 beneficiaries = **$5,779 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Migraine Disorders   [Phase 3, Recruiting]
- unit key `296:96`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 0 patients a year
      source: stated at nil: no free US migraine incidence count, and the uptake anchor below measures its capture on an untreated pool that shrinks by starts alone, with no inflow, so the forecast pool is drawn the same way
    - `prevalence` = 31,236,457 patients
      source: Lipton RB et al., Neurology 2007;68(5):343-349 (PMID 17261680), the American Migraine Prevalence and Prevention study: a 1-year migraine prevalence of 11.7% among 162,576 respondents aged 12 or older (ICHD-2 criteria), applied to the 266,978,268 US residents aged 18 and over (Census SCPRC-EST2024-18+POP at 1 July 2024, the adult denominator data/epidemiology.csv carries for Obesity). 0.117 x 266,978,268 = 31,236,457
- trial NCT06241313  Phase 3, Active not recruiting, n=1300, primary completion 2025-07-07
    Study of Oral Atogepant Tablets to Assess Safety and Efficacy in Adult Participants With Migraine
- trial NCT06810505  Phase 3, Recruiting, n=420, primary completion 2031-03
    A Study of Oral Atogepant Tablets to Assess Adverse Events and Change in Disease Activity To Prevent Migraine in Participants Aged 12 to 17 Years

## Rinvoq  (asset_id 191)
- mode **marketed**, revenue anchor 8,304mm USD
- **CMS Part D 2024** (Rinvoq): $1,385,459,851 over 29,062 beneficiaries = **$47,673 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Hidradenitis Suppurativa   [Phase 3, Active not recruiting]
- unit key `191:56`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 37,785 patients a year
      source: Garg A et al., Journal of the American Academy of Dermatology 2017;77(1):118-122: a one-year HS incidence of 11.4 per 100,000, applied to the 2020 census population of 331,449,281
    - `prevalence` = 324,820 patients
      source: Garg A et al., JAMA Dermatology 2017;153(8):760-764 (EHR data on more than 48 million US patients): a standardised HS prevalence of 98 per 100,000, applied to the 2020 census population of 331,449,281
- trial NCT05889182  Phase 3, Active not recruiting, n=1328, primary completion 2028-03
    A Study to Assess Change in Disease Activity and Adverse Events of Oral Upadacitinib in Adult and Adolescent Participants With Moderate to Severe Hidr
- **pending catalyst** 2028-03 (data readout): Phase 3, Rinvoq

### Lupus Erythematosus, Systemic   [Phase 3, Active not recruiting]
- unit key `191:411`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 14,263 patients a year
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic', the same CDC registries row
    - `prevalence` = 204,295 patients
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic': CDC national lupus registries programme, the five state registries, age-standardised to the US population
- trial NCT05843643  Phase 3, Active not recruiting, n=1014, primary completion 2027-03
    Program to Assess Adverse Events and Change in Disease Activity of Oral Upadacitinib in Adult Participants With Moderate to Severe Systemic Lupus Eryt
- **pending catalyst** 2027-03 (data readout): Phase 3, Rinvoq

### Takayasu Arteritis   [Phase 3, Active not recruiting]
- unit key `191:105`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT04161898  Phase 3, Active not recruiting, n=56, primary completion 2028-08
    A Study to Evaluate the Efficacy and Safety of Upadacitinib in Participants With Takayasu Arteritis (TAK)
- **pending catalyst** 2028-08 (data readout): Phase 3, Rinvoq

### Vitiligo   [Phase 3, Active not recruiting]
- unit key `191:72`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 48,532 patients a year
      source: Mastacouris N et al., JAMA Dermatol 2023 (doi:10.1001/jamadermatol.2023.2162; Explorys EHR, 2015 to 2019): age- and sex-adjusted incidence of diagnosed vitiligo 22.6 per 100,000 person-years, x 266,978,268 adults = 60,337, x 80.4% non-segmental (Gandhi 2022: 0.37% of the 0.46% with clinician-adjudicated diagnosed vitiligo) = 48,532
    - `prevalence` = 987,820 patients
      source: Gandhi K et al., JAMA Dermatol 2022;158(1):43-50 (doi:10.1001/jamadermatol.2021.4724; 40,888 US adults, survey with dermatologist adjudication of photographs): clinician-adjudicated diagnosed non-segmental vitiligo 0.37% of adults (sensitivity bounds 0.37% to 0.49%), applied to the 266,978,268 US residents aged 18 and over at 1 July 2024 (Census nc-est2024-agesex-res)
- trial NCT06118411  Phase 3, Active not recruiting, n=614, primary completion 2028-03
    A Study To Assess Adverse Events and Effectiveness of Upadacitinib Oral Tablets in Adult and Adolescent Participants With Vitiligo
- **pending catalyst** 2028-03 (data readout): Phase 3, Rinvoq

### Alopecia Areata   [Phase 3, Recruiting]
- unit key `191:73`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07023302  Phase 3, Active not recruiting, n=125, primary completion 2029-02
    A Study to Evaluate the Safety and Effectiveness of Upadacitinib Tablets in Adult and Adolescent Participants in Japan With Alopecia Areata
- trial NCT06012240  Phase 3, Recruiting, n=1500, primary completion 2030-04
    A Study to Evaluate the Safety and Effectiveness of Upadacitinib Tablets in Adult and Adolescent Participants With Severe Alopecia Areata
- trial NCT07772492  Phase 3, Recruiting, n=300, primary completion 2032-03
    A Study to Evaluate the Safety and Effectiveness of Upadacitinib in Pediatric Participants With Alopecia Areata

## Ubrelvy  (asset_id 324)
- mode **marketed**, revenue anchor 1,271mm USD
- **CMS Part D 2024** (Ubrelvy): $429,537,898 over 83,437 beneficiaries = **$5,148 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Migraine Disorders   [Phase 3, Recruiting]
- unit key `324:96`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 0 patients a year
      source: stated at nil: no free US migraine incidence count, and the uptake anchor below measures its capture on an untreated pool that shrinks by starts alone, with no inflow, so the forecast pool is drawn the same way
    - `prevalence` = 31,236,457 patients
      source: Lipton RB et al., Neurology 2007;68(5):343-349 (PMID 17261680), the American Migraine Prevalence and Prevention study: a 1-year migraine prevalence of 11.7% among 162,576 respondents aged 12 or older (ICHD-2 criteria), applied to the 266,978,268 US residents aged 18 and over (Census SCPRC-EST2024-18+POP at 1 July 2024, the adult denominator data/epidemiology.csv carries for Obesity). 0.117 x 266,978,268 = 31,236,457
- trial NCT05125302  Phase 3, Recruiting, n=1059, primary completion 2027-05
    Study to Assess Adverse Events and Disease Activity of Oral Ubrogepant Tablets for the Acute Treatment of Migraine in Children and Adolescents (Ages 6
- trial NCT06417775  Phase 3, Active not recruiting, n=496, primary completion 2027-11
    Study of Oral Ubrogepant to Assess Adverse Events and Change in Disease Activity in Adult Participants With Menstrual Migraine
- trial NCT05127954  Phase 3, Enrolling by invitation, n=1200, primary completion 2028-01
    Long-term Extension Study to Assess Safety and Tolerability of Oral Ubrogepant Tablets for the Acute Treatment of Migraine in Pediatric Participants (
- **pending catalyst** 2027-11 (data readout): Phase 3, Ubrelvy

## Venclexta  (asset_id 329)
- mode **marketed**, revenue anchor 2,792mm USD
- **CMS Part D 2024** (Venclexta): $941,720,713 over 21,868 beneficiaries = **$43,064 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Myelodysplastic Syndromes   [Phase 3, Active not recruiting]
- unit key `329:409`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02942290  Phase 1, Active not recruiting, n=129, primary completion 2027-01
    A Study Evaluating Venetoclax in Combination With Azacitidine in Participants With Treatment-Naïve Higher-Risk Myelodysplastic Syndromes (MDS)
- trial NCT04401748  Phase 3, Active not recruiting, n=531, primary completion 2027-07
    Study Of Venetoclax Tablet With Intravenous or Subcutaneous Azacitidine to Assess Change in Disease Activity In Adult Participants With Newly Diagnose
- **pending catalyst** 2027-07 (data readout): Phase 3, Venclexta

### Lymphoma, B-Cell, Marginal Zone   [Phase 2, Active not recruiting]
- unit key `329:57`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07387471  Phase 2, Active not recruiting, n=14, primary completion 2028-07
    Study to Assess Change in Disease Activity of Oral Venetoclax in Adult Participants With Recurring Relapsed or Refractory (R/R) Waldenström Macroglobu

### Multiple Myeloma   [Phase 3, Active not recruiting]
- unit key `329:101`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 36,000 patients a year
      source: SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026. Prevalence equals incidence here by this book's oncology convention: a line of therapy treats the year's diagnoses rather than an accumulating pool, so a patient not started this year has started something else and left the line
    - `prevalence` = 36,000 patients
      source: SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026. Prevalence equals incidence here by this book's oncology convention: a line of therapy treats the year's diagnoses rather than an accumulating pool, so a patient not started this year has started something else and left the line
- trial NCT02899052  Phase 2, Active not recruiting, n=120, primary completion 2027-06
    Study of Venetoclax in Combination With Carfilzomib and Dexamethasone in Participants With Relapsed or Refractory Multiple Myeloma (MM)
- trial NCT03844048  Phase 3, Active not recruiting, n=165, primary completion 2027-08
    An Extension Study of Venetoclax for Subjects Who Have Completed a Prior Venetoclax Clinical Trial

### Precursor Cell Lymphoblastic Leukemia-Lymphoma   [Phase 3, Active not recruiting]
- unit key `329:430`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT03844048  Phase 3, Active not recruiting, n=165, primary completion 2027-08
    An Extension Study of Venetoclax for Subjects Who Have Completed a Prior Venetoclax Clinical Trial

### Waldenstrom Macroglobulinemia   [Phase 2, Active not recruiting]
- unit key `329:58`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07387471  Phase 2, Active not recruiting, n=14, primary completion 2028-07
    Study to Assess Change in Disease Activity of Oral Venetoclax in Adult Participants With Recurring Relapsed or Refractory (R/R) Waldenström Macroglobu

