"""The recorded prices checked against the closes their sessions settled at.

A snapshot or a call priced while its session was still trading carries the last trade,
not the close (market_session.py says how that came about and what now prevents it).
Those rows stay as they were written, because what the book said on the day is the
record. This module is what stands beside them:

- ``settled_close`` is the one place a reader asks what a session closed at. It answers
  from the daily series, and only for a session the series has since moved past: every
  read of the series asks for its whole range, so a bar followed by a later one has been
  written again after its own close.
- ``find`` lists every recorded price that differs from that close, and ``record``
  appends them to ``price_corrections`` (migration 115), once each.

Nothing here changes a snapshot, a call or a price.
"""

from __future__ import annotations

import json

import db

# Two reads of one close differ in the last places of a float and nothing more. A
# hundredth of a percent is far above that and far below any intraday move worth the name.
TOLERANCE = 1e-4


def settled_close(conn, ticker: str, day: str) -> float | None:
    """The close of the session dated ``day``, or None where the daily series holds no
    bar for it or has not yet moved past it."""
    row = conn.execute(
        """SELECT p.close,
                  (SELECT MAX(substr(q.as_of, 1, 10)) FROM prices q
                    WHERE q.company_id = p.company_id AND q.interval = '1d') AS newest
             FROM prices p JOIN companies c ON c.id = p.company_id
            WHERE c.ticker = ? AND p.interval = '1d' AND substr(p.as_of, 1, 10) = ?
              AND p.close IS NOT NULL""", (ticker, (day or "")[:10])).fetchone()
    if row is None or row["newest"] is None or row["newest"] <= (day or "")[:10]:
        return None
    return row["close"]


def differs(recorded, settled) -> bool:
    if recorded is None or settled is None or not settled:
        return False
    return abs(recorded / settled - 1) > TOLERANCE


def _table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (name,)).fetchone() is not None


def find(conn) -> list[dict]:
    """Every recorded price that is not the settled close of the session it names:
    price snapshots, model calls and gate calls. A price whose session has not settled
    yet is left out, and found on a later pass."""
    out: list[dict] = []
    closes: dict = {}

    def close(ticker, day):
        key = (ticker, day)
        if key not in closes:
            closes[key] = settled_close(conn, ticker, day)
        return closes[key]

    def add(kind, ref_key, ticker, day, recorded):
        settled = close(ticker, day)
        if differs(recorded, settled):
            out.append({"kind": kind, "ref_key": ref_key, "ticker": ticker,
                        "price_date": day, "recorded": recorded, "settled": settled})

    for row in conn.execute(
            "SELECT entity_key, captured_at, payload FROM snapshots"
            " WHERE source = 'prices' AND entity_type = 'company' ORDER BY id"):
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            continue
        day, recorded = str(payload.get("as_of") or "")[:10], payload.get("close")
        if day and recorded is not None:
            add("snapshot", f"{row['entity_key']}|{row['captured_at']}",
                row["entity_key"], day, recorded)

    call_day: dict = {}
    if _table(conn, "model_calls"):
        for row in conn.execute(
                "SELECT as_of, ticker, price, price_date FROM model_calls ORDER BY id"):
            day = str(row["price_date"] or row["as_of"] or "")[:10]
            call_day[(row["ticker"], row["as_of"])] = day
            if day and row["price"] is not None:
                add("model_call", f"{row['ticker']}|{row['as_of']}", row["ticker"], day,
                    row["price"])
    if _table(conn, "gate_calls"):
        # A gate call carries the price of the company's call that day and no date of
        # its own, so it takes that call's price date.
        for row in conn.execute(
                "SELECT as_of, ticker, catalyst_id, asset_id, price FROM gate_calls"
                " ORDER BY id"):
            day = call_day.get((row["ticker"], row["as_of"]))
            if day and row["price"] is not None:
                add("gate_call",
                    f"{row['ticker']}|{row['as_of']}|{row['catalyst_id']}|{row['asset_id']}",
                    row["ticker"], day, row["price"])
    return out


def record(db_path=None) -> dict:
    """Append the corrections not yet on file. Idempotent: a corrected row is written
    once and never updated, so a second pass adds only what has settled since."""
    conn = db.get_connection(db_path)
    try:
        if not _table(conn, "price_corrections"):
            return {"skipped": "no price_corrections table"}
        found = find(conn)
        written = 0
        for row in found:
            cur = conn.execute(
                "INSERT OR IGNORE INTO price_corrections"
                " (kind, ref_key, ticker, price_date, recorded, settled)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row["kind"], row["ref_key"], row["ticker"], row["price_date"],
                 row["recorded"], row["settled"]))
            written += cur.rowcount == 1
        conn.commit()
        by_kind: dict = {}
        for row in found:
            by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
        return {"found": len(found), "written": written, "by_kind": by_kind,
                "days": len({r["price_date"] for r in found})}
    finally:
        conn.close()


def summary(db_path=None) -> dict:
    """What the ledger holds, for the track record: how many recorded prices were not
    closes, over how many sessions, and how far off."""
    conn = db.get_connection(db_path)
    try:
        if not _table(conn, "price_corrections"):
            return {"rows": 0}
        rows = conn.execute(
            "SELECT kind, price_date, recorded, settled FROM price_corrections").fetchall()
    finally:
        conn.close()
    gaps = sorted(abs(r["recorded"] / r["settled"] - 1) for r in rows if r["settled"])
    by_kind: dict = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {"rows": len(rows), "by_kind": by_kind,
            "sessions": len({r["price_date"] for r in rows}),
            "first": min((r["price_date"] for r in rows), default=None),
            "last": max((r["price_date"] for r in rows), default=None),
            "median_gap": gaps[len(gaps) // 2] if gaps else None,
            "largest_gap": gaps[-1] if gaps else None}
