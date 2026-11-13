"""Step 1 outcomes and the baseline, each from a free source.

    python3 work/discovery/tools/outcomes.py sbir <out.ndjson> [first FY] [last FY]
    python3 work/discovery/tools/outcomes.py icite <corpus folder> <out.ndjson>
    python3 work/discovery/tools/outcomes.py coi <corpus folder> <out.ndjson>

- ``sbir``: every NIH small-business award (SBIR and STTR, activity codes R41 to R44, U43,
  U44, SB1) from RePORTER, with its investigators, organisation and start date.
- ``icite``: NIH iCite's record for each PMID in the corpus: ``apt`` (the baseline), the
  clinical articles that cite it, and each of those articles' year.
- ``coi``: PubMed's conflict-of-interest statement for each PMID, as printed.
"""

import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Novatalis Research"}
SBIR_CODES = ["R41", "R42", "R43", "R44", "U43", "U44", "SB1"]
FIELDS = ["ApplId", "FiscalYear", "ProjectNum", "CoreProjectNum", "ActivityCode",
          "Organization", "PrincipalInvestigators", "ProjectStartDate", "AwardNoticeDate",
          "ProjectTitle", "AwardType", "AwardAmount", "PrefTerms"]


def _json(url, body=None, tries=6):
    for attempt in range(tries):
        try:
            data = json.dumps(body).encode() if body is not None else None
            headers = dict(UA, **({"Content-Type": "application/json"} if body else {}))
            with urllib.request.urlopen(urllib.request.Request(url, data=data,
                                                               headers=headers),
                                        timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:                               # noqa: BLE001
            print("retry", attempt, str(exc)[:100], flush=True)
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"no answer from {url}")


def sbir(out, first=2012, last=2024):
    with open(out, "w") as handle:
        for year in range(first, last + 1):
            offset, total = 0, None
            while total is None or offset < total:
                data = _json("https://api.reporter.nih.gov/v2/projects/search", {
                    "criteria": {"activity_codes": SBIR_CODES, "fiscal_years": [year]},
                    "include_fields": FIELDS, "limit": 500, "offset": offset,
                    "sort_field": "appl_id", "sort_order": "asc"})
                total = data["meta"]["total"]
                for p in data["results"]:
                    handle.write(json.dumps({
                        "fy": p.get("fiscal_year"), "num": p.get("project_num"),
                        "core": p.get("core_project_num"), "code": p.get("activity_code"),
                        "type": p.get("award_type"), "start": p.get("project_start_date"),
                        "notice": p.get("award_notice_date"),
                        "amount": p.get("award_amount"), "title": p.get("project_title"),
                        "terms": p.get("pref_terms"),
                        "org": (p.get("organization") or {}).get("org_name"),
                        "pis": [{"first": i.get("first_name"), "last": i.get("last_name"),
                                 "id": i.get("profile_id")}
                                for i in p.get("principal_investigators") or []]}) + "\n")
                offset += 500
                time.sleep(1.0)                 # RePORTER asks for one request a second
            print("FY", year, total, flush=True)


def _pmids(folder):
    seen = []
    for path in sorted(pathlib.Path(folder).glob("MED-*.ndjson")):
        for line in path.open():
            pmid = json.loads(line).get("pmid")
            if pmid:
                seen.append(str(pmid))
    return sorted(set(seen), key=int)


def icite(folder, out):
    def fetch(ids, fields=None):
        rows = []
        for i in range(0, len(ids), 200):
            url = ("https://icite.od.nih.gov/api/pubs?pmids=" + ",".join(ids[i:i + 200])
                   + ("&fl=" + ",".join(fields) if fields else ""))
            rows += _json(url).get("data", [])
            time.sleep(0.3)
        return rows

    pmids = _pmids(folder)
    papers = fetch(pmids)
    print("iCite records", len(papers), "of", len(pmids), flush=True)
    citing = sorted({str(c) for p in papers for c in (p.get("cited_by_clin") or [])},
                    key=int)
    years = {str(r["pmid"]): r.get("year") for r in fetch(citing, ["pmid", "year"])}
    print("clinical citing articles", len(citing), flush=True)
    with open(out, "w") as handle:
        for p in papers:
            handle.write(json.dumps({
                "pmid": str(p["pmid"]), "year": p.get("year"), "apt": p.get("apt"),
                "rcr": p.get("relative_citation_ratio"), "human": p.get("human"),
                "animal": p.get("animal"), "molecular": p.get("molecular_cellular"),
                "is_clinical": p.get("is_clinical"),
                "research": p.get("is_research_article"),
                "clin_years": sorted(years[str(c)] for c in (p.get("cited_by_clin") or [])
                                     if years.get(str(c)))}) + "\n")


def coi(folder, out):
    pmids = _pmids(folder)
    block = re.compile(r"<PubmedArticle>.*?</PubmedArticle>", re.S)
    with open(out, "w") as handle:
        for i in range(0, len(pmids), 200):
            url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed"
                   "&retmode=xml&id=" + ",".join(pmids[i:i + 200]))
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                                timeout=120) as resp:
                        text = resp.read().decode("utf-8", "replace")
                    break
                except Exception as exc:                       # noqa: BLE001
                    print("retry", attempt, str(exc)[:80], flush=True)
                    time.sleep(2 ** (attempt + 1))
            else:
                continue
            for article in block.findall(text):
                pmid = re.search(r"<PMID[^>]*>(\d+)</PMID>", article)
                stated = re.search(r"<CoiStatement>(.*?)</CoiStatement>", article, re.S)
                if pmid and stated:
                    handle.write(json.dumps({
                        "pmid": pmid.group(1),
                        "coi": re.sub(r"<[^>]+>", " ", stated.group(1)).strip()}) + "\n")
            time.sleep(0.4)                     # three requests a second without a key
            if i % 4000 == 0:
                print("coi", i, "of", len(pmids), flush=True)


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "sbir":
        sbir(sys.argv[2], *(int(a) for a in sys.argv[3:5]))
    elif what == "icite":
        icite(sys.argv[2], sys.argv[3])
    elif what == "coi":
        coi(sys.argv[2], sys.argv[3])
