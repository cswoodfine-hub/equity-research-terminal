"""Two market reads the catalyst focus list's week needs: short interest and the move
the options price into a dated event.

Short interest is Nasdaq's quote page endpoint
(``api.nasdaq.com/api/quote/{SYM}/short-interest?assetClass=stocks``): FINRA's twice-monthly
settlement figures, each with the average daily volume and days to cover. Keyless, and it
answers a browser's headers only, like the consensus endpoint the street fetcher reads.

The implied move is Cboe's delayed chain, read through event_moves (the parser the step 3
comparison uses): the at-the-money volatility of the first expiry on or after the event,
times the square root of the time to it, is the one standard deviation move the chain
prices by that expiry. It says how big a move the market is paying for, not which way.

Both are display reads, not book data: nothing is stored in the database. Each answer is
kept on disk under backend/cache for CACHE_HOURS, so a page recomputed through the day asks
each host once. A failure is a None the page reads as "no free data", never a raise.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.error
import urllib.request

import db

SHORT_URL = "https://api.nasdaq.com/api/quote/{symbol}/short-interest?assetClass=stocks"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
TIMEOUT_S = 15
PAUSE_S = 0.5
CACHE_HOURS = 12
CACHE_PATH = db.BACKEND_DIR / "cache" / "market_reads.json"


def _num(text):
    if text in (None, "", "N/A"):
        return None
    try:
        return float(str(text).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def parse_short_interest(payload: dict | None) -> list:
    """[{settlement, shares, avg_volume, days_to_cover}], newest first. Empty where the
    payload carries no table."""
    table = (((payload or {}).get("data") or {}).get("shortInterestTable") or {})
    out = []
    for row in table.get("rows") or []:
        try:
            day = dt.datetime.strptime(row.get("settlementDate") or "", "%m/%d/%Y").date()
        except ValueError:
            continue
        shares = _num(row.get("interest"))
        if shares is None:
            continue
        out.append({"settlement": day.isoformat(), "shares": shares,
                    "avg_volume": _num(row.get("avgDailyShareVolume")),
                    "days_to_cover": _num(row.get("daysToCover"))})
    return sorted(out, key=lambda r: r["settlement"], reverse=True)


def implied_move(chain: dict | None, on_or_after: dt.date) -> dict | None:
    """{expiry, iv, years, move}: the first expiry on or after the event and the one
    standard deviation move its at-the-money volatility prices by then. None where the
    chain lists no expiry that late."""
    if not chain:
        return None
    later = [e for e in chain.get("expiries") or [] if e["expiry"] >= on_or_after]
    if not later:
        return None
    e = later[0]
    return {"expiry": e["expiry"].isoformat(), "iv": e["iv"], "years": e["t"],
            "move": e["iv"] * math.sqrt(e["t"]), "spot": chain.get("spot")}


# --- the cached reads ------------------------------------------------------------------
def _load() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


def _fresh(entry: dict | None, now: float) -> bool:
    return bool(entry) and now - entry.get("at", 0) < CACHE_HOURS * 3600


def _get_json(url: str) -> dict | None:
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def short_interest(symbols: list, get=None) -> dict:
    """{symbol: [rows, newest first]} for each US symbol, from the cache where it is fresh."""
    get = get or _get_json
    cache, now, out, dirty = _load(), time.time(), {}, False
    for symbol in symbols:
        key = f"short:{symbol}"
        if _fresh(cache.get(key), now):
            out[symbol] = cache[key]["rows"]
            continue
        rows = parse_short_interest(get(SHORT_URL.format(symbol=symbol)))
        if rows:
            cache[key] = {"at": now, "rows": rows}
            dirty = True
        out[symbol] = rows
        time.sleep(PAUSE_S if get is _get_json else 0)
    if dirty:
        _save(cache)
    return out


def implied_moves(requests: list, fetch=None) -> dict:
    """{(symbol, date): move or None} for [(symbol, event date)], each chain read once."""
    import event_moves
    fetch = fetch or event_moves.fetch_chain
    cache, now, out, dirty, chains = _load(), time.time(), {}, False, {}
    for symbol, day in requests:
        key = f"move:{symbol}:{day}"
        if _fresh(cache.get(key), now):
            out[(symbol, day)] = cache[key]["move"]
            continue
        if symbol not in chains:
            try:
                chains[symbol] = event_moves.parse_chain(fetch(symbol), symbol)
            except Exception:                       # a refused or malformed chain
                chains[symbol] = None
            time.sleep(PAUSE_S if fetch is event_moves.fetch_chain else 0)
        try:
            when = dt.date.fromisoformat(day)
        except ValueError:
            out[(symbol, day)] = None
            continue
        move = implied_move(chains[symbol], when)
        if move:
            cache[key] = {"at": now, "move": move}
            dirty = True
        out[(symbol, day)] = move
    if dirty:
        _save(cache)
    return out
