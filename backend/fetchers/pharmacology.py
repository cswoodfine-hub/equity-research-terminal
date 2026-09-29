"""What each drug is: its mechanism, its targets, its class and its boxed warning.

``assets.mechanism`` and ``assets.target`` were never filled (0 of 2,764 rows on
2026-09-29), so nothing could say that tirzepatide and retatrutide sit on the same
receptor or that a PD-1 antibody and a TIGIT antibody do not. Comparing every candidate
for one indication regardless of modality needs exactly that.

Two free, keyless sources:

- **ChEMBL** (EMBL-EBI) resolves a name to a molecule, and a molecule to its mechanisms
  of action and their targets. Covers the INNs and a good share of the research codes:
  LY3457263 resolves to nisotirostide.
- **openFDA drug labels** give the FDA's pharmacologic classes (mechanism and
  established class), the route and the boxed warning, for anything with a US label.

Matching is exact, never fuzzy. A name is looked up as a ChEMBL synonym, case-insensitive,
and taken only when it resolves to one molecule; a salt form is tried without its salt
word after the name as written. A name that matches nothing is left without a row and
the gap is counted, never filled with the nearest neighbour, because the wrong molecule
is worse than none.

Run for the big pharma companies only, on the assets a landscape shows: marketed, or in
Phase 2 and later, and not retired.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "pharmacology"
TTL_SECONDS = 7 * 24 * 60 * 60     # mechanisms change on a curator's schedule, not daily

CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
_TIMEOUT_S = 60
_POLITE_SLEEP_S = 0.1
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"

LATE = ("Phase 2", "Phase 2/3", "Phase 3")
BOXED_MAX = 1500                   # a boxed warning is read, not archived

# Salt and hydrate words a label's ingredient carries that the molecule's name does not.
# Only tried after the name as written found nothing.
_SALTS = {
    "hydrochloride", "dihydrochloride", "hcl", "sodium", "disodium", "potassium",
    "calcium", "magnesium", "mesylate", "dimesylate", "besylate", "maleate",
    "fumarate", "hemifumarate", "tartrate", "bitartrate", "citrate", "succinate",
    "sulfate", "phosphate", "acetate", "tosylate", "malate", "hydrobromide",
    "monohydrate", "dihydrate", "trihydrate", "hemihydrate", "anhydrous",
    "bromide", "chloride", "meglumine", "tromethamine", "lysine", "arginine",
    "dipropionate", "propionate", "furoate", "valerate", "hyclate", "pegol",
}


def get_json(url: str, params: dict | None = None) -> dict:
    """GET a JSON document. Module level so a test can stand a fixture in for it."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(full, headers={"User-Agent": _USER_AGENT,
                                                    "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # openFDA answers "no match" with a 404, and ChEMBL refuses a name it cannot
        # parse with a 400. Neither is the source being down.
        if exc.code in (400, 404):
            return {}
        raise


# --- pure parsers -----------------------------------------------------------------
def parse_molecules(payload: dict) -> list[dict]:
    """ChEMBL molecule search results, as (id, name, type)."""
    return [{"chembl_id": m.get("molecule_chembl_id"), "name": m.get("pref_name"),
             "molecule_type": m.get("molecule_type")}
            for m in (payload or {}).get("molecules") or []
            if m.get("molecule_chembl_id")]


def parse_mechanisms(payload: dict) -> list[dict]:
    """ChEMBL mechanisms for one molecule."""
    out = []
    for m in (payload or {}).get("mechanisms") or []:
        if not m.get("mechanism_of_action"):
            continue
        out.append({"mechanism": m["mechanism_of_action"],
                    "action_type": m.get("action_type"),
                    "target_chembl_id": m.get("target_chembl_id")})
    return out


def parse_target(payload: dict) -> dict | None:
    if not payload or not payload.get("pref_name"):
        return None
    return {"name": payload["pref_name"], "organism": payload.get("organism"),
            "target_type": payload.get("target_type")}


def parse_label(payload: dict) -> dict | None:
    """The first label openFDA returns: classes, route, boxed warning and set id."""
    results = (payload or {}).get("results") or []
    if not results:
        return None
    label = results[0]
    fda = label.get("openfda") or {}
    boxed = " ".join(label.get("boxed_warning") or []).strip()
    return {"moa": sorted(set(fda.get("pharm_class_moa") or [])),
            "epc": sorted(set(fda.get("pharm_class_epc") or [])),
            "route": sorted(set(fda.get("route") or [])),
            "boxed": _clip(boxed) if boxed else None,
            "set_id": label.get("set_id")}


def _clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= BOXED_MAX else text[:BOXED_MAX].rsplit(" ", 1)[0] + " ..."


