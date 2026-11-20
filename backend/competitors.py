"""Whether a copy of a marketed product is on the market, product by product.

The book dates a product's loss of exclusivity and, until this module, did not ask what
followed it. A date can mean a generic launched that day or that a twelve-year clock ran
out on a biologic nobody has copied, and the two behave nothing alike afterwards: three
or more years on, revenue is falling a median 19% a year where a competitor is on the
market and is flat where none is (docs/research/off_patent_tail).

Three registers answer, and each says a different thing:

  FDA Paragraph IV list   the date the first generic began selling. A launch.
  FDA Purple Book         the biosimilars licensed against a reference product, and
                          whether each is still listed. A licence, not a launch: every
                          etanercept biosimilar is licensed and none is sold.
  A filer's own statement its annual report saying a generic or biosimilar is on its
                          market (data/competitor_launches.csv, and the "expired" rows
                          of data/disclosed_loe.csv). The only evidence of a biosimilar
                          launch, and the only evidence outside the United States.

The record keeps them apart. ``status`` is the strongest thing the evidence supports:

  on the market                    a launch is on file
  licensed, launch not confirmed   a biosimilar is licensed and listed; no filer has
                                   said it is selling
  licensed, not launched           licensed, and the reference product's owner says
                                   none has launched
  licensed, none marketed          licensed, and every presentation discontinued
  none licensed                    a biologic with no biosimilar licence at all
  none recorded                    a small molecule with no generic launch on the list,
                                   which is silence and not proof: the list starts in
                                   2004 and records Paragraph IV launches only

The valuation reads one thing from it, ``selling``: whether a competitor is on the US
market against a product whose loss of exclusivity is already behind it. Such a product
goes on falling (forecast.build, data/erosion_defaults.csv tail_decay_pct); one with
nothing copying it holds. Everything else here is a view.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import pathlib
import re

import db
import loe

DATA = db.BACKEND_DIR.parent / "data"
LAUNCHES = DATA / "competitor_launches.csv"
DISCLOSED = DATA / "disclosed_loe.csv"

ON_MARKET = "on the market"
LICENSED = "licensed, launch not confirmed"
NOT_LAUNCHED = "licensed, not launched"
SHELVED = "licensed, none marketed"
# What a filer can say short of a launch: nothing has, or one is licensed and has not.
_DENIALS = ("none", "licensed, not launched")
NONE_LICENSED = "none licensed"
NONE_RECORDED = "none recorded"
# A device or a presentation after the brand, which is still the brand.
PRESENTATIONS = {"solostar", "flexpen", "penfill", "kwikpen", "pen", "sureclick",
                 "autoinjector", "pfs", "sensoready", "onpro", "onbody", "flextouch"}
# Words in a filer's stated basis that say a competitor is selling.
_SELLING = ("generic marketed", "generic entry", "generic competition", "biosimilar")
# And words that say it is only expected: a date agreed in a settlement or anticipated by
# the filer is a competitor that is coming. Its passing is not the filer saying it came.
_EXPECTED = ("anticipated", "settled", "expected")


def _rows(path) -> list[dict]:
    path = pathlib.Path(path)
    if not path.exists():
        return []
    return [dict(r) for r in _read(str(path), path.stat().st_mtime_ns)]


@functools.lru_cache(maxsize=8)
def _read(path: str, _stamp: int) -> tuple:
    """A curated file, read once for as long as it does not change: the valuation asks
    for every asset it builds."""
    with open(path, newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(l for l in handle if not l.lstrip().startswith("#")))


def _words(name: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (name or "").lower())


def is_reference(brand: str | None, reference: str | None) -> bool:
    """Whether an asset's brand is the reference product a biosimilar names.

    The same brand, the brand with its device after it (Lantus Solostar), or a reported
    line that is two presentations of one brand (Simponi Simponi Aria). Not a brand that
    merely starts the same: Eylea HD is its own licence and no biosimilar of Eylea's
    copies it.
    """
    mine, ref = _words(brand), _words(reference)
    if not mine or not ref:
        return False
    if mine == ref or set(mine) == set(ref):       # a line reported as two presentations
        return True
    if mine[:len(ref)] == ref:
        rest = mine[len(ref):]
        return all(w in PRESENTATIONS or w in ref for w in rest)
    return False


def biosimilars(conn) -> dict:
    """{reference brand as printed: [licences]} from the Purple Book table."""
    try:
        rows = conn.execute(
            "SELECT * FROM biosimilar_licences ORDER BY approval_date").fetchall()
    except Exception:                       # noqa: BLE001 - no table yet
        return {}
    out: dict = {}
    for row in rows:
        out.setdefault(row["reference_proprietary"], []).append(dict(row))
    return out


def _passed(when: str, today: dt.date) -> str | None:
    """The date or year a filer gave, where it is wholly behind us; None where it is
    ahead, still running, or not a date. A bare year is over when the year is: Roche
    anticipates Perjeta's first biosimilar in 2026, and in November 2026 says none has
    come, so the year alone is not a launch."""
    found = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", when or "")
    if not found:
        return None
    year, month, day = (int(x) if x else None for x in found.groups())
    if day:
        over = dt.date(year, month, day) <= today
    elif month:
        over = (year, month) < (today.year, today.month)
    else:
        over = year < today.year
    return when if over else None


def stated(path=None, disclosed=None, today: dt.date | None = None) -> dict:
    """{(ticker, brand words): [statements]} from the filers' own words.

    The curated launches first, each a quote with its accession. Then the rows of the
    disclosed-dates file where a filer names generic or biosimilar competition as the
    reason for a product's date, which is the same statement already on file for another
    purpose. Such a row counts where the filer calls the exclusivity "expired", or dates
    an entry that has happened. A date the filer only anticipates, or one agreed in a
    settlement, is a competitor that is coming: it is not counted even once it has
    passed, because the filer has not said the competitor came.
    """
    today = today or dt.date.today()
    out: dict = {}
    for row in _rows(path or LAUNCHES):
        key = ((row.get("ticker") or "").upper(), tuple(_words(row.get("product"))))
        out.setdefault(key, []).append({
            "market": row.get("market") or "US", "kind": row.get("kind") or None,
            "status": row.get("status") or ON_MARKET, "launched": row.get("launched") or None,
            "source": " ".join(x for x in (row.get("form"), row.get("accession")) if x),
            "quote": row.get("quote") or ""})
    for row in _rows(disclosed or DISCLOSED):
        basis = (row.get("basis") or "").lower()
        when = (row.get("loe") or row.get("loe_date") or "").strip().lower()
        since = _passed(when, today)
        if not any(w in basis for w in _SELLING):
            continue
        if when != "expired" and (not since or any(w in basis for w in _EXPECTED)):
            continue
        key = ((row.get("ticker") or "").upper(),
               tuple(_words(row.get("asset") or row.get("brand") or row.get("product"))))
        out.setdefault(key, []).append({
            "market": "US", "kind": "biosimilar" if "biosimilar" in basis else "generic",
            "status": ON_MARKET, "launched": since, "source": row.get("basis") or "",
            "quote": row.get("source") or row.get("note") or ""})
    return out


def _is_biologic(modality: str | None, internal_code: str | None) -> bool:
    return "bio" in (modality or "").lower() or (internal_code or "").upper().startswith("BLA")


def for_asset(asset: dict, generic_launched: str | None, licences: dict,
              statements: list) -> dict:
    """One product's record from the three registers. Pure."""
    biologic = _is_biologic(asset.get("modality"), asset.get("internal_code"))
    mine = [lic for ref, group in licences.items() for lic in group
            if is_reference(asset.get("brand_name"), ref)]
    listed = [lic for lic in mine if lic.get("marketing_status") == "Rx"]
    us = [s for s in statements if s.get("market") == "US" and s.get("status") == ON_MARKET]
    denied = [s for s in statements
              if s.get("market") == "US" and s.get("status") in _DENIALS]
    elsewhere = [s for s in statements
                 if s.get("market") != "US" and s.get("status") == ON_MARKET]
    evidence = []
    if generic_launched:
        evidence.append({"register": "FDA Paragraph IV list",
                         "says": f"first generic marketed {generic_launched}"})
    if mine:
        first = min((lic["approval_date"] for lic in mine if lic.get("approval_date")),
                    default=None)
        evidence.append({
            "register": "FDA Purple Book",
            "says": (f"{len(mine)} biosimilar {'licence' if len(mine) == 1 else 'licences'}"
                     f", {len(listed)} still listed" + (f", the first {first}" if first else "")
                     + ": " + ", ".join(sorted({lic["proprietary_name"] for lic in mine})))})
    for s in statements:
        evidence.append({"register": s.get("source") or "filer's statement",
                         "says": (f"{s.get('market')}: {s.get('status')}"
                                  + (f" since {s['launched']}" if s.get("launched") else "")
                                  + (f". \"{s['quote']}\"" if s.get("quote") else ""))})
    if generic_launched or us:
        status = ON_MARKET
        since = generic_launched or next((s["launched"] for s in us if s.get("launched")), None)
        kind = "generic" if generic_launched else (us[0].get("kind") or
                                                  ("biosimilar" if biologic else "generic"))
    elif mine and denied:
        status, since, kind = NOT_LAUNCHED, None, "biosimilar"
    elif listed:
        status, since, kind = LICENSED, None, "biosimilar"
    elif mine:
        status, since, kind = SHELVED, None, "biosimilar"
    elif biologic:
        status, since, kind = NONE_LICENSED, None, None
    else:
        status, since, kind = NONE_RECORDED, None, None
    return {"asset_id": asset.get("id"), "name": asset.get("brand_name")
            or asset.get("generic_name"), "modality": asset.get("modality"),
            "status": status, "kind": kind, "since": since,
            "licensed": len(mine), "listed": len(listed),
            "elsewhere": sorted({s["market"] for s in elsewhere}),
            "evidence": evidence}


