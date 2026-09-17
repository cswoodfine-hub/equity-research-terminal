"""Take working capital build out of each company's other-costs charge.

Each company's ``other_costs_pct`` is solved so its book reproduces the free cash flow it
earned over a window (``interest_addback.WINDOWS``). A company growing fast ties cash up
in receivables and inventories as it grows, and that cash sits outside free cash flow for
as long as the growth lasts. Lilly's operating cash flow over 2018 to 2025 carried $7.6bn
of it, and Novo's over 2023 to 2025 DKK 30.4bn. Charging it on every product for ever
reads a growth phase as a cost of selling medicine, and the product forecasts carry the
growth separately.

The build is read off the cash flow statement: the changes in receivables, inventories
and payables as the filer presents them (``statements`` lines ``ReceivablesCashEffect``,
``InventoriesCashEffect``, and ``PayablesCashEffect`` or, where a filer tags payables only
with accrued liabilities, ``PayablesAccruedCashEffect``). The balance sheet would also move with
what an acquisition brought and with currency translation, neither of which is operating
cash. The cash flow lines have a bias of their own, in one direction: an acquirer's
inventory line also adds back the unwinding of the fair-value step-up on inventory it
bought, a non-cash cost, so the build it shows is understated and the cut is cautious.
The row names the payables line it read.

The charge was solved as other = book pre-tax margin - FCF margin / (1 - tax). Adding the
build back lifts the FCF margin by the build over revenue, which lowers the charge by that
over one minus tax. It runs both ways: a company whose working capital shrank was
flattered by the window, and its charge rises. The charge can fall to the floor the
amortisation inside its cost lines sets (``charge_floor``), and no further. A charge held
at nil or at that floor moves from its rebuilt figure, not from where it was held.
"""

from __future__ import annotations

import interest_addback as IA
import replacement_capex as RC

MARKER = "without working capital build"
LINES = (("ReceivablesCashEffect", "receivables"), ("InventoriesCashEffect", "inventories"))
PAYABLES = (("PayablesCashEffect", "payables"),
            ("PayablesAccruedCashEffect", "payables and accrued liabilities"))


def measure(conn, ticker: str) -> dict:
    """The working capital build over the company's window, as a share of revenue, and
    the cut to the charge. ``cut`` is None, with ``reason``, wherever a line is missing
    for a year of the window."""
    ticker = ticker.upper()
    window = IA.WINDOWS.get(ticker)
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if not window or company is None:
        return {"ticker": ticker, "cut": None, "reason": "no calibration window on file"}
    first, last = window
    cid = company["id"]
    years = set(range(first, last + 1))
    base = {"ticker": ticker, "first": first, "last": last}
    revenue = IA.fy_series(conn, cid, "Revenues", first, last)
    if set(revenue) != years:
        return {**base, "cut": None, "reason": "revenue is not on file for every year"}
    effects, units = {}, {r["unit"] for r in revenue.values()}
    for metric, name in LINES:
        series = IA.fy_series(conn, cid, metric, first, last)
        if set(series) != years:
            return {**base, "cut": None,
                    "reason": f"no change in {name} on file from the cash flow statement "
                              "for every year"}
        effects[name] = sum(r["value"] for r in series.values())
        units |= {r["unit"] for r in series.values()}
    payables_as = None
    for metric, name in PAYABLES:
        series = IA.fy_series(conn, cid, metric, first, last)
        if set(series) == years:
            effects["payables"] = sum(r["value"] for r in series.values())
            units |= {r["unit"] for r in series.values()}
            payables_as = name
            break
    if payables_as is None:
        return {**base, "cut": None,
                "reason": "no change in payables on file from the cash flow statement for "
                          "every year"}
    if len(units) != 1:
        return {**base, "cut": None, "reason": "working capital and revenue in different units"}
    tax = RC._tax(conn, cid)
    if tax is None or tax >= 1:
        return {**base, "cut": None, "reason": "no tax rate on file"}
    build = -sum(effects.values())
    total = sum(r["value"] for r in revenue.values())
    share = build / total
    return {**base, "cut": share / (1.0 - tax), "share": share, "build": build,
            "effects": effects, "payables_as": payables_as,
            "revenue": total, "tax": tax, "unit": next(iter(units)), "reason": None}


def charge(old: float, m: dict, rebuilt: float | None = None, bound: float = 0.0) -> float:
    """The restated charge. ``bound`` is the amortisation floor, or nil where the filer
    states none. A row held at nil or at that floor, above what the filed figures rebuild
    it at (``rebuilt``), moves from the rebuilt figure, since the cut may not lift it off
    the floor. Every other row moves from its own value: Merck's charge was solved on its
    modelled book, which the filed ratios do not rebuild."""
    if m.get("cut") is None:
        return old
    start = rebuilt if _held(old, rebuilt, bound) else old
    return max(min(bound, old), start - m["cut"])


def _held(old: float, rebuilt: float | None, bound: float) -> bool:
    return (rebuilt is not None and rebuilt < old
            and (abs(old) < 1e-9 or abs(old - bound) < 1e-6))


def clause(m: dict, old: float, new: float, who: str, held_from: float | None = None) -> str:
    if m.get("cut") is None:
        return f" Checked {MARKER}: {m['reason']}, so the charge stands."
    span = f"{m['first']}" if m["first"] == m["last"] else f"{m['first']} to {m['last']}"
    unit = m["unit"]
    parts = []
    for name in ("receivables", "inventories", "payables"):
        effect = m["effects"][name]
        label = m["payables_as"] if name == "payables" else name
        grew = effect > 0 if name == "payables" else effect < 0
        parts.append(f"{label} {'up' if grew else 'down'} {IA._money(abs(effect), unit)}")
    grew = m["build"] >= 0
    lead = (f" Restated {MARKER}: over {span} {who}'s cash flow statement shows "
            + ", ".join(parts) + ", a working capital "
            + (f"build of {IA._money(m['build'], unit)}" if grew
               else f"release of {IA._money(-m['build'], unit)}")
            + f", {abs(m['share']):.2%} of revenue. "
            + ("Growth ties that cash up once, not on every product for ever, so the charge "
               if grew else
               "A release flatters the window once and does not recur, so the charge "))
    if held_from is not None:
        where = "nil" if abs(old) < 1e-9 else f"the amortisation floor, {old:.2%}"
        lead += f"was held at {where} where the filed figures rebuild it at {held_from:.2%}, and "
        if abs(new - old) < 5e-5:
            return lead + "stays there."
        return lead + f"moves from that rebuilt figure to {new:.2%}."
    if abs(new - old) < 5e-5:
        return lead + f"stays at {old:.2%}."
    return lead + f"{'falls' if new < old else 'rises'} from {old:.2%} to {new:.2%}."


def restate_row(row: dict, m: dict, who: str, rebuilt: float | None = None,
                bound: float = 0.0) -> dict | None:
    source = row.get("source") or ""
    if MARKER in source:
        return None
    old = float(row["value"])
    new = charge(old, m, rebuilt, bound)
    held_from = rebuilt if m.get("cut") is not None and _held(old, rebuilt, bound) else None
    return {**row, "value": new,
            "source": source.rstrip(". ") + "." + clause(m, old, new, who, held_from)}
