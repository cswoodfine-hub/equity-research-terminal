"""Label state per marketed product, from DailyMed.

Per company, the same shape as the price and trial fetchers. For each marketed asset
with a brand name it resolves a DailyMed set id once, reads the current version and
the indications section, extracts the population over the LLM seam, and upserts the
label row plus a snapshot keyed on the set id. The diff engine turns a version
increment into a label_change, and a widened population or a new indication into
their own change types.

Resolution is best effort and never guesses: a product DailyMed does not carry, or a
version already on file, simply writes nothing new. A daily TTL keeps this to one
pass; labels revise on the order of weeks.
"""

from __future__ import annotations

import json
import time

import dailymed
import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "labels"
TTL_SECONDS = 24 * 60 * 60
_POLITE_SLEEP_S = 0.4              # DailyMed is free; do not hammer it


class LabelsDailyMedFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _assets(self, conn):
        return conn.execute(
            """
            SELECT a.id, a.brand_name, a.generic_name,
                   (SELECT l.setid FROM labels l WHERE l.asset_id = a.id) AS setid
              FROM assets a JOIN companies c ON a.owner_company_id = c.id
             WHERE c.ticker = ? AND a.is_marketed = 1 AND a.brand_name IS NOT NULL
            """,
            (self.ticker,),
        ).fetchall()

    def fetch(self) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            assets = self._assets(conn)
        finally:
            conn.close()
        rows = []
        for asset in assets:
            setid = asset["setid"]
            try:
                if not setid:
                    setid = dailymed.parse_search(
                        dailymed.search(asset["brand_name"]),
                        asset["brand_name"], asset["generic_name"])
                    time.sleep(_POLITE_SLEEP_S)
                if not setid:
                    continue                       # no DailyMed label for this product
                current = dailymed.parse_history(dailymed.history(setid))
                time.sleep(_POLITE_SLEEP_S)
                if not current:
                    continue
                indications = dailymed.parse_indications(dailymed.spl_xml(setid))
                time.sleep(_POLITE_SLEEP_S)
                rows.append({
                    "asset_id": asset["id"], "setid": setid,
                    "drug_name": asset["brand_name"],
                    "spl_version": current["spl_version"],
                    "effective_time": current["published_date"],
                    "indications_text": indications,
                })
            except Exception:
                continue                            # one bad product never fails the run
        return rows

    def normalise(self, raw) -> list[dict]:
        # Population extraction happens here so the network fetch stays fast and the
        # LLM cost is paid once per product per run, only when the version is new.
        conn = db.get_connection(self.db_path)
        try:
            known = {r["setid"]: r["spl_version"] for r in conn.execute(
                "SELECT setid, spl_version FROM labels")}
        finally:
            conn.close()
        out = []
        for row in raw:
            unchanged = known.get(row["setid"]) == row["spl_version"]
            population = ({"age_floor_years": None, "age_ceiling_years": None,
                           "indication_count": None, "population_text": None}
                          if unchanged
                          else dailymed.extract_population(row["indications_text"]))
            out.append({**row, **population, "_unchanged": unchanged})
        return out

    def snapshot(self, rows: list[dict]) -> None:
        # A company-level live snapshot for the TTL clock only. The per-label
        # snapshots that feed the diff are written by diff._diff_labels from the
        # labels table, the same split trials use, so the version-change signal
        # advances its baseline exactly once and re-running detects nothing new.
        self._write_company_snapshot("live", len(rows))

    def _snapshot_cache(self) -> None:
        self._write_company_snapshot("cache", None)

    def _write_company_snapshot(self, kind: str, count) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES ('labels', 'company', ?, ?, ?)",
                (self.ticker, json.dumps({"ticker": self.ticker, "labels": count,
                                          "fetch_kind": kind}), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for row in rows:
                # A run where the version did not change keeps the population fields
                # already on file rather than overwriting them with the nulls a
                # skipped extraction returns.
                if row.get("_unchanged"):
                    conn.execute(
                        "UPDATE labels SET spl_version = ?, effective_time = ?,"
                        " fetched_at = datetime('now') WHERE setid = ?",
                        (row["spl_version"], row["effective_time"], row["setid"]))
                else:
                    conn.execute(
                        """
                        INSERT INTO labels (asset_id, setid, drug_name, spl_version,
                            effective_time, indications_text, indication_count,
                            age_floor_years, age_ceiling_years, population_text)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(setid) DO UPDATE SET
                            spl_version=excluded.spl_version,
                            effective_time=excluded.effective_time,
                            indications_text=excluded.indications_text,
                            indication_count=excluded.indication_count,
                            age_floor_years=excluded.age_floor_years,
                            age_ceiling_years=excluded.age_ceiling_years,
                            population_text=excluded.population_text,
                            fetched_at=datetime('now')
                        """,
                        (row["asset_id"], row["setid"], row["drug_name"],
                         row["spl_version"], row["effective_time"],
                         row["indications_text"], row["indication_count"],
                         row["age_floor_years"], row["age_ceiling_years"],
                         row["population_text"]))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
