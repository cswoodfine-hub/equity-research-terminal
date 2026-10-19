"""Each priced readout's move as the model states it, beside the move the options price.

**The model's move.** catalyst_stakes prices a readout on legs: the asset's probability if
it passes and if it misses, at the readout's own odds q = (now - miss) / (pass - miss).
Where a miss leaves other Phase 3s open the model holds the asset (``held``) rather than
taking it to nil, and that held probability is the miss leg here too. As a share price
move the readout is a jump of up = k (pass - now) with probability q and down =
k (miss - now) otherwise, k the value per share of a point of probability; its standard
deviation is |up - down| sqrt(q (1 - q)). Near q = 1/2 that tests the swing's size far
more than the odds.

**The options' move.** An expiry after an event carries its variance and one before it
does not. The variance the window between two expiries adds beyond diffusion is

    iv2^2 T2 - iv1^2 T1 - base (T2 - T1) - the results dates inside it

with ``base`` the diffusive rate: the earlier expiry's total variance less the results it
already holds, per year. Running the earlier volatility on instead counts those results
again over the gap; on Novo's January to March 2027 window that alone was worth a 6.5%
move.

**What it cannot see, said rather than guessed.**

- Results. The next results date is Nasdaq's (marked expected). Its own window prices its
  move, which stands in for every later quarter's, projected 91 days on at a time. A
  full-year results date (January to mid-March) carries guidance and moved Novo 14.6% on
  3 February 2026 against 0.4% to 6% in other quarters, so its size is held uncertain by
  half. A readout in the same window as the next results is not separated from them.
- Registry dates. A readout dated from the registry is its primary completion date, and
  the topline follows: the 8 Phase 3 toplines the book can match came 0 to 127 days later,
  median 48. Such a readout is read over the window from that date to 120 days on.
- Long dates. Past six months the surface does not show even the results dates it must
  hold (12 of 25 such windows read negative in a check across 20 chains), so those windows
  are not read. Nor is any window that fails to show its own results.
- Noise. The quotes' error (half the spread over vega), the baseline's (the gap between
  the stripped and the raw rate) and the results taken out each add an error, in
  quadrature. The verdict uses a band two of those either side of the market's reading.
- No listed options. Roche and Bayer trade over the counter in the US and Cboe lists no
  options on them.

Source: Cboe's delayed quotes (``cdn-api.cboe.com/api/global/delayed_quotes/options``),
keyless, 15 minutes delayed, every listed strike with its implied volatility and greeks;
its volatilities are annualised on calendar days, as here. Nothing is stored.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.request

import db

CHAIN_URL = "https://cdn-api.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
EARNINGS_URL = "https://api.nasdaq.com/api/analyst/{symbol}/earnings-date"
REGISTRY_URL = "https://clinicaltrials.gov/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (equity research terminal)",
            "Accept": "application/json"}
TIMEOUT_S = 30
PAUSE_S = 1.0
CLOSE = dt.time(16, 0)              # an expiry settles on the close, New York time
QUARTER_DAYS = 91                   # a results date projected on from the next one
RESULTS_SLACK_DAYS = 10             # how far a projected results date can stray
ANNUAL_SIZE_ERROR = 0.5             # a full-year results move, uncertain by half
READOUT_LAG_DAYS = 120              # a registry completion date to its topline
MAX_BEFORE_YEARS = 0.5              # past this the surface does not show results
BAND = 2.0                          # the verdict's band, in errors either side
_OPTION = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
_ANNOUNCED = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")


# --- reading the sources ---------------------------------------------------------------
def _get(url: str) -> str:
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_chain(symbol: str, get=None) -> dict | None:
    """Cboe's delayed chain for a US symbol, or None where it lists none (it answers 403
    for an over-the-counter ADR)."""
    get = get or _get
    try:
        return json.loads(get(CHAIN_URL.format(symbol=symbol)))
    except urllib.error.HTTPError as err:
        if err.code in (403, 404):
            return None
        raise


def fetch_earnings(symbol: str, get=None) -> dict | None:
    get = get or _get
    try:
        return json.loads(get(EARNINGS_URL.format(symbol=symbol)))
    except (urllib.error.HTTPError, ValueError):
        return None


def parse_earnings(payload: dict | None) -> dict | None:
    """The next results date Nasdaq announces, and whether it is marked expected."""
    data = (payload or {}).get("data") or {}
    text = data.get("announcement") or ""
    found = _ANNOUNCED.search(text)
    if not found:
        return None
    day = dt.datetime.strptime(" ".join(found.groups()), "%b %d %Y").date()
    return {"date": day, "expected": "*" in text, "text": text.strip()}


def _atm(strikes: dict, spot: float) -> dict | None:
    """The at-the-money volatility, interpolated in strike between the quoted strikes
    either side of the price, each strike the mean of its call and put. Its error is the
    median half spread over vega, shrunk by the number of quotes averaged."""
    below = [k for k in strikes if k <= spot]
    above = [k for k in strikes if k >= spot]
    if not below or not above:
        return None
    lo, hi = max(below), min(above)

    def iv_at(k):
        quotes = list(strikes[k].values())
        return sum(q["iv"] for q in quotes) / len(quotes)
    weight = 0.0 if hi == lo else (spot - lo) / (hi - lo)
    iv = iv_at(lo) + weight * (iv_at(hi) - iv_at(lo))
    used = list(strikes[lo].values()) + (list(strikes[hi].values()) if hi != lo else [])
    spreads = [(q["ask"] - q["bid"]) / 2.0 / (q["vega"] * 100.0)
               for q in used if (q.get("vega") or 0) > 0]
    error = statistics.median(spreads) / math.sqrt(len(spreads)) if spreads else None
    return {"iv": iv, "iv_error": error, "quotes": len(used), "strikes": (lo, hi)}


def parse_chain(payload: dict | None, symbol: str) -> dict | None:
    """Every expiry's at-the-money volatility and years to expiry, from the quote time.
    Only two-sided quotes with a volatility count, and only the symbol's own root: an
    adjusted series after a corporate action carries a different deliverable. An expiry on
    the quote's own day has settled, whatever its last quote says."""
    data = (payload or {}).get("data") or {}
    spot = data.get("current_price") or data.get("close")
    stamp = data.get("last_trade_time")
    if not spot or not stamp:
        return None
    as_of = dt.datetime.fromisoformat(stamp)
    by_expiry: dict = {}
    for quote in data.get("options") or []:
        found = _OPTION.match(quote.get("option") or "")
        if not found or found.group(1) != symbol:
            continue
        if min(quote.get("bid") or 0, quote.get("ask") or 0, quote.get("iv") or 0) <= 0:
            continue
        expiry = dt.datetime.strptime(found.group(2), "%y%m%d").date()
        if expiry <= as_of.date():
            continue
        strike = int(found.group(4)) / 1000.0
        by_expiry.setdefault(expiry, {}).setdefault(strike, {})[found.group(3)] = quote
    expiries = []
    for expiry in sorted(by_expiry):
        years = (dt.datetime.combine(expiry, CLOSE) - as_of).total_seconds() / (365 * 86400)
        atm = _atm(by_expiry[expiry], spot)
        if atm:
            expiries.append({"expiry": expiry, "t": years, **atm})
    return {"symbol": symbol, "spot": spot, "as_of": as_of, "iv30": data.get("iv30"),
            "expiries": expiries}


