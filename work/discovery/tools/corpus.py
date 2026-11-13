"""Step 1 corpus: CGT papers and preprints first published 2017 to 2020, from Europe PMC.

One NDJSON line per record with the fields the backtest reads: ids, dates, title,
abstract, authors with affiliations, MeSH headings, grants and publication types.
Selected by title and abstract terms, the same for papers and preprints, so the corpus is
what a daily feed would have caught on publication day. Reviews are left out.

    python3 work/discovery/tools/corpus.py <out folder> [first year] [last year]
"""

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TERMS = ("gene therapy", "cell therapy", "CAR-T", "CAR T", "chimeric antigen receptor",
         "AAV", "adeno-associated", "lentiviral vector", "base editing", "prime editing",
         "genome editing", "gene editing", "lipid nanoparticle")
QUERY = "(" + " OR ".join(f'TITLE_ABS:"{t}"' for t in TERMS) + ")"


def _get(params):
    url = SEARCH + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Novatalis Research"})
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:                               # noqa: BLE001
            print("retry", attempt, exc, flush=True)
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("Europe PMC did not answer")


def _slim(r):
    authors = [{"name": a.get("fullName"), "last": a.get("lastName"),
                "first": a.get("firstName"), "initials": a.get("initials"),
                "orcid": (a.get("authorId") or {}).get("value"),
                "affiliations": [x.get("affiliation") for x in
                                 (a.get("authorAffiliationDetailsList") or {})
                                 .get("authorAffiliation", [])]}
               for a in (r.get("authorList") or {}).get("author", [])]
    return {"id": r.get("id"), "source": r.get("source"), "pmid": r.get("pmid"),
            "doi": r.get("doi"), "title": r.get("title"),
            "abstract": r.get("abstractText"),
            "first_date": r.get("firstPublicationDate"),
            "journal": ((r.get("journalInfo") or {}).get("journal") or {}).get("title"),
            "pub_types": (r.get("pubTypeList") or {}).get("pubType", []),
            "mesh": [m.get("descriptorName") for m in
                     (r.get("meshHeadingList") or {}).get("meshHeading", [])],
            "grants": [{"agency": g.get("agency"), "id": g.get("grantId")} for g in
                       (r.get("grantsList") or {}).get("grant", [])],
            "authors": authors, "affiliation": r.get("affiliation"),
            "open_access": r.get("isOpenAccess"), "cited_by": r.get("citedByCount")}


def pull(folder, first, last):
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for year in range(first, last + 1):
        for source, extra in (("MED", ' AND NOT PUB_TYPE:"Review"'), ("PPR", "")):
            out = folder / f"{source}-{year}.ndjson"
            if out.exists():
                continue
            query = (f"SRC:{source} AND {QUERY} AND FIRST_PDATE:[{year}-01-01 TO "
                     f"{year}-12-31]{extra}")
            cursor, rows = "*", []
            while True:
                data = _get({"query": query, "format": "json", "resultType": "core",
                             "pageSize": 1000, "cursorMark": cursor})
                batch = (data.get("resultList") or {}).get("result", [])
                rows += [_slim(r) for r in batch]
                following = data.get("nextCursorMark")
                if not batch or not following or following == cursor:
                    break
                cursor = following
                time.sleep(0.2)
            out.write_text("".join(json.dumps(r) + "\n" for r in rows))
            print(source, year, len(rows), flush=True)


if __name__ == "__main__":
    pull(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2017,
         int(sys.argv[3]) if len(sys.argv) > 3 else 2020)
