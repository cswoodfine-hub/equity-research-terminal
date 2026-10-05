"""The codes the payer files key a drug on, from RxNav (NLM): RxCUIs and NDC product codes.

The Part D formulary lists a drug by RxCUI and Medicaid's State Drug Utilization Data by
NDC, and neither file carries a brand name worth matching: SDUD cuts the name to ten
characters. So each marketed asset is mapped to its codes once, here, and the payer
readers join on the codes.

The match is on an identifier. Each marketed asset's FDA application number
(approvals.application_number) goes to RxNav's findRxcuiById, which needs the prefix:
'NDA202155' returns Eliquis's two tablets and its starter pack, and '202155' returns
nothing, so an unprefixed number is never sent. For each RxCUI three calls follow: its
term type and name (/properties), every NDC RxNorm has ever attached to it with the first
and last month listed (/allhistoricalndcs, repackagers included), and the labeler names of
its active NDCs (/ndcproperties). The 11-digit NDCs are stored as product codes,
'LLLLL-PPPP', the form negotiated_prices already uses.

The application route is exact but not complete: RxNorm links a concept to its NDA only
where its sources say so, and newer forms go missing. NDA202155 returns Eliquis's two
tablets and starter pack but not the paediatric dose packs RxNav itself lists under the
same NDA, and an asset whose approval row carries the wrong number gets the wrong drug
(the book files Ozempic under Rybelsus's NDA213051). So every asset is also looked up by
its brand name, through a brand-name concept (term type BN) spelled exactly as the brand,
and the branded products under it (SBD and BPCK) are added, marked rxnav_brand_name. A
generic name finds an ingredient rather than a brand, and an ingredient's products are
every company's, so that route returns nothing rather than another company's codes.

An application also returns unbranded concepts: the clinical drug its authorised generic
is sold as, or a kit component such as the alcohol pad in a biologic's carton. Their NDC
history is every manufacturer's, so for them only the active NDCs RxNav lists under the
asset's own application number are kept, and the RxCUI itself is marked not
brand-specific. Where two assets claim one code, it stays with each asset its RxNorm name
names: co-marketed Eliquis keeps it on both owners, and the alcohol pad goes from all.

A labeler is the company's own (is_owner_labeler 1) when RxNav's labeler name for an
active NDC shares a distinctive word with a name the company is known by: Eliquis is
labelled "E.R. Squibb & Sons", which is Bristol-Myers Squibb. A labeler RxNav names as
someone else is 0, a repackager such as A-S Medication Solutions. A labeler whose codes
are all inactive has no name in RxNav and is left null rather than guessed.

RxNav allows 20 requests a second per address; this sends at most 10, over one kept-alive
connection. NLM asks that any product using its data carry its attribution statement,
which is ATTRIBUTION below.

The daily refresh runs forced, which skips every TTL, so the guard here is per asset and
reads drug_code_lookups: an asset is looked up when it never was, when its application
numbers changed, or when its last lookup is over 30 days old. A run stops at a time
budget and leaves the rest for the next one.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import http.client
import json
import re
import time
import urllib.parse
from pathlib import Path

import db
import ndc
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "rxnav_codes"
ENTITY_KEY = "rxnav"
TTL_SECONDS = 30 * 24 * 60 * 60          # RxNorm publishes monthly
RUN_BUDGET_S = 900
HOST = "rxnav.nlm.nih.gov"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30
_MIN_INTERVAL_S = 0.1                   # 10 requests a second at most; NLM allows 20
_ATTEMPTS = 3
_GIVE_UP_AFTER = 5                      # consecutive failed assets: the source is down

BRAND_TTYS = ("SBD", "BPCK")
_APPLICATION = re.compile(r"^(NDA|BLA|ANDA)(\d{6})$")
OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "data" / "drug_code_overrides.csv"

# NLM's requested statement, as its RxNav terms of service gave it on 2026-10-05.
ATTRIBUTION = (
    "This product uses publicly available data from the U.S. National Library of "
    "Medicine (NLM), National Institutes of Health, Department of Health and Human "
    "Services; NLM is not responsible for the product and does not endorse or recommend "
    "this or any other product.")

# Words too common in a company or labeler name to identify one.
_COMMON_NAME_WORDS = {
    "inc", "incorporated", "corp", "corporation", "company", "plc", "ltd", "limited",
    "holdings", "holding", "group", "the", "and", "pharmaceuticals", "pharmaceutical",
    "pharms", "pharma", "therapeutics", "biosciences", "bioscience", "sciences",
    "science", "biopharma", "biopharmaceuticals", "medicines", "laboratories", "labs",
    "health", "healthcare", "usa", "america", "american", "international", "global",
    "gmbh", "llc", "division", "products", "solutions", "medical", "care",
}

# Words a generic name shares with an unrelated one: salts, forms and class words.
_NOT_A_MOLECULE = {
    "hydrochloride", "dihydrochloride", "sodium", "disodium", "potassium", "calcium",
    "magnesium", "sulfate", "sulphate", "phosphate", "acetate", "maleate", "mesylate",
    "tartrate", "citrate", "fumarate", "succinate", "besylate", "bromide", "chloride",
    "hydrobromide", "tromethamine", "monohydrate", "propionate", "dipropionate",
    "furoate", "valerate", "and", "with", "recombinant", "human", "synthetic",
    "injection", "extended", "release", "oral", "insulin", "vaccine", "factor",
    "coagulation", "antihemophilic", "conjugate", "adjuvanted",
}


# --- pure parsers ---------------------------------------------------------------------

def parse_rxcui_ids(payload: dict) -> list[str]:
    """The RxCUIs a findRxcuiById or findRxcuiByString answer carries, in order."""
    ids = ((payload or {}).get("idGroup") or {}).get("rxnormId") or []
    return [str(i) for i in ids]


def parse_related(payload: dict) -> dict:
    """{rxcui: {tty, name}} from a related.json answer."""
    out = {}
    group = ((payload or {}).get("relatedGroup") or {}).get("conceptGroup") or []
    for concept_group in group:
        for concept in concept_group.get("conceptProperties") or []:
            out[str(concept["rxcui"])] = {"tty": concept.get("tty"),
                                          "name": concept.get("name")}
    return out


def parse_history(payload: dict) -> list[dict]:
    """[{ndc11, start, end}] from allhistoricalndcs: every NDC RxNorm attached to the
    RxCUI, directly or through a concept since remapped to it, with its first and last
    month (YYYYMM)."""
    out = []
    concept = (payload or {}).get("historicalNdcConcept") or {}
    for timeline in concept.get("historicalNdcTime") or []:
        for span in timeline.get("ndcTime") or []:
            for code in span.get("ndc") or []:
                ndc11 = ndc.to_ndc11(code)
                if ndc11:
                    out.append({"ndc11": ndc11, "start": span.get("startDate"),
                                "end": span.get("endDate")})
    return out


_APPLICATION_PROPS = ("NDA", "ANDA", "BLA", "NDA_AUTHORIZED_GENERIC")


def parse_ndc_properties(payload: dict) -> dict:
    """{ndc11: {labeler, application, start}} for the active NDCs an ndcproperties answer
    lists: the labeler's name, the application the package is marketed under (an NDA,
    ANDA or BLA, or the NDA an authorised generic is sold under), and the month its
    marketing began (YYYYMM)."""
    out = {}
    listing = ((payload or {}).get("ndcPropertyList") or {}).get("ndcProperty") or []
    for item in listing:
        ndc11 = ndc.to_ndc11(item.get("ndcItem"))
        if not ndc11:
            continue
        props = {p.get("propName"): (p.get("propValue") or "").strip()
                 for p in (item.get("propertyConceptList") or {}).get("propertyConcept")
                 or []}
        started = props.get("MARKETING_EFFECTIVE_TIME_LOW") or ""
        out[ndc11] = {
            "labeler": props.get("LABELER") or None,
            "application": next((props[k].upper() for k in _APPLICATION_PROPS
                                 if props.get(k)), None),
            "start": started[:6] if len(started) == 8 and started.isdigit() else None,
        }
    return out


def parse_ndc_labelers(payload: dict) -> dict:
    """{ndc11: labeler name} for the active NDCs an ndcproperties answer lists."""
    return {code: info["labeler"] for code, info in parse_ndc_properties(payload).items()
            if info["labeler"]}


def distinctive_words(name: str) -> set:
    """The words in a company or labeler name that could identify it."""
    return {w for w in re.split(r"[^a-z]+", (name or "").lower())
            if len(w) >= 4 and w not in _COMMON_NAME_WORDS}


def molecule_words(generic: str) -> set:
    """The words of a generic name that name the molecule, not its salt or form."""
    return {w for w in re.split(r"[^a-z]+", (generic or "").lower())
            if len(w) >= 4 and w not in _NOT_A_MOLECULE}


def name_fits(name: str, asset: dict) -> bool:
    """Whether a code's RxNorm name names this asset.

    A branded concept carries its brand in brackets, "apixaban 5 MG Oral Tablet
    [Eliquis]", and fits an asset whose brand has a word in them. An unbranded one,
    "isopropyl alcohol 0.7 ML/ML Medicated Pad", fits an asset whose molecule it names.
    """
    text = (name or "").lower()
    brackets = re.findall(r"\[([^\]]+)\]", text)
    brand_words = {w for w in re.split(r"[^a-z]+", (asset.get("brand_name") or "").lower())
                   if len(w) >= 4}
    if brackets and brand_words:
        return bool(brand_words & set(re.split(r"[^a-z]+", " ".join(brackets))))
    molecule = (molecule_words(asset.get("generic_name"))
                or molecule_words(asset.get("brand_name")))
    return bool(molecule & set(re.split(r"[^a-z]+", text)))


def settle_claims(claims: dict, assets: dict) -> list[tuple]:
    """The codes more than one asset claims, and which claims stand.

    claims: {(code_type, code): {asset_id: RxNorm name}}. assets: {asset_id: {brand_name,
    generic_name}}. A code two assets share stays with each asset its RxNorm name names,
    so co-marketed Eliquis stays with both owners, and a code that came with something
    else, the alcohol pad in a biologic's kit or an Ozempic pen claimed by a Rybelsus row
    carrying the wrong number, is dropped from the asset it does not name. A code with no
    name to read (a curated one) is left as it is. Returns [(code_type, code, kept ids,
    dropped ids)] for the codes where a claim was dropped.
    """
    out = []
    for (code_type, code), owners in sorted(claims.items()):
        if len(owners) < 2:
            continue
        name = next((n for n in owners.values() if n), None)
        if not name:
            continue
        kept = sorted(a for a in owners if name_fits(name, assets.get(a, {})))
        dropped = sorted(a for a in owners if a not in kept)
        if dropped:
            out.append((code_type, code, kept, dropped))
    return out


def asset_rows(lookup: dict, owner_words: set, labeler_names: dict) -> list[dict]:
    """The drug_codes rows for one looked-up asset.

    lookup: {asset_id, basis, concepts: [{rxcui, tty, name, application_number, ndcs,
    labelers}]}. owner_words: the distinctive words of every name the owning company is
    known by. labeler_names: {labeler code: {names}} across the whole run, so a code
    named on another drug's active NDC is still read.
    """
    rows, by_ndc9 = [], {}
    for concept in lookup["concepts"]:
        tty = concept.get("tty")
        basis = ("rxnav_application" if concept.get("application_number")
                 else "rxnav_brand_name")
        brand_specific = int(tty in BRAND_TTYS) if tty else None
        months = concept["ndcs"]
        rows.append({
            "code_type": "rxcui", "code": concept["rxcui"], "tty": tty,
            "name": concept.get("name"), "rxcui": None,
            "brand_specific": brand_specific, "labeler_code": None,
            "labeler_name": None,
            "first_ym": min((n["start"] for n in months if n["start"]), default=None),
            "last_ym": max((n["end"] for n in months if n["end"]), default=None),
            "is_owner_labeler": None, "basis": basis,
            "application_number": concept.get("application_number")})
        for item in concept["ndcs"]:
            code9 = ndc.ndc9(item["ndc11"])
            held = by_ndc9.get(code9)
            if held is None:
                labeler_code = ndc.labeler(item["ndc11"])
                names = sorted(labeler_names.get(labeler_code) or ())
                if names:
                    owner = int(any(distinctive_words(n) & owner_words for n in names))
                else:
                    owner = None
                held = by_ndc9[code9] = {
                    "code_type": "ndc9", "code": code9, "tty": tty,
                    "name": concept.get("name"),
                    "rxcui": concept["rxcui"], "brand_specific": brand_specific,
                    "labeler_code": labeler_code,
                    "labeler_name": names[0] if names else None,
                    "first_ym": item["start"], "last_ym": item["end"],
                    "is_owner_labeler": owner, "basis": basis,
                    "application_number": concept.get("application_number")}
                continue
            if item["start"] and (not held["first_ym"] or item["start"] < held["first_ym"]):
                held["first_ym"] = item["start"]
            if item["end"] and (not held["last_ym"] or item["end"] > held["last_ym"]):
                held["last_ym"] = item["end"]
    return rows + list(by_ndc9.values())


_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def _version_month(version: str | None) -> str | None:
    """RxNav's version date, '05-Oct-2026', as the YYYYMM its NDC history ends on."""
    parts = (version or "").split("-")
    if len(parts) != 3 or parts[1][:3].lower() not in _MONTHS or not parts[2].isdigit():
        return None
    return f"{parts[2]}{_MONTHS[parts[1][:3].lower()]:02d}"