def names_for(asset: dict) -> list[str]:
    """The names an asset can be looked up by, most specific first.

    The ingredients a label lists, then the generic name, the internal code and the
    brand. Each is tried as written, then without a salt word. Duplicates dropped.
    """
    ingredients = []
    raw = asset.get("active_ingredients")
    if raw:
        try:
            ingredients = [i for i in json.loads(raw) if isinstance(i, str)]
        except (TypeError, ValueError):
            ingredients = [raw]
    names = []
    for name in ingredients + [asset.get("generic_name"), asset.get("internal_code"),
                               asset.get("brand_name")]:
        if not name or not name.strip() or ";" in name:
            continue
        name = name.strip()
        # An application number is how openFDA filed the product, not a drug name.
        if re.fullmatch(r"(NDA|BLA|ANDA)\s*\d+", name, re.I):
            continue
        names.append(name)
        bare = _without_salt(name)
        if bare and bare != name:
            names.append(bare)
    return list(dict.fromkeys(names))


def _without_salt(name: str) -> str | None:
    words = name.split()
    kept = [w for w in words if w.lower().strip(",") not in _SALTS]
    return " ".join(kept) if kept and len(kept) < len(words) else None


def ingredient_names(asset: dict) -> list[str]:
    """The ingredients of a combination, each to be resolved on its own. Empty for a
    single-ingredient product. A generic name that joins its ingredients with a
    semicolon ("Ethinyl Estradiol; Norethindrone Acetate") is a combination too."""
    raw = asset.get("active_ingredients")
    try:
        items = [i for i in json.loads(raw) if isinstance(i, str)] if raw else []
    except (TypeError, ValueError):
        items = []
    if len(items) <= 1:
        for name in (asset.get("generic_name"), *(items or [])):
            parts = [p.strip() for p in (name or "").split(";") if p.strip()]
            if len(parts) > 1:
                return parts
    return items if len(items) > 1 else []


