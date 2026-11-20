# Europe PMC search payloads

Saved on 2026-11-20 from `https://www.ebi.ac.uk/europepmc/webservices/rest/search`
(`resultType=core`), then reduced: nine records chosen for what they exercise, each cut to
the fields the fetcher reads plus a few around them, and email addresses taken out of the
printed affiliations. Every record with an abstract is open access under CC BY.

| Record | What it is here for |
|---|---|
| MED 42969556 | A journal paper whose last author matches a lab by name and institution |
| MED 42975285 | The same, for a lab ranked too low to alert on |
| MED 42993797 | A company among the authors' addresses |
| MED 43032656 | A company paper with no ranked lab |
| MED 42961140 | Indexed the day before its stated publication date |
| MED 43039921 | No abstract yet |
| MED 42977824 | No abstract and no authors |
| PPR PPR1355809 | A preprint with no address, last author's name held by one lab |
| PPR PPR1363655 | A preprint with no address and no lab |

The saved request is the one made that day, on the publication date. The fetcher asks by
index date (`FIRST_IDATE`), which returns records of the same shape.
