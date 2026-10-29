"""One product's fact profile, assembled from the tables that already key on the asset.

Everything here is sourced: approval and application number from openFDA, the revenue the
SEC data sets tag, the Orange or Purple Book exclusivity with the biologic 12-year floor
merged in the same way the LOE views do, CMS Medicare demand, DailyMed label history,
efficacy supplements, and any Paragraph IV challenge on file. The market size, peak sales
and competitor set an analyst also wants are in no free source, so they are curated by
hand and stored in ``product_notes``; they travel with the profile but are labelled as
the analyst's own, never as fetched data.

A field with nothing behind it comes back null, so the UI can show "no free data" rather
than a zero or a guess.
"""

from __future__ import annotations

import re

import assumptions as assumptions_module
import db
import forecast
import fx
import loe as loe_module
import loe_range
import payer_access
import pte

NOTE_FIELDS = ("market_size", "peak_sales", "competitors", "thesis")


def get_notes(conn, asset_id: int) -> dict:
    """The curated fields for one asset, all null when the analyst has written none."""
    row = conn.execute(
        "SELECT market_size, peak_sales, competitors, thesis, updated_at"
        " FROM product_notes WHERE asset_id = ?", (asset_id,)).fetchone()
    if row is None:
        return {f: None for f in NOTE_FIELDS} | {"updated_at": None}
    return dict(row)


def save_notes(db_path, asset_id: int, fields: dict) -> bool:
    """Upsert the curated fields. A blank string is stored as null, so clearing a field
    leaves no empty placeholder behind. Returns False when the asset does not exist."""
    conn = db.get_connection(db_path)
    try:
        if conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is None:
            return False
        clean = {f: (str(fields.get(f)).strip() or None) if fields.get(f) is not None
                 else None for f in NOTE_FIELDS}
        conn.execute(
            """
            INSERT INTO product_notes (asset_id, market_size, peak_sales, competitors,
                                       thesis, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(asset_id) DO UPDATE SET
                market_size = excluded.market_size, peak_sales = excluded.peak_sales,
                competitors = excluded.competitors, thesis = excluded.thesis,
                updated_at = datetime('now')
            """,
            (asset_id, clean["market_size"], clean["peak_sales"],
             clean["competitors"], clean["thesis"]))
        conn.commit()
        return True
    finally:
        conn.close()


_LABEL_HEADER = re.compile(r"^\s*\d*\s*INDICATIONS AND USAGE\s*", re.I)
_LABEL_SENTENCE = re.compile(r"(?<=[a-z])\.\s+")


def summarise(indications: str | None) -> str | None:
    """What the product is and what it treats, in the label's own words.

    The first sentence of the indications section carries both: "VERZENIO is a kinase
    inhibitor indicated in combination with endocrine therapy for the adjuvant treatment
    of adult patients with HR-positive, HER2-negative breast cancer". Nothing is
    written here and nothing is summarised away, so a product with no label on file has
    no summary rather than a generic one.
    """
    if not indications:
        return None
    body = _LABEL_HEADER.sub("", indications).strip()
    first = _LABEL_SENTENCE.split(body)[0].strip(" .;:")
    if len(first) < 12:
        return None
    # A label that lists its indications runs the first sentence into a bulleted list;
    # the lead-in is the useful part and the list belongs to the indications field.
    first = re.split(r"\s*(?:•|\u2022)\s*", first)[0].strip(" .;:,")
    return (first + ".") if first else None


# What the Orange Book's drug substance flag means in a sentence a reader can use. The
# book's own words are "drug substance", "drug product" and "method of use"; the first
# claims the molecule, the second a formulation or a salt, the third one indication.
PATENT_KINDS = {"substance": "molecule", "product": "formulation", "use": "method of use"}


