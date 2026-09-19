"""What stands between enterprise value and the shareholders, beyond cash and debt.

The sum of the parts ends at net cash: cash minus debt, nothing else. A pharma balance
sheet carries more claims than that, and they run both ways. A pension deficit is
deferred pay the company owes. Contingent consideration is a deal instalment it has
promised. A minority interest is a slice of a consolidated subsidiary whose whole revenue
the book already values. An investment held at equity is a business the book does not
value at all, because its revenue is not consolidated and no product line carries it.

Each is filed, and most are tagged, so they are read rather than estimated. The SEC
Financial Statement Data Sets keep every tag of every filing with the accession as its
version, and the product revenue fetcher already caches them, which is the same route
``selling_costs`` uses to recover a line the companyfacts API drops.

Three rules keep this honest.

A negative minority interest is taken as nil, not as a credit. GSK's non-controlling
interests are minus £421mm, because the accounting puts ViiV's preferential dividend
arrangement there, and reading that as £421mm of value for GSK's own shareholders would
invert what the arrangement is: ViiV's minorities are owed money, not owing it.

An investment held at equity is taken at its carrying value, which is what the filer
states and not what the stake is worth. Sanofi's 48.2% of Opella is carried at
€3,259mm against a transaction that valued the whole business far higher, so this is a
floor on that asset and is marked as one.

A claim the filer does not quantify is not quantified here either. J&J reversed $7.0bn of
talc reserves in 2025 when the settlement route failed and returned to the tort system,
and says it "is unable to estimate the possible loss or range of loss" beyond the $3.4bn
it holds for executed settlements and defence. The $3.4bn is taken; the tail is named in
the note and left out of the arithmetic, because a number invented for it would be the
largest unsourced figure in the book.
"""

from __future__ import annotations

import csv
import io
import pathlib
import zipfile

CACHE_DIR = pathlib.Path(__file__).resolve().parent / "cache"
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
CURATED = DATA_DIR / "other_claims.csv"
ANNUAL_FORMS = ("10-K", "20-F")

# Each item, the sign it carries into equity, and the concepts that hold it. Order is
# priority; where an item names several tags that are parts rather than alternatives
# (a current and a non-current half), ``sum_parts`` adds the ones present.
ITEMS: dict[str, dict] = {
    "noncontrolling_interests": {
        "sign": -1, "floor_at_nil": True,
        "label": "non-controlling interests",
        "tags": ("MinorityInterest", "NoncontrollingInterests")},
    "pension_deficit": {
        "sign": -1,
        "label": "pension and post-employment deficit",
        "tags": ("PensionAndOtherPostretirementDefinedBenefitPlansLiabilitiesNoncurrent",
                 "NoncurrentRecognisedLiabilitiesDefinedBenefitPlan",
                 "NoncurrentProvisionsForEmployeeBenefits",
                 "DefinedBenefitPensionPlanLiabilitiesNoncurrent")},
    "contingent_consideration": {
        "sign": -1, "sum_parts": True,
        "label": "contingent consideration owed on past deals",
        "tags": ("ContingentConsiderationLiabilities",
                 "BusinessCombinationContingentConsiderationLiabilityNoncurrent",
                 "BusinessCombinationContingentConsiderationLiabilityCurrent")},
    "equity_method_investments": {
        "sign": 1,
        "label": "businesses held at equity, not in the book",
        "tags": ("EquityMethodInvestments", "InvestmentAccountedForUsingEquityMethod",
                 "InvestmentsInAssociatesAccountedForUsingEquityMethod")},
}


def _instants(rows: list[dict], adsh: str) -> tuple[str | None, dict]:
    """(the latest balance sheet date in the filing, {tag: {value, unit}}) for the
    unsegmented instants of one filing. Pure."""
    live = [r for r in rows
            if r.get("adsh") == adsh and r.get("qtrs") == "0"
            and not (r.get("segments") or "").strip()
            and not (r.get("coreg") or "").strip()]
    latest = max((r["ddate"] for r in live), default=None)
    out: dict = {}
    for row in live:
        if row["ddate"] != latest:
            continue
        try:
            value = float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue
        out.setdefault(row["tag"], {"value": value, "unit": row.get("uom"),
                                    "tag": row["tag"]})
    return latest, out


def from_filing(rows: list[dict], adsh: str) -> dict:
    """{item: {value, unit, tag, as_of}} for every claim the filing tags. Pure.

    A value is in the unit the filer reports, which is the unit net cash is read in.
    """
    as_of, tagged = _instants(rows, adsh)
    found: dict = {}
    for item, spec in ITEMS.items():
        if spec.get("sum_parts"):
            parts = [tagged[t] for t in spec["tags"] if t in tagged]
            if parts:
                found[item] = {"value": sum(p["value"] for p in parts),
                               "unit": parts[0]["unit"], "as_of": as_of,
                               "tag": " + ".join(p["tag"] for p in parts)}
            continue
        for tag in spec["tags"]:
            if tag in tagged:
                found[item] = {**tagged[tag], "as_of": as_of}
                break
    return found


# A quarter's numeric file is hundreds of megabytes, so it is read once per build, for
# the CIKs asked for, by splitting lines rather than building a dict per row. The result
# is stored (``store``) and the valuation reads the table, because parsing this on the way
# to a share price would cost minutes per company.
_WANTED_COLS = ("adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg",
                "value")


def _rows_for(archive: zipfile.ZipFile, adshs: set) -> dict:
    """{adsh: [row dicts]} for the wanted filings, read straight off num.txt."""
    out: dict = {a: [] for a in adshs}
    with archive.open("num.txt") as handle:
        stream = io.TextIOWrapper(handle, "latin-1")
        header = next(stream).rstrip("\n").split("\t")
        index = {name: header.index(name) for name in _WANTED_COLS if name in header}
        adsh_at = index.get("adsh", 0)
        for line in stream:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= adsh_at:
                continue
            found = out.get(parts[adsh_at])
            if found is None:
                continue
            found.append({name: (parts[at] if at < len(parts) else "")
                          for name, at in index.items()})
    return out


