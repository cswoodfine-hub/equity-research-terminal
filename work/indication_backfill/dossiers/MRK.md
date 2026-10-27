# MRK: 13 indication layers to research

## Keytruda  (asset_id 412)
- mode **franchise**, revenue anchor 31,681mm USD
- price on file: `net_price_per_patient` = 0.079464 mm USD per year — comparator estimate: Keytruda itself, CMS Part B 2024: 5.99bn over 75,361 beneficiaries. Part B pays ASP plus 6%, so thi
- **CMS Part B 2024** (Keytruda): $5,988,521,233 over 75,361 beneficiaries = **$79,464 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **CMS Part D 2024** (Keytruda): $140,055,040 over 1,906 beneficiaries = **$73,481 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct.** Every layer below needs these, so find them once for the product:
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Hodgkin Disease   [Phase 2, Active not recruiting]
- unit key `412:136`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT03407144  Phase 2, Active not recruiting, n=340, primary completion 2027-02-12
    Safety and Efficacy of Pembrolizumab (MK-3475) in Children and Young Adults With Classical Hodgkin Lymphoma (MK-3475-667/KEYNOTE-667)
- **pending catalyst** 2027-02-12 (data readout): Phase 2, Keytruda

### Urinary Bladder Neoplasms   [Phase 3, Active not recruiting]
- unit key `412:385`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 84,530 patients a year
      source: SEER Cancer Stat Facts: Bladder Cancer, as data/epidemiology.csv
    - `prevalence` = 84,530 patients
      source: SEER Cancer Stat Facts: Bladder Cancer, estimated new US cases for the year, the incidence data/epidemiology.csv carries for Urinary Bladder Neoplasms
- trial NCT03924895  Phase 3, Active not recruiting, n=595, primary completion 2025-06-06
    Perioperative Pembrolizumab (MK-3475) Plus Cystectomy or Perioperative Pembrolizumab Plus Enfortumab Vedotin Plus Cystectomy Versus Cystectomy Alone i
- trial NCT04700124  Phase 3, Active not recruiting, n=808, primary completion 2025-10-27
    Perioperative Enfortumab Vedotin (EV) Plus Pembrolizumab (MK-3475) Versus Neoadjuvant Chemotherapy for Cisplatin-Eligible Muscle Invasive Bladder Canc
- trial NCT04241185  Phase 3, Active not recruiting, n=520, primary completion 2027-01-31
    Efficacy and Safety of Pembrolizumab (MK-3475) in Combination With Chemoradiotherapy (CRT) Versus CRT Alone in Muscle-invasive Bladder Cancer (MIBC) (
- trial NCT06305767  Phase 1/2, Active not recruiting, n=230, primary completion 2027-04-23
    A Clinical Study of Intismeran Autogene (V940) Treatment and Pembrolizumab in People With Bladder Cancer (V940-005/INTerpath-005)
- **pending catalyst** 2027-01-31 (data readout): Phase 3, Keytruda

### Bile Duct Neoplasms   [Phase 2, Active not recruiting]
- unit key `412:192`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Carcinoid Tumor   [Phase 2, Active not recruiting]
- unit key `412:193`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Cholangiocarcinoma   [Phase 2, Active not recruiting]
- unit key `412:10`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Hematologic Neoplasms   [Phase 3, Recruiting]
- unit key `412:401`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT03486873  Phase 3, Recruiting, n=3500, primary completion 2043-08-04
    Long-term Safety and Efficacy Extension Study for Participants With Advanced Tumors Who Are Currently on Treatment or in Follow-up in a Pembrolizumab 

### Neuroendocrine Tumors   [Phase 2, Active not recruiting]
- unit key `412:469`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02362594  Phase 3, Active not recruiting, n=1019, primary completion 2018-01-08
    Study of Pembrolizumab (MK-3475) Versus Placebo After Complete Resection of High-Risk Stage III Melanoma (MK-3475-054/1325-MG/KEYNOTE-054)
- trial NCT03553836  Phase 3, Active not recruiting, n=976, primary completion 2021-06-21
    Safety and Efficacy of Pembrolizumab Compared to Placebo in Resected High-risk Stage II Melanoma (MK-3475-716/KEYNOTE-716)
- trial NCT06099782  Phase 2, Active not recruiting, n=147, primary completion 2025-04-09
    A Study of Participant Reported Preference for Subcutaneous Pembrolizumab Coformulated With Berahyaluronidase Alfa (MK-3475A) Over Intravenous Pembrol
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)
- trial NCT02332668  Phase 1/2, Recruiting, n=370, primary completion 2028-02-02
    A Study of Pembrolizumab (MK-3475) in Pediatric Participants With an Advanced Solid Tumor or Lymphoma (MK-3475-051/KEYNOTE-051)
- trial NCT07302347  Phase 1/2, Recruiting, n=20, primary completion 2029-03-30
    A Study of Pembrolizumab in Japanese Pediatric Participants With Solid Tumors or Lymphomas and Japanese Adult Participants With Merkel Cell Carcinoma 

### Parotid Neoplasms   [Phase 2, Active not recruiting]
- unit key `412:196`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Salivary Gland Neoplasms   [Phase 2, Active not recruiting]
- unit key `412:195`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Thyroid Neoplasms   [Phase 2, Active not recruiting]
- unit key `412:407`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

### Vulvar Neoplasms   [Phase 2, Active not recruiting]
- unit key `412:194`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT02628067  Phase 2, Active not recruiting, n=1609, primary completion 2027-05-04
    Study of Pembrolizumab (MK-3475) in Participants With Advanced Solid Tumors (MK-3475-158/KEYNOTE-158)

## Verquvo  (asset_id 330)
- mode **marketed**, revenue anchor 48mm USD
- **CMS Part D 2024** (Verquvo): $49,680,167 over 11,127 beneficiaries = **$4,465 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Ventricular Dysfunction, Left   [Phase 2/3, Recruiting]
- unit key `330:82`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05714085  Phase 2/3, Recruiting, n=342, primary completion 2032-04-15
    Efficacy, Safety, and Pharmacokinetics of Vericiguat in Pediatric Participants With Heart Failure Due to Left Ventricular Systolic Dysfunction (MK-124

## Welireg  (asset_id 339)
- mode **marketed**, revenue anchor 716mm USD
- **CMS Part D 2024** (Welireg): $205,460,496 over 1,896 beneficiaries = **$108,365 per beneficiary a year**. This is the basis the book prices on — see amgn_abp_206.csv.
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Breast Neoplasms   [Phase 2, Active not recruiting]
- unit key `339:371`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 65,000 patients a year
      source: about 310,000 new US breast cancers a year, roughly 70% of them HR-positive HER2-negative, of which about 30% become metastatic
    - `prevalence` = 160,000 patients
      source: roughly 160,000 US women live with metastatic HR-positive HER2-negative breast cancer, the same pool this book uses for Truqap
- trial NCT06428396  Phase 2, Active not recruiting, n=120, primary completion 2027-05-05
    Study of Belzutifan (MK-6482) Plus Fulvestrant for ER+/HER2- Metastatic Breast Cancer (MK-6482-029/LITESPARK-029)

