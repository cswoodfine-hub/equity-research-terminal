"""The Forecast tab's widgets, driven server-side through Streamlit's AppTest.

The what-if sliders are the app's first interactive recompute surface, and a browser
cannot reliably drive a BaseWeb slider with synthetic input, so the widget logic is
tested where it runs: the app script executed in-process, the slider set by key, and
the rendered markdown inspected for the tiles the variation should produce.

Needs the API on localhost:8000 (or ER_API_BASE); skipped when it is not up, so the
suite stays green on a machine that has not started the server.
"""

import os
import pathlib
import sys
import urllib.error
import urllib.request

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"


def _api_up() -> bool:
    base = os.getenv("ER_API_BASE", "http://localhost:8000")
    try:
        with urllib.request.urlopen(base + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


pytestmark = pytest.mark.skipif(not _api_up(), reason="API not running on 8000")


def _patch_button_group_serialisation():
    """Work around a Streamlit AppTest defect, not an app one.

    ButtonGroup.indices iterates ``self.value``, and for a single-select
    segmented_control the session value is a plain string, so it iterates characters
    and every rerun dies on the first segmented control in the app. Rebuilt here to
    treat a scalar as one value and to compare against the option protos' content,
    which is what the real frontend sends.
    """
    from streamlit.testing.v1 import element_tree

    def indices(self):
        values = self.value
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            values = [values]
        labels = [getattr(o, "content", o) for o in self.options]
        out = []
        for v in values:
            label = self.format_func(v) if self.format_func else v
            label = getattr(label, "content", label)
            if label in labels:
                out.append(labels.index(label))
        return out

    element_tree.ButtonGroup.indices = property(indices)


@pytest.fixture(scope="module")
def app():
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    if str(FRONTEND) not in sys.path:
        sys.path.insert(0, str(FRONTEND))
    test = AppTest.from_file(str(APP), default_timeout=120)
    test.query_params["ticker"] = "VRTX"
    test.run()
    return test


def _slider(app, name):
    key = f"fc_wi_{name}_VRTX_371"
    matches = [s for s in app.slider if s.key == key]
    assert matches, f"slider {key} not rendered"
    return matches[0]


def test_the_tab_renders_the_sliders_at_base_values(app):
    assert not app.exception
    assert _slider(app, "volume").value == 1.0
    assert _slider(app, "wacc").value == pytest.approx(0.0985, abs=1e-4)
    assert _slider(app, "pos").value == pytest.approx(0.8075, abs=1e-4)
    body = " ".join(str(m.value) for m in app.markdown)
    assert "1,911.7" in body                # base valuation on the tiles
    assert "vs base" not in body            # no delta badge at rest


def test_moving_the_volume_slider_retells_the_page_itself(app):
    """No separate section: the revenue chart and the valuation tiles are the display,
    and a moved slider changes them, base kept as a muted reference line."""
    _slider(app, "volume").set_value(0.7)
    app.run()
    assert not app.exception
    body = " ".join(str(m.value) for m in app.markdown)
    assert "1,338" in body or "1,337" in body       # varied rNPV on the main tile
    assert "vs base" in body and ("-573" in body or "-574" in body)
    charts = " ".join(str(m.value) for m in app.markdown if "svg" in str(m.value))
    assert "varied" in charts and "base" in charts  # overlay on the top chart


def test_the_reset_button_returns_the_tab_to_rest(app):
    buttons = [b for b in app.button if b.key == "fc_wi_reset_VRTX_371"]
    assert buttons
    buttons[0].click()
    app.run()
    assert not app.exception
    assert _slider(app, "volume").value == 1.0
    body = " ".join(str(m.value) for m in app.markdown)
    assert "1,911.7" in body
    assert "vs base" not in body


def test_the_catalysts_tab_prices_the_casgevy_readout(app):
    """Read-only: the at-stake section renders above the calendar with the one priced
    catalyst, ranked list shape, no resolve clicked against the live database."""
    body = " ".join(str(m.value) for m in app.markdown)
    assert "At stake" in body or "AT STAKE" in body
    assert "swing" in body
    assert "0.95" in body and "0.40" in body        # the two legs on display
