"""Step 1 outcomes and the baseline, each from a free source.

    python3 work/discovery/tools/outcomes.py sbir <out.ndjson> [first FY] [last FY]
    python3 work/discovery/tools/outcomes.py icite <corpus folder> <out.ndjson>
    python3 work/discovery/tools/outcomes.py coi <corpus folder> <out.ndjson>
    python3 work/discovery/tools/outcomes.py formd <out.ndjson> [first year] [last year]
    python3 work/discovery/tools/outcomes.py uk <work folder> <out.ndjson>

- ``sbir``: every NIH small-business award (SBIR and STTR, activity codes R41 to R44, U43,
  U44, SB1) from RePORTER, with its investigators, organisation and start date.
- ``icite``: NIH iCite's record for each PMID in the corpus: ``apt`` (the baseline), the
  clinical articles that cite it, and each of those articles' year.
- ``coi``: PubMed's conflict-of-interest statement for each PMID, as printed.
- ``formd``: every SEC Form D (a private placement notice) whose issuer gives its industry
  as biotechnology or pharmaceuticals, from the SEC's quarterly Form D data sets, with
  the executive officers, directors and promoters it names. ``SEC_USER_AGENT`` must hold
  a contact string; the SEC refuses requests without one.
- ``uk``: every live UK company registered under a biotechnology, pharmaceutical or
  natural-science research code (Companies House's free company data product), with its
  persons with significant control from the ownership snapshot. The snapshot is 33 files
  of about 85 MB; each is read and deleted in turn.
"""

import csv
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

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


FORMD_URL = "https://www.sec.gov/files/structureddata/data/form-d-data-sets/{y}q{q}_d.zip"
FORMD_INDUSTRIES = {"Biotechnology", "Pharmaceuticals"}
# 21100 and 21200 pharmaceutical manufacture, 72110 biotechnology research, 72190 other
# natural-science research (where many spinouts file before they have a product).
UK_SICS = ("21100", "21200", "72110", "72190")
UK_HOST = "https://download.companieshouse.gov.uk/"


