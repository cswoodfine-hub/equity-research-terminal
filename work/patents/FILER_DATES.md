# Filer-stated US dates: re-read for every valued product without a row

Run 2026-10-29, after Keytruda was found valued on its 12-year floor (2026-09-04) while
Merck's 10-K states December 2028. The 2026-09-16 pass wrote a row only where the filer's
date differed from the one the model then held; the date rules have changed since, so
agreement then is not agreement now.

## Method

1. **Candidates.** Every marketed product with a forecast and no row in
   `data/disclosed_loe.csv`: 252 of 372, 1.77tn of the book's 2.61tn NPV. 221 belong to
   the 22 SEC filers.
2. **Filings.** Each filer's latest annual report from EDGAR, all FY2025 and filed in
   2026 (`tools/filer_dates/get_annual.py`).
3. **Reading.** Five agents read the filings in parallel against a fixed brief
   (`tools/filer_dates/BRIEF.md`): the molecule's date only, a settled entry date over
   the patent, pending extensions flagged and not resolved, every quote verbatim.
4. **Checks** (`tools/filer_dates/verify.py`, then by hand):
   - every quote was found in its filing;
   - each stated date was compared with the model's at the precision the filer
     states: a year against the model's year, a month or a day against its date.

Every finding, with its quote, is in `filer_dates_2026-10-29.json`.

## Result

| outcome | products |
|---|---|
| filing states nothing for the US | 102 |
| agrees with the model | 42 |
| same year as the model (a table year against an exact Orange Book date) | 40 |
| differs | 26 |
| "expired" or lost, with no year | 4 |
| a range of years the text cannot resolve (AstraZeneca) | 7 |

### Rows added (11)

| product | model before | filer | NPV, mm |
|---|---|---|---|
| Tremfya (JNJ) | 2029-07-13, 12-year floor | 2031, composition patent | 19,136 to 24,476 |
| Alyftrek (VRTX) | 2040-08-13, latest substance patent | 2039, basic product patent | 28,412 to 26,842 |
| Auvelity (AXSM) | 2043-11-28 | 2038-09-30, Teva settlement | 4,581 to 3,815 |
| Lumakras (AMGN) | 2040-05-20, a crystalline form | 2038-05-21, compounds patent | 2,602 to 2,391 |
| Sunosi (AXSM) | 2038-11-01 | 2040-03-01, Hikma settlement | 896 to 1,054 |
| Dificid (MRK) | 2027-07-31 | lost July 2025 | 44 to 13 |
| Bridion (MRK) | 2026-01-27 | 2026-07-27, pediatric exclusivity | unchanged |
| Otezla (AMGN) | 2028-02-16 | 2028-08-16, pediatric exclusivity | unchanged |
| Sarclisa (SNY) | 2032-03-02 | 2032-10, compound with PTA and PTE | unchanged |
| Mozobil (SNY) | no date | 2023, generic competition | unchanged |
| Symdeko (VRTX) | 2031-07-10 | 2027, basic product patent | no forecast value |

+2,921mm across the book on a copy. A date that stays inside the same year moves
nothing, since the engine works in years.

Alyftrek and Lumakras show the substance rule's known failing: the Orange Book flags a
crystal form as "drug substance", and the latest one is not the molecule.

### Not taken, and why

- **Pending or estimated extensions:**
  - Ozempic and Wegovy: Novo's 2032 includes estimated extensions; the USPTO certificate
    takes the semaglutide compound patent to 2031-12-05, the model's date.
  - Pluvicto, Welireg, Jemperli, Wayrilz, Exdensur, Nexviazyme.
  - Omvoh: Lilly does not say which of its extensions are granted.
- **Ungranted pediatric exclusivity:** Rinvoq. Its April 2037 assumes pediatric
  exclusivity; without it, entry falls at about the model's 2036-10-17.
- **A biologic compound patent ending inside its 12 years:** Evenity, Arexvy, Tecartus,
  Nexviazyme.
- **Not US-approved:** Awiqli. 2037 is Novo's estimate of data protection.
- **"Expired" without saying generics or biosimilars are on the US market:**
  - Lutathera: orphan exclusivity only.
  - Benlysta and Toujeo: compound patent expired, no biosimilar named.
  - Breo Ellipta: a Paragraph IV trial is set for November 2026.
- **AstraZeneca ranges:**
  - Products: Saphnelo, Lokelma, Fasenra, Wainua, FluMist, Beyfortus, and Nucala (GSK).
  - The 20-F marks molecule patents in bold and other patents in italics, and that
    formatting is lost in text. Reading those needs the HTML.
- **Jevtana:** generics are on the market, but no US entry date is given.

## Not covered

- **Roche and Bayer** are not SEC registrants: 31 valued products without a row.
- **Formatting lost in the text:**
  - AstraZeneca's and GSK's bold and italics, as above.
  - The first-listed AstraZeneca year was read as the molecule's. The rows where that
    already agrees with the model rest on that reading.
- **Next season:** rerun when the FY2026 reports file.
  1. `get_annual.py <dir> TICKER:CIK ...`
  2. `snippets.py`
  3. The brief.
  4. `verify.py`.
