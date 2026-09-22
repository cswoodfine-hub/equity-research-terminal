"""Two narrow policy lanes from the Federal Register, as dated context and nothing more.

Everything else in the markets work had to state a measured per-share effect before it
earned a place. No policy fact can, because the numbers that would turn a tariff
proceeding into a charge are not published: the imported share of cost of goods is not
free data and the most-favoured-nation deal terms are undisclosed. So these documents
arrive on a second route, admitted on a publication date and a stable document number
from a primary source, and they carry no modelled number, no threshold and no forecast
hook.

Precision is the whole difficulty, and the gates here were measured before they were
written rather than chosen and hoped for. An agency and a search term alone put a
Framework for Artificial Intelligence Diffusion in a pharmaceutical tariff lane and six
recurring information-collection notices in a drug pricing one, and those notices carry
a real comment deadline that would land on a horizon rail as a date somebody has to
care about.

One field name matters. ``fields[]=presidential_document_type`` is not valid and 400s
the whole request with "field 'presidential_document_type' not valid"; the field is
``subtype``. An invalid agency slug fails differently and loudly, with
``{"errors":{"agencies":"invalid value"}}`` rather than an empty result set, which is
why a bad slug is raised here rather than read as a quiet day.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "policy"
ENTITY_KEY = "fedreg"
TTL_SECONDS = 24 * 60 * 60
API_URL = "https://www.federalregister.gov/api/v1/documents.json"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30

# Everything the context route shows, and nothing it does not. subtype rather than
# presidential_document_type, which is not a field and 400s the request.
FIELDS = ("document_number", "title", "type", "subtype", "publication_date",
          "effective_on", "comments_close_on", "docket_ids", "html_url")

# Where the lanes start. The anchor documents sit well outside any rolling window: the
# Section 232 pharmaceutical investigation was published 2025-04-16. A 180-day window
# would never have fetched the document the whole lane exists to carry.
SEED_FROM = "2025-01-01"

# How far back a maintenance run looks once the seed is in. Generous against a weekly
# TTL, because a missed run must not open a hole.
ROLLING_DAYS = 120

LANES = {
    "bis_pharma": {
        "agency": "industry-and-security-bureau",
        "term": "pharmaceuticals",
        # Measured from 2025-01-01: five hits, of which a Framework for Artificial
        # Intelligence Diffusion and a Section 232 investigation into personal
        # protective equipment and medical devices are not about medicines. The title
        # gate leaves the two that are.
        "title_must_match": re.compile(r"pharmaceutical", re.I),
        "docket_must_match": None,
        "about": "Section 232 tariffs on pharmaceuticals",
    },
    "cms_ira": {
        "agency": "centers-for-medicare-medicaid-services",
        "term": "drug price negotiation",
        "title_must_match": None,
        # Measured from 2025-01-01: twenty-seven hits, seven of which carry a CMS-42xx
        # docket. The twenty dropped are hospital payment rules, Medicaid managed care,
        # the ACA benefit notice, and six information-collection notices whose real
        # comment deadlines would otherwise reach the rail.
        "docket_must_match": re.compile(r"CMS-42\d\d"),
        "about": "Medicare drug price negotiation rulemaking",
    },
}


def _url(lane: dict, since: str, page: int = 1) -> str:
    params = [("per_page", "100"), ("order", "newest"), ("page", str(page)),
              ("conditions[publication_date][gte]", since),
              ("conditions[agencies][]", lane["agency"]),
              ("conditions[term]", lane["term"])]
    params += [("fields[]", f) for f in FIELDS]
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def keep(lane: dict, row: dict) -> bool:
    """Whether a document belongs in its lane. Pure, so a gate can be argued with.

    A document with no docket at all fails a docket gate rather than passing it: the
    gate exists because the agency publishes a great deal that is not this subject, and
    an ungated row is exactly what it is there to refuse.
    """
    title_rule = lane.get("title_must_match")
    if title_rule and not title_rule.search(row.get("title") or ""):
        return False
    docket_rule = lane.get("docket_must_match")
    if docket_rule:
        dockets = row.get("docket_ids") or []
        if not any(docket_rule.search(d or "") for d in dockets):
            return False
    return True


def parse(payload: dict, lane_key: str, lane: dict) -> list[dict]:
    """The documents in one response that pass the lane's gate. Pure.

    Raises where the API reports an error rather than returning an empty list, because
    a bad agency slug and a quiet week look identical once the errors key is dropped.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"{lane_key}: response was not an object")
    if payload.get("errors"):
        raise ValueError(f"{lane_key}: {json.dumps(payload['errors'])}")
    out = []
    for row in payload.get("results") or []:
        if not row.get("document_number") or not row.get("publication_date"):
            continue
        if not keep(lane, row):
            continue
        dockets = [d for d in (row.get("docket_ids") or []) if d]
        out.append({
            "lane": lane_key,
            "document_number": row["document_number"],
            "title": row.get("title") or "",
            "doc_type": row.get("type"),
            "subtype": row.get("subtype"),
            "docket_id": dockets[0] if dockets else None,
            "published_on": row["publication_date"],
            # The document's own dates, and a null stays null. Four of the seven gated
            # CMS rows carry no comment deadline, and inventing one would put a date on
            # the horizon rail that nobody set.
            "effective_on": row.get("effective_on"),
            "comments_close_on": row.get("comments_close_on"),
            "url": row.get("html_url"),
        })
    return out


