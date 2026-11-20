# Readout links and single-trial premises, 2026-11-16

Sources were read on 2026-11-16: the ClinicalTrials.gov API v2 record for each study
(`https://clinicaltrials.gov/api/v2/studies/<NCT>`), openFDA labels
(`https://api.fda.gov/drug/label.json`), PubMed E-utilities, MeSH lookup
(`https://id.nlm.nih.gov/mesh/lookup/descriptor?label=<term>&match=exact`) and the
Federal Register. `er_tool.db` was opened read-only to see where each readout currently
sits. Nothing under `data/` was written. Draft rows are in `docs/research/links_drafts/`.

The test applied is `forecast_view._one_population_legs`: one condition string, one
primary endpoint, one population. Two of the four Part 1 studies file several condition
strings for what is one randomised population, so the rule refuses them and only a
curated row can link them.

## Where the four readouts sit now (read-only)

| Catalyst | Asset it sits on | asset_indication_id | Pairs the asset holds |
|---|---|---|---|
| 1590 NCT05047172, 2027-01-31 | Brilinta (190) | null | Intracranial Arteriosclerosis (165), Stroke (166) |
| 1324 NCT06834932, 2027-02-22 | Crestor (961) | null | none |
| 1592 NCT05374291, 2027-07 | Farxiga (210) | null | Death (173), Heart Failure (174), Renal Insufficiency (175) |
| 1582 NCT06847542, 2028-11-15 | Lucentis (532) | null | none (Susvimo, 615, holds Wet Macular Degeneration 546) |

---

## PART 1

### a. AZN Brilinta, NCT05047172 (CAPTIVA)

**VERDICT: LINK to Intracranial Arteriosclerosis (D002537). Ticagrelor is an INVESTIGATIONAL product, and the reported comparison is wrong.**

- Lead sponsor: University of Florida. Collaborators: NINDS, University of Cincinnati,
  Medical University of South Carolina, Janssen Scientific Affairs, LLC, AstraZeneca.
  Phase 3, ACTIVE_NOT_RECRUITING, enrolment 1,683 (ESTIMATED), randomised, quadruple
  masked. Primary completion 2027-01-31 (estimated).
- Conditions as filed: `['Intracranial Arteriosclerosis', 'Stroke']`, so the book's
  rule refuses it because there are two strings.
- Arms (verbatim):
  - "Experimental Arm: Ticagrelor and Aspirin | EXPERIMENTAL | Ticagrelor (180mg loading
    dose, then 90mg twice daily) and aspirin (81mg daily)"
  - "Standard of Care Arm: Clopidogrel and Aspirin | ACTIVE_COMPARATOR"
  - "Experimental Arm: Rivaroxaban and Aspirin | EXPERIMENTAL | Rivaroxaban (2.5mg twice
    daily) and aspirin (81mg daily)"
- **The brief is wrong.** It says ticagrelor + aspirin against rivaroxaban + aspirin.
  In fact this is a three-arm trial. Both ticagrelor and rivaroxaban are experimental
  arms, and each is measured against **clopidogrel + aspirin**. Ticagrelor is
  investigational, so this is a readout of the medicine. Whether AstraZeneca would file
  on an academic, NINDS-collaborated result cannot be verified from the registry, which
  does not state AstraZeneca's role.
- Primary outcomes (two):
  - Safety: "Number of participants with parenchymal ICH or non-ICH major hemorrhage", up to 12 months.
  - Efficacy: "Number of participants with ischemic stroke, intracerebral hemorrhage or
    vascular death", up to 12 months.
- Population: a stroke within 30 days "attributed to 70-99% stenosis (or flow gap on
  MRA) of a major intracranial artery", mRS of 4 or below, age 30 and over.
- Why one disease: the two condition strings describe one population. Stroke is the
  qualifying event and the outcome, and intracranial atherosclerotic stenosis is the
  disease that selects the patients. MeSH D002537 was verified by exact lookup.
- Label (set id f7b3f443-e83d-4bf2-0e96-023448fed9a8, effective 2026-05-07): "to reduce
  the risk of stroke in patients with acute ischemic stroke (NIH Stroke Scale score ≤5)
  or high-risk transient ischemic attack (TIA)". Dosing: "90 mg twice daily for up to 30
  days". The label names neither intracranial stenosis nor 12 months of treatment.
  Stroke is on the label; Intracranial Arteriosclerosis is not.
