"""Insider transactions from SEC Form 4, one company at a time.

A director, an officer or a holder of more than ten per cent reports every change in
what they own of the company on a Form 4, due two business days after the transaction.
This reads the forms filed about a company's own shares and stores each line of their
two transaction tables: Table I, the shares themselves, and Table II, the options,
warrants and convertibles. `insiders.py` is the reader built on top.

How the source is actually laid out, checked against live payloads on 2026-11-23:

  - `https://data.sec.gov/submissions/CIK{cik}.json` lists a company's Form 4s in the
    same `recent` arrays as its 8-Ks. `recent` holds about a thousand filings, which
    reached back past a year for every one of the 73 SEC filers in the universe.
  - That list mixes two things and does not say which is which: forms about the
    company's shares, and forms the company filed as a shareholder of somebody else.
    GSK's list holds its purchases of Wave Life Sciences, Sanofi's its conversions in
    two newly listed biotechs, Novartis's nothing newer than 2020 and all of it about
    other issuers. Only the document says who the issuer is, so every form is opened
    and one whose `issuerCik` is not the company's is set aside.
  - `primaryDocument` is the rendered view, `xslF345X06/ownership.xml` on a 2026 form
    (`X05` in 2025, `X03` before 2023). The raw XML is the same path without that first
    directory. The number follows the schema version, so the prefix is matched by
    pattern, not by name.
  - The root is `ownershipDocument`. Each value sits in a `<value>` child, beside the
    `footnoteId` that qualifies it. Flags are printed `1`/`0` by some filing agents and
    `true`/`false` by others, in the same schema version.
  - The Rule 10b5-1 box is `aff10b5One`, one for the whole form and not one a line. It
    is absent from a form filed before April 2023.

What a first run costs, and why there is a cap. The universe filed 3,120 Form 4s in the
year to 2026-11-23, and one company (United Therapeutics, whose executives sell on a
plan almost daily) filed 326 of them. Each is one request. Reading them all in the run
that first meets them would put a quarter of an hour of EDGAR requests into a refresh
that has other things to fetch from EDGAR at the same time, so a run reads at most
`MAX_NEW_FILINGS` new forms a company, newest first, and says in its notes how many are
still waiting. The newest are the ones a signal needs; the backlog fills in over the
following days. After that a day's work is the nine or so forms the whole universe
files.

A filing that has been opened is never requested again. `insider_filings` is the record
of that, including the forms that left no row behind (somebody else's shares, holdings
with no transaction), which would otherwise be downloaded on every run.

Foreign private issuers. The payload, on 2026-11-23: BioNTech, Legend and Autolus each
show a block of Form 3s in March 2026 and Form 4s from then on, and nothing before.
AstraZeneca shows one Form 3 that month and eight Form 4s since, all from one officer.
Novo Nordisk, Novartis, GSK, Sanofi and argenx show no Form 4 as issuer at all. So for a
20-F filer the record starts in March 2026 at the earliest and for several it has not
started. A company with no rows here has had no form filed, which for these says
nothing about whether anybody dealt. The fetcher reports what it finds and the reader
says so.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import db
import env  # noqa: F401  loads .env for the side effect, as contact.py does
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "insiders"
EDGAR_SOURCE = "edgar"
TTL_SECONDS = 24 * 60 * 60

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}"
_TIMEOUT_S = 30
_MAX_BYTES = 4 * 1024 * 1024        # of one form; the largest seen was 17 KB

FORMS = ("4", "4/A")

# How far back the first run reaches, by filing date. A year covers the run-up to any
# readout the book is watching and a full cycle of annual awards, which is what an
# open-market trade has to be told apart from. The window rolls: a later run looks at
# the same span behind its own date, and rows already stored are kept when they age out.
LOOKBACK_DAYS = 365

# New forms opened for one company in one run. Forty is about thirteen seconds of
# requests. The median company in the universe filed 35 forms in the year, so most are
# complete on the first run; 29 of the 73 need a second or third, and United
# Therapeutics needs nine.
MAX_NEW_FILINGS = 40

# The refresh runs four companies at once and each of them may be reading EDGAR through
# another fetcher at the same moment. A sleep inside one fetcher bounds that thread's
# rate and not the process's, and this fetcher makes more requests in a row than any
# other. So every request this module makes goes through one gate that holds them 0.3
# seconds apart whichever thread they come from. That is the pause the filing text
# fetcher keeps on a single thread, so all the insider reads together weigh on EDGAR
# no more than one worker already does, and four workers stay under its ten a second.
_MIN_INTERVAL_S = 0.3
_gate = threading.Lock()
_last_request = [0.0]

_XSL_PREFIX = re.compile(r"^xslF345X\d+/", re.IGNORECASE)
_TRUE = {"1", "true", "y", "yes"}
_FALSE = {"0", "false", "n", "no"}

OUTCOME_STORED = "stored"
OUTCOME_EMPTY = "no_transactions"
OUTCOME_NOT_ISSUER = "not_issuer"
OUTCOME_UNREADABLE = "unreadable"


def _pace() -> None:
    """Wait until the interval has passed since this module's last request."""
    with _gate:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def _same_cik(a, b) -> bool:
    """Whether two CIKs name one filer. EDGAR pads to ten digits in some places and not
    in others."""
    try:
        return int(str(a).strip()) == int(str(b).strip())
    except (TypeError, ValueError):
        return False


