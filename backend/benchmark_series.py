"""The one benchmark every forward return in this book is read against, and why.

Three modules measured against three different things: ``backtest`` against the
equal-weight return of the book's own universe, ``call_log.score`` against PPH, and
``event_signal`` against XBI. The first manufactures signals, measurably: a book of
biotech is dragged by whatever is collapsing inside it, so its own mean is a benchmark
almost anything beats, and fifteen change types read positive against it that read nil
against XBI. The second is a pharma fund, cap-weighted, which is the wrong shape for a
small-cap signal. One benchmark, named on every page, is the only way a reader can
compare two of the book's claims.

XBI: the S&P Biotechnology Select Industry index fund, equal-weighted, so a small name
counts as much as a large one, which is what every signal here measures; sector-matched;
and tradeable, so a long against it is a position someone could hold. Its adjusted close
is used where the fetcher stores one, so a dividend is not read as underperformance.

Kept as a module with no imports from the rest of the book, so ``backtest``,
``call_log`` and ``event_signal`` can all read it without a cycle.
"""

from __future__ import annotations

import bisect

BENCHMARK = "XBI"


def series(conn, symbol: str = BENCHMARK) -> list:
    """[(day, close)] for one benchmark, adjusted where the source gives an adjusted
    close. [] where the symbol is not on file, which a caller must say rather than
    silently fall back from."""
    return [(r["as_of"][:10], r["close"]) for r in conn.execute(
        """SELECT substr(as_of, 1, 10) AS as_of, COALESCE(adjclose, close) AS close
             FROM benchmark_prices
            WHERE symbol = ? AND COALESCE(adjclose, close) IS NOT NULL
            ORDER BY as_of""", (symbol,))]


def span(bars: list, day: str, a: int, b: int):
    """The benchmark's return between bars ``a`` and ``b`` trading days from the last bar
    on or before ``day``, or None where either runs off the series. Same contract as
    ``backtest.span_return``, so the two can be subtracted."""
    if not bars:
        return None
    idx = bisect.bisect_right([x[0] for x in bars], day) - 1
    i, j = idx + a, idx + b
    if not (0 <= i < len(bars)) or not (0 <= j < len(bars)):
        return None
    return bars[j][1] / bars[i][1] - 1 if bars[i][1] else None


def on_or_before(bars: list, day: str):
    """(day, close) of the last bar on or before ``day``, or None."""
    if not bars:
        return None
    idx = bisect.bisect_right([x[0] for x in bars], day) - 1
    return bars[idx] if idx >= 0 else None
