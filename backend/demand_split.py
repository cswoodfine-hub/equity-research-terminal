"""Medicare growth split: each brand's Medicare spend growth into patients, use per
patient and price (docs/design/medicare-demand-split.md).

The identity. CMS Spending by Drug gives, per drug and year, total spending S, claims C
and distinct beneficiaries B. Spending is exactly

    S = B x (C / B) x (S / C)

so a year's change multiplies through the same three factors:

    1 + spend = (1 + patients) x (1 + use per patient) x (1 + cost per claim)

with patients = B1/B0 - 1, use per patient = (C1/B1)/(C0/B0) - 1 and cost per claim =
(S1/C1)/(S0/C0) - 1. Nothing is estimated; every factor is a ratio of two published
counts, and the product of the factors is the spend change to rounding. Each factor is
also given in points of spend growth by its log share, pts_f = g ln(1+f) / ln(1+g), and
because the logs of the factors add to the log of the whole, the points add exactly to g.

What a claim is differs by part, in CMS's own data dictionary: in Part D a claim is a
prescription fill, original or refill, so the middle factor is fills per patient and the
last is cost per fill. In Part B it is a claim for the drug, so the factors are claims
per patient and cost per claim. A cross-check splits cost per claim into units per claim
and cost per unit, which shows a move from 30-day to 90-day fills in Part D and a dose
change in Part B.

Medicare only, and never the US market: Medicaid and commercial payers are absent.
Part D spending is gross drug cost, including what the plan and the patient paid,
before manufacturer rebates and other price concessions, which CMS is prohibited from
disclosing. Part B covers fee-for-service beneficiaries only (Medicare Advantage is out)
and is the full value of the product paid, Medicare's payment plus the patient's
deductible and coinsurance, most of it set at average sales price plus 6%. A
beneficiary is a distinct patient on the drug during the year, so patient growth is net
additions, never new starts.

This module is a read-only lens. It writes nothing and moves no assumption, rNPV or
rating; a direction that disagrees with the model is a flag, never an edit.
"""

from __future__ import annotations

import math
import re
import statistics

import db

# A part carrying less than this share of a brand's latest Medicare spend is reported,
# not split: the factors of a $2mm Part D sliver of a Part B drug are noise beside the
# brand, and a reader adds nothing by reading them.
MATERIAL_PART_SHARE = 0.05
# Units per claim moving more than about 5% in a year (in log terms) means the fill or
# the dose changed, so cost per claim is no longer a like-for-like price and the reader
# is pointed at cost per unit. Eliquis moved 1.3% in 2024 and is under it.
FILL_SIZE_FLAG = 0.05
# Growth inside one point either way is read as flat when comparing directions, so a
# +0.4% patient year does not disagree with a -0.2% model.
DIRECTION_DEADBAND = 0.01
# Below this |ln(1+g)| a year is flat and the log-share rule would divide by nothing,
# so each factor's points are its own log instead.
_FLAT = 1e-12


