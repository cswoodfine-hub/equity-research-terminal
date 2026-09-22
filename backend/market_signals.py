"""When a market rate has moved far enough to be worth saying, and what it did.

Three things make this different from the rest of the diff engine.

It is anchored, not a delta. Over the 275 stored DGS10 observations the median daily
move is 3bp and the largest is 14bp, so a rule comparing one refresh to the last fires
zero times in thirteen months at any bar worth having, while the series travels 104bp.
The comparison is against the level the last flag was written from, so a rate walking
3bp a day is caught once it has gone far enough, and once only.

It is rules only, and deliberately so. CLAUDE.md confines the Anthropic API to the note
step, and no model reads these values or writes these sentences: ``insights`` filters
them out of the payload the model sees and appends the composed text verbatim. FRED's
own terms restrict feeding its values into an artificial-intelligence process, and the
ICE credit index may not be furnished onward at all, so the confinement is a licence
requirement as well as a house rule.

Every per-share figure in a sentence is a rerun of the book at the anchor rate through
``tools.rate_sensitivity``, never an elasticity. The chain from a rate to equity per
share runs through the CAPM, a debt weight, a tax shield, the future pipeline and the
stub carry, and an earlier draft of this text asserted 0.9% for a credit move by
omitting the tax shield, which was wrong by half.
"""

from __future__ import annotations

import db
from fetchers import rates_fred

# Each bar is a separate signal with its own anchor. Sharing one anchor across two bars
# on the same series would let the smaller bar keep resetting it so the larger could
# never be reached.
#
# The fire counts are measured over the stored history on 2026-09-22, so each bar can
# be argued with rather than taken on faith. The day-on-day column is what a rule
# comparing consecutive refreshes would have caught: nothing, at every bar here.
#
#   series          bar   fires   day-on-day
#   DGS10           10bp     27            3
#   DGS10           25bp      8            0
#   T10YIE          10bp      8            0      (25bp fires 0 times in 276 obs)
#   BAMLC0A3CAEY    25bp      4            0      (10bp fires 21, too noisy to note)
#
# DFII10 carries no bar of its own. It is read only to split a nominal move into a real
# part and an inflation part, which is a clause inside the ten-year's sentence rather
# than an event anyone needs told separately.
SIGNALS = (
    {"series": "DGS10", "bp": 10, "leg": "risk_free", "significance": "medium",
     "change_type": "rate_move", "notes": False,
     "label": "the 10-year Treasury"},
    {"series": "DGS10", "bp": 25, "leg": "risk_free", "significance": "high",
     "change_type": "rate_move", "notes": True,
     "label": "the 10-year Treasury"},
    {"series": "T10YIE", "bp": 10, "leg": None, "significance": "low",
     "change_type": "inflation_move", "notes": False,
     "label": "10-year breakeven inflation"},
    {"series": "BAMLC0A3CAEY", "bp": 25, "leg": "cost_of_debt", "significance": "medium",
     "change_type": "credit_move", "notes": True,
     "label": "single-A corporate yields"},
)

# How far the real rate and the breakeven may miss the nominal move before the split is
# dropped. The three series publish on their own dates, so on any day the two parts can
# be measured over different windows from the whole; 2bp is the most that can be
# rounding rather than a mismatch.
DECOMPOSE_TOLERANCE_BP = 2.0


def key_of(signal: dict) -> str:
    return f"{signal['series']}:{signal['bp']}"


def anchors(conn) -> dict:
    """{signal_key: row} for every signal that has been anchored."""
    return {r["signal_key"]: dict(r) for r in conn.execute(
        "SELECT signal_key, anchor_value, anchor_as_of, armed, flagged_at"
        "  FROM market_signal_state")}


