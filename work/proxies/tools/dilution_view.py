"""Step 8b: each cash-burning company's expected dilution, and what it does to the model's
value per share. A view: nothing here writes to the book.

The measured share growth over the next twelve months for a company with this many
months of cash (``runway_study.py``: 10%-trimmed averages of 573 company-quarters, moves
above +150% or below -50% left out as IPOs and reverse splits), less the growth of
companies with five years of cash or more, which is employee stock the model already
charges as a cost. What is left is the financing need.

New shares are taken as issued at the current share price. A raise at the market price
costs a holder value only where the model values the share above it:
v' = (v + g P) / (1 + g), for value v, price P and incremental growth g. Underwriting
discounts are not measured here and are left out rather than assumed, so this is the
least the raise costs.

    ER_TOOL_DB=<copy> python3 work/proxies/tools/dilution_view.py [--json out]
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import forecast_view  # noqa: E402
import runway  # noqa: E402

# (months from, months to, 12-month share growth, 10%-trimmed average) from runway_study.
GROWTH = ((0, 12, 0.274), (12, 18, 0.257), (18, 24, 0.182), (24, 36, 0.130),
          (36, 60, 0.103), (60, 10 ** 6, 0.075))
BASELINE = 0.075            # five years of cash or more: employee stock, already a cost


def incremental(months):
    if months is None:
        return None
    for lo, hi, g in GROWTH:
        if lo <= months < hi:
            return max(0.0, g - BASELINE)
    return None


def main(argv):
    rows = []
    for r in runway.build():
        g = incremental(r.get("runway_months"))
        verdict = forecast_view.company_verdict(None, r["ticker"]) or {}
        s = verdict.get("sotp") or {}
        v, price = s.get("equity_per_share"), s.get("close")
        adjusted = (v + g * price) / (1 + g) if None not in (v, price, g) else None
        rows.append({"ticker": r["ticker"], "months": r.get("runway_months"),
                     "funded_to_readout": r.get("funded_to_readout"), "g": g,
                     "value": v, "price": price, "adjusted": adjusted,
                     "change": (adjusted / v - 1) if adjusted and v else None})
    rows.sort(key=lambda x: (x["months"] is None, x["months"] or 0))
    print("ticker | months of cash | funded to readout | expected extra shares 12m | model value | price | after the raise | change")
    for x in rows:
        def f(v, fmt):
            return format(v, fmt) if isinstance(v, (int, float)) else "n/a"
        print(f"{x['ticker']:6s} | {f(x['months'], '.1f'):>6} | {str(x['funded_to_readout']):5s} | "
              f"{f(x['g'], '.1%'):>6} | {f(x['value'], ',.2f'):>8} | {f(x['price'], ',.2f'):>8} | "
              f"{f(x['adjusted'], ',.2f'):>8} | {f(x['change'], '+.1%')}")
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
