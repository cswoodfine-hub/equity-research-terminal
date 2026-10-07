"""Disease areas: every big pharma company's assets in one therapeutic area, scored.

One level above the indication scorecard. An indication compares drugs; an area compares
companies, on everything each holds in oncology, or metabolic disease, or immunology.

Which assets are in an area
    A product's area is ``product_areas.area_for``, the rule the Catalysts view uses: the
    first indication on its label, else the disease it is modelled in, else what its
    trials study, else an ingredient that names a class. Each product has one area, so a
    product sold for several diseases counts once, in its primary labelled area, with its
    whole value. An asset nothing on file places, and one placed only in healthy
    volunteers, is in no area. Retired programmes are left out.

    A company is present in an area when it markets a product there, has an asset there
    in Phase 2 or later, or carries a modelled line there.

Stage
    Marketed where the asset is marketed. Filed where the forecast places the asset at its
    approval gate (NDA or BLA to approval). Otherwise the furthest phase any of its active
    indications has reached. Marketed products are counted by brand, so two rows of one
    product count once.

The four pillars, each from 0 to 100
    Value today: the risked value of the company's marketed products in the area, in USD
    bn, each product's whole value. The area's share of the company's total product value
    (marketed and pipeline, every area) is shown beside it and does not move the score.
    A company with nothing marketed in the area has no value today there, and scores at
    the foot; one whose marketed products carry no model value has no figure.

    Pipeline: two parts averaged, the risked value of its unmarketed assets in the area
    in USD bn, and its depth, the count of those in Phase 3 or filed. Where no pipeline
    asset carries a model value the score rests on depth alone.

    Durability: the share of the company's revenue in the area, each product's latest
    reported year, whose exclusivity ends within five years (this year and the next four),
    by the cliff's own rule: the effective LOE of ``loe.for_assets``, orphan exclusivity
    left out, a product already off protection not counted as ahead. Less is better. No
    figure where no product in the area has revenue on file.

    Clinical quality: the mean overall score of the company's scored drugs on the
    indication scorecard (``landscape_score``), across every indication the Indications
    view offers in this area: each drug's mean over the indications it is scored in, then
    the mean over its drugs. That mean is the pillar itself: it is already 0 to 100 and
    comparable across companies, so it is not rescaled. A drug's clinical record counts in
    every area it is trialled in, while its value counts once. No figure where none is
    scored.

    Value today, pipeline and durability are scaled by percentile rank among the companies
    present with a figure: the share of the others it beats, a tie counting half, so the
    best scores 100 and the weakest 0 whatever the spread. Raw values in this book span a
    hundredfold, and a min-max scale would put every company but the leader near zero. A
    company alone with a figure scores 50.

    The overall weights value today 35%, pipeline 25%, clinical quality 25% and
    durability 15%, renormalised over the pillars a company has. A company needs at least
    three of the four to be ranked; one with fewer is listed below the ranked companies as
    too little on file, with no rank and no overall, and is never a card's pick. A missing
    pillar is never filled in.

Currency
    A value, revenue and stake is in its filer's reporting currency and is converted to
    USD at the book's own latest ECB reference rates (``fx.latest_usd_rates``). A figure
    with no rate on file has no USD figure; it is never treated as a dollar.

Readouts
    Data readouts pending within 24 months on the company's assets in the area, from the
    catalyst stakes. The value at stake is the sum of the swings the stakes price (the
    rNPV if the readout passes less the rNPV if it fails, at the company's share); a
    readout the stakes do not price adds to the count, never to the value.
"""

from __future__ import annotations

import datetime as dt
import re
from statistics import mean

import db
import fx
import loe as loe_module
import product_areas
import therapeutic_areas

PILLARS = ("value", "pipeline", "durability", "clinical")
# Value-led: what a company holds today counts most, durability least.
WEIGHTS = {"value": 0.35, "pipeline": 0.25, "clinical": 0.25, "durability": 0.15}
MIN_PILLARS = 3
PILLAR_NAMES = {"value": "value today", "pipeline": "pipeline", "durability": "durability",
                "clinical": "clinical quality"}
# Not a disease: an asset studied only in healthy volunteers sits in no area.
NOT_AN_AREA = {"Healthy volunteers", therapeutic_areas.OTHER}
DURABILITY_YEARS = 5
READOUT_MONTHS = 24
LATE_STAGES = ("Filed", "Phase 3", "Phase 2/3")
MID_STAGES = ("Phase 2",)
_PHASE_RANK = {"Early Phase 1": 0, "Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3,
               "Phase 2/3": 4, "Phase 3": 5}