# --- the identity, pure ---------------------------------------------------------------
def _pos(value) -> float | None:
    """A count or amount that can be divided by: present and above nil."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _ratio(num, den) -> float | None:
    num, den = _pos(num), _pos(den)
    return num / den if num is not None and den is not None else None


def _change(new, old) -> float | None:
    new, old = _pos(new), _pos(old)
    return new / old - 1.0 if new is not None and old is not None else None


def step(prev: dict, cur: dict) -> dict:
    """The change from one year to the next, each factor a fraction or None.

    Each argument is {year, spending, claims, beneficiaries, units}. A missing or nil
    count gives None for every factor that needs it, never a zero: a suppressed
    beneficiary count leaves claims and price present and patients and use per patient
    None.
    """
    s0, s1 = prev.get("spending"), cur.get("spending")
    c0, c1 = prev.get("claims"), cur.get("claims")
    b0, b1 = prev.get("beneficiaries"), cur.get("beneficiaries")
    u0, u1 = prev.get("units"), cur.get("units")
    return {
        "from": prev.get("year"), "to": cur.get("year"),
        "spend": _change(s1, s0),
        "claims": _change(c1, c0),
        "patients": _change(b1, b0),
        "intensity": _change(_ratio(c1, b1), _ratio(c0, b0)),
        "price": _change(_ratio(s1, c1), _ratio(s0, c0)),
        "units_per_claim": _change(_ratio(u1, c1), _ratio(u0, c0)),
        "price_per_unit": _change(_ratio(s1, u1), _ratio(s0, u0)),
    }


def factors_of(st: dict) -> tuple | None:
    """The factors a step splits into: three where both patient counts are on file,
    claims and price where they are not, None where even that cannot be split."""
    if all(st.get(k) is not None for k in ("patients", "intensity", "price")):
        return ("patients", "intensity", "price")
    if all(st.get(k) is not None for k in ("claims", "price")):
        return ("claims", "price")
    return None


def points(st: dict) -> dict | None:
    """Each factor in points of spend growth, as fractions that add to ``spend``.

    pts_f = g ln(1+f) / ln(1+g). A flat year (|ln(1+g)| under 1e-12) takes each
    factor's own log instead, so it still splits rather than dividing by nothing.
    """
    g = st.get("spend")
    names = factors_of(st)
    if g is None or names is None or g <= -1.0:
        return None
    if any(st[k] <= -1.0 for k in names):
        return None
    whole = math.log1p(g)
    if abs(whole) < _FLAT:
        return {k: math.log1p(st[k]) for k in names}
    return {k: g * math.log1p(st[k]) / whole for k in names}


_SPAN_KEYS = ("spend", "claims", "patients", "intensity", "price", "units_per_claim",
              "price_per_unit")


def span(series: list, start: int, end: int) -> dict | None:
    """Compound annual growth per factor from ``start`` to ``end``, read on the end
    years only, with the same points rule. The CAGRs multiply exactly as the yearly
    factors do, since an nth root of a product is the product of the nth roots. None
    when either end year is missing or the span is under one year."""
    by_year = {r.get("year"): r for r in series}
    if start not in by_year or end not in by_year or end <= start:
        return None
    n = end - start
    whole = step(by_year[start], by_year[end])
    cagr = {k: ((1.0 + whole[k]) ** (1.0 / n) - 1.0) if whole[k] is not None
            and whole[k] > -1.0 else None for k in _SPAN_KEYS}
    out = {"from": start, "to": end, "years": n, **cagr}
    out["points"] = points(out)
    return out


def combine(parts: list) -> dict | None:
    """A brand's growth across two Medicare parts, in points only.

    Each part is {part, prior_spend, step}. The weights are the prior year's spend, so
    sum w_p g_p is the brand's total spend growth exactly. Factor points are the
    weighted sum of each part's own points. There is no combined patient count: a
    patient can be in both parts, and adding the two counts would count them twice.
    """
    usable = [p for p in parts if _pos(p.get("prior_spend")) is not None
              and (p.get("step") or {}).get("spend") is not None]
    if not usable:
        return None
    total = sum(p["prior_spend"] for p in usable)
    by_part, factor_pts, growth = {}, {}, 0.0
    for p in usable:
        w = p["prior_spend"] / total
        g = p["step"]["spend"]
        growth += w * g
        by_part[p["part"]] = w * g
        own = points(p["step"])
        if own is None:
            # A part that cannot be split still carries its growth, as its own share.
            factor_pts["unsplit"] = factor_pts.get("unsplit", 0.0) + w * g
            continue
        for k, v in own.items():
            factor_pts[k] = factor_pts.get(k, 0.0) + w * v
    return {"spend": growth, "by_part": by_part, "points": factor_pts,
            "weights": {p["part"]: p["prior_spend"] / total for p in usable}}


# --- labels ---------------------------------------------------------------------------
PART_LABEL = {"D": "Part D, retail pharmacy", "B": "Part B, clinic"}
SOURCE_FILE = {"D": "CMS Medicare Part D Spending by Drug",
               "B": "CMS Medicare Part B Spending by Drug"}
# The names a reader sees for each factor. A Part D claim is a prescription fill, original
# or refill (CMS data dictionary, Tot_Clms); a Part B claim is a claim for the drug and
# CMS does not say it is one administration, so it is called a claim.
FACTOR_LABELS = {
    "D": {"spend": "Spend", "patients": "Patients", "intensity": "Fills per patient",
          "price": "Cost per fill", "claims": "Fills", "units_per_claim": "Units per fill",
          "price_per_unit": "Cost per unit"},
    "B": {"spend": "Spend", "patients": "Patients", "intensity": "Claims per patient",
          "price": "Cost per claim", "claims": "Claims",
          "units_per_claim": "Units per claim", "price_per_unit": "Cost per unit"},
}
# Every clause is in CMS's own methodology or data dictionary: Part D spending is gross
# drug cost without manufacturer rebates or other price concessions (Part D methodology,
# 2026-06); Part B counts fee-for-service beneficiaries only and most of its payments
# are based on average sales price with the statutory 6 percent add-on (Part B
# methodology and dictionary).
LABEL = ("Medicare only. Part D is gross cost before manufacturer rebates; Part B is "
         "fee-for-service only, paid mostly at average sales price plus 6%.")
PATIENTS_NOTE = ("Patients are distinct beneficiaries on the drug during the year, so "
                 "their growth is net additions, not new starts.")
GAP_LABEL = ("not explained by Medicare gross spend: net price, other payers, "
             "inventory")


def label(latest_year: int | None, latest_fy: int | None) -> str:
    """The label line, with the lag between the CMS year and the latest filing."""
    if latest_year is None:
        return LABEL
    tail = f" CMS calendar {latest_year}"
    if latest_fy is not None:
        lag = latest_fy - latest_year
        if lag > 0:
            tail += (f", {lag} year{'s' if lag != 1 else ''} behind the FY{latest_fy} "
                     "filing")
        elif lag == 0:
            tail += f", the same year as the FY{latest_fy} filing"
    return LABEL + tail + "."


# --- series and flags -----------------------------------------------------------------
_PRESENTATIONS = re.compile(r"\((\d+) presentations\)")
_CONTAINER_NAMES = re.compile(
    r"summed over the presentations CMS lists separately: (.*?)\. Beneficiaries are the "
    r"sum", re.S)


def _row(row) -> dict:
    """One drug_demand row as the split reads it, with what its name and source say
    about how CMS built it."""
    name = row["brand_name"] or ""
    source = row["source"] or ""
    counted = _PRESENTATIONS.search(name)
    listed = _CONTAINER_NAMES.search(source)
    names = ([n.strip() for n in listed.group(1).split(", ") if n.strip()]
             if listed else [name])
    return {"year": row["year"], "spending": row["total_spending"],
            "claims": row["total_claims"], "beneficiaries": row["total_beneficiaries"],
            "units": row["total_dosage_units"], "cms_name": name,
            "presentations": int(counted.group(1)) if counted else 1,
            "names": names,
            "starred": "*" in name or any("*" in n for n in names),
            "partial_suppression": "suppressed" in source}


def _series(conn, asset_id: int) -> dict:
    """{part: [rows ordered by year]} for one asset, from drug_demand."""
    out: dict = {}
    for r in conn.execute(
            "SELECT part, year, brand_name, total_spending, total_claims,"
            "       total_beneficiaries, total_dosage_units, source"
            "  FROM drug_demand WHERE asset_id = ? AND total_spending IS NOT NULL"
            " ORDER BY part, year", (asset_id,)):
        out.setdefault(r["part"], []).append(_row(r))
    return out


def _names_key(row: dict) -> frozenset:
    return frozenset(re.sub(r"\s+", " ", n).strip().lower() for n in row["names"])


def _flag(code: str, words: str) -> dict:
    return {"code": code, "words": words}


# Flags that make a step's patient factors not like for like: drawn hatched and left out
# of the tracked-brand baseline.
NOT_LIKE_FOR_LIKE = ("containers_changed",)


def flags_for(part: str, prev: dict, cur: dict, st: dict, *, first_year=None,
              file_first=None, approval=None) -> list:
    """The codes a step carries, each with the words the UI shows."""
    out = []
    n0, n1 = prev["presentations"], cur["presentations"]
    if n0 != n1 or (max(n0, n1) > 1 and _names_key(prev) != _names_key(cur)):
        out.append(_flag("containers_changed",
                         f"CMS changed the containers it lists ({n0} to {n1}), so patient "
                         "counts are not like for like"))
    elif n0 == n1 == 1 and _names_key(prev) != _names_key(cur):
        out.append(_flag("name_changed",
                         f"CMS renamed the row from {prev['cms_name']} to "
                         f"{cur['cms_name']}"))
    if max(n0, n1) > 1:
        out.append(_flag("containers_summed",
                         "patients summed across containers, an upper bound"))
    if prev["beneficiaries"] is None or cur["beneficiaries"] is None:
        out.append(_flag("beneficiaries_suppressed",
                         "CMS gives no patient count for one of the two years, so only "
                         "claims and price are split"))
    if prev["partial_suppression"] or cur["partial_suppression"]:
        out.append(_flag("partial_suppression",
                         "CMS gives no patient count for some containers, so the patient "
                         "total is short"))
    if prev["starred"] or cur["starred"]:
        # The asterisk means different things in the two files (CMS data dictionaries).
        out.append(_flag("footnoted_name",
                         "CMS reports this billing code, which can carry other brands"
                         if part == "B" else
                         "CMS marks this drug: its cost per unit blends routes of "
                         "administration priced differently"))
    upc = st.get("units_per_claim")
    if upc is not None and upc > -1.0 and abs(math.log1p(upc)) >= FILL_SIZE_FLAG:
        unit = "fill" if part == "D" else "claim"
        out.append(_flag("fill_size_moved",
                         f"units per {unit} moved {upc * 100:+.1f}%, so read cost per "
                         "unit"))
    if max(n0, n1) > 1:
        out.append(_flag("units_blend",
                         "cost per unit blends the containers' units"))
    if (first_year is not None and file_first is not None and prev["year"] == first_year
            and first_year > file_first):
        if approval and int(approval[:4]) >= first_year:
            words = f"first year in Medicare, a part year: approved {approval[:10]}"
        elif approval:
            words = f"first year in the CMS file, though approved {approval[:10]}"
        else:
            words = "first year in the CMS file; no approval date on file"
        out.append(_flag("launch_part_year", words))
    return out


def _db_file(conn) -> str:
    row = next((r for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    return row[2] if row else ""


_BASELINE_CACHE: dict = {}
# The tracked-brand baseline counts a step only when the prior year's spend is at least
# this. Below it a brand's growth is dominated by launches and small counts.
BASELINE_MIN_SPEND = 50e6
_BASELINE_KEYS = ("spend", "claims", "patients", "intensity", "price", "price_per_unit")


def baseline(conn) -> dict:
    """{(part, from, to): {spend, claims, patients, intensity, price, price_per_unit, n}}.

    Medians over every CMS series on file whose prior-year spend is at least $50mm, with
    both patient counts present and the same containers in both years, one year apart.
    A CMS row stored against two assets counts once. The programme moves under every
    brand (the Part D median cost per fill turned from rising to falling in 2024), so a
    brand's own factor is read against this. Cached in-process on the table's row count
    and latest fetch time.
    """
    stamp = tuple(conn.execute(
        "SELECT COUNT(*), MAX(fetched_at) FROM drug_demand").fetchone())
    key = (_db_file(conn), stamp)
    if key in _BASELINE_CACHE:
        return _BASELINE_CACHE[key]
    by_asset: dict = {}
    for r in conn.execute(
            "SELECT asset_id, part, year, brand_name, total_spending, total_claims,"
            "       total_beneficiaries, total_dosage_units, source FROM drug_demand"
            " WHERE total_spending IS NOT NULL ORDER BY asset_id, part, year"):
        by_asset.setdefault((r["asset_id"], r["part"]), []).append(_row(r))
    pooled: dict = {}
    seen = set()
    for (_, part), rows in by_asset.items():
        for prev, cur in zip(rows, rows[1:]):
            if cur["year"] - prev["year"] != 1:
                continue
            if (prev["spending"] or 0) < BASELINE_MIN_SPEND:
                continue
            if prev["beneficiaries"] is None or cur["beneficiaries"] is None:
                continue
            st = step(prev, cur)
            if any(f["code"] in NOT_LIKE_FOR_LIKE for f in flags_for(part, prev, cur, st)):
                continue
            ident = (part, prev["year"], round(prev["spending"], 2),
                     round(cur["spending"], 2))
            if ident in seen:
                continue                       # one CMS row held on two assets
            seen.add(ident)
            pooled.setdefault((part, prev["year"], cur["year"]), []).append(st)
    out = {}
    for pair, steps in pooled.items():
        med = {}
        for k in _BASELINE_KEYS:
            vals = [s[k] for s in steps if s[k] is not None]
            med[k] = statistics.median(vals) if vals else None
        out[pair] = {**med, "n": len(steps), "from": pair[1], "to": pair[2],
                     "min_spend": BASELINE_MIN_SPEND}
    for old in [k for k in _BASELINE_CACHE if k[0] == key[0]]:
        del _BASELINE_CACHE[old]
    _BASELINE_CACHE[key] = out
    return out


def _file_first_years(conn) -> dict:
    return {r["part"]: r["y"] for r in conn.execute(
        "SELECT part, MIN(year) AS y FROM drug_demand GROUP BY part")}


# --- which record holds the brand -----------------------------------------------------
def resolve(conn, asset_id: int) -> dict | None:
    """Where the Medicare series for this asset lives.

    Medicare is brand level, and one brand can sit on two asset records (Eliquis on
    BMY's and Pfizer's, Enbrel on Pfizer's and Amgen's). The CMS fetcher binds a brand
    to one of them, so the other borrows its series and says so: ``held_on`` names the
    record it is read from, and ``shared_with`` names every other company modelling the
    brand. Nothing is inferred about which of them books the US sales.
    """
    asset = conn.execute(
        "SELECT a.id, a.brand_name, a.generic_name, c.ticker FROM assets a"
        "  LEFT JOIN companies c ON c.id = a.owner_company_id WHERE a.id = ?",
        (asset_id,)).fetchone()
    if asset is None:
        return None
    # Counted as _series reads them: a row with no spending is no series.
    own = conn.execute("SELECT COUNT(*) FROM drug_demand WHERE asset_id = ?"
                       " AND total_spending IS NOT NULL", (asset_id,)).fetchone()[0]
    peers = []
    brand = (asset["brand_name"] or "").strip().lower()
    if brand:
        peers = [dict(r) for r in conn.execute(
            "SELECT a.id, c.ticker,"
            "       (SELECT COUNT(*) FROM drug_demand d WHERE d.asset_id = a.id"
            "          AND d.total_spending IS NOT NULL) AS n"
            "  FROM assets a LEFT JOIN companies c ON c.id = a.owner_company_id"
            " WHERE LOWER(TRIM(a.brand_name)) = ? AND a.id != ?"
            " ORDER BY n DESC, a.id", (brand, asset_id))]
    held_on = None
    source_id = asset_id if own else None
    if not own:
        holder = next((p for p in peers if p["n"]), None)
        if holder:
            source_id = holder["id"]
            held_on = {"asset_id": holder["id"], "ticker": holder["ticker"]}
    shared = sorted({p["ticker"] for p in peers
                     if p["ticker"] and p["ticker"] != asset["ticker"]})
    return {"asset_id": asset_id, "ticker": asset["ticker"], "brand": asset["brand_name"],
            "generic": asset["generic_name"], "source_id": source_id,
            "held_on": held_on, "shared_with": shared}


def _first_approval(conn, *asset_ids) -> str | None:
    ids = [a for a in asset_ids if a is not None]
    if not ids:
        return None
    row = conn.execute(
        f"SELECT MIN(approval_date) FROM approvals WHERE asset_id IN"
        f" ({','.join('?' * len(ids))}) AND approval_date IS NOT NULL", ids).fetchone()
    return row[0] if row else None


# --- beside the split -----------------------------------------------------------------
GROWTH_KEY = {"marketed": "revenue_growth_pct", "franchise": "franchise_growth_pct"}


def _scalar(conn, asset_id: int, key: str):
    """The base scenario's asset-level scalar for a key, the US row first."""
    return conn.execute(
        "SELECT value, text_value, unit, source FROM assumptions"
        " WHERE asset_id = ? AND key = ? AND scenario = 'base'"
        "   AND indication_id IS NULL AND year IS NULL"
        " ORDER BY (region = 'US') DESC LIMIT 1", (asset_id, key)).fetchone()


