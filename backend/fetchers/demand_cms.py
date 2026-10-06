"""Medicare demand from the CMS Spending by Drug datasets.

One universe fetcher pulls the Part D and Part B drug spending tables, matches each drug
to a tracked asset by brand name, and stores the per-year volume as a demand time series
(migration 007). A brand outside the universe is dropped; the match is an exact brand
name, so a drug binds to its own asset and nothing is guessed.

CMS updates the tables about once a year, so the TTL is weekly. Part D is filtered
server side to the Overall rows, one per brand across its manufacturers; Part B carries
no manufacturer split. Both are paged through in full and matched in memory, which is a
few thousand rows.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import cms
import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "demand"
ENTITY_KEY = "cms"
TTL_SECONDS = 7 * 24 * 60 * 60          # CMS publishes yearly; refresh weekly
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 90
_PAGE = 5000


# The name rules (footnote markers, billing codes, containers) and the brand map are
# shared with the Part D Prescribers reader, so they live in cms.py. These names stay so
# that nothing reading them from here has to change.
_CODE_SUFFIX = cms.CODE_SUFFIX
_norm = cms.norm
_PRESENTATION_WORDS = cms.PRESENTATION_WORDS
_PRESENTATION_TAIL = cms.PRESENTATION_TAIL
base_brand = cms.base_brand


def _combine_presentations(rows: list[dict], own_name: dict) -> list[dict]:
    """One row per asset, part and year: the containers summed, the molecule not blended.

    Two different things both used to land on one key and silently overwrite each other,
    because the table holds one row per asset, part and year and the upsert let the last
    row written win. Which one that was depended on the order CMS returned, so the series
    was arbitrary. They need opposite treatment.

    Containers are summed. CMS splits a brand by the device it ships in, and there is no
    "Repatha" row at all, only Sureclick, Syringe and Pushtronex. Spending, claims and
    dosage units add exactly. Distinct beneficiaries do not: a patient who moved from the
    syringe to the autoinjector inside one year is in both counts, so the total is an
    upper bound, which is why the brand says how many containers are in it. A count CMS
    suppressed stays out of the sum rather than becoming a zero, which leaves the total
    short, and that is recorded the same way.

    Two different products are not summed. CMS keys a Part D row on the brand and the
    ingredient together, so one brand string can carry two products: "Meloxicam" is both
    plain meloxicam at 4,115,676 beneficiaries and $12.52 each, and "Meloxicam,
    Submicronized" at 6,756 and $2,401 each. The generic fallback in the brand map creates
    the same collision between a brand and its own generic, listing Lyrica and Pregabalin,
    Crestor and Rosuvastatin, Esbriet and Pirfenidone. Adding either pair up answers how
    many people took the molecule and destroys what the row is actually used for, which is
    the branded product's price per beneficiary: a blend of Crestor and generic
    rosuvastatin is neither of them. So containers are summed only within one ingredient,
    which is how CMS itself distinguishes them, and between ingredients the asset's own
    names win. Every one of the 92 colliding groups in the 2024 payload carries the
    asset's own brand name, so nothing has to be guessed at.
    """
    summed: dict[tuple, dict] = {}
    for row in rows:
        key = (row["asset_id"], row["part"], row["year"], row["base"], row["generic"])
        held = summed.get(key)
        if held is None:
            summed[key] = {**row, "_brands": [row["brand"]],
                           "_suppressed": int(row["total_beneficiaries"] is None)}
            continue
        held["_brands"].append(row["brand"])
        for field in ("total_spending", "total_claims", "total_dosage_units"):
            a, b = held[field], row[field]
            held[field] = b if a is None else (a if b is None else a + b)
        if row["total_beneficiaries"] is None:
            held["_suppressed"] += 1
        else:
            held["total_beneficiaries"] = (
                (held["total_beneficiaries"] or 0) + row["total_beneficiaries"])

    by_year: dict[tuple, list] = {}
    for (asset_id, part, year, _, _), row in summed.items():
        by_year.setdefault((asset_id, part, year), []).append(row)

    out = []
    for (asset_id, part, _), candidates in by_year.items():
        chosen, dropped = _choose(candidates, *own_name.get(asset_id, (None, None)))
        brands, suppressed = chosen.pop("_brands"), chosen.pop("_suppressed")
        chosen.pop("base", None), chosen.pop("generic", None)
        notes = []
        if len(brands) > 1:
            chosen["brand"] = f"{_shared_prefix(brands)} ({len(brands)} presentations)"
            notes.append("summed over the presentations CMS lists separately: "
                         + ", ".join(sorted(brands))
                         + ". Beneficiaries are the sum of the distinct counts, so a "
                           "patient who changed container during the year is counted twice")
            if suppressed:
                notes.append(f"{suppressed} of {len(brands)} beneficiary counts were "
                             f"suppressed by CMS and are not in the total")
        if dropped:
            notes.append("CMS lists other products against this asset too ("
                         + ", ".join(sorted(f'{d["brand"]} / {d["generic"]}'
                                            for d in dropped))
                         + "), which are not added in: this row is the branded product, "
                           "not the molecule, so that a price per beneficiary stays a "
                           "branded price")
        if notes:
            chosen["source"] = "cms, " + ". ".join(notes)
        out.append(chosen)
    return out


def _choose(candidates: list[dict], own_brand: str | None, own_generic: str | None):
    """The row that is the asset, and the rows that are only near it.

    A candidate scores for carrying the asset's own brand name and again for its own
    ingredient, so Crestor beats Rosuvastatin and plain Meloxicam beats the submicronized
    form. Nothing scoring means nothing matched, and then the largest is the best reading
    of which product the asset is.
    """
    if len(candidates) == 1:
        return candidates[0], []
    def score(row):
        return (2 * int(bool(own_brand) and row["base"] == own_brand)
                + int(bool(own_generic) and row["generic"] == own_generic),
                row["total_spending"] or 0)
    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0], ranked[1:]


def _shared_prefix(brands: list[str]) -> str:
    """The leading words every container of one drug shares, as CMS spells them."""
    split = [b.rstrip("*").strip().split() for b in brands]
    shared = []
    for words in zip(*split):
        if len({w.lower() for w in words}) > 1:
            break
        shared.append(words[0])
    return " ".join(shared) or brands[0]


class DemandCmsFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _page_through(self, url: str, params: dict) -> list[dict]:
        rows, offset = [], 0
        while True:
            query = urllib.parse.urlencode({**params, "size": _PAGE, "offset": offset})
            request = urllib.request.Request(
                f"{url}?{query}", headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                batch = json.loads(resp.read().decode("utf-8", "replace"))
            rows.extend(batch)
            if len(batch) < _PAGE:
                break
            offset += _PAGE
        return rows

    def fetch(self) -> list[dict]:
        part_d = self._page_through(cms.PART_D_URL, {"filter[Mftr_Name]": "Overall"})
        part_b = self._page_through(cms.PART_B_URL, {})
        return ([{**r, "_part": "D"} for r in part_d]
                + [{**r, "_part": "B"} for r in part_b])

    def _brand_map(self, conn) -> dict:
        """{normalised name: asset_id}, by brand and then by generic name
        (``cms.brand_map``)."""
        return cms.brand_map(conn)

    def normalise(self, raw) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            brand_map = self._brand_map(conn)
            own_name = cms.own_names(conn)
        finally:
            conn.close()
        rows = []
        for item in raw:
            asset_id, base = cms.match_brand(item.get("Brnd_Name"), brand_map)
            if asset_id is None:
                continue                       # a drug outside the universe
            generic = _norm(item.get("Gnrc_Name"))
            for record in cms.parse_row(item, item["_part"]):
                rows.append({**record, "asset_id": asset_id, "base": base,
                             "generic": generic})
        return _combine_presentations(rows, own_name)

    def snapshot(self, rows: list[dict]) -> None:
        assets = len({r["asset_id"] for r in rows})
        self._write_snapshot({"records": len(rows), "assets": assets,
                              "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"fetch_kind": "cache"})

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

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO drug_demand
                        (asset_id, part, brand_name, year, total_spending,
                         total_claims, total_beneficiaries, total_dosage_units,
                         source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(asset_id, part, year) DO UPDATE SET
                        brand_name = excluded.brand_name,
                        total_spending = excluded.total_spending,
                        total_claims = excluded.total_claims,
                        total_beneficiaries = excluded.total_beneficiaries,
                        total_dosage_units = excluded.total_dosage_units,
                        source = excluded.source,
                        fetched_at = datetime('now')
                    """,
                    (row["asset_id"], row["part"], row["brand"], row["year"],
                     row["total_spending"], row["total_claims"],
                     row["total_beneficiaries"], row["total_dosage_units"],
                     row.get("source") or "cms"))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
