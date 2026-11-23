"""The live read: Yahoo's recent bars as they stand now, held in memory and never written.

The Prices tab had one way to bring its chart up to date, which was the whole company
refresh: seventeen sources and a re-derived pipeline, 363 seconds the last time it was
timed, to move a series that is two requests to one endpoint. That refresh also files
what it reads. Pressed while a market is open it writes the last trade into the price
history as that day's close, which no later run corrects (CLAUDE.md, "Daily pulse").

So this is a read and not a fetcher. It asks Yahoo for the recent five minute and hourly
bars, keeps the answer in this process for about a minute, and hands it to the page, which
lays it over the stored series. Nothing here opens the book: the route looks the
company's symbol up and that is the only time the database is touched, to be read. No
``refresh_runs`` row is opened, no snapshot and no bar is written, and that is the
design rather than an omission, for two reasons.

One is the history. A path that cannot write cannot put an intraday price where a close
belongs, whatever hour it is called at.

The other is the cache. ``response_cache`` stamps every stored response with the
database file's modification time, so a bar written once a minute would have every
company's valuation recomputed once a minute, and a cold fair value takes about forty
seconds. Holding the bars in memory moves no stamp.

What Yahoo's chart ``meta`` carries about the market, read off real payloads on
2026-11-23 (NYSE before and after its open, London mid-session), is narrower than its quote
endpoint. There is no ``marketState`` and no stated delay. There is
``currentTradingPeriod`` with the start and end of the pre, regular and post sessions,
``regularMarketTime`` for the last trade, the exchange's name and its timezone. So
whether the regular session is open is worked out here from the session's own hours,
and the delay is reported as what it is: not stated. What can be measured is how old
the last trade was when it was read. London's was fifteen minutes behind the clock and
New York's, minutes after its open the same day, between two seconds and fifty-one, so
the age is returned beside the null.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fetchers import prices as yahoo

SOURCE = yahoo.YAHOO_SOURCE
# How long an answer stands in for a new request. The page asks once a minute while a
# session is open and every rerun of the page asks again, so without a hold a reader
# clicking through tabs would send Yahoo a request a click. A little under the minute
# and not the minute itself: the page's timer fires every sixty seconds, and against a
# hold of exactly sixty a tick landing a moment early would be handed the last answer
# again and the chart would run two minutes behind every so often.
HOLD_S = 55.0
# A failure is held too. The page reads this route while it is being drawn, so a Yahoo
# that has stopped answering would otherwise cost every rerun the full timeout. Shorter
# than the page's minute, so each tick of an open session still tries again.
FAIL_HOLD_S = 45.0
# Short, because the caller is a page mid-draw and not a refresh, but not as short as
# the endpoint usually needs. It answers in about a tenth of a second on a quiet
# market and took between three and five seconds in the first minutes after the New
# York open on 2026-11-23, when a four second limit failed two reads in six.
TIMEOUT_S = 8.0
# What is asked for at each bar size. Five sessions of five minute bars is 391 bars and
# a month of hourly ones about 150, each one request. Both ranges are among the
# endpoint's own validRanges (see HourlyBarsFetcher on what it does with one that is
# not). The stored series reaches further back; these only have to reach the last full
# refresh, and the page says so when they do not.
WINDOWS = {"5m": "5d", "60m": "1mo"}
STEP_S = {"5m": 300, "60m": 3600}
_STAMP = "%Y-%m-%d %H:%M"
_BAR_KEYS = ("as_of", "open", "high", "low", "close", "volume")

_lock = threading.Lock()
# (symbol, interval) -> {"good": {...} | None, "tried": monotonic, "error": str | None}
_held: dict = {}


def clear() -> None:
    """Forget every held answer (tests)."""
    with _lock:
        _held.clear()


def _iso(epoch) -> str | None:
    if epoch is None:
        return None
    return dt.datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _regular(meta: dict) -> tuple:
    period = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    return period.get("start"), period.get("end")


def settle_last_trade(rows: list[dict], meta: dict, interval: str) -> list[dict]:
    """Fold Yahoo's trailing last-trade point into the bar it falls in. Pure.

    While a session is open the chart's last element is not a bar. It is the last
    trade, stamped at the second it printed, with open, high, low and close all equal
    and a volume of nought: London at 13:44 UTC on 2026-11-23 ended on a 13:25 bar
    followed by a point at 13:28:53. Kept as a bar of its own it draws a stick at
    13:28 on a five minute chart, and a different stray stick a minute later.

    So the point is moved to the start of the bar that contains it, counted from the
    session's own opening time, which is what the bars are counted from (New York's
    hourly bars start on the half hour). Where a bar already stands there the trade is
    folded into it by the rule every bar on the page is built by: high the higher,
    low the lower, close the later. Where none does, the point becomes that bar.

    After the close the point sits exactly on the closing time (16:00 in New York),
    which is outside the session's half-open hours and so is left alone. The stored
    series keeps it as a bar of its own, and the two have to agree on its timestamp
    for one to replace the other.
    """
    start, end = _regular(meta)
    step = STEP_S.get(interval)
    if not rows or start is None or end is None or not step:
        return rows
    offset = int(meta.get("gmtoffset") or 0)
    opens = dt.datetime.utcfromtimestamp(start + offset)
    closes = dt.datetime.utcfromtimestamp(end + offset)
    last = rows[-1]
    try:
        stamp = dt.datetime.strptime(last["as_of"], _STAMP)
    except (KeyError, TypeError, ValueError):
        return rows
    if not opens <= stamp < closes:
        return rows
    into = int((stamp - opens).total_seconds())
    key = (opens + dt.timedelta(seconds=into - into % step)).strftime(_STAMP)
    if len(rows) >= 2 and rows[-2]["as_of"] == key:
        bar = dict(rows[-2])
        highs = [v for v in (bar.get("high"), last.get("high")) if v is not None]
        lows = [v for v in (bar.get("low"), last.get("low")) if v is not None]
        volumes = [v for v in (bar.get("volume"), last.get("volume")) if v is not None]
        if bar.get("open") is None:
            bar["open"] = last.get("open")
        bar["high"] = max(highs) if highs else None
        bar["low"] = min(lows) if lows else None
        bar["close"] = last["close"]
        bar["volume"] = sum(volumes) if volumes else None
        return rows[:-2] + [bar]
    if key == last["as_of"]:
        return rows
    return rows[:-1] + [dict(last, as_of=key)]


def same_clock(payload: dict) -> dict:
    """The payload without the bars from the other side of a clock change. Pure.

    ``parse_chart`` stamps every bar with the one ``gmtoffset`` in the meta, which is
    today's. A window that reaches back across the day the clocks moved has sessions
    that ran on the other offset, and those come out an hour off: a month of New York
    hourly bars asked for on 2026-11-23 began "2026-10-21 08:30", an hour before the
    exchange opened. Yahoo does say which sessions those are, since each entry in
    ``tradingPeriods`` carries its own offset. So every bar up to the end of the last
    session on a different offset is dropped here and left to the stored series. An
    hour's error laid over stored bars would draw each of those sessions twice.

    A payload this cannot read is returned as it came, for ``parse_chart`` to refuse.
    """
    try:
        result = payload["chart"]["result"][0]
        meta = result.get("meta") or {}
        today = meta.get("gmtoffset")
        cut = None
        for group in meta.get("tradingPeriods") or []:
            for period in (group if isinstance(group, list) else [group]):
                if (isinstance(period, dict) and period.get("end") is not None
                        and period.get("gmtoffset") not in (None, today)):
                    cut = max(cut or 0, period["end"])
        if cut is None:
            return payload
        stamps = result.get("timestamp") or []
        keep = [i for i, stamp in enumerate(stamps) if stamp > cut]
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        kept = {name: [series[i] for i in keep if i < len(series)]
                for name, series in quote.items() if isinstance(series, list)}
        trimmed = dict(result, timestamp=[stamps[i] for i in keep],
                       indicators={"quote": [kept]})
        return {"chart": dict(payload["chart"], result=[trimmed])}
    except (AttributeError, IndexError, KeyError, TypeError):
        return payload


def market(meta: dict, now: float, read: float | None = None) -> dict:
    """What Yahoo's meta says about the market at ``now`` (epoch seconds). Pure.

    ``read`` is when the meta was fetched, which inside the hold is up to a minute
    before ``now``. The session's state is judged at ``now``; the age of the last
    trade is measured at ``read``, because that is the moment the two were both true.

    ``regular_open`` is the session's stated hours against the clock, nothing more.
    Yahoo does not say whether today is a holiday, so ``traded_this_session`` is
    returned beside it: whether the last trade falls inside the session the hours
    describe. An open session with no trade in it is a holiday, a halt or the first
    seconds after the bell, and the page says which of the two facts it has rather
    than guessing between them.
    """
    periods = meta.get("currentTradingPeriod") or {}
    start, end = _regular(meta)
    last_trade = meta.get("regularMarketTime")
    regular_open = start is not None and end is not None and start <= now < end
    phase = "closed"
    for name in ("pre", "regular", "post"):
        period = periods.get(name) or {}
        if (period.get("start") is not None and period.get("end") is not None
                and period["start"] <= now < period["end"]):
            phase = name
    traded = None
    if start is not None and last_trade is not None:
        traded = bool(last_trade >= start)
    read = now if read is None else read
    read_in_session = start is not None and end is not None and start <= read < end
    return {
        "regular_open": bool(regular_open),
        "phase": phase,
        "traded_this_session": traded,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "exchange_timezone": meta.get("exchangeTimezoneName"),
        "timezone": meta.get("timezone"),
        "gmtoffset": meta.get("gmtoffset"),
        "regular_start": _iso(start),
        "regular_end": _iso(end),
        "seconds_to_open": (int(start - now) if start is not None and now < start
                            else None),
        "seconds_to_close": int(end - now) if regular_open else None,
        "last_trade_at": _iso(last_trade),
        "last_price": meta.get("regularMarketPrice"),
        # Measured, not stated: how far behind the clock the last trade was when it
        # was read. Only while the session is open and has traded, since after the
        # close it measures the evening and not the feed.
        "quote_age_seconds": (int(read - last_trade)
                              if read_in_session and traded and last_trade is not None
                              else None),
        # The quote endpoint names its delay exchangeDataDelayedBy. The chart meta
        # carried no such field for New York or London on 2026-11-23, so this is null
        # unless Yahoo starts sending one: never a figure assumed from the exchange.
        "stated_delay_minutes": meta.get("exchangeDataDelayedBy"),
    }


def _session_end(meta: dict, day: str):
    """The closing time (epoch) of the regular session dated ``day`` at the exchange,
    from the hours Yahoo lists, or None where it lists none for that day."""
    offset = int(meta.get("gmtoffset") or 0)
    periods = [(meta.get("currentTradingPeriod") or {}).get("regular") or {}]
    for group in meta.get("tradingPeriods") or []:
        periods += [p for p in (group if isinstance(group, list) else [group])
                    if isinstance(p, dict)]
    for period in periods:
        start, end = period.get("start"), period.get("end")
        if start is None or end is None:
            continue
        if dt.datetime.utcfromtimestamp(start + offset).strftime("%Y-%m-%d") == day:
            return end
    return None


def live_daily(bars: list[dict], meta: dict, now: float) -> dict | None:
    """The newest session in the five minute bars as one daily bar. Pure.

    Open the first, high the highest, low the lowest, close the last, volume summed:
    the rule the page resamples every other bar by. A field no bar carries stays null.

    It is built from regular-session five minute bars, so its volume is theirs and
    runs under the consolidated figure a finished daily bar carries (Lilly on
    2026-11-20: 2,459,214 here against 3,540,200, with the same open, high, low and
    close). ``complete`` says whether that
    session had closed when this was read, and ``session_end`` when, so the page can
    tell a session still forming from a finished one and prefer a stored close that
    was read after the bell.
    """
    if not bars:
        return None
    day = bars[-1]["as_of"][:10]
    session = [b for b in bars if b["as_of"][:10] == day]
    opens = [b["open"] for b in session if b.get("open") is not None]
    highs = [b["high"] for b in session if b.get("high") is not None]
    lows = [b["low"] for b in session if b.get("low") is not None]
    volumes = [b["volume"] for b in session if b.get("volume") is not None]
    end = _session_end(meta, day)
    return {
        "as_of": day,
        "open": opens[0] if opens else None,
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "close": session[-1]["close"],
        "volume": sum(volumes) if volumes else None,
        "bars": len(session),
        "first_bar": session[0]["as_of"],
        "last_bar": session[-1]["as_of"],
        "session_end": _iso(end),
        "complete": (bool(now >= end) if end is not None else None),
    }


def _series(ticker: str, symbol: str, interval: str, *, fresh: bool, getter, clock,
            wall) -> dict:
    """One bar size for one symbol: the held answer inside the hold, else Yahoo.

    Returns {"good": the last answer that parsed or None, "error": why the newest
    attempt failed or None, "held": whether Yahoo was left alone}. A failure does not
    throw the last good answer away: bars read two minutes ago, said to be two minutes
    old, are worth more to a chart than a hole.
    """
    key = (symbol, interval)
    with _lock:
        entry = dict(_held.get(key) or {})
    if entry and not fresh:
        age = clock() - entry["tried"]
        if age < (FAIL_HOLD_S if entry.get("error") else HOLD_S):
            return {"good": entry.get("good"), "error": entry.get("error"), "held": True}
    try:
        payload = same_clock(getter(symbol, WINDOWS[interval], interval))
        rows, _ = yahoo.parse_chart(payload, ticker, interval)
        meta = payload["chart"]["result"][0].get("meta") or {}
        rows = settle_last_trade(rows, meta, interval)
        good = {"bars": [{k: row.get(k) for k in _BAR_KEYS} for row in rows],
                "meta": meta, "fetched": wall()}
        entry = {"good": good, "tried": clock(), "error": None}
    except Exception as exc:      # noqa: BLE001  a soft error by contract, never a 500
        reason = f"{type(exc).__name__}: {exc}".strip()[:300]
        entry = {"good": entry.get("good"), "tried": clock(), "error": reason}
    with _lock:
        _held[key] = entry
    return {"good": entry["good"], "error": entry["error"], "held": False}


def read(ticker: str, symbol: str | None = None, *, fresh: bool = False, getter=None,
         clock=time.monotonic, wall=time.time) -> dict:
    """The live bars for one company. Never raises and never writes.

    ``symbol`` is what Yahoo is asked for, the US line where the company has one (the
    caller resolves it as the price fetcher does), and defaults to the ticker.
    ``fresh`` asks Yahoo whatever the hold says, which is the tab's Refresh button.
    ``getter``, ``clock`` and ``wall`` are the network and the two clocks, passed in so
    a test can stand in for each.

    ``ok`` is false when either bar size could not be read, with the reason, and the
    last good bars for it ride along with the time they were read if there are any.
    """
    ticker = ticker.upper()
    symbol = symbol or ticker
    getter = getter or (lambda sym, rng, iv: yahoo.fetch_chart(sym, rng, iv,
                                                               timeout=TIMEOUT_S))
    sizes = list(WINDOWS)
    with ThreadPoolExecutor(max_workers=len(sizes)) as pool:
        answers = dict(zip(sizes, pool.map(
            lambda size: _series(ticker, symbol, size, fresh=fresh, getter=getter,
                                 clock=clock, wall=wall), sizes)))
    now = wall()
    errors = [f"{size}: {answers[size]['error']}" for size in sizes
              if answers[size]["error"]]
    goods = {size: answers[size]["good"] for size in sizes}
    # The five minute read is the newest look at the session and the one the daily bar
    # is built from; the hourly one stands in for the market's hours if it is all
    # there is.
    lead = goods.get("5m") or goods.get("60m")
    meta = (lead or {}).get("meta") or {}
    fetched = [good["fetched"] for good in goods.values() if good]
    five = (goods.get("5m") or {}).get("bars") or []
    return {
        "ok": not errors,
        "reason": "; ".join(errors) or None,
        "ticker": ticker,
        "symbol": symbol,
        "source": SOURCE,
        "currency": meta.get("currency"),
        # The older of the two reads: what the page says the prices are as of.
        "fetched_at": _iso(min(fetched)) if fetched else None,
        "held": all(answers[size]["held"] for size in sizes),
        "hold_seconds": int(HOLD_S),
        "windows": dict(WINDOWS),
        "bars": {size: (goods[size] or {}).get("bars") or [] for size in sizes},
        "fetched": {size: _iso((goods[size] or {}).get("fetched")) for size in sizes},
        "live_daily": live_daily(five, (goods.get("5m") or {}).get("meta") or {}, now),
        "market": market(meta, now, lead["fetched"]) if lead else None,
    }