def model_growth(conn, asset_id: int) -> dict | None:
    """The model's own growth rate for the asset, with the fade it runs down.

    A marketed product grows by revenue_growth_pct; a franchise member by
    franchise_growth_pct, which is the pool's growth rather than the product's. Any
    other mode has no single growth rate to set beside Medicare, and gets None rather
    than a number from somewhere else.
    """
    mode_row = _scalar(conn, asset_id, "therapy_mode")
    mode = ((mode_row["text_value"] if mode_row else None) or "").strip().lower()
    key = GROWTH_KEY.get(mode)
    if key is None:
        return None
    row = _scalar(conn, asset_id, key)
    if row is None or row["value"] is None:
        return None
    fade = _scalar(conn, asset_id, "terminal_growth_pct")
    years = _scalar(conn, asset_id, "growth_fade_years")
    start = _scalar(conn, asset_id, "forecast_start_year")
    latest = conn.execute(
        "SELECT MAX(fiscal_year) FROM asset_revenue WHERE asset_id = ? AND period = 'FY'"
        " AND value IS NOT NULL", (asset_id,)).fetchone()[0]
    from_fy = (latest if latest is not None
               else int(start["value"]) - 1 if start and start["value"] is not None
               else None)
    return {"key": key, "mode": mode, "value": row["value"], "unit": row["unit"],
            "source": row["source"],
            "fade_to": fade["value"] if fade else None,
            "fade_years": years["value"] if years else None,
            "from_fy": from_fy}


