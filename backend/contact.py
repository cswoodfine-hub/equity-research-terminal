"""Who the book's requests say they come from.

Public data services ask an automated client to say who runs it, and SEC EDGAR refuses
one that does not. The address used to be written into twenty-eight fetchers as a
literal, which put a person's email in the source of every copy of the repository. It
lives in ``.env`` now, with the other settings that belong to whoever runs the book:

  CONTACT_EMAIL     the address, if set;
  SEC_USER_AGENT    otherwise the address inside it, the one EDGAR already requires.

With neither, requests carry the project's name alone. Every service here answers that,
except EDGAR, whose fetchers read SEC_USER_AGENT themselves and say so when it is empty.
"""

from __future__ import annotations

import os
import re

import env  # noqa: F401  loads .env for the side effect

NAME = "Novatalis Research"
PRODUCT = "NovatalisResearch/0.1"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def address() -> str | None:
    """The contact address from the environment, or None."""
    stated = (os.getenv("CONTACT_EMAIL") or "").strip()
    if stated:
        return stated
    found = _EMAIL.search(os.getenv("SEC_USER_AGENT") or "")
    return found.group(0) if found else None


def user_agent() -> str:
    """'Novatalis Research <address>', or the name alone."""
    found = address()
    return f"{NAME} {found}" if found else NAME


def product_agent() -> str:
    """'NovatalisResearch/0.1 (contact <address>)', the product-token form some APIs
    ask for, or the token alone."""
    found = address()
    return f"{PRODUCT} (contact {found})" if found else PRODUCT
