# Screenshots

These are deterministic renders of the terminal's output, captured headless.

- `tearsheet-lly.png` — the one-page A4 company tearsheet (`exports/`), the
  print artefact, showing the price line, financial snapshot, LOE cliff, five
  catalysts, and the note.
- `analyst-views.png` — the new analyst views built from live data: revenue-at-
  risk waterfall, universe share bars, the slippage dumbbell, the universe
  catalyst grid, and the coverage small multiples.
- `chart-primitives.png` — the ten SVG chart primitives in one gallery.
- `spine-and-donut.png` — the signature time spine, the dual-axis line chart,
  and the leader-line donut.

Live per-tab screenshots of the running Streamlit app are not included: a
hydrating Streamlit page does not capture reliably under headless Chrome (it
snaps the loading skeleton), and the app's tab state is not URL-addressable, so
tabs cannot be selected without a scripted click the headless path does not run.
Every tab was instead verified interactively in a real browser during the build,
and the renders above are the same components those tabs draw.
