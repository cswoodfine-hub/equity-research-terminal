"""Completed studies that have reported, for the evidence behind a marketed product.

The pipeline fetch takes active studies only, because a pipeline is what is still
running. That leaves a product's own record out: an analyst opening Verzenio wants the
trials that read out and what they measured, and every one of those is completed and
therefore absent.

This asks the same registry a different question, keeps the answer in its own table so
nothing that counts the pipeline can pick it up, and stores only studies the registry
marks as having results, since a completed study with nothing posted says nothing that
can be read. Sorted newest first and capped per company, so a sponsor with two thousand
finished studies costs a bounded number of requests and the most recent are always the
ones on file.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import acquired_sponsors
import ctgov
import db
import trial_mapping
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "trials_completed"
CTGOV_SOURCE = "clinicaltrials_v2"
TTL_SECONDS = 24 * 60 * 60

STUDIES_URL = ctgov.STUDIES_URL
PAGE_SIZE = 500
MAX_PAGES = 4               # 2000 studies per sponsor, newest first
_TIMEOUT_S = 60
_POLITE_SLEEP_S = 0.3
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"

FIELDS = "|".join((
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.designModule.phases",
    "protocolSection.statusModule.completionDateStruct",
    "protocolSection.designModule.enrollmentInfo",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.armsInterventionsModule.interventions",
    "protocolSection.outcomesModule.primaryOutcomes",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
))


def parse_studies(payload: dict) -> list[dict]:
    """Registry studies to table rows. Pure, so the parser is testable on a fixture."""
    rows = []
    for study in payload.get("studies") or []:
        section = study.get("protocolSection") or {}
        ident = section.get("identificationModule") or {}
        nct_id = ident.get("nctId")
        if not nct_id:
            continue
        design = section.get("designModule") or {}
        outcomes = (section.get("outcomesModule") or {}).get("primaryOutcomes") or []
        interventions = [
            i.get("name") for i in
            (section.get("armsInterventionsModule") or {}).get("interventions") or []
            if i.get("name")]
        rows.append({
            "nct_id": nct_id,
            "title": ident.get("briefTitle"),
            "phase": _phase(design.get("phases")),
            "conditions": json.dumps(
                (section.get("conditionsModule") or {}).get("conditions") or []),
            "completion_date": ((section.get("statusModule") or {})
                                .get("completionDateStruct") or {}).get("date"),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
            # The measure as the registry words it. The result itself is a separate,
            # much larger document; the endpoint is what says whether a readout is
            # worth opening, and the link goes to the rest.
            "primary_outcome": outcomes[0].get("measure") if outcomes else None,
            "interventions": interventions,
            "lead_sponsor": ((section.get("sponsorCollaboratorsModule") or {})
                             .get("leadSponsor") or {}).get("name"),
        })
    return rows


def _phase(phases) -> str | None:
    """The registry's phase array as one label, the way the pipeline writes it."""
    return ctgov.normalize_phase(phases)


class TrialsCompletedFetcher(BaseFetcher):
    """One company's completed, reported studies."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

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
            return {"studies": [], "company_id": None}

        acquired = acquired_sponsors.for_company(self.db_path, self.ticker)
        studies = []
        own = ctgov.SPONSOR_LEAD.get(self.ticker, company["name"])
        for index, sponsor in enumerate([own] + acquired):
            studies.extend(self._studies_for(sponsor,
                                             acquired if index else None))
        return {"studies": studies, "company_id": company["id"]}

    def _studies_for(self, sponsor: str, verify_against) -> list:
        """One sponsor's completed studies, verified against the registry's own lead
        sponsor name when the sponsor is a company this one acquired."""
        studies, token = [], None
        for _page in range(MAX_PAGES):
            params = {
                # The lead sponsor, by the registry's own name for the company. Its
                # legal name returns almost nothing: AstraZeneca PLC found zero
                # completed studies where AstraZeneca finds thousands. query.lead
                # rather than query.spons, so a study this company only collaborated
                # on is not filed as its own record.
                "query.lead": sponsor,
                "filter.overallStatus": "COMPLETED",
                "aggFilters": "results:with",
                "fields": FIELDS,
                "pageSize": PAGE_SIZE,
                "sort": "CompletionDate:desc",
            }
            if token:
                params["pageToken"] = token
            request = urllib.request.Request(
                STUDIES_URL + "?" + urllib.parse.urlencode(params),
                headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                payload = json.loads(response.read().decode("utf-8"))
            found = payload.get("studies") or []
            if verify_against is not None:
                found = [s for s in found
                         if acquired_sponsors.sponsored_by(s, verify_against)]
            studies.extend(found)
            token = payload.get("nextPageToken")
            if not token:
                break
            time.sleep(_POLITE_SLEEP_S)
        return studies

    def normalise(self, raw) -> list[dict]:
        company_id = raw.get("company_id")
        if company_id is None:
            return []
        rows = parse_studies({"studies": raw["studies"]})
        # Bound to the same assets the pipeline uses, by the same rule, so a product's
        # finished studies and its running ones are attributed the same way.
        conn = db.get_connection(self.db_path)
        try:
            names = trial_mapping._asset_names(conn, company_id)
        finally:
            conn.close()
        for row in rows:
            row["sponsor_company_id"] = company_id
            row["asset_id"] = next(
                (a for a in (trial_mapping.match_intervention(
                    trial_mapping.normalise(name), names)
                    for name in row.pop("interventions", [])) if a), None)
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {"source": CTGOV_SOURCE, "completed": len(rows),
                                        "mapped": sum(1 for r in rows if r["asset_id"])})
            conn.commit()
        finally:
            conn.close()

    def _write_snapshot(self, conn, payload) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
            (self.source, self.entity_key, json.dumps(payload), self.refresh_run_id))

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return
            n = conn.execute(
                "SELECT COUNT(*) FROM completed_trials WHERE sponsor_company_id = ?",
                (company["id"],)).fetchone()[0]
            if n:
                self._write_snapshot(conn, {"source": CTGOV_SOURCE, "completed": n,
                                            "fetch_kind": "cache"})
                conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO completed_trials
                        (nct_id, sponsor_company_id, asset_id, title, phase, conditions,
                         completion_date, enrollment, primary_outcome, lead_sponsor,
                         fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(nct_id) DO UPDATE SET
                        asset_id = excluded.asset_id, title = excluded.title,
                        phase = excluded.phase, conditions = excluded.conditions,
                        completion_date = excluded.completion_date,
                        enrollment = excluded.enrollment,
                        primary_outcome = excluded.primary_outcome,
                        lead_sponsor = excluded.lead_sponsor,
                        fetched_at = datetime('now')
                    """,
                    (row["nct_id"], row["sponsor_company_id"], row["asset_id"],
                     row["title"], row["phase"], row["conditions"],
                     row["completion_date"], row["enrollment"],
                     row["primary_outcome"], row.get("lead_sponsor")))
            conn.commit()
        finally:
            conn.close()
        mapped = sum(1 for r in rows if r["asset_id"])
        notes = ([f"{len(rows) - mapped} completed studies name no product on file"]
                 if len(rows) > mapped else [])
        return RefreshResult(self.source, len(rows), [], False, 0, notes=notes)
