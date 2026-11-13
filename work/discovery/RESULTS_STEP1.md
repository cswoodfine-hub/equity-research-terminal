# Discovery step 1: the feasibility backtest

Run 2026-11-13, three times: first with one company outcome (NIH small-business awards),
then with SEC Form D and UK Companies House added, then with OpenAlex author records. Tools: `work/discovery/tools/corpus.py`,
`outcomes.py`, `backtest.py`.

## Verdict

- **Clinical translation: a day-one score matches the published baseline, and does not
  beat it.** Words and rule flags from the title and abstract rank papers about as well
  as NIH iCite's `apt`, which has the advantage of seeing citations since publication.
- **Company activity: a day-one score works when it knows the authors' record.** With
  three company outcomes joined, 51% of the top twentieth had an author in a later
  company record, against a base rate of 10.8% (4.7 times). iCite's score manages 1.6
  times, the same as counting authors.
- **Who wrote it says more than what it says.** 42% of US papers with an author already
  named on a biotech Form D had an author on another one within three years, against 5%
  of the rest. Content flags (model reached, dose, biodistribution) carry little.
- **First-time founders are the hard case, and the one a VC cares about.** For papers
  whose authors have no company record yet, the top tenth is 2.8 times the base rate
  (15% against 5.3%). Real, and too weak to show as a score on its own.

- **Ranking lab heads works better than ranking papers.** Of 4,099 lab heads active in
  2019 and 2020, the top twentieth by score had a company record in the next three
  years 21% of the time, against 2.8% overall (7.5 times), and the top tenth held 46% of
  all the events.

So the section is two things. A ranked feed for clinical translation, which the score
supports. And a watchlist built around people and labs, where the commercial signal
comes from their record and from footprints as they appear, not from the abstract.

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
    2024);
  - an author at a US address named as executive officer, director or promoter on a
    later SEC Form D from a biotechnology or pharmaceuticals issuer (the SEC's Form D
    data sets: 12,480 filings and 69,516 named people, 2010 to 2023);
  - an author at a UK address holding significant control of a UK research or
    pharmaceutical company incorporated after the paper (Companies House: 22,289 live
    companies under codes 21100, 21200, 72110 and 72190, with 29,080 individual
    owners).
- **Floor.** The number of authors alone. Every company outcome is found by matching
  names, so a long author list raises the hit rate whatever the paper says.

Of 7,006 papers with a US or UK author, 765 had an author in a later company record:
252 by award, 491 by Form D (442 of them with no award) and 72 by UK company.

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
These rows are the first run. The second run added author flags and moved them by a
point or two (first award, academic: AUC 0.606, top 10% 2.4x).

**An author in a later company record, second run (papers with a US or UK author)**

| Papers | Events, base rate | Score | AUC | Top 1% | Top 5% | Top 10% |
|---|---|---|---|---|---|---|
| Form D, US papers (3,352) | 281, 8.4% | rules + words | 0.768 | 29%, 3.5x | 43%, 5.1x | 35%, 4.2x |
| | | iCite `apt` | 0.598 | 21%, 2.5x | 18%, 2.1x | 16%, 2.0x |
| | | author count | 0.623 | 18%, 2.1x | 16%, 1.9x | 16%, 1.9x |
| New UK company, UK papers (751) | 40, 5.3% | rules + words | 0.548 | 0% | 8%, 1.5x | 8%, 1.5x |
| | | author count | 0.573 | 12%, 2.3x | 11%, 2.0x | 7%, 1.3x |
| Any company record (3,923) | 425, 10.8% | rules + words | 0.767 | 49%, 4.5x | 51%, 4.7x | 38%, 3.5x |
| | | iCite `apt` | 0.568 | 15%, 1.4x | 18%, 1.6x | 17%, 1.6x |
| | | author count | 0.615 | 23%, 2.1x | 18%, 1.7x | 17%, 1.6x |
| An author's first record (3,923) | 285, 7.3% | rules + words | 0.679 | 18%, 2.5x | 23%, 3.2x | 20%, 2.7x |
| | | author count | 0.643 | 21%, 2.8x | 16%, 2.2x | 15%, 2.1x |
| First record, academic papers only (2,807) | 148, 5.3% | rules + words | 0.688 | 21%, 4.1x | 16%, 3.0x | 15%, 2.8x |
| | | iCite `apt` | 0.601 | 11%, 2.0x | 12%, 2.3x | 11%, 2.1x |
| | | author count | 0.613 | 4%, 0.7x | 8%, 1.5x | 9%, 1.6x |

