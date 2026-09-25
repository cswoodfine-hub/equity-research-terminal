"""Take the cost of debt out of each company's other-costs charge, where it was in twice.

Each company's ``other_costs_pct`` was solved so its modelled book reproduces the
free-cash margin the company actually earned over a window. Free cash flow is struck
after interest wherever interest paid sits inside operating cash flow, which it always
does under US GAAP and does under IFRS for filers that choose it. The engine values cash
before financing and the sum of the parts then subtracts net debt, so a charge calibrated
to cash after interest took the cost of the debt off a second time. Pfizer's $8.2bn of
interest over 2023 to 2025 was 4.4 points of a 22.2% charge.

The charge was solved as other = book pre-tax margin - FCF margin / (1 - tax). Adding
back interest net of tax lifts the FCF margin by I(1 - t)/R, which lowers the charge by
exactly I/R. So every row falls by interest paid over revenue across the company's own
window, and nothing else about the calibration moves: Lilly keeps its eight years,
Vertex its five. A charge cannot fall below nil.

A filer that books interest under financing (GSK) has cash already struck before
interest, and its charge stands. So does one with no interest on file for the window.
"""

from __future__ import annotations

import csv
import io
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# Each company's calibration window, as its seed source states it.
WINDOWS = {
    "ABBV": (2025, 2025),     # "in FY2025"
    "AMGN": (2023, 2025), "AZN": (2023, 2025), "BIIB": (2023, 2025),
    "BMY": (2023, 2025), "GILD": (2023, 2025), "GSK": (2023, 2025),
    "INCY": (2023, 2025), "JNJ": (2023, 2025), "MRK": (2023, 2025),
    "NVO": (2023, 2025), "NVS": (2023, 2025), "PFE": (2023, 2025),
    "REGN": (2023, 2025), "SNY": (2023, 2025), "UTHR": (2023, 2025),
    "LLY": (2018, 2025),      # "over 2018 to 2025", the capacity build-out note
    "VRTX": (2021, 2025),     # "over the five years to 2025", the Alpine note
    "EXEL": (2023, 2025),     # a block built from its own filed lines, 2026-09-24
    "ARGX": (2025, 2025),     # its first full year of profit; 2023 and 2024 were the turn
    "NBIX": (2023, 2025),     # a block built from its own filed lines, 2026-09-24
    "ALNY": (2025, 2025),     # its first year of profit; 2023 and 2024 were the turn
}
# A charge borrowed from another company follows that company's.
COMPARATORS = {"VKTX": "LLY", "GPCR": "LLY", "DYN": "ALNY", "CAPR": "ALNY", "NTLA": "ALNY",
               "VOR": "ARGX", "RVMD": "EXEL", "IONS": "ALNY", "AXSM": "NBIX",
               "ARWR": "ALNY", "SRPT": "ALNY", "TSHA": "ALNY"}
MARKER = "before interest"


def fy_series(conn, company_id: int, metric: str, first: int, last: int) -> dict:
    """{fiscal_year: row} with one row per year, the latest-dated. A 52 or 53 week filer
    can carry two rows labelled the same fiscal year: Johnson & Johnson's FY2023 is on
    file ending both 2023-12-31 and 2024-01-01, and summing both read its revenue over
    2023 to 2025 as $348bn rather than $263bn."""
    rows = conn.execute(
        """SELECT fiscal_year, value, unit, period_end FROM financials
            WHERE company_id = ? AND metric = ? AND period_type = 'FY'
              AND fiscal_year BETWEEN ? AND ? AND value IS NOT NULL
            ORDER BY fiscal_year, period_end""", (company_id, metric, first, last))
    out = {}
    for row in rows:
        out[row["fiscal_year"]] = row
    return out


def _fy_sum(conn, company_id: int, metric: str, first: int, last: int):
    series = fy_series(conn, company_id, metric, first, last)
    return (sum(r["value"] for r in series.values()), set(series),
            {r["unit"] for r in series.values()})


