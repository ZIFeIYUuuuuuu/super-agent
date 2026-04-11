from __future__ import annotations

import os
from pathlib import Path


def load_env_file(dotenv_path: Path | None = None, *, override: bool = False) -> None:
    """Load simple KEY=VALUE pairs from a project .env file into process env vars."""
    resolved_path = dotenv_path or Path(__file__).resolve().parents[1] / ".env"
    if not resolved_path.exists():
        return

    for raw_line in resolved_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key:
            continue
        if not override and env_key in os.environ:
            continue

        os.environ[env_key] = _normalize_env_value(value)


def _normalize_env_value(raw_value: str) -> str:
    """Normalize one .env value, supporting quotes and inline comments."""
    value = raw_value.strip()
    if not value:
        return ""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        unwrapped = value[1:-1]
        if quote == '"':
            return (
                unwrapped.replace(r"\\", "\\")
                .replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t")
                .replace(r"\"", '"')
            )
        return unwrapped

    return _strip_inline_comment(value).strip()


def _strip_inline_comment(value: str) -> str:
    """Remove trailing inline comments from unquoted values."""
    in_single_quote = False
    in_double_quote = False

    for index, character in enumerate(value):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if character == "#" and not in_single_quote and not in_double_quote:
            if index == 0 or value[index - 1].isspace():
                return value[:index]
    return value
