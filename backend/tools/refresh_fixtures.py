"""Rebuild the company-facts test fixtures from the live EDGAR API.

The fixtures are trimmed copies of real payloads: every concept the line map can ask
for, and every entry from CUTOFF onward. Trimming keeps them small enough to read in a
diff while staying faithful in shape, so a test that passes here is testing the same
structure EDGAR serves.

Run this when a line is added to statements.LINES, or when a parser test fails in a way
that looks like the source moved rather than the code breaking. Then read the diff: a
restated prior year is EDGAR doing its job and the expectation should follow it, a line
that vanished is worth understanding before you update anything.

    SEC_USER_AGENT="Name contact@example.com" python tools/refresh_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import statements  # noqa: E402
from fetchers.financials_edgar import (  # noqa: E402
    DEBT_COMBINED_CANDIDATES,
    DEBT_CURRENT_CANDIDATES,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# One US filer with heavy tag drift, one that tags the concepts the first one skips,
# and one IFRS filer that reports annually only.
COMPANIES = {"lly": "0000059478", "jnj": "0000200406", "nvo": "0000353278"}

# Entries older than this are dropped. Six fiscal years of annual history plus the
# quarters inside them is everything the app stores, with a year of margin.
CUTOFF = "2019-01-01"


def wanted_concepts() -> set[str]:
    names = {name for line in statements.LINES for _, name in line.candidates}
    names.update(name for _, name in DEBT_COMBINED_CANDIDATES)
    names.update(name for _, name in DEBT_CURRENT_CANDIDATES)
    names.update({"LongTermDebtNoncurrent", "LongTermDebt",
                  "EntityCommonStockSharesOutstanding"})
    return names


def trim(payload: dict, keep: set[str]) -> dict:
    facts = {}
    for taxonomy, concepts in (payload.get("facts") or {}).items():
        kept = {}
        for name, concept in concepts.items():
            if name not in keep:
                continue
            units = {}
            for unit, entries in (concept.get("units") or {}).items():
                recent = [e for e in entries if (e.get("end") or "") >= CUTOFF]
                if recent:
                    units[unit] = recent
            if units:
                kept[name] = dict(concept, units=units)
        if kept:
            facts[taxonomy] = kept
    return {"cik": payload.get("cik"), "entityName": payload.get("entityName"),
            "facts": facts}


def main() -> int:
    user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        print("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        return 1
    keep = wanted_concepts()
    for slug, cik in COMPANIES.items():
        request = urllib.request.Request(COMPANYFACTS_URL.format(cik=cik),
                                         headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        trimmed = trim(payload, keep)
        path = FIXTURES / f"companyfacts_{slug}.json"
        path.write_text(json.dumps(trimmed, indent=1, sort_keys=True) + "\n")
        concepts = sum(len(c) for c in trimmed["facts"].values())
        print(f"{path.name}: {concepts} concepts, {path.stat().st_size // 1024}kb")
        time.sleep(0.5)   # stay well inside EDGAR's 10 requests per second
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
