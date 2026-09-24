"""Assets the book calls pipeline whose molecule is already approved.

An asset stays at ``is_marketed = 0`` until ``approvals_openfda`` matches it, and that
fetcher matches an approval to a company by the company's own sponsor name. So an approval
is invisible whenever it sits under someone else's: a licensee, a subsidiary acquired after
the filing, or a generic applicant. The asset then goes on looking like a Phase 3 medicine
with a label to come.

That is not a cosmetic problem, because it decides whether an asset can be valued at all
and how. A Phase 3 row gets a probability of success and an uptake curve built from a
comparator; an approved product gets its own revenue. Three found by hand in one session,
each a different flavour:

  Alectnib            a misspelling of alectinib, which Roche has sold as Alecensa since
                      2015 and which earned CHF 1,562mm in 2025
  Inclisiran 300 mg   Leqvio, under a development description rather than the brand
  Linerixibat         approved 17 March 2026 as Lynavoy under NDA220295, whose sponsor
                      openFDA gives as Intercept while Glaxo Operations UK is the other
                      labeller on the NDC, so it is GSK's molecule and not GSK's label

Across the 378 unmodelled late-stage assets, 133 carry a name shaped like an ingredient
rather than a development code, and 15 of those 133 have an FDA approval under some
sponsor.

WHAT THIS DOES AND DOES NOT DECIDE. It reports; it changes nothing. Two questions are
tangled together and only the first can be answered from a drug approval record:

  is the molecule approved?   Yes, and then the asset is not a Phase 3 bet whatever the
                              phase column says.
  whose value is it?          Not answerable here. An approval under Zydus means eltrombopag
                              now has a generic, which matters to Novartis' Promacta line as
                              a loss of exclusivity and not as an approval it won. An
                              approval under Intercept means the US revenue is Intercept's
                              and GSK's economics are whatever the licence says, which no
                              free source gives.

So the sponsor is reported beside the approval and the reading is left to an analyst. A
module that promoted these to marketed on its own would have moved Zydus' generic into
Novartis' revenue.
"""

from __future__ import annotations

import re

# A word that could be an ingredient rather than a development code: letters and hyphens
# only, long enough to be a stem. "Linerixibat" yes, "GSK4532990" and "PF-07055480" no,
# because a drugsfda search on a code returns nothing and checking one only spends a
# request. Applied to the first word rather than the whole name, so "Efgartigimod PH20 SC"
# still searches efgartigimod while "HZ/su vaccine" searches nothing.
_INN_SHAPED = re.compile(r"^[A-Za-z][A-Za-z\-]{5,}$")

# Words that make a name a description of a regimen or a dose rather than a molecule.
_NOT_A_MOLECULE = ("placebo", "standard of care", "comparator", "monotherapy", "combination",
                   "higher dose", "co-formulated", "test formulation")


def ingredient_of(brand: str | None, generic: str | None) -> str | None:
    """The ingredient to search a drug approval register for, or None.

    Prefers the generic name, because that is what a register is keyed on. Only the first
    word is tested, so "Efgartigimod PH20 SC" searches efgartigimod and "Inclisiran sodium
    300 mg" searches inclisiran, while "HZ/su vaccine" and "GSK4532990" search nothing.
    """
    for value in (generic, brand):
        if not value:
            continue
        text = value.strip()
        if any(word in text.lower() for word in _NOT_A_MOLECULE):
            continue
        head = text.split()[0] if text.split() else ""
        if _INN_SHAPED.fullmatch(head):
            return head
    return None


def candidates(conn) -> list[dict]:
    """Every asset the book calls unmodelled and late stage, with an ingredient to check."""
    rows = conn.execute(
        """
        SELECT DISTINCT a.id AS asset_id, c.ticker, a.brand_name, a.generic_name
          FROM assets a JOIN companies c ON c.id = a.owner_company_id
          JOIN asset_indications ai ON ai.asset_id = a.id
         WHERE ai.phase IN ('Phase 2', 'Phase 2/Phase 3', 'Phase 3')
           AND a.is_marketed = 0
         ORDER BY c.ticker, a.id
        """).fetchall()
    out = []
    for row in rows:
        ingredient = ingredient_of(row["brand_name"], row["generic_name"])
        if ingredient:
            out.append({"asset_id": row["asset_id"], "ticker": row["ticker"],
                        "brand_name": row["brand_name"],
                        "generic_name": row["generic_name"], "ingredient": ingredient})
    return out


def read_approval(payload: dict) -> dict | None:
    """The first approval in a drugsfda response, or None where there is none.

    ``submission_status`` "AP" is an approval; a "TA" is a tentative one, which a generic
    gets while the reference product still has exclusivity and which is not the molecule
    reaching the market.
    """
    results = (payload or {}).get("results") or []
    if not results:
        return None
    record = results[0]
    approvals = [s.get("submission_status_date") for s in record.get("submissions") or []
                 if s.get("submission_status") == "AP" and s.get("submission_status_date")]
    application = record.get("application_number") or ""
    return {
        "application": application,
        # An ANDA is a generic of someone else's product and an approval of it is a loss of
        # exclusivity for the originator, not a win for anybody in this universe.
        "is_generic": application.startswith("ANDA"),
        "sponsor": record.get("sponsor_name"),
        "brands": sorted({p.get("brand_name") for p in record.get("products") or []
                          if p.get("brand_name")}),
        "first_approval": min(approvals) if approvals else None,
    }


def owned_by(sponsor: str | None, company_name: str | None) -> bool:
    """Whether the approval's sponsor looks like the company that owns the asset.

    Deliberately crude, a shared leading word, because the alternative is a table of every
    corporate name a sponsor field has ever carried. False only means the sponsor is
    someone else's name, which is the thing worth reading, not that the value is not the
    company's: Array Biopharma is Pfizer and ImmunoGen is AbbVie.
    """
    if not sponsor or not company_name:
        return False
    first = re.split(r"[^A-Za-z]+", company_name.strip())
    head = (first[0] if first else "").lower()
    return bool(head) and head in sponsor.lower()


def findings(rows: list[dict]) -> list[dict]:
    """The reportable subset: an asset called pipeline whose molecule is approved.

    ``rows`` is what ``candidates`` returned, each with an ``approval`` from
    ``read_approval`` attached by the caller, which is where the network lives.
    """
    out = []
    for row in rows:
        approval = row.get("approval")
        if not approval or not approval.get("first_approval"):
            continue
        reading = ("the molecule has a generic, so this is a loss of exclusivity for "
                   "whoever owns the brand rather than an approval anyone won"
                   if approval["is_generic"] else
                   "approved under this company's own name, so the row is stale and the "
                   "asset is marketed" if row.get("owned") else
                   "approved under another company's name, so the molecule is marketed and "
                   "whose value it is depends on a licence this cannot see")
        out.append({**row, "reading": reading})
    return out
