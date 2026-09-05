"""The development name a marketed product used to go by, read from the company's filings.

A drug is registered under its programme name and sold under a brand, and the two rarely
share a letter. So the same drug sits in the database twice: Enhertu with an approval and
no studies, "trastuzumab deruxtecan" with thirteen studies and no approval, the second
read as an unapproved compound in the pipeline. Of 297 marketed products with revenue on
file, only 116 had a single trial against them.

The link is written down in the filings, because a company introduces its own product the
same way every time: "CASGEVY (exagamglogene autotemcel [exa-cel])", "Cobenfy (KarXT)".
That construction is the evidence, and it has to be the construction rather than nearness.
Matching a programme name to any brand within ninety characters finds seventy-seven links
of which most are false, because a filing's pipeline table lists a dozen products in a
row: it paired ABBV-313 with Rinvoq and retatrutide with Omvoh, which would have moved one
drug's trials onto another product. Requiring the name to sit inside the parenthetical
that follows the brand, or the brand inside the programme's, finds sixteen and every one
is right.

What this cannot reach is a programme whose filings never name it beside the brand. Casgevy
is the example: the filings bind it to "exa-cel" and the registry files the studies under
"CTX001", and nothing on file joins those two. That is what the override table is for.
"""

from __future__ import annotations

import collections
import csv
import pathlib
import re

CURATED = (pathlib.Path(__file__).resolve().parent.parent
           / "data" / "asset_alias_map.csv")


