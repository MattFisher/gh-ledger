"""Find a GitHub token: GITHUB_TOKEN first, then the gh CLI."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from typing import Any


class AuthError(Exception):
    """No usable GitHub token."""


def get_token(
    env: Mapping[str, str] | None = None,
    run: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> str:
    env = os.environ if env is None else env
    token = env.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        proc = run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        proc = None
    if proc is not None and proc.returncode == 0 and str(proc.stdout).strip():
        return str(proc.stdout).strip()
    raise AuthError("No GitHub token: set GITHUB_TOKEN or run `gh auth login`.")
