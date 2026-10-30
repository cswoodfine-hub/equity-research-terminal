# Step 6: the value gate

Run 2026-10-29. Every asset with assumptions (639, marketed and pipeline), valued under
main's code and data files (`origin/main` 4012abe) and under this branch's
(`claude/lucid-johnson-p41rox`), on two copies of the book:

- main's copy holds the Purple Book floors as main's fetcher writes them;
- the branch's copy has them as the fixed fetcher writes them, simulated, since this
  environment cannot reach the Purple Book host.

The two copies are otherwise identical. Reproduce with:

```
ER_TOOL_DB=<main copy>   python3 work/patents/tools/gate.py <main worktree>/backend main.json
ER_TOOL_DB=<branch copy> python3 work/patents/tools/gate.py backend branch.json
python3 work/patents/tools/gate_report.py main.json branch.json
```

## Result

Risk-adjusted value, all companies: **3,092,859mm on main, 3,049,937mm on the branch,
-42,922mm (-1.39%)**. The same 8 assets fail to build on both sides, all for missing
seeds, so nothing new breaks.

By cause, each asset counted once, under the first cause it matches in this order:
US date, route row, regional date, erosion refit. An asset counted under a date also
carries its refit.

| cause | assets | change, mm | largest |
|---|---|---|---|
| erosion rows refit (option B: oral 0.71/0.31/0.23, biologic 0.25/0.25) | 180 | -63,143 | Eliquis -5,040, Skyrizi -2,935, Darzalex -2,655 |
| regional dates (EU SPC cap) | 6 | -6,746 | Rinvoq -4,425, Venclexta -1,313, Evrysdi -618 |
| US dates (filer rows, recorded launches, the floor fix) | 17 | +5,616 | Actemra +5,311, Keytruda +4,552, Tremfya +3,797 |
| the non-oral row (injected and inhaled small molecules) | 37 | +21,351 | Wegovy +8,087, Ozempic +6,987, Mounjaro +2,451 |

By company:

| company | main | branch | change |
|---|---|---|---|
| ABBV | 254,391 | 243,038 | -11,353 (-4.5%) |
| BMY | 113,026 | 104,009 | -9,017 (-8.0%) |
| AZN | 157,831 | 149,533 | -8,298 (-5.3%) |
| NVS | 163,081 | 157,004 | -6,077 (-3.7%) |
| GILD | 87,103 | 82,918 | -4,185 (-4.8%) |
| JNJ | 231,921 | 227,792 | -4,130 (-1.8%) |
| PFE | 106,798 | 103,422 | -3,376 (-3.2%) |
| VRTX | 69,533 | 66,354 | -3,179 (-4.6%) |
| AMGN | 119,340 | 116,463 | -2,876 (-2.4%) |
| GSK | 62,853 | 60,435 | -2,418 (-3.8%) |
| REGN | 49,359 | 47,972 | -1,386 (-2.8%) |
| BAYN | 25,194 | 24,282 | -912 (-3.6%) |
| AXSM | 5,719 | 4,969 | -751 (-13.1%) |
| ARGX | 25,156 | 24,537 | -620 (-2.5%) |
| SNY | 66,186 | 65,674 | -513 (-0.8%) |
| INCY | 7,353 | 6,877 | -476 (-6.5%) |
| BIIB | 19,569 | 19,363 | -206 (-1.1%) |
| RARE | 1,466 | 1,424 | -43 (-2.9%) |
| KRYS | 1,840 | 1,801 | -39 (-2.1%) |
| UTHR | 10,083 | 10,061 | -23 (-0.2%) |
| SRPT | 446 | 479 | +34 (+7.5%) |
| IONS | 3,113 | 3,239 | +126 (+4.1%) |
| LLY | 297,185 | 297,452 | +267 (+0.1%) |
| ROG | 122,480 | 124,070 | +1,590 (+1.3%) |
| MRK | 184,272 | 186,304 | +2,032 (+1.1%) |
| NVO | 892,297 | 905,204 | +12,907 (+1.4%) |

## The 53 assets moving more than 10%, reviewed