APPROVAL_GATE = "nda_to_approval"

METHOD = {
    "value": ("the risked value of the company's marketed products in the area, in USD "
              "bn, each product's whole value. The area's share of the company's total "
              "product value is shown beside it and does not move the score. Nothing "
              "marketed in the area scores at the foot; marketed products with no model "
              "value give no figure."),
    "pipeline": ("the risked value of its unmarketed assets in the area in USD bn, and "
                 "its depth, the count in Phase 3 or filed, each scaled and then "
                 "averaged. With no pipeline value modelled it rests on depth alone."),
    "durability": ("the share of its revenue in the area, each product's latest reported "
                   "year, whose exclusivity ends within 5 years: the effective LOE of the "
                   "cliff, orphan exclusivity left out. Less is better. No figure where no "
                   "product in the area has revenue on file."),
    "clinical": ("the mean overall score of its drugs on the indication scorecard, across "
                 "the indications in this area the Indications view offers: each drug's "
                 "mean over the indications it is scored in, then the mean over its "
                 "drugs. That mean is the score itself, already 0 to 100 and comparable "
                 "across companies. No figure where none is scored."),
    "scale": ("Value today, pipeline and durability run from 0 to 100 by percentile rank "
              "among the companies with a figure: the share of the others it beats, a tie "
              "counting half. The best scores 100 and the weakest 0 whatever the spread; "
              "a company alone with a figure scores 50."),
    "overall": ("The overall weights value today 35%, pipeline 25%, clinical quality 25% "
                "and durability 15%, renormalised over the pillars a company has, the "
                "count shown beside it. A missing pillar is never filled in."),
    "ranking": ("A company needs at least 3 of the 4 pillars to be ranked. One with fewer "
                "is listed below the ranked companies as too little on file, with no rank "
                "and no overall, is left off the chart and is never a card's pick."),
    "assignment": ("A product counts in one area, the first indication on its label, else "
                   "the disease it is modelled in, else what its trials study, with its "
                   "whole value. A drug's clinical record counts in every area it is "
                   "trialled in."),
    "currency": ("Every value, revenue and stake is converted from the filer's reporting "
                 "currency to USD at the book's latest ECB reference rates."),
    "readouts": ("Readouts are data readouts pending within 24 months on assets in the "
                 "area. The value at stake sums the swings the catalyst stakes price; an "
                 "unpriced readout adds to the count only."),
}


# --- names ---------------------------------------------------------------------------
def slug(area: str) -> str:
    """The area as it travels in a URL: "Immunology and inflammation" is
    "immunology-and-inflammation"."""
    return re.sub(r"[^a-z0-9]+", "-", (area or "").lower()).strip("-")


def area_names() -> list:
    return [a for a in therapeutic_areas.area_names() if a not in NOT_AN_AREA]


def area_of(slug_: str):
    for name in area_names():
        if slug(name) == (slug_ or "").lower():
            return name
    return None


# --- the scale -----------------------------------------------------------------------
def percentile_scores(values: dict, higher_is_better: bool = True) -> dict:
    """{key: 0 to 100 or None} by percentile rank among the keys with a figure: the share
    of the others each beats, a tie counting half. None stays None; a key alone with a
    figure scores 50."""
    have = {k: round(v, 9) for k, v in values.items() if v is not None}
    out = {k: None for k in values}
    n = len(have)
    for k, v in have.items():
        if n == 1:
            out[k] = 50.0
            continue
        beats = sum(1 for w in have.values() if (w < v if higher_is_better else w > v))
        ties = sum(1 for w in have.values() if w == v) - 1
        out[k] = 100.0 * (beats + 0.5 * ties) / (n - 1)
    return out


def overall(scores: dict, weights: dict = WEIGHTS):
    """(the weighted mean of the pillars present, renormalised over their weights, or
    None; how many are present)."""
    have = {p: scores[p] for p in PILLARS if scores.get(p) is not None}
    total = sum(weights[p] for p in have)
    if not have or total <= 0:
        return None, len(have)
    return sum(weights[p] * v for p, v in have.items()) / total, len(have)


