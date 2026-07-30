"""When a drug was first approved, from every free route there is.

The approvals table comes from openFDA's drugsfda, and asking it alone leaves most of a
large company's revenue undated. Three separate reasons, each with its own fix.

Alliance products. Pfizer books Eliquis revenue and Bristol Myers holds the application;
Sanofi books Dupixent and Regeneron holds it. Looking for an approval under the company
that reports the revenue finds nothing, though the drug is approved and the date is
already in the table under someone else. So the last route matches on the drug's name
across every company.

Biologics. drugsfda is CDER's register and does not carry BLAs, so vaccines, cell
therapies and most antibody products are simply absent: Shingrix, Prevnar, Comirnaty,
Casgevy and Padcev have no row. The Purple Book does carry them, and although it
publishes no approval column the twelve-year reference product exclusivity is computed
from first licensure, so subtracting twelve years recovers the date the statute was
counting from. That is a derivation rather than a reading and is labelled as one.

Naming. The same product is "Paxlovid" in a revenue table and "Paxlovid (Copackaged)" in
drugsfda, so matching is done on a normalised form with parentheticals and punctuation
removed.

And a last resort for what none of that reaches. drugsfda is CDER's register, so it
returns 404 for the BLA numbers behind Shingrix, Comirnaty and Elevidys: no vaccine and
few gene therapies are in it at all. openFDA's NDC directory does list them, and gives
the date a package began marketing. That is not an approval date and is never treated as
one. A product cannot be marketed before it is approved, so the figure errs in one
direction only, toward looking newer, which is why the route runs last and why the label
it returns says marketing rather than approval.

Every answer carries the route that produced it, because they are not equally direct and
a reader deciding whether to trust a date needs to know which one it came from.
"""

from __future__ import annotations

import re

# What the twelve-year biologic exclusivity is counted from. The Purple Book fetcher
# stores the floor as licensure plus this; going back the same distance returns it.
BIOLOGIC_EXCLUSIVITY_YEARS = 12
_FLOOR_TYPE = "reference product exclusivity (12y)"

# Below this length a containment match is a coincidence rather than a drug: "ivo" sits
# inside a dozen brand names. Seven characters is long enough that sharing a run of them
# means sharing a name.
MIN_CONTAINMENT = 7

_PARENTHETICAL = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(name: str) -> str:
    """A brand name reduced to what two spellings of the same drug share.

    Parentheticals go first: drugsfda writes "Paxlovid (Copackaged)" for the product a
    revenue table calls "Paxlovid", and they are the same drug.
    """
    text = _PARENTHETICAL.sub(" ", (name or "").lower())
    return _NON_ALNUM.sub("", text)


def _own_approval(conn, asset_id: int):
    row = conn.execute(
        "SELECT MIN(approval_date) d FROM approvals WHERE asset_id = ?",
        (asset_id,)).fetchone()
    return (row["d"], "openFDA approval") if row and row["d"] else (None, None)


def _biologic_licensure(conn, asset_id: int):
    """The licensure date recovered from the biologic exclusivity floor."""
    row = conn.execute(
        f"SELECT MIN(date(expiry_date, '-{BIOLOGIC_EXCLUSIVITY_YEARS} years')) d"
        "  FROM exclusivities WHERE asset_id = ? AND protection_type = ?",
        (asset_id, _FLOOR_TYPE)).fetchone()
    return (row["d"], "Purple Book licensure") if row and row["d"] else (None, None)


def _ndc_marketing(conn, asset_id: int, name: str | None):
    """The date openFDA's NDC directory first records this brand being marketed.

    The last resort, and the only one that reaches a vaccine: drugsfda is CDER's register
    and returns 404 for BLA125614, BLA125742 and BLA125781, so Shingrix, Comirnaty and
    Elevidys have no approval anywhere else here.

    It is a marketing date and is labelled as one wherever it surfaces. A product cannot
    be marketed before it is approved, so the figure is never too early and is sometimes
    much too late: Comirnaty's oldest surviving package is the 2025 seasonal formulation,
    four years after licensure. That one-way error is why this route runs last.
    """
    row = conn.execute(
        "SELECT MIN(n.first_marketed) d FROM ndc_products n"
        "  JOIN assets a ON a.owner_company_id = n.company_id"
        " WHERE a.id = ? AND n.first_marketed IS NOT NULL"
        "   AND (upper(n.brand_name) = upper(COALESCE(a.brand_name, ''))"
        "        OR upper(n.brand_name) = upper(COALESCE(a.generic_name, '')))",
        (asset_id,)).fetchone()
    if row and row["d"]:
        return row["d"], "NDC first marketing"
    # Failing an exact brand match, a normalised one, which is what carries a revenue
    # label like "AMONDYS 45" to the register's "Amondys 45".
    key = normalise(name)
    if len(key) < 4:
        return None, None
    for candidate in conn.execute(
        "SELECT n.brand_name, n.first_marketed FROM ndc_products n"
        "  JOIN assets a ON a.owner_company_id = n.company_id"
        " WHERE a.id = ? AND n.first_marketed IS NOT NULL", (asset_id,)):
        other = normalise(candidate["brand_name"])
        if other and (other == key
                      or (len(other) >= MIN_CONTAINMENT and other in key)
                      or (len(key) >= MIN_CONTAINMENT and key in other)):
            return candidate["first_marketed"], "NDC first marketing"
    return None, None


