"""Fold a compound into the row that turns out to be the same programme.

Two passes, because a drug can be recorded twice in two different ways.

The first is a derived compound and the marketed product it became. The pipeline derives
a compound from the drug each trial names, and the registry names drugs by ingredient;
marketed products arrive from openFDA under their brand. So one drug could sit in the
database twice, once as "Jaypirca" with an approval and once as "Pirtobrutinib" with five
trials, and the second row read as an unapproved compound in the pipeline. Across the
universe, 34 compounds were running Phase 4 studies, which only an approved product can
run.

The second is two derived rows for one programme, which the first pass cannot see. Every
match there runs through the canonical name, and canonical() strips parentheticals first,
because a study's own "(LEN)" or "(SG)" is per protocol. That is right for abbreviations
and wrong for a development code: Dyne's Phase 3 registers "zeleciment basivarsen
(DYNE-101)" and its Phase 1/2 registers "DYNE-101", the parenthetical is thrown away, the
two names no longer agree, and the pipeline showed Dyne four programmes when it has two,
each drug split across the phase it was in when each trial was written. So the second pass
matches on the development code instead, which identifies a programme exactly.

Three guards keep the code pass from merging things that are not the same drug, each one
taken from a case in the universe:

- A name carrying two different codes is a combination or a dual name, not a duplicate.
  "MET233 and MET097" is two compounds and "AZD9291 in combination with AZD6094" is a
  regimen; folding either into a single agent would attribute one drug's study to another.
- Two rows that differ by radioisotope are a diagnostic and a therapeutic, not one
  programme. Novartis develops [68Ga]Ga-DWJ155 and [177Lu]Lu-DWJ155 as separate products.
- A token that looks like a code but names a target, an isotope or a rating scale is not
  one. "KYV-101 anti-CD19 CAR-T cell therapy" carries one development code, not two.

Matching stays within one company in both passes: two firms can develop compounds with
similar names, and a merge across owners would be a fabricated relationship. The losing
row's trials move to the survivor and the empty row goes, so a merge cannot lose a study
or leave a duplicate behind.

Idempotent: a second run finds nothing to merge.
"""

from __future__ import annotations

import re

import assets_util
import programme_alias
import trial_mapping
import db
import trial_mapping

# A development code: at least two letters, then digits, optionally hyphenated. DYNE-101,
# MK-1403, AZD6234, BNT323, LY4515100. Two letters minimum because a single one in front
# of a number is usually a fragment of something else: Rocket's RP-L201 truncates to
# "L201" and reads as a programme of its own.
_CODE = re.compile(r"\b([A-Z]{2,6}[A-Z0-9]{0,4}-?\d{2,5})\b")
_PREFIX = re.compile(r"^([A-Z]+)")

# Prefixes that make a token something other than a company's programme code. Element
# symbols, because a radioligand is written 177Lu or 68Ga and the isotope is not the drug.
_ELEMENTS = {"AC", "AT", "BI", "C", "CU", "F", "GA", "GD", "H", "HO", "I", "IN", "KR",
             "LU", "N", "O", "P", "PB", "RA", "RE", "S", "SM", "SR", "TC", "TH", "TL",
             "XE", "Y", "ZR"}
# Targets and biology, because an intervention name describes what a drug hits as well as
# what it is: "KYV-101 anti-CD19 CAR-T cell therapy" names one programme, not two. Vectors
# and cell lines sit here too: AAVrh74 is a capsid serotype and HEK-293 is what the vector
# is grown in, and neither is a compound anyone is developing.
_BIOLOGY = {"AAV", "AAVRH", "ACE", "ANG", "APOE", "BCMA", "CAR", "CART", "CD", "COV",
            "COVID", "DUX", "EGFR", "FC", "GIP", "GLP", "HBV", "HDL", "HEK", "HER",
            "HIV", "HLA", "HPV", "IGG", "IL", "KRAS", "LDL", "LNP", "LRRC", "MHC", "MMP",
            "NK", "PD", "PDL", "PEG", "PSA", "RH", "RSV", "SARS", "TCR", "TDP", "TNF",
            "VEGF"}
# Rating scales and administrative tokens, which appear in trial titles and arm labels.
_INSTRUMENTS = {"ACR", "ADAS", "ASC", "ASU", "BMI", "EASI", "ECOG", "EQ", "EU", "FDA",
                "FVC", "HBA", "ISO", "ITEM", "KCCQ", "MMSE", "NCT", "NYHA", "PART",
                "PASI", "QOL", "SEC", "SF", "US"}