# --- results ---------------------------------------------------------------------------
def window(expiries: list, start: dt.date, end: dt.date) -> tuple:
    """(the last expiry before ``start``, the first on or after ``end``): the pair whose
    difference holds an event dated between them. Either is None past the chain."""
    before = [e for e in expiries if e["expiry"] < start]
    after = [e for e in expiries if e["expiry"] >= end]
    return (before[-1] if before else None), (after[0] if after else None)


def _quote_error(before: dict, after: dict) -> float:
    """The variance error of iv2^2 T2 - iv1^2 T1 - base (T2 - T1) from the quotes: each
    expiry's volatility error times 2 iv T2, the two independent."""
    return 2.0 * after["t"] * math.hypot(after["iv"] * (after["iv_error"] or 0.0),
                                         before["iv"] * (before["iv_error"] or 0.0))


def projected_results(results: dict | None, until: dt.date) -> list:
    """The next results date and those projected a quarter on at a time, to ``until``,
    each marked full-year (January to mid-March) or not."""
    if not results:
        return []
    out, k = [], 0
    while True:
        day = results["date"] + dt.timedelta(days=QUARTER_DAYS * k)
        if day > until + dt.timedelta(days=RESULTS_SLACK_DAYS):
            return out
        out.append({"date": day, "next": k == 0,
                    "annual": (day.month, day.day) <= (3, 15)})
        k += 1


def next_results(chain: dict, results: dict | None) -> dict | None:
    """The variance the options price for the next results, from the window holding them
    with the earlier expiry's volatility as the base, and its error. None where it cannot
    be read: before the first expiry, past the chain, or no larger than its own error."""
    if not results:
        return None
    before, after = window(chain["expiries"], results["date"], results["date"])
    if before is None or after is None:
        return None
    variance = after["t"] * (after["iv"] ** 2 - before["iv"] ** 2)
    error = _quote_error(before, after)
    if variance <= error:
        return None
    return {"variance": variance, "error": error}


