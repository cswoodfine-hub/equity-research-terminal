"""The odds the price is paying for on one readout, against the odds the book holds.

A disagreement with the market on a small biotech is almost never a disagreement about
the disease. It is a disagreement about one binary event, and the sum of the parts is
the wrong instrument for it: twenty-six rows where three are borrowed from an analogue
is not a level anyone can defend against a price. But the book already records, for
every priced gate and every day, what the asset is worth per share if the gate passes,
what it is worth if it fails, and what it is worth today (``call_log``, ``gate_calls``).
Those three numbers and the price are enough to turn the question round: not "what is
the company worth" but "what probability of passing does the price pay for".

**The obvious inversion is wrong, and it was tried.** The per-share legs are the asset's
own contribution, not the company's conditional value. Lilly's retatrutide swings 4.6%
of Lilly; dividing Lilly's $800 gap to the price by that leg gives an implied probability
of thirty-seven, which is the arithmetic saying the method does not apply. So the rest of
the company is taken out first, from the same day's ``model_calls``::

    rest   = fair_value - per_share_now
    p_mkt  = (price - rest - per_share_failure) / (per_share_success - per_share_failure)

and the book's own odds come from the same legs rather than from ``p_gate``, which is
null on a stated-leg catalyst and blended across indications on a trial gate::

    p_book = (per_share_now - per_share_failure) / (per_share_success - per_share_failure)

**It only means anything where one gate carries the company.** Attributing a whole gap
to a gate that swings a twentieth of the value is attributing it to the wrong thing. A
gate is reported only where its swing is at least ``MIN_SHARE`` of the book's value, which
today is eight companies and the ones that matter: Viking's VK2735 swings 148% of Viking.

**The answer comes in three regimes, and the regime is the finding.** An implied
probability inside [0, 1] is a disagreement about odds, which the readout will settle.
One above 1 says the price exceeds the asset's full-success value plus the rest of the
company: the market disagrees about the payoff, not the odds, and the readout cannot
settle that. Below 0 is the mirror. Of the ten gates reported on 2026-10-25, three were
about odds and six were about payoff. A reader who sees "the market pays 184%" and treats
it as a mispriced coin has misread it.

Not a backtest. Whether the book's odds beat the market's is what ``call_log.score``
measures as calls resolve, and this view says when each gate is due so that reconciles.
"""

from __future__ import annotations

import datetime as dt

import db

# A gate is reported only where its swing is this share of the book's value or more.
# Below it the inversion attributes the company's whole disagreement to a sideshow.
MIN_SHARE = 0.20

REGIMES = ("odds", "payoff above success", "payoff below failure")


def regime(p_mkt: float) -> str:
    if p_mkt > 1.0:
        return "payoff above success"
    if p_mkt < 0.0:
        return "payoff below failure"
    return "odds"


def invert(price, fair_value, per_share_now, per_share_success, per_share_failure) -> dict | None:
    """One gate's odds, the book's and the price's. None where the legs cannot be read."""
    if None in (price, fair_value, per_share_now, per_share_success, per_share_failure):
        return None
    span = per_share_success - per_share_failure
    if span <= 0 or fair_value <= 0:
        return None
    rest = fair_value - per_share_now
    p_mkt = (price - rest - per_share_failure) / span
    return {"p_book": (per_share_now - per_share_failure) / span,
            "p_mkt": p_mkt, "regime": regime(p_mkt),
            "share": span / fair_value, "rest": rest, "span": span}


def build(db_path=None, today=None, min_share: float = MIN_SHARE) -> dict:
    """Every dominant gate as last recorded: {rows, as_of, reason}. Reads; never writes."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT g.as_of, g.ticker, g.asset_id, g.asset_name, g.gate_label,
                      g.expected_date, g.date_confidence, g.p_gate, g.pos_now,
                      g.per_share_now, g.per_share_success, g.per_share_failure, g.price,
                      m.fair_value, m.cohort
                 FROM gate_calls g
                 JOIN model_calls m ON m.as_of = g.as_of AND m.ticker = g.ticker
                WHERE g.per_share_success IS NOT NULL AND g.per_share_failure IS NOT NULL
                  AND m.fair_value IS NOT NULL
                ORDER BY g.as_of""")]
    finally:
        conn.close()

    latest: dict = {}
    for r in rows:
        got = invert(r["price"], r["fair_value"], r["per_share_now"],
                     r["per_share_success"], r["per_share_failure"])
        if not got or got["share"] < min_share:
            continue
        due = r.get("expected_date")
        due_date = None
        try:
            due_date = dt.date.fromisoformat(str(due)[:10]) if due and len(str(due)) >= 10 else None
        except ValueError:
            due_date = None
        latest[(r["ticker"], r["asset_name"])] = {
            **{k: r[k] for k in ("as_of", "ticker", "asset_id", "asset_name", "gate_label",
                                 "expected_date", "date_confidence", "price", "fair_value",
                                 "cohort")},
            **got,
            "gap": got["p_mkt"] - got["p_book"],
            # A gate whose date has passed is a call awaiting its answer, not a live
            # disagreement, and the row says so rather than reading as one.
            "due_passed": bool(due_date and due_date < today),
            "pos_now": r.get("pos_now"),
        }
    out = sorted(latest.values(), key=lambda x: x["gap"])
    return {
        "as_of": max((r["as_of"] for r in out), default=None),
        "min_share": min_share,
        "rows": out,
        "regimes": {k: sum(1 for r in out if r["regime"] == k) for k in REGIMES},
        "reason": None if out else "no priced gate swings a fifth of its company's value",
    }