def build_name_index(conn) -> dict:
    """{normalised brand name: earliest approval date} across every company.

    Built once per pass rather than queried per asset, since a company with forty
    revenue rows would otherwise scan the approvals table forty times.
    """
    index: dict = {}
    for row in conn.execute(
        """
        SELECT a.brand_name, a.generic_name, MIN(ap.approval_date) d
          FROM approvals ap JOIN assets a ON a.id = ap.asset_id
         WHERE ap.approval_date IS NOT NULL
         GROUP BY a.id
        """):
        for name in (row["brand_name"], row["generic_name"]):
            key = normalise(name)
            # Three characters would match half the table; a real brand is longer.
            if len(key) < 4:
                continue
            if key not in index or row["d"] < index[key]:
                index[key] = row["d"]
    return index


def first_approval(conn, asset_id: int, name: str | None = None,
                   name_index: dict | None = None) -> tuple:
    """(date, route) for a drug's first approval, or (None, None).

    Routes are tried most direct first: the drug's own approval row, then the licensure
    date implied by its biologic exclusivity, then the same drug approved under another
    company. The last one is how an alliance product gets a date, and it is last because
    a name match is the weakest of the three.
    """
    for route in (_own_approval, _biologic_licensure):
        date, source = route(conn, asset_id)
        if date:
            return date, source
    if name and name_index:
        key = normalise(name)
        if len(key) >= 4 and key in name_index:
            return name_index[key], "approved to another company"
        # A filing sometimes concatenates the names a product sells under, so Vertex's
        # 10.3bn line is "TRIKAFTAKAFTRIO" for the drug drugsfda calls Trikafta and
        # Europe calls Kaftrio. Fall back to containment, in either direction, on keys
        # long enough that a coincidence is implausible.
        if len(key) >= MIN_CONTAINMENT:
            # The earliest of everything the line contains, not whichever the index
            # happened to yield first. A combined line covers several brands of one
            # product and the question asked is when it was first approved, so taking
            # the minimum is both the right answer and independent of dict order.
            hits = [date for known, date in name_index.items()
                    if len(known) >= MIN_CONTAINMENT and (known in key or key in known)]
            if hits:
                return min(hits), "name matched within a combined revenue line"

    # Last, because it is a marketing date rather than an approval and can only err
    # toward looking newer than the truth.
    date, route = _ndc_marketing(conn, asset_id, name)
    if date:
        return date, route
    return None, None


# Revenue lines a filing discloses that are not a product. These are XBRL member labels
# for how revenue is earned, not for what was sold, and counting them as drugs put
# "Grant" and "License And Royalty" in the denominator of a portfolio-freshness figure
# where they could never be dated and so always read as an ageing portfolio.
#
# A disease or franchise label such as "Shingles" or "COVID 19" is deliberately not here.
# That is product revenue, genuinely earned by a drug, and the only problem is that the
# filing did not name which one. It stays in the base and shows up honestly as revenue
# that could not be dated, rather than being quietly removed to flatter the coverage.
_NON_PRODUCT = (
    "royalt", "collaborat", "collaborativeand", "grant", "milestone",
    "reimbursement", "license and", "licensing", "contract", "service",
    "alliance", "other revenue", "and service other", "product other",
    "upfront", "deferred", "interest",
)


def is_product_line(name: str | None) -> bool:
    """Whether a revenue row names something sold rather than a way of earning."""
    if not name or not name.strip():
        return False
    low = name.lower()
    return not any(term in low for term in _NON_PRODUCT)