def _held_results(dates: list, lo: dt.date, hi: dt.date) -> dict:
    """The results dates inside (lo, hi]: sure where the slack keeps them inside, possible
    where it straddles an edge."""
    slack = dt.timedelta(days=RESULTS_SLACK_DAYS)
    sure, possible = [], []
    for r in dates:
        if lo < r["date"] <= hi and (r["next"] or (lo + slack < r["date"] <= hi - slack)):
            sure.append(r)
        elif lo - slack < r["date"] <= hi + slack:
            possible.append(r)
    return {"sure": sure, "possible": possible}


def _results_error(held: list, results: dict, scale: float = 1.0) -> float:
    """The variance error of taking ``held`` results out at the next results' size."""
    terms = []
    for r in held:
        terms.append(results["error"] * scale)
        if r["annual"]:
            terms.append(ANNUAL_SIZE_ERROR * results["variance"] * scale)
    return math.sqrt(sum(t * t for t in terms))


def priced_variance(before: dict, after: dict, dates: list | None = None,
                    results: dict | None = None, as_of: dt.date | None = None) -> dict:
    """The window's event variance beyond diffusion and its results, its error, and how
    it was reached. ``why`` is set where the window cannot be read."""
    dates = dates or []
    lo, hi = before["expiry"], after["expiry"]
    held = _held_results(dates, lo, hi)
    earlier = _held_results(dates, as_of or dt.date.min, lo)["sure"] if dates else []
    total = after["iv"] ** 2 * after["t"] - before["iv"] ** 2 * before["t"]
    gap = after["t"] - before["t"]
    out = {"held_results": len(held["sure"]), "edge_results": len(held["possible"]),
           "why": None}
    if held["sure"] and any(r["next"] for r in held["sure"]):
        out["why"] = "the window also holds the next results, which cannot be separated"
    if (held["sure"] or earlier) and results is None:
        out["why"] = "the window's results cannot be sized: the next results could not be read"
    if out["why"]:
        return {**out, "variance": None, "error": None}
    size = results["variance"] if results else 0.0
    base = max(before["iv"] ** 2 - len(earlier) * size / before["t"], 0.0)
    raw_base = before["iv"] ** 2
    variance = total - base * gap - len(held["sure"]) * size
    errors = [_quote_error(before, after), gap * abs(raw_base - base)]
    if results:
        errors.append(_results_error(held["sure"], results))
        errors.append(_results_error(earlier, results, gap / before["t"]))
    error = math.sqrt(sum(e * e for e in errors))
    if before["t"] > MAX_BEFORE_YEARS:
        out["why"] = ("past six months the options surface does not show even the results "
                      "dates it must hold, so the window is not read")
    elif held["sure"] and total - base * gap < len(held["sure"]) * size - BAND * error:
        out["why"] = "the window does not show the results it holds, so it is not read"
    return {**out, "variance": variance, "error": error, "base": math.sqrt(base),
            "raw_base": math.sqrt(raw_base)}


# --- one company -----------------------------------------------------------------------
def _span(row: dict) -> tuple:
    """The days a catalyst can fall on: a month for a month, a half for a half, a registry
    completion date to its topline, else the day itself."""
    text, confidence = row["expected_date"], row.get("date_confidence")
    if len(text) == 7 or confidence == "month":
        first = dt.date.fromisoformat(text[:7] + "-01")
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return first, nxt - dt.timedelta(days=1)
    day = dt.date.fromisoformat(text[:10])
    if confidence == "half":
        return (day.replace(month=1, day=1) if day.month <= 6
                else day.replace(month=7, day=1)), day
    if confidence == "estimated" and (row.get("source_url") or "").startswith(REGISTRY_URL):
        return day, day + dt.timedelta(days=READOUT_LAG_DAYS)
    return day, day


def legs(row: dict, spot: float) -> dict | None:
    """The readout's own odds and its two legs as a share of the price. None where the
    row carries no legs to read."""
    now, win = row.get("pos_now"), row.get("pos_success")
    lose, swing = row.get("pos_failure"), row.get("per_share")
    if None in (now, win, lose, swing) or win <= lose or not spot:
        return None
    held = (row.get("held") or {}).get("pos")
    miss = held if held is not None else lose
    per_point = swing / spot / (win - lose)
    q = min(max((now - lose) / (win - lose), 0.0), 1.0)
    up, down = per_point * (win - now), per_point * (miss - now)
    return {"q": q, "up": up, "down": down, "held": held is not None,
            "sd": abs(up - down) * math.sqrt(q * (1.0 - q))}


