"""A readout research has read and found to decide nothing the book values.

``in_the_base`` says the trial's patients are already inside the revenue the forecast
grows from, so no pool can be built for them without counting the same people twice.
That is true of 60 readouts on the book and it is the right answer for most of them, but
the row said the same thing whether an analyst had read the study or nobody had looked.
Those are different states and the queue cannot be worked while they share a word.

This file holds the ones that have been read. Each row names the study, what kind of
study it is, and the evidence that it cannot move the claim, the guideline or the payer
position. The three kinds that account for almost all of them:

  an open-label extension or long-term follow-up, whose primary outcome is adverse
  events and which has no control arm, run as a post-approval safety obligation;

  a regional registration or bridging study, seeking in another country a claim the US
  label already carries;

  a lot-consistency or immunogenicity study, which reads out on manufacturing rather
  than on medicine.

A second verdict shares the file because it shares the shape: a study the research has
read and found WOULD move the value, but whose figure no free source carries. That is not
nil and must not read as nil, so those kinds take their own reason, ``no_free_data``: the
row is worth something, the book cannot say how much without inventing it, and the queue
is not the place for it because no amount of work on the free sources will price it.
``reason()`` says which of the two a row is.

A row here is a judgement with a citation, not a dismissal, and it is reversible: delete
the row and the readout returns to the queue. The opposite judgement lives in
``data/catalyst_scenarios.csv``, which prices a readout inside the base from a named
case, and a study cannot be in both files. A test enforces that, because a readout both
settled at nil and priced at a delta is one of the two judgements being wrong.

Keyed by ticker and the asset's name rather than by id, because ids are rebuilt with the
database and a name is not.
"""

from __future__ import annotations

import csv
import pathlib

import db

CURATED = db.BACKEND_DIR.parent / "data" / "settled_readouts.csv"
FIELDS = ("ticker", "asset", "nct_id", "kind", "basis")

# What the row says about itself, and what the stake tab says to the reader.
KINDS = {
    "open_label_extension":
        "an open-label extension reporting adverse events, with no control arm",
    "long_term_follow_up":
        "long-term follow-up of participants already treated",
    "regional_registration":
        "a registration study for another country, seeking a claim the label carries",
    "evidence_generation":
        "single-arm evidence generation inside the approved use",
    "lot_consistency":
        "a lot-consistency or immunogenicity study, which reads out on manufacturing",
    "in_label":
        "a study whose population the label already covers",
    "allocation_only":
        "a master protocol whose primary outcome is which sub-study a participant "
        "joined, which is an allocation record rather than a readout",
    "roll_over_extension":
        "a roll-over extension carrying participants from several studies, whose "
        "primary outcome is adverse events",
    "basket":
        "a basket or master protocol, whose diseases are filed separately and read "
        "out separately",
    "continued_access":
        "a continued-access study, whose primary outcome is how many participants "
        "kept receiving the drug",
    "comparator_arm":
        "a study of something else, in which this product is the comparator",
    "both_arms_treated":
        "a study in which every arm receives the product, so the result decides how it "
        "is given rather than whether another patient gets it",
    "confirmatory_conversion":
        "a confirmatory trial for an accelerated approval the product already holds, "
        "so the question is whether the approval converts or is withdrawn rather than "
        "whether it is granted",
    "already_read_out":
        "a study whose result the company has already published, where the date on "
        "file is the registry's administrative completion rather than the readout",
    "outside_the_us":
        "a study run wholly outside the US for a claim the book does not value there, "
        "with no US pool or price to build one from",
    "not_pursued":
        "a programme the company has said it will continue only with a partner, with none "
        "announced and its study closed to enrolment",
    "suspended":
        "a study suspended with no sponsor to complete it, so the date on file will not "
        "happen",
}

# Read, and found to move the value by an amount no free source states. Each takes the
# reason no_free_data rather than settled_nil.
NO_FREE_DATA = {
    "no_citable_figure":
        "a readout inside the business already sold to, where a win would move share, and "
        "no company filing or free source states the figure that would price it",
    "no_free_input":
        "an expansion whose pool, price or uptake no free source carries, so the layer is "
        "refused rather than estimated",
    "no_launch_date":
        "a product with no filed date to launch from, so no launch year can be cited",
    "unnamed_candidate":
        "a candidate the registry names only by arm, which no public source ties to a "
        "programme the book could value",
}


def rows(path=None) -> list[dict]:
    """The file's rows, comment lines skipped. A missing file is an empty register."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    out = []
    for row in csv.DictReader(lines):
        got = {key: (row.get(key) or "").strip() for key in FIELDS}
        if got["ticker"] and got["asset"] and got["nct_id"] and got["basis"]:
            out.append(got)
    return out


def _asset(conn, ticker: str, name: str):
    found = conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ?
              AND LOWER(?) IN (LOWER(TRIM(COALESCE(a.generic_name, ''))),
                               LOWER(TRIM(COALESCE(a.brand_name, ''))),
                               LOWER(TRIM(COALESCE(a.internal_code, ''))))
            ORDER BY a.id""", (ticker.upper(), name)).fetchall()
    return found[0]["id"] if len(found) == 1 else None


def load(conn, path=None) -> dict:
    """{(asset_id, nct_id): {"kind", "basis"}} for every row that resolves."""
    out: dict = {}
    for row in rows(path):
        asset_id = _asset(conn, row["ticker"], row["asset"])
        if asset_id is None:
            continue
        out[(asset_id, row["nct_id"].upper())] = {"kind": row["kind"],
                                                  "basis": row["basis"]}
    return out


def reason(entry: dict) -> str:
    """settled_nil for a study that moves nothing; no_free_data for one that would move
    the value by an amount no free source states."""
    return "no_free_data" if (entry.get("kind") or "") in NO_FREE_DATA else "settled_nil"


def why(entry: dict) -> str:
    """The sentence the stake row carries, from the kind and the filed basis."""
    kind = entry.get("kind") or ""
    if kind in NO_FREE_DATA:
        lead = ("The research has read this study and it would move the value, but no "
                f"free source carries the figure: {NO_FREE_DATA[kind]}. ")
    else:
        said = KINDS.get(kind, "")
        lead = ("The research has read this study and it decides nothing the book values"
                + (f": {said}" if said else "") + ". ")
    basis = (entry.get("basis") or "").strip()
    return lead + (basis if basis.endswith((".", "!", "?")) else basis + ".")


def unresolved(conn, path=None) -> list[str]:
    """Rows the book cannot act on, each said in one line and why."""
    out = []
    for row in rows(path):
        if _asset(conn, row["ticker"], row["asset"]) is None:
            out.append(f"{row['ticker']} {row['asset']}: no single asset of that name")
        elif row["kind"] and row["kind"] not in KINDS and row["kind"] not in NO_FREE_DATA:
            out.append(f"{row['ticker']} {row['asset']}: unknown kind "
                       f"'{row['kind']}'")
    return out