# Time words, because a filing is full of dates written as one token. "mid-2027" and
# "pre-2018" have the shape of a development code and are neither.
_TIME = {"MID", "PRE", "POST", "END", "EARLY", "LATE", "FY", "CY", "YE", "THROUGH",
         "SINCE", "UNTIL", "BY"}
# Ordinary words that happen to sit in front of a number, and element names written
# out: "for-10" and "gallium-68" both have the shape of a code.
_WORDS = {"FOR", "THE", "AND", "NOT", "ALL", "ANY", "OUR", "ITS", "PER", "VIA", "TOP",
          "NEW", "TWO", "ONE", "ACTINIUM", "COPPER", "FLUORINE", "GALLIUM", "IODINE",
          "LUTETIUM", "RADIUM", "TECHNETIUM", "YTTRIUM", "ZIRCONIUM"}
_NOT_A_CODE = _ELEMENTS | _BIOLOGY | _INSTRUMENTS | _TIME | _WORDS

# A radioisotope written any of the ways the registry writes it: 177Lu, [177Lu]Lu, 68 Ga.
_ISOTOPE = re.compile(r"\[?(\d{1,3})\s?([A-Z][a-z]?)\]?")


# Rows a merge could not move because the survivor already held the same key. Reported
# by merge() so a collapse that loses something says so.
DROPPED: dict = {}


def _canonical_names(asset) -> set:
    """Every canonical spelling a row answers to: its generic, its brand, its code."""
    names = set()
    for field in ("generic_name", "brand_name", "internal_code"):
        value = asset[field] if field in asset.keys() else None
        if not value:
            continue
        canon = trial_mapping.canonical(str(value))
        if canon and len(canon) > 2:
            names.add(canon)
    return names


def find_duplicates(conn, company_id: int) -> list[tuple]:
    """(derived_asset_id, marketed_asset_id) for every unapproved row that names the
    same drug as one of the company's marketed products."""
    marketed = conn.execute(
        "SELECT id, generic_name, brand_name, internal_code FROM assets"
        "  WHERE owner_company_id = ? AND is_marketed = 1", (company_id,)).fetchall()
    by_name: dict = {}
    for row in marketed:
        for name in _canonical_names(row):
            # A name held by two marketed rows identifies neither, so it is dropped
            # rather than merged into whichever came first.
            by_name[name] = None if name in by_name else row["id"]

    pairs = []
    derived = conn.execute(
        "SELECT id, generic_name, brand_name, internal_code FROM assets"
        "  WHERE owner_company_id = ? AND is_marketed = 0", (company_id,)).fetchall()
    for row in derived:
        targets = {by_name[n] for n in _canonical_names(row)
                   if by_name.get(n) is not None}
        if len(targets) == 1:
            pairs.append((row["id"], targets.pop()))
    return pairs


# A brand stripped to what identifies the product. The parenthetical goes because
# openFDA qualifies a brand by presentation, "Paxlovid (Copackaged)" and "Wainua
# (Autoinjector)", while a filer's revenue table prints the brand alone. Case and
# punctuation go because a filer prints KRYSTEXXA and openFDA prints Krystexxa. What
# survives is alphanumeric, so "Prevnar 13" and "Prevnar 20" stay two products.
_QUALIFIER = re.compile(r"\([^)]*\)")


def canonical_brand(name: str) -> str:
    """A brand reduced to the letters and digits that identify the product."""
    return re.sub(r"[^a-z0-9]+", "", _QUALIFIER.sub(" ", name or "").lower())


def _is_identified(row) -> bool:
    """Whether a row carries anything behind its name."""
    return bool(row["generic_name"] or row["internal_code"] or row["approvals"])


def find_brand_duplicates(conn, company_id: int) -> list[tuple]:
    """(survivor_id, [loser_ids]) for one company's marketed rows that share a brand.

    A product reaches the database twice when two sources name it differently: openFDA
    files Pfizer's antiviral as "Paxlovid (Copackaged)" with its ingredient and its NDA,
    and the revenue table files it as "Paxlovid" with nothing. The second row then reads
    as a product with no approval on file, which is the opposite of true.

    Only an unidentified row is folded away, and only into exactly one identified row. Two
    identified rows sharing a brand are left alone: both carry an approval, and choosing
    between them would throw one away on a spelling.
    """
    rows = conn.execute(
        "SELECT id, generic_name, brand_name, internal_code,"
        "       (SELECT COUNT(*) FROM approvals ap WHERE ap.asset_id = assets.id) AS approvals"
        "  FROM assets WHERE owner_company_id = ? AND is_marketed = 1"
        "    AND brand_name IS NOT NULL AND brand_name <> ''", (company_id,)).fetchall()
    groups: dict = {}
    for row in rows:
        brand = canonical_brand(row["brand_name"])
        if len(brand) > 2:
            groups.setdefault(brand, []).append(row)

    pairs = []
    for group in groups.values():
        identified = [r for r in group if _is_identified(r)]
        losers = [r["id"] for r in group if not _is_identified(r)]
        if len(identified) == 1 and losers:
            pairs.append((identified[0]["id"], losers))
    return pairs


