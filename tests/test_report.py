from datetime import date

import pytest
from builders import manifest, tables
from report_data import PRIVATE_REPO, sample_metrics, write_report_data
from typer.testing import CliRunner

from gh_ledger import cli
from gh_ledger.config import Config, ReportConfig
from gh_ledger.metrics import compute_metrics
from gh_ledger.report import build_charts, headline
from gh_ledger.report import images as images_module
from gh_ledger.report.html import build_html
from gh_ledger.report.images import export_images
from gh_ledger.report.redact import redact_repos
from gh_ledger.store import load_table

CONFIG = '[report]\ncompare_at = "2024-03-01"\ntitle = "My year"\n'


def run_report(tmp_path, *extra, config_text=CONFIG):
    data, out = tmp_path / "data", tmp_path / "out"
    if not data.exists():
        write_report_data(data)
    config = tmp_path / "ledger.toml"
    config.write_text(config_text, encoding="utf-8")
    args = ["report", "--data", str(data), "--out", str(out), "--config", str(config), *extra]
    return CliRunner().invoke(cli.app, args), out


def read_html(out):
    # Plotly's embedded JSON escapes "/" as \\u002f, so "octo/app" never appears literally.
    return (out / "report.html").read_text(encoding="utf-8").replace("\\u002f", "/")


def test_report_contains_every_configured_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "find_spec", lambda _name: None)
    result, out = run_report(tmp_path)
    assert result.exit_code == 0, result.output
    html = (out / "report.html").read_text(encoding="utf-8")
    for name in ("activity", "lines", "review_mix", "ai_share", "repos", "compare"):
        assert f'id="chart-{name}"' in html
    assert "My year" in html
    assert '<script src="http' not in html
    assert "Images skipped" in result.output


def test_compare_omitted_without_compare_at(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "find_spec", lambda _name: None)
    result, out = run_report(tmp_path, config_text="")
    assert result.exit_code == 0, result.output
    assert 'id="chart-compare"' not in (out / "report.html").read_text(encoding="utf-8")


def test_redaction_hides_private_names_in_html(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "find_spec", lambda _name: None)
    result, out = run_report(tmp_path, "--redact-private")
    assert result.exit_code == 0, result.output
    html = read_html(out)
    assert PRIVATE_REPO not in html
    assert "private repo 1" in html
    assert "octo/app" in html


def test_without_redaction_private_names_show(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "find_spec", lambda _name: None)
    _, out = run_report(tmp_path)
    assert PRIVATE_REPO in read_html(out)


def test_redacted_images_contain_no_private_names(tmp_path):
    write_report_data(tmp_path / "data")
    metrics = redact_repos(sample_metrics(), load_table(tmp_path / "data", "repos"))
    charts = build_charts(
        metrics, ReportConfig(compare_at=date(2024, 3, 1)), [], date(2024, 1, 1), date(2024, 4, 30)
    )
    skipped = export_images(charts, tmp_path / "charts", (1200, 600))
    if skipped:
        pytest.skip(skipped)
    for name, _ in charts:
        assert (tmp_path / "charts" / f"{name}.png").stat().st_size > 0
        svg = (tmp_path / "charts" / f"{name}.svg").read_text(encoding="utf-8")
        assert PRIVATE_REPO not in svg
    assert "private repo 1" in (tmp_path / "charts" / "repos.svg").read_text(encoding="utf-8")


def test_report_with_no_activity(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "find_spec", lambda _name: None)
    empty = compute_metrics(tables(), manifest(), Config(), "month")
    write_report_data(tmp_path / "data", metrics=empty)
    result, out = run_report(tmp_path)
    assert result.exit_code == 0, result.output
    assert 'id="chart-repos"' in (out / "report.html").read_text(encoding="utf-8")


def test_report_without_summary_is_a_clean_error(tmp_path):
    data = tmp_path / "data"
    write_report_data(data)
    (data / "metrics.csv").unlink()
    result = CliRunner().invoke(
        cli.app, ["report", "--data", str(data), "--out", str(tmp_path / "out")]
    )
    assert result.exit_code == 1
    assert "gh-ledger summary" in result.output


def test_report_bad_events_file_exits_cleanly(tmp_path):
    events = tmp_path / "events.yaml"
    events.write_text("- label: no date\n", encoding="utf-8")
    result, _ = run_report(tmp_path, "--events", str(events))
    assert result.exit_code == 1
    assert "missing date" in result.output
    assert "Traceback" not in result.output


def test_build_html_escapes_headline_and_inlines_plotly_once():
    charts = build_charts(sample_metrics(), ReportConfig(), [], date(2024, 1, 1), date(2024, 4, 30))
    html = build_html("<Title>", "sub", [("A & B", "1")], charts)
    assert "&lt;Title&gt;" in html
    assert "A &amp; B" in html
    assert html.count('<section class="chart"') == len(charts)
    # plotly.js is several MB: inlined once, extra charts add only their data.
    one = build_html("t", "s", [], charts[:1])
    assert len(one) > 1_000_000
    assert len(html) - len(one) < 1_000_000


def test_headline_strip_present():
    html = build_html("t", "s", headline(sample_metrics()), [])
    assert "PRs merged" in html
