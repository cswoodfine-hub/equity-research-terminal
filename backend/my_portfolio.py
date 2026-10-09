"""The user's own holdings beside the model's view of each (fetchers/broker_t212.py).

Read live on every call and never cached or stored: the positions are the user's, so they
stay out of the response cache's disk copy and out of the history export that reaches git.

``mine`` lists the positions. Each carries its return in the account's currency since it was
first bought, the S&P 500's over the same days converted the same way (so the difference is
the pick, not the market or the currency), the currency effect Trading 212 reports, and for
a company the book covers: the model's latest recorded call (call_log), the next dated
catalyst, every priced gate within 24 months with what a pass adds and a miss takes in the
account's currency for this holding, and what changed on it in the last 7 days.

The pounds at stake scale the model's swing a share by the holding's value over the share
price the model was valued against, so a London holding of a company valued per US-listed
share needs no ratio between the two lines: value is value.

``performance`` answers how the account has done: the money-weighted return over the
period (never annualised) from the deposits and withdrawals to today's value, beside what the same cash would have made in the
S&P 500 and in PPH, bought and sold on the same days at that day's exchange rate, and the
gain split into realised, unrealised price, currency and dividends.

The model's view beside a holding is the model's, not a recommendation to buy or sell.
"""

from __future__ import annotations

import datetime as dt
import re

import db
import fx
from fetchers import broker_t212

_BANNED = re.compile(r"\b(?:additionally|highlight\w*|underscor\w*|pivotal|showcas\w*|"
                     r"testament)\b", re.I)
GATE_DAYS = 730
FLAG_DAYS = 7
BENCHMARKS = {"^GSPC": "S&P 500", "PPH": "PPH"}


def _close(conn, symbol: str, day: str):
    row = conn.execute(
        """SELECT close FROM benchmark_prices WHERE symbol = ? AND close IS NOT NULL
             AND substr(as_of, 1, 10) <= ? ORDER BY as_of DESC LIMIT 1""",
        (symbol, day)).fetchone()
    return row["close"] if row else None


# The Federal Reserve's noon buying rates, keyless, for days before the book's ECB set
# begins (2026-07-24): US dollars per pound and per euro.
FRED_USD_PER = {"GBP": "DEXUSUK", "EUR": "DEXUSEU"}
_fred_cache: dict = {}


def _fred_rate(currency: str, day: str):
    series = FRED_USD_PER.get(currency)
    if not series:
        return None
    if series not in _fred_cache:
        import urllib.request
        rows = {}
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
            with urllib.request.urlopen(url, timeout=20) as resp:
                for line in resp.read().decode("utf-8").splitlines()[1:]:
                    d, _sep, v = line.partition(",")
                    try:
                        rows[d] = float(v)
                    except ValueError:
                        continue                  # "." marks a holiday
        except Exception:
            return None
        _fred_cache[series] = rows
    rows = _fred_cache[series]
    earlier = [d for d in rows if d <= day]
    return rows[max(earlier)] if earlier else None


def _usd_per(db_path, currency: str, day: str):
    """US dollars per unit of ``currency`` on ``day``: the ECB reference rate the book holds,
    else the Federal Reserve's rate for a day before that set begins."""
    if currency == "USD":
        return 1.0
    try:
        rate = (fx.rates_on(db_path, day) or {}).get(currency)
    except Exception:
        rate = None
    return rate if rate else _fred_rate(currency, day)


def _bench_return(conn, db_path, symbol, currency, start, end):
    """The benchmark's price return from ``start`` to ``end`` in ``currency``."""
    c0, c1 = _close(conn, symbol, start), _close(conn, symbol, end)
    f0, f1 = _usd_per(db_path, currency, start), _usd_per(db_path, currency, end)
    if not (c0 and c1 and f0 and f1):
        return None
    return (c1 / c0) * (f0 / f1) - 1


def _gates(conn, ticker: str, value, today: dt.date) -> list:
    """The latest day's priced gates within GATE_DAYS for one holding: odds, and what a pass
    adds and a miss takes for this holding, in the account's currency."""
    call = conn.execute("SELECT as_of, price FROM model_calls WHERE ticker = ?"
                        " ORDER BY as_of DESC LIMIT 1", (ticker,)).fetchone()
    if not call or not call["price"] or not value:
        return []
    end = (today + dt.timedelta(days=GATE_DAYS)).isoformat()
    out = []
    for g in conn.execute(
            """SELECT asset_name, gate_label, expected_date, p_gate, per_share_now,
                      per_share_success, per_share_failure FROM gate_calls
                WHERE ticker = ? AND as_of = ? AND per_share_now IS NOT NULL
                ORDER BY expected_date""", (ticker, call["as_of"])):
        day = str(g["expected_date"] or "")
        if day and day[:10] > end:
            continue
        scale = value / call["price"]
        up = (g["per_share_success"] - g["per_share_now"]) if g["per_share_success"] is not None \
            else None
        down = (g["per_share_failure"] - g["per_share_now"]) if g["per_share_failure"] is not None \
            else None
        out.append({"asset": g["asset_name"], "gate": g["gate_label"], "date": day,
                    "odds": g["p_gate"],
                    "pass_pct": up / call["price"] if up is not None else None,
                    "miss_pct": down / call["price"] if down is not None else None,
                    "pass_adds": (g["per_share_success"] - g["per_share_now"]) * scale
                    if g["per_share_success"] is not None else None,
                    "miss_takes": (g["per_share_failure"] - g["per_share_now"]) * scale
                    if g["per_share_failure"] is not None else None})
    return out