def build(ciks, cache_dir: pathlib.Path = CACHE_DIR) -> dict:
    """{cik: {adsh, form, filed, items}} for each CIK's latest annual filing in the
    cached data sets. Newest archive first, so a filer filing twice keeps its latest."""
    want = set()
    for cik in ciks:
        try:
            want.add(str(int(cik)))
        except (TypeError, ValueError):
            continue
    out: dict = {}
    for path in sorted(cache_dir.glob("fsds_*.zip"), reverse=True):
        left = want - set(out)
        if not left:
            break
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            continue
        with archive:
            with archive.open("sub.txt") as handle:
                subs = {r["adsh"]: r
                        for r in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                                delimiter="\t")
                        if r.get("cik") in left and r.get("form") in ANNUAL_FORMS}
            if not subs:
                continue
            rows = _rows_for(archive, set(subs))
        for adsh, sub in subs.items():
            out[sub["cik"]] = {"adsh": adsh, "form": sub.get("form"),
                               "filed": sub.get("filed"),
                               "items": from_filing(rows[adsh], adsh)}
    return out


def store(conn, cache_dir: pathlib.Path = CACHE_DIR, curated_path=None) -> dict:
    """Write every company's claims to ``other_claims``, filed and curated together.

    Run after a refresh, like the asset merge: the data sets change quarterly and the
    curated file when a filing is read, and neither belongs in the path to a price.
    """
    companies = {r["ticker"]: r for r in conn.execute(
        "SELECT id, ticker, cik FROM companies WHERE cik IS NOT NULL")}
    filings = build([r["cik"] for r in companies.values()], cache_dir)
    curated_rows = curated(curated_path)
    written, seen = 0, set()
    for ticker, company in companies.items():
        lines = _lines(filings.get(str(int(company["cik"]))), ticker, curated_rows)
        for line in lines:
            conn.execute(
                """INSERT INTO other_claims (company_id, item, label, value, sign, unit,
                     as_of, basis, source, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, item) DO UPDATE SET
                     label = excluded.label, value = excluded.value,
                     sign = excluded.sign, unit = excluded.unit, as_of = excluded.as_of,
                     basis = excluded.basis, source = excluded.source,
                     note = excluded.note, updated_at = datetime('now')""",
                (company["id"], line["item"], line["label"], line["value"],
                 line["sign"], line.get("unit"), line.get("as_of"), line.get("basis"),
                 line.get("source"), line.get("note")))
            written += 1
            seen.add((company["id"], line["item"]))
    # A claim a filer has settled or stopped tagging is removed, so the table says what
    # the latest filing says rather than accumulating history.
    stale = 0
    for row in conn.execute("SELECT company_id, item FROM other_claims").fetchall():
        if (row["company_id"], row["item"]) not in seen:
            conn.execute("DELETE FROM other_claims WHERE company_id = ? AND item = ?",
                         (row["company_id"], row["item"]))
            stale += 1
    conn.commit()
    return {"written": written, "removed": stale, "companies": len(companies)}


def curated(path=None) -> dict:
    """{ticker: [{item, label, value, sign, as_of, source, note}]} read from the curated
    file: claims a filing states in words or inside an aggregate, where no tag isolates
    them."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return {}
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out: dict = {}
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        try:
            value = float((row.get("value") or "").strip())
        except ValueError:
            continue
        if not ticker or not (row.get("item") or "").strip():
            continue
        sign = -1 if (row.get("kind") or "").strip().lower() == "liability" else 1
        out.setdefault(ticker, []).append({
            "item": row["item"].strip(), "label": (row.get("label") or "").strip(),
            "value": value, "sign": sign, "as_of": (row.get("as_of") or "").strip(),
            "source": (row.get("source") or "").strip(),
            "note": (row.get("note") or "").strip(), "basis": "filed, curated"})
    return out


def _lines(filing: dict | None, ticker: str, curated_rows: dict) -> list[dict]:
    """Every claim for one company, filed and curated, shaped for storage. Pure."""
    lines = []
    for item, found in (filing or {}).get("items", {}).items():
        spec = ITEMS[item]
        value, note = found["value"], ""
        if spec.get("floor_at_nil") and value < 0:
            note = (f"filed at {value / 1e6:,.0f}mm, taken as nil: a negative book value "
                    f"is not a credit to the parent's shareholders")
            value = 0.0
        lines.append({"item": item, "label": spec["label"], "value": value / 1e6,
                      "sign": spec["sign"], "as_of": found["as_of"],
                      "unit": found["unit"], "basis": "filed",
                      "source": f"{filing['form']} {filing['adsh']}, XBRL {found['tag']}",
                      "note": note})
    for row in curated_rows.get((ticker or "").upper(), []):
        lines.append({**row, "unit": None})
    return lines


def for_company(conn, ticker: str) -> dict:
    """Every claim outside cash and debt for one company, and its net effect on equity.

    ``total`` is in the reporting currency's millions, signed the way net cash is:
    positive adds to equity. Read from the table ``store`` wrote, so this costs a query.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT o.item, o.label, o.value, o.sign, o.unit, o.as_of, o.basis, o.source,
                  o.note FROM other_claims o JOIN companies c ON c.id = o.company_id
            WHERE c.ticker = ? ORDER BY o.sign, o.item""", (ticker,))]
    return {"lines": rows, "total": sum(r["sign"] * r["value"] for r in rows),
            "reason": None if rows else "no claims outside cash and debt on file"}