def _verdict(model_sd: float, variance: float, error: float, label: str):
    """Where the model's move sits against the band two errors either side of the
    options' reading."""
    band = BAND * error
    lo = math.sqrt(max(variance - band, 0.0))
    hi = math.sqrt(max(variance + band, 0.0))
    if model_sd * model_sd < band:
        said = f"{label}, below the {math.sqrt(band):.1%} the options can resolve"
        if lo > 0:
            said += f"; the options price {lo:.1%} to {hi:.1%} in the window"
        return "unresolved", said, lo, hi
    priced = f"the options price {lo:.1%} to {hi:.1%}" if hi > 0 else "the options price nothing"
    if model_sd > hi:
        return "smaller", f"{label}; {priced}", lo, hi
    if model_sd < lo:
        return "larger", f"{label}; {priced}", lo, hi
    return "in_line", f"{label}; {priced}", lo, hi


def compare(chain: dict | None, results: dict | None, stakes: list) -> dict:
    """Every priced readout's move beside the options' move for its window."""
    if chain is None:
        return {"ok": False, "reason": "no listed options on Cboe for the US listing"}
    spot, expiries = chain["spot"], chain["expiries"]
    measured = next_results(chain, results)
    last = expiries[-1]["expiry"] if expiries else chain["as_of"].date()
    dates = projected_results(results, last)
    placed, out = [], []
    for row in stakes:
        got = legs(row, spot) if row.get("expected_date") else None
        if got is None:
            out.append({"catalyst_id": row.get("id"), "asset": row.get("asset_name"),
                        "date": row.get("expected_date"), "verdict": "unread",
                        "why": "no date or no legs on file"})
            continue
        start, end = _span(row)
        placed.append((row, got, start, end, window(expiries, start, end)))
    for row, got, start, end, (before, after) in placed:
        base = {"catalyst_id": row.get("id"), "asset": row.get("asset_name"),
                "kind": row.get("catalyst_type"), "date": row["expected_date"],
                "date_confidence": row.get("date_confidence"),
                "span": [start.isoformat(), end.isoformat()], "q": got["q"],
                "up_pct": got["up"], "down_pct": got["down"], "held": got["held"],
                "model_sd": got["sd"]}
        if before is None or after is None:
            out.append({**base, "verdict": "unread",
                        "why": ("dated past the last listed expiry" if after is None
                                else "dated before the first listed expiry")})
            continue
        sharing = [(r, g) for r, g, s, e, _ in placed
                   if before["expiry"] < s and e <= after["expiry"]]
        window_var = sum(g["sd"] ** 2 for _, g in sharing) or got["sd"] ** 2
        driver = max(sharing, key=lambda rg: rg[1]["sd"])[0] if sharing else row
        priced = priced_variance(before, after, dates, measured, chain["as_of"].date())
        detail = {"window": [before["expiry"].isoformat(), after["expiry"].isoformat()],
                  "iv_before": before["iv"], "iv_after": after["iv"],
                  "window_model_sd": math.sqrt(window_var),
                  "shared_with": [r.get("asset_name") for r, _ in sharing if r is not row],
                  "driver": driver.get("asset_name"),
                  "held_results": priced["held_results"],
                  "edge_results": priced["edge_results"]}
        if priced["why"]:
            out.append({**base, **detail, "verdict": "unread", "why": priced["why"]})
            continue
        label = (f"the model's {len(sharing)} readouts in the window come to "
                 f"{math.sqrt(window_var):.1%}" if len(sharing) > 1
                 else f"the model's move is {math.sqrt(window_var):.1%}")
        if driver is not row:
            label += f", carried by {driver.get('asset_name')}"
        verdict, said, lo, hi = _verdict(math.sqrt(window_var), priced["variance"],
                                         priced["error"], label)
        out.append({**base, **detail, "market_variance": priced["variance"],
                    "error": priced["error"], "market_lo": lo, "market_hi": hi,
                    "base_iv": priced["base"], "raw_base_iv": priced["raw_base"],
                    "verdict": verdict, "why": said})
    return {"ok": True, "spot": spot, "as_of": chain["as_of"].isoformat(),
            "iv30": chain.get("iv30"), "expiries": len(expiries),
            "results": ({"date": results["date"].isoformat(),
                         "expected": results["expected"],
                         "move": math.sqrt(measured["variance"]) if measured else None}
                        if results else None),
            "rows": out}


def us_symbol(db_path, ticker: str) -> str | None:
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT ticker, us_adr_ticker FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()
        return (row["us_adr_ticker"] or row["ticker"]) if row else None
    finally:
        conn.close()


def company(db_path, ticker: str, get=None) -> dict | None:
    """The comparison for one company, reading its chain and next results date now."""
    import forecast_view as V
    symbol = us_symbol(db_path, ticker)
    if symbol is None:
        return None
    stakes = (V.catalyst_stakes(db_path, ticker) or {}).get("priced") or []
    chain = parse_chain(fetch_chain(symbol, get), symbol)
    time.sleep(PAUSE_S if get is None else 0)
    results = parse_earnings(fetch_earnings(symbol, get)) if chain else None
    return {"ticker": ticker, "symbol": symbol, **compare(chain, results, stakes)}