# A salt or hydrate is how a molecule is formulated, not which molecule it is. Calquence
# is filed as both acalabrutinib and acalabrutinib maleate, Mekinist as trametinib and
# trametinib dimethyl sulfoxide. Stripping these lets one product's applications agree,
# while a genuinely different active does not: Emend covers aprepitant and fosaprepitant,
# which differ before any salt is removed and so are left apart.
_SALTS = (
    "dimethyl sulfoxide", "hydrochloride", "hydrobromide", "dimeglumine", "besylate",
    "tosylate", "mesylate", "maleate", "succinate", "fumarate", "hemifumarate",
    "tartrate", "citrate", "acetate", "phosphate", "diphosphate", "sulfate", "sulphate",
    "oxalate", "lactate", "gluconate", "carbonate", "bicarbonate", "nitrate", "bromide",
    "chloride", "iodide", "disodium", "sodium", "potassium", "calcium", "magnesium",
    "meglumine", "trometamol", "tromethamine", "arginine", "lysine", "choline",
    "monohydrate", "dihydrate", "trihydrate", "hydrate", "anhydrous", "pentahydrate",
    # Salts met in the universe that the common list misses. "malate" sits beside
    # "maleate" deliberately: Torecan is filed as thiethylperazine under both, and they
    # are two salts of one molecule rather than two molecules.
    "hyclate", "pamoate", "edisylate", "palmitate", "malate", "napsylate", "embonate",
    "valerate", "propionate", "dipropionate", "furoate", "xinafoate", "bitartrate",
)


def canonical_generic(name: str) -> str:
    """A generic name reduced to the molecule, with salt and hydrate words removed."""
    text = " " + re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip() + " "
    for salt in _SALTS:
        text = text.replace(f" {salt} ", " ")
    return re.sub(r"[^a-z0-9]+", "", text)


def find_alias_duplicates(conn) -> list[tuple]:
    """(loser_id, survivor_id) where an asset's own name is recorded as another's alias.

    Casgevy is why this exists. Its studies are registered under CTX001, the filings bind
    the brand to "exa-cel", and nothing on record joins those two, so no derivation can
    reach it. An analyst writes one row saying CTX001 is Casgevy, and the pipeline copy
    folds into the product on the next run rather than being corrected by hand every time.
    """
    pairs = []
    for row in conn.execute(
            """SELECT al.internal_code AS name, al.asset_id AS survivor_id,
                      a.owner_company_id AS company_id
                 FROM asset_aliases al JOIN assets a ON a.id = al.asset_id"""):
        wanted = trial_mapping.aliases(row["name"])
        if not wanted:
            continue
        for other in conn.execute(
                "SELECT id, brand_name, generic_name, internal_code FROM assets"
                " WHERE owner_company_id = ? AND id <> ?",
                (row["company_id"], row["survivor_id"])):
            names: set = set()
            for field in ("brand_name", "generic_name", "internal_code"):
                names |= trial_mapping.aliases(other[field])
            if names & wanted:
                pairs.append((other["id"], row["survivor_id"]))
    return pairs


def find_formulation_duplicates(conn, company_id: int) -> list[tuple]:
    """(survivor_id, [loser_ids]) for one product filed under several applications.

    A marketed product holds one application per formulation and strength: Zithromax is
    seven NDAs for azithromycin, Neoral six for cyclosporine. Each arrived as its own
    asset, so the universe counted one drug as seven and every revenue, exclusivity and
    indication lookup saw a fraction of it.

    The brand and the molecule both have to agree, which is what keeps this apart from the
    brand pass above. That pass refuses to choose between two identified rows, correctly,
    because a shared brand alone can hide two different drugs. Here nothing is being
    chosen: the rows are the same molecule under the same brand from the same company, and
    what differs is which application number the FDA gave the formulation.
    """
    rows = conn.execute(
        "SELECT id, brand_name, generic_name, internal_code FROM assets"
        " WHERE owner_company_id = ? AND is_marketed = 1"
        "   AND COALESCE(brand_name, '') <> '' AND COALESCE(generic_name, '') <> ''",
        (company_id,)).fetchall()
    groups: dict = {}
    for row in rows:
        brand = canonical_brand(row["brand_name"])
        generic = canonical_generic(row["generic_name"])
        if len(brand) > 2 and len(generic) > 2:
            groups.setdefault((brand, generic), []).append(row["id"])
    # The oldest row survives, so the choice is stable across runs and the id an earlier
    # refresh already wrote down keeps meaning the same product.
    return [(min(ids), sorted(ids)[1:]) for ids in groups.values() if len(ids) > 1]


