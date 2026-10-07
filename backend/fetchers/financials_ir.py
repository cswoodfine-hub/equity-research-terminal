"""Financials for a company that does not file with the SEC, from its own IR workbook.

``financials_edgar`` needs a CIK. Two companies in this universe have none, Roche and
Bayer, and until now they carried no financial row at all: no cost structure, no tax rate,
no debt and no share count, so nothing they own could be valued. Roche has 101 assets, 46
of them marketed and earning CHF 47.7bn a year, and every one of them was worth nothing in
this book.

Roche answers the question itself. Its Finance Information Tool publishes a workbook of
group financial data for investors to model from, free and without a login, holding the
IFRS income statement, the consolidated balance sheet and per-product sales split by
region. The parsing lives in ``roche.py``; this is the download and the write.

WHAT IT REFUSES TO DO. A spreadsheet is a human document and Roche will move a row in it.
Every subtotal in the sheet is the sum of the lines above it and the 26 named products sum
to the Pharmaceuticals Division exactly, so the parse can check itself, and this fetcher
writes nothing for a statement that does not tie. A financial row that is wrong is worse
than one that is missing, because the missing one is visible in the view and the wrong one
is not. What failed comes back in ``notes`` so a refresh says so rather than going quiet.

ONE FETCHER, ONE READER PER COMPANY. Bayer is in the same position and publishes the same
kind of file: every table of its annual report as one workbook, read by ``bayer.py``. The
ESEF route built for it first cannot reach it, because the index it reads carries no German
filer. Each reader gives the addresses to try and turns a loaded workbook into records and
notes; this fetcher downloads, dispatches and writes.
"""

from __future__ import annotations

import io
import json
import urllib.request

import urllib.error

import bayer
import db
import roche
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "financials_ir"
TTL_SECONDS = 24 * 60 * 60          # the workbook moves with the results calendar
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 120

# What each company publishes, and the module that reads it. A company absent here has
# no machine-readable statement on file and the fetcher does not run for it.
WORKBOOKS = {
    "ROG": {"reader": roche, "note": roche.NOTE, "products": roche.PRODUCT_SHEET,
            "aliases": {}},
    "BAYN": {"reader": bayer, "note": bayer.NOTE, "products": bayer.PRODUCT_SHEET,
             "aliases": bayer.PRODUCT_ALIASES,
             # The half-year report's product table, for the latest first halves.
             "interim": {"urls": bayer.half_year_urls, "read": bayer.read_half_year,
                         "note": bayer.HALF_YEAR_NOTE},
             # A best-selling product with no row of Bayer's own gets one. Eylea and
             # Xarelto are Bayer's sales outside the US of molecules the book holds under
             # Regeneron and Johnson & Johnson, and Adalat, Aspirin Cardio and Glucobay
             # were never in an FDA register, so without this their revenue had nowhere
             # to land. The row is Bayer's, never the partner's.
             "create_unmatched": True},
}

# The note a row this fetcher creates carries, as the SEC revenue fetcher marks its own.
CREATED_NOTE = ("created from product revenue the company publishes in its own annual "
                "report workbook; no Orange Book or openFDA entry under this company")

# Roche's own region names, mapped to the codes the rest of the book uses. "International"
# is everything outside the three named markets, which is what ROW means here.
REGIONS = {
    "United States": ("US", "US"),
    "Europe": ("EU", "Europe"),
    "Japan": ("JP", "Japan"),
    "International": ("ROW", "International"),
}

# A residual line, not a product. Keeping it would double count the named ones.
_RESIDUAL = {"other products"}


class FinancialsIrFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self.spec = WORKBOOKS[self.ticker]
        self._notes: list[str] = []
        self._created: list[str] = []

    @property
    def entity_key(self) -> str:
        return self.ticker

    def fetch(self) -> list[dict]:
        """The workbook, from the first address the reader offers that answers.

        Bayer's report has a new address every year and is published in March, so the
        newest address can be a 404 for months before it exists. That is a fall back, not a
        failure; any other error is.
        """
        last_error = None
        for url in self.spec["reader"].source_urls():
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                    annual = {"bytes": response.read(), "url": url}
                return [annual] + self.fetch_interim()
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                last_error = exc
                self._notes.append(f"{url} is not published yet, so the one before it "
                                   f"was read")
        raise last_error or RuntimeError(f"no workbook address for {self.ticker}")

    def fetch_interim(self) -> list[dict]:
        """The interim workbook, where the company publishes one. Optional: a missing or
        failing interim report is a note, never a failed run, because the annual
        statements stand without it."""
        spec = self.spec.get("interim")
        if not spec:
            return []
        for url in spec["urls"]():
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                    return [{"bytes": response.read(), "url": url, "interim": True}]
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    self._notes.append(f"{url} answered {exc.code}, so no interim "
                                       f"figures were read")
                    return []
            except (urllib.error.URLError, TimeoutError) as exc:
                self._notes.append(f"{url} could not be read ({exc}), so no interim "
                                   f"figures were read")
                return []
        self._notes.append("no interim report is published yet")
        return []

    def normalise(self, raw) -> list[dict]:
        import openpyxl
        if not raw or not raw[0].get("bytes"):
            return []
        book = openpyxl.load_workbook(io.BytesIO(raw[0]["bytes"]), data_only=True)
        records, notes = self.spec["reader"].read_book(book)
        self._notes.extend(notes)
        interim = self.spec.get("interim")
        for item in raw[1:]:
            if not (item.get("interim") and item.get("bytes") and interim):
                continue
            book = openpyxl.load_workbook(io.BytesIO(item["bytes"]), data_only=True)
            found, notes = interim["read"](book)
            self._notes.extend(notes)
            records += [{**r, "note_source": interim["note"]} for r in found]
        return records

    def snapshot(self, rows: list[dict]) -> None:
        kinds: dict[str, int] = {}
        for row in rows:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        self._write_snapshot({"ticker": self.ticker, "records": len(rows),
                              "by_kind": kinds, "notes": self._notes,
                              "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"ticker": self.ticker, "fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'company', ?, ?, ?)",
                (self.source, self.entity_key, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    # --- the write ----------------------------------------------------------

    def _asset_ids(self, conn) -> dict:
        """{lowercased brand: asset_id} for this company's assets.

        Roche joins two brands with a slash where one product is sold under both names,
        "MabThera/Rituxan" and "TNKase/Activase", so each side is offered separately.
        """
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (self.ticker,)).fetchone()
        if company is None:
            return {}
        out = {}
        for row in conn.execute(
                "SELECT id, brand_name, generic_name FROM assets"
                " WHERE owner_company_id = ? AND brand_name IS NOT NULL",
                (company["id"],)):
            out.setdefault(row["brand_name"].strip().lower(), row["id"])
        return out

    def _create(self, conn, company_id: int, product: str, brands: dict) -> int:
        """A marketed row of the company's own for a product it reports and the book
        does not hold, named as the company names it. Never a partner's row: the brand
        index is this company's assets only."""
        cur = conn.execute(
            "INSERT INTO assets (owner_company_id, brand_name, is_marketed, notes)"
            " VALUES (?, ?, 1, ?)", (company_id, product.strip(), CREATED_NOTE))
        brands[product.strip().lower()] = cur.lastrowid
        self._created.append(product.strip())
        return cur.lastrowid

    def _match(self, product: str, brands: dict):
        """The asset a product line belongs to, or None.

        A line naming several brands, "Kovaltry/Jivi" or "Mirena/Kyleena/Jaydess", is the
        company's own figure for the family and goes to the first brand the book carries.
        It is not split, because the company does not split it.
        """
        name = product.strip().lower()
        if name in _RESIDUAL:
            return None
        name = self.spec["aliases"].get(name, name)
        if name in brands:
            return brands[name]
        for part in name.split("/"):
            part = part.strip()
            if part in brands:
                return brands[part]
        return None

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = unmatched = 0
        try:
            company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                   (self.ticker,)).fetchone()
            if company is None:
                return RefreshResult(self.source, 0,
                                     errors=[f"{self.ticker} is not in the universe"])
            brands = self._asset_ids(conn)
            missing = set()
            for row in rows:
                if row["kind"] in ("income", "balance", "cashflow"):
                    period_end = row.get("period_end") or f'{row["fiscal_year"]}-12-31'
                    # A balance sheet line is a stock on one day, stored as an instant the
                    # way EDGAR's are. Written as a year, it was invisible to every reader
                    # of a balance sheet: Roche carried debt and cash that net debt, the
                    # statements view and the equity bridge could not see.
                    instant = row["kind"] == "balance"
                    conn.execute(
                        """
                        INSERT INTO financials
                            (company_id, period_end, period_type, metric, value, unit,
                             fiscal_year, fiscal_period, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_id, metric, period_end, period_type)
                          DO UPDATE SET value=excluded.value, unit=excluded.unit,
                            fiscal_year=excluded.fiscal_year, source=excluded.source
                        """,
                        (company["id"], period_end, "instant" if instant else "FY",
                         row["metric"], row["value"], row["unit"], row["fiscal_year"],
                         None if instant else "FY", SOURCE))
                    written += 1
                    continue
                asset_id = self._match(row["product"], brands)
                if (asset_id is None and self.spec.get("create_unmatched")
                        and row["product"].strip().lower() not in _RESIDUAL):
                    asset_id = self._create(conn, company["id"], row["product"], brands)
                if asset_id is None:
                    if row["product"].strip().lower() not in _RESIDUAL:
                        missing.add(row["product"])
                        unmatched += 1
                    continue
                if row["region"] is None:
                    period = row.get("period") or "FY"
                    conn.execute(
                        """
                        INSERT INTO asset_revenue
                            (asset_id, fiscal_year, period, value, unit, source, note,
                             is_curated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                        ON CONFLICT(asset_id, fiscal_year, period) DO UPDATE SET
                            value=excluded.value, unit=excluded.unit,
                            source=excluded.source, note=excluded.note,
                            updated_at=datetime('now')
                        """,
                        (asset_id, row["fiscal_year"], period, row["value"], row["unit"],
                         row.get("note_source") or self.spec["note"],
                         f'{self.spec["products"]} sheet, {row["product"]} global sales'
                         + ("" if period == "FY" else f", {period}")))
                    written += 1
                    continue
                code, label = REGIONS.get(row["region"], (None, None))
                if code is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO asset_revenue_regions
                        (asset_id, fiscal_year, member, region, value, unit, source, note,
                         is_curated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(asset_id, fiscal_year, member) DO UPDATE SET
                        region=excluded.region, value=excluded.value, unit=excluded.unit,
                        source=excluded.source, note=excluded.note,
                        updated_at=datetime('now')
                    """,
                    (asset_id, row["fiscal_year"], label, code, row["value"], row["unit"],
                     self.spec["note"], f'{self.spec["products"]} sheet, '
                                        f'{row["product"]} thereof {row["region"]}'))
                written += 1
            conn.commit()
        finally:
            conn.close()
        notes = list(self._notes)
        if self._created:
            notes.append(f"{len(self._created)} products had no row of this company's own "
                         f"and were given one: {', '.join(sorted(self._created))}")
        if missing:
            notes.append(f"{len(missing)} product lines matched no asset and were not "
                         f"written: {', '.join(sorted(missing))}")
        return RefreshResult(self.source, written, notes=notes)
