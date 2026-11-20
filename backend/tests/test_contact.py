"""The contact address lives in .env, never in the source."""

import pathlib
import re

import contact

BACKEND = pathlib.Path(__file__).resolve().parent.parent
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.(?:com|org|net|co\.uk|io)\b")


def test_no_source_file_carries_an_email_address():
    """Twenty-eight fetchers once carried a person's address as a literal."""
    found = []
    for path in list(BACKEND.glob("*.py")) + list(BACKEND.glob("fetchers/*.py")):
        for hit in _EMAIL.findall(path.read_text(encoding="utf-8")):
            if not hit.endswith(("@example.org", "@example.com", "@anthropic.com")):
                found.append(f"{path.name}: {hit}")
    assert found == []


def test_the_address_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "someone@example.org")
    assert contact.user_agent() == "Novatalis Research someone@example.org"
    assert contact.product_agent() == "NovatalisResearch/0.1 (contact someone@example.org)"


def test_the_sec_identifier_supplies_it_when_nothing_else_does(monkeypatch):
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", "A Person someone@example.org")
    assert contact.address() == "someone@example.org"


def test_with_no_address_the_name_stands_alone(monkeypatch):
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", "")
    assert contact.user_agent() == "Novatalis Research"
    assert contact.product_agent() == "NovatalisResearch/0.1"
