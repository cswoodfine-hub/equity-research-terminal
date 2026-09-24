"""Where a seed puts a key decides whether the engine reads it.

The pool identity reads its inputs from an indication's own scalars. A key that belongs to
an indication but is written at asset level is loaded, displayed, and never used. That is
worse than missing, because it looks as though it is doing something.
"""

import csv
import pathlib

import pool_crowding

_SEEDS = pathlib.Path(__file__).resolve().parents[2] / "data" / "assumptions"


def _rows():
    for path in sorted(_SEEDS.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            yield path.name, row


def test_no_seed_writes_a_pool_input_where_the_engine_does_not_read_it():
    """Seven obesity seeds carried their ex-US multiple at asset level. forecast.py and
    pool_crowding.py both read it from the indication, so the working row existed only in
    the database, and a database rebuilt from these files would have dropped the ex-US
    revenue of seven assets without a word."""
    per_indication = set(pool_crowding._PER_INDICATION)
    misplaced = [(name, row["key"]) for name, row in _rows()
                 if row.get("key") in per_indication
                 and not (row.get("indication") or "").strip()]
    assert misplaced == [], misplaced


def test_the_check_covers_the_key_that_was_misplaced():
    """If exus_multiple ever leaves the per-indication list, the guard above goes quiet."""
    assert "exus_multiple" in pool_crowding._PER_INDICATION


# --- the currency a seed's money is written in -------------------------------------
import re

_MONEY_KEYS = ("list_price_per_patient", "net_price_per_patient", "base_revenue",
               "franchise_revenue")
_CURRENCY_IN_UNIT = re.compile(r"\bmm\s+([A-Z]{3})\b")


def _reporting_currency():
    path = pathlib.Path(__file__).resolve().parents[2] / "data" / "companies_seed.csv"
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["ticker"].strip().upper(): row["reporting_currency"].strip().upper()
                for row in csv.DictReader(handle) if row.get("ticker")}


def test_every_price_is_in_the_currency_the_company_reports_in():
    """The engine models a company in its reporting currency and converts to dollars once,
    at the end, so the unit on a price is a label and the number is read as the company's
    own currency whatever the label says. A US comparator's dollar figure written into a
    sterling or euro filer is overstated by the exchange rate without any error being
    raised. It has happened twice: a Novo Nordisk seed carried dollars labelled kroner, and
    five GSK and Sanofi seeds carried dollars labelled dollars, which read as pounds and
    euros and overstated them 33% and 14%."""
    currency = _reporting_currency()
    wrong = []
    for name, row in _rows():
        if row.get("key") not in _MONEY_KEYS:
            continue
        match = _CURRENCY_IN_UNIT.search(row.get("unit") or "")
        ticker = (row.get("ticker") or "").strip().upper()
        if match and ticker in currency and match.group(1) != currency[ticker]:
            wrong.append((name, row["key"], row["unit"], currency[ticker]))
    assert wrong == [], wrong


# --- the deduction a Part B price takes ----------------------------------------------
_PART_B = re.compile(r"\bPart B\b")
_PART_D = re.compile(r"\bPart D\b")


def test_a_part_b_price_does_not_take_the_part_d_halving():
    """gross_to_net.py measured halving on Part D, where CMS spending is gross of rebates.
    Part B pays 106% of average sales price, which is already net, so a Part B figure
    loses the 6% add-on and no more. Nine seeds halved a Part B price anyway, and a
    new one priced off Trodelvy nearly joined them, which put its net at half of what
    the book's other Trodelvy-priced seeds carry for the same comparator."""
    halved = []
    rows_by_file: dict = {}
    for name, row in _rows():
        rows_by_file.setdefault(name, []).append(row)
    for name, rows in rows_by_file.items():
        for price in rows:
            source = price.get("source") or ""
            if (price.get("key") != "list_price_per_patient" or not _PART_B.search(source)
                    or _PART_D.search(source)):
                continue
            for row in rows:
                if (row.get("key") == "gross_to_net_pct"
                        and row.get("scenario") == price.get("scenario")
                        and (row.get("indication") or "") == (price.get("indication") or "")
                        and float(row["value"]) == 0.5):
                    halved.append((name, price.get("indication") or "", row["value"]))
    assert halved == [], halved
