"""Clinical trials from ClinicalTrials.gov API v2.

Pulls each company's active, lead-sponsored interventional drug/biological trials.
Uses query.lead (not query.spons, which also matches collaborator trials) and a
per-ticker sponsor-name map, because CTGov's lead-sponsor names differ from the
companies' legal names (Merck is "Merck Sharp & Dohme LLC", Roche is
"Hoffmann-La Roche", J&J's pharma is "Janssen Research & Development, LLC").

And then one pass more, because the lead-sponsor rule is blind to a shape that
matters. A company funds an outcomes trial and an academic group runs it, so the
registry files it under the university and the book holds none of it. ORION-4
(NCT03705234) is 16,124 patients of inclisiran with major adverse cardiovascular
events as its primary endpoint, due to report while this was written, and its lead
sponsor is the University of Oxford with Novartis a collaborator. The book had no
row for it at all, while pricing a smaller Novartis-led study in the same setting
as Leqvio's gate.

query.spons on its own is not the fix: it matches every study a company is named
on, including other people's medicines it merely supplied or part-funded. The
discriminator is the molecule. A collaborator study is kept only where one of its
interventions names an asset this company owns, which is the same rule
trial_mapping uses to place a study on an asset in the first place.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import acquired_sponsors
import company_names
import ctgov
import db
import trial_mapping
from fetchers.base import BaseFetcher, RefreshResult
import contact

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
    # When dosing began and when the record first appeared. A development timeline and a
    # count of programmes entering the clinic both need a start; a completion date alone
    # cannot give either.
    "protocolSection.statusModule.startDateStruct",
    "protocolSection.statusModule.studyFirstPostDateStruct",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.studyType",
    "protocolSection.designModule.enrollmentInfo",
    "protocolSection.conditionsModule.conditions",
    # The controlled vocabulary the registry already derives. The sponsor's free text
    # spells one indication three ways; the MeSH descriptor is one id. Ancestors are
    # not requested: they carry Neoplasms for every oncology study.
    "derivedSection.conditionBrowseModule",
    "protocolSection.armsInterventionsModule.interventions",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    # Who else is on it. The collaborator pass needs this to confirm the company is
    # actually named, since query.spons matches loosely.
    "protocolSection.sponsorCollaboratorsModule.collaborators",
    # What it measures and how it is built. Watched for change, not shown: an endpoint
    # rewritten mid-trial is the signal, and it cannot be seen without the last value.
    "protocolSection.outcomesModule.primaryOutcomes",
    "protocolSection.designModule.designInfo",
]
PAGE_SIZE = 1000
_USER_AGENT = contact.product_agent()
_TIMEOUT_S = 60
_PAGE_SLEEP_S = 0.2

# The sponsor terms and phase mapping are shared with the completed-studies fetch and
# live in ctgov.py, since fetchers do not import each other.
SPONSOR_LEAD = ctgov.SPONSOR_LEAD
PHASE_MAP = ctgov.PHASE_MAP
PHASES = ctgov.PHASES
normalize_phase = ctgov.normalize_phase


def _primary_outcome(section: dict) -> str | None:
    """The first primary endpoint as the protocol words it, or None when it states none.

    Only the measure, not its time frame: a sponsor rewording "at week 52" to "at week
    48" is a change worth catching, but it arrives through the completion date too,
    while a changed measure is a change of what the trial is asking.
    """
    outcomes = (section.get("outcomesModule") or {}).get("primaryOutcomes") or []
    measure = (outcomes[0].get("measure") if outcomes else None) or None
    return measure.strip() if measure else None


def _design(design: dict) -> str | None:
    """Allocation, masking and purpose in one string, or None when the registry gives
    none. Dropping a blind or moving from randomised to single-arm is a design change,
    and it reads as one here."""
    info = (design or {}).get("designInfo") or {}
    parts = [info.get("allocation"), (info.get("maskingInfo") or {}).get("masking"),
             info.get("primaryPurpose")]
    parts = [p.replace("_", " ").title() for p in parts if p]
    return ", ".join(parts) or None


def _humanize_status(status) -> str | None:
    return status.replace("_", " ").capitalize() if status else None


def _date(struct) -> str | None:
    return struct.get("date") if isinstance(struct, dict) else None


def _date_type(struct) -> str | None:
    """ACTUAL or ESTIMATED, lowercased. The registry distinguishes the two and the
    difference is the whole meaning of a date that has already passed."""
    kind = struct.get("type") if isinstance(struct, dict) else None
    return kind.lower() if isinstance(kind, str) else None


# The registry's intervention types that mean "a therapy is being given". DRUG and
# BIOLOGICAL alone silently deleted whole companies: ClinicalTrials.gov types a gene
# therapy or a gene-edited construct as GENETIC, so Editas, Sangamo and Taysha each had
# three to five active studies in the registry and zero trials on file here, and every
# gene editing programme in the universe was invisible. The bias fell hardest on exactly
# the modality this terminal is meant to be good at.
#
# COMBINATION_PRODUCT is included for the same reason, a drug delivered with its device.
# Types that are not a therapy, DIAGNOSTIC_TEST, BEHAVIORAL, DIETARY_SUPPLEMENT, OTHER,
# stay out: a study whose only intervention is a questionnaire is not a readout.
THERAPEUTIC_TYPES = ("DRUG", "BIOLOGICAL", "GENETIC", "COMBINATION_PRODUCT")


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
        # Name and type both kept: the name is what binds a trial to an asset, and the
        # type distinguishes a study drug from a biological comparator downstream.
        drugs = [{"name": i["name"], "kind": i.get("type")} for i in interventions
                 if i.get("type") in THERAPEUTIC_TYPES and i.get("name")]
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
                "primary_completion_type": _date_type(
                    status.get("primaryCompletionDateStruct")),
                "completion_date": _date(status.get("completionDateStruct")),
                "last_update_posted": _date(status.get("lastUpdatePostDateStruct")),
                "start_date": _date(status.get("startDateStruct")),
                "first_posted": _date(status.get("studyFirstPostDateStruct")),
                "conditions": ps.get("conditionsModule", {}).get("conditions") or [],
                "mesh_terms": _meshes(study),
                "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
                "interventions": drugs,
                # Who the registry says leads it, which is how a study acquired with a
                # company explains why it sits under its new owner.
                "lead_sponsor": ((ps.get("sponsorCollaboratorsModule") or {})
                                 .get("leadSponsor") or {}).get("name"),
                "primary_outcome": _primary_outcome(ps),
                "design": _design(design),
            }
        )
    return rows


def _meshes(study: dict) -> dict:
    """The registry's MeSH indexing for a study: {"meshes": [...], "ancestors": [...]}.

    Both halves are stored, because neither alone says which term is the indication.
    ``meshes`` is not reliably specific: for NCT06926621 it runs to twelve terms ending in
    "Nervous System Diseases", while for NCT05027269 it holds two and the broad ones sit in
    ``ancestors``. What ``ancestors`` is reliably good for is the opposite job, naming
    terms that are somebody's parent somewhere, which is how the broad ones are recognised
    across the corpus.
    """
    browse = (study.get("derivedSection") or {}).get("conditionBrowseModule") or {}
    pick = lambda key: [{"id": m["id"], "term": m["term"]}
                        for m in (browse.get(key) or []) if m.get("id") and m.get("term")]
    return {"meshes": pick("meshes"), "ancestors": pick("ancestors")}


def _phase_counts(rows: list[dict]) -> dict:
    counts = {phase: 0 for phase in PHASES}
    for row in rows:
        counts[row["phase"]] += 1
    return counts


# What a collaborator study has to be before the book takes it. Measured, not guessed:
# the molecule test alone returns 1,659 studies the book does not hold, and they are
# overwhelmingly investigator-initiated oncology work using an approved drug. The
# interventions say so plainly - 225 of them name pembrolizumab, 113 nivolumab, 81
# durvalumab. Those are academics running their own trial with a company's marketed
# medicine, not the company's programme, and admitting them would bury the gate model.
#
# Scale is what separates the one shape the book must not miss. A Phase 3 or 4 study of
# a thousand people or more that somebody else leads is a registrational or pragmatic
# outcomes trial, and that is ORION-4's shape: 16,124 participants, major adverse
# cardiovascular events, the University of Oxford leading. At this threshold the sweep
# keeps 31 rather than 1,659, and reading them they are what they should be: ORION-4,
# oral semaglutide at Oxford, adjuvant palbociclib, finerenone, Shingrix and a COVID
# vaccine in the Danish pragmatic trials.
#
# What still gets through is a generic. Two companies own rows called Doxorubicin and
# Vincristine, so an academic chemotherapy de-escalation study matches them. The cure is
# data/not_a_programme.csv, which exists for exactly that and is applied where a study is
# turned into a programme rather than here.
# Intersected with the study's phases rather than compared, so a Phase 2/3 study
# qualifies on the PHASE3 half of its label. That is the book's own reading elsewhere:
# forecast_view._LAYER_GATE_PHASES already treats "Phase 2/3" as a Phase 3 gate. One
# study came in this way on the first full fetch, GBM AGILE at 2,250 participants.
_COLLABORATION_PHASES = ("PHASE3", "PHASE4")
_COLLABORATION_MIN_ENROLMENT = 1000


NOT_OUR_TRIALS_CSV = db.BACKEND_DIR.parent / "data" / "not_our_trials.csv"


def not_our_trials(ticker: str, path=None) -> set:
    """{nct_id} the analyst has said are not this company's programme, for one ticker."""
    import csv as _csv
    source = path or NOT_OUR_TRIALS_CSV
    try:
        with open(source, newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
    except FileNotFoundError:
        return set()
    return {(r.get("nct_id") or "").strip().upper()
            for r in _csv.DictReader(lines)
            if (r.get("ticker") or "").strip().upper() == ticker.upper()
            and (r.get("nct_id") or "").strip()}


def _is_our_collaboration(study: dict, sponsor_norm: str, names: list, already) -> bool:
    """Whether a study somebody else leads belongs to this company's book.

    Four tests, and all four have to hold.

    It must not already be in hand, because the lead-sponsor query runs first and a
    company is sometimes listed as its own collaborator.

    The company must actually be named as a collaborator. query.spons matches the
    sponsor fields loosely, and a loose match on a common word would otherwise sweep in
    studies the company has nothing to do with.

    It must be at the scale the book models. See _COLLABORATION_MIN_ENROLMENT above:
    without this the rule returns 1,659 studies, almost all of them investigator-initiated
    work with an approved drug.

    And an intervention must name one of the company's own assets. Oxford's ORION-4 lists
    "Inclisiran" and binds; a university study of somebody else's drug that a company
    part-funded lists nothing of the company's and does not. Pure, so the rule is testable
    without a database or a network call.
    """
    protocol = study.get("protocolSection") or {}
    nct = (protocol.get("identificationModule") or {}).get("nctId")
    if not nct or nct in (already or set()):
        return False
    sponsors = protocol.get("sponsorCollaboratorsModule") or {}
    lead = trial_mapping.normalise((sponsors.get("leadSponsor") or {}).get("name") or "")
    if lead == sponsor_norm:
        return False                        # the lead-sponsor pass owns this one
    named = {trial_mapping.normalise(c.get("name") or "")
             for c in (sponsors.get("collaborators") or [])}
    if sponsor_norm not in named:
        return False
    design = protocol.get("designModule") or {}
    if not set(design.get("phases") or []) & set(_COLLABORATION_PHASES):
        return False
    if ((design.get("enrollmentInfo") or {}).get("count") or 0) \
            < _COLLABORATION_MIN_ENROLMENT:
        return False
    for intervention in ((protocol.get("armsInterventionsModule") or {})
                         .get("interventions") or []):
        got = trial_mapping.normalise(intervention.get("name") or "")
        if trial_mapping.match_intervention(got, names) is not None:
            return True
    return False


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
        term = company_names.source_name(self.ticker, "ctgov_sponsor",
                                         SPONSOR_LEAD.get(self.ticker), self.db_path)
        if not term:
            raise ValueError(f"no CTGov sponsor mapping for {self.ticker}")
        # The company's own name, then the companies it has bought: the registry lists
        # a study under whoever registered it, and Centessa still sponsors its own
        # studies months after Lilly acquired it.
        acquired = acquired_sponsors.for_company(self.db_path, self.ticker)
        studies: list[dict] = []
        errors = []
        for term_index, sponsor in enumerate([term] + acquired):
            try:
                studies.extend(
                    self._studies_for(sponsor, acquired if term_index else None))
            except Exception as exc:
                if not term_index:
                    raise          # the company's own sponsor failing is a real failure
                # An acquired name is read off a headline and can be unusable as a
                # query. Losing it costs that one company's studies, not the run.
                errors.append(f"{sponsor}: {exc}")
        # Then the studies somebody else leads that test this company's own molecule.
        # Appended rather than merged: a study found both ways is the same payload, and
        # parse_studies is keyed on nct_id, so the duplicate settles itself.
        collaborated = []
        try:
            collaborated = self._collaborator_studies(term, {st.get("protocolSection", {})
                                                             .get("identificationModule", {})
                                                             .get("nctId")
                                                             for st in studies})
        except Exception as exc:                                   # noqa: BLE001
            # A pass that finds extra studies must not be able to lose the ordinary
            # ones. The lead-sponsor query above is the contract.
            errors.append(f"collaborator pass: {exc}")
        studies.extend(collaborated)
        return {"studies": studies, "sponsor_errors": errors,
                "collaborated": len(collaborated)}

    def _collaborator_studies(self, term: str, already: set) -> list:
        """Active studies another organisation leads that test this company's molecule.

        Kept only where an intervention names an asset the company owns, by the same
        rule that places a study on an asset (trial_mapping.match_intervention). Without
        that test this would pull in every study a company is named on, including other
        people's medicines it supplied or part-funded.

        Returns nothing rather than raising where the company has no assets yet, which
        is the state a brand-new ticker is in on its first refresh.
        """
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            names = (trial_mapping._asset_names(conn, company_id)
                     if company_id is not None else [])
        finally:
            conn.close()
        if not names:
            return []
        wanted = trial_mapping.normalise(term)
        excluded = not_our_trials(self.ticker)
        already = set(already or ()) | excluded
        kept, page_token = [], None
        while True:
            params = {
                "query.spons": term,
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
            for study in data.get("studies", []):
                if _is_our_collaboration(study, wanted, names, already):
                    kept.append(study)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(_PAGE_SLEEP_S)
        return kept

    def _studies_for(self, term: str, verify_against) -> list:
        """One sponsor's active studies. ``verify_against`` is the acquired-name list
        when this is an acquired sponsor, and the studies are then kept only where the
        registry's own lead sponsor agrees, since the query matches loosely."""
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
            found = data.get("studies", [])
            if verify_against is not None:
                found = [st for st in found
                         if acquired_sponsors.sponsored_by(st, verify_against)]
            studies.extend(found)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(_PAGE_SLEEP_S)
        return studies

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
            # A study the analyst has said is not this company's leaves it on every fetch,
            # not once, so the correction reaches the database the nightly run restores.
            for nct_id in not_our_trials(self.ticker):
                conn.execute("DELETE FROM trial_interventions WHERE nct_id = ?", (nct_id,))
                conn.execute("DELETE FROM trials WHERE nct_id = ? AND sponsor_company_id = ?",
                             (nct_id, company_id))
            rows = [r for r in rows if (r.get("nct_id") or "").upper()
                    not in not_our_trials(self.ticker)]
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO trials
                        (nct_id, sponsor_company_id, title, phase, overall_status,
                         primary_completion_date, primary_completion_type,
                         completion_date, enrollment, conditions, mesh_terms,
                         last_update_posted, start_date, first_posted,
                         lead_sponsor, primary_outcome, design,
                         source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            datetime('now'))
                    ON CONFLICT(nct_id) DO UPDATE SET
                        sponsor_company_id=excluded.sponsor_company_id, title=excluded.title,
                        phase=excluded.phase, overall_status=excluded.overall_status,
                        primary_completion_date=excluded.primary_completion_date,
                        primary_completion_type=excluded.primary_completion_type,
                        completion_date=excluded.completion_date, enrollment=excluded.enrollment,
                        conditions=excluded.conditions,
                        mesh_terms=excluded.mesh_terms,
                        last_update_posted=excluded.last_update_posted,
                        start_date=excluded.start_date,
                        first_posted=excluded.first_posted,
                        lead_sponsor=excluded.lead_sponsor,
                        primary_outcome=excluded.primary_outcome,
                        design=excluded.design, fetched_at=datetime('now')
                    """,
                    (
                        row["nct_id"], company_id, row["title"], row["phase"],
                        row["overall_status"], row["primary_completion_date"],
                        row.get("primary_completion_type"),
                        row["completion_date"], row["enrollment"],
                        json.dumps(row["conditions"]),
                        json.dumps(row.get("mesh_terms") or []),
                        row["last_update_posted"],
                        row.get("start_date"), row.get("first_posted"),
                        row.get("lead_sponsor"), row.get("primary_outcome"),
                        row.get("design"), CTGOV_SOURCE,
                    ),
                )
                # The study drugs, replaced wholesale per trial so a dropped arm does not
                # linger. These are what bind a trial to an asset; without them stored,
                # nothing can be mapped.
                conn.execute("DELETE FROM trial_interventions WHERE nct_id = ?",
                             (row["nct_id"],))
                for drug in row["interventions"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO trial_interventions"
                        "  (nct_id, name, norm, kind) VALUES (?, ?, ?, ?)",
                        (row["nct_id"], drug["name"],
                         trial_mapping.normalise(drug["name"]), drug.get("kind")),
                    )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)
