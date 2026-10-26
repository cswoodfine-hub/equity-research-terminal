"""The mechanical acceptance test for a draft indication-layer seed file.

Written before any agent ran, on purpose. An agent researching online produces
plausible numbers whether or not it found them, and prose about its own diligence is
not evidence. So the guard cannot be a reader's judgement about whether a row looks
sourced; it has to be a rule that a fabricated row fails.

The strongest rule here reuses the book's own grader. ``evidence.grade`` reads a row's
source sentence and says what kind of evidence it names. A prevalence whose source says
"CDC, 2024 national estimate" grades as published; one whose source says "typical for
this disease" grades as judgement, and one that names nothing at all grades as None.
A pool row must grade as evidence, so a number with a hand-waved provenance fails the
same way a number with none does.

What this cannot catch: a real citation misread. "Published, and wrong" passes every
rule here. That is why a human spot-check stays in the plan, weighted to the widest
layers, and why this file claims only to be a floor.

Usage:  python3 work/indication_backfill/verify_seeds.py data/assumptions/azn_x.csv [...]
Exit 0 if every file passes, 1 otherwise.
"""
from __future__ import annotations
import csv, json, pathlib, sqlite3, sys

sys.path.insert(0, "backend")
import db, evidence                                                   # noqa: E402

POOL_KEYS = {"prevalence", "incidence"}
SHARE_KEYS = {"base_pool_overlap_pct", "eligible_pct", "penetration_peak_pct",
              "gross_to_net_pct", "discontinuation_pct", "pos"}
# What a layer needs before indication_layer.build will price it. The overlap is the
# layer's own key and only a product that already sells something has a base to overlap
# with: on a pipeline asset the indication is the whole forecast, so requiring one there
# failed 255 files that are complete as they stand.
NEEDED = ("prevalence", "eligible_pct", "penetration_peak_pct", "base_pool_overlap_pct")
NEEDED_PIPELINE = ("prevalence", "eligible_pct", "penetration_peak_pct")
SELLING_MODES = ("marketed", "franchise", "launch")
EVIDENCE_GRADES = {"filed", "measured", "published"}
# A judgement has to say what would replace it. These are the words that do that.
REPLACES = ("replace", "until", "when ", "if ", "would become", "on success",
            "on a stated", "superseded")