def _currency_note(unit: str | None) -> str | None:
    if not unit or unit == "USD":
        return None
    # The book's FX history starts in July 2026, so a past year cannot be converted.
    return f"in {unit}, so it carries the dollar's move"


def reported_growth(conn, asset_id: int) -> list:
    """[{fiscal_year, global_value, global_growth, us_value, us_growth, unit, ...}].

    Worldwide from asset_revenue's FY rows, the US from regional_loe.us_series. Growth
    is in the filer's own currency and only between two years in the same unit.
    """
    import regional_loe

    world = {r["fiscal_year"]: (r["value"], r["unit"]) for r in conn.execute(
        "SELECT fiscal_year, value, unit FROM asset_revenue WHERE asset_id = ?"
        "   AND period = 'FY' AND value IS NOT NULL", (asset_id,))}
    us = {y: (v[0], v[1]) for y, v in regional_loe.us_series(conn, asset_id).items() if v}

    def growth(series, fy):
        cur, prev = series.get(fy), series.get(fy - 1)
        if not cur or not prev or (cur[1] or "") != (prev[1] or ""):
            return None
        return _change(cur[0], prev[0])

    out = []
    for fy in sorted(set(world) | set(us)):
        g_unit = (world.get(fy) or (None, None))[1]
        u_unit = (us.get(fy) or (None, None))[1]
        out.append({"fiscal_year": fy,
                    "global_value": (world.get(fy) or (None,))[0], "global_unit": g_unit,
                    "global_growth": growth(world, fy),
                    "us_value": (us.get(fy) or (None,))[0], "us_unit": u_unit,
                    "us_growth": growth(us, fy),
                    "global_note": _currency_note(g_unit),
                    "us_note": _currency_note(u_unit)})
    return out


