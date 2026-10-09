# pyright: basic
# plotly is untyped; strict mode can't help here.
"""PNG and SVG export of each chart, via the optional kaleido extra."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path

import plotly.graph_objects as go


def export_images(
    charts: Sequence[tuple[str, go.Figure]], out_dir: Path, size: tuple[int, int]
) -> str | None:
    """Write `<name>.png` and `<name>.svg` per chart. Returns why images were skipped, or None."""
    if find_spec("kaleido") is None:
        return "kaleido is not installed; install gh-ledger[images] for PNG/SVG export"
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = size
    try:
        for name, fig in charts:
            for extension in ("png", "svg"):
                fig.write_image(out_dir / f"{name}.{extension}", width=width, height=height)
    except Exception as exc:  # kaleido drives a local Chrome; any failure there means no images
        return f"image export failed ({exc}); kaleido needs Chrome, which `plotly_get_chrome` can install"
    return None