def raw_document(primary_document: str) -> str | None:
    """The raw XML's path for a filing's `primaryDocument`, or None where there is none.

    `xslF345X06/ownership.xml` is the browser view of `ownership.xml`. A form with no
    XML document at all (paper filings, and everything before mid-2003) has nothing a
    parser can read.
    """
    document = _XSL_PREFIX.sub("", (primary_document or "").strip())
    return document if document.lower().endswith(".xml") else None


def document_url(cik, accession: str, primary_document: str) -> str | None:
    """Where the raw ownership XML lives. The folder is the accession without dashes
    under the unpadded CIK of any filer on the form, the issuer included."""
    document = raw_document(primary_document)
    if not document:
        return None
    return ARCHIVE_URL.format(cik=int(str(cik)), folder=accession.replace("-", ""),
                              document=document)


def list_form4s(payload: dict, cik, since: str | None = None) -> list[dict]:
    """The Form 4s and amendments in a submissions payload, newest first. Pure.

    ``since`` is an ISO date; a filing dated before it is left out. Everything listed is
    a candidate only: whether the company is the issuer is not known until the document
    is read.
    """
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    accepted = recent.get("acceptanceDateTime") or []
    rows = []
    for i, form in enumerate(forms):
        if form not in FORMS or i >= len(accessions):
            continue
        filed = dates[i] if i < len(dates) else None
        if since and filed and filed < since:
            continue
        document = documents[i] if i < len(documents) else ""
        rows.append({
            "accession": accessions[i],
            "form_type": form,
            "filed_date": filed,
            "accepted_at": (accepted[i] if i < len(accepted) else None) or None,
            "url": document_url(cik, accessions[i], document),
        })
    rows.sort(key=lambda r: (r["filed_date"] or "", r["accepted_at"] or ""), reverse=True)
    return rows


# --- the ownership document ----------------------------------------------------------
def _text(node, path: str) -> str | None:
    """The stripped text at ``path``, or None where the element is missing or empty."""
    if node is None:
        return None
    found = node.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _value(node, path: str) -> str | None:
    """A form field's value. Each field wraps it in a <value> child, and a field that
    carries only a footnote reference has no <value> at all."""
    return _text(node, f"{path}/value")


def _number(text) -> float | None:
    """A stated number, or None. An empty field and a field that is not a number are
    both no figure: nothing here becomes a zero."""
    if text is None:
        return None
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


def _flag(text) -> int | None:
    """1, 0, or None where the form has no box or left it blank. Filing agents print the
    same box as 1/0 and as true/false."""
    token = (text or "").strip().lower()
    if token in _TRUE:
        return 1
    if token in _FALSE:
        return 0
    return None