def development_codes(text: str) -> set:
    """Every development code a name carries, ignoring targets, isotopes and scales."""
    out = set()
    for token in _CODE.findall((text or "").upper()):
        prefix = _PREFIX.match(token)
        if prefix and prefix.group(1) in _NOT_A_CODE:
            continue
        out.add(token)
    return out


def _isotope(text: str):
    """(mass, element) for a radiolabelled name, or None. Two rows whose isotopes differ
    are a diagnostic and a therapeutic rather than one programme."""
    match = _ISOTOPE.search(text or "")
    return (match.group(1), match.group(2).lower()) if match else None


def _blob(row) -> str:
    return " ".join(str(row[f]) for f in ("generic_name", "brand_name", "internal_code")
                    if f in row.keys() and row[f])


def find_code_duplicates(conn, company_id: int) -> list[tuple]:
    """(survivor_id, [loser_ids], code) for each group of derived rows sharing a code.

    Only rows carrying exactly one code take part, so a combination or a dual name is left
    alone. The survivor is the row with the most trials, then the longer name, since a name
    that carries both the INN and the code says more than the code alone.
    """
    groups: dict = {}
    for row in conn.execute(
            "SELECT a.id, a.generic_name, a.brand_name, a.internal_code,"
            "       (SELECT COUNT(*) FROM trials t WHERE t.asset_id = a.id) trials"
            "  FROM assets a WHERE a.owner_company_id = ? AND a.is_marketed = 0",
            (company_id,)):
        codes = development_codes(_blob(row))
        if len(codes) == 1:
            groups.setdefault(codes.pop(), []).append(row)

    out = []
    for code, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        isotopes = {i for i in (_isotope(_blob(r)) for r in rows) if i}
        if len(isotopes) > 1:
            continue
        ranked = sorted(rows, key=lambda r: (-r["trials"], -len(_blob(r)), r["id"]))
        out.append((ranked[0]["id"], [r["id"] for r in ranked[1:]], code))
    return out


def _fold_one_per_asset(conn, survivor_id: int, loser_id: int) -> None:
    """Settle the tables that hold exactly one row per asset, before the generic move.

    ``patent_challenges`` is UNIQUE(asset_id): one row saying when a generic first
    challenged the product. Two formulations of one drug are challenged separately, so a
    merge has to choose, and the generic move keeps whichever row the survivor happened to
    hold. That is not a spelling choice, it is a date: across seventeen products it put the
    first Paragraph IV later than the truth, Ozempic by two and a half years and Nexium by
    eight. The earliest is the fact, so the earliest is kept.
    """
    rows = conn.execute(
        "SELECT asset_id, first_submission FROM patent_challenges"
        "  WHERE asset_id IN (?, ?)", (survivor_id, loser_id)).fetchall()
    dates = sorted(r["first_submission"] for r in rows if r["first_submission"])
    if not dates:
        return
    holder = survivor_id if any(r["asset_id"] == survivor_id for r in rows) else loser_id
    conn.execute("UPDATE patent_challenges SET first_submission = ? WHERE asset_id = ?",
                 (dates[0], holder))


def _absorb(conn, survivor_id: int, loser_id: int) -> int:
    """Move everything keyed to the loser onto the survivor and delete the empty row."""
    # An application number is how a marketed product is looked up, so a folded row would
    # be recreated by the next openFDA or Orange Book refresh and the merge would undo
    # itself daily. The number is recorded against the survivor instead, which stops the
    # churn and keeps a fact worth having: which applications make up one product.
    code = conn.execute("SELECT internal_code FROM assets WHERE id = ?",
                        (loser_id,)).fetchone()
    if code and code[0]:
        conn.execute(
            "INSERT INTO asset_aliases (internal_code, asset_id, note)"
            " VALUES (?, ?, 'absorbed by merge') ON CONFLICT(internal_code)"
            " DO UPDATE SET asset_id = excluded.asset_id", (code[0], survivor_id))
    _fold_one_per_asset(conn, survivor_id, loser_id)
    moved = conn.execute("UPDATE trials SET asset_id = ? WHERE asset_id = ?",
                         (survivor_id, loser_id)).rowcount
    # Anything else keyed to the losing row follows the trials, so the delete cannot
    # orphan a mapping or break a foreign key. Where the survivor already holds the same
    # key, the move is skipped and the duplicate dropped: it is the same fact recorded
    # twice, and the copy kept is the one on the row that survives.
    for table in assets_util.referring_tables(conn):
        if table == "trials":
            continue                      # already moved, and counted, above
        conn.execute(f"UPDATE OR IGNORE {table} SET asset_id = ? WHERE asset_id = ?",
                     (survivor_id, loser_id))
        # Whatever would not move collided with a row the survivor already holds, so it
        # is the same fact twice and the survivor's copy is kept. Counted rather than
        # dropped in silence, because that is how a real loss would look too.
        stuck = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE asset_id = ?",
                             (loser_id,)).fetchone()[0]
        if stuck:
            DROPPED[table] = DROPPED.get(table, 0) + stuck
        conn.execute(f"DELETE FROM {table} WHERE asset_id = ?", (loser_id,))
    conn.execute("DELETE FROM assets WHERE id = ?", (loser_id,))
    return moved


