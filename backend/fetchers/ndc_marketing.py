"""What a company markets, from openFDA's NDC directory.

The approvals fetcher reads drugsfda, which is CDER's register and carries no CBER
biologics. Confirmed by asking it directly for BLA125614, BLA125742 and BLA125781:
Shingrix, Comirnaty and Elevidys all return 404. So every vaccine and most gene
therapies in this universe had no approval row, nothing they earn could be dated, and
GSK, Moderna and Sarepta could not be measured at all.

The NDC directory does list them. It is a register of packages rather than approvals, so
what it gives is the date a package began marketing and the application it was licensed
under, and the distinction is the whole caveat here: a product cannot be marketed before
it is approved, so this date is never earlier than the approval and is sometimes years
later. Comirnaty's earliest surviving record is the 2025 seasonal formulation, four years
after licensure, because the original packages have been delisted. The error runs one way
only, toward looking newer than the truth.

Against known approvals it is exact for Shingrix, Arexvy, Elevidys and Pylarify, one day
out on Beyfortus, two months on Prevnar 20, two years on Bexsero and four on Comirnaty.
Good enough to date a product, not good enough to be called an approval, and everything
downstream labels it as a marketing date.

The company is found by labeler name rather than a map, the same way the approvals
fetcher discovers a sponsor, and every record is checked against the company's own name
before it is kept: GlaxoSmithKline Biologicals is GSK, and a contract packager that
happens to distribute for them is not.

That check is stricter here than the approvals fetcher's shared distinctive word, and it
has to be. openFDA abbreviates a sponsor to "UNITED THERAP", so an approval can only be
matched on a word; a labeler is written out in full, so a labeler can be required to
carry all of them. Requiring one attached United Natural Foods' 88 groceries to United
Therapeutics, every Chinese cosmetics house with "Biotechnology" in its name to Sana,
and the whole Janssen catalogue to Krystal Biotech. Requiring all of them leaves those
three with 2, 0 and 1 rows, and takes nothing off any of the majors.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import company_names
import db
from fetchers.approvals_openfda import (
    MANUFACTURER_MAP, SPONSOR_MAP, _COMMON_NAME_WORDS)
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "ndc_marketing"
TTL_SECONDS = 7 * 24 * 60 * 60          # a marketing register changes slowly
NDC_URL = "https://api.fda.gov/drug/ndc.json"
_LIMIT = 100
_TIMEOUT_S = 40
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"

# The divisions a drugmaker labels its products under. A vaccine is labelled by the
# biologics arm, which is a different string from the parent: GSK's vaccines are
# "GlaxoSmithKline Biologicals SA" and its tablets are "GlaxoSmithKline LLC". Both are
# asked for, and the name check keeps anyone else's out.
_DIVISIONS = ("", " Biologicals", " Vaccines", " US", " USA", " LLC", " Inc")

# The words that say which company this is rather than what kind of company it is. The
# approvals fetcher drops "Therapeutics" as too common to identify anyone, and on its own
# it is. Held together with the rest of the name it does the work: United Therapeutics
# and United Natural Foods share "United" and nothing else, and neither does Century
# Therapeutics share anything but "Century" with Century Pharmaceuticals.
_LEGAL_FORMS = {
    "inc", "corp", "corporation", "company", "co", "plc", "ltd", "limited", "holdings",
    "group", "holding", "the", "and", "llc", "lp", "nv", "sa", "se", "ag", "as",
    "gmbh", "spa", "srl", "usa",
}


def company_words(name: str) -> set:
    """The words a labeler for this company would carry, its legal form aside.

    Four characters and up, which is what keeps "Eli Lilly and Company" from requiring
    "eli" of a labeler that writes itself "Lilly USA, LLC".
    """
    return {word for word in re.split(r"[^A-Za-z]+", (name or "").lower())
            if len(word) >= 4 and word not in _LEGAL_FORMS}


def _search_word(name: str) -> str | None:
    """The word to ask openFDA for, which is the head of the name rather than its
    longest word.

    A query returns 100 records and no more, so what it asks for decides what can be
    found at all. Asking for the longest word searched Krystal Biotech as "biotech" and
    Taysha Gene Therapies as "therapies", and both came back full of other people's
    products with the company's own row surviving on luck. The head of a name is the
    part that names the company.
    """
    for word in re.split(r"[^A-Za-z]+", (name or "").lower()):
        if len(word) >= 4 and word not in _COMMON_NAME_WORDS:
            return word
    return None


def _iso(raw) -> str | None:
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else None


def parse_ndc(payload: dict, required: list) -> dict:
    """{brand: (earliest marketing date, application number, labeler)} for this company.

    The earliest date across every package of a brand, because a brand reformulated each
    season carries one record per season and the newest says nothing about when the drug
    arrived.

    ``required`` is one word set per name the company is known by, and a labeler is kept
    when it carries every word of one of them. One set per name rather than one set
    overall, because a company answers to several names and no labeler answers to two:
    Johnson & Johnson labels its drugs Janssen, and demanding both words of both names at
    once would keep nothing.
    """
    best: dict = {}
    for row in payload.get("results", []):
        brand = (row.get("brand_name") or "").strip()
        started = _iso(row.get("marketing_start_date"))
        labeler = row.get("labeler_name") or ""
        if not brand or not started:
            continue
        if required:
            words = company_words(labeler)
            if not any(wanted <= words for wanted in required):
                continue
        current = best.get(brand)
        if current is None or started < current[0]:
            best[brand] = (started, row.get("application_number"), labeler)
    return best


class NdcMarketingFetcher(BaseFetcher):
    """One company's marketed brands and when each was first packaged."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _run(self, query: str) -> list[dict]:
        params = {"search": query, "limit": _LIMIT}
        api_key = (os.getenv("OPENFDA_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key
        request = urllib.request.Request(
            f"{NDC_URL}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8")).get("results", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:            # openFDA says 404 for no matches
                return []
            raise

    def _company(self, conn):
        return conn.execute(
            "SELECT id, name FROM companies WHERE ticker = ?", (self.ticker,)).fetchone()

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
        finally:
            conn.close()
        if company is None:
            return {"results": [], "company_id": None}

        # The names a labeler string could carry. The company's own name is not enough
        # and for several of the largest it is actively wrong: GSK is registered as
        # "GSK plc" and yields no distinctive word at all, Johnson & Johnson labels its
        # drugs "Janssen", and Roche labels them "Genentech". The openFDA names already
        # configured for the approvals fetcher hold exactly these strings, so they are
        # reused here rather than guessed at a second time.
        configured = company_names.source_name(
            self.ticker, "openfda_manufacturer",
            MANUFACTURER_MAP.get(self.ticker), self.db_path) or []
        if isinstance(configured, str):
            configured = [configured]
        sponsor = company_names.source_name(
            self.ticker, "openfda_sponsor", SPONSOR_MAP.get(self.ticker), self.db_path)
        candidates = list(configured) + ([sponsor] if sponsor else [])

        # Verified against the configured names alone where there are any, rather than
        # against those and the company name together. "SC Johnson Professional" shares
        # "johnson" with Johnson & Johnson and sells hand sanitiser, and unioning the two
        # sets let a dozen of its products in as J&J drugs. Where a name is configured
        # for this source it is the authority on what belongs to the company.
        if not candidates:
            # Nothing configured, so the company's own registered name is the name, and
            # openFDA is asked for the head of it. A name with no word that identifies
            # anyone is not asked for at all: "Vor Biopharma" would search "biopharma"
            # and verify against it, which every biopharma in the directory would pass.
            word = _search_word(company["name"])
            if not word:
                return {"results": [], "company_id": company["id"]}
            candidates = [company["name"]]
            stems = [word]
        else:
            stems = list(candidates)

        required = [words for words in (company_words(n) for n in candidates) if words]
        results: list[dict] = []
        for stem in dict.fromkeys(stems):
            for division in _DIVISIONS:
                results += self._run(f'labeler_name:"{stem}{division}"')
        return {"results": results, "company_id": company["id"], "required": required}

    def normalise(self, raw) -> list[dict]:
        if raw.get("company_id") is None:
            return []
        found = parse_ndc({"results": raw["results"]}, raw.get("required") or [])
        return [{"company_id": raw["company_id"], "brand_name": brand,
                 "first_marketed": started, "application_number": application,
                 "labeler_name": labeler}
                for brand, (started, application, labeler) in found.items()]

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'company', ?, ?, ?)",
                (self.source, self.ticker, json.dumps({"brands": len(rows)}),
                 self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        self.snapshot([])

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for row in rows:
                conn.execute(
                    "INSERT INTO ndc_products (company_id, brand_name,"
                    "  application_number, first_marketed, labeler_name, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, datetime('now'))"
                    " ON CONFLICT(company_id, brand_name) DO UPDATE SET"
                    "   application_number = excluded.application_number,"
                    "   first_marketed = MIN(ndc_products.first_marketed,"
                    "                        excluded.first_marketed),"
                    "   labeler_name = excluded.labeler_name,"
                    "   fetched_at = datetime('now')",
                    (row["company_id"], row["brand_name"], row["application_number"],
                     row["first_marketed"], row["labeler_name"]))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)
