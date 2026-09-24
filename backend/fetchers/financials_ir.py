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

ONE FETCHER, A REGISTRY OF ONE. Bayer is in the same position and is not here, because its
equivalent file has not been found: it reports under EU rules whose electronic format is
inline XBRL rather than a workbook, and that is a different parser. The shape is ready for
it; the source is not.
"""

from __future__ import annotations

import io
import json
import urllib.request

import db
import roche
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "financials_ir"
TTL_SECONDS = 24 * 60 * 60          # the workbook moves with the results calendar
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 120

# What each company publishes, and the sheets to read it from. A company absent here has
# no machine-readable statement on file and the fetcher does not run for it.
WORKBOOKS = {
    "ROG": {
        "url": roche.SOURCE_URL,
        "currency": roche.CURRENCY,
        "income": roche.INCOME_SHEET,
        "balance": roche.BALANCE_SHEET,
        "products": roche.PRODUCT_SHEET,
        "sales": "Group Sales CHF",
        "division": "Pharmaceuticals Division",
        "note": "Roche Finance Information Tool, group financial data workbook",
    },
}

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

    @property
    def entity_key(self) -> str:
        return self.ticker

    def fetch(self) -> list[dict]:
        """The workbook, as the sheets this reads. One request."""
        request = urllib.request.Request(self.spec["url"],
                                        headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            payload = response.read()
        return [{"bytes": payload}]

    def normalise(self, raw) -> list[dict]:
        import openpyxl
        if not raw or not raw[0].get("bytes"):
            return []
        book = openpyxl.load_workbook(io.BytesIO(raw[0]["bytes"]), data_only=True)
        spec = self.spec
        income = roche.cells(book[spec["income"]])
        balance = roche.cells(book[spec["balance"]])
        products = roche.cells(book[spec["products"]])
        sales = roche.cells(book[spec["sales"]])

        problems = roche.reconcile(income)
        if problems:
            self._notes.extend(problems)
            self._notes.append("the income statement did not tie, so no statement row was "
                               "written: check the sheet's labels against roche.py")
            statement = []
        else:
            statement = ([{**r, "kind": "income"} for r in roche.parse_income(income)]
                         + [{**r, "kind": "balance"} for r in roche.parse_balance(balance)])
            shares = roche.shares_from(roche.parse_income(income))
            for year, count in shares.items():
                # The metric name the rest of the book reads. forecast_view._diluted_shares
                # looks for WeightedAverageDilutedShares first and otherwise falls back to
                # group net income over earnings per share, which for Roche is wrong by the
                # non-controlling interest: 13,799 / 16.04 is 860.3mm against the true
                # 803.0mm, because the per-share figure is struck on the 12,880mm
                # attributable to shareholders. Roche is the only filer in this universe
                # with a material minority, so writing the count under the name the reader
                # already uses is what keeps that fallback off it.
                statement.append({
                    "kind": "income", "metric": "WeightedAverageDilutedShares",
                    "fiscal_year": year, "value": count, "unit": "shares",
                    "label": "earnings attributable to shareholders over diluted "
                             "earnings per share"})

        product_rows = roche.parse_products(products)
        division = roche.division_sales(sales, spec["division"])
        product_problems = roche.reconcile_products(product_rows, division)
        if product_problems:
            self._notes.extend(product_problems)
            self._notes.append("the per-product sales did not sum to the division, so no "
                               "product revenue was written")
            product_rows = []
        return statement + [{**r, "kind": "product"} for r in product_rows]

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

    def _match(self, product: str, brands: dict):
        """The asset a Roche product name belongs to, or None."""
        name = product.strip().lower()
        if name in _RESIDUAL:
            return None
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
                if row["kind"] in ("income", "balance"):
                    period_end = row.get("period_end") or f'{row["fiscal_year"]}-12-31'
                    conn.execute(
                        """
                        INSERT INTO financials
                            (company_id, period_end, period_type, metric, value, unit,
                             fiscal_year, fiscal_period, source)
                        VALUES (?, ?, 'FY', ?, ?, ?, ?, 'FY', ?)
                        ON CONFLICT(company_id, metric, period_end, period_type)
                          DO UPDATE SET value=excluded.value, unit=excluded.unit,
                            fiscal_year=excluded.fiscal_year, source=excluded.source
                        """,
                        (company["id"], period_end, row["metric"], row["value"],
                         row["unit"], row["fiscal_year"], SOURCE))
                    written += 1
                    continue
                asset_id = self._match(row["product"], brands)
                if asset_id is None:
                    if row["product"].strip().lower() not in _RESIDUAL:
                        missing.add(row["product"])
                        unmatched += 1
                    continue
                if row["region"] is None:
                    conn.execute(
                        """
                        INSERT INTO asset_revenue
                            (asset_id, fiscal_year, period, value, unit, source, note,
                             is_curated)
                        VALUES (?, ?, 'FY', ?, ?, ?, ?, 0)
                        ON CONFLICT(asset_id, fiscal_year, period) DO UPDATE SET
                            value=excluded.value, unit=excluded.unit,
                            source=excluded.source, note=excluded.note,
                            updated_at=datetime('now')
                        """,
                        (asset_id, row["fiscal_year"], row["value"], row["unit"],
                         self.spec["note"], f'{self.spec["products"]} sheet, '
                                            f'{row["product"]} global sales'))
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
        if missing:
            notes.append(f"{len(missing)} product lines matched no asset and were not "
                         f"written: {', '.join(sorted(missing))}")
        return RefreshResult(self.source, written, notes=notes)
