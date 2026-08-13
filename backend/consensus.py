"""The consensus layer: reported, guidance, street and mine, side by side.

An analyst's forecast only means something against consensus, and the delta view is the
whole point: where do I disagree, and by how much. The table has existed since the base
schema with nothing writing to it; this module is its reader, its curated seed loader,
and the view the Street section renders.

Sources share one table and are told apart by ``source``: ``fmp`` is the street (the
key-gated fetcher), ``guidance`` is management's own numbers read out of filings, and
``manual`` is the curated CSV column the roadmap promised for anything gated. Revisions
accumulate as rows because the UNIQUE key includes ``as_of``; the reader always takes
the newest per (metric, period, source), so the history of revisions stays queryable
without ever being shown by accident.
"""

from __future__ import annotations

import csv
import pathlib

import db
import forecast_view
import fx

SEED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "consensus"

# Metrics the layer speaks. Growth is a first-class metric rather than a conversion,
# because companies that guide in growth (Novo's "sales growth of 8-14%") state exactly
# that, and deriving an absolute from it would compound a constant-currency rate onto a
# reported base the company did not use.
METRICS = ("Revenue", "EPS", "RevenueGrowth")


def latest(conn, company_id: int) -> list[dict]:
    """The newest row per (metric, period, source). Revisions stay in the table."""
    return [dict(r) for r in conn.execute(
        """SELECT e.* FROM consensus_estimates e
            WHERE e.company_id = ? AND e.as_of = (
                  SELECT MAX(e2.as_of) FROM consensus_estimates e2
                   WHERE e2.company_id = e.company_id AND e2.metric = e.metric
                     AND e2.period = e.period
                     AND COALESCE(e2.source, '') = COALESCE(e.source, ''))
            ORDER BY e.period, e.metric, e.source""", (company_id,))]


def street_view(db_path, ticker: str):
    """Per metric and period: reported beside guidance beside street beside mine.

    Reported comes from the financials table (FY rows), converted to USD beside the
    original where the filer reports in another currency, because the street's numbers
    are dollars and Novo's are kroner. Mine is the forecast roll-up's combined series,
    present only where a drug forecast exists. None means no data, never zero.
    """
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, ticker, reporting_currency FROM companies WHERE ticker = ?",
            (ticker.upper(),)).fetchone()
        if company is None:
            return None
        estimates = latest(conn, company["id"])
        reported = {}
        for row in conn.execute(
                """SELECT fiscal_year, metric, value, unit FROM financials
                    WHERE company_id = ? AND period_type = 'FY'
                      AND metric IN ('Revenues', 'EarningsPerShareDiluted')
                    ORDER BY fiscal_year""", (company["id"],)):
            key = ("Revenue" if row["metric"] == "Revenues" else "EPS",
                   f"FY{row['fiscal_year']}")
            reported[key] = {"value": row["value"], "unit": row["unit"]}
    finally:
        conn.close()

    rates = fx.latest_usd_rates(db_path) or {}
    for entry in reported.values():
        unit = (entry.get("unit") or "USD").upper()
        if unit not in ("USD", "", "SHARES") and unit in rates:
            entry["usd_value"] = fx.to_usd(entry["value"], unit, rates)
        else:
            entry["usd_value"] = entry["value"] if unit in ("USD", "") else None

    mine, mine_lines = {}, []
    rollup = forecast_view.company_rollup(db_path, ticker)
    if rollup and rollup.get("lines"):
        for year, value in rollup["combined"]:
            mine[f"FY{year}"] = value * 1e6      # the roll-up runs in millions
        # What the column actually covers. Vertex's roll-up is one drug against a
        # company guiding 13.2bn, and a reader who takes 184mm for a company forecast
        # has been misled by the layout rather than by a number. The names travel with
        # the figure so the view can say which assets are in it.
        mine_lines = [line["name"] for line in rollup["lines"]]

    periods = sorted({e["period"] for e in estimates}
                     | {p for _m, p in reported} | set(mine))
    by_key = {}
    for estimate in estimates:
        by_key.setdefault((estimate["metric"], estimate["period"]), {})[
            estimate["source"] or "manual"] = estimate

    rows = []
    for (metric, period), sources in sorted(by_key.items()):
        entry = {"metric": metric, "period": period,
                 "reported": reported.get((metric, period)),
                 "guidance": sources.get("guidance"),
                 "street": sources.get("fmp") or sources.get("manual"),
                 "mine": mine.get(period) if metric == "Revenue" else None}
        street = entry["street"]
        if street and street.get("value"):
            if entry["mine"] is not None:
                entry["mine_vs_street"] = entry["mine"] / street["value"] - 1.0
            if entry["guidance"] and entry["guidance"].get("value") \
                    and metric != "RevenueGrowth":
                entry["guidance_vs_street"] = (entry["guidance"]["value"]
                                               / street["value"] - 1.0)
        rows.append(entry)
    # Reported-only periods still show, so the strip reads as one series ending in
    # estimates rather than estimates floating alone.
    for (metric, period), value in sorted(reported.items()):
        if (metric, period) not in by_key and (period in periods):
            if any(r["period"] == period for r in rows) or period >= max(
                    periods[:1] + [p for _m, p in reported]):
                rows.append({"metric": metric, "period": period,
                             "reported": value, "guidance": None, "street": None,
                             "mine": mine.get(period) if metric == "Revenue"
                             else None})
    rows.sort(key=lambda r: (r["period"], r["metric"]))
    return {"ticker": company["ticker"], "rows": rows,
            "mine_lines": mine_lines,
            "reporting_currency": company["reporting_currency"]}


def load_seeds(conn, directory=None) -> dict:
    """data/consensus/*.csv into the table, insert-only, like the assumption seeds.

    The manual column: a curated street or guidance figure an analyst wrote down, with
    its source and date. A row that already exists is never overwritten, so a live
    revision beats the file it started from.
    """
    source_dir = pathlib.Path(directory) if directory else SEED_DIR
    written = skipped = 0
    if not source_dir.exists():
        return {"written": 0, "skipped": 0}
    for path in sorted(source_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            ticker = (row.get("ticker") or "").strip().upper()
            company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                   (ticker,)).fetchone()
            if not company or not (row.get("metric") or "").strip():
                skipped += 1
                continue
            cursor = conn.execute(
                """INSERT OR IGNORE INTO consensus_estimates
                       (company_id, metric, period, value, low, high, currency,
                        source, as_of, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (company["id"], row["metric"].strip(), (row.get("period") or "").strip(),
                 float(row["value"]) if (row.get("value") or "").strip() else None,
                 float(row["low"]) if (row.get("low") or "").strip() else None,
                 float(row["high"]) if (row.get("high") or "").strip() else None,
                 (row.get("currency") or "").strip() or None,
                 (row.get("source") or "manual").strip(),
                 (row.get("as_of") or "").strip(),
                 (row.get("note") or "").strip() or None))
            written += cursor.rowcount
    conn.commit()
    return {"written": written, "skipped": skipped}