def _patents(conn, asset_id: int, governing: str | None,
             certificates: dict | None = None) -> list[dict]:
    """Every patent and exclusivity on the product, with the one that sets the date marked.

    A product does not have a patent, it has a stack of them, and the stack is why two
    pages could disagree about Farxiga. Dapagliflozin's own patent expired in April 2026
    and the book also lists a second drug substance patent to 2029 and method-of-use
    patents for the heart failure and kidney indications to 2041. Showing the stack is
    what makes the date arguable instead of mysterious.

    A paediatric extension is not a patent. It is the same number with "*PED" after it and
    six more months, so it is folded into the row it extends rather than listed beside it.

    A term extension is, and the Orange Book's date already includes it, so the row says
    how long the USPTO certificate added rather than moving the date. A method-of-use
    patent carries the Orange Book's use codes; the data files give no wording for them.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT identifier, expiry_date, patent_kind, protection_type, source,
                  use_codes
             FROM exclusivities WHERE asset_id = ? ORDER BY expiry_date""", (asset_id,))]
    if certificates is None:
        certificates = _term_extensions(conn)
    extensions = {}
    for row in rows:
        name = row["identifier"] or ""
        if name.endswith("*PED"):
            extensions[name[: -len("*PED")]] = row["expiry_date"]
    out = []
    for row in rows:
        name = row["identifier"] or ""
        if name.endswith("*PED"):
            continue
        extended = extensions.get(name)
        out.append({
            "identifier": name or None,
            "expiry": row["expiry_date"],
            # The date it actually runs to, extension included, which is what the stack
            # has to be sorted and read on.
            "effective": max(row["expiry_date"], extended) if extended
                         else row["expiry_date"],
            "extended_to": extended,
            "term_extension": certificates.get(pte.patent_key(name)),
            "use_codes": [c for c in (row["use_codes"] or "").split(",") if c],
            "kind": PATENT_KINDS.get(row["patent_kind"] or ""),
            "type": row["protection_type"],
            "governs": bool(governing and name == governing),
            "source": row["source"],
        })
    out.sort(key=lambda r: (r["effective"] or "", r["identifier"] or ""))
    return out


def _term_extensions(conn) -> dict:
    """{patent: {"extension", "original_expiry"}} from the USPTO certificate list. Empty
    on a database from before the source."""
    try:
        found = conn.execute(
            "SELECT patent, extension, original_expiry FROM patent_term_extensions"
            " WHERE kind = 'certificate'").fetchall()
    except Exception:                       # noqa: BLE001 - no table yet
        return {}
    return {r["patent"]: {"extension": r["extension"],
                          "original_expiry": r["original_expiry"]} for r in found}


def _paragraph_iv(conn, asset_id: int) -> list[dict]:
    """The FDA Paragraph IV list's rows for the product's own application, one per
    strength: when the first challenge was filed, how many filers, the 180-day
    exclusivity status, and when the first filer was approved and began selling.

    The 30-month stay runs from the day the brand receives notice, which the list does
    not give, so no stay date is shown rather than one counted from the submission."""
    try:
        return [dict(r) for r in conn.execute(
            """SELECT p.strength, p.dosage_form, p.submission_date, p.pre_mma,
                      p.anda_count, p.status_180, p.first_approval, p.first_marketing,
                      p.last_patent_expiry, p.list_date
                 FROM paragraph_iv_list p JOIN assets a
                   ON a.internal_code = p.application_number
                WHERE a.id = ?
                ORDER BY (p.submission_date IS NULL), p.submission_date""",
            (asset_id,))]
    except Exception:                       # noqa: BLE001 - no table yet
        return []


def _erosion(inputs: dict | None) -> dict | None:
    """The erosion shape the valuation runs on and how many launches it was fitted to.
    None where the asset has no forecast inputs."""
    if not inputs or not inputs.get("scalars"):
        return None
    scalars = inputs["scalars"]
    if scalars.get("erosion_year1_pct") is not None:
        return {"row": "stated", "year1_pct": scalars["erosion_year1_pct"],
                "decay_pct": scalars.get("erosion_decay_pct"),
                "late_decay_pct": scalars.get("erosion_late_decay_pct"),
                "late_from_year": scalars.get("erosion_late_from_year"),
                "sample_n": None, "source": "stated on the asset"}
    default, which = forecast.erosion_default(inputs)
    if not default:
        return None
    return {"row": which, "year1_pct": default["year1_pct"],
            "decay_pct": default["decay_pct"],
            "late_decay_pct": default.get("late_decay_pct"),
            "late_from_year": default.get("late_from_year"),
            "sample_n": default.get("sample_n"), "source": default.get("source")}


def _range(conn, asset_id: int, found=None, inputs=None) -> dict | None:
    """Bear, base and bull LOE dates with the value at each, or None where there is no
    range or no forecast. A failure here costs the panel, never the profile."""
    try:
        return loe_range.for_asset(conn, asset_id, found=found, inputs=inputs)
    except Exception:                       # noqa: BLE001 - a view beside the profile
        return None