def _flags(db_path, tickers: set) -> dict:
    """What changed on each covered holding in the last FLAG_DAYS: {ticker: {"count",
    "high": [up to three headlines the feed rates high]}}. The rest are counted, not
    listed: a week of registry edits is not news."""
    if not tickers:
        return {}
    try:
        import whatchanged
        feed = whatchanged.build_feed(db_path, days=FLAG_DAYS)
    except Exception:
        return {}
    out: dict = {}
    for item in feed:
        t = (item.get("ticker") or "").upper()
        if t not in tickers or item.get("kind") != "change":
            continue
        entry = out.setdefault(t, {"count": 0, "high": []})
        entry["count"] += 1
        head = re.sub(rf"^{re.escape(t)}\s+", "", str(item.get("headline")
                                                     or item.get("change_type") or ""))
        # A source headline is quoted as published and cannot be reworded, so one in a
        # word the house style bars is counted but not shown.
        if (item.get("significance") == "high" and len(entry["high"]) < 3
                and not _BANNED.search(head)):
            entry["high"].append(head)
    return out


def mine(db_path=None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    held = broker_t212.positions()
    if not held.get("ok"):
        return {"ok": False, "status": held.get("status"), "reason": held.get("reason")
                or "Trading 212 did not answer", "rows": []}
    currency = held.get("currency") or "GBP"
    conn = db.get_connection(db_path)
    try:
        covered = {r["ticker"] for r in conn.execute("SELECT ticker FROM companies")}
        flags = _flags(db_path, {p["ticker"] for p in held["rows"]} & covered)
        rows = []
        for p in held["rows"]:
            row = {**p, "covered": p["ticker"] in covered, "model": None,
                   "previous_rating": None, "next_catalyst": None, "gates": [],
                   "flags": {"count": 0, "high": []}}
            cost, value = p.get("cost"), p.get("value")
            row["return"] = (value / cost - 1) if cost and value else None
            opened = str(p.get("opened") or "")[:10]
            row["market"] = (_bench_return(conn, db_path, "^GSPC", currency, opened,
                                           today.isoformat()) if opened else None)
            row["pick"] = (row["return"] - row["market"]
                           if row["return"] is not None and row["market"] is not None
                           else None)
            if row["covered"]:
                calls = conn.execute(
                    """SELECT as_of, price, fair_value, upside_12m, rating, target_mid
                         FROM model_calls WHERE ticker = ? ORDER BY as_of DESC LIMIT 2""",
                    (p["ticker"],)).fetchall()
                row["model"] = dict(calls[0]) if calls else None
                row["previous_rating"] = calls[1]["rating"] if len(calls) > 1 else None
                cat = conn.execute(
                    """SELECT c.expected_date, c.catalyst_type,
                              COALESCE(a.brand_name, a.generic_name) AS asset, c.title
                         FROM catalysts c JOIN companies co ON co.id = c.company_id
                         LEFT JOIN assets a ON a.id = c.asset_id
                        WHERE co.ticker = ? AND c.status = 'pending'
                          AND c.expected_date >= ?
                        ORDER BY c.expected_date LIMIT 1""",
                    (p["ticker"], today.isoformat())).fetchone()
                row["next_catalyst"] = dict(cat) if cat else None
                row["gates"] = _gates(conn, p["ticker"], value, today)
                row["flags"] = flags.get(p["ticker"], {"count": 0, "high": []})
            rows.append(row)
    finally:
        conn.close()
    rows.sort(key=lambda r: -(r.get("value") or 0))
    return {"ok": True, "currency": currency, "rows": rows,
            "covered": sum(1 for r in rows if r["covered"]), "positions": len(rows),
            "source": "your Trading 212 account, read only, live"}


# --- performance ---------------------------------------------------------------------
def xirr(flows: list) -> float | None:
    """The annual rate that sets the flows' present value to nil: [(date, amount)], money
    in negative and out positive. Bisection, so it cannot wander off."""
    if len(flows) < 2 or not any(a < 0 for _d, a in flows) or not any(a > 0 for _d, a in flows):
        return None
    t0 = min(d for d, _a in flows)

    def npv(r):
        return sum(a / (1 + r) ** ((d - t0).days / 365.25) for d, a in flows)

    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _period(rate, flows, today):
    """A money-weighted annual rate as the return over the period the flows span, so a
    few months are never annualised into a figure nobody earned."""
    if rate is None or not flows:
        return None
    return (1 + rate) ** ((today - flows[0][0]).days / 365.25) - 1


def _cash_flows(transactions: list) -> list:
    """(date, amount) from the account's deposits and withdrawals, the investor's side:
    money in is negative, money out positive."""
    out = []
    for t in transactions:
        kind = (t.get("type") or "").upper()
        amount = abs(t.get("amount") or 0)
        day = dt.date.fromisoformat(str(t.get("dateTime"))[:10])
        if kind == "DEPOSIT":
            out.append((day, -amount))
        elif kind in ("WITHDRAW", "WITHDRAWAL"):
            out.append((day, amount))
    return sorted(out)


def _transfers_in(orders: list) -> list:
    """(date, amount) for shares transferred into the account: a fill of type FOP, free of
    payment, is money put in at the value Trading 212 booked, never a gain (2026-10-09: five
    holdings moved in on 31 July, 573.01, read at first as cash the API did not itemise)."""
    out = []
    for it in orders:
        fill, order = it.get("fill") or {}, it.get("order") or {}
        if fill.get("type") != "FOP":
            continue
        value = abs((fill.get("walletImpact") or {}).get("netValue") or 0)
        sign = -1 if (order.get("side") or "").upper() == "BUY" else 1
        out.append((dt.date.fromisoformat(str(fill.get("filledAt"))[:10]), sign * value))
    return out


def _replicate(conn, db_path, symbol, currency, flows, today):
    """The same deposits and withdrawals bought and sold in ``symbol`` on the same days at
    that day's exchange rate: (value today in ``currency``, its money-weighted return)."""
    units = 0.0
    for day, amount in flows:
        close, usd = _close(conn, symbol, day.isoformat()), _usd_per(db_path, currency,
                                                                      day.isoformat())
        if not (close and usd):
            return None, None
        units += (-amount) * usd / close
    close, usd = _close(conn, symbol, today.isoformat()), _usd_per(db_path, currency,
                                                                   today.isoformat())
    if not (close and usd):
        return None, None
    value = units * close / usd
    return value, xirr(flows + [(today, value)])


def performance(db_path=None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    summary = broker_t212.summary()
    if not summary.get("ok"):
        return {"ok": False, "reason": summary.get("reason") or "Trading 212 did not answer"}
    tx = broker_t212.history("transactions")
    dividends = broker_t212.history("dividends")
    orders = broker_t212.history("orders")
    held = broker_t212.positions()
    currency = summary.get("currency") or "GBP"
    flows = sorted(_cash_flows(tx.get("rows") or []) + _transfers_in(orders.get("rows") or []))
    total = summary.get("total") or 0.0
    net_in = -sum(a for _d, a in flows)
    paid = sum((d.get("amount") or 0) for d in dividends.get("rows") or [])
    fx_effect = sum((p.get("fx_effect") or 0) for p in held.get("rows") or [])
    unrealised = summary.get("unrealised") or 0.0
    out = {"ok": True, "currency": currency, "since": flows[0][0].isoformat() if flows else None,
           "total": total, "cash": summary.get("cash"), "invested": summary.get("invested"),
           "net_deposits": net_in, "gain": total - net_in,
           "return": _period(xirr(flows + [(today, total)]), flows, today) if flows else None,
           "split": {"realised": summary.get("realised"),
                     "unrealised_price": unrealised - fx_effect,
                     "unrealised_currency": fx_effect, "dividends": paid},
           "benchmarks": [],
           "history_complete": bool(tx.get("ok") and dividends.get("ok") and orders.get("ok"))}
    # Cash the trade, transaction and dividend lists do not account for (interest on cash,
    # promotions): said as a figure, never given a cause the API does not state.
    out["split"]["not_itemised"] = out["gain"] - sum(v or 0 for v in out["split"].values())
    conn = db.get_connection(db_path)
    try:
        for symbol, label in BENCHMARKS.items():
            value, rate = _replicate(conn, db_path, symbol, currency, flows, today)
            out["benchmarks"].append({"symbol": symbol, "label": label, "value": value,
                                      "gain": (value - net_in) if value is not None else None,
                                      "return": _period(rate, flows, today)})
    finally:
        conn.close()
    return out
