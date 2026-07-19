"""Load the .env once, from wherever it actually is.

The file lives at the repo root and the app runs from ``backend/``. Plain
``load_dotenv()`` looks only in the current directory, so it never found it: the key was
present and silently unloaded, and every consumer reported "no key" while a real one sat
one directory up. ``find_dotenv`` walks up the tree and finds it, which is the whole fix.

Import for the side effect. ``override=False`` keeps a value already in the real
environment ahead of the file, so an explicit ``ANTHROPIC_API_KEY=... python ...`` still
wins over the .env.
"""

from __future__ import annotations


def load() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ModuleNotFoundError:      # the app runs without python-dotenv installed
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)


load()