def set_anchor(conn, signal_key: str, value: float, as_of: str,
               flagged: bool = False) -> None:
    """Move a signal's anchor. ``flagged`` records that a flag was written from it."""
    conn.execute(
        """INSERT INTO market_signal_state
               (signal_key, anchor_value, anchor_as_of, armed, flagged_at)
           VALUES (?, ?, ?, 1, CASE WHEN ? THEN datetime('now') END)
           ON CONFLICT(signal_key) DO UPDATE SET
               anchor_value = excluded.anchor_value,
               anchor_as_of = excluded.anchor_as_of,
               flagged_at = COALESCE(excluded.flagged_at, market_signal_state.flagged_at)""",
        (signal_key, value, as_of, 1 if flagged else 0))


def evaluate(conn) -> list[dict]:
    """Every signal that has moved past its bar, against its own anchor.

    A signal with no anchor is baselined here and never fires on that pass: a first
    sighting is not a move, and flagging one would announce the rate the day the
    terminal was installed.

    Pure of side effects other than baselining. The caller decides whether to write the
    flags and re-anchor, so a read-only caller can ask what would fire.
    """
    latest = rates_fred.latest(None, conn=conn)
    held = anchors(conn)
    fired = []
    for signal in SIGNALS:
        now = latest.get(signal["series"]) or {}
        if now.get("value") is None or not now.get("as_of"):
            continue
        signal_key = key_of(signal)
        anchor = held.get(signal_key)
        if anchor is None:
            set_anchor(conn, signal_key, now["value"], now["as_of"])
            continue
        if not anchor["armed"]:
            continue
        # Rounded before the comparison, and to two decimals of a basis point, which
        # is far finer than FRED's own precision. Unrounded, 0.0501 less 0.0476 is
        # 24.999999999999996 and a clean 25bp move does not clear a 25bp bar.
        move_bp = round((now["value"] - anchor["anchor_value"]) * 10_000.0, 2)
        if abs(move_bp) < signal["bp"]:
            continue
        fired.append({**signal, "signal_key": signal_key,
                      "anchor_value": anchor["anchor_value"],
                      "anchor_as_of": anchor["anchor_as_of"],
                      "value": now["value"], "as_of": now["as_of"],
                      "move_bp": move_bp})
    return fired


def decompose(conn, series_from: str, series_to: str) -> dict | None:
    """Split a nominal move into the real rate and the breakeven, over the same dates.

    Returns None where either part cannot be read on both dates, or where the parts
    miss the whole by more than the tolerance. That happens often enough to matter: the
    indexed series lags two days and the breakeven is published a day after the
    nominal, so on any given refresh the three can be dated differently.
    """
    def move(series):
        first = rates_fred.rates_on(None, series_from, series, conn=conn)
        last = rates_fred.rates_on(None, series_to, series, conn=conn)
        if not first or not last or first["as_of"] == last["as_of"]:
            return None, None, None
        return ((last["value"] - first["value"]) * 10_000.0,
                first["as_of"], last["as_of"])

    nominal, _, _ = move("DGS10")
    real, real_from, real_to = move("DFII10")
    breakeven, be_from, be_to = move("T10YIE")
    if None in (nominal, real, breakeven):
        return None
    if abs((real + breakeven) - nominal) > DECOMPOSE_TOLERANCE_BP:
        return None
    return {"nominal_bp": round(nominal, 1),
            "real_bp": round(real, 1), "breakeven_bp": round(breakeven, 1),
            "real_dates": (real_from, real_to), "breakeven_dates": (be_from, be_to)}


def _opening(label: str) -> str:
    """Sentence case on the first letter only. ``capitalize`` lowercases the rest,
    which turned "the 10-year Treasury" into "The 10-year treasury"."""
    return label[:1].upper() + label[1:] if label else label


def headline(fired: dict) -> str:
    """One line for the feed, universe wide and carrying no ticker."""
    direction = "up" if fired["move_bp"] > 0 else "down"
    return (f"{_opening(fired['label'])} {fired['value'] * 100:.2f}%, "
            f"{abs(fired['move_bp']):.0f}bp {direction} on the "
            f"{fired['anchor_value'] * 100:.2f}% this book last priced against "
            f"({fired['anchor_as_of']} to {fired['as_of']})")