- **For the row:** an additions row on D002537 links catalyst 1590 to pair 165, which
  reads as an unapproved expansion. Part of the population (minor stroke, first 30 days)
  is already labelled. The readout decides ticagrelor against clopidogrel only. The
  rivaroxaban comparison is Janssen's/Bayer's, not AstraZeneca's.

### b. AZN Crestor, NCT06834932 (AZURE-CHINA)

**VERDICT: NOT THIS COMPANY'S PROGRAMME (for Crestor). Rosuvastatin is a background and run-in therapy. The study is AZD0780's.**

- Official title: "A Randomised, Double-blind, Placebo-controlled, Multi-centre,
  Sequential Phase II, and Phase III Study to Evaluate the Efficacy, Safety, and
  Pharmacokinetics of AZD0780 ... in Participants With Dyslipidaemia (AZURE-CHINA)".
- Lead: AstraZeneca, no collaborators. Phase 2/3, ACTIVE_NOT_RECRUITING, 432 enrolled
  (ACTUAL). Condition: `['Dyslipidaemia']`, which the registry indexes as Dyslipidemias
  (D050171).
- Arms (verbatim):
  - "AZD0780 +Rosuvastatin Dose 1 (Part A) | EXPERIMENTAL"
  - "Placebo +Rosuvastatin Dose 1 (Part A) | PLACEBO_COMPARATOR"
  - "AZD0780 (Part B Cohort 1) | EXPERIMENTAL"
  - "Placebo (Part B Cohort 1) | PLACEBO_COMPARATOR"
  - "AZD0780+Rosuvastatin Dose 1 (Part B Cohort 2)"
  - "Placebo+Rosuvastation Dose 1 (Part B Cohort 2)"
  - Part A: "Participants will receive Rosuvastatin Dose 1 QD for minimum 21 days (up to 28
    days) ... Then receive AZD0780 QD as add on".
  - Rosuvastatin is given in both the AZD0780 and placebo arms, so it is background.
- Primary outcomes: Part A, AZD0780 PK (concentrations, AUC, Cmax); Part B, "Relative
  change in LDL-C from baseline to 12 weeks".
- How it reached Crestor: the interventions are Placebo, Rosuvastatin Dose 1, Rosuvastatin
  dose 2, AZD0780 (`trial_interventions`), and the name match landed on rosuvastatin.
- **For the row:** a Crestor readout here is a mapping error. Draft
  `trial_asset_map.csv` row pins the study to AZD0780 (asset 1707, which holds
  Hypercholesterolemia D006937 and Cardiovascular Diseases D002318). An optional
  additions row puts the readout on AZD0780's Hypercholesterolemia pair, because Part B
  selects and measures on LDL-C.

### c. AZN Farxiga, NCT05374291 (RENAL LIFECYCLE)

**VERDICT: LINK to Renal Insufficiency, Chronic (D051436). Dapagliflozin is the INVESTIGATIONAL product. CKD is on the label, but this population is the part the label does not recommend starting in, so a sub-population row is the better landing.**

- Lead: University Medical Center Groningen. Collaborators: AstraZeneca, Dutch Kidney
  Foundation. Phase 3, ACTIVE_NOT_RECRUITING, 1,750 (ESTIMATED), randomised, double
  masked. Primary completion 2027-07 (estimated). The brief is confirmed on sponsor,
  dose, comparator and size.
- Arms: "Dapagliflozin | EXPERIMENTAL | Dapagliflozin 10 mg/day (oral)"; "Placebo |
  PLACEBO_COMPARATOR". Intervention other name: Forxiga.
- Conditions as filed (five): `['Kidney Disease, Chronic', 'Renal Transplant Failure',
  'Heart Failure', 'Kidney Failure', 'Death']`. The rule refuses it. But this is not a
  basket. Death, kidney failure and heart failure are components of the one composite
  endpoint, and transplant failure is a stratum of the one randomised population.
- Primary outcome: "Number of partipants with all-cause mortality, kidney failure, and
  hospitalization for heart failure ... in the overall study population", over 48 months.
- Population (verbatim): "Patients with advanced CKD i.e. an eGFR ≤25 mL/min/1.73m2";
  "Dialysis patients (at least 3 months after start of dialysis)"; "Transplant patients
  with an eGFR ≤45 mL/min/1.73m2 (at least 6 months after transplantation)".