def merge(db_path=None) -> dict:
    """Both passes: derived into marketed, then derived rows that share a code."""
    conn = db.get_connection(db_path)
    DROPPED.clear()
    merged = moved = by_code = 0
    try:
        companies = [r["id"] for r in conn.execute("SELECT id FROM companies")]
        for company_id in companies:
            for derived_id, marketed_id in find_duplicates(conn, company_id):
                moved += _absorb(conn, marketed_id, derived_id)
                merged += 1
        # After the marketed pass, so a row that belongs to an approved product is folded
        # there rather than into a sibling derived row that is about to disappear.
        for company_id in companies:
            for survivor_id, losers, code in find_code_duplicates(conn, company_id):
                for loser_id in losers:
                    moved += _absorb(conn, survivor_id, loser_id)
                    merged += 1
                    by_code += 1
                # The code identified the merge, so it is written down. Every one of these
                # rows was derived from a trial's intervention name and carries no code of
                # its own, which is what let the duplicate form in the first place.
                conn.execute(
                    "UPDATE assets SET internal_code = COALESCE(internal_code, ?),"
                    "  updated_at = datetime('now') WHERE id = ?", (code, survivor_id))
        # Last, because it folds an unidentified row into an identified one and the two
        # passes above can leave a fresh pair behind.
        by_brand = 0
        for company_id in companies:
            for survivor_id, losers in find_brand_duplicates(conn, company_id):
                for loser_id in losers:
                    moved += _absorb(conn, survivor_id, loser_id)
                    merged += 1
                    by_brand += 1
        by_alias = 0
        # The hand-kept names first, so an override applies on a database rebuilt from
        # scratch rather than only where someone remembered to write the row.
        programme_alias.load_curated(conn)
        # A row whose own name is an alias of another asset. The filing pass writes
        # those aliases, and an analyst writes the ones no filing gives up, so this is
        # also the path a curated override takes: name the programme against the product
        # and the row folds on the next run.
        for loser_id, survivor_id in find_alias_duplicates(conn):
            moved += _absorb(conn, survivor_id, loser_id)
            merged += 1
            by_alias += 1

        # A programme that turns out to be a product already sold, linked by the way the
        # company introduces it in its own filings. Before the formulation pass, so the
        # trials land on the row that pass will keep.
        for link in programme_alias.find_links(conn):
            moved += _absorb(conn, link["marketed_id"], link["programme_id"])
            # The programme name is recorded against the product, or the next refresh
            # derives the pipeline row again from the same intervention and the merge
            # undoes itself.
            conn.execute(
                "INSERT INTO asset_aliases (internal_code, asset_id, note)"
                " VALUES (?, ?, ?) ON CONFLICT(internal_code) DO UPDATE SET"
                "   asset_id = excluded.asset_id",
                (link["code"], link["marketed_id"],
                 f"development name of {link['brand']}, from the filings"))
            merged += 1
            by_alias += 1

        # One product filed under several application numbers. Last, so the passes above
        # have already settled which row is the product.
        by_formulation = 0
        for company_id in companies:
            for survivor_id, losers in find_formulation_duplicates(conn, company_id):
                for loser_id in losers:
                    moved += _absorb(conn, survivor_id, loser_id)
                    merged += 1
                    by_formulation += 1
        conn.commit()
    finally:
        conn.close()
    return {"merged": merged, "trials_moved": moved, "by_code": by_code,
            "by_brand": by_brand, "by_formulation": by_formulation,
            "by_alias": by_alias, "duplicate_rows_collapsed": dict(DROPPED)}
