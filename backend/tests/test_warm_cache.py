"""Saving the slow reads for a container that starts cold: one warming pass, in the order
the reads' embeddings need, and the deployed app picking each release asset by its name.
No network: the fetches and the release listing are stubbed."""

import ast
import io
import json
import pathlib

import response_cache as R

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_one_pass_reads_globals_then_companies_then_what_embeds_them(monkeypatch):
    fetched = []

    def fetch(url):
        if url.endswith("/companies/BBB/street"):
            raise OSError("down")
        fetched.append(url)

    monkeypatch.setattr(R, "_fetch", fetch)
    monkeypatch.setattr(R, "_tickers", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(R, "_area_reads", lambda: ["/areas/oncology"])
    monkeypatch.setattr(R, "_universe_reads",
                        lambda base, first: [base + "/universe/command?ticker=BBB&part=all"])
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    done = R.warm_once("http://api")
    paths = [u[len("http://api"):] for u in fetched]
    assert paths[:len(R.GLOBAL_READS)] == list(R.GLOBAL_READS)
    # Every company's reads before the reads that embed them.
    last_company = max(i for i, p in enumerate(paths) if p.startswith("/companies/BBB/"))
    assert paths.index("/comps/valuation") > last_company
    assert paths[-2:] == ["/areas/oncology", "/universe/command?ticker=BBB&part=all"]
    total = len(R.GLOBAL_READS) + 2 * len(R.COMPANY_READS) + len(R.LATE_GLOBAL_READS) + 2
    assert done == {"reads": total - 1, "failed": 1}


def _resolver():
    """The cloud app's asset lookup, lifted out of the module, which starts the app on
    import."""
    source = (ROOT / "streamlit_cloud_app.py").read_text()
    tree = ast.parse(source)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "_resolve_release_asset")
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") in ("DB_ASSET", "RESPONSES_ASSET")
                        for t in n.targets))]
    release = {"assets": [
        {"name": "responses.db.gz", "url": "https://api.github.com/assets/2"},
        {"name": "er_tool.db.gz", "url": "https://api.github.com/assets/1"}]}

    class Stub:
        class request:
            Request = staticmethod(lambda url, headers=None: url)

            @staticmethod
            def urlopen(request, timeout=None):
                return io.BytesIO(json.dumps(release).encode())

    space = {"json": json, "urllib": Stub}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "streamlit_cloud_app.py", "exec"),
         space)
    return space


def test_the_app_takes_the_database_by_name_not_the_first_gz():
    space = _resolver()
    find = space["_resolve_release_asset"]
    # The responses are listed first, and taking the first .gz would load them as the book.
    assert find("o/r", "data-latest", "") == "https://api.github.com/assets/1"
    assert (find("o/r", "data-latest", "", space["RESPONSES_ASSET"])
            == "https://api.github.com/assets/2")
    try:
        find("o/r", "data-latest", "", "missing.gz")
    except RuntimeError as exc:
        assert "publishes no missing.gz" in str(exc)
    else:
        raise AssertionError("a missing asset must be reported")