- Label (set id 72ad22ae-efe6-4cd6-a302-98aaee423d69, effective 2026-06-03), indication:
  "To reduce the risk of sustained eGFR decline, end-stage kidney disease, cardiovascular
  (CV) death, and hospitalization for heart failure in adults with chronic kidney disease
  at risk of progression."
  - Dosing: "Initiation with FARXIGA is not recommended in patients with an eGFR less than 25 mL/min/1.73 m2".
  - Section 8.6: "Efficacy and safety trials with FARXIGA did not enroll patients with an
    eGFR less than 25 mL/min/1.73 m2 or on dialysis."
  - Limitation of use: not recommended "in patients with polycystic kidney disease or
    patients requiring or with a recent history of immunosuppressive therapy". The trial
    likewise excludes recent renal immunosuppression and ADPKD on tolvaptan.
- **For the row:** a plain additions row on D051436 (option A) makes the readout read as
  already approved, which would misstate a genuine expansion of the population. Option B,
  a `subpopulation_indications.csv` row "Advanced chronic kidney disease (eGFR 25 or
  below, dialysis, or kidney transplant)" with parent D051436 and label_covers "no", is
  recommended. Commit one, not both. Separately, Farxiga's Death (D003643) pair is a
  study outcome, not a disease, and probably wants an exclusion row. This was not
  drafted, because I did not check which other studies feed it.

### d. ROG Lucentis, NCT06847542 (Sightspire)