def _challenge_summary(rows: list[dict]) -> dict | None:
    """The Paragraph IV list cut to one line for a product: the first challenge, the most
    filers on any strength, and whether a generic has been approved or sold."""
    if not rows:
        return None
    dated = [r["submission_date"] for r in rows if r.get("submission_date")]
    sold = [r["first_marketing"] for r in rows if r.get("first_marketing")]
    approved = [r["first_approval"] for r in rows if r.get("first_approval")]
    counts = [r["anda_count"] for r in rows if r.get("anda_count") is not None]
    return {"first_submission": min(dated) if dated else None,
            "pre_mma": any(r.get("pre_mma") for r in rows),
            "filers": max(counts) if counts else None,
            "first_marketing": min(sold) if sold else None,
            "first_approval": min(approved) if approved else None,
            "strengths": len(rows)}


def company_stack(db_path, ticker: str, horizon_years: int = 10) -> list[dict] | None:
    """The stack behind the date for every product a company loses inside the window, one
    row each, for the LOE view: the protection that sets the date with its extensions,
    what is listed after it, the Paragraph IV record, the range valued at each end and
    the erosion row. The same pieces as the product profile, cut to a line a product.
    None when the ticker is unknown."""
    import datetime as dt

    rows = loe_module.loe_detail(db_path, ticker)
    if rows is None:
        return None
    last_year = dt.date.today().year + horizon_years
    rows = [r for r in rows if r["loe_year"] <= last_year]
    conn = db.get_connection(db_path)
    try:
        ids = [r["asset_id"] for r in rows]
        # The date's own patent as the view's date resolves it, and the range as the
        # valuation does, which leaves orphan exclusivity out.
        dated = loe_module.for_assets(conn, ids)
        resolved = loe_module.for_assets(conn, ids, exclude_orphan=True)
        certificates = _term_extensions(conn)
        out = []
        for row in rows:
            aid = row["asset_id"]
            patents = _patents(conn, aid, (dated.get(aid) or {}).get("identifier"),
                               certificates)
            governing = next((p for p in patents if p["governs"]), None)
            later = [p for p in patents if p["type"] == "patent" and not p["governs"]
                     and governing and (p["effective"] or "") > (governing["effective"] or "")]
            inputs = assumptions_module.load(conn, aid, "base")
            # The valuation leaves orphan exclusivity out, since it covers one orphan
            # indication and does not hold off a generic or biosimilar. Where that gives
            # a different date from the view's, both are shown: Humira's cliff reads its
            # 2028 orphan exclusivity, its value the 12-year floor that lapsed in 2014.
            valued = resolved.get(aid) or {}
            out.append({
                "asset_id": aid, "brand": row["brand_name"], "generic": row["generic_name"],
                "modality": row["modality"], "loe": row["loe"], "loe_year": row["loe_year"],
                "basis": row["loe_basis"],
                "valued_loe": (None if valued.get("date") == row["loe"] else
                               {"date": valued.get("date"), "basis": valued.get("basis"),
                                "past": bool(valued.get("past"))}),
                "governing": governing,
                "later_patents": len(later),
                "later_to": max((p["effective"] for p in later), default=None),
                "later_use": sum(1 for p in later if p["kind"] == "method of use"),
                "paragraph_iv": _challenge_summary(_paragraph_iv(conn, aid)),
                "loe_range": _range(conn, aid, found=resolved.get(aid), inputs=inputs),
                "erosion": _erosion(inputs),
            })
        return out
    finally:
        conn.close()


def _loe(conn, asset_id: int) -> dict:
    """The effective loss of exclusivity for the asset, on the one rule every view uses.

    The date is the compound patent where the Orange Book flags a drug substance, which
    is the earliest of them with its paediatric extension rather than the latest of
    anything. The later dates are still reported beside it: an analyst wants to see the
    use patent running to 2041, and wants not to be told that is when the generic comes.
    """
    row = conn.execute(
        """
        SELECT MAX(e.expiry_date) AS loe_max, MIN(e.expiry_date) AS loe_earliest,
               MAX(CASE WHEN e.patent_kind = 'use' THEN e.expiry_date END) AS use_max,
               MAX(CASE WHEN e.patent_kind = 'substance' THEN e.expiry_date END)
                 AS substance_max
          FROM exclusivities e WHERE e.asset_id = ?
        """, (asset_id,)).fetchone()
    found = loe_module.for_assets(conn, [asset_id]).get(asset_id) or {}
    date, basis = found.get("date"), found.get("basis")
    return {
        "loe": date, "basis": basis,
        "loe_year": int(date[:4]) if date else None,
        "loe_identifier": found.get("identifier"),
        "loe_past": bool(found.get("past")),
        "loe_earliest_year": (int(row["loe_earliest"][:4])
                              if row and row["loe_earliest"] else None),
        # Reported beside the date rather than folded into it: a use patent running
        # later does not hold the market, but an analyst still wants to see it. The same
        # goes for a second substance patent, which claims a salt or a form rather than
        # the molecule and which a generic designs around.
        "use_patent_year": (int(row["use_max"][:4])
                            if row and row["use_max"] else None),
        "last_listed_year": (int(row["loe_max"][:4])
                             if row and row["loe_max"] else None),
        "later_substance_year": (int(row["substance_max"][:4])
                                 if row and row["substance_max"]
                                 and (not date or row["substance_max"] > date) else None),
    }

