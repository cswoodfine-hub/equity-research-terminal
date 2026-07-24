"""Component layer: tokens, SVG chart primitives, and the render shim.

Everything visual renders through here. Charts are pure functions returning SVG
strings with explicit dimensions, which is what makes them immune to Streamlit's
hidden-tab measurement defect: an SVG with its own viewBox and width needs nothing
measured at render time.
"""
