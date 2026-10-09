"""The user's Trading 212 account valued every trading day since its first deposit.

Trading 212 gives no history of the account's value, so it is rebuilt: what was held each
day from the order fills (a fill of type FOP is a transfer in of shares, free of payment,
counted as money put in at the value Trading 212 booked), the cash each day from the
deposits, withdrawals, fills and dividends, and each instrument's daily close from Yahoo's
chart data converted to the account's currency at that day's rate.

An instrument's prices are found by listing: a London line is ``<root>.L`` and a Toronto
one ``<root>.TO``; a US line tries its own ticker, then the listings Yahoo returns for its
ISIN (Trading 212 keeps old tickers after a rename: AHAC is Humacyte, FVAC MP Materials). A
series is kept only when its currency is the instrument's and its last close sits within a
quarter of Trading 212's current price; one that fails is left out and named, never guessed,
and the day's value then counts that holding at nothing, which the payload says.

Read live and held in memory for an hour, never written anywhere: the holdings are the user's.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request

from fetchers import broker_t212

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
_UA = "Mozilla/5.0 (compatible; NovatalisResearch/0.1)"
_TIMEOUT_S = 20
PRICE_BAND = 0.25
_TTL_S = 3600
_memo: dict = {}


def _json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def closes(symbol: str, start: dt.date) -> tuple:
    """({date: close}, currency) for one Yahoo symbol from ``start``, or ({}, None)."""
    key = ("closes", symbol, start)
    if key in _memo and time.monotonic() - _memo[key][0] < _TTL_S:
        return _memo[key][1]
    p1 = int(dt.datetime.combine(start - dt.timedelta(days=7), dt.time()).timestamp())
    url = (CHART.format(symbol=urllib.parse.quote(symbol)) + "?"
           + urllib.parse.urlencode({"period1": p1, "period2": int(time.time()) + 86400,
                                     "interval": "1d"}))
    try:
        res = (_json(url).get("chart") or {}).get("result") or []
    except Exception:
        res = []
    out = ({}, None)
    if res:
        r = res[0]
        stamps = r.get("timestamp") or []
        cl = (((r.get("indicators") or {}).get("quote") or [{}])[0].get("close")) or []
        series = {dt.datetime.utcfromtimestamp(s).date().isoformat(): c
                  for s, c in zip(stamps, cl) if c is not None}
        out = (series, (r.get("meta") or {}).get("currency"))
    _memo[key] = (time.monotonic(), out)
    return out


def _norm_currency(cur: str | None) -> str | None:
    """Yahoo writes pence as GBp and Trading 212 as GBX: both pence."""
    return "GBX" if cur in ("GBp", "GBX") else cur


def _candidates(t212_ticker: str, isin: str | None) -> list:
    root = broker_t212.universe_ticker(t212_ticker)
    if t212_ticker.endswith("l_EQ"):
        return [root + ".L"]
    if "_CA_" in t212_ticker:
        return [root + ".TO"]
    out = [root]
    if isin:
        try:
            quotes = _json(SEARCH + "?" + urllib.parse.urlencode(
                {"q": isin, "quotesCount": 5, "newsCount": 0})).get("quotes") or []
            out += [q["symbol"] for q in quotes if q.get("symbol") and q["symbol"] not in out]
        except Exception:
            pass
    return out


def resolve(t212_ticker: str, isin: str | None, currency: str | None, price, start):
    """(symbol, {date: close}) for one instrument, or (None, {}) when no listing matches
    its currency and its current price."""
    for symbol in _candidates(t212_ticker, isin):
        series, cur = closes(symbol, start)
        if not series or _norm_currency(cur) != _norm_currency(currency):
            continue
        last = series[max(series)]
        if price and last and abs(last / price - 1) > PRICE_BAND:
            continue
        return symbol, series
    return None, {}


def _fx_to_account(currency: str, account: str, start) -> dict:
    """{date: account units per one unit of ``currency``}; pence are a hundredth of a pound."""
    if currency == account:
        return None
    if currency == "GBX" and account == "GBP":
        return 0.01
    series, _cur = closes(f"{account}{currency}=X", start)      # e.g. GBPUSD=X: USD per GBP
    return {d: 1 / v for d, v in series.items() if v}


def _on(series, day: str):
    """The last value on or before ``day``."""
    if not isinstance(series, dict):
        return series
    earlier = [d for d in series if d <= day]
    return series[max(earlier)] if earlier else None


INDEX_FLOOR = 100.0          # the index starts once the account holds this much


def _indices(out: dict, sp: dict, usd_on, start) -> dict:
    """The account as a unit price, 100 on the first day it held INDEX_FLOOR or more: each
    day's return is the value over the day before's plus the money put in that day, so
    deposits and transfers move the value but never the price. The S&P 500 and PPH are
    rebased to 100 on the same day, in the account's currency."""
    dates, value, contrib = out["dates"], out["value"], out["contributions"]
    pph, _cur = closes("PPH", start)
    first = next((i for i, v in enumerate(value) if v >= INDEX_FLOOR), None)
    index, sp_ix, pph_ix = [None] * len(dates), [None] * len(dates), [None] * len(dates)
    if first is None:
        return {"index": index, "sp500_index": sp_ix, "pph_index": pph_ix, "index_start": None}
    index[first] = 100.0
    for i in range(first + 1, len(dates)):
        base = value[i - 1] + (contrib[i] - contrib[i - 1])
        index[i] = index[i - 1] * (value[i] / base) if base > 0 else index[i - 1]

    def rebased(series, day0):
        b = (_on(series, day0) or 0) * (usd_on(day0) or 0)
        return [(round(100 * _on(series, d) * usd_on(d) / b, 3)
                 if i >= first and b and _on(series, d) and usd_on(d) else None)
                for i, d in enumerate(dates)]

    return {"index": [round(v, 3) if v is not None else None for v in index],
            "sp500_index": rebased(sp, dates[first]), "pph_index": rebased(pph, dates[first]),
            "index_start": dates[first]}


