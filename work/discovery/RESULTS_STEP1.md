# Discovery step 1: the feasibility backtest

Run 2026-11-13. Tools: `work/discovery/tools/corpus.py`, `outcomes.py`, `backtest.py`.

## Verdict

- **Clinical translation: a day-one score matches the published baseline, and does not
  beat it.** Words and rule flags from the title and abstract rank papers about as well
  as NIH iCite's `apt`, which has the advantage of seeing citations since publication.
- **Company formation: the day-one score is the only one with signal, and it is weak.**
  iCite's score is no better than chance at it. Ours lifts the top tenth about 2.5 to 3
  times over the base rate.
- **Who wrote it says more than what it says.** The strongest commercial flags are an
  author who already holds a small-business award and an equity interest declared in
  the paper. Content flags (model reached, dose, biodistribution) carry little.

So a single "commercial score" on publication day is not worth building on this
evidence. The watchlist that accumulates footprints after publication is.

## What was tested

- **Papers.** 20,725 CGT research papers and preprints first published 2017 to 2020,
  from Europe PMC by title and abstract terms; 18,947 have an iCite record.
- **Split.** Trained on 2017 and 2018, scored on 2019 and 2020.
- **Features, all knowable on the day:** the words of the title and abstract; 18 rule
  flags (model reached, CGT de-risking terms); a company among the affiliations; an
  author already holding a small-business award; conflict-of-interest phrases. MeSH
  terms are not used, since they are assigned months later.
- **Outcomes within three years:**
  - cited by a clinical article (iCite);
  - an author at a US address named as investigator on a later NIH small-business
    award (SBIR or STTR) about gene or cell therapy (RePORTER, 25,098 awards 2012 to
    2024).

## Results

"Hit" is the share of the top slice that had the outcome; the multiple is against the
base rate.

**Cited by a clinical article within three years**

| Papers | Events, base rate | Score | AUC | Top 1% | Top 5% | Top 10% |
|---|---|---|---|---|---|---|
| All (10,611) | 939, 8.8% | rules + words | 0.848 | 81%, 9.2x | 60%, 6.8x | 45%, 5.1x |
| | | iCite `apt` | 0.854 | 78%, 8.8x | 51%, 5.7x | 44%, 4.9x |
| Not themselves clinical (7,734) | 308, 4.0% | rules + words | 0.760 | 34%, 8.5x | 21%, 5.2x | 14%, 3.6x |
| | | iCite `apt` | 0.792 | 39%, 9.8x | 25%, 6.2x | 18%, 4.5x |

**An author on a later CGT small-business award (papers with a US author)**

| Papers | Events, base rate | Score | AUC | Top 1% | Top 5% | Top 10% |
|---|---|---|---|---|---|---|
| Any later award (3,352) | 129, 3.8% | rules + words | 0.742 | 18%, 4.6x | 10%, 2.5x | 12%, 3.0x |
| | | iCite `apt` | 0.508 | 3%, 0.8x | 4%, 0.9x | 3%, 0.9x |
| The author's first award (3,352) | 85, 2.5% | words | 0.626 | 18%, 7.0x | 9%, 3.5x | 6%, 2.4x |
| | | rules + words | 0.606 | 6%, 2.3x | 7%, 2.6x | 5%, 2.1x |
| First award, academic papers only (2,494) | 49, 2.0% | rules + words | 0.651 | 4%, 2.0x | 6%, 2.9x | 5%, 2.7x |
| | | iCite `apt` | 0.535 | 0% | 2%, 1.2x | 3%, 1.4x |

The top 1% of 2,494 papers is 25 papers, so those cells move by four points per paper.

Strongest rule flags for a later award: prior award +0.46, number of authors +0.34,
declared equity +0.23, "platform" +0.21. For a clinical citation among papers that are
not clinical: number of authors, primate, mouse, a patent in the interests statement.

## What went wrong on the way, and the fix

- **Name matching.** The first award outcome matched on first and last name alone. Of 574
  matches, 301 were authors outside the US, mostly sharing a common name with a US
  investigator. The match now needs the author's own address on the paper to be in the
  US: 197 matches, 100 people. Of 14 read by hand, about 11 are clearly the same person
  (three UNC authors and Bedrock Therapeutics; Yang Liu and OncoImmune; a Berkeley author
  and Catena Biosciences); two or three common names remain doubtful.
- **Award topic.** "Vector", "stem cell" and "T cell" alone let unrelated awards through;
  the topic test now needs a CGT term.

## Limits

- **US only for the company outcome.** CORDIS project files carry no investigator
  names, so they cannot give a person-level outcome. The UK route is Companies House
  control data (2.7 GB, not yet read). The HESA register blocks scripts.
- **A small-business award is one footprint.** Patents, Form D filings and licences are
  not in the outcome yet, so company formation is undercounted.
- **Preprints fall out of the award study:** Europe PMC gives them no per-author address.
- **Few events.** 49 to 129 in the award studies, so the lifts are rough.
- **Conflict-of-interest text exists for 7,685 of 20,807 papers** in PubMed's field.
- **iCite's score reads today's record,** so it is a harder baseline than a day-one score
  would face.

## What this says to build

1. **The watchlist, not a point score.** Rank the feed by the clinical-translation score,
   which works, and attach footprints as they appear.
2. **People and labs as first-class objects.** A senior author's record (prior awards,
   companies, patents) is the strongest commercial signal found.
3. **More outcomes before any commercial score is shown:** patents by inventor match,
   Form D, Companies House. Then retest.
4. **Embeddings** in place of word counts, once a key or a local model is available.