def _per_share(ticker: str, leg: str, move_bp: float, db_path=None) -> dict | None:
    """What the move already cost, by rebuilding the book at the anchor rate.

    The book today already carries the new rate, so the question is what it was worth
    at the old one, which is the move run backwards. Measured, never an elasticity.
    """
    try:
        from tools import rate_sensitivity
    except Exception:
        return None
    got = rate_sensitivity.measure(ticker, leg, -move_bp / 10_000.0, db_path=db_path)
    if not got.get("ok") or not got.get("moves") or got.get("moved") is None:
        return None
    before, now = got["moved"], got["base"]
    if not before:
        return None
    return {"before": before, "now": now, "change": now - before,
            "change_pct": (now - before) / before, "wacc_bp": got.get("wacc_delta"),
            "debt_weight": got.get("debt_weight"), "tax_rate": got.get("tax_rate")}


def sentence(conn, ticker: str, fired: dict, db_path=None, measured=None) -> str | None:
    """The macro paragraph for one company, composed from levels and measurements.

    Returns None for a signal that carries no consequence this company can be told,
    which is a credit move at a company with no debt weight.
    """
    if not fired.get("notes"):
        return None
    direction = "above" if fired["move_bp"] > 0 else "below"
    lead = (f"{_opening(fired['label'])} are {fired['value'] * 100:.2f}%, "
            if fired["series"] == "BAMLC0A3CAEY" else
            f"{_opening(fired['label'])} is {fired['value'] * 100:.2f}%, ")
    lead += (f"{abs(fired['move_bp']):.0f}bp {direction} the "
             f"{fired['anchor_value'] * 100:.2f}% this book last priced against.")
    parts = [lead]

    if measured is None and fired.get("leg"):
        measured = _per_share(ticker, fired["leg"], fired["move_bp"], db_path)
    if measured is None and fired["series"] == "BAMLC0A3CAEY":
        parts.append(f"{ticker} carries no debt weight, so its discount rate does "
                     "not move with credit.")
    elif measured is not None:
        verb = "falls" if measured["change"] < 0 else "rises"
        if fired["series"] == "BAMLC0A3CAEY" and measured.get("debt_weight") is not None:
            parts.append(
                f"At a debt weight of {measured['debt_weight']:.3f} and a tax rate of "
                f"{measured['tax_rate']:.1%}, that is "
                f"{abs(measured['wacc_bp'] or 0) * 10000:.1f}bp of {ticker}'s discount "
                f"rate: equity per share {verb} {abs(measured['change_pct']):.1%}, from "
                f"{measured['before']:.2f} to {measured['now']:.2f}.")
        else:
            parts.append(
                f"Carried into the risk-free rate, {ticker} equity per share {verb} "
                f"{abs(measured['change_pct']):.1%}, from {measured['before']:.2f} to "
                f"{measured['now']:.2f}.")

    if fired["series"] == "DGS10":
        split = decompose(conn, fired["anchor_as_of"], fired["as_of"])
        # The split is read from the series over the two dates; the headline states the
        # move from the anchor. They agree whenever the anchor is the level the series
        # actually held on its date, and they must, or the sentence would say 25bp and
        # then account for 34bp of it. Where they disagree the clause is dropped rather
        # than reconciled: a revised observation is not something to paper over.
        if split and abs(split["nominal_bp"] - fired["move_bp"]) > DECOMPOSE_TOLERANCE_BP:
            split = None
        if split:
            real, breakeven = abs(split["real_bp"]), abs(split["breakeven_bp"])
            # Below a basis point the split rounds to zero, and "0bp is breakeven
            # inflation" reads as a measurement rather than as nothing happening.
            if breakeven < 1:
                parts.append("All of the move is the real rate, with breakeven "
                             "inflation flat, so it is not an inflation story.")
            elif real < 1:
                parts.append("All of the move is breakeven inflation, with the real "
                             "rate flat, so it is an inflation story.")
            else:
                parts.append(
                    f"{real:.0f}bp of the move is the real rate and {breakeven:.0f}bp "
                    "is breakeven inflation, so it is "
                    + ("an inflation story." if breakeven > real
                       else "not an inflation story."))
    parts.append(f"Dates compared: {fired['anchor_as_of']} and {fired['as_of']}.")
    return " ".join(parts)