def direction_disagrees(model_value, latest: dict | None) -> bool | None:
    """True when the model and Medicare's latest patient growth (claims growth where
    CMS gives no patient count) point opposite ways, each beyond the deadband. None
    when either side is missing."""
    if model_value is None or not latest:
        return None
    medicare = (latest.get("patients") if latest.get("patients") is not None
                else latest.get("claims"))
    if medicare is None:
        return None
    if abs(model_value) <= DIRECTION_DEADBAND or abs(medicare) <= DIRECTION_DEADBAND:
        return False
    return (model_value > 0) != (medicare > 0)


def _pc(x: float) -> str:
    return f"{abs(x) * 100:.1f}%"


def _moved(x: float) -> str:
    if abs(x) < 0.0005:
        return "was flat"
    return f"{'rose' if x > 0 else 'fell'} {_pc(x)}"


def sentence(brand: str, part: str, latest: dict | None, model: dict | None,
             disagrees: bool | None) -> str | None:
    """The split in words, leading with the number.

    "Medicare patients on Eliquis rose 12.7% in 2024 and cost per fill was flat, so
    volume carried the 13.7% rise in Medicare spend. The model grows it 18.9% a year
    from FY2025."
    """
    if not latest or latest.get("spend") is None:
        return None
    labels = FACTOR_LABELS.get(part, FACTOR_LABELS["D"])
    g, year = latest["spend"], latest["to"]
    pts = latest.get("points")
    if latest.get("patients") is not None:
        lead = f"Medicare patients on {brand} {_moved(latest['patients'])} in {year}"
    elif latest.get("claims") is not None:
        lead = (f"Medicare {labels['claims'].lower()} of {brand} "
                f"{_moved(latest['claims'])} in {year}")
    else:
        lead = None
    if lead is None or pts is None or latest.get("price") is None:
        first = f"Medicare spend on {brand} {_moved(g)} in {year}."
    else:
        price = latest["price"]
        price_word = labels["price"].lower()
        price_clause = (f"{price_word} was flat" if abs(price) < 0.005
                        else f"{price_word} {_moved(price)}")
        vol = sum(v for k, v in pts.items() if k != "price")
        pp = pts["price"]
        whole = f"the {_pc(g)} {'rise' if g >= 0 else 'fall'} in Medicare spend"
        if abs(g) < 0.005:
            tail = "so Medicare spend was flat"
        elif abs(pp) <= 0.25 * abs(g) and vol * g > 0:
            tail = f"so volume carried {whole}"
        elif abs(vol) <= 0.25 * abs(g) and pp * g > 0:
            tail = f"so price carried {whole}"
        else:
            tail = (f"so volume gave {vol * 100:+.1f} points and price {pp * 100:+.1f} "
                    f"of {whole}")
        first = f"{lead} and {price_clause}, {tail}."
    if not model or model.get("value") is None:
        return first
    v = model["value"]
    what = "it" if model.get("key") == "revenue_growth_pct" else "its franchise pool"
    verb = "grows" if v >= 0 else "shrinks"
    second = f"The model {verb} {what} {_pc(v)} a year"
    if model.get("from_fy"):
        second += f" from FY{model['from_fy']}"
    if disagrees:
        who = ("Medicare patients" if latest.get("patients") is not None
               else f"Medicare {labels['claims'].lower()}")
        second += f", the other way from {who}"
    return f"{first} {second}."