def _date(text) -> str | None:
    """An ISO date. Some agents append a UTC offset to the day (2023-05-01-05:00)."""
    token = (text or "").strip()
    return token[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", token) else None


def _any(flags) -> int | None:
    """True of any reporting owner; false when every one says no; None when none says."""
    stated = [f for f in flags if f is not None]
    if not stated:
        return None
    return 1 if any(stated) else 0


def _cited(node, footnotes: dict) -> str | None:
    """The text of every footnote a row cites, in the order cited, each once."""
    seen, parts = set(), []
    for ref in node.iter("footnoteId"):
        key = ref.get("id")
        if key and key not in seen and footnotes.get(key):
            seen.add(key)
            parts.append(f"{key}: {footnotes[key]}")
    return "\n".join(parts) or None


def _transaction(node, footnotes: dict, derivative: bool) -> dict:
    row = {
        "is_derivative": 1 if derivative else 0,
        "security_title": _value(node, "securityTitle"),
        "transaction_date": _date(_value(node, "transactionDate")),
        "transaction_code": _text(node, "transactionCoding/transactionCode"),
        "shares": _number(_value(node, "transactionAmounts/transactionShares")),
        "price_per_share": _number(
            _value(node, "transactionAmounts/transactionPricePerShare")),
        "acquired_disposed": _value(
            node, "transactionAmounts/transactionAcquiredDisposedCode"),
        "shares_owned_after": _number(
            _value(node, "postTransactionAmounts/sharesOwnedFollowingTransaction")),
        "ownership": _value(node, "ownershipNature/directOrIndirectOwnership"),
        "ownership_nature": _value(node, "ownershipNature/natureOfOwnership"),
        "exercise_price": None, "underlying_title": None, "underlying_shares": None,
        "footnotes": _cited(node, footnotes),
    }
    if derivative:
        row["exercise_price"] = _number(_value(node, "conversionOrExercisePrice"))
        row["underlying_title"] = _value(
            node, "underlyingSecurity/underlyingSecurityTitle")
        row["underlying_shares"] = _number(
            _value(node, "underlyingSecurity/underlyingSecurityShares"))
    return row


def parse_ownership(xml_text: str) -> dict:
    """An ownership document as a dict: who it is about, who filed it, and each line of
    its two transaction tables in filing order. Pure. Raises ValueError on anything that
    is not an ownership document.

    Holdings lines (what is owned, with no transaction) are counted and not returned:
    they report a position, and a position is on the transaction lines already as the
    amount owned afterwards.
    """
    # The schema has no DTD and no entities. A document that declares either is not a
    # Form 4, and the standard library's parser would expand what it declares.
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError("document declares a DTD or an entity")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}")
    if root.tag != "ownershipDocument":
        raise ValueError(f"root is {root.tag}, not ownershipDocument")

    footnotes = {}
    for note in root.findall("footnotes/footnote"):
        if note.get("id"):
            footnotes[note.get("id")] = " ".join("".join(note.itertext()).split())

    owners = []
    for owner in root.findall("reportingOwner"):
        relation = owner.find("reportingOwnerRelationship")
        owners.append({
            "name": _text(owner, "reportingOwnerId/rptOwnerName"),
            "cik": _text(owner, "reportingOwnerId/rptOwnerCik"),
            "is_director": _flag(_text(relation, "isDirector")),
            "is_officer": _flag(_text(relation, "isOfficer")),
            "is_ten_percent_owner": _flag(_text(relation, "isTenPercentOwner")),
            "is_other": _flag(_text(relation, "isOther")),
            "officer_title": _text(relation, "officerTitle"),
        })

    remarks = _text(root, "remarks")
    title = next((o["officer_title"] for o in owners if o["officer_title"]), None)
    # "See Remarks" is the form pointing at its own remarks box, which is where a title
    # too long for the field is written. Follow the pointer; the remarks are the form's
    # words, not a reading of them.
    if title and re.sub(r"[^a-z]", "", title.lower()) in ("seeremarks", "seeremark") \
            and remarks:
        title = remarks[:200]

    transactions = (
        [_transaction(n, footnotes, False)
         for n in root.findall("nonDerivativeTable/nonDerivativeTransaction")]
        + [_transaction(n, footnotes, True)
           for n in root.findall("derivativeTable/derivativeTransaction")])

    return {
        "form_type": _text(root, "documentType"),
        "schema_version": _text(root, "schemaVersion"),
        "period_of_report": _date(_text(root, "periodOfReport")),
        "original_filed_date": _date(_text(root, "dateOfOriginalSubmission")),
        "issuer_cik": _text(root, "issuer/issuerCik"),
        "issuer_symbol": _text(root, "issuer/issuerTradingSymbol"),
        "owners": owners,
        "owner_name": owners[0]["name"] if owners else None,
        "owner_cik": owners[0]["cik"] if owners else None,
        "other_owners": "; ".join(o["name"] for o in owners[1:] if o["name"]) or None,
        "is_director": _any(o["is_director"] for o in owners),
        "is_officer": _any(o["is_officer"] for o in owners),
        "is_ten_percent_owner": _any(o["is_ten_percent_owner"] for o in owners),
        "is_other": _any(o["is_other"] for o in owners),
        "officer_title": title,
        # One box for the whole form: every line on it carries the same answer.
        "plan_10b5_1": _flag(_text(root, "aff10b5One")),
        "transactions": transactions,
        "holdings": (len(root.findall("nonDerivativeTable/nonDerivativeHolding"))
                     + len(root.findall("derivativeTable/derivativeHolding"))),
    }


