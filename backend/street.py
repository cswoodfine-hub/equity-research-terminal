"""The book against the street, company by company, today.

Whether the book beats the market is a twelve-month question and ``call_log.score`` is
answering it. Whether the book agrees with the street is answerable this morning, and
it is the first thing anyone serious asks, because a valuation that disagrees with the
market *and* with every analyst covering the name is making two claims, and a reader
should see both.

``consensus_estimates`` carries genuine vintages: a price target per company with its
range and the count behind it, and for the larger names the street's revenue for the
guided year. This reads the newest of each beside the book's own figures from the same
day's call. Nothing here says who is right. It says where the book stands alone, where
it stands with the street against the price, and where the three agree, and it keeps
the count of analysts beside each target because a target from two is not a consensus.

Two disagreements are reported separately and must not be added. The target gap is the
book's value against the street's mid, both per share. The revenue gap is the book's
modelled revenue for the guided year against the street's, both in the filer's own
currency, and only where the book has a revenue split for that year. A company can
agree on revenue and disagree on value, which is the book's conventions showing, and
that is the more useful finding of the two.
"""

from __future__ import annotations

import db
import consensus

# A target carried by fewer analysts than this is reported but not read as the street.
MIN_ANALYSTS = 3


def _analysts(note: str | None) -> int | None:
    """The count behind a target, from the note's own 'n buy, m hold, k sell'."""
    import re
    got = re.findall(r"(\d+)\s+(?:buy|hold|sell)", note or "")
    return sum(int(x) for x in got) if got else None


def build(db_path=None) -> dict:
    conn = db.get_connection(db_path)
    try:
        companies = [dict(r) for r in conn.execute(
            "SELECT id, ticker, name FROM companies ORDER BY ticker")]
        rows = []
        for co in companies:
            call = conn.execute(
                """SELECT as_of, price, fair_value, upside_12m, cohort FROM model_calls
                    WHERE ticker = ? ORDER BY as_of DESC LIMIT 1""", (co["ticker"],)).fetchone()
            latest = consensus.latest(conn, co["id"])
            target = next((e for e in latest if e["metric"] == "PriceTarget"), None)
            revenue = next((e for e in latest if e["metric"] == "Revenue"
                            and e["period"] == "FY2026"), None)
            if not call and not target:
                continue
            row = {"ticker": co["ticker"], "name": co["name"],
                   "cohort": call["cohort"] if call else None,
                   "as_of": call["as_of"] if call else None,
                   "price": call["price"] if call else None,
                   "book": call["fair_value"] if call else None,
                   "book_upside": call["upside_12m"] if call else None,
                   "street": None, "street_low": None, "street_high": None,
                   "analysts": None, "street_as_of": None, "street_upside": None,
                   "target_gap": None, "stance": None,
                   "revenue_book": None, "revenue_street": None, "revenue_gap": None,
                   "revenue_currency": None}
            if target:
                n = _analysts(target.get("note"))
                row.update({"street": target["value"], "street_low": target.get("low"),
                            "street_high": target.get("high"), "analysts": n,
                            "street_as_of": target["as_of"]})
                if call and call["price"] and target["value"]:
                    row["street_upside"] = target["value"] / call["price"] - 1
                if call and call["fair_value"] and target["value"]:
                    row["target_gap"] = call["fair_value"] / target["value"] - 1
                    b_up = (call["fair_value"] / call["price"] - 1) if call["price"] else None
                    s_up = row["street_upside"]
                    thin = n is not None and n < MIN_ANALYSTS
                    if b_up is None or s_up is None:
                        row["stance"] = None
                    elif thin:
                        row["stance"] = "street too thin to read"
                    elif (b_up > 0) == (s_up > 0):
                        row["stance"] = ("both above the price" if b_up > 0
                                         else "both below the price")
                    else:
                        row["stance"] = ("book above, street below" if b_up > 0
                                         else "book below, street above")
            if revenue and revenue.get("value"):
                try:
                    import fair_value
                    split = (fair_value.company(db_path, co["ticker"]) or {}).get("revenue_split") or {}
                    mine = (split.get("modelled") or {}).get("total") if split.get("ok") else None
                    if mine is not None and split.get("year") == 2026:
                        row.update({"revenue_book": mine, "revenue_street": revenue["value"],
                                    "revenue_currency": revenue.get("currency"),
                                    "revenue_gap": mine / revenue["value"] - 1})
                except Exception:                                   # noqa: BLE001
                    pass
            rows.append(row)
    finally:
        conn.close()

    read = [r for r in rows if r["stance"] and "thin" not in r["stance"]]
    stances = {}
    for r in read:
        stances[r["stance"]] = stances.get(r["stance"], 0) + 1
    gaps = sorted(r["target_gap"] for r in read if r["target_gap"] is not None)
    return {
        "benchmark_note": "agreement, not accuracy: call_log.score measures accuracy as "
                          "the horizons close",
        "rows": sorted(rows, key=lambda r: (r["target_gap"] is None, r["target_gap"] or 0)),
        "totals": {
            "companies": len(rows),
            "with_a_target": sum(1 for r in rows if r["street"] is not None),
            "readable": len(read),
            "stances": stances,
            "median_target_gap": gaps[len(gaps) // 2] if gaps else None,
            "alone": sum(1 for r in read if r["stance"] in
                         ("book above, street below", "book below, street above")),
            "with_revenue": sum(1 for r in rows if r["revenue_gap"] is not None),
        },
    }