class PharmacologyFetcher(BaseFetcher):
    """One company's drugs, looked up in ChEMBL and the openFDA labels."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._targets: dict = {}
        self._molecules: dict = {}

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _assets(self, conn) -> list[dict]:
        return [dict(r) for r in conn.execute(
            f"""SELECT a.id, a.generic_name, a.brand_name, a.internal_code,
                       a.active_ingredients, a.is_marketed
                  FROM assets a JOIN companies c ON c.id = a.owner_company_id
                 WHERE c.ticker = ?
                   AND a.id NOT IN (SELECT asset_id FROM retired_programmes)
                   AND (a.is_marketed = 1 OR EXISTS (
                        SELECT 1 FROM asset_indications ai WHERE ai.asset_id = a.id
                           AND ai.phase IN ({",".join("?" * len(LATE))})))""",
            (self.ticker, *LATE))]

    # --- lookups ------------------------------------------------------------------
    def _molecule(self, name: str) -> dict | None:
        """The one ChEMBL molecule this exact name names, or None."""
        key = name.lower()
        if key in self._molecules:
            return self._molecules[key]
        found = parse_molecules(get_json(f"{CHEMBL}/molecule.json", {
            "molecule_synonyms__molecule_synonym__iexact": name, "limit": 3,
            "only": "molecule_chembl_id,pref_name,molecule_type"}))
        if not found:
            found = parse_molecules(get_json(f"{CHEMBL}/molecule.json", {
                "pref_name__iexact": name, "limit": 3,
                "only": "molecule_chembl_id,pref_name,molecule_type"}))
        time.sleep(_POLITE_SLEEP_S)
        # Two molecules for one name is an ambiguity, and an ambiguity is not a match.
        hit = found[0] if len(found) == 1 else None
        self._molecules[key] = hit
        return hit

    def _target(self, chembl_id: str) -> dict | None:
        if chembl_id not in self._targets:
            self._targets[chembl_id] = parse_target(
                get_json(f"{CHEMBL}/target/{chembl_id}.json"))
            time.sleep(_POLITE_SLEEP_S)
        return self._targets[chembl_id]

    def _resolve(self, asset: dict) -> list[dict]:
        """Every ChEMBL molecule the asset is made of: one per ingredient of a
        combination, else the first name that resolves."""
        combo = ingredient_names(asset)
        if combo:
            hits = []
            for ingredient in combo:
                for name in names_for({"active_ingredients": json.dumps([ingredient])}):
                    hit = self._molecule(name)
                    if hit:
                        hits.append({**hit, "matched_on": name})
                        break
            return hits
        for name in names_for(asset):
            hit = self._molecule(name)
            if hit:
                return [{**hit, "matched_on": name}]
        return []

    def _label(self, asset: dict, molecules: list[dict]) -> dict | None:
        """The US label for the molecule, by its generic name. A class and a boxed
        warning belong to the molecule, so any sponsor's label carries them."""
        for name in [m["name"] for m in molecules if m.get("name")] + names_for(asset)[:2]:
            params = {"search": f'openfda.generic_name:"{name}"', "limit": 1}
            key = os.getenv("OPENFDA_API_KEY")
            if key:
                params["api_key"] = key
            got = parse_label(get_json(OPENFDA_LABEL, params))
            time.sleep(_POLITE_SLEEP_S)
            if got:
                return got
        return None

    # --- contract -----------------------------------------------------------------
    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            assets = self._assets(conn)
        finally:
            conn.close()
        out, errors = [], []
        for asset in assets:
            try:
                molecules = self._resolve(asset)
                mechanisms = []
                for m in molecules:
                    mech = parse_mechanisms(get_json(f"{CHEMBL}/mechanism.json", {
                        "molecule_chembl_id": m["chembl_id"], "limit": 50}))
                    time.sleep(_POLITE_SLEEP_S)
                    for x in mech:
                        x["molecule"] = m["chembl_id"]
                        x["target"] = (self._target(x["target_chembl_id"])
                                       if x.get("target_chembl_id") else None)
                    mechanisms.extend(mech)
                # The label only where the drug is on sale somewhere or has a name a
                # label could carry: a code-named Phase 2 asset has none.
                label = (self._label(asset, molecules)
                         if asset["is_marketed"] or molecules else None)
                out.append({"asset_id": asset["id"], "molecules": molecules,
                            "mechanisms": mechanisms, "label": label})
            except Exception as exc:     # one drug's lookup failing is not the run's
                errors.append(f"{asset.get('generic_name') or asset.get('brand_name')}: {exc}")
        return {"assets": out, "errors": errors[:20], "asked": len(assets)}

    def normalise(self, raw) -> list[dict]:
        rows = []
        for a in raw.get("assets") or []:
            aid = a["asset_id"]
            for m in a["molecules"]:
                rows.append({"asset_id": aid, "kind": "molecule_type",
                             "value": m.get("molecule_type") or "unknown",
                             "detail": m.get("name"), "ref": m["chembl_id"],
                             "source": "chembl",
                             "source_url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{m['chembl_id']}/"})
            for x in a["mechanisms"]:
                url = f"https://www.ebi.ac.uk/chembl/compound_report_card/{x['molecule']}/"
                rows.append({"asset_id": aid, "kind": "mechanism", "value": x["mechanism"],
                             "detail": x.get("action_type"), "ref": x.get("target_chembl_id"),
                             "source": "chembl", "source_url": url})
                if x.get("target"):
                    rows.append({"asset_id": aid, "kind": "target",
                                 "value": x["target"]["name"],
                                 "detail": x["target"].get("organism"),
                                 "ref": x.get("target_chembl_id"), "source": "chembl",
                                 "source_url": url})
            label = a.get("label")
            if label:
                url = (f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={label['set_id']}"
                       if label.get("set_id") else None)
                for kind, values in (("moa_class", label["moa"]), ("epc_class", label["epc"]),
                                     ("route", label["route"])):
                    for v in values:
                        rows.append({"asset_id": aid, "kind": kind, "value": v,
                                     "detail": None, "ref": label.get("set_id"),
                                     "source": "openfda_label", "source_url": url})
                if label.get("boxed"):
                    rows.append({"asset_id": aid, "kind": "boxed_warning",
                                 "value": label["boxed"], "detail": None,
                                 "ref": label.get("set_id"), "source": "openfda_label",
                                 "source_url": url})
        self._summary = {"asked": raw.get("asked", 0),
                         "resolved": sum(1 for a in raw.get("assets") or [] if a["molecules"]),
                         "errors": raw.get("errors") or []}
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            summary = getattr(self, "_summary", {})
            self._write_snapshot(conn, {"source": SOURCE, "rows": len(rows),
                                        "asked": summary.get("asked"),
                                        "resolved": summary.get("resolved"),
                                        "fetch_kind": "live"})
            conn.commit()
        finally:
            conn.close()

    def _write_snapshot(self, conn, payload) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
            (self.source, self.entity_key, json.dumps(payload), self.refresh_run_id))

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM asset_pharmacology p JOIN assets a ON a.id = p.asset_id"
                " JOIN companies c ON c.id = a.owner_company_id WHERE c.ticker = ?",
                (self.ticker,)).fetchone()[0]
            self._write_snapshot(conn, {"source": SOURCE, "rows": n, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        """Replace the company's rows with this fetch's. A mechanism ChEMBL withdrew
        should not outlive the withdrawal, and the snapshot above keeps the count."""
        summary = getattr(self, "_summary", {})
        conn = db.get_connection(self.db_path)
        try:
            ids = [r[0] for r in conn.execute(
                "SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id"
                " WHERE c.ticker = ?", (self.ticker,))]
            if ids and (rows or summary.get("asked")):
                conn.execute(f"DELETE FROM asset_pharmacology WHERE asset_id IN "
                             f"({','.join('?' * len(ids))})", ids)
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_pharmacology"
                    " (asset_id, kind, value, detail, ref, source, source_url)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r["asset_id"], r["kind"], r["value"], r["detail"], r["ref"],
                     r["source"], r["source_url"]))
            conn.commit()
        finally:
            conn.close()
        notes = []
        if summary.get("asked"):
            missed = summary["asked"] - summary.get("resolved", 0)
            if missed:
                notes.append(f"{missed} of {summary['asked']} drugs match no ChEMBL "
                             "molecule by exact name")
        return RefreshResult(self.source, len(rows), summary.get("errors") or [], False,
                             0, notes=notes)