def _download(url, path, headers, tries=5):
    """The file at ``url`` saved to ``path``; False where the source has none."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=600) as resp, open(path, "wb") as handle:
                while chunk := resp.read(1 << 20):
                    handle.write(chunk)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            print("retry", attempt, exc.code, flush=True)
        except Exception as exc:                               # noqa: BLE001
            print("retry", attempt, str(exc)[:100], flush=True)
        time.sleep(2 ** (attempt + 2))
    raise RuntimeError(f"no answer from {url}")


def _day(text):
    """A filing date as YYYY-MM-DD. The data sets write 2019-03-29 17:29:14 in some
    quarters and 29-MAR-2019 in others."""
    text = (text or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        return time.strftime("%Y-%m-%d", time.strptime(text[:11].title(), "%d-%b-%Y"))
    except ValueError:
        return None


def _table(archive, name):
    member = next(n for n in archive.namelist() if n.upper().endswith("/" + name))
    with archive.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, "utf-8", errors="replace"),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)


def formd(out, first=2010, last=2023):
    contact = (os.environ.get("SEC_USER_AGENT") or "").strip()
    if not contact:
        sys.exit("SEC_USER_AGENT is empty; the SEC refuses requests without a contact")
    scratch = pathlib.Path(out).with_suffix(".zip")
    with open(out, "w") as handle:
        for year in range(first, last + 1):
            for quarter in (1, 2, 3, 4):
                if not _download(FORMD_URL.format(y=year, q=quarter), scratch,
                                 {"User-Agent": contact}):
                    print(year, quarter, "no data set", flush=True)
                    continue
                with zipfile.ZipFile(scratch) as archive:
                    offers = {r["ACCESSIONNUMBER"]: r for r in _table(archive, "OFFERING.TSV")
                              if r.get("INDUSTRYGROUPTYPE") in FORMD_INDUSTRIES}
                    filed = {r["ACCESSIONNUMBER"]: r
                             for r in _table(archive, "FORMDSUBMISSION.TSV")
                             if r["ACCESSIONNUMBER"] in offers}
                    issuers = {}
                    for r in _table(archive, "ISSUERS.TSV"):
                        if (r["ACCESSIONNUMBER"] in offers
                                and (r.get("IS_PRIMARYISSUER_FLAG") or "").upper() == "YES"):
                            issuers[r["ACCESSIONNUMBER"]] = r
                    people = {}
                    for r in _table(archive, "RELATEDPERSONS.TSV"):
                        if r["ACCESSIONNUMBER"] in offers:
                            people.setdefault(r["ACCESSIONNUMBER"], []).append({
                                "first": r.get("FIRSTNAME"), "middle": r.get("MIDDLENAME"),
                                "last": r.get("LASTNAME"), "state": r.get("STATEORCOUNTRY"),
                                "roles": [r[k] for k in ("RELATIONSHIP_1", "RELATIONSHIP_2",
                                                         "RELATIONSHIP_3") if r.get(k)]})
                for number, offer in offers.items():
                    issuer = issuers.get(number) or {}
                    handle.write(json.dumps({
                        "accession": number,
                        "filed": _day((filed.get(number) or {}).get("FILING_DATE")),
                        "form": (filed.get(number) or {}).get("SUBMISSIONTYPE"),
                        "industry": offer.get("INDUSTRYGROUPTYPE"),
                        "amendment": offer.get("ISAMENDMENT"),
                        "first_sale": _day(offer.get("SALE_DATE")),
                        "offered": offer.get("TOTALOFFERINGAMOUNT"),
                        "sold": offer.get("TOTALAMOUNTSOLD"),
                        "cik": issuer.get("CIK"), "issuer": issuer.get("ENTITYNAME"),
                        "state": issuer.get("STATEORCOUNTRY"),
                        "inc_year": issuer.get("YEAROFINC_VALUE_ENTERED"),
                        "people": people.get(number, [])}) + "\n")
                print(year, quarter, len(offers), flush=True)
                time.sleep(0.5)                  # far under the SEC's ten a second
    scratch.unlink(missing_ok=True)


def _links(page, pattern):
    with urllib.request.urlopen(urllib.request.Request(UK_HOST + page, headers=UA),
                                timeout=120) as resp:
        return sorted(set(re.findall(pattern, resp.read().decode("utf-8", "replace"))))


def uk(work, out):
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    whole = _links("en_output.html", r'href="(BasicCompanyDataAsOneFile-[\d-]+\.zip)"')[-1]
    path = work / whole
    if not path.exists():
        _download(UK_HOST + whole, path, UA)
    companies = {}
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, "utf-8", errors="replace"))
            head = [h.strip() for h in next(reader)]
            at = {name: i for i, name in enumerate(head)}
            sic_columns = [i for name, i in at.items() if name.startswith("SICCode.")]
            for row in reader:
                if len(row) < len(head):         # a broken line, of which there are a few
                    continue
                sics = [row[i][:5] for i in sic_columns if row[i]]
                if not any(code in UK_SICS for code in sics):
                    continue
                companies[row[at["CompanyNumber"]].strip()] = {
                    "number": row[at["CompanyNumber"]].strip(),
                    "name": row[at["CompanyName"]],
                    "incorporated": row[at["IncorporationDate"]],
                    "status": row[at["CompanyStatus"]], "sics": sics,
                    "post_town": row[at["RegAddress.PostTown"]],
                    "postcode": row[at["RegAddress.PostCode"]], "psc": []}
    print("companies under", UK_SICS, len(companies), "from", whole, flush=True)
    parts = _links("en_pscdata.html", r'href="(psc-snapshot-[\d-]+_\d+of\d+\.zip)"')
    for part in sorted(parts, key=lambda n: int(re.search(r"_(\d+)of", n).group(1))):
        path = work / part
        _download(UK_HOST + part, path, UA)
        kept = 0
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.namelist()[0]) as raw:
                for line in raw:
                    record = json.loads(line)
                    company = companies.get(str(record.get("company_number") or "").strip())
                    data = record.get("data") or {}
                    if company is None or "name" not in data:
                        continue
                    names = data.get("name_elements") or {}
                    born = data.get("date_of_birth") or {}
                    company["psc"].append({
                        "kind": data.get("kind"), "name": data.get("name"),
                        "first": names.get("forename"), "middle": names.get("middle_name"),
                        "last": names.get("surname"), "title": names.get("title"),
                        "born": (f"{born['year']}-{born.get('month', 0):02d}"
                                 if born.get("year") else None),
                        "residence": data.get("country_of_residence"),
                        "notified": data.get("notified_on"), "ceased": data.get("ceased_on"),
                        "control": data.get("natures_of_control")})
                    kept += 1
        path.unlink()
        print(part, kept, flush=True)
    with open(out, "w") as handle:
        for company in companies.values():
            handle.write(json.dumps(company) + "\n")


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "sbir":
        sbir(sys.argv[2], *(int(a) for a in sys.argv[3:5]))
    elif what == "icite":
        icite(sys.argv[2], sys.argv[3])
    elif what == "coi":
        coi(sys.argv[2], sys.argv[3])
    elif what == "formd":
        formd(sys.argv[2], *(int(a) for a in sys.argv[3:5]))
    elif what == "uk":
        uk(sys.argv[2], sys.argv[3])