# --- readers --------------------------------------------------------------------------
def _negotiated_map(conn) -> dict:
    """{normalised brand: first year a negotiated price applies}."""
    import ira
    out: dict = {}
    for s in ira.selected(conn):
        name = re.sub(r"\s+", " ", (s["brand"] or "").strip().lower())
        if name and s.get("ipay"):
            out[name] = min(out.get(name, s["ipay"]), s["ipay"])
    return out


_BASE_KEYS = ("spend", "patients", "intensity", "price", "price_per_unit", "claims", "n")


def _build(conn, asset_id: int, ticker: str, *, base=None, file_first=None,
           negotiated=None) -> dict | None:
    who = resolve(conn, asset_id)
    if who is None:
        return None
    model = model_growth(conn, asset_id)
    reported = reported_growth(conn, asset_id)
    latest_fy = max((r["fiscal_year"] for r in reported if r["global_value"] is not None),
                    default=None)
    out = {"asset_id": asset_id, "ticker": ticker, "brand": who["brand"],
           "generic": who["generic"], "held_on": who["held_on"],
           "shared_with": who["shared_with"], "patients_note": PATIENTS_NOTE,
           "gap_label": GAP_LABEL}
    if who["source_id"] is None:
        return {**out, "ok": False, "reason": "not in the CMS files",
                "label": label(None, None), "latest_year": None, "lag_years": None,
                "parts": [], "brand_total": [], "sentence": None,
                "beside": {"model_growth": model, "reported": reported,
                           "direction_disagrees": None}}
    series = _series(conn, who["source_id"])
    base = base if base is not None else baseline(conn)
    file_first = file_first if file_first is not None else _file_first_years(conn)
    negotiated = negotiated if negotiated is not None else _negotiated_map(conn)
    approval = _first_approval(conn, asset_id, who["source_id"])
    ira_year = negotiated.get(re.sub(r"\s+", " ", (who["brand"] or "").strip().lower()))

    latest_year = max(rows[-1]["year"] for rows in series.values())
    totals: dict = {}
    for rows in series.values():
        for r in rows:
            totals[r["year"]] = totals.get(r["year"], 0.0) + (r["spending"] or 0.0)
    brand_growth = {y: _change(totals[y], totals.get(y - 1)) for y in totals}
    by_fy = {r["fiscal_year"]: r for r in reported}

    def latest_spend(rows):
        return next((r["spending"] for r in rows if r["year"] == latest_year), 0.0) or 0.0

    parts = []
    for part, rows in sorted(series.items(), key=lambda kv: -latest_spend(kv[1])):
        share = (latest_spend(rows) / totals[latest_year]) if totals.get(latest_year) else 0.0
        material = share >= MATERIAL_PART_SHARE
        first_year = rows[0]["year"]
        steps = []
        for prev, cur in zip(rows, rows[1:]):
            st = step(prev, cur)
            entry = {"from": st["from"], "to": st["to"], "years": cur["year"] - prev["year"],
                     "spend": st["spend"], "flags": []}
            if material:
                entry.update(st)
                entry["factors"] = list(factors_of(st) or [])
                entry["points"] = points(st)
                entry["flags"] = flags_for(part, prev, cur, st, first_year=first_year,
                                           file_first=file_first.get(part),
                                           approval=approval)
                held = base.get((part, prev["year"], cur["year"]))
                entry["baseline"] = ({k: held[k] for k in _BASE_KEYS} if held else None)
                rep = by_fy.get(cur["year"]) or {}
                entry["us_growth"] = rep.get("us_growth")
                entry["us_note"] = rep.get("us_note")
                entry["global_growth"] = rep.get("global_growth")
                entry["global_note"] = rep.get("global_note")
                entry["brand_spend"] = brand_growth.get(cur["year"])
                # Only set against dollars: a growth rate in another currency carries
                # the exchange rate, and a gap between the two would be part FX.
                entry["gap_pts"] = (entry["us_growth"] - entry["brand_spend"]
                                    if entry["us_growth"] is not None
                                    and entry["brand_spend"] is not None
                                    and rep.get("us_unit") == "USD" else None)
            entry["like_for_like"] = not any(f["code"] in NOT_LIKE_FOR_LIKE
                                             for f in entry["flags"])
            steps.append(entry)
        if ira_year and steps and material:
            steps[-1]["flags"].append(_flag(
                "negotiated_price",
                f"Medicare's negotiated price applies from {ira_year}, so the price "
                "factor breaks then"))
        sp = span(rows, first_year, rows[-1]["year"]) if material and len(rows) > 1 else None
        if sp is not None:
            sp["flags"] = sorted({f["code"] for s in steps for f in s["flags"]
                                  if f["code"] in ("containers_changed", "launch_part_year",
                                                   "beneficiaries_suppressed")})
        parts.append({
            "part": part, "part_label": PART_LABEL.get(part, part),
            "source_file": SOURCE_FILE.get(part), "factor_labels": FACTOR_LABELS.get(part),
            "spend_share": share, "material": material, "latest_year": rows[-1]["year"],
            "latest_spending": latest_spend(rows),
            "series": [{k: r[k] for k in ("year", "spending", "claims", "beneficiaries",
                                          "units", "cms_name", "presentations")}
                       for r in rows],
            "steps": steps, "span": sp})

    material_parts = [p for p in parts if p["material"]]
    brand_total = []
    if len(material_parts) > 1:
        pairs = None
        for p in material_parts:
            have = {(s["from"], s["to"]) for s in p["steps"]}
            pairs = have if pairs is None else pairs & have
        for pair in sorted(pairs or ()):
            legs = []
            for p in material_parts:
                s = next(s for s in p["steps"] if (s["from"], s["to"]) == pair)
                prior = next(r["spending"] for r in p["series"] if r["year"] == pair[0])
                legs.append({"part": p["part"], "prior_spend": prior, "step": s})
            combined = combine(legs)
            if combined:
                brand_total.append({"from": pair[0], "to": pair[1], **combined})

    main = parts[0]
    latest = main["steps"][-1] if main["steps"] and main["material"] else None
    disagrees = direction_disagrees((model or {}).get("value"), latest)
    return {**out, "ok": True, "reason": None,
            "label": label(latest_year, latest_fy),
            "latest_year": latest_year,
            "lag_years": (latest_fy - latest_year) if latest_fy is not None else None,
            "latest_fy": latest_fy,
            "approval": approval, "negotiated_from": ira_year,
            "parts": parts, "brand_total": brand_total,
            "beside": {"model_growth": model, "reported": reported,
                       "direction_disagrees": disagrees},
            "sentence": sentence(who["brand"] or who["generic"] or "this drug",
                                 main["part"], latest, model, disagrees)}