def usd(value, currency, rates: dict):
    """A figure in its currency in USD at the book's rates, or None. A dollar is a dollar;
    any other currency with no rate on file has no USD figure."""
    if value is None or not currency:
        return None
    if currency == "USD":
        return float(value)
    return fx.to_usd(value, currency, rates)


def _bn(mm):
    return None if mm is None else mm / 1000.0


def _add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return dt.date(year, month, d)
        except ValueError:
            continue
    return dt.date(year, month, 28)


# --- what the book holds -------------------------------------------------------------
def _cohort(conn, cohort=None) -> list:
    """The big pharma companies, the Indications view's own cohort."""
    if cohort is None:
        import landscape
        cohort = landscape._big_pharma_ids(conn)
    ids = sorted(cohort)
    if not ids:
        return []
    rows = conn.execute(
        f"SELECT id, ticker, name, COALESCE(reporting_currency, 'USD') AS currency"
        f"  FROM companies WHERE id IN ({','.join('?' * len(ids))}) ORDER BY ticker",
        ids).fetchall()
    return [dict(r) for r in rows]


def _assets(conn, company_ids: list) -> list:
    """Every unretired asset of these companies with its area and its furthest active
    phase. Filed is set later, from the forecast's gate."""
    if not company_ids:
        return []
    marks = ",".join("?" * len(company_ids))
    rows = [dict(r) for r in conn.execute(
        f"""SELECT a.id, a.owner_company_id AS company_id, a.brand_name, a.generic_name,
                   a.internal_code, a.is_marketed
              FROM assets a
             WHERE a.owner_company_id IN ({marks})
               AND a.id NOT IN (SELECT asset_id FROM retired_programmes)""",
        company_ids)]
    if not rows:
        return []
    phases: dict = {}
    am = ",".join("?" * len(rows))
    for r in conn.execute(
            f"""SELECT asset_id, phase FROM asset_indications
                 WHERE asset_id IN ({am})
                   AND LOWER(COALESCE(development_status, '')) NOT IN
                       ('discontinued', 'withdrawn', 'terminated', 'suspended')""",
            [r["id"] for r in rows]):
        if r["phase"] in _PHASE_RANK and (
                _PHASE_RANK[r["phase"]] > _PHASE_RANK.get(phases.get(r["asset_id"]), -1)):
            phases[r["asset_id"]] = r["phase"]
    modelled = {r[0] for r in conn.execute(
        f"SELECT DISTINCT asset_id FROM assumptions WHERE asset_id IN ({am})",
        [r["id"] for r in rows])}
    for r in rows:
        r["name"] = r["brand_name"] or r["generic_name"] or r["internal_code"] or f"#{r['id']}"
        r["area"] = product_areas.area_for(conn, r["id"])
        if r["area"] in NOT_AN_AREA:
            r["area"] = None
        r["phase"] = phases.get(r["id"])
        r["has_model"] = r["id"] in modelled
        r["stage"] = "Marketed" if r["is_marketed"] else r["phase"]
    return rows


def _present(a: dict) -> bool:
    return bool(a["stage"] == "Marketed" or a["stage"] in LATE_STAGES
                or a["stage"] in MID_STAGES or a.get("has_model") or a.get("line"))


def _brand_key(a: dict) -> str:
    return (a.get("brand_name") or a.get("generic_name") or a["name"]).strip().lower()


def _revenue(conn, asset_ids: list) -> dict:
    """{asset_id: {value, unit, fiscal_year}}, each product's latest reported year (the
    cliff's own rule, asset_revenue._latest_revenue), in whole units of ``unit``."""
    if not asset_ids:
        return {}
    out: dict = {}
    for r in conn.execute(
            f"""SELECT asset_id, fiscal_year, value, unit FROM asset_revenue
                 WHERE period = 'FY' AND asset_id IN ({','.join('?' * len(asset_ids))})
                 ORDER BY asset_id, fiscal_year""", asset_ids):
        out[r["asset_id"]] = {"value": r["value"], "unit": r["unit"],
                              "fiscal_year": r["fiscal_year"]}
    return out