_FILING_FIELDS = ("period_of_report", "original_filed_date", "owner_name", "owner_cik",
                  "other_owners", "is_director", "is_officer", "officer_title",
                  "is_ten_percent_owner", "is_other", "plan_10b5_1")


def transaction_rows(document: dict, filing: dict) -> list[dict]:
    """Table rows for one parsed form: its lines, each carrying the filing's own facts
    and its position. Pure. The form type is the document's, which says 4/A where the
    filing list sometimes does and sometimes does not."""
    rows = []
    for index, line in enumerate(document["transactions"]):
        row = {
            "accession": filing["accession"],
            "row_index": index,
            "form_type": document.get("form_type") or filing.get("form_type"),
            "filed_date": filing.get("filed_date"),
            "accepted_at": filing.get("accepted_at"),
            "url": filing.get("url"),
        }
        for name in _FILING_FIELDS:
            row[name] = document.get(name)
        row.update(line)
        rows.append(row)
    return rows


_COLUMNS = (
    "accession", "row_index", "form_type", "filed_date", "accepted_at",
    "original_filed_date", "period_of_report", "owner_name", "owner_cik", "other_owners",
    "is_director", "is_officer", "officer_title", "is_ten_percent_owner", "is_other",
    "security_title", "transaction_date", "transaction_code", "shares",
    "price_per_share", "acquired_disposed", "shares_owned_after", "ownership",
    "ownership_nature", "is_derivative", "exercise_price", "underlying_title",
    "underlying_shares", "plan_10b5_1", "footnotes", "url")


class InsidersEdgarFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._cik = None
        self._outcomes: list[dict] = []     # one a filing opened this run
        self._errors: list[str] = []
        self._backlog = 0

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company(self, conn):
        return conn.execute(
            "SELECT id, cik FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()

    def _already_read(self, conn, company_id: int) -> set:
        """Accessions never to request again: the ones the ledger holds for this
        company, and any that left rows (the same thing, said twice on purpose, so a
        ledger lost to a partial restore does not cost a year of requests)."""
        seen = {r[0] for r in conn.execute(
            "SELECT accession FROM insider_filings WHERE company_id = ?", (company_id,))}
        seen.update(r[0] for r in conn.execute(
            "SELECT DISTINCT accession FROM insider_transactions WHERE company_id = ?",
            (company_id,)))
        return seen

    def _get(self, url: str, user_agent: str, limit: int | None = None) -> str:
        _pace()
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            body = resp.read(limit) if limit else resp.read()
        return body.decode("utf-8", "replace")

    # --- contract ---------------------------------------------------------
    def fetch(self) -> dict:
        self._outcomes, self._errors, self._backlog = [], [], 0
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None or not company["cik"]:
                raise ValueError(f"no CIK for {self.ticker}")
            seen = self._already_read(conn, company["id"])
        finally:
            conn.close()
        self._cik = company["cik"]
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")

        # The list is the one request made on every run. A failure here raises, and the
        # base class reports it and tries again where the failure was the resolver.
        payload = json.loads(self._get(SUBMISSIONS_URL.format(cik=self._cik), user_agent))
        since = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
        listed = list_form4s(payload, self._cik, since)
        pending = [f for f in listed if f["accession"] not in seen]
        self._backlog = max(0, len(pending) - MAX_NEW_FILINGS)

        read = []
        for filing in pending[:MAX_NEW_FILINGS]:
            if not filing["url"]:
                # Nothing to download: recorded so it is not looked at again.
                read.append({**filing, "xml": None, "missing": "no XML document"})
                continue
            try:
                read.append({**filing,
                             "xml": self._get(filing["url"], user_agent, _MAX_BYTES)})
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # The path was built from the list and the document is not there.
                    # Said once and recorded; asking again tomorrow gets the same answer.
                    read.append({**filing, "xml": None, "missing": "HTTP 404"})
                    continue
                self._errors.append(
                    f"{self.ticker} {filing['accession']}: HTTP {exc.code}")
                if exc.code in (403, 429):
                    # EDGAR is refusing this client. Every further request makes the
                    # block longer, so the rest wait for the next run.
                    self._backlog = len(pending) - len(read)
                    break
            except Exception as exc:
                # One form that would not download is tried again on the next run and
                # never fails the forms that did.
                self._errors.append(
                    f"{self.ticker} {filing['accession']}: {type(exc).__name__}: {exc}")
        return {"listed": len(listed), "filings": read}

    def normalise(self, raw) -> list[dict]:
        rows, self._outcomes = [], []
        for filing in (raw or {}).get("filings") or []:
            outcome = {"accession": filing["accession"], "form_type": filing["form_type"],
                       "filed_date": filing["filed_date"], "url": filing["url"],
                       "issuer_cik": None, "row_count": 0}
            self._outcomes.append(outcome)
            if filing.get("xml") is None:
                outcome["outcome"] = OUTCOME_UNREADABLE
                self._errors.append(f"{self.ticker} {filing['accession']}: "
                                    f"{filing.get('missing') or 'no document'}")
                continue
            try:
                document = parse_ownership(filing["xml"])
            except ValueError as exc:
                outcome["outcome"] = OUTCOME_UNREADABLE
                self._errors.append(f"{self.ticker} {filing['accession']}: {exc}")
                continue
            outcome["issuer_cik"] = document["issuer_cik"]
            if not _same_cik(document["issuer_cik"], self._cik):
                outcome["outcome"] = OUTCOME_NOT_ISSUER
                continue
            found = transaction_rows(document, filing)
            outcome["outcome"] = OUTCOME_STORED if found else OUTCOME_EMPTY
            outcome["row_count"] = len(found)
            rows.extend(found)
        return rows

    # --- snapshots --------------------------------------------------------
    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'company', ?, ?, ?)",
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id))

    def _held(self, conn, company_id: int) -> dict:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT accession) AS filings,"
            "       MAX(filed_date) AS latest FROM insider_transactions"
            " WHERE company_id = ?", (company_id,)).fetchone()
        return {"transactions": row["n"], "filings": row["filings"],
                "latest_filed": row["latest"]}

    def snapshot(self, rows: list[dict]) -> None:
        """What the table held before this run's rows go in, and what the run adds."""
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return
            payload = {"ticker": self.ticker, **self._held(conn, company["id"]),
                       "new_transactions": len(rows),
                       "new_filings": len({r["accession"] for r in rows}),
                       "opened": len(self._outcomes),
                       "backlog": self._backlog,
                       "source": EDGAR_SOURCE, "fetch_kind": "live"}
            self._write_snapshot(conn, payload)
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return
            held = self._held(conn, company["id"])
            if not held["transactions"]:
                return
            self._write_snapshot(conn, {"ticker": self.ticker, **held,
                                        "source": EDGAR_SOURCE, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- current-state tables ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"],
                                     False, 0)
            company_id = company["id"]
            names = ", ".join(_COLUMNS)
            marks = ", ".join("?" for _ in _COLUMNS)
            updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS
                                if c not in ("accession", "row_index"))
            for row in rows:
                conn.execute(
                    f"INSERT INTO insider_transactions (company_id, {names}, fetched_at)"
                    f" VALUES (?, {marks}, datetime('now'))"
                    f" ON CONFLICT(accession, row_index) DO UPDATE SET {updates},"
                    f" fetched_at=datetime('now')",
                    [company_id] + [row.get(c) for c in _COLUMNS])
            for outcome in self._outcomes:
                conn.execute(
                    "INSERT INTO insider_filings (company_id, accession, form_type,"
                    " filed_date, outcome, issuer_cik, row_count, url, read_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))"
                    " ON CONFLICT(company_id, accession) DO UPDATE SET"
                    " form_type=excluded.form_type, filed_date=excluded.filed_date,"
                    " outcome=excluded.outcome, issuer_cik=excluded.issuer_cik,"
                    " row_count=excluded.row_count, url=excluded.url,"
                    " read_at=datetime('now')",
                    (company_id, outcome["accession"], outcome["form_type"],
                     outcome["filed_date"], outcome["outcome"], outcome["issuer_cik"],
                     outcome["row_count"], outcome["url"]))
            conn.commit()
        finally:
            conn.close()
        notes = []
        if self._backlog:
            notes.append(
                f"{self.ticker}: {self._backlog} Form 4s in the last {LOOKBACK_DAYS} days"
                f" not read yet; a run reads {MAX_NEW_FILINGS} a company, newest first")
        return RefreshResult(self.source, len(rows), list(self._errors), False, 0,
                             notes=notes)
