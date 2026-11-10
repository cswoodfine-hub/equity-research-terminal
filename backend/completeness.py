"""How complete the book is, company by company, in one answer.

The terminal grew past the point where anyone could hold its state in their head. It
covers seventy-five companies over a thousand assets and six hundred and eighty seed
files, and the question "what is actually finished" had no answer short of opening every
page. Worse, the honest refusals the book makes are invisible in aggregate: a company
that stops at enterprise value because its debt is unresolved looks, from the outside,
exactly like one nobody has got to.

So this is the status of every company against the things that have to be true before its
number means anything, each either met or named:

- **revenue covered.** The share of what the company reports selling that a product model
  or a company line accounts for (``forecast_view._revenue_coverage``).
- **a value at all.** Whether the sum reaches an equity figure, and the reasons where it
  does not. A refusal is a state, not a gap.
- **against guidance.** The gap between the modelled book's revenue for the guided year
  and what the company guides, with the date the guidance was read, because a figure
  three months old is a different claim from today's.
- **unmodelled revenue.** What is on the books and worth nothing in them, in dollars.

Nothing here computes a valuation or judges one. It reads what the other modules already
say and puts it in one place, so the next question is which company to work on rather
than which page to open.
"""

from __future__ import annotations

import datetime as dt

import db

# A guidance figure older than this is reported as stale. Companies guide on a quarterly
# cadence, so a row past a quarter and a half has had a raise or a cut it did not catch:
# Lilly's sat at $86.0bn from August while the company was guiding $91.5bn.
GUIDANCE_STALE_DAYS = 135

# The page values every company in the book to build itself, which takes a minute and a
# half. It is a status board rather than a figure anyone trades on, so it is served from
# a cache and says how old it is.
CACHE_TTL_S = 15 * 60
_cache: dict = {}


def _as_of(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def build(db_path=None, today=None, use_cache: bool = False) -> dict:
    """One row per company, plus the totals. Reads; never computes a valuation itself."""
    if use_cache:
        import time
        hit = _cache.get(str(db_path))
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return {**hit[1], "cached_seconds": int(time.time() - hit[0])}
    import fair_value
    import forecast_view

    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM companies ORDER BY ticker")]
    finally:
        conn.close()

    rows = []
    for ticker in tickers:
        try:
            verdict = forecast_view.company_verdict(db_path, ticker)
        except Exception as exc:                                   # noqa: BLE001
            rows.append({"ticker": ticker, "state": "error", "error": str(exc)})
            continue
        if not verdict:
            continue
        sotp = verdict.get("sotp") or {}
        coverage = verdict.get("coverage") or {}
        unmodelled = sotp.get("not_valued") or []
        equity = sotp.get("equity_per_share")
        missing = sotp.get("missing") or []

        guidance = {"ok": False}
        try:
            split = (fair_value.company(db_path, ticker) or {}).get("revenue_split")
        except Exception:                                          # noqa: BLE001
            split = None
        if split and split.get("ok"):
            read = _as_of((split.get("guidance") or {}).get("as_of"))
            age = (today - read).days if read else None
            guidance = {"ok": True, "gap_pct": split.get("gap_pct"),
                        "as_of": str(read) if read else None, "age_days": age,
                        "stale": bool(age is not None and age > GUIDANCE_STALE_DAYS)}

        # The state in one word, so a list of seventy-five can be read at a glance. The
        # order is the order the work goes in: a company with no products modelled is a
        # different job from one whose debt line is missing.
        if not unmodelled and equity is not None:
            state = "complete"
        elif equity is None and any("marketed products" in m for m in missing):
            state = "no product modelled"
        elif equity is None:
            state = "refused"
        else:
            state = "partial"

        rows.append({
            "ticker": ticker,
            "state": state,
            "coverage": coverage.get("share"),
            "equity_per_share": equity,
            "close": sotp.get("close"),
            "upside": sotp.get("upside_today"),
            "unmodelled_products": len(unmodelled),
            "unmodelled_revenue_musd": sum((u.get("revenue") or 0) for u in unmodelled),
            "missing": missing,
            "guidance": guidance,
        })

    priced = [r for r in rows if r.get("equity_per_share") is not None]
    guided = [r for r in rows if (r.get("guidance") or {}).get("ok")]
    out = {
        "as_of": str(today),
        "rows": rows,
        "totals": {
            "companies": len(rows),
            "complete": sum(1 for r in rows if r.get("state") == "complete"),
            "partial": sum(1 for r in rows if r.get("state") == "partial"),
            "no_product_modelled": sum(1 for r in rows
                                       if r.get("state") == "no product modelled"),
            "refused": sum(1 for r in rows if r.get("state") == "refused"),
            "priced": len(priced),
            "unmodelled_revenue_musd": sum(r.get("unmodelled_revenue_musd") or 0
                                           for r in rows),
            "guidance_rows": len(guided),
            "guidance_stale": sum(1 for r in guided if r["guidance"].get("stale")),
        },
        "cached_seconds": 0,
    }
    if use_cache:
        import time
        _cache[str(db_path)] = (time.time(), out)
    return out
