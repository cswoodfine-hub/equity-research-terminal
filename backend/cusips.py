"""The CUSIP register: which security each company's holders are reported under.

Form 13F names a holding by CUSIP and by whatever the manager typed as the issuer's
name. The book knows its companies by ticker and by CIK, neither of which a 13F carries,
and no free service maps one to the other. So the join is a curated file,
``data/cusips.csv``, derived once from the SEC's own Official List of Section 13(f)
Securities and read here.

A CUSIP is nine characters, the last a check digit over the first eight. The loader
refuses a row whose check digit fails, on the reasoning the seed applies to an LEI: a
mistyped identifier that is still well formed would read another company's holders and
nothing downstream could tell. A refused row is reported by ``problems()`` and never
reaches a caller, so the worst a typing mistake can do is leave a company with no data.

A company with no row has no free data. ``data/cusips_left_out.csv`` holds the reason
for each company deliberately left out (a depositary receipt that trades over the
counter is not a 13(f) security, so the few managers who report it anyway are not its
holders), and the reader hands that reason back in place of a number.

Pure: files in, rows out. No database and no network.
"""

from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
REGISTER = DATA / "cusips.csv"
LEFT_OUT = DATA / "cusips_left_out.csv"

# The words the official list uses for a depositary share. A position in one is counted
# in depositary shares, so it cannot be set against a count of ordinary shares without
# the ratio between the two.
_DEPOSITARY_WORDS = {"ADR", "ADS"}

# The three characters CUSIP allows beyond digits and letters, with the values the
# standard gives them. They appear in private placement numbers, never in a listed
# share's, and are here so the arithmetic is the standard's and not a subset of it.
_SPECIAL = {"*": 36, "@": 37, "#": 38}


def valid_cusip(cusip: str | None) -> bool:
    """True for a nine-character CUSIP whose check digit holds.

    The scheme is "modulus 10 double add double": each of the first eight characters
    becomes a number (a digit is itself, A is 10 through Z at 35), every second one is
    doubled, the digits of the results are summed, and the check digit is what brings
    that sum to a multiple of ten.

    The official list's entries for options fail this on purpose. It gives a company's
    calls and puts pseudo-CUSIPs made by overwriting the last three characters with 90x
    and 95x (Lilly's 532457108 becomes 532457908 and 532457958), and those are labels,
    not securities, so a register row can never be one.
    """
    cusip = (cusip or "").strip().upper()
    if len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for position, char in enumerate(cusip[:8]):
        if char.isdigit():
            value = int(char)
        elif "A" <= char <= "Z":
            value = ord(char) - ord("A") + 10
        elif char in _SPECIAL:
            value = _SPECIAL[char]
        else:
            return False
        if position % 2:
            value *= 2
        total += value // 10 + value % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def is_depositary(class_title: str | None) -> bool:
    """True when the class is a depositary share: ADR, SPONSORED ADS, SPON ADS."""
    return bool(_DEPOSITARY_WORDS & set((class_title or "").upper().split()))


def _read(path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#")))


def _checked(path=None) -> tuple:
    """(rows that may be used, one sentence for each row that may not)."""
    good: list[dict] = []
    bad: list[str] = []
    owner: dict = {}
    for row in _read(path or REGISTER):
        ticker = (row.get("ticker") or "").strip().upper()
        cusip = (row.get("cusip") or "").strip().upper()
        if not ticker or not cusip:
            bad.append(f"a row with no ticker or no CUSIP: {dict(row)}")
            continue
        if not valid_cusip(cusip):
            bad.append(f"{ticker}: the check digit of {cusip} does not hold, so the "
                       f"row is not used")
            continue
        if cusip in owner:
            # One security cannot be two companies' shares. Whichever row is wrong,
            # the second is the one refused, and the first is reported with it.
            bad.append(f"{ticker}: {cusip} is already {owner[cusip]}'s, so the row is "
                       f"not used")
            continue
        owner[cusip] = ticker
        good.append({
            "ticker": ticker,
            "cusip": cusip,
            "class_title": (row.get("class_title") or "").strip() or None,
            "source": (row.get("source") or "").strip() or None,
            "note": (row.get("note") or "").strip() or None,
        })
    return good, bad


def load(path=None) -> list[dict]:
    """Every usable row of the register, in file order."""
    return _checked(path)[0]


def problems(path=None) -> list[str]:
    """What is wrong with the register, one sentence a row. Empty when nothing is."""
    return _checked(path)[1]


def by_cusip(path=None) -> dict:
    """{CUSIP: ticker}, the shape the fetcher filters millions of lines against."""
    return {row["cusip"]: row["ticker"] for row in load(path)}


def for_ticker(ticker: str, path=None) -> list[dict]:
    """A company's rows. Usually one; two where its CUSIP changed."""
    wanted = (ticker or "").strip().upper()
    return [row for row in load(path) if row["ticker"] == wanted]


def left_out(path=None) -> dict:
    """{ticker: why it has no row}, for the companies left out on purpose."""
    return {(row.get("ticker") or "").strip().upper(): (row.get("reason") or "").strip()
            for row in _read(path or LEFT_OUT) if (row.get("ticker") or "").strip()}
