"""Why a company's value moved between two days.

The terminal keeps three histories and until now they did not meet. ``changes`` is the
world moving, ``assumption_edits`` is the analyst moving, ``model_calls`` is the number
that came out. On 2026-10-25 a fair value moved 8.7% in a day and answering why took an
afternoon of hand queries, a scratch database and a git worktree. A reader of someone
else's book cannot do that, and a licensee should not have to.

What this does and does not claim:

- It states what provably did not move. Four comparison lenses, the close, the date of
  the close and the discount rate are all recorded on the call, so when they are
  identical the market can be ruled out rather than merely doubted. That single fact did
  more work in the 25 October decomposition than everything else put together.
- It names the inputs that changed, from the ledger, with the reason the analyst gave.
- It names the data that changed, from the diff feed, grouped by kind.
- It reports whether the engine itself changed, from the commit on each call, and says
  plainly that a code change cannot be attributed from records alone: that needs the old
  engine run against the same book, which is a job and not a query.

It never divides a move into percentages it cannot defend. A residual stays a residual
and is labelled one.
"""

from __future__ import annotations

import collections

import db

# Recorded on every call, so a change in any of them is visible without re-deriving
# anything. These are the ones that let the market be ruled in or out.
MARKET_FIELDS = ("price", "price_date", "cost_of_equity", "target_low", "target_mid",
                 "target_high", "pe_mid", "ev_sales_mid", "precedents_mid")


def _call(conn, ticker: str, day: str):
    """The call on a day, or the last one before it."""
    return conn.execute(
        """SELECT * FROM model_calls WHERE ticker = ? AND as_of <= ?
            ORDER BY as_of DESC LIMIT 1""", (ticker.upper(), day)).fetchone()


def _gate_total(conn, ticker: str, day: str) -> tuple[int, float]:
    rows = conn.execute(
        """SELECT per_share_now FROM gate_calls WHERE ticker = ? AND as_of = ?""",
        (ticker.upper(), day)).fetchall()
    return len(rows), sum(r["per_share_now"] or 0.0 for r in rows)


def _edits(conn, ticker: str, start: str, end: str) -> list[dict]:
    """Assumption changes in the window, one entry per save rather than per row."""
    rows = conn.execute(
        """SELECT e.*, s.brand_name, s.generic_name, i.name AS indication
             FROM assumption_edits e
             LEFT JOIN assets s ON s.id = e.asset_id
             LEFT JOIN companies c ON c.id = s.owner_company_id
             LEFT JOIN indications i ON i.id = e.indication_id
            WHERE c.ticker = ? AND e.changed_at > ? AND e.changed_at <= ?
              AND e.reason IS NOT NULL AND e.reason != 'initial_seed'
            ORDER BY e.changed_at""",
        (ticker.upper(), start, f"{end} 23:59:59")).fetchall()
    batches: dict = {}
    for r in rows:
        key = r["batch_id"] or f"row:{r['id']}"
        held = batches.setdefault(key, {
            "when": r["changed_at"], "reason": r["reason"], "why": r["rationale"],
            "trigger": r["trigger_ref"], "by": r["changed_by"],
            "rnpv_before": r["rnpv_before"], "rnpv_after": r["rnpv_after"], "rows": []})
        held["rows"].append({
            "asset": r["brand_name"] or r["generic_name"], "indication": r["indication"],
            "key": r["key"], "from": r["old_value"], "to": r["new_value"]})
    return list(batches.values())


def _data(conn, ticker: str, start: str, end: str) -> dict:
    """What the world did, by kind, from the diff feed."""
    rows = conn.execute(
        """SELECT change_type, significance, COUNT(*) n FROM changes
            WHERE detected_at > ? AND detected_at <= ?
            GROUP BY change_type, significance""",
        (f"{start} 23:59:59", f"{end} 23:59:59")).fetchall()
    kinds = collections.Counter()
    for r in rows:
        kinds[r["change_type"] or "unclassified"] += r["n"]
    return dict(kinds.most_common())


