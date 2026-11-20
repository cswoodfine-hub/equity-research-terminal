"""The areas a paper is filed under. They are defined once, in ``backend/discovery.py``;
this module keeps the name the scripts here use."""

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

from discovery import AREAS, areas as tag  # noqa: E402,F401

_RULES = {name: __import__("re").compile(rule) for name, rule in AREAS.items()}
