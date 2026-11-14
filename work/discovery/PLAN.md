# Discovery: early-stage research, scored for translation and commercial relevance

Status, 2026-11-13: sources verified and the feasibility backtest run three times
(`RESULTS_STEP1.md`): with SEC Form D and UK Companies House added as company outcomes,
then with OpenAlex author records, which let lab heads be ranked as people. A day-one score matches iCite for clinical translation. For company activity
the authors' record carries the signal (42% of papers by a prior Form D officer lead to
another filing, against 5%), and first-time founders stay hard to rank. So the thing to
build is a ranked feed plus a watchlist of people and labs, not a commercial score. No
app code yet.

## What it is

A section for a VC reader. It takes in every new cell and gene therapy (CGT) paper and
preprint, scores each on evidence the paper itself states, and then watches it: a paper
"lights up" when commercial footprints accumulate around it (a grant to a small business,
a patent, a trial, a new company). Scope: CGT first; US, UK and Europe.

Volume (Europe PMC counts, 2026-11-13): 9,878 CGT papers and 1,708 CGT preprints first
published in 2025, about 32 a day. Small enough for rules and free model tiers.

## Rules it keeps

- The score works with no model key. Rules and a classical model do the ranking; a model
  only extracts facts from a shortlist, and every fact carries a verbatim quote that the
  code checks against the text.
- Nothing is fabricated: a field the paper does not state is null.
- Nothing ships before the backtest says the score beats the baseline.

## Sources, as verified on 2026-11-13

| Source | Host | State | Notes |
|---|---|---|---|
| Europe PMC search | www.ebi.ac.uk | works, keyless | Papers and preprints in one index; `resultType=core` gives abstract, authors, affiliations, MeSH, grants. The `MESH:` field does not exist; use `KW:` or `TITLE_ABS:` |
| Europe PMC annotations | www.ebi.ac.uk | works, keyless | Text-mined genes, diseases, organisms |
| PubTator3 | www.ncbi.nlm.nih.gov | works, keyless | Entities per PMID, BioC JSON |
| PubMed E-utilities | eutils.ncbi.nlm.nih.gov | works, keyless | `<CoiStatement>` is its own field |
| PMC open access (BioC) | www.ncbi.nlm.nih.gov | works, keyless | Full text; a commercial-use subset exists |
| bioRxiv and medRxiv API | api.biorxiv.org | works, keyless | 30 rows a page (not 100). `details` gives licence, category, corresponding institution, JATS link, published DOI; `pubs` links preprint to paper |
| NIH iCite | icite.od.nih.gov | works, keyless | `apt` (potential to translate), `cited_by_clin`, human/animal/molecular shares. The baseline |
| NIH RePORTER | api.reporter.nih.gov | works, keyless | POST search; SBIR and STTR by activity code (R41 to R44), PI names, organisation |
| UKRI Gateway to Research | gtr.ukri.org | works, keyless | Includes Innovate UK awards to companies |
| CORDIS | cordis.europa.eu | works, keyless | Bulk project files (H2020, Horizon Europe) |
| Companies House bulk | download.companieshouse.gov.uk | works, keyless | Company snapshot and persons with significant control (33 files of about 82 MB). A university's tech transfer arm as a controlling party marks a spinout |
| ClinicalTrials.gov | clinicaltrials.gov | works, keyless | Already in the terminal |
| FDA orphan designations | www.accessdata.fda.gov | page answers | Search form; not yet read |
| EMA orphan designations | www.ema.europa.eu | answers, rate limited | Listed among the EMA's medicine data reports |
| SEC EDGAR | www.sec.gov | 403 without an identifier | Needs `SEC_USER_AGENT`, which is unset in this environment |
| OpenAlex | api.openalex.org | needs a free key | Keyless calls now share one daily budget per IP, and it was spent. A key is requested by email |
| Semantic Scholar | api.semanticscholar.org | 429 keyless | Free key by form, for embeddings and summaries |
| SBIR.gov API | api.www.sbir.gov | 403 from the service | RePORTER covers the NIH part of SBIR and STTR |
| HESA spin-out register | www.hesa.ac.uk | bot challenge | Not readable by script; Companies House control data is the route |
| Reliance on Science | zenodo.org | works, 1.4 GB | Patent to paper citations. **CC BY-NC 4.0: non-commercial**, so not for a product |
| Europe PMC patents | www.ebi.ac.uk | gone | `SRC:PAT` returns nothing |

Not yet probed (hosts not allowed here): Open Targets, Orphadata, ORCID, CIRM, the Cell and
Gene Therapy Catapult, Crossref, PatentsView.

## Open decisions

1. **Patent label.** Reliance on Science is non-commercial. The clean route is inventor
   and author matching on USPTO data, which is public domain but needs a free USPTO key
   (`api.uspto.gov`, sent as `X-Api-Key`). Not set up, so patents are not in the
   backtest.
