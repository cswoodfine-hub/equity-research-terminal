"""The Ask box drawn in two places on one page: its own tab and beside the Trading board.

The box lives in the Streamlit script, which runs the whole app on import, so its
functions are read out of the source by name and run on their own in AppTest, with the
API stood in. No model, no API and no network is needed.
"""

import ast
import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"
WANTED = ("ASK_STARTERS", "_ask_reads_html", "_ask_send", "_ask_tab")

_STUBS = '''
import html, json, urllib.error, urllib.request
import streamlit as st

def html_escape(text):
    return html.escape(str(text), quote=True)
def section(label, count=None, basis=""):
    st.markdown(f"SECTION[{label}]")
def state(title, detail, error=False):
    st.markdown(f"STATE[{title}]")
def api_get(base, path, timeout=30):
    return {"ready": True, "model": "stand-in"}
def api_post_body(base, path, body, timeout=300):
    st.session_state.setdefault("sent", []).append({"path": path, "body": body})
    return {"ok": True, "answer": "It holds $1,134m in cash and $221m in notes.",
            "steps": [{"title": "Runway", "args": {"ticker": "LLY"}, "ok": True,
                       "as_of": "2026-11-20"}]}
'''


def _source() -> str:
    """The Ask box's own definitions, cut from the app with their decorators."""
    text = APP.read_text()
    lines = text.splitlines()
    tree = ast.parse(text, feature_version=(3, 9))
    parts = []
    for node in tree.body:
        name = (node.name if isinstance(node, ast.FunctionDef) else
                node.targets[0].id if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name) else None)
        if name in WANTED:
            first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            parts.append("\n".join(lines[first - 1:node.end_lineno]))
    assert len(parts) == len(WANTED), "the Ask box's functions are not where they were"
    return "\n\n\n".join(parts)


def _page(tail: str):
    from streamlit.testing.v1 import AppTest
    test = AppTest.from_string(_STUBS + "\n\n" + _source() + "\n\n" + tail,
                               default_timeout=60)
    test.run()
    return test


BOTH = '''
_ask_tab("http://api.invalid", "LLY", "Eli Lilly")
_ask_tab("http://api.invalid", "LLY", "Eli Lilly", slot="td_")
'''


def _md(test) -> str:
    return "\n".join(str(m.value) for m in test.markdown)


def test_the_box_is_drawn_twice_on_one_page_with_no_key_shared():
    test = _page(BOTH)
    assert not test.exception, test.exception
    assert _md(test).count("SECTION[Ask the book]") == 2
    keys = [b.key for b in test.button]
    assert len(keys) == 6 and len(set(keys)) == 6          # three starters in each place
    assert {k for k in keys if "td_" in k} == {f"ask_start_td_LLY_{n}" for n in range(3)}
    assert len(test.chat_input) == 2
    assert {c.key for c in test.chat_input} == {"ask_input_LLY", "ask_input_td_LLY"}


def test_two_boxes_in_the_same_place_would_stop_the_page():
    """The reason the slot exists: without it the second box reuses the first's keys."""
    test = _page('''
_ask_tab("http://api.invalid", "LLY", "Eli Lilly")
_ask_tab("http://api.invalid", "LLY", "Eli Lilly")
''')
    assert test.exception


def test_one_conversation_a_company_is_shown_in_both_places():
    test = _page('''
st.session_state["ask_turns_LLY"] = [{"q": "How much cash does it hold?", "ok": True,
    "answer": "It holds $1,134m in cash.", "steps": []}]
''' + BOTH)
    assert not test.exception, test.exception
    md = _md(test)
    assert md.count("How much cash does it hold?") == 2
    # Dollar signs are escaped, or Streamlit sets the text between two of them as maths.
    assert md.count("It holds \\$1,134m in cash.") == 2
    assert {b.key for b in test.button} == {"ask_clear_LLY", "ask_clear_td_LLY"}


def test_a_question_sent_from_either_place_joins_the_same_conversation():
    test = _page('''
_ask_send("http://api.invalid", "LLY", "Eli Lilly", "ask_turns_LLY", "Is it funded?")
_ask_send("http://api.invalid", "LLY", "Eli Lilly", "ask_turns_LLY", "Through when?")
st.markdown("TURNS[%d]" % len(st.session_state["ask_turns_LLY"]))
''')
    assert not test.exception, test.exception
    assert "TURNS[2]" in _md(test)
    first, second = test.session_state["sent"]
    assert first["path"] == "/ask" and first["body"]["history"] == []
    assert [h["role"] for h in second["body"]["history"]] == ["user", "assistant"]
    assert second["body"]["ticker"] == "LLY" and second["body"]["name"] == "Eli Lilly"


def test_the_open_panels_go_with_a_question_only_from_the_box_beside_a_board():
    test = _page('''
st.session_state["td_showing"] = [{"panel": "news", "ticker": "LLY"}]
_ask_send("http://api.invalid", "LLY", "Eli Lilly", "ask_turns_LLY", "From the tab?")
_ask_send("http://api.invalid", "LLY", "Eli Lilly", "ask_turns_LLY", "From the board?",
          "td_showing")
st.session_state["td_showing"] = []
_ask_send("http://api.invalid", "LLY", "Eli Lilly", "ask_turns_LLY", "An empty board?",
          "td_showing")
''')
    assert not test.exception, test.exception
    tab, board, empty = [sent["body"] for sent in test.session_state["sent"]]
    assert "showing" not in tab and "showing" not in empty
    assert board["showing"] == [{"panel": "news", "ticker": "LLY"}]
    assert set(board) == {"question", "history", "ticker", "name", "showing"}


def test_the_box_beside_a_board_says_what_the_model_is_told():
    test = _page('''
_ask_tab("http://api.invalid", "LLY", "Eli Lilly")
_ask_tab("http://api.invalid", "LLY", "Eli Lilly", slot="td_", showing_key="td_showing")
''')
    assert not test.exception, test.exception
    assert _md(test).count("by name, and not what they show") == 1


def test_every_key_carries_the_slot_after_the_part_the_stylesheet_matches():
    """theme.py styles the box by key prefix ("st-key-ask_box_"). A slot put first would
    lose the second box its styles; a key with no slot would clash."""
    source = _source()
    keys = re.findall(r'key=f"([^"]+)"', source)
    assert len(keys) == 6
    for key in keys:
        assert re.fullmatch(r"ask_[a-z]+_\{where\}(_\{[a-z]\})?", key), key
    assert 'where = f"{slot}{ticker}"' in source
    theme = (FRONTEND / "theme.py").read_text()
    for prefix in ("st-key-ask_answer_", "st-key-ask_box_", "st-key-ask_starters_"):
        assert prefix in theme