def replay(conn, series: str, field: str, anchor_value) -> dict | None:
    """A written change row, back in the shape ``sentence`` reads.

    A note is composed after the diff has already re-anchored, so asking ``evaluate``
    again would find nothing moved and say nothing. The row carries the anchor and the
    date it was struck, and the current level is read live, so the sentence restates
    the move that was actually flagged rather than whatever is true this second.
    """
    signal = next((s for s in SIGNALS if s["series"] == series and s["notes"]), None)
    if signal is None or anchor_value is None:
        return None
    try:
        anchor = float(anchor_value)
    except (TypeError, ValueError):
        return None
    as_of = (field or "").split("@", 1)[1] if "@" in (field or "") else None
    now = rates_fred.latest(None, series, conn=conn)
    if not as_of or not now or now.get("value") is None:
        return None
    return {**signal, "signal_key": key_of(signal), "anchor_value": anchor,
            "anchor_as_of": as_of, "value": now["value"], "as_of": now["as_of"],
            "move_bp": round((now["value"] - anchor) * 10_000.0, 2)}


def notes_from(items: list[dict], ticker: str, db_path=None,
               limit: int = 1) -> list[str]:
    """The macro paragraphs for one company, from the market changes already flagged.

    Capped, so a refresh that trips several bars at once does not bury the company's
    own news under a wall of rate arithmetic. Ranked by the size of the move, since
    that is what the per-share consequence tracks.
    """
    rows = [it for it in items if it.get("kind") == "market" and it.get("anchor_value")]
    if not rows:
        return []
    ticker = ticker.upper()
    conn = db.get_connection(db_path)
    try:
        # Ranked on what the move is worth to this company, not on how many basis
        # points it is. A 35bp credit move and a 34bp rate move look the same in the
        # feed and are not: on Pfizer the rate move is 4.2% of equity per share and
        # the credit move 1.6%, and on Lilly the credit move is 0.2%. Measuring both
        # to rank them costs a book rerun each, which is affordable because these bars
        # trip a handful of times a year.
        scored = []
        for item in rows:
            signal = replay(conn, item["series"], item.get("field"),
                            item["anchor_value"])
            if signal is None:
                continue
            measured = (_per_share(ticker, signal["leg"], signal["move_bp"], db_path)
                        if signal.get("leg") else None)
            text = sentence(conn, ticker, signal, db_path, measured=measured)
            if text:
                scored.append((abs((measured or {}).get("change_pct") or 0.0), text))
        return [text for _weight, text in sorted(scored, key=lambda x: -x[0])][:limit]
    finally:
        conn.close()


def notes_for(ticker: str, db_path=None, limit: int = 1) -> list[str]:
    """The macro paragraphs this company should carry, largest effect first.

    Capped so a refresh that fires several bars at once does not bury the company's own
    news under a wall of rate arithmetic. Read-only: it does not re-anchor, because the
    diff engine owns that and a note must not silence the next refresh's flag.
    """
    conn = db.get_connection(db_path)
    try:
        fired = [f for f in evaluate(conn) if f.get("notes")]
        conn.commit()               # a first sighting baselines, even on a read
        said = []
        for signal in sorted(fired, key=lambda f: -abs(f["move_bp"])):
            text = sentence(conn, ticker.upper(), signal, db_path)
            if text:
                said.append(text)
        return said[:limit]
    finally:
        conn.close()
