"""National Drug Codes, read into the shapes the payer files key on.

An NDC names a labeler, a product and a package. FDA prints it with hyphens in one of
three 10-digit layouts, 4-4-2, 5-3-2 and 5-4-1, and the payer files use the 11-digit
5-4-2 form with the short segment zero-padded: RxNav's NDC history, the Part D formulary
NDC column and Medicaid's State Drug Utilization Data all carry it. The book already
keys the negotiated Medicare prices on the 9-digit product code, 'LLLLL-PPPP'
(negotiated_prices.ndc9, for example '00173-0869'), so that is the product form here
too.

Pure functions only. A string that is not one of those layouts comes back as None: a
10-digit code with no hyphens cannot be padded, because which segment is short is
exactly what the hyphens say, and guessing it would bind one drug's claims to another.
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"^\d+$")

# Segment lengths FDA prints, each padded to 5-4-2.
_PACKAGE_LAYOUTS = {(4, 4, 2), (5, 3, 2), (5, 4, 1), (5, 4, 2)}
_PRODUCT_LAYOUTS = {(4, 4), (5, 3), (5, 4)}


def to_ndc11(ndc: str | None) -> str | None:
    """The 11-digit 5-4-2 package code with no hyphens, or None.

    '71610-662-09' -> '71610066209'; '0003-0894-21' -> '00003089421';
    '00003089421' -> '00003089421'. An unhyphenated 10-digit code is ambiguous and
    returns None.
    """
    text = (ndc or "").strip()
    if not text:
        return None
    if "-" not in text:
        return text if len(text) == 11 and _DIGITS.match(text) else None
    parts = text.split("-")
    if len(parts) != 3 or not all(p and _DIGITS.match(p) for p in parts):
        return None
    if tuple(len(p) for p in parts) not in _PACKAGE_LAYOUTS:
        return None
    labeler_code, product, package = parts
    return labeler_code.zfill(5) + product.zfill(4) + package.zfill(2)


def product_ndc9(product_ndc: str | None) -> str | None:
    """A hyphenated two-segment product code as 'LLLLL-PPPP', or None.

    '0003-3764' -> '00003-3764'; '71610-662' -> '71610-0662'.
    """
    parts = (product_ndc or "").strip().split("-")
    if len(parts) != 2 or not all(p and _DIGITS.match(p) for p in parts):
        return None
    if tuple(len(p) for p in parts) not in _PRODUCT_LAYOUTS:
        return None
    return f"{parts[0].zfill(5)}-{parts[1].zfill(4)}"


def ndc9(ndc11: str | None) -> str | None:
    """The product code 'LLLLL-PPPP' of a package code, or None.

    ndc9('00003089321') == '00003-0893'. Hyphenated input is normalised first.
    """
    code = to_ndc11(ndc11)
    return f"{code[:5]}-{code[5:9]}" if code else None


def labeler(ndc11: str | None) -> str | None:
    """The five-digit labeler code of a package code, or None."""
    code = to_ndc11(ndc11)
    return code[:5] if code else None
