# `in_the_base` triage — 58 zero-priced readouts

Prepared 2026-11-11. Every label quote below is from the current FDA label retrieved via
openFDA (`https://api.fda.gov/drug/label.json`) or, for CBER vaccine products, from the
DailyMed SPL. Every eligibility quote is from the ClinicalTrials.gov v2 API record for the
NCT shown. Effective dates of the labels used are given in each entry.

**Result: 8 bucket A, 21 bucket B, 28 bucket C, 1 could-not-determine.**

The 21 B's are not of equal weight, so a conviction column is included. High-conviction B's
(11 rows) are the ones where the label itself states the gap: an accelerated approval awaiting
a confirmatory trial, an explicit Limitations of Use, a missing outcomes claim, or a dosing
schedule the label does not contain. Low-conviction B's (2 rows) only firm up an existing
guideline position and should probably be discounted heavily rather than modelled.

**Three findings worth flagging before the table:**

1. **Three rows that look like bucket A are not.** The worked example generalises badly.
   Otezla/juvenile PsA (row 2), Tryngolza/sHTG (row 18) and Hyrnuo/1L NSCLC (row 11) all
   read as out-of-label sub-populations from the registry alone, but the current labels have
   caught up: Otezla now covers pediatric PsA from age 6, Tryngolza now covers sHTG at
   TG>=500 mg/dL, and the Hyrnuo indication carries no line-of-therapy limit at all (its own
   efficacy population includes a treatment-naive group). Checking the label as of today,
   rather than as of when the row was written, is what separates these from the real A's.

2. **Rows 43, 45 and 46 are an asset-mapping defect, not a triage question.** All three study
   "PG4", which the registry records describe as *"a new pneumococcal vaccine ... compared to
   the pneumococcal vaccines that are currently in use, 20vPnC (Prevnar 20)"*. PG4 is a
   separate investigational multivalent PCV, not Prevnar 20. These should be re-pointed at a
   PG4 pipeline asset rather than carried as Prevnar base-overlap rows. Bucketed C on their
   own merits (lot consistency, formulation selection, catch-up cohort), but the mapping is
   the thing to fix.

3. **Row 25 is a master-protocol shell.** Its only primary outcome is *"Number of Participants
   Allocated to Each ISA"*. It cannot produce a priceable readout in any bucket; rows 26 and 27
   are the substantive ISAs under it. Consider suppressing it as a catalyst entirely.

---

## 1. Summary table

