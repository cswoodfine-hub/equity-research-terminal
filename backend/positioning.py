"""How the market is positioned in one stock, from the four reads that say so.

The book's side of a readout is the gate: the odds, and what the asset is worth either
way. The market's side has been one number, the price, inverted into the odds it pays for
(``gate_odds``). The price is the sum of everybody's position and says nothing about who
holds it or how hard they are leaning. Four free sources say a little of that, and each
says a different thing:

- **Short interest**, twice a month from FINRA through Nasdaq's quote endpoint
  (``market_reads``): shares sold short and the days of volume it would take to cover.
- **The options chain**, delayed from Cboe (``event_moves``): the move the market is
  paying for by each expiry, set beside the move the model's own legs imply for each
  dated catalyst. It is a size, never a direction.
- **Insiders**, from Form 4 (``insiders``): what the company's own officers and directors
  bought and sold in the open market.
- **Institutional holders**, from 13F (``holders``): who held it at the last quarter end
  and how that changed.

They are put side by side and not combined. There is no positioning score here, because
a score would need weights nobody has measured: whether short interest ahead of a readout
precedes anything in this universe is a question for ``event_signal``, with a placebo,
before it is a number on a page.

Each read is soft. A source that does not answer is a part marked absent with the reason,
and the others are still returned. The first two are network reads made when asked, kept
on disk for twelve hours by ``market_reads``; the last two are read from the book.
"""

from __future__ import annotations

import db

SHORT_ROWS = 6
# The row-by-row lists stay behind their own routes. Here each stored read is its summary:
# four reads side by side stop being side by side once one of them is three hundred lines.
_LISTS = {"insiders": ("transactions", "codes"),
          "holders": ("top", "sold_out", "set_aside")}
# event_moves reads a 403 from Cboe as a symbol with no listed options, which is what it
# is for an over-the-counter ADR. Cboe also answers 403 when it refuses the request
# itself (it did for every symbol on 2026-11-23), and the two cannot be told apart from
# here, so the reason is not passed on as if it were a fact about the stock.
_NO_CHAIN = ("Cboe returned no chain. It answers the same way for a stock with no listed "
             "options and when it refuses the request, so this is not evidence that none "
             "are listed.")


def _short(symbol: str) -> dict:
    import market_reads
    try:
        rows = (market_reads.short_interest([symbol]) or {}).get(symbol) or []
    except Exception as exc:                      # a host that refused or changed shape
        return {"ok": False, "reason": f"short interest could not be read: {exc}"}
    if not rows:
        return {"ok": False, "reason": "no short interest published for this symbol"}
    latest, earlier = rows[0], (rows[1] if len(rows) > 1 else None)
    change = None
    if earlier and earlier.get("shares"):
        change = round(latest["shares"] / earlier["shares"] - 1, 4)
    return {"ok": True, "source": "FINRA settlement figures, read from Nasdaq",
            "latest": latest, "change_from_previous": change, "history": rows[:SHORT_ROWS],
            "note": ("Shares sold short at the settlement date. Not divided by the float: "
                     "the book holds no float figure.")}


def _options(db_path, ticker: str) -> dict:
    import event_moves
    try:
        got = event_moves.company(db_path, ticker)
    except Exception as exc:
        return {"ok": False, "reason": f"the options chain could not be read: {exc}"}
    if got is None:
        return {"ok": False, "reason": "no US listing on file to read a chain for"}
    if got.get("ok") is False and "no listed options" in (got.get("reason") or ""):
        got = {**got, "reason": _NO_CHAIN}
    return {"source": "Cboe delayed quotes", **got}


def _from_book(module_name: str, db_path, ticker: str) -> dict:
    """One of the two stored reads, absent with its reason where the module or its table
    is not there yet (a book that has not run the fetcher)."""
    try:
        module = __import__(module_name)
        got = module.for_company(db_path, ticker)
    except Exception as exc:
        return {"ok": False, "reason": f"{module_name} could not be read: {exc}"}
    if got is None:
        return {"ok": False, "reason": f"no {module_name} rows on file"}
    return {k: v for k, v in got.items() if k not in _LISTS.get(module_name, ())}


def for_company(db_path=None, ticker: str = "", parts: tuple | None = None) -> dict | None:
    """The reads for one company. ``parts`` narrows to some of short, options, insiders
    and holders, so a caller that wants the stored reads makes no network call."""
    import event_moves
    ticker = (ticker or "").strip().upper()
    conn = db.get_connection(db_path)
    try:
        known = conn.execute("SELECT name FROM companies WHERE ticker = ?",
                             (ticker,)).fetchone()
    finally:
        conn.close()
    if known is None:
        return None
    wanted = set(parts or ("short", "options", "insiders", "holders"))
    symbol = event_moves.us_symbol(db_path, ticker)
    out = {"ticker": ticker, "name": known["name"], "us_symbol": symbol}
    if "short" in wanted:
        out["short_interest"] = (_short(symbol) if symbol else
                                 {"ok": False, "reason": "no US listing on file"})
    if "options" in wanted:
        out["options"] = _options(db_path, ticker)
    if "insiders" in wanted:
        out["insiders"] = _from_book("insiders", db_path, ticker)
    if "holders" in wanted:
        out["holders"] = _from_book("holders", db_path, ticker)
    out["note"] = ("Four separate reads, not a score. None of them states a direction "
                   "for the stock.")
    return out
