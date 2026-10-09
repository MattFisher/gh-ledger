"""Measure one GitHub user's activity over time and chart it"""

from importlib.metadata import PackageNotFoundError, version

# The version is set once, in pyproject.toml; this reads it back from the
# installed package metadata.
try:
    __version__ = version("gh-ledger")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "unknown"
