# pyright: basic
# plotly is untyped; strict mode can't help here.
"""Assemble the self-contained HTML report."""

from __future__ import annotations

import html
from collections.abc import Sequence

import plotly.graph_objects as go

STYLE = """
:root { color-scheme: light; --surface: #fcfcfb; --text: #0b0b0b; --muted: #52514e; --rule: #e7e6e2; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1240px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 28px; margin: 0 0 4px; }
.subtitle { color: var(--muted); margin: 0 0 24px; }
.headline { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 32px; }
.tile { flex: 1 1 150px; border: 1px solid var(--rule); border-radius: 8px; padding: 12px 16px; }
.tile .value { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .label { color: var(--muted); font-size: 13px; }
.chart { margin: 0 0 40px; border-top: 1px solid var(--rule); padding-top: 16px; }
"""


def build_html(
    title: str,
    subtitle: str,
    headline: Sequence[tuple[str, str]],
    charts: Sequence[tuple[str, go.Figure]],
) -> str:
    tiles = "\n".join(
        f'<div class="tile"><div class="value">{html.escape(value)}</div>'
        f'<div class="label">{html.escape(label)}</div></div>'
        for label, value in headline
    )
    sections: list[str] = []
    for i, (name, fig) in enumerate(charts):
        div = fig.to_html(
            full_html=False,
            include_plotlyjs=i == 0,  # inline the library once; the file works offline
            div_id=f"plot-{name}",
            config={"displaylogo": False, "responsive": True},
        )
        sections.append(f'<section class="chart" id="chart-{name}">\n{div}\n</section>')
    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>{html.escape(title)}</h1>
<p class="subtitle">{html.escape(subtitle)}</p>
<div class="headline">
{tiles}
</div>
{body}
</main>
</body>
</html>
"""
