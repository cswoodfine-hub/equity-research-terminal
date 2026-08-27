"""Foreign exchange, to USD, from the ECB daily reference rates.

The rest of this app never converts a currency, on purpose: mixing DKK and USD into
one total without a rate would be a number wrong in both. This module supplies the
rate, from a real free source (the ECB reference set), so the universe revenue-at-risk
view can show absolutes across reporting currencies. The discipline holds: a currency
with no stored rate returns None and is never converted, and every converted figure
travels with the date of the rate that made it.

The ECB set is EUR-based (units of a currency per one euro). USD per one unit of X is
``rate_USD_per_EUR / rate_X_per_EUR``, which gives USD per USD = 1 exactly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import db

ECB_NS = {"g": "http://www.gesmes.org/xml/2002-08-01",
          "e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def parse_ecb(xml_text: str) -> dict:
    """(as_of, {currency: USD-per-unit}) from the ECB daily XML.

    Pure. Raises ValueError if the document has no USD rate, since every quote here is
    USD and a set without it can convert nothing.
    """
    root = ET.fromstring(xml_text)
    cube = root.find(".//e:Cube/e:Cube[@time]", ECB_NS)
    if cube is None:
        raise ValueError("ECB document carries no dated cube")
    as_of = cube.get("time")
    per_eur = {"EUR": 1.0}
    for node in cube.findall("e:Cube", ECB_NS):
        currency, rate = node.get("currency"), node.get("rate")
        if currency and rate:
            per_eur[currency] = float(rate)
    if "USD" not in per_eur:
        raise ValueError("ECB document carries no USD rate")
    usd_per_eur = per_eur["USD"]
    return as_of, {cur: usd_per_eur / value for cur, value in per_eur.items()}


def store(db_path, as_of: str, usd_rates: dict) -> int:
    """Upsert USD-quoted rates for one reference date. Returns rows written."""
    conn = db.get_connection(db_path)
    try:
        written = 0
        for base, rate in usd_rates.items():
            conn.execute(
                """
                INSERT INTO fx_rates (base, quote, rate, as_of, source)
                VALUES (?, 'USD', ?, ?, 'ecb')
                ON CONFLICT(base, quote, as_of) DO UPDATE SET
                    rate = excluded.rate, fetched_at = datetime('now')
                """,
                (base, rate, as_of))
            written += 1
        conn.commit()
        return written
    finally:
        conn.close()


def latest_usd_rates(db_path=None) -> dict:
    """{currency: USD-per-unit} from the most recent stored reference date, plus the
    date under the key ``as_of``. Empty (bar as_of=None) when no rates are stored."""
    conn = db.get_connection(db_path)
    try:
        newest = conn.execute(
            "SELECT MAX(as_of) FROM fx_rates WHERE quote = 'USD'").fetchone()[0]
        if not newest:
            return {"as_of": None}
        rows = conn.execute(
            "SELECT base, rate FROM fx_rates WHERE quote = 'USD' AND as_of = ?",
            (newest,)).fetchall()
    finally:
        conn.close()
    out = {r["base"]: r["rate"] for r in rows}
    out["as_of"] = newest
    return out


def rates_on(db_path, on_date: str) -> dict:
    """The rate set published on or before ``on_date``, plus the date actually used.

    ``latest_usd_rates`` answers "what is a krone worth now", which is the right question
    for a current figure and the wrong one for a price paid in the past. A position
    entered in kroner and exited in kroner made what it made in kroner; converting both
    ends at today's rate rescales the two legs identically and reports the local return
    wearing a dollar sign, while converting each end at its own rate gives the number a
    dollar investor actually experienced.

    Returns {} when the history does not reach back that far. The reference set starts on
    2026-07-24, so a position older than that has no honest conversion and is told so
    rather than quietly given today's rate.
    """
    if not on_date:
        return {}
    conn = db.get_connection(db_path)
    try:
        newest = conn.execute(
            "SELECT MAX(as_of) FROM fx_rates WHERE quote = 'USD' AND as_of <= ?",
            (on_date[:10],)).fetchone()[0]
        if not newest:
            return {}
        rows = conn.execute(
            "SELECT base, rate FROM fx_rates WHERE quote = 'USD' AND as_of = ?",
            (newest,)).fetchall()
    finally:
        conn.close()
    out = {r["base"]: r["rate"] for r in rows}
    out["as_of"] = newest
    return out


def to_usd(value, currency, rates: dict) -> float | None:
    """Convert ``value`` in ``currency`` to USD using a rates dict from
    ``latest_usd_rates``. None when the value, currency, or rate is absent, so an
    unconvertible figure is never silently zeroed."""
    if value is None or not currency:
        return None
    rate = rates.get(currency)
    return value * rate if rate is not None else None