"Academic" here is no company among the affiliations and no author with a company
record of any of the three kinds before the paper.

**What the authors' record is worth (US papers, all four years)**

| The paper has | Papers | A later Form D | Any later company record |
|---|---|---|---|
| An author already named on a biotech Form D | 528 | 42% (5% without) | 47% (9%) |
| An author already holding a small-business award | 811 | 14% (7%) | 26% (10%) |
| A founder interest declared in the paper | 307 | 22% (8%) | 28% (11%) |
| An equity interest declared in the paper | 336 | 18% (8%) | 24% (11%) |
| A company among the affiliations | 740 | 18% (7%) | 23% (10%) |

Strongest rule flags for any company record: prior Form D +0.60, number of authors
+0.46, prior award +0.29, "capsid" +0.25. For an author's first record: number of
authors, "capsid", manufacturing, "platform". For a clinical citation among papers that
are not clinical: number of authors, primate, efficacy, immunogenicity.

**The UK outcome shows nothing yet.** 40 events in the scored years, and a score no
better than the author count. That is the register's limit as much as the model's (see
Limits), so it is not evidence that UK spinouts cannot be seen.

## Third run: OpenAlex author records

OpenAlex gave a record for 22,538 of 22,583 papers and 116,064 authors, matched to
99.5% of the corpus's author names by position and surname. It cost under 15 cents of
the free dollar a day. Three things changed.

- **Preprints join the company studies.** OpenAlex carries each author's address where
  Europe PMC has none, so 1,047 preprints with a US or UK author come in and the scored
  set grows from 3,923 to 5,228. iCite has no record for a preprint, so its baseline
  drops out of these rows.
- **The senior author's output before the paper is a feature**, rebuilt as of the
  paper's year from OpenAlex's counts by year. It is the strongest flag for a first
  company record on an academic paper (+0.48), ahead of anything in the abstract.
- **Lab heads can be ranked as people.** One identifier per author lets every paper by
  the same last or corresponding author be read together.

| Study | Scored | Events, base rate | Score | AUC | Top 1% | Top 5% | Top 10% |
|---|---|---|---|---|---|---|---|
| Paper: any company record | 5,228 | 560, 10.7% | rules + words | 0.777 | 56%, 5.2x | 51%, 4.8x | 38%, 3.5x |
| | | | author count | 0.623 | 25%, 2.3x | 19%, 1.8x | 18%, 1.6x |
| Paper: first record, academic only | 3,612 | 199, 5.5% | rules + words | 0.715 | 33%, 6.1x | 24%, 4.3x | 17%, 3.2x |
| | | | author count | 0.615 | 8%, 1.5x | 10%, 1.9x | 10%, 1.8x |
| Lab head: any company record | 4,099 | 114, 2.8% | rules + words | 0.777 | 29%, 10.5x | 21%, 7.5x | 13%, 4.6x |
| | | | paper count | 0.648 | 29%, 10.5x | 11%, 3.9x | 8%, 2.9x |
| Lab head: first record | 3,815 | 68, 1.8% | rules + words | 0.699 | 21%, 11.8x | 7%, 4.1x | 5%, 2.8x |
| | | | paper count | 0.622 | 21%, 11.8x | 6%, 3.5x | 4%, 2.5x |