def _demand(conn, asset_id: int) -> dict | None:
    """Medicare Part D and Part B demand: spend for the latest year with the year before
    it for direction, summed across parts, and each part on its own beside it.

    Beneficiaries and claims are never summed across the parts. A patient who has a
    Part B infusion and fills a Part D prescription is in both counts, so the sum counts
    them twice, and a Part D fill is not a Part B claim; each part's counts and its growth
    are reported in ``parts`` instead, with whether the growth is like for like. None when
    CMS has nothing matched to this drug.
    """
    import demand_split

    rows = conn.execute(
        "SELECT year, SUM(total_spending) AS spend"
        "  FROM drug_demand WHERE asset_id = ? GROUP BY year ORDER BY year DESC LIMIT 2",
        (asset_id,)).fetchall()
    if not rows:
        return None
    latest = dict(rows[0])
    prior = dict(rows[1]) if len(rows) > 1 else None
    growth = None
    if prior and prior["spend"]:
        growth = (latest["spend"] - prior["spend"]) / prior["spend"]
    parts = []
    for part, series in demand_split._series(conn, asset_id).items():
        cur = series[-1]
        prev = series[-2] if len(series) > 1 else None
        st = demand_split.step(prev, cur) if prev else None
        flags = demand_split.flags_for(part, prev, cur, st) if prev else []
        parts.append({
            "part": part, "year": cur["year"], "spend": cur["spending"],
            "claims": cur["claims"], "beneficiaries": cur["beneficiaries"],
            "prior_year": prev["year"] if prev else None,
            "spend_growth": st["spend"] if st else None,
            "patient_growth": st["patients"] if st else None,
            "like_for_like": not any(f["code"] in demand_split.NOT_LIKE_FOR_LIKE
                                     for f in flags)})
    parts.sort(key=lambda p: -(p["spend"] or 0.0))
    return {"year": latest["year"], "spend": latest["spend"],
            "prior_year": prior["year"] if prior else None,
            "spend_growth": growth, "parts": parts}