def rows_of(path: pathlib.Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def check(path: pathlib.Path, conn) -> list[str]:
    bad: list[str] = []
    try:
        rows = rows_of(path)
    except Exception as exc:                                   # noqa: BLE001
        return [f"{path.name}: unreadable ({exc})"]
    if not rows:
        return [f"{path.name}: no rows"]

    def fail(i, msg):
        bad.append(f"{path.name}:{i} {msg}")

    pools: dict = {}
    layers: dict = {}
    for i, r in enumerate(rows, start=2):
        key = (r.get("key") or "").strip()
        src = (r.get("source") or "").strip()
        note = (r.get("note") or "").strip()
        raw = (r.get("value") or "").strip()
        ind = (r.get("indication") or "").strip()
        ticker = (r.get("ticker") or "").strip().upper()
        brand = (r.get("brand") or "").strip()

        if not key:
            fail(i, "no key"); continue

        # The row must resolve to something the book actually holds, or the loader
        # silently skips it and the file reads as loaded when nothing happened.
        if not conn.execute(
                "SELECT 1 FROM assets a JOIN companies c ON c.id=a.owner_company_id"
                " WHERE c.ticker=? AND (LOWER(TRIM(a.brand_name))=LOWER(?)"
                "    OR LOWER(TRIM(a.generic_name))=LOWER(?))", (ticker, brand, brand)
        ).fetchone():
            fail(i, f"no asset in the book for {ticker} / {brand!r}")
        if ind and not conn.execute(
                "SELECT 1 FROM indications WHERE LOWER(name)=LOWER(?)", (ind,)).fetchone():
            fail(i, f"no indication in the book named {ind!r}")

        if raw == "":
            if not (r.get("text_value") or "").strip():
                fail(i, f"{key} has neither a value nor a text_value")
            continue
        try:
            value = float(raw)
        except ValueError:
            fail(i, f"{key} value {raw!r} is not a number"); continue

        # Rule one: a number names a source.
        if not src:
            fail(i, f"{key} = {value} with no source"); continue

        g = evidence.grade(src, note, key)

        # Rule two: a disease's pool is evidence somewhere.
        #
        # Per row rather than per disease was the first shape and it was wrong: the
        # Lilly precedent writes incidence as "as the prevalence row", a back-reference
        # to the sourced figure three lines above, and that is good practice rather than
        # a gap. So the requirement lands on the pool as a whole -- at least one of
        # prevalence and incidence must cite something openable -- while every row still
        # has to carry a source of some kind.
        if key in POOL_KEYS:
            pools.setdefault(ind, {})[key] = (value, src, g)

        # Rule three: shares are shares.
        if key in SHARE_KEYS and not (0.0 <= value <= 1.0):
            fail(i, f"{key} = {value} is outside 0 to 1")

        # Rule four: a judgement probability says what replaces it.
        #
        # Only pos. A penetration peak is a judgement that nothing resolves -- it is
        # settled by years of sales, not by an event -- and demanding a replacement
        # clause on it failed the Lilly file on three rows that are exactly right. The
        # gate probability is different: it sits in front of a dated readout, the whole
        # book is built to step it when that readout lands, and a pos judgement with no
        # stated replacement is the one that quietly never moves.
        if key == "pos" and value not in (0.0, 1.0) and not _overlap_is_one(rows, ind):
            says = any(w in (note + " " + src).lower() for w in REPLACES)
            # analogue belongs here beside the evidence grades. The published
            # transition chain is a figure measured across other people's programmes,
            # which is what an analogue is, and Omvoh's two Crohn rows carry it.
            # A layer whose overlap is 1.0 is exempt above: it adds nothing, so its
            # probability prices nothing either, which is what Jaypirca's row says.
            if g in EVIDENCE_GRADES | {"analogue"}:
                pass                      # the published chain, or a stated result
            elif g == "judgement" and says:
                pass                      # argued, and it says what settles it
            else:
                fail(i, f"pos = {value} grades as {g or 'ungraded'} and names no "
                        f"replacement. A gate probability is the published chain for "
                        f"the area, a stated result, or a judgement that says what "
                        f"would replace it; \"industry standard\" is none of the three")

        if ind:
            layers.setdefault(ind, set()).add(key)

    # Rule five: a layer is complete or it is not built. An incomplete one is not an
    # error in itself -- indication_layer names what it lacks -- but a file that means
    # to price a layer and leaves out one key silently prices nothing, so say so.
    for ind, keys in sorted(layers.items()):
        if "pos" in keys and float(next(
                (r["value"] for r in rows
                 if (r.get("indication") or "").strip() == ind
                 and (r.get("key") or "").strip() == "pos" and r.get("value")), 1) or 1) == 0:
            continue                      # a failed programme is deliberately bare
        if keys.get if False else ("base_pool_overlap_pct" in keys and
                                   _overlap_is_one(rows, ind)):
            continue                      # overlap 1.0 adds nothing; no pool needed
        wanted = NEEDED if _sells(conn, rows, ind) else NEEDED_PIPELINE
        missing = [k for k in wanted if k not in keys]
        if missing:
            bad.append(f"{path.name}: layer {ind!r} is missing {', '.join(missing)}, "
                       f"so indication_layer will refuse to price it")

    # Rule two, concluded: every disease priced here names its pool's evidence once.
    for ind, got in sorted(pools.items()):
        if not any(gr in EVIDENCE_GRADES for _, _, gr in got.values()):
            worst = "; ".join(f"{k} grades {gr or 'ungraded'}" for k, (_, _, gr)
                              in sorted(got.items()))
            bad.append(f"{path.name}: the pool for {ind!r} cites no evidence at all "
                       f"({worst}). A pool must name something a reader can open")

    # Rule five-and-a-half: two layers built on the same pool are a double count
    # waiting to happen. Cobenfy's file prices psychosis of Alzheimer's and agitation
    # in Alzheimer's as separate layers off the same 7.4 million patients, and they are
    # largely the same people; the file handles it by halving the second layer's
    # penetration and saying so, which is the right answer. But the engine sums layers
    # without knowing that, so the case has to be visible rather than left to whoever
    # happens to read the source sentences.
    shared: dict = {}
    for ind, got in pools.items():
        if "prevalence" in got:
            shared.setdefault(got["prevalence"][0], []).append(ind)
    # So the rule is not "do not do this", which would refuse a real case. It is "say
    # how you kept them apart", which is a sentence the author has to write and a
    # reader can then argue with.
    for value, inds in sorted(shared.items()):
        if len(inds) < 2:
            continue
        said = " ".join((r.get("note") or "") + " " + (r.get("source") or "")
                        for r in rows
                        if (r.get("indication") or "").strip() in inds).lower()
        if not any(w in said for w in ("double count", "double-count", "twice",
                                       "same patient", "read the two", "overlap")):
            bad.append(f"{path.name}: {' and '.join(repr(i) for i in sorted(inds))} are "
                       f"priced off the same pool of {value:,.0f} and no row says how "
                       f"they are kept apart. The engine sums layers, so unless these "
                       f"are disjoint populations this sells the same patient twice")

    # Rule six: the book must not disagree with itself about a disease.
    for ind, got in sorted(pools.items()):
        row = conn.execute(
            "SELECT a.value, a.source FROM assumptions a JOIN indications i"
            "  ON i.id=a.indication_id WHERE LOWER(i.name)=LOWER(?)"
            "   AND a.key='prevalence' AND a.value IS NOT NULL LIMIT 1", (ind,)).fetchone()
        mine = got.get("prevalence")
        if row and mine and abs(row["value"] - mine[0]) > max(1.0, 0.02 * row["value"]):
            bad.append(f"{path.name}: prevalence for {ind!r} is {mine[0]:,.0f} here and "
                       f"{row['value']:,.0f} already in the book. One of them is wrong, "
                       f"and test_no_two_assets_disagree will fail on it")
    return bad


def _sells(conn, rows, ind) -> bool:
    """Whether the file's asset already has revenue, which is what makes its unapproved
    indications layers rather than the forecast itself."""
    for r in rows:
        ticker = (r.get("ticker") or "").strip().upper()
        brand = (r.get("brand") or "").strip()
        if not ticker or not brand:
            continue
        got = conn.execute(
            "SELECT s.text_value FROM assets a JOIN companies c"
            "   ON c.id = a.owner_company_id"
            "  JOIN assumptions s ON s.asset_id = a.id AND s.key = 'therapy_mode'"
            " WHERE c.ticker = ? AND (LOWER(TRIM(a.brand_name)) = LOWER(?)"
            "    OR LOWER(TRIM(a.generic_name)) = LOWER(?)) LIMIT 1",
            (ticker, brand, brand)).fetchone()
        if got:
            return (got["text_value"] or "") in SELLING_MODES
    return False


def _overlap_is_one(rows, ind) -> bool:
    for r in rows:
        if ((r.get("indication") or "").strip() == ind
                and (r.get("key") or "").strip() == "base_pool_overlap_pct"):
            try:
                return float(r.get("value") or 0) >= 1.0
            except ValueError:
                return False
    return False


def main(argv) -> int:
    if not argv:
        print(__doc__); return 2
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    bad, n = [], 0
    for arg in argv:
        p = pathlib.Path(arg)
        for path in ([p] if p.is_file() else sorted(p.glob("*.csv"))):
            n += 1
            bad += check(path, conn)
    for line in bad:
        print("FAIL", line)
    print(f"\n{n} file(s), {len(bad)} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
