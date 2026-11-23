"""The broker fetcher reads and does nothing else, and the app has no way to trade.

``fetchers/broker_t212.py`` says in its docstring that only GET endpoints are called and
that no order route is to be added. Nothing held it to that: one keyword on one call
would turn a read into a write against a real account. These tests read the source, so
they need no key and reach no network.
"""

import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BROKER = BACKEND / "fetchers" / "broker_t212.py"

# Every path the fetcher may ask Trading 212 for. All five are reads of the account's own
# state; "/api/v0" is the prefix history strips from the next page's address.
READS = {"/equity/account/summary", "/equity/positions", "/equity/history/orders",
         "/equity/history/transactions", "/equity/history/dividends", "/api/v0"}
# A client that can send a body without urllib's Request ever being named.
OTHER_CLIENTS = {"requests", "httpx", "http.client", "aiohttp", "socket", "subprocess"}


def _tree() -> ast.AST:
    return ast.parse(BROKER.read_text(encoding="utf-8"))


def _name(func) -> str:
    """``urllib.request.Request`` as written, for a call's function."""
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def test_every_request_the_broker_fetcher_builds_is_a_get():
    """A urllib Request is a GET until it is given a body or a method. Neither is."""
    built = [node for node in ast.walk(_tree())
             if isinstance(node, ast.Call) and _name(node.func).endswith("Request")]
    assert built, "the fetcher no longer builds a request this test can see"
    for call in built:
        keywords = {kw.arg for kw in call.keywords}
        assert not keywords & {"data", "method"}, f"line {call.lineno} sends a body or a method"
        assert len(call.args) <= 1, f"line {call.lineno} passes a body by position"


def test_nothing_is_sent_through_urlopen_either():
    """urlopen takes a body as its second argument, which would be a POST."""
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and _name(node.func).endswith("urlopen"):
            assert len(node.args) <= 1, f"line {node.lineno} passes a body by position"
            assert "data" not in {kw.arg for kw in node.keywords}


def test_the_broker_fetcher_uses_no_other_way_to_reach_the_network():
    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not imported & OTHER_CLIENTS


def test_the_only_paths_asked_for_are_the_five_reads():
    """An order is placed at a path of its own, so a new path is the thing to catch."""
    paths = {node.value for node in ast.walk(_tree())
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith("/")}
    assert paths <= READS, f"a path that is not a known read: {sorted(paths - READS)}"


def test_no_route_under_portfolio_takes_a_write():
    """The holdings routes are reads. A POST there would be the first step to an order."""
    source = (BACKEND / "main.py").read_text(encoding="utf-8")
    writes = re.findall(r'@app\.(?:post|put|patch|delete)\(\s*"(/portfolio[^"]*)"', source)
    assert writes == []


def test_no_route_is_named_for_an_order():
    source = (BACKEND / "main.py").read_text(encoding="utf-8")
    routes = re.findall(r'@app\.(?:get|post|put|patch|delete)\(\s*"([^"]+)"', source)
    assert routes, "main.py declares its routes some other way now"
    named = [r for r in routes if re.search(r"/(orders?|trade|buy|sell)(/|$)", r)]
    assert named == []