The first-record study on academic papers moved from AUC 0.688 to 0.715, and its top
twentieth from 3.0 to 4.3 times the base rate. Clinical translation did not move
(AUC 0.849 against iCite's 0.854). The UK study is still no better than its floor.

A lab head is anyone who was last or corresponding author, at a US or UK address, on a
corpus paper in the two years to the cutoff: 6,340 people. They are described by all
their papers to that date and scored on their own later records, trained at the end of
2018 and scored at the end of 2020.

**"No company record yet" means none in these three sources, and that is not the same
as never having founded a company.** The top of the first-record list holds Jennifer
Doudna, Matthew Porteus, Robert MacLaren and Adrian Thrasher. All had founded companies
before 2020. None had been an officer or director on a Form D, held a small-business
award, or held 25% of a live UK company. So part of what the first-record score learns
is "senior and prolific", which finds known founders the sources miss as well as new
ones. For lab heads the score barely clears the paper count on this study.

## What went wrong on the way, and the fix

- **Name matching.** The first award outcome matched on first and last name alone. Of 574
  matches, 301 were authors outside the US, mostly sharing a common name with a US
  investigator. The match now needs the author's own address on the paper to be in the
  US: 197 matches, 100 people. Of 14 read by hand, about 11 are clearly the same person
  (three UNC authors and Bedrock Therapeutics; Yang Liu and OncoImmune; a Berkeley author
  and Catena Biosciences); two or three common names remain doubtful.
- **Award topic.** "Vector", "stem cell" and "T cell" alone let unrelated awards through;
  the topic test now needs a CGT term.
- **Form D names.** A first and last name at any US address matched 1,112 filings to
  authors, with common names (Ming Li, Hui Yang) among them. The filing's state now has
  to be one the author's address names, or the middle initials have to agree. The 25
  read by hand after that were all the same person (StrideBio, Lacerta, Apic Bio,
  Allovir, Mammoth). The rule costs real matches where a founder's company sits in
  another state: Atsena's Florida founders and a North Carolina filing, Lyell, Rheos.
  A differing middle initial is not used to reject, because filers leave junk in that
  field (one filing gives every director the middle initial L).
- **Form D dates.** The SEC writes `2019-03-29 17:29:14` in some quarters and
  `29-MAR-2019` in others. Reading only the first form lost 2010, 2011, 2013 and half of
  2020 to 2023.
- **UK names.** A name at any UK address matched plainly unrelated owners (a "Mr James
  Smith" of a company in Elland). The company's town now has to be in the author's
  address, or the register has to title the owner Dr or Professor, and the company has
  to be incorporated after the paper.

## Limits

- **A Form D names officers and directors, not founders.** A professor on the board of
  someone else's company counts the same as one who founded it, and a company that has
  filed before files again. That is why the prior-filing flag is so strong, and why the
  first-record studies are the ones to read for new companies.
- **The UK register undercounts.** Companies House's free files hold live companies
  only and owners of 25% or more only. A spinout since dissolved, or a founder diluted
  below 25% by the university and a seed round, is not seen. Directors are in the
  Companies House API, which is free with a key, and would fix the second.
- **No continental Europe outcome.** CORDIS project files carry no investigator names,
  so they cannot give a person-level outcome, and there is no free EU-wide company
  register with officers. The HESA register blocks scripts.
- **Patents and licences are not in the outcome yet.** The USPTO's API needs a free key,
  which is not set up.
- **Preprints fall out of the company studies:** Europe PMC gives them no per-author
  address.
- **Few events.** 40 to 148 in the first-record and UK studies, so those lifts are rough.
- **Name matching is still name matching on the company side.** OpenAlex identifies the
  author, but an award, a Form D and the UK register carry only a name and a place, so
  the state and town rules still decide a match. They cut false matches and lose some
  real ones.
- **Founders who are neither officer nor director are not seen.** A scientific founder
  with an advisory seat and under 25% leaves no trace in these sources. Patents by
  inventor would catch many of them.
- **OpenAlex's author totals are today's, wound back by year.** Its merging of people
  with a shared name is not perfect, so a common name can carry someone else's papers.
- **Conflict-of-interest text exists for 7,685 of 20,807 papers** in PubMed's field.
- **iCite's score reads today's record,** so it is a harder baseline than a day-one score
  would face.

## What this says to build

1. **The watchlist, not a point score.** Rank the feed by the clinical-translation score,
   which works, and attach footprints as they appear.
2. **People and labs as first-class objects.** An author's record (Form D filings,
   awards, declared interests) is the strongest commercial signal found, by a wide
   margin. Each paper in the feed should show it: "senior author on two prior biotech
   filings" is worth more to a reader than any score.
3. **Two lists, because they answer different questions.** "Proven founders publishing
   again" is easy to rank and already useful. "Labs with no company yet" is the list a
   VC cannot get elsewhere, and the one where the score is weakest, so it is shown as a
   watchlist with evidence, not as a ranking to trust.
4. **Rank lab heads, and show papers under them.** The lab-level ranking is the
   stronger one for company activity, and it is the object a watchlist is made of.
5. **Still to add before a "first-time founder" list is trusted:** patents by inventor
   match (needs the USPTO key) and UK directors (needs a Companies House key). Both
   find founders the present sources miss, which is the gap that list has. Then retest.
6. **Embeddings** in place of word counts, once a key or a local model is available.