def build(today: dt.date | None = None) -> dict:
    """{"ok", "currency", "dates", "value", "contributions", "sp500", "left_out", "end"}."""
    today = today or dt.date.today()
    summary = broker_t212.summary()
    orders = broker_t212.history("orders")
    tx = broker_t212.history("transactions")
    dividends = broker_t212.history("dividends")
    held = broker_t212.positions()
    if not (summary.get("ok") and orders.get("ok") and tx.get("ok")):
        return {"ok": False, "reason": "Trading 212 did not answer"}
    account = summary.get("currency") or "GBP"
    current = {p["t212_ticker"]: p for p in held.get("rows") or []}

    # Events: (date, cash change, contribution change, {ticker: share change}).
    events = []
    for t in tx.get("rows") or []:
        day, amount = str(t.get("dateTime"))[:10], abs(t.get("amount") or 0)
        kind = (t.get("type") or "").upper()
        if kind == "DEPOSIT":
            events.append((day, amount, amount, {}))
        elif kind in ("WITHDRAW", "WITHDRAWAL"):
            events.append((day, -amount, -amount, {}))
    instruments = {}
    for it in orders.get("rows") or []:
        order, fill = it.get("order") or {}, it.get("fill") or {}
        if not fill:
            continue
        inst = order.get("instrument") or {}
        ticker = order.get("ticker") or inst.get("ticker")
        instruments.setdefault(ticker, {"isin": inst.get("isin"),
                                        "currency": inst.get("currency"),
                                        "name": inst.get("name")})
        day = str(fill.get("filledAt"))[:10]
        qty = abs(fill.get("quantity") or 0)
        net = abs((fill.get("walletImpact") or {}).get("netValue") or 0)
        buy = (order.get("side") or "").upper() == "BUY"
        if fill.get("type") == "FOP":                     # shares transferred in
            events.append((day, 0.0, net, {ticker: qty if buy else -qty}))
        else:
            events.append((day, -net if buy else net, 0.0, {ticker: qty if buy else -qty}))
    for d in dividends.get("rows") or []:
        events.append((str(d.get("paidOn"))[:10], d.get("amount") or 0, 0.0, {}))
    if not events:
        return {"ok": False, "reason": "no history on the account"}
    events.sort(key=lambda e: e[0])
    start = dt.date.fromisoformat(events[0][0])

    prices, left_out = {}, []
    for ticker, meta in instruments.items():
        now = current.get(ticker, {})
        symbol, series = resolve(ticker, meta["isin"], meta["currency"],
                                 now.get("current_price"), start)
        if symbol is None:
            if ticker in current:
                left_out.append(meta.get("name") or ticker)
            continue
        prices[ticker] = (series, _fx_to_account(_norm_currency(meta["currency"]), account,
                                                 start))
    usd = _fx_to_account("USD", account, start)
    usd_on = (lambda day: 1.0) if usd is None else (lambda day: _on(usd, day))
    sp, _cur = closes("^GSPC", start)

    days = sorted({d for series, _f in prices.values() for d in series if d >= start.isoformat()}
                  | {e[0] for e in events})
    days = [d for d in days if d <= today.isoformat()]
    cash = contrib = units_sp = 0.0
    shares: dict = {}
    out = {"dates": [], "value": [], "contributions": [], "sp500": []}
    i = 0
    for day in days:
        while i < len(events) and events[i][0] <= day:
            _d, dc, dk, ds = events[i]
            cash += dc
            contrib += dk
            for t, q in ds.items():
                shares[t] = shares.get(t, 0.0) + q
            if dk:                          # money put in or taken out buys or sells the index
                spx, rate = _on(sp, _d), usd_on(_d)
                if spx and rate:
                    units_sp += dk / rate / spx
            i += 1
        value = cash
        for t, q in shares.items():
            if abs(q) < 1e-9 or t not in prices:
                continue
            series, fx_ = prices[t]
            close, rate = _on(series, day), (_on(fx_, day) if fx_ is not None else 1.0)
            if close is not None and rate is not None:
                value += q * close * rate
        spx, rate = _on(sp, day), usd_on(day)
        out["dates"].append(day)
        out["value"].append(round(value, 2))
        out["contributions"].append(round(contrib, 2))
        out["sp500"].append(round(units_sp * spx * rate, 2) if spx and rate else None)
    out.update(_indices(out, sp, usd_on, start))
    actual = summary.get("total")
    return {"ok": True, "currency": account, **out, "left_out": left_out,
            "end": {"rebuilt": out["value"][-1] if out["value"] else None, "actual": actual},
            "source": "rebuilt from your Trading 212 fills, transfers, deposits and "
                      "dividends, priced at Yahoo daily closes"}
