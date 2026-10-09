# pyright: basic
# pandas leaves too many partially-unknown types for strict mode.
"""CSV tables and the manifest on disk."""

from __future__ import annotations

import csv
import dataclasses
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd

from gh_ledger.model import TABLES, FetchResult, Manifest, columns, to_csv_row

# PR text includes every commit message, which can pass the csv module's 128 KiB default.
csv.field_size_limit(2**31 - 1)

MANIFEST = "manifest.json"


class StoreError(Exception):
    """A data file is missing or does not match the expected schema."""


def upsert_table(
    path: Path, fieldnames: Sequence[str], key: Sequence[str], rows: Iterable[dict[str, str]]
) -> int:
    """Merge rows into a CSV. Existing rows sharing a key with any new row are replaced.

    Returns the number of rows written.
    """
    new_rows = list(rows)
    new_keys = {tuple(row[k] for k in key) for row in new_rows}
    kept: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(fieldnames):
                raise StoreError(
                    f"{path} has columns {reader.fieldnames}, expected {list(fieldnames)}"
                )
            kept = [row for row in reader if tuple(row[k] for k in key) not in new_keys]
    merged = sorted([*kept, *new_rows], key=lambda row: tuple(row[k] for k in key))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(merged)
    tmp.replace(path)
    return len(merged)


def write_tables(data_dir: Path, result: FetchResult) -> None:
    """Upsert every table, writing header-only files for tables with no rows."""
    for spec in TABLES:
        upsert_table(
            data_dir / f"{spec.name}.csv",
            columns(spec.row_type),
            spec.key,
            (to_csv_row(row) for row in result.rows(spec.name)),
        )


def load_table(data_dir: Path, name: str) -> pd.DataFrame:
    """Read one table with every column as str and empty cells as ''."""
    path = data_dir / f"{name}.csv"
    if not path.exists():
        raise StoreError(f"{path} not found; run `gh-ledger fetch` first")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    return {spec.name: load_table(data_dir, spec.name) for spec in TABLES}


def read_manifest(data_dir: Path) -> Manifest | None:
    path = data_dir / MANIFEST
    if not path.exists():
        return None
    return Manifest(**json.loads(path.read_text(encoding="utf-8")))


def write_manifest(data_dir: Path, manifest: Manifest) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dataclasses.asdict(manifest), indent=2) + "\n"
    (data_dir / MANIFEST).write_text(text, encoding="utf-8")


def write_metrics(metrics: pd.DataFrame, path: Path) -> None:
    """Write long-format metrics; whole numbers without '.0', empty cells for NaN."""
    out = metrics[["period", "metric", "value", "repo"]].copy()
    out["value"] = [_format_value(v) for v in out["value"]]
    out.to_csv(path, index=False)


def _format_value(value: float) -> str:
    if pd.isna(value):
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:.6g}"


def read_metrics(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise StoreError(f"{path} not found; run `gh-ledger summary` first")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["value"] = pd.to_numeric(frame["value"].replace("", float("nan")))
    return frame