| # | Ticker | Asset | Indication | NCT | Bucket | Conv. | One-line reason |
|---|---|---|---|---|---|---|---|
| 0 | ABBV | Ubrelvy | Migraine Disorders | [NCT06417775](https://clinicaltrials.gov/study/NCT06417775) | **B** | high | Label Limitations of Use: 'not indicated for the preventive treatment of migraine'; trial is preventive dosing for menstrual migraine. |
| 1 | ABBV | Venclexta | Leukemia, Lymphocytic, Chronic, B-Cell | [NCT06428019](https://clinicaltrials.gov/study/NCT06428019) | **B** | med | In-label 1L CLL; tests shorter venetoclax ramp-up / TLS risk - a Dosage & Administration (section 2) change, not a population change. |
| 2 | AMGN | Otezla | Arthritis, Juvenile | [NCT04804553](https://clinicaltrials.gov/study/NCT04804553) | **C** | - | Otezla label now covers pediatric PsA 6+; PEAPOD population is in-label (only the 5-to-<6y sliver is outside). |
| 3 | ARGX | Vyvgart | Polyradiculoneuropathy, Chronic Inflammatory Demyelinating | [NCT04280718](https://clinicaltrials.gov/study/NCT04280718) | **C** | - | Open-label extension of ADHERE; primary endpoint is TEAEs. |
| 4 | AZN | Tezspire | Rhinosinusitis | [NCT06706817](https://clinicaltrials.gov/study/NCT06706817) | **C** | - | Single-arm Phase 3b symptom-description study in the approved CRSwNP indication. |
| 5 | AZN | Enhertu | Pancreatic Neoplasms | [NCT04482309](https://clinicaltrials.gov/study/NCT04482309) | **A** | med | Pan-tumor label is HER2 IHC 3+ only; DESTINY-PanTumor02 also enrols IHC 2+ - partial overlap, IHC2+ pancreatic slice is unpriced. |
| 6 | AZN | Tezspire | Asthma | [NCT06473779](https://clinicaltrials.gov/study/NCT06473779) | **B** | low | ARRIVAL tests ICS step-down while on Tezspire - a positioning/steroid-sparing claim, not a new population. |
| 7 | AZN | Calquence | Leukemia, Lymphocytic, Chronic, B-Cell | [NCT05057494](https://clinicaltrials.gov/study/NCT05057494) | **B** | high | MAJIC is head-to-head acala+ven vs ven+obin in 1L CLL; both in-label, a win moves guideline preference between regimens. |
| 8 | AZN | Baxfendy | Hyperaldosteronism | [NCT07007793](https://clinicaltrials.gov/study/NCT07007793) | **B** | med | Primary aldosteronism patients fall inside the broad 'hypertension not adequately controlled' label; a PA-specific claim incl. renin normalisation is new. |
| 9 | AZN | Tezspire | Asthma | [NCT07363642](https://clinicaltrials.gov/study/NCT07363642) | **C** | - | TAPER is single-arm descriptive step-down; no control, cannot establish the claim ARRIVAL is testing. |
| 10 | AZN | Tezspire | Rhinosinusitis | [NCT07520162](https://clinicaltrials.gov/study/NCT07520162) | **C** | - | BIFANG is a single-arm China descriptive study in the approved CRSwNP indication. |
| 11 | BAYN | Hyrnuo | Carcinoma, Non-Small-Cell Lung | [NCT06452277](https://clinicaltrials.gov/study/NCT06452277) | **B** | high | Hyrnuo indication carries no line-of-therapy limit and the label's efficacy population already includes treatment-naive Group F; SOHO-02 is the confirmatory trial for the accelerated approval. |
| 12 | BMY | Augtyro | Carcinoma, Non-Small-Cell Lung | [NCT06140836](https://clinicaltrials.gov/study/NCT06140836) | **B** | low | TKI-naive ROS1+ is inside the Augtyro indication; only lever is randomised confirmation vs crizotinib firming the guideline category. |
| 13 | BNTX | Comirnaty | COVID-19 | [NCT07798648](https://clinicaltrials.gov/study/NCT07798648) | **C** | - | Routine annual variant-adapted strain-change immunogenicity/safety study in the already-narrowed COVID label population. |
| 14 | GSK | Boostrix | Whooping Cough | [NCT07596199](https://clinicaltrials.gov/study/NCT07596199) | **C** | - | Japan immunogenicity bridging study; Boostrix already carries the third-trimester pregnancy indication. |
| 15 | GSK | Arexvy | Respiratory Syncytial Virus Infections | [NCT07092865](https://clinicaltrials.gov/study/NCT07092865) | **C** | - | Phase 2b open-label extension, descriptive GMTs in transplant recipients already covered by the 18-59 at-increased-risk indication. |
| 16 | GSK | PENMENVY | Pediatric meningococcal meningitis | [NCT05087056](https://clinicaltrials.gov/study/NCT05087056) | **B** | med | Approved schedule is 2 doses 6 months apart; trial tests 0/24-month and 0/48-month schedules - an ACIP-platform schedule change. |
| 17 | IONS | Dawnzera (Autoinjector) | Angioedemas, Hereditary | [NCT05392114](https://clinicaltrials.gov/study/NCT05392114) | **C** | - | Open-label long-term safety extension; primary endpoint is TEAEs. |
| 18 | IONS | Tryngolza (Autoinjector) | Hypertriglyceridemia | [NCT05681351](https://clinicaltrials.gov/study/NCT05681351) | **C** | - | Tryngolza label now includes sHTG (TG>=500 mg/dL); this is an in-label open-label extension. |
| 19 | IONS | Tryngolza (Autoinjector) | Familial hyperchylomicronemia syndrome | [NCT05185843](https://clinicaltrials.gov/study/NCT05185843) | **C** | - | Open-label safety study in FCS, the core approved indication; lab-abnormality primaries. |
| 20 | IONS | Tryngolza (Autoinjector) | Familial hyperchylomicronemia syndrome | [NCT05130450](https://clinicaltrials.gov/study/NCT05130450) | **C** | - | Open-label extension in FCS, the core approved indication. |
| 21 | JNJ | Rybrevant / Lazcluze | Carcinoma, Non-Small-Cell Lung | [NCT06120140](https://clinicaltrials.gov/study/NCT06120140) | **B** | med | In-label 1L EGFRm NSCLC; COCOON tests prophylactic dermatologic management of the rash that is amivantamab's main adoption barrier - label section 2.6 / supportive-care guidance. |
| 22 | JNJ | Rybrevant / Lazcluze | Carcinoma, Non-Small-Cell Lung | [NCT05498428](https://clinicaltrials.gov/study/NCT05498428) | **C** | - | SC amivantamab and Q4W dosing are both already approved (Rybrevant Faspro, eff. 2026-11-05); remaining cohorts sit inside existing indications. |
| 23 | JNJ | IMBRUVICA | Leukemia, Lymphocytic, Chronic, B-Cell | [NCT05963074](https://clinicaltrials.gov/study/NCT05963074) | **C** | - | Imbruvica's CLL/SLL indication is unqualified by regimen; TAILOR is a Phase 2 ORR study with no comparator. |
| 24 | KRYS | VYJUVEK | Epidermolysis Bullosa Dystrophica | [NCT07016750](https://clinicaltrials.gov/study/NCT07016750) | **A** | high | Vyjuvek label is 'for topical application on wounds only'; IOLITE is ophthalmic KB803 for corneal abrasions - a disjoint anatomical use needing its own pool. |
| 25 | LLY | Foundayo | Hypertension | [NCT06948422](https://clinicaltrials.gov/study/NCT06948422) | **C** | - | Master-protocol shell; primary endpoint is 'Number of Participants Allocated to Each ISA' - produces no interpretable efficacy readout. |
| 26 | LLY | Foundayo | Hypertension | [NCT06952530](https://clinicaltrials.gov/study/NCT06952530) | **B** | high | In-label obesity/overweight population; a systolic BP-lowering claim would be a new label claim for Foundayo. |
| 27 | LLY | Foundayo | Hypertension | [NCT06948435](https://clinicaltrials.gov/study/NCT06948435) | **B** | high | Second ATTAIN-HYPERTENSION ISA; same BP-lowering claim lever. |
| 28 | LLY | Foundayo | Urinary Incontinence, Stress | [NCT07202884](https://clinicaltrials.gov/study/NCT07202884) | **B** | med | BMI>=27 with SUI is inside the label; incontinence-episode-frequency would be a new claim in a large untreated female population. |
| 29 | LLY | Foundayo | Osteoarthritis | [NCT07153471](https://clinicaltrials.gov/study/NCT07153471) | **B** | med | BMI>=27 with knee OA is inside the label; a WOMAC pain claim would be new. |
| 30 | LLY | Foundayo | Peripheral Arterial Disease | [NCT07223593](https://clinicaltrials.gov/study/NCT07223593) | **A** | med | Label population is BMI>=30, or 27-<30 with a comorbidity; ATTAIN-PAD only excludes BMI<23, so the BMI 23-<27 PAD slice is outside the approved population. |
| 31 | MRK | Gardasil / Gardasil 9 | Papillomavirus Infections | [NCT04199689](https://clinicaltrials.gov/study/NCT04199689) | **B** | high | Gardasil 9's oropharyngeal/head-and-neck claim is under accelerated approval 'contingent upon verification ... in a confirmatory trial'; this oral-persistent-infection trial in men 20-45 is that trial. |
| 32 | MRK | Keytruda | Urinary Bladder Neoplasms | [NCT04241185](https://clinicaltrials.gov/study/NCT04241185) | **A** | high | Keytruda's bladder indications are BCG-unresponsive HR-NMIBC with CIS, and la/mUC with enfortumab; muscle-invasive bladder cancer treated with definitive chemoradiation is neither. |
| 33 | MRK | Belsomra | Sleep Initiation and Maintenance Disorders | [NCT06655883](https://clinicaltrials.gov/study/NCT06655883) | **C** | - | Belsomra's insomnia indication is unqualified by comorbidity; OUD patients with DSM-5 insomnia are squarely inside it. |
| 34 | MRK | Lipfendra | Hypercholesterolemia | [NCT07821944](https://clinicaltrials.gov/study/NCT07821944) | **C** | - | India regional registration study in the approved hypercholesterolaemia indication. |
| 35 | MRK | Gardasil / Gardasil 9 | Papillomavirus Infections | [NCT07785843](https://clinicaltrials.gov/study/NCT07785843) | **B** | med | Prior-2vHPV-vaccinated Chinese women are a cohort currently treated as non-candidates; the label only addresses prior-GARDASIL (4v) recipients (section 2.3). |
| 36 | MRK | Gardasil / Gardasil 9 | Papillomavirus Infections | [NCT03998254](https://clinicaltrials.gov/study/NCT03998254) | **C** | - | China post-approval confirmatory efficacy study; Gardasil 9 is already approved for females in this age range. |
| 37 | MRK | Keytruda | Urinary Bladder Neoplasms | [NCT03711032](https://clinicaltrials.gov/study/NCT03711032) | **A** | high | Label is BCG-UNRESPONSIVE HR-NMIBC with CIS; KEYNOTE-676 Cohort B is BCG-naive and Cohort A is persistent/recurrent after BCG induction - both outside. |
| 38 | MRK | Lipfendra | Hypercholesterolemia | [NCT06492291](https://clinicaltrials.gov/study/NCT06492291) | **C** | - | Open-label extension; primaries are AEs and discontinuations. |
| 39 | NVS | Leqvio | Cardiovascular Diseases | [NCT05030428](https://clinicaltrials.gov/study/NCT05030428) | **B** | high | Leqvio's label cites MACE benefit only for statins and PCSK9 mAbs; VICTORION-2P would give inclisiran its own cardiovascular outcomes claim. |
| 40 | NVS | Vanrafia | Glomerulonephritis, IGA | [NCT04573478](https://clinicaltrials.gov/study/NCT04573478) | **B** | high | Vanrafia is an accelerated approval on proteinuria; label states 'It has not been established whether VANRAFIA slows kidney function decline'. ALIGN's eGFR endpoint is the confirmatory readout. |
| 41 | PFE | Abrysvo | Respiratory Syncytial Virus Infections | [NCT05035212](https://clinicaltrials.gov/study/NCT05035212) | **B** | high | Abrysvo is labelled as a single dose with no revaccination guidance; RENOIR substudies A/B/C test Year 1-4 revaccination - the recurring-dose question for the adult RSV franchise. |
| 42 | PFE | Abrysvo | Respiratory Syncytial Virus Infections | [NCT07653100](https://clinicaltrials.gov/study/NCT07653100) | **C** | - | India descriptive safety/immunogenicity study in the approved adult indication. |
| 43 | PFE | Prevnar / Prevenar family | Pediatric pneumococcal infections | [NCT06524414](https://clinicaltrials.gov/study/NCT06524414) | **C** | - | Phase 2 dose/formulation-selection study; also an asset-mapping defect - PG4 is a new investigational PCV, not Prevnar 20. |
| 44 | PFE | Abrysvo | Respiratory Syncytial Virus Infections | [NCT07819097](https://clinicaltrials.gov/study/NCT07819097) | **C** | - | China/US descriptive safety and immunogenicity in the approved 60+ indication. |
| 45 | PFE | Prevnar / Prevenar family | Pneumococcal Infections | [NCT07794748](https://clinicaltrials.gov/study/NCT07794748) | **C** | - | Three-lot consistency study - a CMC enabler that cannot move claim, guideline or payer. Same PG4 asset-mapping defect. |
| 46 | PFE | Prevnar / Prevenar family | Pediatric pneumococcal infections | [NCT07660198](https://clinicaltrials.gov/study/NCT07660198) | **C** | - | Catch-up-regimen supportive cohort for PG4; same asset-mapping defect, and no claim change for the marketed Prevnar line. |
| 47 | PFE | Tukysa | Colorectal Neoplasms | [NCT05253651](https://clinicaltrials.gov/study/NCT05253651) | **A** | high | Tukysa CRC label requires progression after fluoropyrimidine-, oxaliplatin- and irinotecan-based chemo; MOUNTAINEER-03 excludes any prior systemic therapy for advanced disease. |
| 48 | PFE | Abrysvo | Respiratory Syncytial Virus Infections | [NCT07768345](https://clinicaltrials.gov/study/NCT07768345) | **B** | med | Stated purpose is 'to inform the revaccination interval'; label has no revaccination schedule. |
| 49 | PFE | Abrysvo | Respiratory Syncytial Virus Infections | [NCT06866405](https://clinicaltrials.gov/study/NCT06866405) | **B** | high | Randomised placebo-controlled second dose in a subsequent pregnancy; maternal label is a single dose at 32-36 weeks with no repeat-dose guidance. |
| 50 | PFE | Litfulo | Alopecia universalis | [NCT06873945](https://clinicaltrials.gov/study/NCT06873945) | **B** | high | Approved dosage is 50 mg once daily; ALLEGRO-100 tests 100 mg with dose-up for 50 mg non-responders - a dose/label change that recaptures failures. |
| 51 | RARE | Fayuvi | Mucopolysaccharidosis III | [NCT04360265](https://clinicaltrials.gov/study/NCT04360265) | **C** | - | Long-term follow-up of prior ABO-102/UX111 gene-therapy trials; safety/durability registry. |
| 52 | ROG | Alecensa | Carcinoma, Non-Small-Cell Lung | [NCT05170204](https://clinicaltrials.gov/study/NCT05170204) | **A** | high | Alecensa label is adjuvant-after-resection or metastatic; HORIZON-1 Cohort A1 is locally advanced UNRESECTABLE stage III - neither. |
| 53 | ROG | Xofluza | Influenza, Human | [NCT07827599](https://clinicaltrials.gov/study/NCT07827599) | **C** | - | China registration study; post-exposure prophylaxis is already in the Xofluza label for patients 5+. |
| 54 | ROG | Alecensa | Carcinoma, Non-Small-Cell Lung | [NCT03178552](https://clinicaltrials.gov/study/NCT03178552) | **C** | - | Multi-cohort blood-first platform; alectinib Cohort A sits inside the metastatic ALK+ indication and has already read out. |
| 55 | RVMD | Rasonque | Pancreatic Neoplasms | [NCT07491445](https://clinicaltrials.gov/study/NCT07491445) | **A** | high | Rasonque label requires >=1 prior systemic therapy OR not a candidate for multiagent therapy; RASolute 303 excludes prior systemic therapy and randomises against gem/nab-paclitaxel. |
| 56 | SNY | Wayrilz | Purpura, Thrombocytopenic, Idiopathic | [NCT07216079](https://clinicaltrials.gov/study/NCT07216079) | **C** | - | Open-label extension for 3 Japanese patients completing LUNA 3 LTE. |
| 57 | SNY | Wayrilz | Purpura, Thrombocytopenic, Idiopathic | [NCT07007962](https://clinicaltrials.gov/study/NCT07007962) | **?** | - | Cannot tell whether patients relapsing soon after first-line sit outside the label's 'persistent or chronic' ITP; registry record states no ITP-duration criterion. |
---

## 2. Bucket A — sub-population (8 rows)

Each of these enrols patients the approved label does not reach. They need their own
indication row and their own bottom-up pool; `base_pool_overlap_pct = 1.0` is wrong.

### A1. MRK Keytruda — KEYNOTE-676, high-risk NMIBC — NCT03711032 (row 37)

**Label** (KEYTRUDA, pembrolizumab, openFDA, effective_time 20261016) — the only NMIBC
indication:

> "KEYTRUDA, as a single agent, is indicated for the treatment of patients with Bacillus
> Calmette-Guerin (BCG)-unresponsive, high-risk, non-muscle invasive bladder cancer (NMIBC)
> with carcinoma in situ (CIS) with or without papillary tumors who are ineligible for or have
> elected not to undergo cystectomy."

The only other bladder indication is "in combination with enfortumab vedotin-ejfv, for the
treatment of adult patients with locally advanced or metastatic urothelial cancer."

**Trial** (NCT03711032), official title:

> "A Phase 3, Randomized, Comparator-controlled Clinical Trial to Study the Efficacy and Safety
> of Pembrolizumab (MK-3475) in Combination With Bacillus Calmette-Guerin (BCG) in Participants
> With High-risk Non-muscle Invasive Bladder Cancer (HR NMIBC) That is Either Persistent or
> Recurrent Following BCG Induction or That is Naïve to BCG Treatment (KEYNOTE-676)"

Arm labels: "BCG plus Pembrolizumab: Post-induction Cohort A (Arm A-1)", "BCG Monotherapy:
Post-induction Cohort A (Arm A-2)", "BCG plus Pembrolizumab: BCG Naïve Cohort B-Reduced
Maintenance (Arm B-1)", "BCG plus Pembrolizumab: BCG Naïve Cohort B-Full Maintenance (Arm B-2)",
"BCG Monotherapy: BCG Naïve Cohort B (Arm B-3)". N=1397.

**Disjoint.** Cohort B is BCG-naive by construction — patients who have never received BCG
cannot be BCG-unresponsive. Cohort A is "persistent or recurrent following BCG **induction**",
which is a weaker exposure than the adequate-BCG (induction plus maintenance) standard that
defines BCG-unresponsive disease. Neither cohort requires CIS, and neither requires
cystectomy-ineligibility. The combination partner also differs: the label is single-agent
pembrolizumab, the trial is pembrolizumab *plus* BCG. Both primaries (CRR in Cohort A,
EFS in Cohort B) read out outside the approved population.

### A2. MRK Keytruda — KEYNOTE-992, muscle-invasive bladder cancer — NCT04241185 (row 32)

**Label**: as quoted in A1 — BCG-unresponsive high-risk **non**-muscle-invasive disease, or
locally advanced/metastatic urothelial cancer with enfortumab vedotin.

**Trial** (NCT04241185), official title:

> "A Phase 3, Randomized, Double-blind, Placebo-controlled Clinical Trial to Study the Efficacy
> and Safety of Pembrolizumab (MK-3475) in Combination With Chemoradiotherapy (CRT) Versus CRT
> Alone in Participants With Muscle-invasive Bladder Cancer (MIBC) (KEYNOTE-992)"

Primary outcome: "Bladder Intact Event-Free Survival (BI-EFS)". N=520.

**Disjoint.** Muscle-invasive, non-metastatic disease managed with definitive chemoradiation
for bladder preservation is neither the NMIBC population nor the locally advanced/metastatic
population. The registry indexes it as "Urinary Bladder Neoplasms", which is why the book
collapsed it into the marketed line. This is a separate pool — MIBC patients opting for
trimodality therapy rather than cystectomy — and a separate pricing question.

### A3. PFE Tukysa — MOUNTAINEER-03, 1L HER2+ mCRC — NCT05253651 (row 47)

**Label** (TUKYSA, tucatinib, openFDA, effective_time 20261014):

> "TUKYSA is indicated in combination with trastuzumab for the treatment of adult patients with
> RAS wild-type, HER2-positive unresectable or metastatic colorectal cancer that has progressed
> following treatment with fluoropyrimidine-, oxaliplatin-, and irinotecan-based chemotherapy.
> This indication is approved under accelerated approval based on tumor response rate and
> durability of response."

**Trial** (NCT05253651), official title: "An Open-label Randomized Phase 3 Study of Tucatinib in
Combination With Trastuzumab and mFOLFOX6 Versus mFOLFOX6 Given With or Without Either Cetuximab
or Bevacizumab as **First-line** Treatment for Subjects With HER2+ Metastatic Colorectal Cancer".
Exclusion criterion:

> "Prior systemic anticancer therapy for colorectal cancer (CRC) in the locally advanced
> unresectable or metastatic setting; note that participants may have received a maximum of 2
> doses of mFOLFOX6 in the locally advanced/unresectable or metastatic setting prior to
> randomization."

**Disjoint.** The label requires progression after three chemotherapy backbones; the trial
excludes any prior systemic therapy for advanced disease. These are opposite ends of the
treatment sequence, and the 1L pool is roughly an order of magnitude larger than the
chemo-refractory pool currently in the revenue line.

### A4. RVMD Rasonque — RASolute 303, 1L metastatic PDAC — NCT07491445 (row 55)

**Label** (RASONQUE, daraxonrasib, openFDA, effective_time 20260827):

> "RASONQUE is indicated for the treatment of adult patients with metastatic pancreatic
> adenocarcinoma who have received at least one prior systemic therapy or who are not candidates
> for multiagent systemic therapy."

**Trial** (NCT07491445), inclusion and exclusion criteria:

> Inclusion: "Histologically or cytologically confirmed pancreatic adenocarcinoma." /
> "Diagnosis of metastatic disease ≤ 6 weeks prior to informed consent." /
> "Eastern Cooperative Oncology Group (ECOG) performance status of 0 or 1."
>
> Exclusion: "Prior treatment with systemic anticancer therapy in metastatic setting or prior
> RAS-targeted therapy in any treatment setting."

Arms: "Arm A: daraxonrasib", "Arm B: daraxonrasib + gemcitabine and nab-paclitaxel",
"Arm C: gemcitabine and nab-paclitaxel". N=900.

**Disjoint on both limbs of the indication.** Patients have had no prior systemic therapy, and
by being randomisable to gemcitabine plus nab-paclitaxel at ECOG 0-1 they are by definition
candidates for multiagent systemic therapy. Neither branch of the approved wording reaches them.

### A5. ROG Alecensa — HORIZON-1 Cohort A1, unresectable stage III — NCT05170204 (row 52)

**Label** (ALECENSA, alectinib, openFDA, effective_time 20260821):

> "ALECENSA is indicated as adjuvant treatment in adult patients following tumor resection of
> anaplastic lymphoma kinase (ALK)-positive non-small cell lung cancer (NSCLC) (tumors ≥ 4 cm or
> node positive), as detected by an FDA-approved test."
>
> "ALECENSA is indicated for the treatment of adult patients with ALK-positive metastatic NSCLC
> as detected by an FDA-approved test."

**Trial** (NCT05170204), brief summary:

> "This study will evaluate the efficacy and safety of multiple therapies in participants with
> locally advanced, **unresectable**, Stage III NSCLC with eligible biomarker status as determined
> by Version 8 of the American Joint Committee on Cancer/Union for International Cancer Control
> (AJCC/UICC) NSCLC staging system."

Relevant arms: "Cohort A1: Anaplastic Lymphoma Kinase (ALK)-positive (Alectinib Arm)" vs
"Cohort A1: ALK-positive (Durvalumab Arm)".

**Disjoint.** Unresectable stage III is, by definition, neither resected (so not the adjuvant
indication) nor metastatic (so not the metastatic indication). It is the gap between Alecensa's
two approved settings, and the comparator being durvalumab — the current stage III standard —
confirms the setting. Its own pool.

### A6. KRYS Vyjuvek — IOLITE, ocular DEB — NCT07016750 (row 24)

**Label** (VYJUVEK, beremagene geperpavec-svdt, openFDA, effective_time 20250929):

> Indication: "VYJUVEK is indicated for the treatment of **wounds** in adult and pediatric patients
> with dystrophic epidermolysis bullosa (DEB) with mutation(s) in the collagen type VII alpha 1
> chain (COL7A1) gene."
>
> Dosage: "For topical application on **wounds only**. ... Apply VYJUVEK gel to the selected wound(s)
> in droplets spaced evenly within the wound, approximately 1cm-by-1cm apart."

**Trial** (NCT07016750), official title: "A Double-Blind Crossover of **KB803** and Matched Placebo for
the Treatment and Prevention of **Corneal Abrasions** in Dystrophic Epidermolysis Bullosa". Inclusion:

> "Confirmed diagnosis of DEB with a mutation in the COL7A1 gene." /
> "Meets minimum corneal abrasion symptom frequency in the NHS study."

Primary: "To evaluate the effect of **ophthalmic** KB803 on frequency of corneal abrasion symptoms."

**Disjoint use, overlapping patients.** This is the one A where the *people* largely overlap —
they are DEB patients, many already on Vyjuvek for skin wounds — but the treated manifestation,
the route and the product are all different: an ophthalmic formulation (KB803) applied to the
ocular surface, not a topical gel applied to cutaneous wounds. It will carry its own approval,
its own price and its own dosing frequency, so it needs its own pool sized on DEB patients with
recurrent corneal abrasions. Pricing it at zero on skin-wound overlap double-counts nothing —
it simply omits a product.

### A7. LLY Foundayo — ATTAIN-PAD — NCT07223593 (row 30)

**Label** (FOUNDAYO, orforglipron, openFDA, effective_time 20260729):

> "FOUNDAYO is indicated in combination with a reduced-calorie diet and increased physical
> activity to reduce excess body weight and maintain weight reduction long term in adults with
> obesity or adults with overweight in the presence of at least one weight-related comorbid
> condition."

The label defines those terms numerically in Clinical Studies:

> "Trial 1 (NCT05869903) was a 72-week trial that enrolled 3,127 adult patients with obesity
> (BMI ≥30 kg/m2), or with overweight (BMI 27 to <30 kg/m2) and at least one weight-related
> comorbid condition."

**Trial** (NCT07223593) — the complete inclusion criteria are:

> "Have symptomatic PAD with intermittent claudication of Fontaine Stage II" /
> "Have an Ankle Brachial Index (ABI) of 0.9 or less"

and the only weight-related criterion is an **exclusion**:

> "Have a body mass index (BMI) less than 23 kilogram per square meter (kg/m2)"

**Partly disjoint.** Unlike every other ATTAIN study on this list, ATTAIN-PAD has no obesity or
overweight entry requirement — not in the title, not in the inclusion criteria. It enrols from
BMI 23 upwards, so the BMI 23 to <27 band is outside the approved population entirely. Size the
new pool on that band of symptomatic Fontaine II PAD patients; the BMI ≥27 remainder is in the base
and should be treated as a bucket-B claim question alongside rows 26-29.

### A8. AZN Enhertu — DESTINY-PanTumor02, pancreatic — NCT04482309 (row 5)

**Label** (ENHERTU, fam-trastuzumab deruxtecan-nxki, openFDA, effective_time 20260515) — the
pan-tumour indication that would otherwise cover pancreatic cancer:

> "HER2-Positive (**IHC 3+**) Unresectable or Metastatic Solid Tumors — as monotherapy for the
> treatment of adult patients with unresectable or metastatic HER2-positive (IHC 3+) solid tumors
> who have received prior systemic treatment and have no satisfactory alternative treatment
> options. ... approved under accelerated approval based on objective response rate and duration
> of response."

**Trial** (NCT04482309), inclusion criteria:

> "Part 1: The respective cohorts for patient inclusion are: ... Cohort 6: Pancreatic cancer" /
> "HER2 expression scored using current ASCO/CAP guidelines ... **Part 1: IHC 3+ or IHC 2+** by local
> or central assessment" /
> "Part 2 ... Cohort B: Metastatic or advanced solid tumors that are HER2 **IHC 2+/ISH+** any tumor
> type (excluding breast, gastric cancer, and colorectal cancer)."

**Partly disjoint.** The approved pan-tumour indication is restricted to IHC 3+; the trial enrols
IHC 2+ alongside IHC 3+. The IHC 3+ pancreatic patients are genuinely in the base. The IHC 2+
pancreatic patients are not reachable under any current Enhertu indication, and HER2 IHC 2+ is a
materially larger share of pancreatic adenocarcinoma than IHC 3+. The pool to build is the IHC 2+
slice only — this is the row most at risk of being over-sized if someone prices the whole cohort.

---

## 3. Bucket B — scenario (21 rows)

Patients are inside the approved population. What a win changes is the claim, the guideline
position, the payer position, or the dosing. No revenue figures below — only the lever.

### High conviction (11 rows)

**B1. ABBV Ubrelvy — menstrual migraine prevention — NCT06417775 (row 0).**
What moves: **the label claim**, from acute-only to preventive. The Ubrelvy label (openFDA,
effective_time 20260929) carries an explicit Limitations of Use:

> "UBRELVY is indicated for the acute treatment of migraine with or without aura in adults.
> **Limitations of Use: UBRELVY is not indicated for the preventive treatment of migraine.**"

The trial (NCT06417775) is titled "...to Evaluate the Efficacy, Safety, and Tolerability of
Ubrogepant for the **Preventive** Treatment of Menstrual Migraine", enrolling women with "at least
a 1-year history of migraine", "migraine attacks in at least 2 of 3 perimenstrual periods" and
"less than 15 headache days per month", with primary endpoint "Change From Baseline in Number of
Migraine Days Occurring During Perimenstrual Periods".
*Note for the model:* the overlap flag is right that these are the same people, but it is wrong
that the revenue double-counts. Preventive use is scheduled dosing layered on top of existing
PRN acute use in the same patient — additive units, not a reallocation. This row is arguably
the single most mis-specified zero on the list.

**B2. BAYN Hyrnuo — SOHO-02, 1L HER2-mutant NSCLC — NCT06452277 (row 11).**
What moves: **conversion of an accelerated approval to full approval, and the 1L standard of care.**
The Hyrnuo label (openFDA, effective_time 20260917) states:

> "HYRNUO is indicated for the treatment of adult patients with locally advanced or metastatic
> non-squamous non-small cell lung cancer (NSCLC) whose tumors have HER2 (ERBB2) tyrosine kinase
> domain (TKD) activating mutations ... This indication is approved under accelerated approval
> based on objective response rate (ORR) and duration of response (DOR). **Continued approval for
> this indication may be contingent upon verification and description of clinical benefit in a
> confirmatory trial.**"

Critically, the indication carries **no line-of-therapy restriction**, and the label's own efficacy
population already includes untreated patients: "Treatment Naïve: Group F — Efficacy was evaluated
in 69 patients ... who have not received prior systemic therapy." So SOHO-02 — which excludes
"prior systemic therapy for locally advanced or metastatic disease" and randomises against
platinum-doublet plus pembrolizumab — is *not* a new population. It is the confirmatory trial, and
a PFS win would displace chemo-IO as the 1L standard for HER2-mutant NSCLC.

**B3. NVS Leqvio — VICTORION-2 PREVENT — NCT05030428 (row 39).**
What moves: **a cardiovascular outcomes claim of its own, plus guideline and payer position.**
The Leqvio label (openFDA, effective_time 20260819) is explicit that the MACE evidence belongs
to other drug classes:

> "LEQVIO is indicated as an adjunct to diet and exercise to reduce low-density lipoprotein
> cholesterol (LDL-C) in: adults with hypercholesterolemia. ... **Cardiovascular outcomes trials
> have demonstrated that reducing LDL-C lowers the risk for major adverse cardiovascular events
> (MACE) in adults at increased risk when treated with statins or monoclonal antibody proprotein
> convertase subtilisin kexin type 9 (PCSK9) inhibitors as an add-on to statin therapy.**"

The trial (NCT05030428, N=17,004) has primary outcome "Time to First Occurrence of 3P-MACE
(3-Point Major Adverse Cardiovascular Events)" in "Atherosclerotic Cardiovascular Disease". The
patients are already in the label; what is missing is inclisiran's own outcomes claim, which is
what payers have been withholding broad access on.

**B4. NVS Vanrafia — ALIGN — NCT04573478 (row 40).**
What moves: **conversion of an accelerated approval to full approval on a hard renal endpoint.**
The Vanrafia label (openFDA, effective_time 20260612):

> "VANRAFIA is indicated to reduce proteinuria in adults with primary immunoglobulin A nephropathy
> (IgAN) at risk of rapid disease progression, generally a urine protein-to-creatinine ratio (UPCR)
> ≥ 1.5 g/g. This indication is approved under accelerated approval based on a reduction of
> proteinuria. **It has not been established whether VANRAFIA slows kidney function decline in
> patients with IgAN.** Continued approval for this indication may be contingent upon verification
> and description of clinical benefit in a confirmatory clinical trial."

ALIGN (NCT04573478) is that trial: "A Phase 3, Randomized, Double-blind, Placebo-controlled Study
of Atrasentan in Patients With IgA Nephropathy at Risk of Progressive Loss of Renal Function",
with the eGFR readout dated 2028-04. Same patients; the claim moves from surrogate to outcome.

**B5. MRK Gardasil 9 — oral persistent infection in men — NCT04199689 (row 31).**
What moves: **conversion of the accelerated-approval oropharyngeal/head-and-neck claim.**
The Gardasil 9 label (DailyMed SPL a21f4f4b-b891-4f25-b747-cb9ec7d865d6):

> "GARDASIL 9 is indicated in boys and men 9 through 45 years of age for the prevention of the
> following diseases: Anal, **oropharyngeal and other head and neck cancers** caused by HPV types 16,
> 18, 31, 33, 45, 52, and 58. ... **The oropharyngeal and head and neck cancer indication is approved
> under accelerated approval based on effectiveness in preventing HPV-related anogenital disease.
> Continued approval for this indication may be contingent upon verification and description of
> clinical benefit in a confirmatory trial.**"

The trial (NCT04199689, N=6,033) is titled "...to Study the Efficacy, Immunogenicity, and Safety of
the 9vHPV Vaccine ... in the Prevention of **Oral** Persistent Infection With HPV Types 16, 18, 31, 33,
45, 52, or 58 in Adult Males, 20 to 45 Years of Age", with primary outcome "Incidence of HPV
16/18/31/33/45/52/58-related 6-month Persistent Oral Infection". Men 20-45 are inside the approved
9-through-45 age range, so the population is in the base; the confirmatory readout is the catalyst.

**B6. PFE Abrysvo — RENOIR revaccination substudies — NCT05035212 (row 41).**
What moves: **the dosing schedule — one-and-done versus recurring.**
The Abrysvo label (DailyMed SPL be18292e-b1a2-4815-a0ed-003efaa6bea3) gives only:

> "Active immunization for the prevention of LRTD caused by RSV in individuals 60 years of age and
> older." / "2.1 Dose and Schedule — After reconstitution, **a single dose** of ABRYSVO is either 0.5 mL
> ... or approximately 0.5 mL."

There is no revaccination schedule anywhere in the label. RENOIR's substudies are exactly that
question — arms include "SSA: Vaccination of RSVpreF recipients with RSVpreF (Year 2 revaccination)",
"SSB: ... (Year 1 revaccination)", "SSC: ... (Year 3 revaccination)" and "(Year 4 revaccination)",
each with a placebo comparator. Whether the adult RSV franchise is a one-time or a repeating
purchase is the dominant variable in its growth rate, and it is currently unresolved in the label.

**B7. PFE Abrysvo — revaccination in subsequent pregnancies — NCT06866405 (row 49).**
What moves: **the maternal dosing schedule.** Label:

> "ABRYSVO is a vaccine indicated for active immunization of pregnant individuals at 32 through 36
> weeks gestational age for the prevention of lower respiratory tract disease (LRTD) and severe LRTD
> caused by respiratory syncytial virus (RSV) in infants from birth through 6 months of age."

Again a single dose, with nothing about a later pregnancy. The trial (NCT06866405, N=550,
randomised, quadruple-masked, RSVpreF vs placebo) is titled "A Phase 3 Study to Investigate the
Safety, Tolerability, and Immunogenicity of **Revaccinating Pregnant Participants During Subsequent
Pregnancies** and Persistence of Immunity of a Single Dose of a Bivalent Respiratory Syncytial Virus
(RSV) Vaccine." A positive result converts the maternal indication from one dose per woman to one
dose per pregnancy.

**B8/B9. LLY Foundayo — ATTAIN-HYPERTENSION ISAs — NCT06952530, NCT06948435 (rows 26, 27).**
What moves: **a blood-pressure-lowering claim.** The Foundayo label (openFDA, effective_time
20260729) is a weight-reduction claim only:

> "FOUNDAYO is indicated in combination with a reduced-calorie diet and increased physical activity
> to reduce excess body weight and maintain weight reduction long term in adults with obesity or
> adults with overweight in the presence of at least one weight-related comorbid condition."

The master protocol's entry criteria (NCT06948422, which these two ISAs refer to for screening
eligibility) are "Has systolic blood pressure (SBP) ≥ 140 mmHg and/or diastolic blood pressure (DBP)
≥ 90 mmHg ..." and "Have a body mass index (BMI) ≥ 25 kg/m²"; both ISAs have primary outcome "Change
from Baseline in office Systolic Blood Pressure (SBP)". Hypertension is a weight-related comorbid
condition, so the BMI ≥27 patients are in the base; what a win adds is an antihypertensive claim.
*Minor caveat:* BMI 25 to <27 is below the label's "overweight (BMI 27 to <30)" band, so a thin
slice of these trials is also out-of-label.

**B10. AZN Calquence — MAJIC — NCT05057494 (row 7).** *(moved to high conviction on the strength
of the head-to-head design)*
What moves: **guideline preference between two in-label regimens.** The Calquence label (openFDA,
effective_time 20260219) is unqualified as to regimen: "CALQUENCE is indicated for the treatment of
adult patients with chronic lymphocytic leukemia (CLL) or small lymphocytic lymphoma (SLL)." MAJIC
(NCT05057494, N=607) is "A Phase III Prospective, Multicenter, Randomized, Open-Label Trial of
**Acalabrutinib Plus Venetoclax Versus Venetoclax Plus Obinutuzumab** in Previously Untreated Chronic
Lymphocytic Leukemia or Small Lymphocytic Lymphoma", primary endpoint PFS. Both regimens are
already available to these patients; the readout decides which one NCCN and prescribers default to
in 1L, and therefore how the fixed-duration 1L CLL pool splits between AbbVie/Roche and AstraZeneca.

**B11. PFE Litfulo — ALLEGRO-100 — NCT06873945 (row 50).**
What moves: **the approved dose, and recapture of 50 mg non-responders.** The Litfulo label
(openFDA, effective_time 20260617):

> Indication: "LITFULO is a kinase inhibitor indicated for the treatment of severe alopecia areata in
> adults and adolescents 12 years and older."
> Dosage: "**Recommended dosage is 50 mg orally once daily.**"

The trial (NCT06873945) brief summary states: "Ritlecitinib is approved in many countries at a dose
of 50 mg ... This study will look at both the 50 mg dose and a **100 mg** dose", and the design is
"...RANDOMIZED STUDY WITH **DOSE-UP FOR NON-RESPONDERS**", with arms "Ritlecitinib 50 mg" and
"Ritlecitinib 100 mg" and re-randomisation at Week 24 by SALT ≤20 response status. Patients are
in-label; a win adds a higher dose that retains patients who currently discontinue after failing
50 mg, and lengthens duration of therapy.

### Medium conviction (8 rows)

**B12. AZN Baxfendy — BaxPA, primary aldosteronism — NCT07007793 (row 8).**
What moves: **a disease-specific claim (including renin normalisation) and Endocrine Society
guideline position.** The Baxfendy label (openFDA, effective_time 20260807) is a broad
blood-pressure claim: "BAXFENDY, in combination with other antihypertensive drugs, is indicated for
the treatment of hypertension, to lower blood pressure in adults who are not adequately controlled
on other agents." BaxPA enrols "Participants with a documented diagnosis of PA that fulfils the
criteria defined in the 2016 or 2025 Endocrine Society Guidelines" with "Mean seated SBP on AOBPM
of ≥ 135 mmHg and ≤ 170 mmHg" on "a stable regimen of antihypertensive medications" — i.e. inside
the approved wording. What is new is the second primary endpoint, "Achieving normalization of renin
at week 8 in participants with dysregulated renin at baseline": a biochemical, disease-specific
claim in a diagnosed population where MRAs are the entrenched standard.

**B13. ABBV Venclexta — ramp-up optimisation — NCT06428019 (row 1).**
What moves: **Dosage and Administration (label section 2), and the monitoring burden that gates
adoption.** The Venclexta label (openFDA, effective_time 20260520) indication is unqualified:
"VENCLEXTA is indicated for the treatment of adult patients with chronic lymphocytic leukemia (CLL)
or small lymphocytic lymphoma (SLL)." The trial (NCT06428019) is titled "...to Evaluate the Risk of
TLS and Optimization of the Initiation of Venetoclax in Combination With Obinutuzumab or
Acalabrutinib With **Different Ramp-Up Periods** in Previously Untreated Subjects With CLL", enrolling
"previously untreated, chronic lymphocytic leukemia (CLL) requiring treatment according to the 2018
... (iwCLL) criteria", with primaries "Percentage of Participants with Treatment-Emergent Laboratory
Tumor Lysis Syndrome (TLS)" and "Percentage of Participants with Hyperkalemia". Same patients; a
shorter ramp-up removes the hospitalisation/monitoring friction that is the documented reason
community prescribers reach for a BTKi instead.

**B14. GSK PENMENVY — alternative dosing schedules — NCT05087056 (row 16).**
What moves: **the vaccination schedule, and with it alignment to the routine adolescent platform.**
The Penmenvy label (DailyMed SPL 6b2c9ee3-ae88-46f1-9b3f-fc9e9e716cbf):

> "PENMENVY is a vaccine indicated for active immunization to prevent invasive disease caused by
> Neisseria meningitidis serogroups A, B, C, W, and Y in individuals 10 through 25 years of age."
> "2.1 Dose and Schedule — Administer **2 doses** (approximately 0.5 mL each) of PENMENVY **6 months
> apart**."

The trial (NCT05087056) enrols "A male or female between, and including, 11 and 14 years of age"
— inside the approved range — but tests: "ABCWY-24 Group: Participants receive 2 doses of the
MenABCWY vaccine at Day 1 and **Day 721**" and "ABCWY-48 Group: ... at Day 1 and **Day 1441**", i.e.
0/24-month and 0/48-month schedules against the approved 0/6-month. The 0/48-month arm maps onto
the existing 11-12 and 16-year adolescent visits, which is the schedule that determines whether
MenABCWY displaces separate MenACWY and MenB courses.

**B15. JNJ Rybrevant/Lazcluze — COCOON — NCT06120140 (row 21).**
What moves: **supportive-care guidance in label section 2.6 and NCCN, and therefore persistence.**
The Rybrevant label (openFDA, effective_time 20251111) already instructs "Administer prophylactic
and concomitant medications as recommended to reduce the risk of dermatologic adverse reactions.
(2.6)", and the trial population — "locally advanced or metastatic stage IIIB/C-IV EGFR-mutated
NSCLC treated first-line with amivantamab and lazertinib" — is squarely the approved 1L indication
("in combination with lazertinib for the first-line treatment of adult patients with locally
advanced or metastatic NSCLC with EGFR exon 19 deletions or exon 21 L858R substitution mutations").
The primary outcome is "Number of Participants With Grade ≥2 Dermatologic Adverse Events of Interest
Within 12 Weeks". This is not a patient-pool question at all — it is whether the regimen's rash
burden, the single most-cited barrier to MARIPOSA adoption, can be managed down. That changes the
share of eligible patients who start and stay on the regimen.

**B16/B17. LLY Foundayo — RESTRAIN-SUI, ATTAIN-OA PAIN — NCT07202884, NCT07153471 (rows 28, 29).**
What moves: **new symptom claims in the approved obesity population.** Both require "a body mass
index (BMI) of 27 kilograms per square meter (kg/m2) or higher at screening" — inside the label's
obesity/overweight-with-comorbidity population — plus "a diagnosis of stress urinary incontinence"
(NCT07202884, primary "Change from Baseline in Incontinence Episode Frequency") or "osteoarthritis
of the knee" (NCT07153471, primary "Change from Baseline in the Western Ontario and McMaster
Universities Osteoarthritis Index (WOMAC) Pain Subscale Score"). Neither symptom claim exists in the
Foundayo label today. These are the Wegovy-style comorbidity claims that drive payer coverage
beyond cosmetic-weight framing.

**B18. MRK Gardasil 9 — prior bivalent-HPV recipients in China — NCT07785843 (row 35).**
What moves: **whether an already-vaccinated cohort becomes addressable.** The Gardasil 9 label
addresses prior vaccination only for the 4-valent predecessor — "2.3 Administration of GARDASIL 9 in
Individuals Who Have Been Previously Vaccinated with GARDASIL — Safety and immunogenicity were
assessed in individuals who completed a three-dose vaccination series with GARDASIL 9 and had
previously completed a three-dose vaccination series with GARDASIL" — and nothing about prior
**bivalent** vaccine recipients. The trial (NCT07785843) randomises "Prior 2vHPV Vaccine Recipients
Receiving V503" against "Prior 2vHPV Vaccine Recipients Receiving Placebo", with primary outcome
"Percentage of Participants Who Are Seropositive by cLIA to HPV Types 6, 11, 31, 33, 45, 52, and 58
(Month 7)" — i.e. the seven types the bivalent vaccine does not cover. Chinese females 10-45 are
inside the approved age range, so this is a base-population row; what moves is whether the large
cohort already vaccinated with a bivalent product is recommendable for 9-valent vaccination.
*Caveat:* the operative label here is the NMPA's, which I could not reach within the no-paid-sources
constraint. Graded medium on the US label structure plus the trial design alone.

**B19. PFE Abrysvo — revaccination interval in immunocompromised adults — NCT07768345 (row 48).**
What moves: **the revaccination interval.** Same labelled gap as B6/B7 (single dose, no
revaccination schedule). The trial's own brief summary states the purpose directly: "to learn the
safety, tolerability and immunogenicity of revaccination with RSVpreF at approximately 1-, 2-, and
3-year intervals **to inform the revaccination interval** in immunocompromised adults", with
participants "grouped based on prior RSV vaccination history". Immunocompromised adults 18+ are
already covered by the "18 through 59 years of age who are at increased risk" indication, so this is
in-base; the schedule is the lever. Graded medium rather than high because the design is open-label,
non-randomised and descriptive.

### Low conviction (2 rows) — recommend heavy discount or leaving at zero

**B20. AZN Tezspire — ARRIVAL — NCT06473779 (row 6).**
What moves: **a steroid-sparing positioning claim.** The Tezspire label (openFDA, effective_time
20251017) reads "TEZSPIRE is indicated for the **add-on maintenance** treatment of adult and pediatric
patients aged 12 years and older with severe asthma" — the trial tests whether that background
maintenance can be reduced: "A Multicentre, Randomised, Open-Label, Parallel-Group, Phase IIIb Study
to Assess the Potential for Tezepelumab-treated Patients With Severe Asthma to **Reduce Background
Therapy** While Sustaining Asthma Control and Clinical Remission", primary "Proportion of patients who
reduced their SYMBICORT daily maintenance dose without the loss of asthma control". The precedent
for an OCS-sparing claim in the biologics class is real, but an ICS step-down claim is a
differentiation message rather than something that changes the number of patients treated or the
price, and the study is open-label Phase IIIb. Honest answer: close to C.

**B21. BMY Augtyro — TRIDENT-3 — NCT06140836 (row 12).**
What moves: **the strength of the guideline recommendation, nothing else.** The Augtyro label
(openFDA, effective_time 20240613) already covers the trial population without a line restriction:
"AUGTYRO is indicated for the treatment of adult patients with locally advanced or metastatic ROS1-
positive non-small cell lung cancer (NSCLC)", and that indication is a full approval, not an
accelerated one. TRIDENT-3 is "Randomized, Open-label, Multicenter, Phase 3 Trial of Repotrectinib
Versus Crizotinib in Participants With ... TKI-naïve ROS1-positive NSCLC", primary PFS by BICR. A win
converts single-arm evidence into randomised superiority over a comparator that is already largely
displaced. Honest answer: this is nearly C, and I would not pay much for it.

---

## 4. Bucket C — correctly nil (28 rows)

Grouped by kind of study. These are inside the approved population and cannot plausibly move
the claim, the guideline or the payer position. Zero is the right answer for all of them.

**Open-label extensions and long-term follow-up (8).** NCT04280718 (Vyvgart, ADHERE+ CIDP OLE),
NCT05392114 (Dawnzera HAE OLE), NCT05681351 (Tryngolza sHTG OLE), NCT05185843 and NCT05130450
(Tryngolza FCS open-label studies), NCT06492291 (Lipfendra hypercholesterolaemia OLE),
NCT07216079 (Wayrilz Japan OLE, N=3), NCT04360265 (Fayuvi MPS IIIA long-term follow-up of prior
ABO-102/UX111 trial participants). Every one has adverse events or laboratory abnormalities as its
primary outcome and no control arm; they are post-approval safety obligations. Two deserve a
specific note: Tryngolza's label was expanded to cover sHTG ("To reduce TG and the risk of acute
pancreatitis in adults with severe hypertriglyceridemia (sHTG: TG greater than or equal to 500
mg/dL)", effective_time 20260703), so NCT05681351 is now plainly in-label; and Fayuvi was approved
in October 2026 for "the treatment of neurologic manifestations of mucopolysaccharidosis type IIIA
... in pediatric patients with preserved neurodevelopmental function", making NCT04360265 a
durability registry.

**Geographic / regional registration and bridging studies (7).** NCT07520162 (Tezspire BIFANG,
China CRSwNP), NCT07596199 (Boostrix, Japanese pregnant women), NCT07821944 (Lipfendra, India),
NCT03998254 and NCT07653100 (Gardasil 9 China confirmatory; Abrysvo India), NCT07819097 (Abrysvo
China/US 60+), NCT07827599 (Xofluza China post-exposure prophylaxis). In each case the claim being
sought already exists on the US label — for Xofluza explicitly: "XOFLUZA is indicated for
post-exposure prophylaxis of influenza in persons 5 years of age and older following contact with
an individual who has influenza" (effective_time 20260424). These expand geography, not the claim.
If the book's base pool is global, they are correctly nil; if the base pool is US-only, the
geographic question is a separate modelling decision and not a sub-population one.

**Phase 3b/4 and single-arm descriptive evidence generation (5).** NCT06706817 (Tezspire ESSENCE,
"Single-Arm, Phase 3b Study to Assess Changes in Symptoms"), NCT07363642 (Tezspire TAPER,
single-arm step-down — the same question ARRIVAL tests, but with no control arm, so it cannot
establish the claim), NCT05963074 (Imbruvica TAILOR, Phase 2 ORR, no comparator, against an
unqualified "adult patients with chronic lymphocytic leukemia (CLL)/small lymphocytic lymphoma
(SLL)" indication), NCT03178552 (Alecensa B-FAST — multi-cohort blood-first platform whose
alectinib cohort sits inside the metastatic ALK+ indication and has already reported),
NCT05498428 (Rybrevant PALOMA-2 — note both of its convenience levers are now already approved:
Rybrevant Faspro, effective_time 20261105, is labelled "For subcutaneous use only" with an
"Every 4 weeks starting at Week 5 onwards" regimen).

**Vaccine immunogenicity and lot-consistency studies (5).** NCT07798648
(Comirnaty variant-adapted strain change — routine annual update, and its cohorts "with risk
factors" and "≥65 Years" match the already-narrowed label), NCT07092865 (Arexvy Phase 2b extension
in transplant recipients — descriptive GMTs in a group already covered by the "18 through 59 years
of age who are at increased risk" indication), NCT07794748 (PG4 three-lot consistency), NCT06524414
(PG4 Phase 2 formulation/solution comparison in infants), NCT07660198 (PG4 catch-up regimen in
children and adolescents). Note the contrast with NCT07768345, the fourth Abrysvo study, which is
*not* in this group: its stated purpose is to set a revaccination interval the label does not
contain, which is why it sits in bucket B (B19).

**In-label population, no achievable claim change (3).** NCT04804553 (Otezla PEAPOD — the label now
reads "OTEZLA is indicated for the treatment of adult patients and pediatric patients 6 years of age
and older and weighing at least 20 kg with active psoriatic arthritis", effective_time 20260902, so
the trial's 5-to-<18 population is in-label apart from a negligible 5-to-<6 sliver), NCT06655883
(Belsomra in opioid use disorder — "BELSOMRA is indicated for the treatment of insomnia
characterized by difficulties with sleep onset and/or sleep maintenance" is unqualified by
comorbidity, and the trial requires "Meets DSM-5 criteria for the diagnosis of Insomnia Disorder";
a win adds Clinical Studies data but no indication, guideline or coverage change), NCT06948422
(ATTAIN-HYPERTENSION master protocol — primary outcome "Number of Participants Allocated to Each
ISA", which is an allocation record, not a readout).

---

## 5. Could not determine (1 row)

**SNY Wayrilz — LUNA 4 — NCT07007962 (row 57).**
The Wayrilz label (openFDA, effective_time 20250826) reads: "WAYRILZ is indicated for the treatment
of adult patients with **persistent or chronic** immune thrombocytopenia (ITP) who have had an
insufficient response to a previous treatment." The ITP phase terms are time-defined — newly
diagnosed is 0-3 months from diagnosis, persistent 3-12 months, chronic beyond 12 months.

The trial is "A Multi-center, Open-label, Single-arm Study to Evaluate the Efficacy and Safety of
Oral Rilzabrutinib in Adults With Immune Thrombocytopenia (ITP) Who **Failed First-line Treatment**",
whose brief summary describes the intent as "**early** multi-immune modulation with rilzabrutinib in
adult ITP patients who failed first-line treatment". Its inclusion criteria are: "a documented
diagnosis of primary ITP in the medical history" / "Participant received at least one course of
first-line therapy and had a history of response while on treatment" / "Participant has loss of
response, relapse, or steroid dependency", with "Participant received advanced therapy for ITP or
was splenectomized" excluded.

**What is missing:** the registry record states **no ITP-duration criterion**. A patient who relapses
two months after a first corticosteroid course is still in the newly-diagnosed phase and would sit
outside "persistent or chronic" — which would make this a bucket A sub-population row, and a
commercially meaningful one, since it would move rilzabrutinib ahead of TPO-RAs. A patient who
relapses at month eight is inside the label, which would make it bucket C (single-arm, N=60, no
achievable claim change). The two readings imply opposite answers and the registry cannot separate
them. **To resolve:** check the LUNA 4 protocol or statistical analysis plan for a minimum
time-since-diagnosis criterion, or Sanofi's trial disclosure for the enrolled population's median
ITP duration.

---

## 6. Sources

- ClinicalTrials.gov API v2, `https://clinicaltrials.gov/api/v2/studies/{NCT}`, all 58 records
  retrieved 2026-11-11.
- openFDA drug label API, `https://api.fda.gov/drug/label.json`, retrieved 2026-11-11. Label
  `effective_time` is given inline with each quote.
- DailyMed SPL service (`https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.xml`) for
  the CBER vaccine products, which are not carried in the openFDA drug label endpoint: Gardasil 9
  (a21f4f4b-b891-4f25-b747-cb9ec7d865d6), Abrysvo (be18292e-b1a2-4815-a0ed-003efaa6bea3), Penmenvy
  (6b2c9ee3-ae88-46f1-9b3f-fc9e9e716cbf), Arexvy (1e50f275-002e-413f-a840-66ee3cb3740c), Boostrix
  (cd98bff9-4602-4268-d68d-029a14a5513b), Prevnar 20 (d4e2cf51-e6a8-4103-bb1d-6120c6474ff8).
- No figure in this document is an estimate. No revenue, pool size or probability is asserted
  anywhere; every row's verdict rests on a label quote and a registry quote only.
