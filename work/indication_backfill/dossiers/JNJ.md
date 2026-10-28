# JNJ: 7 indication layers to research

## Caplyta  (asset_id 3387)
- mode **marketed**, revenue anchor 1,353mm USD
- **CMS Part D 2024** (Caplyta): $268,479,293 over 27,010 beneficiaries = **$9,940 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Autism Spectrum Disorder   [Phase 3, Recruiting]
- unit key `3387:147`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT06706674  Phase 3, Recruiting, n=160, primary completion 2027-06-21
    Multicenter Study of Lumateperone for the Treatment of Irritability Associated With Autism Spectrum Disorder (ASD) in Pediatric Patients
- trial NCT06690398  Phase 3, Recruiting, n=160, primary completion 2027-06-21
    Multicenter Study of Lumateperone for the Treatment of Irritability Associated With Autism Spectrum Disorder in Pediatric Patients
- trial NCT06229210  Phase 3, Recruiting, n=300, primary completion 2032-04-28
    Safety and Tolerability Trial of Lumateperone in Pediatric Patients With Schizophrenia, Bipolar Disorder or Autism Spectrum Disorder

## IMBRUVICA  (asset_id 844)
- mode **marketed**, revenue anchor 2,823mm USD
- **CMS Part D 2024** (Imbruvica): $2,266,252,032 over 15,351 beneficiaries = **$147,629 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Lymphoma, Follicular   [Phase 3, Active not recruiting]
- unit key `844:6`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 13,960 patients a year
      source: Teras LR et al., CA Cancer J Clin 2016;66:443-459: 13,960 new US follicular lymphoma cases expected in 2016. SEER does not report follicular lymphoma separately, counting it within non-Hodgkin lymphoma, so this remains the standard citation despite its age. Prevalence equals incidence by the oncology convention above
    - `prevalence` = 13,960 patients
      source: Teras LR et al., CA Cancer J Clin 2016;66:443-459: 13,960 new US follicular lymphoma cases expected in 2016. SEER does not report follicular lymphoma separately, counting it within non-Hodgkin lymphoma, so this remains the standard citation despite its age. Prevalence equals incidence by the oncology convention above
- trial NCT01804686  Phase 3, Active not recruiting, n=539, primary completion 2026-12-31
    A Long-term Extension Study of PCI-32765 (Ibrutinib)

### Lymphoma, Large B-Cell, Diffuse   [Phase 3, Active not recruiting]
- unit key `844:5`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 19,046 patients a year
      source: SEER Cancer Stat Facts: 5.6 new DLBCL cases per 100,000 a year (age-adjusted, 2019 to 2023) applied to the 340,110,988 US residents of 1 July 2024 (Census)
    - `prevalence` = 19,046 patients
      source: SEER Cancer Stat Facts: 5.6 new DLBCL cases per 100,000 a year (age-adjusted, 2019 to 2023) applied to the 340,110,988 US residents of 1 July 2024 (Census)
- trial NCT01804686  Phase 3, Active not recruiting, n=539, primary completion 2026-12-31
    A Long-term Extension Study of PCI-32765 (Ibrutinib)

### Lymphoma, Mantle-Cell   [Phase 3, Active not recruiting]
- unit key `844:59`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT01804686  Phase 3, Active not recruiting, n=539, primary completion 2026-12-31
    A Long-term Extension Study of PCI-32765 (Ibrutinib)

## Rybrevant / Lazcluze  (asset_id 7308)
- mode **marketed**, revenue anchor 734mm USD
- **CMS Part B 2024** (Rybrevant): $70,056,728 over 839 beneficiaries = **$83,500 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **CMS Part D 2024** (Rybrevant): $3,046,904 over 28 beneficiaries = **$108,818 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Colorectal Neoplasms   [Phase 3, Recruiting]
- unit key `7308:381`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 158,850 patients a year
      source: SEER Cancer Stat Facts, colorectal cancer: 158,850 estimated new US cases in 2026
    - `prevalence` = 158,850 patients
      source: SEER Cancer Stat Facts, colorectal cancer: 158,850 estimated new US cases in 2026
- trial NCT05379595  Phase 1/2, Recruiting, n=225, primary completion 2027-04-27
    A Study of Amivantamab Monotherapy and in Addition to Standard-of-Care Chemotherapy in Participants With Advanced or Metastatic Colorectal Cancer
- trial NCT06750094  Phase 3, Recruiting, n=700, primary completion 2027-12-15
    A Study of Amivantamab and FOLFIRI Versus Cetuximab/Bevacizumab and FOLFIRI in Participants With KRAS/NRAS and BRAF Wild-type Colorectal Cancer Who Ha
- trial NCT06662786  Phase 3, Recruiting, n=1000, primary completion 2028-12-15
    A Study of Amivantamab and mFOLFOX6 or FOLFIRI Versus Cetuximab and mFOLFOX6 or FOLFIRI as First-line Treatment in Participants With KRAS/NRAS and BRA
- **pending catalyst** 2027-12-15 (data readout): Phase 3, Rybrevant / Lazcluze

### Squamous Cell Carcinoma of Head and Neck   [Phase 3, Recruiting]
- unit key `7308:67`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT07276399  Phase 3, Recruiting, n=500, primary completion 2029-06-18
    A Study of Amivantamab in Addition to Standard of Care Agents (SOC) Compared With SOC Alone in Participants With Recurrent/Metastatic Head and Neck Ca
- trial NCT06385080  Phase 1/2, Recruiting, n=287, primary completion 2032-12-27
    A Study of Amivantamab Alone or in Addition to Other Treatment Agents in Participants With Head and Neck Cancer

## Tremfya  (asset_id 572)
- mode **marketed**, revenue anchor 5,155mm USD
- **CMS Part D 2024** (Tremfya (2 presentations)): $619,021,086 over 10,860 beneficiaries = **$57,000 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Arthritis, Juvenile   [Phase 3, Recruiting]
- unit key `572:43`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 1,300 patients a year
      source: JIA incidence 11.9 per 100,000 in the same cohort, 8,660 a year, at the same 15% for the two categories
    - `prevalence` = 4,900 patients
      source: JIA at 44.7 per 100,000 US children (managed-care cohort, PMC5657479) against 72.8 million under 18 is 32,500 with JIA; enthesitis-related arthritis is 5% to 10% of JIA and juvenile psoriatic arthritis 2% to 15% (StatPearls NBK554605), so the two categories COSPIRIT-JIA enrolled are taken at 15% of JIA together
- trial NCT06663332  Phase 3, Recruiting, n=196, primary completion 2031-12-12
    A Long-term Extension (LTE) Study of Guselkumab in Pediatric Participants

