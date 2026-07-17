"""Clinical trials from ClinicalTrials.gov API v2.

Pulls each company's active, lead-sponsored interventional drug/biological trials.
Uses query.lead (not query.spons, which also matches collaborator trials) and a
per-ticker sponsor-name map, because CTGov's lead-sponsor names differ from the
companies' legal names (Merck is "Merck Sharp & Dohme LLC", Roche is
"Hoffmann-La Roche", J&J's pharma is "Janssen Research & Development, LLC").
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "trials"
CTGOV_SOURCE = "clinicaltrials_v2"
TTL_SECONDS = 24 * 60 * 60

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
ACTIVE_STATUSES = [
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
]
FIELDS = [
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.primaryCompletionDateStruct",
    "protocolSection.statusModule.completionDateStruct",
    "protocolSection.statusModule.lastUpdatePostDateStruct",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.studyType",
    "protocolSection.designModule.enrollmentInfo",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.armsInterventionsModule.interventions",
]
PAGE_SIZE = 1000
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"
_TIMEOUT_S = 60
_PAGE_SLEEP_S = 0.2

# CTGov lead-sponsor search term per ticker (verified against the live API).
SPONSOR_LEAD = {
    "LLY": "Eli Lilly and Company",
    "NVO": "Novo Nordisk A/S",
    "MRK": "Merck Sharp & Dohme LLC",
    "PFE": "Pfizer",
    "ABBV": "AbbVie",
    "JNJ": "Janssen Research & Development, LLC",
    "AZN": "AstraZeneca",
    "GSK": "GlaxoSmithKline",
    "NVS": "Novartis Pharmaceuticals",
    "ROG": "Hoffmann-La Roche",
    "SNY": "Sanofi",
    "BMY": "Bristol-Myers Squibb",
    "AMGN": "Amgen",
    "GILD": "Gilead Sciences",
    "VRTX": "Vertex Pharmaceuticals Incorporated",
    "REGN": "Regeneron Pharmaceuticals",
    "BIIB": "Biogen",
    "BAYN": "Bayer",
}

PHASE_MAP = {
    ("EARLY_PHASE1",): "Phase 1",
    ("PHASE1",): "Phase 1",
    ("PHASE1", "PHASE2"): "Phase 1/2",
    ("PHASE2",): "Phase 2",
    ("PHASE2", "PHASE3"): "Phase 2/3",
    ("PHASE3",): "Phase 3",
    ("PHASE4",): "Phase 4",
}
PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]


def normalize_phase(phases) -> str | None:
    """Map a CTGov phases array to a heatmap column, or None for NA/observational."""
    if not phases:
        return None
    return PHASE_MAP.get(tuple(phases))


def _humanize_status(status) -> str | None:
    return status.replace("_", " ").capitalize() if status else None


def _date(struct) -> str | None:
    return struct.get("date") if isinstance(struct, dict) else None


def parse_studies(payload: dict) -> list[dict]:
    """Turn a CTGov studies payload into trial rows. Pure.

    Keeps interventional studies that have a drug/biological intervention and a real
    (non-NA) phase; drops observational, NA-phase, and non-drug studies.
    """
    rows: list[dict] = []
    for study in payload.get("studies", []):
        ps = study.get("protocolSection", {})
        design = ps.get("designModule", {})
        if design.get("studyType") != "INTERVENTIONAL":
            continue
        phase = normalize_phase(design.get("phases"))
        if phase is None:
            continue
        interventions = ps.get("armsInterventionsModule", {}).get("interventions") or []
        drugs = [i.get("name") for i in interventions
                 if i.get("type") in ("DRUG", "BIOLOGICAL") and i.get("name")]
        if not drugs:
            continue
        ident = ps.get("identificationModule", {})
        status = ps.get("statusModule", {})
        rows.append(
            {
                "nct_id": ident.get("nctId"),
                "title": ident.get("briefTitle"),
                "phase": phase,
                "overall_status": _humanize_status(status.get("overallStatus")),
                "primary_completion_date": _date(status.get("primaryCompletionDateStruct")),
                "completion_date": _date(status.get("completionDateStruct")),
                "last_update_posted": _date(status.get("lastUpdatePostDateStruct")),
                "conditions": ps.get("conditionsModule", {}).get("conditions") or [],
                "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
                "interventions": drugs,
            }
        )
    return rows


def _phase_counts(rows: list[dict]) -> dict:
    counts = {phase: 0 for phase in PHASES}
    for row in rows:
        counts[row["phase"]] += 1
    return counts


class TrialsFetcher(BaseFetcher):
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

    def fetch(self) -> dict:
        term = SPONSOR_LEAD.get(self.ticker)
        if not term:
            raise ValueError(f"no CTGov sponsor mapping for {self.ticker}")
        studies: list[dict] = []
        page_token = None
        while True:
            params = {
                "query.lead": term,
                "filter.overallStatus": "|".join(ACTIVE_STATUSES),
                "fields": ",".join(FIELDS),
                "pageSize": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            url = f"{STUDIES_URL}?{urllib.parse.urlencode(params)}"
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            studies.extend(data.get("studies", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(_PAGE_SLEEP_S)
        return {"studies": studies}

    def normalise(self, raw) -> list[dict]:
        return parse_studies(raw)

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "active_trials": len(rows),
                    "by_phase": _phase_counts(rows),
                    "source": CTGOV_SOURCE,
                    "fetch_kind": "live",
                },
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
            rows = conn.execute(
                "SELECT phase FROM trials WHERE sponsor_company_id = ? AND phase IN (%s)"
                % ",".join("?" * len(PHASES)),
                (company_id, *PHASES),
            ).fetchall()
            if not rows:
                return
            counts = {phase: 0 for phase in PHASES}
            for r in rows:
                counts[r["phase"]] += 1
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "active_trials": len(rows),
                    "by_phase": counts,
                    "source": CTGOV_SOURCE,
                    "fetch_kind": "cache",
                },
            )
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO trials
                        (nct_id, sponsor_company_id, title, phase, overall_status,
                         primary_completion_date, completion_date, enrollment, conditions,
                         last_update_posted, source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(nct_id) DO UPDATE SET
                        sponsor_company_id=excluded.sponsor_company_id, title=excluded.title,
                        phase=excluded.phase, overall_status=excluded.overall_status,
                        primary_completion_date=excluded.primary_completion_date,
                        completion_date=excluded.completion_date, enrollment=excluded.enrollment,
                        conditions=excluded.conditions,
                        last_update_posted=excluded.last_update_posted, fetched_at=datetime('now')
                    """,
                    (
                        row["nct_id"], company_id, row["title"], row["phase"],
                        row["overall_status"], row["primary_completion_date"],
                        row["completion_date"], row["enrollment"],
                        json.dumps(row["conditions"]), row["last_update_posted"], CTGOV_SOURCE,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)