def load_curated(conn, path=None) -> int:
    """Write the hand-kept programme names into ``asset_aliases``. Returns rows written.

    Run before the merge and on every refresh, so an override survives a database rebuilt
    from scratch. It carries a name and nothing else: no date, no figure, no phase. What
    follows from it still comes from the registry.
    """
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return 0
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    written = 0
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        name = (row.get("programme_name") or "").strip()
        brand = (row.get("brand") or "").strip()
        if not (ticker and name and brand):
            continue
        # Brand or generic. A compound in development has no brand yet, so a target
        # column that only matched brand_name could merge a development code into a
        # marketed product and never into another compound. That is the wrong way round:
        # the duplicates that need merging most are pipeline pairs, where the registry
        # files one study under a radiolabel or a dose arm and another under the compound.
        # Brand still wins where both match, so a launched product is never shadowed.
        asset = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ?
                  AND (LOWER(TRIM(a.brand_name)) = LOWER(?)
                       OR LOWER(TRIM(a.generic_name)) = LOWER(?))
                ORDER BY (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)) DESC,
                         a.is_marketed DESC, a.id LIMIT 1""",
            (ticker, brand, brand, brand)).fetchone()
        if not asset:
            continue          # the product is not on file yet; nothing to point at
        conn.execute(
            "INSERT INTO asset_aliases (internal_code, asset_id, note) VALUES (?, ?, ?)"
            " ON CONFLICT(internal_code) DO UPDATE SET asset_id = excluded.asset_id,"
            "   note = excluded.note",
            (name, asset["id"], f"curated: {(row.get('note') or '').strip()}"))
        written += 1
    return written


# The naming constructions a company actually uses to introduce a product. Anchored on the
# punctuation, so a pipeline table listing many drugs in sequence matches none of them.
_PATTERNS = (
    # Enhertu (fam-trastuzumab deruxtecan), Casgevy (exagamglogene autotemcel [exa-cel])
    r"{name}\s*(?:®|™|®|™)?\s*[\(\[][^()\[\]]{{0,70}}{code}",
    # trastuzumab deruxtecan (Enhertu)
    r"{code}\s*(?:®|™|®|™)?\s*[\(\[][^()\[\]]{{0,70}}{name}",
    r"{name}[^.]{{0,40}}\bformerly\b[^.]{{0,25}}{code}",
    r"{code}[^.]{{0,40}}\bnow\s+(?:known\s+as|marketed\s+as|sold\s+as)\b[^.]{{0,25}}{name}",
)

# Short names collide with ordinary words and with each other, so they are not evidence.
MIN_NAME = 5


def alias_hits(text: str, name: str, code: str) -> int:
    """How many times the text introduces ``name`` as ``code``, or the reverse."""
    if not text or len(name or "") < MIN_NAME or len(code or "") < MIN_NAME:
        return 0
    n, c = re.escape(name.lower()), re.escape(code.lower())
    return sum(len(re.findall(p.format(name=n, code=c), text.lower()))
               for p in _PATTERNS)


# How far either side of a mention the construction can reach. The longest pattern is a
# brand, a symbol, a bracket and seventy characters of generic name.
WINDOW = 150


def _windows(blob: str, code: str) -> list:
    """The stretches of text around each mention of ``code``, or nothing if it is absent."""
    out, start = [], blob.find(code)
    while start != -1:
        out.append(blob[max(0, start - WINDOW):start + len(code) + WINDOW])
        start = blob.find(code, start + len(code))
    return out


def _names(row) -> list:
    return [x for x in (row["generic_name"], row["internal_code"], row["brand_name"]) if x]


def find_links(conn) -> list[dict]:
    """[{programme_id, marketed_id, code, brand, hits}] for programmes that are a product.

    Only within one company, and only where exactly one marketed product answers. Two
    candidates means the filing's wording does not decide it, and a guess here moves a
    drug's whole trial history onto the wrong product.
    """
    programmes: dict = collections.defaultdict(list)
    marketed: dict = collections.defaultdict(list)
    for row in conn.execute(
            """SELECT a.id, a.owner_company_id, a.brand_name, a.generic_name,
                      a.internal_code, a.is_marketed,
                      (SELECT COUNT(*) FROM trials t WHERE t.asset_id = a.id) AS trials
                 FROM assets a"""):
        names = _names(row)
        if not names:
            continue
        entry = (row["id"], names, row["trials"])
        if row["is_marketed"]:
            marketed[row["owner_company_id"]].append(entry)
        elif row["trials"]:
            programmes[row["owner_company_id"]].append(entry)

    text: dict = collections.defaultdict(list)
    for row in conn.execute(
            "SELECT company_id, text FROM filing_sections WHERE text IS NOT NULL"):
        text[row["company_id"]].append((row["text"] or "").lower())

    links = []
    for company_id, rows in programmes.items():
        blobs = text.get(company_id) or []
        sellers = marketed.get(company_id) or []
        if not blobs or not sellers:
            continue
        # The patterns are applied to a window around each mention of the programme
        # name, never to a whole document. A 10-K section runs to tens of thousands of
        # characters and the regex is the expensive part; the construction being looked
        # for spans a hundred at most.
        sellers = [(mid, [n.lower() for n in names if len(n) >= MIN_NAME])
                   for mid, names, _ in sellers]
        for programme_id, names, _ in rows:
            code = min(names, key=len).lower()
            if len(code) < MIN_NAME:
                continue
            hits: collections.Counter = collections.Counter()
            for blob in blobs:
                for window in _windows(blob, code):
                    for marketed_id, seller_names in sellers:
                        for name in seller_names:
                            if name not in window:
                                continue
                            found = alias_hits(window, name, code)
                            if found:
                                hits[marketed_id] += found
                                break
            # One answer or none. Ambiguity is refused rather than resolved by counting,
            # because the loser of a close count is still a different drug.
            if len(hits) == 1:
                marketed_id = next(iter(hits))
                brand = conn.execute("SELECT brand_name, generic_name FROM assets"
                                     " WHERE id = ?", (marketed_id,)).fetchone()
                links.append({"programme_id": programme_id, "marketed_id": marketed_id,
                              "code": code, "hits": hits[marketed_id],
                              "brand": brand["brand_name"] or brand["generic_name"]})
    return links