**VERDICT: LINK to Wet Macular Degeneration (D057135), on Susvimo, not Lucentis. Ranibizumab via the Port Delivery System is the INVESTIGATIONAL product (Roche's own). The disease is already on the label.**

- Official title: "A Phase IIIb, Multicenter, Single-arm Study Assessing the
  Effectiveness, Safety and Patient Reported Outcomes of a 36-week Refill Exchange
  Regimen for the Port Delivery System With Ranibizumab in Patients With Neovascular
  Age-related Macular Degeneration".
- Lead: Hoffmann-La Roche, collaborator Genentech. Phase 3 (IIIb), RECRUITING, 250
  (ESTIMATED), single arm. Primary completion 2028-11-15 (estimated). Condition:
  `['Neovascular Age-related Macular Degeneration']` (one string, no MeSH indexing).
- Arm: "Port Delivery System (PDS) | EXPERIMENTAL". Interventions: "Device: Susvimo PDS
  Implant", "Drug: Ranibizumab". The 0.5 mg intravitreal ranibizumab is only
  "supplemental treatment".
- Primary outcome: "Change From Baseline in Best Corrected Visual Acuity (BCVA) Score
  Averaged Over Weeks 68 and 72".
- Population: "Initial diagnosis of nAMD within 24 months prior to screening"; "Previous
  treatment with at least 3 anti-vascular endothelial growth factor (VEGF) IVT
  injections"; "Demonstrated response to prior anti-VEGF IVT treatment".
- SUSVIMO label (set id 9c6d9e2a-9a77-4d11-b692-de87cfde3444, effective 2025-11-21):
  "Neovascular (wet) Age-related Macular Degeneration (AMD) who have previously responded
  to at least two intravitreal injections of a VEGF inhibitor". nAMD and DME are dosed
  "with refills every 24 weeks"; DR is dosed "with refills every 36 weeks". The study
  population is inside the label, and it tests a 36-week interval in nAMD.
- **For the row:** this is the Velodrome (NCT04657289) shape already pinned in
  `data/trial_asset_map.csv` line 51. Draft rows pin NCT06847542 to Susvimo and add it to
  Susvimo's D057135 pair (or append it to the existing line 101). The readout will read
  already_approved, which is correct.
- Side defect: the basis text of `asset_indication_additions.csv` line 101 says "(D057130)".
  D057130 is Leber Congenital Amaurosis. The mesh_id column (D057135) is right; only the
  prose is wrong.

---

## PART 2

### e. BAYN Stivarga in glioblastoma, NCT03970447 (GBM AGILE)

**VERDICT: The regorafenib arm STOPPED FOR LIMITED EFFICACY and its final analysis is published negative. It decides nothing further.**

- Registry: lead Global Coalition for Adaptive Research; collaborators include Bayer.
  Platform status RECRUITING; primary completion 2028-06 (estimated) for the whole
  platform. The arm label is verbatim: **"Regorafenib Treatment Arm- Enrollment
  concluded"**. The registry lists as its RESULT reference: Wen PY, Berry DA, ... Lassman
  AB; GBM AGILE Regorafenib Study Group. J Clin Oncol 2026;44(18):1676-1686, Epub
  2026-04-14, doi 10.1200/JCO-25-01137, PMID 41980234.
- The publication abstract (PubMed, read 2026-11-16) says:
  - Regorafenib was the first investigational arm.
  - It was tested in newly diagnosed MGMT-unmethylated and recurrent glioblastoma against
    temozolomide plus radiotherapy or lomustine.
  - Accrual stopped when Bayesian predictive power fell below 25% in every predefined
    signature (limited efficacy).
  - The final analysis showed no overall survival improvement: median HRs 1.05 (NDU),
    1.07 (recurrent) and 1.07 (all), with higher toxicity.
  - The authors report regorafenib was removed from NCCN guidelines for recurrent disease.
    I did not verify this against NCCN directly.
- **For the row:** catalyst 1591 (Stivarga, pair 263 Glioblastoma, 2028-06, pending) is
  dated to the platform, not the arm. The draft `settled_readouts.csv` row uses kind
  `already_read_out`. Pair 263 at Phase 2/3 should be treated as failed. I found no Bayer
  statement and did not search Bayer's pipeline chart.

### f. SNY Wayrilz (rilzabrutinib) in ITP, NCT07007962 (LUNA 4)

**VERDICT: CANNOT BE SETTLED FROM FREE SOURCES. The registry does not exclude newly diagnosed ITP (under 3 months) and does not require persistent or chronic disease. The population is defined by line of therapy, not duration.**

- Lead: Sanofi. Phase 3, open-label single arm, 60 (ESTIMATED), RECRUITING, primary
  completion 2027-11-05. Condition: `['Immune Thrombocytopenia']`, MeSH D016553.
- Primary outcome: "Durable platelet response", until Week 28.
- Key inclusion (verbatim):
  - "documented diagnosis of primary ITP in the medical history"
  - "Participant received at least one course of first-line therapy and had a history of
    response while on treatment"
  - "Participant has loss of response, relapse, or steroid dependency"
- Key exclusion: "Participant received advanced therapy for ITP or was splenectomized".
- Brief summary: "evaluate the impact of early multi-immune modulation with rilzabrutinib
  in adult ITP patients who failed first-line treatment."
- Contrast with LUNA 3 (NCT04562766), the study the approval rests on: it required "duration
  of >3 months in ages 18 years and above". LUNA 4 has no duration criterion in the
  registered key criteria. The record also warns that "The above information is not
  intended to contain all considerations".
- Against the label ("adult patients with persistent or chronic immune thrombocytopenia
  (ITP) who have had an insufficient response to a previous treatment"):
  - The "insufficient response to a previous treatment" clause is met.
  - The "persistent or chronic" clause is not required, so patients under 3 months from
    diagnosis can enrol. The word "early" points that way.
  - The duration mix cannot be verified without the full protocol, which I did not find
    on a free primary source.
- **For the row:** the trial is already linked (catalyst 926 on pair 297, from
  `asset_indication_additions.csv` line 42). It overlaps the label and extends it into
  early second-line ITP of any duration. `settled_readouts.csv` already leaves it
  unsettled for exactly this reason, and the registry supports keeping it that way. A
  60-patient single-arm study is unlikely by itself to support a label change, but I have
  no source on Sanofi's filing intent.

### g. SNY Dupixent in paediatric prurigo nodularis, NCT06293053

**VERDICT: A 24-week open-label PK and safety study in about 18 children. A design like this has supported a Dupixent paediatric extension before (CSU), but there efficacy already reached age 12. Here efficacy is adults-only. A free US source sizes paediatric PN, secondhand.**

- Lead: Sanofi; collaborator Regeneron. Phase 3, single arm, open label, 18 (ESTIMATED),
  RECRUITING, primary completion 2027-10-28. Ages 6 months to 17 years. Condition:
  `['Prurigo Nodularis']`, with no MeSH indexing.
- Title: "A Multicenter Open-label Study to Investigate the Pharmacokinetics and Safety of
  Dupilumab in Participants ≥6 Months to <18 Years of Age With Prurigo Nodularis".
- Design (verbatim): "This is a Phase 3, multicenter, open-label, pharmacokinetics
  (PK)/safety study", with a "Treatment period: 24 weeks" and a "Post-intervention
  follow-up period: 16 weeks".
- Primary outcome: "Concentration of dupilumab in serum", Day 1 to Week 40. Secondary
  outcomes are TEAEs/SAEs and anti-drug antibodies. There is no efficacy endpoint.
- Can PK support a paediatric label?
  - FDA finalised ICH **E11A Pediatric Extrapolation** in December 2024 (Federal Register
    89 FR, 2024-12-30, doc 2024-31026,
    https://www.govinfo.gov/content/pkg/FR-2024-12-30/html/2024-31026.htm). It covers
    extrapolating efficacy from adults to children, with modelling and simulation.
  - Precedent on the same label (Dupixent set id 595f437d-..., effective 2026-04-22, 8.4):
    CSU in ages 2 and up is "supported by evidence from two adequate and well-controlled
    studies in adults and pediatric patients aged 12 years and older ... with the following
    additional data: Pharmacokinetic (PK) data in 6 pediatric patients 12 to 17 years of
    age, PK data in 18 pediatric patients 2 to 11 years of age". AFRS ages 6 and up rested
    on PK in 3 paediatric patients plus PK and safety from other indications.
  - The difference here: PRIME (NCT04183335) and PRIME2 (NCT04202679) enrolled ages 18 to
    80 only. The PN efficacy evidence has no adolescents, so extrapolation would run from
    adults to infants with nothing in between. I found no precedent label built on
    adult-only efficacy plus paediatric PK.
  - The label today: "Safety and effectiveness of DUPIXENT have not been established in
    pediatric patients with PN".
- Sizing: the book already holds prevalence 15,797 (assumption 16041), which is 21.6 per
  100,000 children times 73,132,720 US residents aged 0 to 17 (Census Vintage 2024).
  - The rate's primary is Huang AH ... Kwatra SG, J Am Acad Dermatol 2022;86(3):655-657,
    PMID 33600911. It is a research letter with no abstract on PubMed (confirmed).
  - I re-read both open-access secondary quotes in PMC on 2026-11-16, and both state 21.6
    per 100,000: PMC13425074 (Skin Health Dis 2026) and PMC13630499 (Clin Exp Allergy 2026).
- **For the row:** the paediatric row (2470) and its catalyst (922) are already correct.
  This is a PK readout whose regulatory value depends on FDA accepting adult-to-child
  extrapolation. Price it as a label extension with that risk named, not as an efficacy
  readout.

### h. SNY Dupixent in chronic pruritus of unknown origin, NCT05263206

**VERDICT: CONFIRMED, as far as a search can confirm a negative. I found no free US prevalence figure for CPUO.**

- Study: "Master Protocol of Two Randomized, Double Blind, Placebo-controlled, Multi-center,
  Parallel Group Studies ... in Adult Patients With Chronic Pruritus of Unknown Origin
  (CPUO)".
  - Sanofi, Phase 3, 284 (ESTIMATED). Condition: `['Pruritus']`.
  - Primary outcomes: Study A, WI-NRS improvement of 4 or more at Week 24; Study B, the
    same at Week 12.
  - Inclusion: "Chronic pruritus considered of unknown origin as assessed by the
    investigator at baseline".
- Searches:
  - PubMed E-utilities, 2026-11-16: `"chronic pruritus of unknown origin" AND (prevalence OR
    epidemiology OR incidence)` returned 6 records; `"pruritus of unknown origin" AND (United
    States OR claims OR TriNetX OR database)` returned 5; `"CPUO" AND (prevalence OR
    epidemiology)` returned 2. None reports a US population prevalence.
  - The closest US review, Roh YS ... Kwatra SG, "Itch: Epidemiology, clinical
    presentation, and diagnostic workup", J Am Acad Dermatol 2022 (PMC8678917), describes
    CPUO as a diagnosis of exclusion and gives no CPUO prevalence (full text searched).
  - A web search found only European and German-centre shares and a paywalled commercial
    forecast. The forecast is not a free primary source.
- **For the row:** the refusal in `layers_2026-11-16.md` (row 25) stands. Pair 634 stays
  unpriced on epidemiology.

---

## Drafts written (none applied)

- `docs/research/links_drafts/asset_indication_additions.csv`: Brilinta D002537
  (NCT05047172); Farxiga D051436 (NCT05374291, option A); Susvimo D057135 (NCT06847542);
  optional AZD0780 D006937 (NCT06834932).
- `docs/research/links_drafts/subpopulation_indications.csv`: Farxiga advanced CKD
  (option B, recommended).
- `docs/research/links_drafts/trial_asset_map.csv`: NCT06847542 to Susvimo; NCT06834932
  to AZD0780.
- `docs/research/links_drafts/settled_readouts.csv`: Stivarga NCT03970447 `already_read_out`.

All MeSH ids were verified by exact lookup on 2026-11-16: D002537, D051436, D057135,
D016553, D050171, D006937, D005909, D011536, D011537, D020521.