| BMY Eliquis | 27,251 | 22,211 | -5,040 (-18%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AZN Farxiga | 8,647 | 6,654 | -1,993 (-23%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| GSK Nucala | 4,057 | 2,262 | -1,795 (-44%) | LOE 2031 to 2027; biologic row refit (0.25/0.2 to 0.25/0.25) |
| NVS Entresto | 5,893 | 4,120 | -1,773 (-30%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| PFE Vyndaqel | 4,651 | 3,304 | -1,347 (-29%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ABBV Vraylar | 10,959 | 9,638 | -1,322 (-12%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ABBV Venclexta | 10,998 | 9,685 | -1,313 (-12%) | small molecule row refit (0.6/0.35 to 0.71/0.31); region INTL 2031 |
| AZN Saphnelo | 4,609 | 3,320 | -1,289 (-28%) | LOE 2038 to 2033; biologic row refit (0.25/0.2 to 0.25/0.25); region EM 2033, ROW 2033 |
| JNJ Xarelto | 2,096 | 1,176 | -920 (-44%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| NVS Tasigna | 2,123 | 1,266 | -858 (-40%) | LOE None to 2025; loss no longer in base; basis: generic marketed (2025-05-23, FDA Paragraph IV list); erosion None to small molecule |
| AXSM Auvelity | 4,663 | 3,815 | -848 (-18%) | LOE 2043 to 2038; basis: Axsome 10-K, settled generic entry (2038-09-30); small molecule row refit (0.6/0.35 to 0.71/0.31) |
| JNJ Opsumit | 2,573 | 1,867 | -706 (-27%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AZN Lynparza | 3,897 | 3,222 | -675 (-17%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| BMY Cobenfy | 4,388 | 3,750 | -637 (-15%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| PFE Ibrance | 3,660 | 3,055 | -605 (-17%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| GSK Dovato | 3,411 | 2,877 | -534 (-16%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| INCY Jakafi | 3,368 | 2,857 | -511 (-15%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| LLY Jardiance | 4,667 | 4,172 | -495 (-11%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| MRK Prevymis | 3,637 | 3,212 | -425 (-12%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| MRK Lenvima | 3,650 | 3,234 | -416 (-11%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| BMY Yervoy | 2,481 | 2,103 | -378 (-15%) | biologic row refit (0.25/0.2 to 0.25/0.25) |
| MRK Idvynso | 2,263 | 1,900 | -363 (-16%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ABBV Linzess | 2,719 | 2,371 | -349 (-13%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AMGN Otezla | 2,918 | 2,587 | -331 (-11%) | basis: Amgen 10-K, U.S. compound patent with pediatric exclusivity ; small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AMGN Lumakras | 2,669 | 2,391 | -278 (-10%) | LOE 2040 to 2038; basis: Amgen 10-K, U.S. compounds patent (2038-05-21); small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AMGN Krystexxa | 2,062 | 1,787 | -275 (-13%) | biologic row refit (0.25/0.2 to 0.25/0.25) |
| BMY Pomalyst | 2,424 | 2,156 | -268 (-11%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| PFE Xtandi | 1,567 | 1,303 | -264 (-17%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ROG Kadcyla | 1,382 | 1,167 | -215 (-16%) | biologic row refit (0.25/0.2 to 0.25/0.25) |
| AZN Koselugo | 1,319 | 1,145 | -174 (-13%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ROG Gazyva | 959 | 785 | -174 (-18%) | biologic row refit (0.25/0.2 to 0.25/0.25) |
| GSK Tivicay | 1,085 | 942 | -143 (-13%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| UTHR Orenitram | 750 | 609 | -141 (-19%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| MRK Zerbaxa | 1,324 | 1,186 | -138 (-10%) | erosion small molecule to small molecule, non-oral route; region INTL 2030 |
| PFE Xeljanz | 743 | 609 | -133 (-18%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AZN Baxfendy | 870 | 750 | -120 (-14%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| BAYN Adempas | 277 | 200 | -77 (-28%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| PFE Cresemba | 154 | 86 | -68 (-44%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| GSK Juluca | 516 | 449 | -67 (-13%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AZN Soliris | 508 | 450 | -58 (-11%) | biologic row refit (0.25/0.2 to 0.25/0.25) |
| PFE Bosulif | 240 | 189 | -51 (-21%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| GSK Triumeq | 481 | 431 | -50 (-10%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| AZN Brilinta | 130 | 82 | -48 (-37%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| ROG Erivedge | 350 | 304 | -46 (-13%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| PFE Talzenna | 344 | 301 | -43 (-12%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| MRK Dificid | 49 | 13 | -36 (-73%) | LOE 2027 to 2025; basis: Merck 10-K, U.S. loss of exclusivity (2025-07); small molecule row refit (0.6/0.35 to 0.71/0.31); region INTL 2025 |
| GSK Rukobia | 197 | 173 | -23 (-12%) | small molecule row refit (0.6/0.35 to 0.71/0.31) |
| SNY Jevtana Kit | 94 | 113 | +19 (+20%) | erosion small molecule to small molecule, non-oral route |
| UTHR Tyvaso | 556 | 620 | +64 (+11%) | erosion small molecule to small molecule, non-oral route |
| AXSM Sunosi | 956 | 1,054 | +98 (+10%) | LOE 2038 to 2040; basis: Axsome 10-K, settled generic entry (2040-03-01); small molecule row refit (0.6/0.35 to 0.71/0.31) |
| GSK Trelegy Ellipta | 2,554 | 2,815 | +262 (+10%) | erosion small molecule to small molecule, non-oral route |
| JNJ Tremfya | 20,679 | 24,476 | +3,797 (+18%) | LOE 2029 to 2031; basis: J&J 10-K, U.S. composition patent (2031); biologic row refit (0.25/0.2 to 0.25/0.25); region INTL 2031 |
| ROG Actemra | 1,415 | 6,726 | +5,311 (+375%) | LOE 2025 to 2022; loss now in base; erosion biologic to None; region EU 2022, JP 2022, ROW 2022 |

### Review

- **38 move on the erosion refit alone**, agreed as option B (`EROSION_3B.md`). The
  rows are fitted to the average launch, so the oral row cuts deeper in year one (0.71)
  and slower later (0.23 from year four). The largest are oral products whose cliff
  falls inside the window: Eliquis, Farxiga, Entresto, Vyndaqel, Xarelto.
- **The non-oral row raises three inhaled or injected products:** Trelegy, Tyvaso and
  Jevtana. It is fitted to 28 launches (interquartile range 0.26 to 0.78) and chosen by
  the Orange Book route of the asset's own application.
- **Dates, each traced in its own record:**
  - Nucala and Saphnelo: the first-licensure floor (`FILER_DATES.md`).
  - Tremfya, Auvelity, Otezla, Lumakras, Sunosi and Dificid: filer rows, each quoted.
  - Tasigna: a generic recorded on the Paragraph IV list on 2025-05-23.
  - Venclexta and Zerbaxa: the EU SPC cap (`REGIONAL.md`).
- **Actemra, +375%, flagged.**
  - The corrected floor (2022) puts its loss in the base, so the branch applies no
    erosion. Revenue falls 7% a year from the reported 2,470mm, fading to flat at about
    1,991mm by 2030.
  - Main dated the loss 2025 and cut the full first-year biosimilar drop again, though US
    and EU biosimilars launched in 2024 and FY2025 already carries a year of them.
  - Both are wrong in part. Main counts the first year twice; the branch stops eroding a
    biologic that is only two years into its biosimilar competition.
  - The book holds no Actemra revenue before FY2025, so the fall so far cannot be
    measured here.

## Agreed

2026-10-29, by Charles: the gate is accepted and the branch merges as it stands.
Actemra stays flagged here. "A recent loss keeps eroding" is the follow-up: a loss in
the base that is younger than its erosion row's run would keep decaying from the year it
began. It touches every product whose loss passed in the last few years, so it gets its
own measured delta.

## Follow-up: does a recent loss keep eroding? Measured, and no

Tested 2026-10-29 with `work/patents/tools/decline_backtest.py`. The test takes each year a
product's series fell after its loss had passed, projects it forward three ways, and
compares with the reported level:

- **fade:** today's rule, the rate fading to zero over five years;
- **hold:** the rate held, capped at the erosion row's decay for that many years past
  the loss;
- **curve:** the erosion row's own decay for that many years past the loss.

The filer series are too short (33 events), so the test runs on CMS Medicare spending,
Part D and Part B, 2013 on. That is gross and Medicare only, but long.

| events | horizon | fade, median / median abs | hold | curve |
|---|---|---|---|---|
| all 186 | 1 year (n 132) | -0.009 / 0.105 | +0.005 / 0.104 | -0.141 / 0.196 |
| all 186 | 2 years (n 87) | -0.005 / 0.160 | -0.025 / 0.224 | -0.284 / 0.410 |
| all 186 | 3 years (n 49) | -0.003 / 0.269 | -0.034 / 0.408 | -0.372 / 0.644 |
| within 3 years of the loss, 35 | 1 year (n 28) | +0.009 / 0.141 | +0.105 / 0.170 | +0.092 / 0.180 |
| within 3 years of the loss, 35 | 2 years (n 19) | +0.046 / 0.219 | +0.113 / 0.312 | +0.113 / 0.397 |
| within 3 years of the loss, 35 | 3 years (n 11) | +0.253 / 0.269 | +0.222 / 0.248 | +0.222 / 0.707 |

Errors are the log of projected over reported; negative over-predicts the fall.

- The fade is unbiased and the most accurate at every horizon on all events.
- The erosion curve suits a fresh cliff, not a line already past one: it over-predicts
  the fall by about a third at three years.
- Within three years of a loss, all three under-predict the fall. The fade is best or
  tied at one and two years; at three years there are 11 events, too few to choose.

So the rule built to hold Actemra's decline (39 assets, -47,416mm on a copy) is not kept,
and Actemra stays on the merged treatment, which is the best measured of the three.

## Agreed, second round (2026-10-30)

Both value changes made since the first merge are accepted and merge with the branch:

| change | value | basis |
|---|---|---|
| Roche's biosimilar entries from its 2025 Finance Report | -19,422mm (Xolair -15,120, Perjeta -4,302) | `data/disclosed_loe.csv`, `disclosed_loe_regions.csv`; FILER_DATES.md |
| Japan's re-examination floor from the PMDA list | +9mm (Gazyva's Japanese line from 2026) | REGIONAL.md, "Japan: the re-examination floor" |

The IRA bear case and the use-code wording are display only and move no value. The
Phase 2 safety gradient (work/proxies/RESULTS_8D_8E.md) stays a display; no cut to the
Phase 2 probability was taken.
