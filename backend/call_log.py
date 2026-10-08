"""The model's calls, recorded each day as they were made, and scored as the market answers.

A disagreement with the price is not an edge until it is shown to be right more often than
chance. That needs a record of what the model said on the day, before the outcome was known,
which no later rebuild of the book can produce honestly: a value recomputed today for a past
date carries everything learnt since. So the record is written once a day, at the end of the
scheduled refresh, and a row is never updated (``model_calls`` and ``gate_calls``, migration
085). The history export carries both tables, so the daily commit is the dated proof.

Scoring (``score``) asks two questions of the record:

- Does the model's 12-month upside rank the companies by what they then returned against
  the sector? Per day, the rank correlation (Spearman) between the upside and the return
  over the horizon less PPH's, averaged over days: the information coefficient. The same is
  done for the analysts' targets, so the model is scored against the street, not in a vacuum.
  The hit rate is the share of calls whose upside had the sign of the excess return, and the
  spread is the top third's excess return less the bottom third's.
- Are the gate odds calibrated? A gate is scored on the last call before its readout: the
  Brier score, and the share that passed in each band of odds.

Horizons are calendar days from the close the call was made against. A call is scored at a
horizon only once the horizon has passed and a close exists within five days of its end.
Daily calls overlap, so the days are not independent; the count of days a horizon apart is
reported beside the average so the evidence is not overstated.

Off when ``ER_TOOL_CALL_LOG=0``, which the test suite sets, so a test that runs the
scheduled refresh never values the book.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

import db

HORIZONS = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}
BENCHMARK = "PPH"
# A horizon's end must have a close within this many days, so a stale price never stands in
# for the end of a window.
END_SLACK_DAYS = 5
MIN_NAMES = 5                       # a day's cross-section needs at least this many calls
ODDS_BANDS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))
LENS_MIDS = {"targets": "target", "pe_ntm": "pe_mid", "ev_sales": "ev_sales_mid",
             "precedents": "precedents_mid"}


def enabled() -> bool:
    return os.getenv("ER_TOOL_CALL_LOG", "1") != "0"


def code_version() -> str | None:
    """The commit that computed the calls: the runner's own on GitHub, else the checkout's."""
    if os.getenv("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                             cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def modelled_tickers(conn) -> list[str]:
    """Every company the model values: one with at least one asset carrying assumptions."""
    return [r[0] for r in conn.execute(
        """SELECT DISTINCT c.ticker FROM companies c
             JOIN assets a ON a.owner_company_id = c.id
             JOIN assumptions s ON s.asset_id = a.id
            ORDER BY c.ticker""")]


def _cohort(conn, ticker: str, db_path) -> str | None:
    try:
        import engines
        import fx
        import productivity
        cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()[0]
        rates = fx.latest_usd_rates(db_path)
        return engines.assign(conn, cid, productivity.latest_revenue(conn, cid, rates))
    except Exception:
        return None


def _call_row(as_of, ticker, fair, cohort, version, run_id) -> dict | None:
    """The day's company call from ``fair_value.company``, or None when it did not value."""
    if not fair or not fair.get("ok") or fair.get("equity_per_share") is None:
        return None
    rating = fair.get("rating") if isinstance(fair.get("rating"), dict) else {}
    lenses = {lens.get("key"): lens for lens in fair.get("lenses") or []
              if isinstance(lens, dict)}
    target = lenses.get("targets") or {}
    row = {
        "as_of": as_of, "ticker": ticker, "cohort": cohort,
        "price": rating.get("close") if rating.get("close") is not None else fair.get("close"),
        "price_date": str(fair.get("price_date") or "")[:10] or None,
        "fair_value": fair.get("equity_per_share"),
        "value_today": rating.get("value_today"), "low_today": rating.get("low_today"),
        "high_today": rating.get("high_today"), "forward_12m": rating.get("forward_12m"),
        "upside_12m": rating.get("upside_12m"),
        "rating": rating.get("rating") if rating.get("ok", True) else None,
        "cost_of_equity": rating.get("cost_of_equity"),
        "target_low": target.get("low"), "target_mid": target.get("mid"),
        "target_high": target.get("high"),
        "code_version": version, "refresh_run_id": run_id,
    }
    for key, column in LENS_MIDS.items():
        if column != "target":
            row[column] = (lenses.get(key) or {}).get("mid")
    return row


def _gate_rows(as_of, ticker, stakes, price, version, run_id) -> list[dict]:
    """The day's priced gates from ``forecast_view.catalyst_stakes``, each leg a share."""
    shares = (stakes or {}).get("diluted_shares")
    out = []
    for g in (stakes or {}).get("priced") or []:
        if not isinstance(g, dict) or not g.get("priced"):
            continue
        per = (lambda v: v / shares if v is not None and shares else None)
        out.append({
            "as_of": as_of, "ticker": ticker, "catalyst_id": g.get("id"),
            "asset_id": g.get("asset_id"), "asset_name": g.get("asset_name"),
            "gate": g.get("gate"), "gate_label": g.get("gate_label"),
            "trial": g.get("gate_trial") or g.get("trial"),
            "expected_date": g.get("expected_date"),
            "date_confidence": g.get("date_confidence"), "p_gate": g.get("p_gate"),
            "pos_now": g.get("pos_now"), "pos_success": g.get("pos_success"),
            "pos_failure": g.get("pos_failure"),
            "per_share_now": per(g.get("rnpv_now")),
            "per_share_success": per(g.get("rnpv_success")),
            "per_share_failure": per(g.get("rnpv_failure")),
            "price": price, "code_version": version, "refresh_run_id": run_id,
        })
    return out


