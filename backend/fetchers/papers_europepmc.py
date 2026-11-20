"""New cell and gene therapy papers, read each day from Europe PMC.

Europe PMC's search (``/europepmc/webservices/rest/search``) is free and keyless. The
query is the one the scores were trained on (``discovery.QUERY``): a short list of terms
in the title or abstract, journal papers without reviews, and preprints. Each run reads
the records that *entered the index* in the last three weeks (``FIRST_IDATE``), not the
ones dated in that window: on 2026-11-20 a fifth of the journal papers returned had been
indexed before their stated publication date, some by months, and a search on the
publication date would have shown them late or never.

Three weeks, read every day, is on purpose. A journal paper often arrives without its
abstract, and both scores read the abstract, so a paper with none is held with null
scores and read again on each run until one arrives or it leaves the window. The very
first run reaches back to the day the lab heads were ranked, so what each lab has done
since is not mistaken later for something new.

Each paper is filed under its areas, scored (``discovery.Scorer``), and its last author is
looked up among the ranked lab heads by name and institution. A snapshot of a paper is
written when it is first read and again only if what an alert depends on changes; a
snapshot of a lab is written only when one of its papers moves it to a later model stage
or brings its first company co-author. ``diff._diff_discovery`` turns those into alerts.

No abstract is stored. Nothing here reaches a value, a forecast or a company's note.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
import urllib.parse
import urllib.request

import contact
import db
import discovery as D
import materiality
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "europepmc"
ENTITY_KEY = "discovery_feed"
TTL_SECONDS = 24 * 60 * 60
SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Journal papers leave out reviews, as the training set did; preprints carry no such type.
SOURCES = (("MED", ' AND NOT PUB_TYPE:"Review"'), ("PPR", ""))
WINDOW_DAYS = 21                 # how far back each run reads, by index date
FIRST_WINDOW_MAX_DAYS = 120      # and the furthest the first run reaches
PAGE_SIZE = 200                  # a full record is about 8 KB; the service is slow on more
KEEP_DAYS = 400                  # a paper leaves the table this long after it was seen
_TIMEOUT_S = 180
_PAUSE_S = 0.2
_TAG = re.compile(r"<[^>]+>")

# The fields of a paper an alert depends on. A new snapshot is written when one changes.
_TRACKED = ("read", "lab_id", "stage", "company_author", "feas_tier", "comm_tier")


def tier(pct):
    """A rank reduced to what an alert asks of it: top 1%, top 5%, or neither."""
    if pct is None:
        return None
    return ("top1" if pct >= materiality.DISCOVERY_HIGH_PCT
            else "top5" if pct >= materiality.DISCOVERY_TOP_PCT else "rest")


def _plain_title(title) -> str:
    return " ".join(html.unescape(_TAG.sub("", title or "")).split()).rstrip(".")


def parse(record: dict) -> dict | None:
    """One Europe PMC record as the fields kept, or None without an id, title or date."""
    source, rid = record.get("source"), record.get("id")
    title, published = record.get("title"), record.get("firstPublicationDate")
    if not (source and rid and title and published):
        return None
    authors = [a for a in (record.get("authorList") or {}).get("author") or []
               if a.get("lastName")]            # a consortium has no surname and no lab
    addresses = [[x.get("affiliation") for x in
                  (a.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []
                  if x.get("affiliation")] for a in authors]
    senior = authors[-1] if authors else {}
    first = senior.get("firstName") or ""
    preprint = source == "PPR"
    journal = (((record.get("journalInfo") or {}).get("journal") or {}).get("title")
               or (record.get("bookOrReportDetails") or {}).get("publisher"))
    return {
        "id": f"{source}:{rid}", "source": source, "pmid": record.get("pmid"),
        "doi": record.get("doi"), "raw_title": title, "title": _plain_title(title),
        "abstract": record.get("abstractText") or "", "published": published[:10],
        "indexed": (record.get("firstIndexDate") or "")[:10] or None,
        "journal": journal, "preprint": preprint, "authors": len(authors),
        "senior_first": first, "senior_last": senior.get("lastName"),
        "senior_author": " ".join(x for x in (first, senior.get("lastName")) if x) or None,
        "senior_addresses": addresses[-1] if addresses else [],
        "all_addresses": [x for theirs in addresses for x in theirs]}


def _later(stage, than) -> bool:
    return stage is not None and (than is None or D.STAGES.index(stage) > D.STAGES.index(than))


class EuropePmcPapersFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, today=None):
        super().__init__(db_path)
        self.today = today
        self.window: tuple | None = None
        self.problems: list[str] = []

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    # --- the fetch ----------------------------------------------------------
    def _today(self) -> dt.date:
        return self.today or dt.datetime.now(dt.timezone.utc).date()

    def _window(self) -> tuple:
        """(first, last) index dates to read. Three weeks; the first run reaches back to
        the day the labs were ranked, so each lab's state is carried forward whole."""
        today = self._today()
        first = today - dt.timedelta(days=WINDOW_DAYS)
        conn = db.get_connection(self.db_path)
        try:
            D.load_labs(conn)                   # insert-only; nothing if already there
            conn.commit()
            held = conn.execute("SELECT COUNT(*) FROM discovery_papers").fetchone()[0]
            ranked = conn.execute("SELECT MIN(ranked_as_of) FROM discovery_labs").fetchone()[0]
        finally:
            conn.close()
        if not held and ranked:
            first = min(first, max(dt.date.fromisoformat(ranked),
                                   today - dt.timedelta(days=FIRST_WINDOW_MAX_DAYS)))
        return first, today + dt.timedelta(days=1)

    def _get(self, params: dict) -> dict:
        request = urllib.request.Request(
            f"{SEARCH_URL}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": contact.user_agent(), "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.load(resp)

    def fetch(self) -> list[dict]:
        self.window = self._window()
        first, last = (d.isoformat() for d in self.window)
        out = []
        for source, extra in SOURCES:
            query = f"SRC:{source} AND {D.QUERY} AND FIRST_IDATE:[{first} TO {last}]{extra}"
            cursor = "*"
            while True:
                data = self._get({"query": query, "format": "json", "resultType": "core",
                                  "pageSize": PAGE_SIZE, "cursorMark": cursor})
                batch = (data.get("resultList") or {}).get("result") or []
                out.extend(batch)
                following = data.get("nextCursorMark")
                if len(batch) < PAGE_SIZE or not following or following == cursor:
                    break
                cursor = following
                time.sleep(_PAUSE_S)
        return out

    def normalise(self, raw) -> list[dict]:
        rows, seen = [], set()
        for record in raw:
            row = parse(record)
            if row is None:
                self.problems.append(f"{record.get('source')}:{record.get('id')}: no title or date")
            elif row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        # Oldest first, so a lab's papers move its state in the order they arrived.
        rows.sort(key=lambda r: (r["indexed"] or r["published"], r["id"]))
        return rows

    # --- snapshots ----------------------------------------------------------
    def snapshot(self, rows: list[dict]) -> None:
        first, last = self.window or (None, None)
        self._write_snapshot("feed", ENTITY_KEY, {
            "records": len(rows), "without_abstract": sum(not r["abstract"].strip() for r in rows),
            "indexed_from": first.isoformat() if first else None,
            "indexed_to": last.isoformat() if last else None,
            "problems": self.problems[:20], "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot("feed", ENTITY_KEY, {"fetch_kind": "cache"})

    def _write_snapshot(self, entity_type: str, key: str, payload: dict, conn=None) -> None:
        own = conn is None
        conn = conn or db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, ?, ?, ?, ?)",
                (self.source, entity_type, key, json.dumps(payload), self.refresh_run_id))
            if own:
                conn.commit()
        finally:
            if own:
                conn.close()

    def _last(self, conn, entity_type: str, key: str) -> dict | None:
        row = conn.execute(
            "SELECT payload FROM snapshots WHERE source = ? AND entity_type = ?"
            " AND entity_key = ? ORDER BY id DESC LIMIT 1",
            (self.source, entity_type, key)).fetchone()
        return json.loads(row["payload"]) if row else None

    # --- the write ----------------------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        today = self._today().isoformat()
        scorer = D.scorer()
        version = scorer.version if scorer else None
        conn = db.get_connection(self.db_path)
        added = 0
        try:
            labs = D.lab_index(conn)
            states: dict = {}
            for row in rows:
                held = conn.execute("SELECT * FROM discovery_papers WHERE id = ?",
                                    (row["id"],)).fetchone()
                text = D.text_of(row["raw_title"], row["abstract"])
                read = bool(row["abstract"].strip())
                sha = D.text_sha(text) if read else None
                lab_id, how = (held["lab_id"], held["lab_match"]) if held and held["lab_id"] \
                    else labs.match(row["senior_first"], row["senior_last"],
                                    row["senior_addresses"])
                institution = next(
                    (found for found in map(D.institution_of, row["senior_addresses"]) if found),
                    None)
                # A company among the authors can only be said where addresses are printed.
                company = int(D.company_among(row["all_addresses"])) \
                    if row["all_addresses"] else None
                if held and held["text_sha"] == sha and held["model_version"] == version:
                    scored = {k: held[k] for k in ("feas_score", "feas_pct", "comm_score",
                                                   "comm_pct", "reasons", "scored_at")}
                elif read and scorer:
                    got = scorer.score(row["raw_title"], row["abstract"], row["preprint"])
                    scored = {"feas_score": got["feas"]["score"], "feas_pct": got["feas"]["pct"],
                              "comm_score": got["comm"]["score"], "comm_pct": got["comm"]["pct"],
                              "reasons": json.dumps({"feas": got["feas"]["reasons"],
                                                     "comm": got["comm"]["reasons"]}),
                              "scored_at": dt.datetime.now(dt.timezone.utc)
                              .strftime("%Y-%m-%d %H:%M:%S")}
                else:
                    scored = dict.fromkeys(("feas_score", "feas_pct", "comm_score", "comm_pct",
                                            "reasons", "scored_at"))
                found = D.flags(text) if read else {}
                stage = D.furthest(found) if read else None
                values = {
                    "source": row["source"], "pmid": row["pmid"], "doi": row["doi"],
                    "title": row["title"], "published": row["published"],
                    "indexed": row["indexed"], "journal": row["journal"],
                    "preprint": int(row["preprint"]), "authors": row["authors"],
                    "senior_author": row["senior_author"], "institution": institution,
                    "lab_id": lab_id, "lab_match": how,
                    "areas": json.dumps(D.areas(text)) if read else None,
                    "modalities": json.dumps(D.modalities(text)) if read else None,
                    "stage": stage, "company_author": company, "text_sha": sha,
                    "model_version": version if scored["feas_pct"] is not None else None,
                    **scored}
                if held:
                    conn.execute(
                        f"UPDATE discovery_papers SET {', '.join(f'{k} = ?' for k in values)},"
                        " fetched_at = datetime('now') WHERE id = ?", (*values.values(), row["id"]))
                    seen = held["first_seen"]
                else:
                    conn.execute(
                        f"INSERT INTO discovery_papers (id, first_seen, {', '.join(values)})"
                        f" VALUES (?, ?, {', '.join('?' for _ in values)})",
                        (row["id"], today, *values.values()))
                    seen = today
                    added += 1
                if not read:
                    continue                      # held until its abstract arrives
                state = {"read": True, "lab_id": lab_id, "stage": stage,
                         "company_author": company, "feas_tier": tier(scored["feas_pct"]),
                         "comm_tier": tier(scored["comm_pct"])}
                before = self._last(conn, "paper", row["id"])
                if before and all(before.get(k) == state[k] for k in _TRACKED):
                    continue
                self._write_snapshot("paper", row["id"], {
                    **state, "title": row["title"], "published": row["published"],
                    "indexed": row["indexed"], "seen": seen, "journal": row["journal"],
                    "preprint": row["preprint"], "senior_author": row["senior_author"],
                    "institution": institution, "lab_match": how,
                    "feas_pct": scored["feas_pct"], "comm_pct": scored["comm_pct"]}, conn)
                if lab_id:
                    self._move_lab(conn, labs.labs.get(lab_id), states, row, stage, company,
                                   seen)
            conn.execute("DELETE FROM discovery_papers WHERE first_seen < date(?, ?)",
                         (today, f"-{KEEP_DAYS} days"))
            conn.commit()
        finally:
            conn.close()
        notes = list(self.problems)
        if scorer is None:
            notes.append("no score model file: papers stored unscored")
        # Every record the window returned counts, new or not: a day with nothing new is a
        # quiet day, and only a window that returns nothing at all is a source gone quiet.
        return RefreshResult(self.source, len(rows), notes=notes)

    def _move_lab(self, conn, lab, states, row, stage, company, seen) -> None:
        """Write a lab's new state when this paper takes it to a later model stage or is
        its first with a company among the authors. The state before is the last snapshot,
        or the seed where there is none."""
        if lab is None:
            return
        key = lab["id"]
        if key not in states:
            states[key] = self._last(conn, "lab", key) or {
                "furthest_stage": lab["furthest_stage"],
                "company_coauthor": bool(lab["company_coauthor"])}
        was = states[key]
        now = {"furthest_stage": stage if _later(stage, was["furthest_stage"])
               else was["furthest_stage"],
               "company_coauthor": bool(was["company_coauthor"] or company)}
        if (now["furthest_stage"], now["company_coauthor"]) == (
                was["furthest_stage"], bool(was["company_coauthor"])):
            return
        states[key] = {**now, "paper": row["id"], "title": row["title"],
                       "published": row["published"], "indexed": row["indexed"],
                       "seen": seen, "journal": row["journal"], "preprint": row["preprint"]}
        self._write_snapshot("lab", key, states[key], conn)