def record(conn, ticker: str | None = None, launches=None, disclosed=None,
           today: dt.date | None = None) -> list:
    """Every marketed product's record, or one company's."""
    where = "WHERE a.is_marketed = 1" + (" AND c.ticker = ?" if ticker else "")
    assets = conn.execute(
        "SELECT a.id, a.brand_name, a.generic_name, a.modality, a.internal_code,"
        "       c.ticker FROM assets a JOIN companies c ON c.id = a.owner_company_id "
        + where + " ORDER BY c.ticker, a.brand_name",
        ((ticker.upper(),) if ticker else ())).fetchall()
    generic = loe.generic_launches(conn)
    licences = biosimilars(conn)
    said = stated(launches, disclosed, today)
    out = []
    for a in assets:
        asset = dict(a)
        mine = [s for (t, brand), group in said.items() if t == asset["ticker"]
                and is_reference(asset["brand_name"], " ".join(brand)) for s in group]
        row = for_asset(asset, generic.get(asset["id"]), licences, mine)
        row["ticker"] = asset["ticker"]
        out.append(row)
    return out


def selling(conn, asset_id: int, launches=None, disclosed=None,
            today: dt.date | None = None) -> dict | None:
    """{kind, since, basis} where a generic or biosimilar is on the US market against
    this product, else None. What the valuation reads. ``basis`` is the register that
    says so, in words a note can print."""
    try:
        asset = conn.execute(
            "SELECT a.id, a.brand_name, a.generic_name, a.modality, a.internal_code,"
            "       c.ticker FROM assets a JOIN companies c ON c.id = a.owner_company_id"
            " WHERE a.id = ?", (asset_id,)).fetchone()
    except Exception:                       # noqa: BLE001 - a book with no such tables
        return None
    if asset is None:
        return None
    asset = dict(asset)
    said = stated(launches, disclosed, today)
    mine = [s for (t, brand), group in said.items() if t == asset["ticker"]
            and is_reference(asset["brand_name"], " ".join(brand)) for s in group]
    row = for_asset(asset, loe.generic_launches(conn).get(asset_id), biosimilars(conn), mine)
    if row["status"] != ON_MARKET:
        return None
    return {"kind": row["kind"], "since": row["since"],
            "basis": "; ".join(f"{e['register']}: {e['says']}" for e in row["evidence"])[:400]}