def index(db_path=None, cohort=None) -> list:
    """Every area with a big pharma company present, most companies first: its name, slug,
    the companies present, its asset counts and how many assets each company has there."""
    conn = db.get_connection(db_path)
    try:
        companies = _cohort(conn, cohort)
        by_id = {c["id"]: c for c in companies}
        assets = _assets(conn, list(by_id))
    finally:
        conn.close()
    out: dict = {}
    for a in assets:
        if not a["area"] or not _present(a):
            continue
        row = out.setdefault(a["area"], {"area": a["area"], "slug": slug(a["area"]),
                                         "tickers": set(), "marketed": set(), "late": 0,
                                         "phase2": 0, "assets_by_ticker": {}})
        t = by_id[a["company_id"]]["ticker"]
        row["tickers"].add(t)
        row["assets_by_ticker"][t] = row["assets_by_ticker"].get(t, 0) + 1
        if a["stage"] == "Marketed":
            row["marketed"].add((a["company_id"], _brand_key(a)))
        elif a["stage"] in LATE_STAGES:
            row["late"] += 1
        elif a["stage"] in MID_STAGES:
            row["phase2"] += 1
    rows = [{**r, "tickers": sorted(r["tickers"]), "companies": len(r["tickers"]),
             "marketed": len(r["marketed"])} for r in out.values()]
    rows.sort(key=lambda r: (-r["companies"], -(r["marketed"] + r["late"]), r["area"]))
    return rows


# --- the clinical pillar's inputs ----------------------------------------------------
def scored_drugs(db_path, area: str, scorecard_for=None, verdict_for=None) -> list:
    """[{ticker, asset_id, name, indication, overall}] for every drug the indication
    scorecard places in this area's indications. ``scorecard_for(indication_id)`` hands
    back a scorecard already built (the API's cached overview) or None."""
    import landscape
    import landscape_score
    import pool_crowding
    out = []
    seen_groups = set()
    conn = db.get_connection(db_path)
    try:
        index_ = landscape.indications(db_path)
        groups = {i["id"]: pool_crowding.group_of(conn, i["id"]) for i in index_}
    finally:
        conn.close()
    for ind in index_:
        if therapeutic_areas.classify([ind["name"]]) != area:
            continue
        # Two names of one population draw the same landscape: score it once.
        if groups.get(ind["id"]) in seen_groups:
            continue
        seen_groups.add(groups.get(ind["id"]))
        sc = scorecard_for(ind["id"]) if scorecard_for else None
        if sc is None:
            land = landscape.landscape(db_path, ind["id"], verdict_for=verdict_for)
            sc = landscape_score.scorecard(land) if land else None
        for a in (sc or {}).get("assets") or []:
            if a.get("placed") and a.get("overall") is not None and a.get("ticker"):
                out.append({"ticker": a["ticker"], "asset_id": a.get("asset_id"),
                            "name": a.get("name"), "indication": ind["name"],
                            "overall": float(a["overall"])})
    return out


def clinical_by_company(drugs: list) -> dict:
    """{ticker: {mean, drugs: [{name, mean, indications}]}}: each drug's mean over the
    indications it is scored in, then the mean over the company's drugs."""
    per: dict = {}
    for d in drugs:
        key = (d["ticker"], d.get("asset_id") or d.get("name"))
        per.setdefault(key, {"name": d.get("name"), "scores": [], "indications": []})
        per[key]["scores"].append(d["overall"])
        per[key]["indications"].append(d.get("indication"))
    out: dict = {}
    for (ticker, _), v in per.items():
        out.setdefault(ticker, []).append({"name": v["name"], "mean": mean(v["scores"]),
                                           "indications": len(v["scores"])})
    return {t: {"mean": mean(x["mean"] for x in ds),
                "drugs": sorted(ds, key=lambda x: -x["mean"])} for t, ds in out.items()}