def for_asset(db_path, ticker: str, asset_id: int) -> dict | None:
    """The Medicare split for one asset the company may see, owner or partner. None
    for an unknown ticker or an asset it may not see; ok False with a reason when CMS
    has no series for the brand on any record."""
    import forecast_view

    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (ticker.upper(),)).fetchone()
        if company is None:
            return None
        if forecast_view._accessible(conn, company["id"], asset_id, ticker) is None:
            return None
        return _build(conn, asset_id, ticker.upper())
    finally:
        conn.close()


def company_split(db_path, ticker: str) -> dict | None:
    """One compact row per brand and Medicare part across the company's own and
    partnered assets, sorted by latest spend, with the tracked median beside them."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (ticker.upper(),)).fetchone()
        if company is None:
            return None
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM assets WHERE owner_company_id = ? ORDER BY id",
            (company["id"],))]
        ids += [r["asset_id"] for r in conn.execute(
            "SELECT DISTINCT asset_id FROM assumptions WHERE key = 'partner_ticker'"
            "   AND UPPER(COALESCE(text_value, '')) = ? ORDER BY asset_id",
            (ticker.upper(),)) if r["asset_id"] not in ids]
        base = baseline(conn)
        file_first = _file_first_years(conn)
        negotiated = _negotiated_map(conn)
        rows, seen, latest_years = [], set(), {}
        for aid in ids:
            who = resolve(conn, aid)
            if who is None or who["source_id"] is None:
                continue
            built = _build(conn, aid, ticker.upper(), base=base, file_first=file_first,
                           negotiated=negotiated)
            model = built["beside"]["model_growth"] or {}
            for part in built["parts"]:
                key = (who["source_id"], part["part"])
                if key in seen:
                    continue                   # the same CMS series on two records
                seen.add(key)
                latest = part["steps"][-1] if part["steps"] else None
                latest_years[part["part"]] = max(latest_years.get(part["part"], 0),
                                                 part["latest_year"])
                rows.append({
                    "asset_id": aid, "brand": built["brand"] or built["generic"],
                    "part": part["part"], "part_label": part["part_label"],
                    "factor_labels": part["factor_labels"],
                    "latest_year": part["latest_year"],
                    "spending": part["latest_spending"],
                    "spend_share": part["spend_share"], "material": part["material"],
                    "from": (latest or {}).get("from"),
                    **{k: (latest or {}).get(k) for k in (
                        "spend", "claims", "patients", "intensity", "price",
                        "price_per_unit", "points", "us_growth", "us_note",
                        "global_growth", "global_note", "gap_pts")},
                    "flags": (latest or {}).get("flags") or [],
                    "like_for_like": (latest or {}).get("like_for_like", True),
                    "model_growth": model.get("value"), "model_key": model.get("key"),
                    "model_from_fy": model.get("from_fy"),
                    "direction_disagrees": (direction_disagrees(model.get("value"), latest)
                                            if part["material"] else None),
                    "held_on": built["held_on"], "shared_with": built["shared_with"]})
        rows.sort(key=lambda r: -(r["spending"] or 0.0))
        medians = {}
        for part, year in latest_years.items():
            held = base.get((part, year - 1, year))
            if held:
                medians[part] = {k: held[k] for k in _BASE_KEYS} | {
                    "from": year - 1, "to": year, "min_spend": BASELINE_MIN_SPEND}
        latest_year = max(latest_years.values(), default=None)
        return {"ticker": ticker.upper(), "brands": rows, "baseline": medians,
                "label": label(latest_year, None), "latest_year": latest_year,
                "patients_note": PATIENTS_NOTE, "factor_labels": FACTOR_LABELS}
    finally:
        conn.close()
