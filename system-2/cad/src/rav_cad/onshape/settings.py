"""Onshape settings from the repo-root `.env` (git-ignored; `.env.example` lists the names).

Real environment variables win over the file. Key values are never printed: `OnshapeSettings.__repr__` hides them.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field
from typing import Mapping

DEFAULT_BASE_URL = "https://cad.onshape.com"
NAMES = ("ONSHAPE_ACCESS_KEY", "ONSHAPE_SECRET_KEY", "ONSHAPE_BASE_URL", "ONSHAPE_DEV_DOCUMENT_URL")
_ROOT_MARKERS = (".env.example", ".git")


class OnshapeSettingsError(RuntimeError):
    """Raised when required Onshape settings are missing."""


@dataclass(frozen=True)
class OnshapeSettings:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    dev_document_url: str | None = None
    env_file: pathlib.Path | None = None

    @property
    def has_keys(self) -> bool:
        return bool(self.access_key and self.secret_key)


def find_repo_root(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The first ancestor holding `.env.example` or `.git`: from `start`, else the package location, else the cwd."""
    starts = [start] if start else [pathlib.Path(__file__).resolve().parent, pathlib.Path.cwd().resolve()]
    for s in starts:
        for d in (s, *s.parents):
            if any((d / m).exists() for m in _ROOT_MARKERS):
                return d
    return None


def parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """A tiny .env parser: KEY=VALUE lines, `#` comments, optional `export ` prefix and surrounding quotes."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key.strip()] = value
    return out


def load_settings(env_file: pathlib.Path | str | None = None, environ: Mapping[str, str] | None = None,
                  require_keys: bool = True) -> OnshapeSettings:
    """Read the Onshape settings. A non-empty real environment variable beats the `.env` file."""
    environ = os.environ if environ is None else environ
    if env_file is None:
        root = find_repo_root()
        env_file = root / ".env" if root else None
    env_file = pathlib.Path(env_file) if env_file else None
    file_values = parse_env_file(env_file) if env_file and env_file.is_file() else {}

    def get(name: str) -> str:
        return (environ.get(name) or file_values.get(name) or "").strip()

    settings = OnshapeSettings(
        access_key=get("ONSHAPE_ACCESS_KEY"),
        secret_key=get("ONSHAPE_SECRET_KEY"),
        base_url=(get("ONSHAPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        dev_document_url=get("ONSHAPE_DEV_DOCUMENT_URL") or None,
        env_file=env_file,
    )
    if require_keys and not settings.has_keys:
        missing = [n for n in ("ONSHAPE_ACCESS_KEY", "ONSHAPE_SECRET_KEY") if not get(n)]
        where = env_file if env_file else "<repo root>/.env"
        raise OnshapeSettingsError(
            f"Missing {', '.join(missing)}. Fill them in {where} (copy .env.example; keys come from "
            "dev-portal.onshape.com > API keys), or set them as environment variables."
        )
    return settings