# --- the assembly --------------------------------------------------------------------
def assemble(area: str, companies: list, assets: list, verdicts: dict, revenue: dict,
             loe: dict, stakes: dict, clinical: dict, rates: dict, today: dt.date) -> dict:
    """The area's page from plain inputs, so every rule is testable without a book.

    ``companies`` [{id, ticker, name, currency}]; ``assets`` the rows of ``_assets``;
    ``verdicts`` {ticker: company verdict}; ``revenue`` {asset_id: {value, unit,
    fiscal_year}} in whole units; ``loe`` {asset_id: {date, basis}}; ``stakes`` {ticker: catalyst
    stakes}; ``clinical`` the output of ``clinical_by_company``; ``rates`` the book's
    USD rates.
    """
    horizon_end = today.year + DURABILITY_YEARS - 1
    readout_end = _add_months(today, READOUT_MONTHS)
    by_ticker = {c["ticker"]: c for c in companies}
    lines_of: dict = {}
    totals_of: dict = {}
    currency_of: dict = {}
    for t, v in verdicts.items():
        if not v:
            continue
        currency_of[t] = (((v.get("sotp") or {}).get("fx") or {}).get("currency")
                          or (by_ticker.get(t) or {}).get("currency") or "USD")
        counted = [m for m in v.get("modelled") or [] if m.get("counted", True)]
        lines_of[t] = {m["asset_id"]: m for m in counted}
        totals_of[t] = sum(m.get("rnpv_share") or 0.0 for m in counted)

    rows = []
    for c in companies:
        t = c["ticker"]
        cur = currency_of.get(t) or c.get("currency") or "USD"
        lines = lines_of.get(t) or {}
        mine = [dict(a) for a in assets if a["company_id"] == c["id"] and a["area"] == area]
        for a in mine:
            a["line"] = lines.get(a["id"])
            gate = ((a["line"] or {}).get("gate") or {}).get("gate")
            if not a["is_marketed"] and gate == APPROVAL_GATE:
                a["stage"] = "Filed"
        mine = [a for a in mine if _present(a)]
        if not mine:
            continue
        marketed = [a for a in mine if a["stage"] == "Marketed"]
        pipe = [a for a in mine if a["stage"] != "Marketed"]
        late = [a for a in pipe if a["stage"] in LATE_STAGES]
        mid = [a for a in pipe if a["stage"] in MID_STAGES]

        # Value today: the modelled marketed products, each its whole value.
        valued_m = [a for a in marketed if a["line"]]
        m_mm = sum(a["line"]["rnpv_share"] or 0.0 for a in valued_m)
        if not marketed:
            value_usd, value_basis = 0.0, "none marketed"
        elif not valued_m:
            value_usd, value_basis = None, "no marketed product here carries a model value"
        else:
            value_usd = usd(m_mm, cur, rates)
            value_basis = (None if value_usd is not None
                           else f"no {cur} to USD rate on file")
        p_lines = [a for a in pipe if a["line"]]
        p_mm = sum(a["line"]["rnpv_share"] or 0.0 for a in p_lines)
        if not pipe:
            pipe_usd = 0.0
        elif not p_lines:
            pipe_usd = None
        else:
            pipe_usd = usd(p_mm, cur, rates)
        total = totals_of.get(t)
        share = ((m_mm + p_mm) / total) if (total and (valued_m or p_lines)) else None

        # Durability: revenue on file in the area, and what of it loses exclusivity.
        rev_rows, risk_rows = [], []
        for a in mine:
            r = revenue.get(a["id"])
            if not r or r.get("value") is None:
                continue
            # Product revenue is filed in whole units, the model's values in millions.
            amount = usd(r["value"] / 1e6, r.get("unit") or cur, rates)
            if amount is None:
                continue
            rev_rows.append((a, amount, r.get("fiscal_year")))
            found = loe.get(a["id"]) or {}
            date, basis = found.get("date"), found.get("basis") or ""
            if date and basis != "orphan exclusivity":
                year = int(str(date)[:4])
                if today.year <= year <= horizon_end:
                    risk_rows.append({"name": a["name"], "loe": str(date)[:10],
                                      "usd_bn": _bn(amount)})
        rev_total = sum(x[1] for x in rev_rows)
        at_risk = sum(r["usd_bn"] for r in risk_rows) * 1000.0
        risk_share = (at_risk / rev_total) if rev_total > 0 else None

        # Readouts within 24 months, and the value the stakes put on them.
        ids = {a["id"] for a in mine}
        st_ = stakes.get(t) or {}
        events = []
        for priced, group in ((True, st_.get("priced") or []),
                              (False, st_.get("unpriced") or [])):
            for e in group:
                if e.get("asset_id") not in ids or e.get("catalyst_type") != "data readout":
                    continue
                day = (e.get("expected_date") or "")[:10]
                if not day or not (today.isoformat() <= day <= readout_end.isoformat()):
                    continue
                swing = usd(e.get("share_swing"), cur, rates) if priced else None
                events.append({"asset": e.get("asset_name"), "date": day,
                               "usd_bn": _bn(swing), "priced": swing is not None})
        priced_ev = [e for e in events if e["priced"]]
        stake = sum(e["usd_bn"] for e in priced_ev) if priced_ev else None

        cl = clinical.get(t)
        rows.append({
            "ticker": t, "name": c["name"], "currency": cur,
            "counts": {"marketed": len({_brand_key(a) for a in marketed}),
                       "late": len(late), "filed": sum(1 for a in late
                                                        if a["stage"] == "Filed"),
                       "phase2": len(mid)},
            "value": {"usd_bn": _bn(value_usd), "share": share, "basis": value_basis,
                      "valued": len(valued_m), "products": len(marketed),
                      "top": _top([(a["name"], usd(a["line"]["rnpv_share"], cur, rates))
                                   for a in valued_m])},
            "pipeline": {"usd_bn": _bn(pipe_usd), "depth": len(late), "valued": len(p_lines),
                         "assets": len(pipe),
                         "late": [{"name": a["name"], "stage": a["stage"]} for a in late],
                         "top": _top([(a["name"], usd(a["line"]["rnpv_share"], cur, rates))
                                      for a in p_lines])},
            "durability": {"share": risk_share, "revenue_usd_bn": _bn(rev_total)
                           if rev_rows else None,
                           "at_risk_usd_bn": _bn(at_risk) if rev_rows else None,
                           "fiscal_year": max((x[2] for x in rev_rows if x[2]), default=None),
                           "products": sorted(risk_rows, key=lambda r: r["loe"])},
            "clinical": {"mean": cl["mean"] if cl else None,
                         "drugs": (cl or {}).get("drugs") or []},
            "readouts": {"count": len(events), "priced": len(priced_ev),
                         "stake_usd_bn": stake,
                         "top": sorted(priced_ev, key=lambda e: -e["usd_bn"])[:5],
                         "first": min((e["date"] for e in events), default=None),
                         "last": max((e["date"] for e in events), default=None)},
        })

    # The pillars, each scaled among the companies present.
    value_s = percentile_scores({r["ticker"]: r["value"]["usd_bn"] for r in rows})
    pv_s = percentile_scores({r["ticker"]: r["pipeline"]["usd_bn"] for r in rows})
    depth_s = percentile_scores({r["ticker"]: r["pipeline"]["depth"] for r in rows})
    dur_s = percentile_scores({r["ticker"]: r["durability"]["share"] for r in rows},
                              higher_is_better=False)
    for r in rows:
        t = r["ticker"]
        parts = [s for s in (pv_s[t], depth_s[t]) if s is not None]
        r["pipeline"]["value_score"], r["pipeline"]["depth_score"] = pv_s[t], depth_s[t]
        # Clinical quality is the indication scorecard's own 0 to 100, not rescaled.
        r["scores"] = {"value": value_s[t], "pipeline": mean(parts) if parts else None,
                       "durability": dur_s[t], "clinical": r["clinical"]["mean"]}
        weighted, r["pillars"] = overall(r["scores"])
        r["ranked"] = r["pillars"] >= MIN_PILLARS
        r["overall"] = weighted if r["ranked"] else None
    # The ranked companies by overall, then those with too little on file, most pillars
    # first.
    rows.sort(key=lambda r: (not r["ranked"], -(r["overall"] or 0.0), -r["pillars"],
                             r["ticker"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i if r["ranked"] else None

    def total(getter):
        vals = [getter(r) for r in rows]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    rev = total(lambda r: r["durability"]["revenue_usd_bn"])
    risk = total(lambda r: r["durability"]["at_risk_usd_bn"])
    totals = {
        "companies": len(rows),
        "marketed": sum(r["counts"]["marketed"] for r in rows),
        "late": sum(r["counts"]["late"] for r in rows),
        "filed": sum(r["counts"]["filed"] for r in rows),
        "phase2": sum(r["counts"]["phase2"] for r in rows),
        "value_usd_bn": total(lambda r: r["value"]["usd_bn"]),
        "pipeline_usd_bn": total(lambda r: r["pipeline"]["usd_bn"]),
        "revenue_usd_bn": rev,
        "at_risk_usd_bn": risk,
        "at_risk_share": (risk / rev) if (rev and risk is not None) else None,
        "readouts": sum(r["readouts"]["count"] for r in rows),
        "priced_readouts": sum(r["readouts"]["priced"] for r in rows),
        "stake_usd_bn": total(lambda r: r["readouts"]["stake_usd_bn"]),
        "scored_drugs": sum(len(r["clinical"]["drugs"]) for r in rows),
    }
    a = totals["value_usd_bn"]
    b = totals["pipeline_usd_bn"]
    totals["risked_usd_bn"] = (None if a is None and b is None else (a or 0.0) + (b or 0.0))
    totals["ranked"] = sum(1 for r in rows if r["ranked"])
    return {"area": area, "slug": slug(area), "as_of": today.isoformat(),
            "weights": WEIGHTS, "min_pillars": MIN_PILLARS,
            "fx_as_of": rates.get("as_of"), "horizon_end": horizon_end,
            "readout_end": readout_end.isoformat(), "companies": rows, "totals": totals,
            "cards": cards(area, rows, horizon_end), "method": METHOD}


def _top(pairs, n: int = 5) -> list:
    have = [(name, v) for name, v in pairs if v is not None]
    have.sort(key=lambda p: -p[1])
    return [{"name": name, "usd_bn": _bn(v)} for name, v in have[:n]]


# --- the cards -----------------------------------------------------------------------
def money(bn) -> str:
    """$12.3bn, $0.45bn, or no free data. A negative value keeps its sign."""
    if bn is None:
        return "no free data"
    sign = "−" if bn < 0 else ""
    v = abs(bn)
    return f"{sign}${v:,.1f}bn" if v >= 1 else f"{sign}${v:,.2f}bn"


def pct(share, digits: int = 0) -> str:
    return "no free data" if share is None else f"{share * 100:.{digits}f}%"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def short_name(name: str) -> str:
    """The company without its legal suffix: "Eli Lilly and Company" is "Eli Lilly"."""
    text = re.sub(r"\s*(,?\s*(PLC|plc|Inc\.?|AG|A/S|SA|S\.A\.|SE|N\.V\.|Ltd\.?|"
                  r"& Co\.?|Corporation|Corp\.?|Company|Holdings?|Co\.?))+$", "",
                  name or "").strip()
    return re.sub(r"\s+(and|&)$", "", text) or (name or "")


def marketed_text(r: dict) -> str:
    """What a company markets in the area, in words: nothing marketed is a fact and is
    said, never printed as $0."""
    v = r.get("value") or {}
    if v.get("basis") == "none marketed":
        return "nothing marketed"
    if v.get("usd_bn") is None:
        return "marketed value no free data"
    share = f', {pct(v["share"])} of its value' if v.get("share") is not None else ""
    return f'{money(v["usd_bn"])} marketed{share}'


def pipeline_text(r: dict) -> str:
    p = r.get("pipeline") or {}
    if not p.get("assets"):
        return "no pipeline"
    if p.get("usd_bn") is None:
        return "pipeline value no free data"
    return f'{money(p["usd_bn"])} pipeline'


def _mon(day: str) -> str:
    try:
        d = dt.date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return day or ""
    return d.strftime("%b %Y")


def cards(area: str, rows: list, horizon_end: int) -> list:
    """Four findings for the area: its leader, its deepest pipeline, its biggest
    exclusivity risk and its biggest readouts ahead, each picked among the ranked
    companies. Each a title of one line, a headline of at most two and a detail of at most
    three; the whole is the hover."""
    out = []
    # A company with too little on file is never a pick.
    everyone, rows = rows, [r for r in rows if r.get("ranked")]
    ranked = [r for r in rows if r["overall"] is not None]
    if ranked:
        r = ranked[0]
        out.append({"kind": "leader", "title": "Area leader",
                    "headline": f"{short_name(r['name'])} leads at {r['overall']:.0f} of 100, "
                                f"on {r['pillars']} of 4 pillars",
                    "detail": (f"{_cap(marketed_text(r))}; {pipeline_text(r)}, "
                               f"{r['pipeline']['depth']} in Phase 3 or filed.")})
    deep = [r for r in rows if r["scores"]["pipeline"] is not None]
    if deep:
        r = max(deep, key=lambda r: (r["scores"]["pipeline"], r["pipeline"]["usd_bn"] or 0.0))
        top = r["pipeline"]["top"][:3]
        detail = ("Most value in " + ", ".join(f"{d['name']} {money(d['usd_bn'])}"
                                               for d in top) + "." if top else
                  "No pipeline asset here carries a model value.")
        risked = (f"{money(r['pipeline']['usd_bn'])} risked"
                  if r["pipeline"]["usd_bn"] is not None else "no model value")
        out.append({"kind": "pipeline", "title": "Deepest pipeline",
                    "headline": f"{short_name(r['name'])}: {risked}, "
                                f"{r['pipeline']['depth']} in Phase 3 or filed",
                    "detail": detail})
    risky = [r for r in rows if r["durability"]["at_risk_usd_bn"]]
    if risky:
        r = max(risky, key=lambda r: r["durability"]["at_risk_usd_bn"])
        prods = r["durability"]["products"]
        names = ", ".join(f"{p['name']} {p['loe'][:4]}" for p in
                          sorted(prods, key=lambda p: -(p["usd_bn"] or 0))[:3])
        out.append({"kind": "risk", "title": "Biggest exclusivity risk",
                    "headline": f"{short_name(r['name'])}: "
                                f"{money(r['durability']['at_risk_usd_bn'])} of revenue "
                                f"loses exclusivity by {horizon_end}",
                    "detail": f"{pct(r['durability']['share'])} of its revenue here. "
                              f"{names}."})
    else:
        unranked = any(r["durability"]["at_risk_usd_bn"] for r in everyone)
        out.append({"kind": "risk", "title": "Biggest exclusivity risk",
                    "headline": (f"No ranked company loses revenue to exclusivity by "
                                 f"{horizon_end}" if unranked else
                                 f"No revenue on file here loses exclusivity by "
                                 f"{horizon_end}"),
                    "detail": "Read from each product's effective LOE, orphan exclusivity "
                              "left out."})
    staked = [r for r in rows if r["readouts"]["stake_usd_bn"]]
    if staked:
        r = max(staked, key=lambda r: r["readouts"]["stake_usd_bn"])
        ro = r["readouts"]
        top = ", ".join(f"{e['asset']} {_mon(e['date'])} {money(e['usd_bn'])}"
                        for e in ro["top"][:2])
        out.append({"kind": "readouts", "title": "Biggest readouts ahead",
                    "headline": f"{short_name(r['name'])}: {money(ro['stake_usd_bn'])} at "
                                f"stake in {ro['priced']} priced readout"
                                f"{'s' if ro['priced'] != 1 else ''}",
                    "detail": f"{top}. {ro['count']} readouts due by {_mon(ro['last'])}."})
    else:
        n = sum(r["readouts"]["count"] for r in everyone)
        unranked = any(r["readouts"]["stake_usd_bn"] for r in everyone)
        out.append({"kind": "readouts", "title": "Biggest readouts ahead",
                    "headline": ("No ranked company's readout is priced" if unranked
                                 else "No readout here is priced"),
                    "detail": f"{n} readouts are due within 24 months; none carries a "
                              f"modelled swing."})
    return out


# --- from the book -------------------------------------------------------------------
def area(db_path, area_slug: str, verdict_for=None, stakes_for=None, scorecard_for=None,
         cohort=None, today: dt.date | None = None) -> dict | None:
    """The area's page from the book. ``verdict_for(ticker)``, ``stakes_for(ticker)`` and
    ``scorecard_for(indication_id)`` hand back reads already computed (the API passes its
    response cache) or None, when each is computed here."""
    import forecast_view
    name = area_of(area_slug)
    if name is None:
        return None
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        companies = _cohort(conn, cohort)
        assets = _assets(conn, [c["id"] for c in companies])
        mine = [a for a in assets if a["area"] == name]
        ids = [a["id"] for a in mine]
        revenue = _revenue(conn, ids)
        loe = loe_module.for_assets(conn, ids) if ids else {}
    finally:
        conn.close()
    present = {a["company_id"] for a in mine}
    verdicts, stakes = {}, {}
    for c in companies:
        if c["id"] not in present:
            continue
        t = c["ticker"]
        v = verdict_for(t) if verdict_for else None
        if v is None:
            try:
                v = forecast_view.company_verdict(db_path, t)
            except Exception:          # one company's failed book is that company's gap
                v = None
        verdicts[t] = v if (v and v.get("ok", True)) else None
        s = stakes_for(t) if stakes_for else None
        if s is None:
            try:
                s = forecast_view.catalyst_stakes(db_path, t)
            except Exception:
                s = None
        stakes[t] = s
    clinical = clinical_by_company(scored_drugs(db_path, name, scorecard_for, verdict_for))
    rates = fx.latest_usd_rates(db_path)
    return assemble(name, companies, assets, verdicts, revenue, loe, stakes, clinical,
                    rates, today)
