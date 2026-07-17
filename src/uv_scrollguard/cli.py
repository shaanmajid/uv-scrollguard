"""Command-line interface for uv-scrollguard."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import ExitCode, RunResult, run_checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv-scrollguard",
        description="Check uv PEP 723 script lockfiles without modifying them.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files and/or directories to check (default: the current directory tree)",
    )
    parser.add_argument(
        "--existing-only",
        action="store_true",
        help="check existing script lockfiles without requiring missing ones",
    )
    parser.add_argument(
        "--paths-from-env",
        metavar="NAME",
        help="also read newline-delimited paths from environment variable NAME",
    )
    return parser


def _display(path: Path) -> str:
    try:
        return os.fspath(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return os.fspath(path)


def _report(result: RunResult, *, existing_only: bool = False) -> None:
    if result.exit_code is ExitCode.SUCCESS:
        if result.scripts:
            print(f"Checked {len(result.scripts)} script(s): lockfiles are current.")
        elif existing_only:
            print("No existing PEP 723 script lockfiles found.")
        else:
            print("No PEP 723 scripts found.")
        return

    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for failure in result.failures:
        print(
            f"error: uv check failed for {_display(failure.script)} "
            f"(uv exited {failure.returncode})",
            file=sys.stderr,
        )
        if failure.output:
            for line in failure.output.splitlines():
                print(f"  {line}", file=sys.stderr)
    if result.failures:
        print(
            f"{len(result.failures)} of {len(result.scripts)} uv script check(s) failed.",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its process exit status."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    paths = list(arguments.paths)
    if arguments.paths_from_env:
        value = os.environ.get(arguments.paths_from_env)
        if value is None:
            parser.error(f"environment variable is not set: {arguments.paths_from_env}")
        paths.extend(line for line in value.splitlines() if line)

    result = run_checks(paths or None, require_locks=not arguments.existing_only)
    _report(result, existing_only=arguments.existing_only)
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