def _insert(conn, table: str, row: dict) -> bool:
    cols = list(row)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
    return cur.rowcount == 1


def record(db_path=None, as_of: str | None = None, run_id: int | None = None,
           tickers: list[str] | None = None, fair_fn=None, stakes_fn=None) -> dict:
    """Write the day's calls: one per modelled company and one per priced gate. A company
    already recorded for the day is left as it was, so a second run never rewrites a call.
    ``fair_fn`` and ``stakes_fn`` are injectable for tests."""
    if not enabled():
        return {"skipped": "ER_TOOL_CALL_LOG=0"}
    if fair_fn is None or stakes_fn is None:
        import fair_value
        import forecast_view
        fair_fn = fair_fn or (lambda t: fair_value.company(db_path, t))
        stakes_fn = stakes_fn or (lambda t: forecast_view.catalyst_stakes(db_path, t))
    as_of = as_of or dt.datetime.now(dt.timezone.utc).date().isoformat()
    version = code_version()
    conn = db.get_connection(db_path)
    written = {"as_of": as_of, "calls": 0, "gates": 0, "kept": 0, "errors": []}
    try:
        for ticker in tickers if tickers is not None else modelled_tickers(conn):
            try:
                row = _call_row(as_of, ticker, fair_fn(ticker),
                                _cohort(conn, ticker, db_path), version, run_id)
                if row is None:
                    continue
                if _insert(conn, "model_calls", row):
                    written["calls"] += 1
                else:
                    written["kept"] += 1
                for g in _gate_rows(as_of, ticker, stakes_fn(ticker), row["price"],
                                    version, run_id):
                    written["gates"] += int(_insert(conn, "gate_calls", g))
                conn.commit()
            except Exception as exc:          # one company never stops the record
                written["errors"].append(f"{ticker}: {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    return written


# --- scoring -------------------------------------------------------------------------
def _close_on(conn, ticker: str, day: str) -> tuple | None:
    """(date, close) of the last daily close on or before ``day``."""
    row = conn.execute(
        """SELECT substr(p.as_of, 1, 10) AS d, p.close FROM prices p
             JOIN companies c ON c.id = p.company_id
            WHERE c.ticker = ? AND p.interval = '1d' AND p.close IS NOT NULL
              AND substr(p.as_of, 1, 10) <= ?
            ORDER BY p.as_of DESC LIMIT 1""", (ticker, day)).fetchone()
    return (row["d"], row["close"]) if row else None


def _bench_on(conn, day: str) -> tuple | None:
    row = conn.execute(
        """SELECT substr(as_of, 1, 10) AS d, close FROM benchmark_prices
            WHERE symbol = ? AND close IS NOT NULL AND substr(as_of, 1, 10) <= ?
            ORDER BY as_of DESC LIMIT 1""", (BENCHMARK, day)).fetchone()
    return (row["d"], row["close"]) if row else None


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else None


def _excess(conn, call, days: int, today: dt.date) -> float | None:
    """The call's return over ``days`` from its close, less PPH's over the same dates."""
    start = call["price_date"] or call["as_of"]
    if not call["price"] or not start:
        return None
    end = dt.date.fromisoformat(start) + dt.timedelta(days=days)
    if end > today:
        return None
    stock, bench0 = _close_on(conn, call["ticker"], end.isoformat()), _bench_on(conn, start)
    bench1 = _bench_on(conn, end.isoformat())
    if not (stock and bench0 and bench1 and bench0[1]):
        return None
    if (end - dt.date.fromisoformat(stock[0])).days > END_SLACK_DAYS or \
            (end - dt.date.fromisoformat(bench1[0])).days > END_SLACK_DAYS:
        return None
    return (stock[1] / call["price"] - 1) - (bench1[1] / bench0[1] - 1)


def _horizon_score(by_day: dict, days: int) -> dict:
    """Average the per-day cross-sections for one predictor at one horizon."""
    ics, hits, spreads, n_calls = [], [], [], 0
    for day in sorted(by_day):
        pairs = by_day[day]
        n_calls += len(pairs)
        if len(pairs) < MIN_NAMES:
            continue
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        ic = spearman(xs, ys)
        if ic is not None:
            ics.append((day, ic))
        hits += [(x > 0) == (y > 0) for x, y in pairs if x != 0]
        ranked = sorted(pairs)
        third = max(1, len(ranked) // 3)
        spreads.append(sum(y for _x, y in ranked[-third:]) / third
                       - sum(y for _x, y in ranked[:third]) / third)
    # Days a full horizon apart, the honest count of independent windows.
    spaced, last = 0, None
    for day, _ic in ics:
        d = dt.date.fromisoformat(day)
        if last is None or (d - last).days >= days:
            spaced, last = spaced + 1, d
    return {"calls": n_calls, "days": len(ics), "independent_days": spaced,
            "ic": sum(i for _d, i in ics) / len(ics) if ics else None,
            "hit_rate": sum(hits) / len(hits) if hits else None,
            "top_minus_bottom": sum(spreads) / len(spreads) if spreads else None}


def _gate_outcomes(conn) -> dict:
    """Resolved gates: {catalyst_id: (date, passed)} from the calendar's own resolutions,
    and {(company_id, drug lower, phase): [(date, passed)]} from the companies' announced
    results, read where the drug and phase match the gate's."""
    # A catalyst resolved by hand is dated by when its row changed to met or missed.
    by_catalyst = {r["id"]: (str(r["d"] or "")[:10], r["status"] == "met")
                   for r in conn.execute(
                       "SELECT id, status, COALESCE(updated_at, expected_date) AS d"
                       " FROM catalysts WHERE status IN ('met', 'missed')")}
    announced: dict = {}
    for r in conn.execute("SELECT company_id, drug, phase, outcome, event_date FROM"
                          " trial_readouts WHERE outcome IN ('positive', 'negative')"):
        key = (r["company_id"], (r["drug"] or "").strip().lower(), r["phase"])
        announced.setdefault(key, []).append((str(r["event_date"])[:10],
                                              r["outcome"] == "positive"))
    return {"catalyst": by_catalyst, "announced": announced}


def _gate_phase(gate: str | None) -> int | None:
    g = (gate or "").lower()
    return 3 if g.startswith("p3") else 2 if g.startswith("p2") else None


def _calibration(conn) -> dict:
    """Each resolved gate on the last call made before it resolved: Brier score and the
    share that passed in each band of odds."""
    outcomes = _gate_outcomes(conn)
    cid_of = {r["ticker"]: r["id"] for r in conn.execute("SELECT id, ticker FROM companies")}
    last: dict = {}
    for g in conn.execute("SELECT * FROM gate_calls WHERE p_gate IS NOT NULL ORDER BY as_of"):
        resolved = outcomes["catalyst"].get(g["catalyst_id"])
        if resolved is None:
            key = (cid_of.get(g["ticker"]), (g["asset_name"] or "").strip().lower(),
                   _gate_phase(g["gate"]))
            later = [o for o in outcomes["announced"].get(key, []) if o[0] > g["as_of"]]
            resolved = min(later) if later else None
        if resolved is None or resolved[0] <= g["as_of"]:
            continue
        last[(g["ticker"], g["catalyst_id"])] = (g["p_gate"], resolved[1])
    scored = list(last.values())
    bands = []
    for lo, hi in ODDS_BANDS:
        inside = [passed for p, passed in scored if lo <= p < hi]
        bands.append({"odds": f"{lo:.0%} to {min(hi, 1):.0%}", "gates": len(inside),
                      "passed": (sum(inside) / len(inside)) if inside else None})
    return {"resolved": len(scored),
            "brier": (sum((p - float(passed)) ** 2 for p, passed in scored) / len(scored)
                      if scored else None),
            "bands": bands}


def score(db_path=None, today: dt.date | None = None, cohort: str | None = None) -> dict:
    """The record scored so far, per horizon, for the model's upside and the analysts'
    targets, and the gate odds' calibration. ``cohort`` limits the companies scored."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        sql = "SELECT * FROM model_calls WHERE upside_12m IS NOT NULL"
        args: tuple = ()
        if cohort:
            sql, args = sql + " AND cohort = ?", (cohort,)
        calls = conn.execute(sql + " ORDER BY as_of", args).fetchall()
        first = calls[0]["as_of"] if calls else None
        horizons = {}
        for name, days in HORIZONS.items():
            model, street = {}, {}
            for c in calls:
                ex = _excess(conn, c, days, today)
                if ex is None:
                    continue
                model.setdefault(c["as_of"], []).append((c["upside_12m"], ex))
                if c["target_mid"] and c["price"]:
                    street.setdefault(c["as_of"], []).append(
                        (c["target_mid"] / c["price"] - 1, ex))
            horizons[name] = {"days": days, "model": _horizon_score(model, days),
                              "street": _horizon_score(street, days),
                              "first_scored": (dt.date.fromisoformat(first)
                                               + dt.timedelta(days=days)).isoformat()
                              if first else None}
        return {"benchmark": BENCHMARK, "today": today.isoformat(), "cohort": cohort,
                "calls": len(calls), "first_call": first,
                "companies": len({c["ticker"] for c in calls}),
                "horizons": horizons, "gates": _calibration(conn)}
    finally:
        conn.close()


def history(db_path=None, ticker: str = "") -> list[dict]:
    """Every call on file for one company, oldest first."""
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM model_calls WHERE ticker = ? ORDER BY as_of", (ticker.upper(),))]
    finally:
        conn.close()