def product_profile(db_path, ticker: str, asset_id: int) -> dict | None:
    """The full profile for one asset owned by ``ticker``. None when the ticker is unknown
    or the asset is not one of its products, so a mismatched id cannot leak another
    company's data."""
    ticker = ticker.upper()
    conn = db.get_connection(db_path)
    try:
        asset = conn.execute(
            """
            SELECT a.id, a.brand_name, a.generic_name, a.modality, a.internal_code,
                   a.is_marketed, c.ticker, c.name AS company
              FROM assets a JOIN companies c ON c.id = a.owner_company_id
             WHERE a.id = ? AND c.ticker = ?
            """, (asset_id, ticker)).fetchone()
        if asset is None:
            return None

        approvals = [dict(r) for r in conn.execute(
            "SELECT approval_date, application_number, indication_text, agency, region"
            "  FROM approvals WHERE asset_id = ? ORDER BY approval_date", (asset_id,))]
        # Shown in dollars whatever the filer reports in, so a profile compares against
        # any other; the filed figure stays beside it and an unconvertible one is left
        # as filed rather than counted at par.
        rates = fx.latest_usd_rates(db_path)
        # The annual series and the quarterly one are kept apart. Interleaved they read
        # as a collapse, since a quarter beside a year is a quarter of the number and
        # nothing in the row says which it is.
        revenue, quarterly = [], []
        for r in conn.execute(
                "SELECT fiscal_year, period, period_end, value, unit, source"
                "  FROM asset_revenue WHERE asset_id = ?"
                "  ORDER BY fiscal_year, period_end", (asset_id,)):
            row = dict(r)
            row["reported_value"], row["reported_unit"] = row["value"], row["unit"]
            if row["unit"] and row["unit"] != "USD":
                converted = fx.to_usd(row["value"], row["unit"], rates)
                if converted is not None:
                    row["value"], row["unit"] = converted, "USD"
            (revenue if row["period"] == "FY" else quarterly).append(row)
        quarterly.sort(key=lambda r: r["period_end"] or "")
        label = conn.execute(
            "SELECT effective_time, indication_count, indications_text, population_text"
            "  FROM labels WHERE asset_id = ? ORDER BY effective_time DESC LIMIT 1",
            (asset_id,)).fetchone()
        supplements = [dict(r) for r in conn.execute(
            "SELECT approval_date, description FROM supplements"
            "  WHERE asset_id = ? AND approval_date IS NOT NULL"
            "  ORDER BY approval_date DESC LIMIT 6", (asset_id,))]
        challenges = [dict(r) for r in conn.execute(
            "SELECT application_number, first_submission FROM patent_challenges"
            "  WHERE asset_id = ? ORDER BY first_submission", (asset_id,))]
        catalysts = [dict(r) for r in conn.execute(
            "SELECT expected_date, catalyst_type, title FROM catalysts"
            "  WHERE asset_id = ? AND expected_date >= date('now')"
            "  ORDER BY expected_date LIMIT 6", (asset_id,))]
        # The drug's own studies, now that trials are bound to assets. Ordered by the
        # date each reads out, soonest first, so the nearest evidence leads; a trial with
        # no completion date on file sorts last rather than being dropped.
        trials = [dict(r) for r in conn.execute(
            """
            SELECT nct_id, title, phase, overall_status, primary_completion_date,
                   enrollment
              FROM trials WHERE asset_id = ?
             ORDER BY (primary_completion_date IS NULL),
                      primary_completion_date LIMIT 8
            """, (asset_id,))]
        # What the drug has already shown. The pipeline table holds active studies
        # only, so a marketed product's own evidence lives in its own table; newest
        # readout first, since that is the one an analyst is being asked about.
        completed = [dict(r) for r in conn.execute(
            """
            SELECT nct_id, title, phase, completion_date, enrollment, primary_outcome,
                   conditions
              FROM completed_trials WHERE asset_id = ?
             ORDER BY (completion_date IS NULL), completion_date DESC LIMIT 10
            """, (asset_id,))]
        completed_count = conn.execute(
            "SELECT COUNT(*) FROM completed_trials WHERE asset_id = ?",
            (asset_id,)).fetchone()[0]
        trial_count = conn.execute(
            "SELECT COUNT(*) FROM trials WHERE asset_id = ?", (asset_id,)).fetchone()[0]
        by_phase = {r["phase"]: r["n"] for r in conn.execute(
            "SELECT phase, COUNT(*) AS n FROM trials WHERE asset_id = ?"
            "  AND phase IS NOT NULL GROUP BY phase", (asset_id,))}

        return {
            "asset_id": asset["id"],
            "ticker": asset["ticker"],
            "company": asset["company"],
            "brand": asset["brand_name"],
            "generic": asset["generic_name"],
            "modality": asset["modality"],
            "approvals": approvals,
            "first_approval": approvals[0]["approval_date"] if approvals else None,
            "revenue": revenue,
            "quarterly_revenue": quarterly,
            "loe": (found_loe := _loe(conn, asset_id)),
            "patents": _patents(conn, asset_id, found_loe.get("loe_identifier")),
            "demand": _demand(conn, asset_id),
            # Who prescribes it in Medicare, which Part D plans cover it and how often
            # Medicaid fills it. Gross counts from three files, each with its own scope
            # label; nothing valued reads them.
            "access": payer_access.for_asset(conn, asset_id),
            "label": dict(label) if label else None,
            "supplements": supplements,
            "supplement_count": len(supplements),
            "challenges": challenges,
            # The stack behind the date (plan step 7): the FDA's Paragraph IV list for the
            # product's own application, the bear-to-bull range valued, and the erosion
            # row the valuation uses with the number of launches behind it.
            "paragraph_iv": _paragraph_iv(conn, asset_id),
            "loe_range": _range(conn, asset_id),
            "erosion": _erosion(assumptions_module.load(conn, asset_id, "base")),
            "catalysts": catalysts,
            "trials": trials,
            "trial_count": trial_count,
            "completed_trials": completed,
            "completed_count": completed_count,
            # One sentence on what the drug is and what it treats, taken from the
            # label's own first indication rather than written here.
            "summary": summarise(label["indications_text"] if label else None),
            "trials_by_phase": by_phase,
            "is_marketed": bool(asset["is_marketed"]),
            "notes": get_notes(conn, asset_id),
        }
    finally:
        conn.close()
