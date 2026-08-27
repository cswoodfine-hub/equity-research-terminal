"""The book, read back: what each position made, in its own currency and in dollars.

The table is the record of a claim. This is the arithmetic on top of it, and there is
only as much of it as the data supports.

Two returns, because they are two different questions. The local return is what the
position made in the currency it was quoted in, and it is the clean measure of the call:
a krone position that rose 10% rose 10%, whatever the dollar did. The dollar return is
what a dollar investor actually experienced, trade and currency together, and it is only
honest when each leg is converted at its own date. Converting both ends at today's rate
would rescale them identically and hand back the local return wearing a dollar sign,
which is the mistake the currency column exists to prevent rather than to commit.

The reference rates begin on 2026-07-24. A position entered before that has no honest
conversion, so it gets None and a note saying why, never today's rate standing in for a
rate nobody recorded.
"""

from __future__ import annotations

import db
import fx

# What the direction column may say. Written here rather than enforced by a constraint,
# following scenario in assumptions and status in catalysts.
DIRECTIONS = ("long", "short")


def _return(direction: str, entry, exit_) -> float | None:
    """The move, signed by which way the position was taken.

    174 in and 133 out is a loss on a long and a gain on a short, and the two prices are
    identical either way. Without the direction this is not a hard number to compute, it
    is an undefined one.
    """
    if entry in (None, 0) or exit_ is None:
        return None
    move = exit_ / entry - 1.0
    return -move if (direction or "long").lower() == "short" else move


def _converted(price, currency, on_date, db_path):
    """(usd_price, rate_date) for one leg, or (None, None) with nothing invented."""
    if price is None:
        return None, None
    currency = (currency or "USD").upper()
    if currency == "USD":
        return price, None              # no conversion happened, so no date to report
    rates = fx.rates_on(db_path, on_date or "")
    if not rates:
        return None, None
    return fx.to_usd(price, currency, rates), rates.get("as_of")


def book(db_path=None, ticker: str | None = None) -> list[dict]:
    """Every position, newest entry first, with both returns attached.

    ``ticker`` narrows to one name. An open position keeps its exit fields as None and
    reports no return, because a position that has not been closed has not made anything
    yet.
    """
    conn = db.get_connection(db_path)
    try:
        sql = "SELECT * FROM positions"
        args: tuple = ()
        if ticker:
            sql += " WHERE ticker = ?"
            args = (ticker.upper(),)
        sql += " ORDER BY entry_date DESC, id DESC"
        rows = [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()

    out = []
    for row in rows:
        currency = (row.get("currency") or "USD").upper()
        entry_usd, entry_rate = _converted(
            row.get("entry_price"), currency, row.get("entry_date"), db_path)
        exit_usd, exit_rate = _converted(
            row.get("exit_price"), currency, row.get("exit_date"), db_path)

        row["is_open"] = row.get("exit_date") is None
        row["return_pct"] = _return(row.get("direction"), row.get("entry_price"),
                                    row.get("exit_price"))
        row["entry_price_usd"] = entry_usd
        row["exit_price_usd"] = exit_usd
        row["fx_entry_rate_date"] = entry_rate
        row["fx_exit_rate_date"] = exit_rate

        if currency == "USD":
            row["return_pct_usd"] = row["return_pct"]
            row["fx_note"] = None
        elif entry_usd is not None and exit_usd is not None:
            row["return_pct_usd"] = _return(row.get("direction"), entry_usd, exit_usd)
            row["fx_note"] = (f"each leg at its own rate, {entry_rate} and {exit_rate}")
        else:
            # Named rather than approximated. A missing rate is a gap in the record, and
            # the local return is still the answer to what the call was worth.
            row["return_pct_usd"] = None
            missing = "entry" if entry_usd is None else "exit"
            row["fx_note"] = (
                f"no {currency} reference rate on or before the {missing} date;"
                f" the reference set begins 2026-07-24, so the dollar return is not"
                f" computable and the local return stands alone")
        out.append(row)
    return out