def measure(conn, ticker: str) -> dict:
    """Interest paid inside operating cash flow over the company's window, as a share of
    its revenue over the same years. ``share`` is None, with ``reason``, wherever the
    add-back does not apply or cannot be computed."""
    ticker = ticker.upper()
    window = WINDOWS.get(ticker)
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if not window or company is None:
        return {"ticker": ticker, "share": None, "reason": "no calibration window on file"}
    first, last = window
    wanted = set(range(first, last + 1))
    interest, i_years, i_units = _fy_sum(conn, company["id"], "InterestPaidOperating",
                                         first, last)
    revenue, r_years, r_units = _fy_sum(conn, company["id"], "Revenues", first, last)
    financing, f_years, _ = _fy_sum(conn, company["id"], "InterestPaidFinancing", first, last)
    base = {"ticker": ticker, "first": first, "last": last}
    if f_years and not i_years:
        return {**base, "share": None, "booked": "financing",
                "reason": "interest paid is booked under financing, so free cash flow is "
                          "already struck before interest"}
    if i_years != wanted:
        return {**base, "share": None, "booked": None,
                "reason": "no interest paid on file for every year of the window"}
    if r_years != wanted or not revenue:
        return {**base, "share": None, "reason": "revenue not on file for every year"}
    if len(i_units | r_units) != 1:
        return {**base, "share": None, "reason": "interest and revenue in different units"}
    return {**base, "share": interest / revenue, "interest": interest, "revenue": revenue,
            "unit": next(iter(i_units)), "booked": "operating", "reason": None}


def revised(old: float, share: float | None) -> float:
    return old if share is None else max(0.0, old - share)


def _money(value: float, unit: str) -> str:
    return (f"${value / 1e6:,.0f}mm" if unit == "USD"
            else f"{value / 1e6:,.0f}mm {unit}")


def clause(m: dict, old: float, new: float, company_name: str = "") -> str:
    """The sentence appended to a row's source, saying what was checked and done."""
    who = company_name or m["ticker"]
    if m.get("share") is None:
        return f" Checked {MARKER}: {m['reason']}, so the charge stands."
    span = (f"{m['first']}" if m["first"] == m["last"] else f"{m['first']} to {m['last']}")
    lead = (f" Restated {MARKER}: {who} paid {_money(m['interest'], m['unit'])} of "
            f"interest inside operating cash flow over {span}, {m['share']:.2%} of "
            f"revenue. The free cash flow above is struck after it and the valuation "
            f"already charges the debt by subtracting net debt")
    if old <= 0 or new == old:
        return lead + ", so adding it back only widens a gap the filed lines already leave, and the charge stays nil."
    return lead + f", so the charge falls by that much, from {old:.2%} to {new:.2%}."


def restate_row(row: dict, m: dict, company_name: str = "") -> dict | None:
    """The row with its value and source restated, or None when already done."""
    source = row.get("source") or ""
    if MARKER in source:
        return None
    old = float(row["value"])
    new = revised(old, m.get("share"))
    return {**row, "value": new, "source": source.rstrip(". ") + "." + clause(m, old, new, company_name)}


def rewrite_csv(path: pathlib.Path, restate, key: str = "other_costs_pct") -> int:
    """Rewrite only the ``key`` lines of a seed file (the other_costs_pct charge unless
    told otherwise), leaving every other line, comment and quoting exactly as it was.
    ``restate(fields)`` returns the new fields dict or None. Returns lines changed."""
    # Read and written without newline translation: the seed files carry CRLF endings,
    # and a text-mode round trip rewrote every line of every file to change 331.
    with path.open(encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines(keepends=True)
    header = None
    changed = 0
    out = []
    for line in lines:
        if line.lstrip().startswith("#") or not line.strip():
            out.append(line)
            continue
        cells = next(csv.reader([line]))
        if header is None:
            header = cells
            out.append(line)
            continue
        fields = dict(zip(header, cells))
        if fields.get("key") != key:
            out.append(line)
            continue
        new = restate(fields)
        if new is None:
            out.append(line)
            continue
        new["value"] = f"{float(new['value']):.6f}".rstrip("0").rstrip(".") or "0"
        buf = io.StringIO()
        csv.writer(buf, lineterminator="").writerow([new.get(h, "") for h in header])
        ending = line[len(line.rstrip("\r\n")):]
        out.append(buf.getvalue() + ending)
        changed += 1
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("".join(out))
    return changed