2. **OpenAlex key.** Active from 2026-11-13, $1 of free use a day; the whole corpus cost
   under 15 cents. It is in the backtest (author identifiers, preprint addresses, the
   senior author's prior output). Semantic Scholar's is still open and not needed.
3. **SEC identifier** for Form D: agreed 2026-11-13, and the outcome is in the backtest.
4. **Companies House API key** (free). The bulk files give owners of 25% or more only;
   the API gives directors, which is where a diluted academic founder shows.

## Step 1: the feasibility backtest

- **Corpus.** CGT papers and preprints first published 2017 to 2020 (about 20,500 and
  1,900), from Europe PMC, by title and abstract terms.
- **Outcomes, within three years of publication, each from a free source:**
  - cited by a clinical article (iCite);
  - an SBIR or STTR award whose PI is an author (RePORTER), US;
  - a biotech Form D naming an author as officer or director (SEC data sets), US;
  - a new UK research company an author controls (Companies House bulk files), UK;
  - not done: an Innovate UK or EU company grant naming an author (CORDIS carries no
    investigator names), and a patent (needs the USPTO key).
- **Score, from what was knowable on publication day:** rule features (model ladder from
  species tags, CGT terms such as vg/kg, NHP, neutralising antibodies, off-target
  analysis; conflict-of-interest phrases) plus a word-frequency model, trained on 2017
  and 2018 and tested on 2019 and 2020.
- **Baseline to beat:** iCite's `apt`.
- **Measure:** the share of outcomes captured in the top 1%, 5% and 10% against the base
  rate. Base rates are low, so the top of the list is what is judged.
- **Bias, stated:** name matching misses renamed or licensed-out work; grants and trials
  are the visible outcomes, not every commercial one.

Stop after the report. The section is built only if the top of the list beats the baseline.

Outcome: it does for company activity and ties for clinical translation. See
`RESULTS_STEP1.md` for what that supports building and what it does not.

## Step 2: the Discovery tab (front end)

Prototype, on real backtest output: https://claude.ai/artifact/Johy1LTTuLw5hirdYdQeVP
(source in `work/discovery/prototype/`). It shows the section as it would have stood on
31 December 2020, with what happened in the next three years beside each row.

**Where it sits.** A top-level tab, "Discovery", beside Universe and Themes on the cell
and gene engine. It is about the sector, not the selected ticker, so it ignores the
company picker the way Universe does. A module of its own (`frontend/discovery_view.py`),
drawn with the existing tokens and `theme.py`; no new colour.

**Four views.**

| View | The question it answers | Main parts |
|---|---|---|
| Labs (opens first) | Who should I be watching? | Ranked lab heads; what they work on; furthest model reached; interests declared in their papers; company records to date; score. A row opens to a timeline of papers and records, and their papers. |
| Papers | What came out, and what is closest to patients? | Ranked by translation or company score, or newest; the model ladder (human cells, mouse, large animal, primate, patients); six de-risking flags; the authors' record. |
| Lit up | What changed for the labs I watch? | A dated feed: a new Form D, award or company naming a watched or top-ranked lab head. Feeds the terminal's What changed too. |
| How good is it | Can I trust the ranking? | The backtest: what the top 5% held against the base rate and a plain count, and what the sources cannot see. |

**Rules for the copy.**

- Every company record says how it was matched ("by name and state, not verified") and
  links to its source: the SEC filing, the RePORTER project, the Companies House page.
- A paper with no US or UK author shows "not scored" for company, never a blank or zero.
- A score is shown as a rank ("top 2%"), never as a probability or a made-up number.
- No list is called "first-time founders" until patents and UK directors are in.
- House style: sentence case, no em dashes, the number or the change first.

**What it needs from the back end.** Five reads, each a plain table behind it.

| Read | Returns |
|---|---|
| `/discovery/labs` | ranked lab heads, filtered by modality, country, record, text |
| `/discovery/labs/{id}` | one lab head: papers, records, timeline |
| `/discovery/papers` | scored papers, filtered and sorted |
| `/discovery/events` | new records since a date, for the feed |
| `/discovery/method` | the backtest figures the fourth view draws |

Tables: `discovery_papers`, `discovery_people`, `discovery_paper_people`,
`discovery_records` (kind, date, name as filed, source link, how matched),
`discovery_scores` (with the model version), `discovery_watch` (pinned labs),
`discovery_record_overrides` (a match marked wrong, the same pattern as
`trial_asset_map`).

**Order of work.**

1. **F1, read-only on the backtest snapshot.** Load the prototype's data into the
   tables, add the five reads, build Labs, Papers and How good is it in the app. No
   fetcher yet. This settles the layout in the real terminal.
2. **F2, live.** A daily fetcher for new papers and preprints (Europe PMC by date,
   OpenAlex for authors), a weekly one for records (Form D, RePORTER, Companies House).
   Snapshots and diffs as every other source, so Lit up is the change feed. "New this
   week" becomes the opening filter on Papers.
3. **F3, watchlist.** Pin a lab; pinned labs lead the Labs view and their records reach
   What changed. Mark a record as the wrong person.
4. **F4, the VC layer.** For a lab or paper: likely buyers and comparable deals from
   the terminal's own deal and pipeline tables; the quote behind each flag, read by the
   model where a key is present and left out where not.

**Decisions to agree before F1.**

1. Labs opens first, not Papers (the backtest says the lab ranking is the stronger one).
2. The tab shows on the cell and gene engine only, or on every engine.
3. The opening state of Labs once live: the whole ranking, or labs with something new
   in the last 30 days.
4. Whether "what happened next" stays as a backtest toggle in the live section, for
   showing how the ranking held up, or lives only on How good is it.

## Later steps

5. Patents by inventor (USPTO key) and UK directors (Companies House key), then retest
   and decide on a first-time founder list.
6. Europe: a person-level company source for the continent, if a free one is found.
7. Embeddings in place of word counts.
