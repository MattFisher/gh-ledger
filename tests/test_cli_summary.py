from builders import manifest, pr
from typer.testing import CliRunner

from gh_ledger import cli
from gh_ledger.model import FetchResult
from gh_ledger.store import read_metrics, write_manifest, write_tables


def make_data(tmp_path):
    write_tables(tmp_path, FetchResult(prs=[pr()]))
    write_manifest(tmp_path, manifest())


def test_summary_writes_metrics_and_prints_table(tmp_path):
    make_data(tmp_path)
    result = CliRunner().invoke(cli.app, ["summary", "--data", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "2024-01-01" in result.output
    metrics = read_metrics(tmp_path / "metrics.csv")
    assert set(metrics["period"]) == {"2024-01-01", "2024-02-01", "2024-03-01"}


def test_period_flag_overrides_config(tmp_path):
    make_data(tmp_path)
    result = CliRunner().invoke(
        cli.app, ["summary", "--data", str(tmp_path), "--period", "quarter"]
    )
    assert result.exit_code == 0, result.output
    assert set(read_metrics(tmp_path / "metrics.csv")["period"]) == {"2024-01-01"}


def test_summary_without_fetch_is_a_clean_error(tmp_path):
    result = CliRunner().invoke(cli.app, ["summary", "--data", str(tmp_path)])
    assert result.exit_code == 1
    assert "gh-ledger fetch" in result.output


def test_bad_config_is_a_clean_error(tmp_path):
    make_data(tmp_path)
    config = tmp_path / "ledger.toml"
    config.write_text("[ai]\npatterns = ['(']\n", encoding="utf-8")
    result = CliRunner().invoke(
        cli.app, ["summary", "--data", str(tmp_path), "--config", str(config)]
    )
    assert result.exit_code == 1
    assert "invalid regex" in result.output
    assert "Traceback" not in result.output
