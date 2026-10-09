from datetime import date

import pytest

from gh_ledger.config import CHART_NAMES, ConfigError, load_config
from gh_ledger.filters import DEFAULT_AI_PATTERNS, DEFAULT_EXCLUDES


def write(tmp_path, text):
    path = tmp_path / "ledger.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_no_file_gives_defaults():
    config = load_config(None)
    assert config.filters.exclude == DEFAULT_EXCLUDES
    assert config.filters.per_file_cap == 1000
    assert config.filters.count_unmerged_pr_lines is False
    assert config.ai.patterns == DEFAULT_AI_PATTERNS
    assert config.report.period == "month"
    assert config.report.title == "GitHub activity"
    assert config.report.top_repos == 8
    assert config.report.compare_at is None
    assert config.report.charts == CHART_NAMES
    assert config.report.image_size == (1200, 600)


def test_spec_example(tmp_path):
    config = load_config(
        write(
            tmp_path,
            """
[filters]
extra_exclude = ["fixtures/**"]
per_file_cap = 1000
count_unmerged_pr_lines = false

[ai]
patterns = ['(?i)co-authored-by:.*\\b(claude|copilot)\\b']

[report]
period = "month"
title = "GitHub activity"
top_repos = 8
compare_at = "2025-02-24"
charts = ["activity", "lines", "review_mix", "ai_share", "repos", "compare"]
image_size = [1200, 600]
""",
        )
    )
    assert config.filters.exclude == (*DEFAULT_EXCLUDES, "fixtures/**")
    assert config.report.compare_at == date(2025, 2, 24)
    assert len(config.ai.patterns) == 1


def test_exclude_replaces_defaults(tmp_path):
    config = load_config(write(tmp_path, '[filters]\nexclude = ["*.lock"]\n'))
    assert config.filters.exclude == ("*.lock",)


def test_per_file_cap_false_disables(tmp_path):
    assert (
        load_config(write(tmp_path, "[filters]\nper_file_cap = false\n")).filters.per_file_cap
        is None
    )


def test_toml_date_literal_for_compare_at(tmp_path):
    config = load_config(write(tmp_path, "[report]\ncompare_at = 2025-02-24\n"))
    assert config.report.compare_at == date(2025, 2, 24)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[filters]\nexclud = []\n", "unknown key exclud in \\[filters\\]"),
        ("[filter]\n", "unknown key filter"),
        ("[ai]\npatterns = ['(unclosed']\n", "invalid regex"),
        ("[filters]\nper_file_cap = true\n", "per_file_cap"),
        ("[filters]\nper_file_cap = 0\n", "per_file_cap"),
        ('[report]\nperiod = "year"\n', "period must be one of"),
        ('[report]\ncharts = ["activity", "pie"]\n', "unknown chart pie"),
        ("[report]\ntop_repos = 12\n", "top_repos must be an integer from 1 to 8"),
        ('[report]\ncompare_at = "last spring"\n', "compare_at"),
        ("[report]\nimage_size = [1200]\n", "image_size"),
        ("[filters]\nextra_exclude = 'x'\n", "list of strings"),
        ("filters = 3\n", "\\[filters\\] must be a table"),
        ("[report\n", "ledger.toml"),
    ],
)
def test_invalid_config_names_the_problem(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_example_config_loads():
    from pathlib import Path

    config = load_config(Path(__file__).parent.parent / "examples" / "ledger.toml")
    assert config.report.compare_at == date(2025, 2, 24)
    assert config.filters.exclude[-1] == "fixtures/**"
