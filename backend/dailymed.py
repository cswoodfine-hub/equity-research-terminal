"""DailyMed: structured product labels, and the population inside them.

NIH publishes the full Structured Product Label for every marketed product with
complete version history, free, no key. This module is the two halves of using it:
the network calls (search, version history, the SPL XML) and the pure parsers that
turn each response into the fields the tracker stores. The parsers take strings, so
they test against saved fixtures without a network.

The population is extracted, never invented: the LLM seam reads only the indications
section and returns the age bounds and indication count, or nulls when the label
does not state them. Without a model key the raw section is still stored and a
version increment is still detected; the richer fields simply stay null.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import llm

_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
_HL7 = "urn:hl7-org:v3"
INDICATIONS_LOINC = "34067-9"          # Indications and usage section
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30


# --- network --------------------------------------------------------------
def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8")


def search(drug_name: str, pagesize: int = 5) -> str:
    return _get(f"{_BASE}/spls.json?drug_name="
                f"{urllib.parse.quote(drug_name)}&pagesize={pagesize}")


def history(setid: str) -> str:
    return _get(f"{_BASE}/spls/{setid}/history.json")


def spl_xml(setid: str) -> str:
    return _get(f"{_BASE}/spls/{setid}.xml")


# --- pure parsers ---------------------------------------------------------
def parse_search(payload: str, brand: str, generic: str = None) -> str | None:
    """The set id whose title names the product. Matched on the brand, then the
    generic, both uppercased, so a search that returns a combination product or a
    near-name does not bind the wrong label."""
    data = json.loads(payload).get("data") or []
    wanted = [w.upper() for w in (brand, generic) if w]
    for token in wanted:
        for row in data:
            if token in (row.get("title") or "").upper():
                return row.get("setid")
    return None


def parse_history(payload: str) -> dict | None:
    """The current version: the highest spl_version and its published date."""
    entries = (json.loads(payload).get("data") or {}).get("history") or []
    versions = [e for e in entries if e.get("spl_version") is not None]
    if not versions:
        return None
    latest = max(versions, key=lambda e: int(e["spl_version"]))
    return {"spl_version": int(latest["spl_version"]),
            "published_date": latest.get("published_date")}


def parse_indications(xml_text: str) -> str | None:
    """The Indications and usage section (LOINC 34067-9) as collapsed plain text.

    None when the label carries no such section, which is honest: a product with no
    parseable indications block has no population to extract rather than an empty one.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for section in root.iter(f"{{{_HL7}}}section"):
        code = section.find(f"{{{_HL7}}}code")
        if code is not None and code.get("code") == INDICATIONS_LOINC:
            text = " ".join("".join(node.itertext()) for node in section.iter())
            text = re.sub(r"\s+", " ", text).strip()
            return text or None
    return None


# --- population extraction, over the LLM seam -----------------------------
_SYSTEM = """You read one drug label's indications and usage section and return \
strict JSON describing the treated population. Use only the text given.

Return exactly these keys:
- age_floor_years: the youngest age the label indicates, in years, as a number, or \
null if the label states no lower age bound. A neonate is 0, "6 months" is 0.5.
- age_ceiling_years: the oldest age bound in years, or null if none is stated \
(most labels state none; return null, do not guess 100).
- indication_count: how many distinct indications the section lists, as an integer.
- population_text: one short phrase naming the population, at most 12 words.

Never infer a value the text does not support. Return the JSON object and nothing \
else."""


def _parse_json(text: str) -> dict:
    """The JSON out of a model reply, tolerant of a code fence."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def extract_population(indications_text: str, complete=None) -> dict:
    """{age_floor_years, age_ceiling_years, indication_count, population_text}.

    All null when there is no indications text or no model configured, so the fields
    are absent rather than fabricated. ``complete`` is injectable for tests.
    """
    empty = {"age_floor_years": None, "age_ceiling_years": None,
             "indication_count": None, "population_text": None}
    if not indications_text:
        return empty
    complete = complete or (llm.complete if llm.provider() is not None else None)
    if complete is None:
        return empty
    try:
        reply = complete(_SYSTEM, indications_text[:6000], 300)
        data = _parse_json(reply)
    except Exception:
        return empty

    def _num(value):
        return value if isinstance(value, (int, float)) else None

    count = data.get("indication_count")
    return {
        "age_floor_years": _num(data.get("age_floor_years")),
        "age_ceiling_years": _num(data.get("age_ceiling_years")),
        "indication_count": int(count) if isinstance(count, (int, float)) else None,
        "population_text": (str(data["population_text"])[:120]
                            if data.get("population_text") else None),
    }