def read_overrides(path: Path) -> list[dict]:
    """The rows of drug_code_overrides.csv, comment lines skipped."""
    if not path.exists():
        return []
    lines = [line for line in path.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


# --- network --------------------------------------------------------------------------

class _Client:
    """One kept-alive HTTPS connection to RxNav, paced to 10 requests a second."""

    def __init__(self):
        self._conn = None
        self._last = 0.0
        self.calls = 0

    def get(self, path: str) -> dict:
        for attempt in range(_ATTEMPTS):
            wait = self._last + _MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPSConnection(HOST, timeout=_TIMEOUT_S)
                self._conn.request("GET", path, headers={
                    "User-Agent": _USER_AGENT, "Accept": "application/json"})
                resp = self._conn.getresponse()
                body = resp.read()
                self.calls += 1
            except (OSError, http.client.HTTPException):
                self.close()
                if attempt + 1 == _ATTEMPTS:
                    raise
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.status == 404:
                return {}
            if resp.status >= 500 and attempt + 1 < _ATTEMPTS:
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.status != 200:
                raise RuntimeError(f"RxNav answered {resp.status} for {path}")
            text = body.decode("utf-8", "replace").strip()
            return json.loads(text) if text else {}
        return {}

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None


# --- fetcher --------------------------------------------------------------------------

class DrugCodesRxNavFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, budget_s: float = RUN_BUDGET_S, get=None,
                 overrides_path=None):
        super().__init__(db_path)
        self.budget_s = budget_s
        self._client = _Client() if get is None else None
        self._get = get or self._client.get
        self.overrides_path = Path(overrides_path) if overrides_path else OVERRIDES_PATH
        self._notes: list[str] = []
        self._errors: list[str] = []
        self._version = None
        self._named: dict = {}                  # labeler code -> names RxNav gave it

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _within_ttl(self) -> bool:
        # The guard is per asset, in _due_assets, so that it holds under force and a
        # launch gets its codes on the next run rather than a month later.
        return False

    # --- what is due ------------------------------------------------------------------
    def _due_assets(self, conn) -> list[dict]:
        cutoff = (dt.datetime.now(dt.timezone.utc)
                  - dt.timedelta(seconds=self.ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """
            SELECT a.id, a.brand_name, a.generic_name, a.owner_company_id,
                   (SELECT group_concat(DISTINCT p.application_number)
                      FROM approvals p
                     WHERE p.asset_id = a.id AND p.application_number <> '') AS apps,
                   l.application_numbers AS looked_apps, l.looked_up_at
              FROM assets a
              LEFT JOIN drug_code_lookups l ON l.asset_id = a.id
             WHERE a.is_marketed = 1
             ORDER BY a.id
            """).fetchall()
        due = []
        for row in rows:
            apps = sorted({a.strip().upper() for a in (row["apps"] or "").split(",")
                           if a.strip()})
            joined = ",".join(apps)
            if row["looked_up_at"] is None:
                rank = 0
            elif (row["looked_apps"] or "") != joined:
                rank = 1
            elif row["looked_up_at"] < cutoff:
                rank = 2
            else:
                continue
            due.append({"asset_id": row["id"], "brand_name": row["brand_name"],
                        "generic_name": row["generic_name"],
                        "company_id": row["owner_company_id"], "apps": apps,
                        "_rank": (rank, row["looked_up_at"] or "", row["id"])})
        due.sort(key=lambda d: d["_rank"])
        return due

    def _owner_words(self, conn) -> dict:
        """{company_id: distinctive words of every name the company is known by}."""
        words: dict = {}
        for row in conn.execute(
                "SELECT id, name, openfda_manufacturer, openfda_sponsor,"
                " orange_book_applicant, purple_book_applicant FROM companies"):
            names = [row["name"]]
            for column in ("openfda_manufacturer", "openfda_sponsor",
                           "orange_book_applicant", "purple_book_applicant"):
                names.extend((row[column] or "").split("|"))
            words[row["id"]] = set().union(*(distinctive_words(n) for n in names))
        for row in conn.execute(
                "SELECT DISTINCT company_id, labeler_name FROM ndc_products"
                " WHERE labeler_name IS NOT NULL"):
            words.setdefault(row["company_id"], set()).update(
                distinctive_words(row["labeler_name"]))
        return words

    # --- fetch ------------------------------------------------------------------------
    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            due = self._due_assets(conn)
            owner_words = self._owner_words(conn)
            # Labeler names an earlier run read, so a code named on a drug looked up
            # last month is still named on one looked up today.
            known_labelers = [(r["labeler_code"], r["labeler_name"]) for r in conn.execute(
                "SELECT DISTINCT labeler_code, labeler_name FROM drug_codes"
                " WHERE labeler_name IS NOT NULL")]
        finally:
            conn.close()
        if not due:
            self._notes.append("rxnav_codes: every marketed asset was looked up in the "
                               "last 30 days, so nothing was fetched")
            return {"version": None, "lookups": [], "due": 0, "pending": 0,
                    "owner_words": owner_words, "known_labelers": known_labelers}
        self._version = (self._get("/REST/version.json") or {}).get("version")
        for code, name in known_labelers:
            self._named.setdefault(code, set()).add(name)
        started = time.monotonic()
        lookups, cache, failed_in_a_row, pending = [], {}, 0, 0
        for index, asset in enumerate(due):
            if time.monotonic() - started > self.budget_s:
                pending = len(due) - index
                self._notes.append(
                    f"rxnav_codes: stopped at the {int(self.budget_s)}s run budget with "
                    f"{pending} of {len(due)} assets left for the next run")
                break
            try:
                lookups.append(self._lookup(asset, cache))
                failed_in_a_row = 0
            except Exception as exc:
                failed_in_a_row += 1
                self._errors.append(
                    f"rxnav_codes: {asset['brand_name'] or asset['generic_name']} "
                    f"(asset {asset['asset_id']}): {exc}")
                if failed_in_a_row >= _GIVE_UP_AFTER:
                    pending = len(due) - index - 1
                    self._errors.append(
                        f"rxnav_codes: {_GIVE_UP_AFTER} lookups failed in a row, so the "
                        f"run stopped with {pending} assets left")
                    break
        if self._client is not None:
            self._client.close()
        return {"version": self._version, "lookups": lookups, "due": len(due),
                "pending": pending, "owner_words": owner_words,
                "known_labelers": known_labelers}

    def _lookup(self, asset: dict, cache: dict) -> dict:
        found: dict = {}                         # rxcui -> the application it came from
        notes = []
        for app in asset["apps"]:
            match = _APPLICATION.match(app)
            if not match:
                notes.append(f"{app} is not an NDA, BLA or ANDA number and was not sent")
                continue
            query = urllib.parse.urlencode({"idtype": match.group(1), "id": app})
            for rxcui in parse_rxcui_ids(self._get(f"/REST/rxcui.json?{query}")):
                found.setdefault(rxcui, app)
        known: dict = {}
        concept = self._brand_concept(asset)
        if concept:
            known = parse_related(self._get(
                f"/REST/rxcui/{concept}/related.json?tty=SBD+BPCK"))
        by_application = bool(found)
        for rxcui in known:
            found.setdefault(rxcui, None)
        basis = ("rxnav_application" if by_application
                 else "rxnav_brand_name" if found else None)
        concepts = []
        for rxcui, app in found.items():
            if rxcui not in cache:
                cache[rxcui] = self._concept(rxcui, known.get(rxcui))
            concepts.append({**self._concept_for(cache[rxcui], app), "rxcui": rxcui,
                             "application_number": app})
        if not found:
            notes.append("RxNav returned no code for the application numbers"
                         if asset["apps"] else "no application number, and no RxNorm "
                                               "brand concept spelled as the brand")
        return {**asset, "basis": basis, "concepts": concepts, "note": "; ".join(notes)}

    def _brand_concept(self, asset: dict) -> str | None:
        """The RxCUI of the brand-name concept (TTY BN) spelled exactly as the brand."""
        brand = re.sub(r"\s+", " ", (asset.get("brand_name") or "").strip())
        generic = re.sub(r"\s+", " ", (asset.get("generic_name") or "").strip())
        if not brand or brand.lower() == generic.lower():
            return None
        query = urllib.parse.urlencode({"name": brand, "search": 2})
        for rxcui in parse_rxcui_ids(self._get(f"/REST/rxcui.json?{query}")):
            props = (self._get(f"/REST/rxcui/{rxcui}/properties.json") or {}).get(
                "properties") or {}
            name = re.sub(r"\s+", " ", (props.get("name") or "").strip())
            if props.get("tty") == "BN" and name.lower() == brand.lower():
                return rxcui
        return None

    def _concept(self, rxcui: str, known: dict | None) -> dict:
        props = known or ((self._get(f"/REST/rxcui/{rxcui}/properties.json") or {})
                          .get("properties") or {})
        tty = props.get("tty")
        if tty not in BRAND_TTYS:
            # A clinical drug or a generic pack is every manufacturer's: the NDC history
            # of metoprolol succinate 25 MG lists 504 codes, nearly all of them other
            # companies' generics. So only the active NDCs labelled under the asset's own
            # application are taken (its authorised generics, or its ANDA products), and
            # a kit component such as the alcohol pad in a biologic's carton takes none.
            listed = parse_ndc_properties(self._get(f"/REST/ndcproperties.json?id={rxcui}"))
            self._name_labelers(listed)
            return {"tty": tty, "name": props.get("name"), "ndcs": None, "listed": listed}
        history = parse_history(self._get(f"/REST/rxcui/{rxcui}/allhistoricalndcs.json"))
        # Labeler names come only from active NDCs, so the call is made only when an
        # active NDC's labeler has not been named yet in this run or an earlier one.
        # Repackagers recur across hundreds of drugs; asking each time tripled the run.
        current = self._current_month(history)
        unnamed = {ndc.labeler(n["ndc11"]) for n in history
                   if current and n["end"] and n["end"] >= current} - set(self._named)
        listed = {}
        if unnamed:
            listed = parse_ndc_properties(self._get(f"/REST/ndcproperties.json?id={rxcui}"))
            self._name_labelers(listed)
        return {"tty": tty, "name": props.get("name"), "ndcs": history, "listed": listed}

    def _current_month(self, history: list[dict]) -> str | None:
        return _version_month(self._version) or max(
            (n["end"] for n in history if n["end"]), default=None)

    def _name_labelers(self, listed: dict) -> None:
        for ndc11, info in listed.items():
            if info["labeler"]:
                self._named.setdefault(ndc.labeler(ndc11), set()).add(info["labeler"])

    def _concept_for(self, concept: dict, app: str | None) -> dict:
        """A cached concept as one asset sees it: a branded concept's whole NDC history,
        or an unbranded one's active NDCs marketed under this asset's application."""
        listed = concept["listed"]
        labelers = {code: info["labeler"] for code, info in listed.items()
                    if info["labeler"]}
        if concept["ndcs"] is not None:
            return {"tty": concept["tty"], "name": concept["name"],
                    "ndcs": concept["ndcs"], "labelers": labelers}
        current = _version_month(self._version)
        own = [{"ndc11": code, "start": info["start"], "end": current}
               for code, info in sorted(listed.items())
               if app and info["application"] == app]
        return {"tty": concept["tty"], "name": concept["name"], "ndcs": own,
                "labelers": labelers}

    # --- normalise --------------------------------------------------------------------
    def normalise(self, raw: dict) -> list[dict]:
        labeler_names: dict = {}
        for code, name in raw.get("known_labelers") or ():
            labeler_names.setdefault(code, set()).add(name)
        for lookup in raw["lookups"]:
            for concept in lookup["concepts"]:
                for ndc11, name in concept["labelers"].items():
                    labeler_names.setdefault(ndc.labeler(ndc11), set()).add(name)
        bundles = []
        for lookup in raw["lookups"]:
            rows = asset_rows(lookup, raw["owner_words"].get(lookup["company_id"], set()),
                              labeler_names)
            bundles.append({
                "asset_id": lookup["asset_id"], "apps": ",".join(lookup["apps"]),
                "basis": lookup["basis"], "rows": rows, "note": lookup["note"] or None,
                "rxcuis": sum(r["code_type"] == "rxcui" for r in rows),
                "ndc9s": sum(r["code_type"] == "ndc9" for r in rows)})
        self._raw_meta = {k: raw[k] for k in ("version", "due", "pending")}
        return bundles

    # --- snapshot ---------------------------------------------------------------------
    def snapshot(self, bundles: list[dict]) -> None:
        meta = getattr(self, "_raw_meta", {})
        if not bundles:
            self._snapshot_cache()          # nothing due: the table, as it stands
            return
        conn = db.get_connection(self.db_path)
        try:
            claims, assets = self._claims_after(conn, bundles)
        finally:
            conn.close()
        payload = {
            "assets_looked_up": len(bundles),
            "assets_with_rxcui": sum(1 for b in bundles if b["rxcuis"]),
            "rxcuis": len({r["code"] for b in bundles for r in b["rows"]
                           if r["code_type"] == "rxcui"}),
            "ndc9s": len({r["code"] for b in bundles for r in b["rows"]
                          if r["code_type"] == "ndc9"}),
            "conflicts": len(settle_claims(claims, assets)),
            "assets_pending": meta.get("pending", 0),
            "rxnorm_version": meta.get("version"),
            "fetch_kind": "live",
        }
        self._write_snapshot(payload)

    def _claims_after(self, conn, bundles: list[dict]):
        """Every (code_type, code) -> {asset id: RxNorm name} the table will hold once
        the batch is written, and the assets' names, for the conflict count."""
        replaced = {b["asset_id"] for b in bundles}
        claims: dict = {}
        for row in conn.execute(
                "SELECT asset_id, code_type, code, name, basis FROM drug_codes"):
            if row["asset_id"] in replaced and row["basis"] != "curated":
                continue
            claims.setdefault((row["code_type"], row["code"]), {})[row["asset_id"]] = \
                row["name"]
        for bundle in bundles:
            for row in bundle["rows"]:
                claims.setdefault((row["code_type"], row["code"]), {})[
                    bundle["asset_id"]] = row["name"]
        assets = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, brand_name, generic_name FROM assets")}
        return claims, assets

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            counts = conn.execute(
                "SELECT COUNT(DISTINCT CASE WHEN code_type = 'rxcui' THEN asset_id END),"
                " COUNT(DISTINCT CASE WHEN code_type = 'rxcui' THEN code END),"
                " COUNT(DISTINCT CASE WHEN code_type = 'ndc9' THEN code END)"
                " FROM drug_codes").fetchone()
        finally:
            conn.close()
        self._write_snapshot({"assets_with_rxcui": counts[0], "rxcuis": counts[1],
                              "ndc9s": counts[2], "fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    # --- upsert -----------------------------------------------------------------------
    def upsert(self, bundles: list[dict]) -> RefreshResult:
        meta = getattr(self, "_raw_meta", {})
        written = 0
        conn = db.get_connection(self.db_path)
        try:
            for bundle in bundles:
                with conn:                      # one asset, one transaction
                    conn.execute("DELETE FROM drug_codes WHERE asset_id = ?"
                                 " AND basis <> 'curated'", (bundle["asset_id"],))
                    for row in bundle["rows"]:
                        cur = conn.execute(
                            """
                            INSERT INTO drug_codes
                                (asset_id, code_type, code, tty, name, rxcui,
                                 brand_specific, labeler_code, labeler_name, first_ym,
                                 last_ym, is_owner_labeler, basis, application_number)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(asset_id, code_type, code) DO NOTHING
                            """,
                            (bundle["asset_id"], row["code_type"], row["code"],
                             row["tty"], row["name"], row["rxcui"],
                             row["brand_specific"], row["labeler_code"],
                             row["labeler_name"], row["first_ym"], row["last_ym"],
                             row["is_owner_labeler"], row["basis"],
                             row["application_number"]))
                        written += cur.rowcount
                    conn.execute(
                        """
                        INSERT INTO drug_code_lookups
                            (asset_id, application_numbers, basis, rxcuis, ndc9s,
                             rxnorm_version, note, looked_up_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(asset_id) DO UPDATE SET
                            application_numbers = excluded.application_numbers,
                            basis = excluded.basis, rxcuis = excluded.rxcuis,
                            ndc9s = excluded.ndc9s,
                            rxnorm_version = excluded.rxnorm_version,
                            note = excluded.note, looked_up_at = datetime('now')
                        """,
                        (bundle["asset_id"], bundle["apps"], bundle["basis"],
                         bundle["rxcuis"], bundle["ndc9s"], meta.get("version"),
                         bundle["note"]))
            with conn:
                self._apply_overrides(conn)
                self._drop_conflicts(conn)
        finally:
            conn.close()
        return RefreshResult(self.source, written, errors=list(self._errors),
                             notes=list(self._notes))

    def _apply_overrides(self, conn) -> None:
        for row in read_overrides(self.overrides_path):
            brand, ticker = (row.get("asset_brand") or "").strip(), (
                row.get("ticker") or "").strip().upper()
            code_type, code = (row.get("code_type") or "").strip(), (
                row.get("code") or "").strip()
            action, source = (row.get("action") or "").strip().lower(), (
                row.get("source") or "").strip()
            if code_type not in ("rxcui", "ndc9") or not code or not source \
                    or action not in ("add", "remove"):
                self._notes.append(f"rxnav_codes: override {brand} {code} is incomplete "
                                   f"and was not applied")
                continue
            if code_type == "ndc9":
                code = ndc.product_ndc9(code) or ndc.ndc9(code) or ""
                if not code:
                    self._notes.append(f"rxnav_codes: override {brand} carries an NDC "
                                       f"that does not parse and was not applied")
                    continue
            hit = conn.execute(
                "SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id"
                " WHERE c.ticker = ? AND lower(a.brand_name) = lower(?)",
                (ticker, brand)).fetchone()
            if hit is None:
                self._notes.append(f"rxnav_codes: override {ticker} {brand} names no "
                                   f"asset and was not applied")
                continue
            if action == "remove":
                conn.execute("DELETE FROM drug_codes WHERE asset_id = ? AND code_type = ?"
                             " AND code = ?", (hit["id"], code_type, code))
                continue
            tty = (row.get("tty") or "").strip().upper() or None
            conn.execute(
                """
                INSERT INTO drug_codes (asset_id, code_type, code, tty, brand_specific,
                                        labeler_code, basis, source_note)
                VALUES (?, ?, ?, ?, ?, ?, 'curated', ?)
                ON CONFLICT(asset_id, code_type, code) DO UPDATE SET
                    basis = 'curated', source_note = excluded.source_note,
                    tty = COALESCE(excluded.tty, drug_codes.tty),
                    brand_specific = COALESCE(excluded.brand_specific,
                                              drug_codes.brand_specific)
                """,
                (hit["id"], code_type, code, tty,
                 int(tty in BRAND_TTYS) if tty else None,
                 code[:5] if code_type == "ndc9" else None, source))

    def _drop_conflicts(self, conn) -> None:
        """Settle the codes several assets claim (settle_claims), and say so once per
        set of assets rather than once per code."""
        claims: dict = {}
        for row in conn.execute("SELECT asset_id, code_type, code, name FROM drug_codes"):
            claims.setdefault((row["code_type"], row["code"]), {})[row["asset_id"]] = \
                row["name"]
        assets = {r["id"]: dict(r) for r in conn.execute(
            "SELECT a.id, a.brand_name, a.generic_name, c.ticker FROM assets a"
            " JOIN companies c ON c.id = a.owner_company_id")}
        grouped: dict = {}
        for code_type, code, kept, dropped in settle_claims(claims, assets):
            conn.executemany(
                "DELETE FROM drug_codes WHERE asset_id = ? AND code_type = ? AND code = ?"
                " AND basis <> 'curated'", [(a, code_type, code) for a in dropped])
            grouped.setdefault((tuple(kept), tuple(dropped)), []).append(
                (code_type, code, claims[(code_type, code)]))

        def label(asset_id):
            a = assets.get(asset_id, {})
            return f"{a.get('ticker')} {a.get('brand_name') or a.get('generic_name')}"

        for (kept, dropped), codes in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            example_type, example, names = codes[0]
            example_name = next((n for n in names.values() if n), "")
            stays = (f"stay with {', '.join(label(a) for a in kept)}" if kept
                     else "name none of the claimants and were dropped")
            self._notes.append(
                f"rxnav_codes: {len(codes)} codes claimed by "
                f"{', '.join(label(a) for a in kept + dropped)} {stays}; dropped from "
                f"{', '.join(label(a) for a in dropped)} (for example {example_type} "
                f"{example}, {example_name})")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Map every marketed asset to its RxCUIs and NDC product codes.")
    parser.add_argument("--budget", type=float, default=RUN_BUDGET_S,
                        help="seconds before the run stops and leaves the rest")
    args = parser.parse_args(argv)
    fetcher = DrugCodesRxNavFetcher(budget_s=args.budget)
    fetcher.force = True
    result = fetcher.run()
    print(json.dumps({"rows_written": result.rows_fetched, "errors": result.errors,
                      "notes": result.notes, "elapsed_ms": result.elapsed_ms}, indent=1))


if __name__ == "__main__":
    main()