def between(db_path=None, ticker: str = "", start: str = "", end: str = "") -> dict:
    """The two calls, what held still, what moved, and what cannot be attributed."""
    conn = db.get_connection(db_path)
    try:
        a, b = _call(conn, ticker, start), _call(conn, ticker, end)
        if a is None or b is None:
            return {"ok": False, "ticker": ticker.upper(), "reason": "no_calls",
                    "why": "the book recorded no fair value on or before one of these "
                           "days, so there is nothing to compare"}
        if a["as_of"] == b["as_of"]:
            return {"ok": False, "ticker": ticker.upper(), "reason": "same_call",
                    "why": f"both dates resolve to the call of {a['as_of']}"}
        held, moved = [], {}
        for field in MARKET_FIELDS:
            x, y = a[field], b[field]
            if x == y:
                held.append(field)
            else:
                moved[field] = {"from": x, "to": y}
        gates_a, per_a = _gate_total(conn, ticker, a["as_of"])
        gates_b, per_b = _gate_total(conn, ticker, b["as_of"])
        edits = _edits(conn, ticker, a["as_of"], b["as_of"])
        data = _data(conn, ticker, a["as_of"], b["as_of"])
        same_code = (a["code_version"] or "") == (b["code_version"] or "")
        # A call brought in from another book is not this book's view on the day, and two
        # books price differently. Comparing across the seam reads as the model changing
        # its mind when it only changed author.
        crosses = (a["source"] or "") != (b["source"] or "")
    finally:
        conn.close()

    fair_a, fair_b = a["fair_value"], b["fair_value"]
    move = (fair_b - fair_a) if (fair_a is not None and fair_b is not None) else None
    out = {
        "ok": True, "ticker": ticker.upper(),
        "from": {"as_of": a["as_of"], "fair_value": fair_a, "price": a["price"],
                 "code_version": a["code_version"], "source": a["source"]},
        "to": {"as_of": b["as_of"], "fair_value": fair_b, "price": b["price"],
               "code_version": b["code_version"], "source": b["source"]},
        "move": move,
        "move_pct": (move / fair_a) if (move is not None and fair_a) else None,
        "held_still": held, "market_moved": moved,
        "gates": {"from": gates_a, "to": gates_b, "per_share_from": per_a,
                  "per_share_to": per_b, "move": per_b - per_a},
        "assumptions": edits, "data": data,
        "code": {"from": a["code_version"], "to": b["code_version"], "same": same_code},
        "crosses_books": crosses,
    }
    out["reading"] = _reading(out)
    return out


def _reading(out: dict) -> list[str]:
    """The decomposition in sentences, claiming only what the records support."""
    said = []
    move, pct = out["move"], out["move_pct"]
    if move is None:
        return ["One of the two days has no fair value to compare."]
    said.append(f"Fair value moved {move:+,.2f} a share"
                + (f" ({pct:+.1%})" if pct is not None else "")
                + f", {out['from']['as_of']} to {out['to']['as_of']}.")
    if out["crosses_books"]:
        said.append("These two calls came from different books, one of them brought in "
                    "from an exported history. Part of this move is the seam between "
                    "them rather than anything the model did.")
    if not out["market_moved"]:
        said.append("The market did not move it. The close, the date of the close, the "
                    "discount rate and every comparison lens are identical on both days.")
    else:
        said.append("The market moved too: "
                    + ", ".join(sorted(out["market_moved"])) + ".")
    gates = out["gates"]
    if abs(gates["move"]) > 0.005 or gates["from"] != gates["to"]:
        said.append(f"Priced gates went {gates['from']} to {gates['to']}, worth "
                    f"{gates['move']:+,.2f} a share.")
    else:
        said.append("The priced gates are worth what they were.")
    if out["assumptions"]:
        n = sum(len(e["rows"]) for e in out["assumptions"])
        kinds = sorted({e["reason"] for e in out["assumptions"]})
        said.append(f"The analyst changed {n} number(s) in "
                    f"{len(out['assumptions'])} save(s): {', '.join(kinds)}.")
    else:
        said.append("No analyst changed an assumption on this company in the window.")
    if out["data"]:
        top = ", ".join(f"{k} {v}" for k, v in list(out["data"].items())[:4])
        said.append(f"The data underneath changed: {top}.")
    if not out["code"]["same"]:
        said.append(f"The engine also changed, {out['code']['from']} to "
                    f"{out['code']['to']}. A code change cannot be attributed from these "
                    f"records: that needs the old engine run against the same book.")
    return said
