import pytest

from gh_ledger.filters import DEFAULT_AI_PATTERNS, DEFAULT_EXCLUDES, AiMatcher, PathFilter


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("uv.lock", True),
        ("services/api/poetry.lock", True),
        ("web/package-lock.json", True),
        ("go.sum", True),
        ("data/results.json", True),
        ("logs/run.jsonl", True),
        ("notebooks/explore.ipynb", True),
        ("assets/logo.svg", True),
        ("web/node_modules/react/index.js", True),
        ("vendor/lib.go", True),
        ("app/dist/bundle.js", True),
        ("build/out.o", True),
        ("static/app.min.js", True),
        ("static/app.min.css", True),
        ("static/app.js.map", True),
        ("src/app.py", False),
        ("src/build_tools.py", False),
        ("docs/vendored.md", False),
        ("src/json_utils.py", False),
        ("README.md", False),
    ],
)
def test_default_exclusions(path, excluded):
    assert PathFilter(DEFAULT_EXCLUDES).excluded(path) is excluded


def test_slash_pattern_is_anchored_at_repo_root():
    path_filter = PathFilter(["fixtures/**"])
    assert path_filter.excluded("fixtures/a/b.py")
    assert not path_filter.excluded("src/fixtures/a.py")


def test_double_star_slash_matches_any_depth_including_root():
    path_filter = PathFilter(["**/generated/*.py"])
    assert path_filter.excluded("a/b/generated/x.py")
    assert path_filter.excluded("generated/x.py")
    assert not path_filter.excluded("generated/sub/x.py")


def test_nested_directory_pattern():
    path_filter = PathFilter(["docs/api/"])
    assert path_filter.excluded("docs/api/index.md")
    assert not path_filter.excluded("src/docs/api/index.md")


def test_no_patterns_excludes_nothing():
    assert not PathFilter([]).excluded("uv.lock")


@pytest.mark.parametrize(
    ("text", "co_authors", "expected"),
    [
        ("", ["Claude <noreply@anthropic.com>"], True),
        ("Fix\n\nCo-authored-by: GitHub Copilot <copilot@github.com>", [], True),
        ("🤖 Generated with [Claude Code](https://claude.com/claude-code)", [], True),
        ("*Posted by [Claude Code](https://claude.com/claude-code) on Matt's behalf.*", [], True),
        ("generated with claude code", [], True),
        ("Co-authored-by: Jane Doe <jane@example.com>", ["Jane Doe <jane@example.com>"], False),
        ("Talked to Claudette about this", [], False),
        ("", [], False),
    ],
)
def test_default_ai_markers(text, co_authors, expected):
    assert AiMatcher(DEFAULT_AI_PATTERNS).matches(text, co_authors) is expected


def test_custom_ai_pattern():
    assert AiMatcher([r"(?i)\bwritten by gpt\b"]).matches("Written by GPT")
