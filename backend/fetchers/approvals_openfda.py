"""FDA approvals from openFDA drugsfda.

Queries drugsfda by both the sponsor name and the openFDA manufacturer name, and unions
the two. Neither field alone is enough. The manufacturer name is the legal entity that
holds the application, which for an acquired product is the company that was bought:
Bristol Myers Squibb holds Opdivo as E.R. Squibb & Sons, Revlimid as Celgene, Camzyos as
Myokardia, so a manufacturer query for Bristol found nothing. The sponsor name catches
those but misses the drugs an acquirer never re-registered, so both run and the results
are merged on application number.

Covers NDAs and BLAs, so approvals link to the same marketed assets the Orange and
Purple Book create, by application number.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import db
import acquired_sponsors
import company_names
from assets_util import normalize_appl, upsert_asset
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "approvals"
OPENFDA_SOURCE = "openfda"
TTL_SECONDS = 24 * 60 * 60

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30
_LIMIT = 100

# ticker -> openFDA manufacturer-name phrases (matched as phrases against the
# tokenized field). Distinctive short phrases match more product records.
MANUFACTURER_MAP = {
    "LLY": ["Eli Lilly and Company"],
    "NVO": ["Novo Nordisk"],
    "MRK": ["Merck Sharp & Dohme"],
    "PFE": ["Pfizer"],
    "ABBV": ["AbbVie"],
    "JNJ": ["Janssen"],
    "AZN": ["AstraZeneca"],
    "GSK": ["GlaxoSmithKline"],
    "NVS": ["Novartis"],
    "ROG": ["Genentech", "Hoffmann-La Roche"],
    "SNY": ["sanofi-aventis", "Genzyme"],
    "BMY": ["Bristol-Myers Squibb"],
    "AMGN": ["Amgen"],
    "GILD": ["Gilead Sciences"],
    "VRTX": ["Vertex Pharmaceuticals"],
    "REGN": ["Regeneron Pharmaceuticals"],
    "BIIB": ["Biogen"],
    "BAYN": ["Bayer"],
}

# ticker -> sponsor_name terms. A term search, not a phrase: a quoted phrase 404s here,
# and the terms match only the exact sponsor anyway (a Merck query returns none of
# Merck KGaA). The sponsor is the parent, so this is where an acquired product surfaces.
SPONSOR_MAP = {
    "LLY": "ELI LILLY", "NVO": "NOVO NORDISK", "MRK": "MERCK SHARP DOHME",
    "PFE": "PFIZER", "ABBV": "ABBVIE", "JNJ": "JANSSEN", "AZN": "ASTRAZENECA",
    "GSK": "GLAXOSMITHKLINE", "NVS": "NOVARTIS", "ROG": "GENENTECH", "SNY": "SANOFI",
    "BMY": "BRISTOL MYERS SQUIBB", "AMGN": "AMGEN", "GILD": "GILEAD",
    "VRTX": "VERTEX", "REGN": "REGENERON", "BIIB": "BIOGEN", "BAYN": "BAYER",
}

# ticker -> sponsor strings that are this company under another name, asked for as
# phrases. ``acquired_sponsors`` reads the deals table and so knows only the recent
# acquisitions; these are the older ones and the wholly-owned subsidiaries that never
# appear in a deal at all, and no rule derives them from the parent's name. ViiV is the
# large one: GlaxoSmithKline's entire HIV portfolio, ten marketed products, is filed
# under "VIIV HLTHCARE" and a GSK query reached none of it.
#
# An entry is only safe where the sponsor's whole portfolio belongs to the parent, so
# each was checked before it was added by asking openFDA for the sponsor and testing
# every brand it returned against the owner on file. A sponsor holding a product another
# company in the universe owns is a partner rather than a subsidiary and is left out: a
# "JANSSEN PHARMS" phrase returns 58 applications of which 22 are Johnson & Johnson's
# own, so adding it to Bayer for Xarelto would have credited Bayer with J&J's portfolio,
# and "CELGENE CORP" would have handed Bristol the Otezla application Amgen bought.
# Those products are reached by brand instead (``_by_brand_name``). "SCHERING" is left
# out for the same reason in reverse: it is both Merck's Schering-Plough and Bayer's
# Schering AG, and the phrase cannot tell them apart.
AFFILIATE_SPONSORS = {
    "GSK": ["VIIV HLTHCARE"],
    "SNY": ["GENZYME"],
    "JNJ": ["JANSSEN PRODS", "CENTOCOR INC"],
    "ABBV": ["APIL", "IMMUNOGEN INC"],
    "LLY": ["IMCLONE"],
    "LNTH": ["PROGENICS PHARMS INC"],
    "INCY": ["MORPHOSYS US INC"],
}


# How many molecules to ask about per company. Every one is a request, and a company
# with two hundred assets would otherwise make two hundred of them for the handful that
# are approved. Ordered by name so the cap is at least deterministic.
_MAX_GENERIC_QUERIES = 60
# The brand route runs after the other four and only over what they left, so its cap is
# the size of a plausible remaining gap rather than a portfolio.
_MAX_BRAND_QUERIES = 40
_MIN_BRAND_CHARS = 4
_POLITE_SLEEP_S = 0.12

# Below this a name is too short to identify a molecule and the query would be too broad
# to trust.
_MIN_MOLECULE_CHARS = 6

# A company's internal code is not a generic name and matches nothing here: ARGX-124,
# BEAM-101, FB102, LY3437943. The test used to be a digit anywhere in the name, which
# also threw away every radiodiagnostic, because an isotope belongs to the name and
# openFDA indexes it there: Pylarify is "Piflufolastat F-18" and asking for exactly that
# returns NDA214793. So the test is the shape of a code instead, one token of a short
# alphabetic prefix and a number, which "Piflufolastat F-18" is not.
_CODE_NAME = re.compile(r"^[A-Za-z]{1,6}[-\s]?\d+[A-Za-z]?$")

# Words too common in a drug company's name to identify one. Without these, every
# "Pharmaceuticals" matches every other.
_COMMON_NAME_WORDS = {
    "inc", "corp", "corporation", "company", "co", "plc", "ltd", "limited", "holdings",
    "group", "holding", "the", "and", "pharmaceuticals", "pharmaceutical", "pharms",
    "pharma",
    "therapeutics", "biosciences", "bioscience", "sciences", "science", "biopharma",
    "biopharmaceuticals", "medicines", "laboratories", "labs", "health", "healthcare",
    "usa", "us", "america", "american", "international", "global", "nv", "sa", "ag",
    "as", "gmbh", "llc", "lp",
}


# How a trial names the same molecule twice: "Oral Treprostinil" and "Parenteral
# Treprostinil" are one drug given two ways, and openFDA indexes neither. The route and
# the form are stripped so the molecule is what gets asked for.
_FORM_WORDS = re.compile(
    r"^(?:oral|parenteral|inhaled|nebuli[sz]ed|intravenous|iv|subcutaneous|sc|topical|"
    r"injectable|injection|solution|tablet|capsule|extended[- ]release|autoinjector|"
    r"prefilled|recombinant|human|sterile)\s+", re.I)


def _molecule(generic: str) -> str:
    """A generic name reduced to the molecule, with the route and form removed."""
    text = (generic or "").strip()
    for _ in range(3):                      # "Oral Extended-Release Treprostinil"
        stripped = _FORM_WORDS.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text.strip()


# The FDA's nonproprietary name for a biologic ends in a hyphen and four meaningless
# letters, and the Purple Book is where the generic name on file comes from, so that is
# the form stored: "efgartigimod alfa-fcab". openFDA indexes the core name without it,
# so the exact-phrase query answered 404 while the BLA sat there under "EFGARTIGIMOD
# ALFA", and argenx showed two marketed products and no approval record for either.
_BIOLOGIC_SUFFIX = re.compile(r"-[a-z]{4}$", re.I)


def _query_forms(molecule: str) -> list[str]:
    """Every spelling of one molecule worth asking openFDA for, the stored one first.

    The suffix is asked for as well, never instead. A biosimilar keeps it in openFDA,
    which writes Inflectra as "INFLIXIMAB-DYYB", so stripping it unconditionally would
    lose the approvals the stored form already found. Both forms cost one request each
    and the results merge on application number, so asking twice is cheap and safe.
    """
    molecule = (molecule or "").strip()
    if not molecule:
        return []
    forms = [molecule]
    core = _BIOLOGIC_SUFFIX.sub("", molecule).strip()
    if core != molecule and len(core) >= _MIN_MOLECULE_CHARS:
        forms.append(core)
    return forms


def _molecules(generic: str) -> list[str]:
    """The molecules in a generic name, because a combination product holds several.

    openFDA stores a combination as one string with its parts joined by a semicolon,
    "Bupropion Hydrochloride; Dextromethorphan Hydrobromide". Asked for that inside a
    quoted phrase its parser answers 400 BAD_REQUEST, "Search not supported", and the
    fetcher only ever expected a 404, so Axsome lost its approvals to a raised error on
    refresh run 114. Each part asked for on its own returns results.

    Deduped and order-preserving, so a name repeating a salt asks once.
    """
    seen, out = set(), []
    for part in re.split(r"[;/]", generic or ""):
        molecule = _molecule(part)
        if molecule and molecule.lower() not in seen:
            seen.add(molecule.lower())
            out.append(molecule)
    return out


def _distinctive_words(name: str) -> set:
    """The words in a name that could identify the company.

    openFDA abbreviates a sponsor to "ALNYLAM PHARMS INC" or "UNITED THERAP", so an
    exact comparison is useless and the shared distinctive word is what survives. A
    prefix is enough on both sides, since "THERAP" is how it writes "Therapeutics".
    """
    words = set()
    for word in re.split(r"[^A-Za-z]+", (name or "").lower()):
        if len(word) >= 4 and word not in _COMMON_NAME_WORDS:
            words.add(word)
    return words


def _approval_date(submissions) -> str | None:
    """Earliest original approval date (YYYYMMDD -> ISO) from the submissions list."""
    dates = [
        s.get("submission_status_date")
        for s in submissions or []
        if s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"
        and s.get("submission_status_date")
    ]
    if not dates:
        return None
    raw = min(dates)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else None


def _modality(application_number: str) -> str:
    return "biologic" if application_number.upper().startswith("BLA") else "small molecule"


def _iso(raw) -> str | None:
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else None


def parse_drugsfda(payload: dict, ticker: str) -> list[dict]:
    """Turn a drugsfda payload into approval rows. Pure."""
    rows = []
    for result in payload.get("results", []):
        appl = (result.get("application_number") or "").upper()
        match = re.match(r"([A-Za-z]+)(\d+)", appl)
        if not match:
            continue
        internal_code = normalize_appl(match.group(1), match.group(2))
        approval_date = _approval_date(result.get("submissions"))
        if approval_date is None:
            continue
        products = result.get("products") or [{}]
        brand = products[0].get("brand_name")
        generic = _generic(result, products[0])
        rows.append(
            {
                "ticker": ticker,
                "internal_code": internal_code,
                "application_number": appl,
                "brand": brand.title() if brand else None,
                "generic": generic,
                "modality": _modality(appl),
                "approval_date": approval_date,
                "marketing_status": products[0].get("marketing_status"),
                "active_ingredients": _ingredients(products[0]),
            }
        )
    return rows


def _ingredients(product: dict) -> list:
    """Every active ingredient the product contains, in the order the payload gives them.

    ``_generic`` below keeps only the first, which is right for it: the generic name is
    what binds a trial's intervention to an asset, and "Budesonide" matches a budesonide
    study where the full triple would not. But the first ingredient alone cannot tell
    Breztri, which is budesonide with glycopyrrolate and formoterol, from Rhinocort, which
    is a budesonide nasal spray, and molecule grouping has to.
    """
    return [str(item["name"]).title()
            for item in (product.get("active_ingredients") or [])
            if item.get("name")]


def _generic(result: dict, product: dict) -> str | None:
    """The active ingredient behind a brand, from the product entry or the openFDA
    block, or None when the payload states neither.

    Without it a marketed product is only its brand, and the registry names drugs by
    ingredient: Jaypirca and pirtobrutinib were two rows for one drug, which put an
    approved product in the pipeline as an unapproved compound. Title case, since the
    payload shouts and the rest of the app does not.
    """
    ingredients = product.get("active_ingredients") or []
    if ingredients and ingredients[0].get("name"):
        return str(ingredients[0]["name"]).title()
    openfda = (result.get("openfda") or {}).get("generic_name") or []
    return str(openfda[0]).title() if openfda else None


def parse_supplements(payload: dict, ticker: str) -> list[dict]:
    """Approved efficacy supplements from the same payload. Pure.

    An entry in submissions[] with class EFFICACY and status AP is a label expansion
    that already happened; the application number and the approval date come straight
    off it, so no second call is needed.
    """
    rows = []
    for result in payload.get("results", []):
        appl = (result.get("application_number") or "").upper()
        if not re.match(r"[A-Za-z]+\d+", appl):
            continue
        brand = (result.get("products") or [{}])[0].get("brand_name")
        for sub in result.get("submissions") or []:
            if sub.get("submission_class_code") != "EFFICACY" \
                    or sub.get("submission_status") != "AP":
                continue
            approval_date = _iso(sub.get("submission_status_date"))
            if approval_date is None:
                continue
            rows.append({
                "ticker": ticker,
                "application_number": appl,
                "internal_code": normalize_appl(
                    *re.match(r"([A-Za-z]+)(\d+)", appl).groups()),
                "submission_number": str(sub.get("submission_number") or ""),
                "submission_class_code": "EFFICACY",
                "approval_date": approval_date,
                "brand": brand.title() if brand else None,
                "description": sub.get("submission_class_code_description")
                or "Efficacy supplement",
            })
    return rows


class ApprovalsOpenFdaFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company_id(self, conn) -> int | None:
        row = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()
        return row[0] if row else None

    def _run(self, query: str) -> list[dict]:
        params = {"search": query, "limit": _LIMIT}
        api_key = (os.getenv("OPENFDA_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key
        url = f"{DRUGSFDA_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8")).get("results", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # openFDA returns 404 for no matches
                return []
            raise

    def _by_generic_name(self, marketed_only: bool = False) -> list[dict]:
        """Approvals found by asking openFDA for each molecule this company develops.

        Only molecules with no approval on file are asked about. An asset already linked
        to an application has nothing to discover, so a second refresh costs a fraction
        of the first and the cap is spent on the gap rather than on re-confirming what is
        already known. Marketed assets are asked about first for the same reason: a
        marketed product with no approval row is the gap this route exists to close, and
        an unapproved pipeline compound returning 404 is the expected answer.

        ``marketed_only`` narrows it further, and is how a company the maps *do* know
        runs this route: its portfolio already arrives by manufacturer and sponsor, so
        discovery is there to reach the handful those two queries miss, not to spend
        sixty requests re-asking about its pipeline.

        Every result is checked against the company's own name before it is kept: a
        generic can be sold by a dozen manufacturers, and treprostinil returns nine
        applications of which only some are United Therapeutics'. The check is a shared
        distinctive word, which is what survives openFDA's abbreviations.
        """
        conn = db.get_connection(self.db_path)
        try:
            company = conn.execute(
                "SELECT id, name FROM companies WHERE ticker = ?",
                (self.ticker,)).fetchone()
            if company is None:
                return []
            generics = [r[0] for r in conn.execute(
                "SELECT generic_name FROM assets a"
                "  WHERE a.owner_company_id = ? AND a.generic_name IS NOT NULL"
                "    AND NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id)"
                + ("    AND a.is_marketed = 1" if marketed_only else "") +
                "  GROUP BY a.generic_name"
                "  ORDER BY MAX(a.is_marketed) DESC, a.generic_name LIMIT ?",
                (company["id"], _MAX_GENERIC_QUERIES))]
        finally:
            conn.close()
        if not generics:
            return []

        wanted = _distinctive_words(company["name"])
        found = []
        asked = set()
        for stored in generics:
            for generic in _molecules(stored):
                if len(generic) < _MIN_MOLECULE_CHARS or _CODE_NAME.match(generic):
                    continue
                for form in _query_forms(generic):
                    if form.lower() in asked:
                        continue
                    asked.add(form.lower())
                    found += self._for_molecule(form, wanted)
        return found

    def _by_brand_name(self, found_so_far: list = ()) -> list[dict]:
        """Approvals found by asking openFDA for the brand of a marketed product that
        still has no approval on file.

        The last route, and the only one that reaches a product the company co-markets.
        Xarelto is Bayer's and its United States application is Janssen's, Eylea is
        Bayer's and Regeneron's, Beyfortus is Sanofi's and AstraZeneca's: no query built
        on the owner's name can find any of them, and a sponsor query wide enough to
        catch one drags in the partner's whole portfolio with it.

        A brand does not have that problem. It names one product, the asset on file says
        this company sells it, and the match is exact rather than a shared word, so the
        result is the approval record for that product and nothing else. The approval
        stays the applicant's; what is taken from it is the date, which is the thing the
        page was missing.

        Only marketed assets with no approval row are asked about, so this costs the
        size of the remaining gap and shrinks to nothing as it closes.
        """
        conn = db.get_connection(self.db_path)
        try:
            company = conn.execute(
                "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)).fetchone()
            if company is None:
                return []
            brands = [r[0] for r in conn.execute(
                "SELECT DISTINCT a.brand_name FROM assets a"
                "  WHERE a.owner_company_id = ? AND a.is_marketed = 1"
                "    AND a.brand_name IS NOT NULL"
                "    AND NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id)"
                "  ORDER BY a.brand_name LIMIT ?",
                (company["id"], _MAX_BRAND_QUERIES))]
        finally:
            conn.close()

        # The query reads the gap as it stood when the run began, so a brand one of the
        # routes above has just answered is skipped rather than asked for twice.
        asked = {(p.get("brand_name") or "").strip().lower()
                 for result in found_so_far for p in result.get("products") or []}
        asked.discard("")
        found = []
        for stored in brands:
            # "Fluarix, Fluarix Quadrivalent" is one asset holding two brands; the first
            # is the one the application is filed under.
            brand = re.split(r"[,;]", stored or "")[0].strip()
            if len(brand) < _MIN_BRAND_CHARS or brand.lower() in asked:
                continue
            asked.add(brand.lower())
            for result in self._run(f'products.brand_name:"{brand}"'):
                # An exact brand match or nothing. A phrase query also returns the
                # longer names containing it, and "Humalog" would otherwise collect
                # every Humalog Mix application as though it were the same product.
                if any((p.get("brand_name") or "").strip().lower() == brand.lower()
                       for p in result.get("products") or []):
                    found.append(result)
            time.sleep(_POLITE_SLEEP_S)
        return found

    def _for_molecule(self, generic: str, wanted: set) -> list[dict]:
        """One molecule's approvals, kept only where the sponsor is this company.

        A generic can be sold by a dozen manufacturers, so every result is checked
        against the company's own name before it is kept.
        """
        found = []
        for result in self._run(f'openfda.generic_name:"{generic}"'):
            if _distinctive_words(result.get("sponsor_name") or "") & wanted:
                found.append(result)
        time.sleep(_POLITE_SLEEP_S)
        return found

    def fetch(self) -> dict:
        names = company_names.source_name(self.ticker, "openfda_manufacturer",
                                          MANUFACTURER_MAP.get(self.ticker), self.db_path)
        sponsor = company_names.source_name(self.ticker, "openfda_sponsor",
                                            SPONSOR_MAP.get(self.ticker), self.db_path)
        if isinstance(names, str):
            names = [names]

        results: list[dict] = []
        if names:
            phrase = " ".join(f'"{n}"' for n in names)
            results += self._run(f"openfda.manufacturer_name:({phrase})")
        if sponsor:
            results += self._run(f"sponsor_name:({sponsor})")
        # The products this company owns because it bought the company that registered
        # them. openFDA files an approval under the manufacturer named on it, and that
        # name is not updated when the manufacturer is acquired: Tavneos is filed under
        # ChemoCentryx years after Amgen bought it, so Amgen's own searches miss a drug
        # it sells. Each acquired name is asked for separately, so one that matches
        # nothing costs a 404 and no results rather than breaking the query.
        for acquired in acquired_sponsors.for_company(self.db_path, self.ticker):
            results += self._run(f'openfda.manufacturer_name:("{acquired}")')
        # The same thing for an acquisition old enough that no deal row records it, and
        # for a subsidiary that was never acquired at all because the parent created it.
        # Asked for by sponsor rather than manufacturer: ViiV holds the application, and
        # the manufacturer named on a ViiV product is a contract site.
        for affiliate in AFFILIATE_SPONSORS.get(self.ticker) or []:
            results += self._run(f'sponsor_name:"{affiliate}"')
            time.sleep(_POLITE_SLEEP_S)

        # Nothing found by company name, so ask by molecule instead. The maps above are
        # hand-keyed and a company absent from them was being treated as clinical-stage,
        # which was wrong about Neurocrine, Alnylam, Ionis, Sarepta, Moderna and United
        # Therapeutics: all six sell drugs and all six had no approval on file. Guessing
        # harder at the sponsor string does not fix it, because openFDA writes them as
        # "ALNYLAM PHARMS INC", "UNITED THERAP" and "INCYTE CORP", which no rule derives
        # from a company name.
        #
        # A generic name does not have that problem. It identifies one molecule, it is
        # what the registry gave us for every asset these companies own, and the answer
        # carries the sponsor so the match can be checked rather than assumed.
        # Run whenever the maps do not know this company, rather than when nothing at
        # all was found. Neurocrine has an acquisition, so its acquired-sponsor query
        # returned a single application and that was enough to skip the discovery route
        # entirely, leaving three of its four approvals unfound.
        #
        # Run it for a company the maps *do* know as well, over its marketed assets only.
        # Being in the map was treated as proof the portfolio had been found, and it is
        # not: a manufacturer query asks for one legal entity and a large company files
        # under many, so GSK's HIV portfolio sat under ViiV and Bristol's under the
        # companies it bought, and 217 of the 245 marketed products with no approval row
        # belonged to the eighteen companies the maps cover. Narrowing to marketed assets
        # keeps the cost to the size of the gap: a pipeline compound has no approval to
        # find, and the portfolio itself still arrives by manufacturer and sponsor.
        found = self._by_generic_name(marketed_only=bool(names or sponsor))
        results += found
        # The answers carry the sponsor string openFDA actually uses, which is the
        # thing no rule could derive: "ALNYLAM PHARMS INC", "UNITED THERAP",
        # "INCYTE CORP", "VIIV HLTHCARE". Asking for it directly then returns the rest
        # of the portfolio, since a molecule search only ever finds the molecules we
        # already knew about. Alnylam goes from one approval to four this way and
        # Incyte from two to six, and the map stays empty: the fetcher discovers
        # the name instead of being told it.
        #
        # A sponsor already asked for above is not asked for again, so the sweep costs
        # nothing when discovery only rediscovers the name the map already holds.
        for sponsor_name in sorted({r.get("sponsor_name") for r in found
                                    if r.get("sponsor_name")}):
            if sponsor and _distinctive_words(sponsor_name) & _distinctive_words(sponsor):
                continue
            results += self._run(f'sponsor_name:"{sponsor_name}"')
            time.sleep(_POLITE_SLEEP_S)

        # Last, and over whatever the four routes above still left: the marketed products
        # with no approval record, asked for by their own brand. See _by_brand_name.
        results += self._by_brand_name(results)

        # An application can come back from both queries. The application number is its
        # identity, so a later parse keying on it dedupes, but merging here keeps the
        # count honest and the payload small.
        seen, merged = set(), []
        for item in results:
            number = item.get("application_number")
            if number and number in seen:
                continue
            seen.add(number)
            merged.append(item)
        return {"results": merged}

    def normalise(self, raw) -> dict:
        # Both signals come from the one payload: the approvals, and the approved
        # efficacy supplements sitting inside the same submissions arrays.
        return {"approvals": parse_drugsfda(raw, self.ticker),
                "supplements": parse_supplements(raw, self.ticker)}

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: dict) -> None:
        approvals = rows["approvals"] if isinstance(rows, dict) else rows
        latest = max((r["approval_date"] for r in approvals), default=None)
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"ticker": self.ticker, "approvals": len(approvals),
                 "supplements": len(rows.get("supplements", []))
                 if isinstance(rows, dict) else 0,
                 "latest_approval": latest, "source": OPENFDA_SOURCE, "fetch_kind": "live"},
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return
            n = conn.execute(
                """
                SELECT COUNT(*) FROM approvals ap JOIN assets a ON ap.asset_id = a.id
                 WHERE a.owner_company_id = ? AND ap.source = ?
                """,
                (company_id, OPENFDA_SOURCE),
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"ticker": self.ticker, "approvals": n,
                                        "source": OPENFDA_SOURCE, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: dict) -> RefreshResult:
        approvals = rows["approvals"] if isinstance(rows, dict) else rows
        supplements = rows.get("supplements", []) if isinstance(rows, dict) else []
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            for row in approvals:
                asset_id = upsert_asset(
                    conn, company_id, row["internal_code"], row["brand"],
                    row["generic"], row["modality"],
                )
                if row.get("active_ingredients"):
                    conn.execute(
                        "UPDATE assets SET active_ingredients = ? WHERE id = ?",
                        (json.dumps(row["active_ingredients"]), asset_id))
                # Only this application's own row. A product can hold several: Cosentyx
                # is BLA125504 from 2015 and BLA761349, the intravenous form, from 2023,
                # and both resolve to one asset. Clearing every row first left whichever
                # application happened to be processed last, so Cosentyx read as a 2023
                # launch and its whole $6.7bn counted as revenue recent research had
                # bought. The earliest row is what first_approval reads.
                conn.execute(
                    "DELETE FROM approvals WHERE asset_id = ? AND source = ?"
                    "  AND application_number = ?",
                    (asset_id, OPENFDA_SOURCE, row["application_number"]),
                )
                conn.execute(
                    """
                    INSERT INTO approvals
                        (asset_id, region, agency, approval_date, application_number, source)
                    VALUES (?, 'US', 'FDA', ?, ?, ?)
                    """,
                    (asset_id, row["approval_date"], row["application_number"], OPENFDA_SOURCE),
                )
            # Efficacy supplements attach to the asset that holds the application, so
            # they resolve against the same internal_code the approval created.
            for sup in supplements:
                asset = conn.execute(
                    "SELECT id FROM assets WHERE owner_company_id = ?"
                    " AND internal_code = ?",
                    (company_id, sup["internal_code"])).fetchone()
                conn.execute(
                    """
                    INSERT INTO supplements (asset_id, application_number,
                        submission_number, submission_class_code, approval_date,
                        description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(application_number, submission_number) DO UPDATE SET
                        approval_date=excluded.approval_date,
                        asset_id=excluded.asset_id, fetched_at=datetime('now')
                    """,
                    (asset["id"] if asset else None, sup["application_number"],
                     sup["submission_number"], sup["submission_class_code"],
                     sup["approval_date"], sup["description"]))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(approvals) + len(supplements), [], False, 0)
