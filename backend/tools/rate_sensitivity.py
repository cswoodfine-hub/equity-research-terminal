"""What a move in each rate is worth, per company, measured rather than derived.

Every sentence the terminal writes about a rate has to name a number: how much a
company is worth less if the ten-year rises 25bp, what a point of credit spread does
to a levered filer. Those numbers are easy to get wrong from an elasticity, because
the chain from a market rate to equity per share runs through the CAPM, a debt weight,
a tax shield, the future pipeline and the stub carry, and two of those legs were
themselves wrong until recently.

So nothing derives them. This reruns the book at the moved rate and reads the answer
off the model, and any note quoting a per-share figure cites this script and the day
it was run.

Read-only. It opens the database, values each company twice and prints. It writes
nothing, and it is not imported by the app.

    python tools/rate_sensitivity.py                  # every covered company, 25bp
    python tools/rate_sensitivity.py --bp 100 LLY ABBV
    python tools/rate_sensitivity.py --csv > /tmp/sensitivity.csv

Three legs are measured separately, because they reach different companies:

  risk-free    every company, through the cost of equity on every product.
  credit       only the levered, and through the tax shield: d(wacc)/d(cost_of_debt)
               is debt_weight x (1 - tax_rate), not debt_weight. Six covered
               companies carry no debt weight and do not move at all.
  premium      every company, through beta x erp. Moved here as the premium itself,
               so a company with a beta under one moves less than the shock.

The moved rate is pushed in through ``assumptions.load``'s scalars for each product,
the same path the engine reads, and the book is rebuilt through the break-points
engine so the future pipeline and the growth charge are rebuilt with it.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import env  # noqa: F401,E402  loads .env before any module reads it
import breakpoints  # noqa: E402
import db  # noqa: E402
import forecast  # noqa: E402

LEGS = ("risk_free", "cost_of_debt", "erp")
DEFAULT_BP = 25


def _covered(db_path=None) -> list[str]:
    conn = db.get_connection(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT ticker FROM companies ORDER BY ticker")]
    finally:
        conn.close()


def _moved(scalars: dict, leg: str, delta: float) -> dict:
    """The scalars with one CAPM leg moved and the WACC re-derived from them.

    A stated ``wacc`` beats the components in ``forecast.wacc``, so it is dropped
    first. Leaving it in place would move the leg and change nothing, which is the
    quiet failure this whole script exists to avoid.
    """
    out = {k: v for k, v in scalars.items() if k != "wacc"}
    if out.get(leg) is None:
        return {}                       # this product cannot answer for this leg
    out[leg] = out[leg] + delta
    rate, _basis = forecast.wacc(out)
    if rate is None:
        return {}
    return out


def measure(ticker: str, leg: str, delta: float, db_path=None) -> dict:
    """{base, moved, change, change_pct, wacc_delta, ...} for one company and leg."""
    book = breakpoints.Book(db_path, ticker)
    if book.verdict is None:
        return {"ticker": ticker, "ok": False, "reason": "not a covered company"}
    if not book.ok:
        return {"ticker": ticker, "ok": False, "reason": book.reason}

    seen = {"waccs": [], "weights": [], "debt_weight": None, "tax_rate": None,
            "moved_any": False}

    def asset_trial(part, inputs):
        scalars = (inputs or {}).get("scalars") or {}
        before, _ = forecast.wacc(scalars)
        out = _moved(scalars, leg, delta)
        if not out:
            return None                 # left as it is, and counted as not moving
        after, _ = forecast.wacc(out)
        if before is not None and after is not None:
            seen["waccs"].append(after - before)
            seen["weights"].append(abs(part.get("rnpv_share") or 0.0))
        seen["moved_any"] = True
        if seen["debt_weight"] is None:
            seen["debt_weight"] = scalars.get("debt_weight")
            seen["tax_rate"] = scalars.get("tax_rate")
        return {**inputs, "scalars": out}

    def line_trial(part, scalars):
        out = _moved(scalars or {}, leg, delta)
        return out or None

    moved = book.equity_with(asset_trial, line_trial)
    total = sum(seen["weights"])
    wacc_delta = (sum(w * d for w, d in zip(seen["weights"], seen["waccs"])) / total
                  if total else None)
    return {"ticker": ticker, "ok": True, "leg": leg, "delta": delta,
            "base": book.equity, "moved": moved,
            "change": moved - book.equity,
            "change_pct": (moved - book.equity) / book.equity if book.equity else None,
            "wacc_delta": wacc_delta, "moves": seen["moved_any"],
            "debt_weight": seen["debt_weight"], "tax_rate": seen["tax_rate"],
            "close": book.close}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tickers", nargs="*", help="default: every covered company")
    ap.add_argument("--bp", type=float, default=DEFAULT_BP,
                    help=f"size of the move in basis points (default {DEFAULT_BP})")
    ap.add_argument("--legs", default=",".join(LEGS),
                    help=f"comma separated, from {','.join(LEGS)}")
    ap.add_argument("--csv", action="store_true", help="machine readable")
    args = ap.parse_args(argv)

    delta = args.bp / 10_000.0
    tickers = [t.upper() for t in args.tickers] or _covered()
    legs = [l.strip() for l in args.legs.split(",") if l.strip() in LEGS]

    rows = []
    for leg in legs:
        for ticker in tickers:
            rows.append(measure(ticker, leg, delta))

    if args.csv:
        import csv as _csv
        writer = _csv.writer(sys.stdout)
        writer.writerow(["leg", "bp", "ticker", "base_per_share", "moved_per_share",
                         "change_per_share", "change_pct", "wacc_delta_bp",
                         "debt_weight", "tax_rate", "reason"])
        for r in rows:
            writer.writerow([
                r.get("leg", ""), args.bp, r["ticker"],
                f"{r['base']:.4f}" if r.get("base") is not None else "",
                f"{r['moved']:.4f}" if r.get("moved") is not None else "",
                f"{r['change']:.4f}" if r.get("change") is not None else "",
                f"{r['change_pct']:.6f}" if r.get("change_pct") is not None else "",
                f"{r['wacc_delta'] * 10000:.2f}" if r.get("wacc_delta") else "",
                r.get("debt_weight") if r.get("debt_weight") is not None else "",
                r.get("tax_rate") if r.get("tax_rate") is not None else "",
                r.get("reason") or ("no component on file" if r.get("ok")
                                    and not r.get("moves") else "")])
        return 0

    for leg in legs:
        mine = [r for r in rows if r.get("leg") == leg]
        print(f"\n{leg} +{args.bp:g}bp")
        print(f"{'':6} {'base/sh':>10} {'moved/sh':>10} {'change':>9} {'pct':>8} "
              f"{'wacc bp':>8}  note")
        moved = [r for r in mine if r.get("ok") and r.get("moves")]
        for r in sorted(mine, key=lambda x: (not x.get("moves", False), x["ticker"])):
            if not r.get("ok"):
                print(f"{r['ticker']:6} {'':10} {'':10} {'':9} {'':8} {'':8}  "
                      f"{r['reason']}")
                continue
            if not r.get("moves"):
                print(f"{r['ticker']:6} {r['base']:10.2f} {'':10} {'':9} {'':8} "
                      f"{'':8}  no {leg} on file, does not move")
                continue
            note = ""
            if leg == "cost_of_debt":
                note = (f"debt weight {r['debt_weight']:.3f}, tax {r['tax_rate']:.3f}"
                        if r.get("debt_weight") is not None else "")
            print(f"{r['ticker']:6} {r['base']:10.2f} {r['moved']:10.2f} "
                  f"{r['change']:9.2f} {r['change_pct'] * 100:7.2f}% "
                  f"{(r['wacc_delta'] or 0) * 10000:8.2f}  {note}")
        if moved:
            pcts = sorted(r["change_pct"] for r in moved)
            mid = pcts[len(pcts) // 2]
            print(f"{'':6} {len(moved)} of {len(mine)} move; median "
                  f"{mid * 100:.2f}%, range {pcts[0] * 100:.2f}% to "
                  f"{pcts[-1] * 100:.2f}%")
    print("\nEvery figure above is a rerun of the book, not an elasticity. Cite this "
          "script and the day it was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