def since_for(db_path=None, conn=None) -> str:
    """The seed date until the lanes hold something, then a rolling window.

    Seeding from a date rather than a window is the point: the Section 232 initiation
    of 2025-04-16 sits outside any window a daily fetcher would use, so a rolling-only
    lane would never carry the document it exists for.
    """
    own = conn is None
    c = db.get_connection(db_path) if own else conn
    try:
        held = c.execute("SELECT COUNT(*) FROM policy_items").fetchone()[0]
    finally:
        if own:
            c.close()
    if not held:
        return SEED_FROM
    return (dt.date.today() - dt.timedelta(days=ROLLING_DAYS)).isoformat()


class PolicyFedRegFetcher(BaseFetcher):
    """Two lanes of dated policy context, gated on what was measured."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> dict:
        self._soft: list[str] = []
        since = since_for(self.db_path)
        out: dict = {"since": since, "lanes": {}}
        for key, lane in LANES.items():
            request = urllib.request.Request(
                _url(lane, since), headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                    out["lanes"][key] = json.loads(resp.read().decode("utf-8",
                                                                     "replace"))
            except urllib.error.HTTPError as exc:
                self._soft.append(f"{key}: HTTP {exc.code}")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self._soft.append(f"{key}: {type(exc).__name__}")
        return out

    def normalise(self, raw: dict) -> list[dict]:
        rows = []
        for key, payload in ((raw or {}).get("lanes") or {}).items():
            try:
                rows += parse(payload, key, LANES[key])
            except ValueError as exc:
                self._soft.append(str(exc))
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        counts: dict = {}
        for row in rows:
            counts[row["lane"]] = counts.get(row["lane"], 0) + 1
        self._write({"lanes": counts,
                     "newest": max((r["published_on"] for r in rows), default=None)},
                    "live")

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            counts = {r[0]: r[1] for r in conn.execute(
                "SELECT lane, COUNT(*) FROM policy_items GROUP BY lane")}
            newest = conn.execute(
                "SELECT MAX(published_on) FROM policy_items").fetchone()[0]
        finally:
            conn.close()
        self._write({"lanes": counts, "newest": newest}, "cache")

    def _write(self, payload: dict, fetch_kind: str) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'policy', ?, ?, ?)",
                (SOURCE, ENTITY_KEY,
                 json.dumps({**payload, "fetch_kind": fetch_kind}),
                 self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                conn.execute(
                    """INSERT INTO policy_items
                           (lane, document_number, title, doc_type, subtype, docket_id,
                            published_on, effective_on, comments_close_on, url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(document_number) DO UPDATE SET
                           title = excluded.title,
                           effective_on = excluded.effective_on,
                           comments_close_on = excluded.comments_close_on,
                           docket_id = excluded.docket_id,
                           fetched_at = datetime('now')""",
                    (row["lane"], row["document_number"], row["title"],
                     row["doc_type"], row["subtype"], row["docket_id"],
                     row["published_on"], row["effective_on"],
                     row["comments_close_on"], row["url"]))
                written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(SOURCE, written, errors=list(getattr(self, "_soft", [])),
                             notes=[f"{written} policy documents"])


def recent(db_path=None, days: int = 365, lane: str | None = None) -> list[dict]:
    """Dated policy context, newest first. Read-only and never a modelled number."""
    sql = ["SELECT lane, document_number, title, doc_type, subtype, docket_id,",
           "       published_on, effective_on, comments_close_on, url",
           "  FROM policy_items WHERE published_on >= ?"]
    since = (dt.date.today() - dt.timedelta(days=max(1, int(days)))).isoformat()
    args: list = [since]
    if lane:
        sql.append("AND lane = ?")
        args.append(lane)
    sql.append("ORDER BY published_on DESC, document_number DESC")
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(" ".join(sql), args)]
    finally:
        conn.close()
