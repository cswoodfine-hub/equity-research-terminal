"""Universe catalyst grid: every company against the coming months.

Cell value is the count of pending catalysts in that company-month; cell weight
is the strongest thing in the cell (a regulatory decision outweighs a derived
readout, and anything inside the soon window outweighs both); an uncurated PDUFA
extraction marks the cell for review, since a machine-read date should not pass
as a curated one.
"""

from __future__ import annotations

import datetime as dt

import db
import materiality

# Regulatory decisions are binary events with dates set by an agency; a readout
# is an estimate that moves. The grid weighs them accordingly.
_REGULATORY = ("PDUFA", "EMA decision", "AdCom")


def _months(start: dt.date, count: int) -> list[str]:
    out = []
    year, month = start.year, start.month
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def build(db_path=None, months: int = 18, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    month_keys = _months(today, months)
    horizon_end = month_keys[-1] + "-31"
    soon_end = (today + dt.timedelta(days=materiality.CATALYST_SOON_DAYS)).isoformat()

    conn = db.get_connection(db_path)
    try:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM companies ORDER BY ticker")]
        rows = conn.execute(
            """
            SELECT c.ticker, cat.expected_date, cat.catalyst_type, cat.is_curated
              FROM catalysts cat JOIN companies c ON c.id = cat.company_id
             WHERE cat.status = 'pending'
               AND cat.expected_date >= ? AND cat.expected_date <= ?
            """,
            (today.isoformat(), horizon_end),
        ).fetchall()
    finally:
        conn.close()

    cells: dict[str, dict[str, dict]] = {t: {} for t in tickers}
    for r in rows:
        month = (r["expected_date"] or "")[:7]
        if month not in month_keys or r["ticker"] not in cells:
            continue
        cell = cells[r["ticker"]].setdefault(month, {
            "count": 0, "weight": 0.0, "uncurated_pdufa": False,
            "regulatory": 0, "readouts": 0})
        cell["count"] += 1
        regulatory = r["catalyst_type"] in _REGULATORY
        soon = r["expected_date"] <= soon_end
        cell["weight"] = max(cell["weight"],
                             1.0 if soon else 0.85 if regulatory else 0.5)
        cell["regulatory"] += 1 if regulatory else 0
        cell["readouts"] += 0 if regulatory else 1
        if regulatory and not r["is_curated"]:
            cell["uncurated_pdufa"] = True
    return {"months": month_keys, "tickers": tickers, "cells": cells,
            "soon_days": materiality.CATALYST_SOON_DAYS}
