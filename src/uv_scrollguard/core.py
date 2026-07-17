"""Discovery and lockfile checking for PEP 723 scripts."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

_SKIPPED_DIRECTORIES = frozenset({".git", ".hg", ".svn", ".venv", "__pycache__"})
_SCRIPT_SUFFIXES = frozenset({".py", ".pyw"})
_SCRIPT_OPENER = b"# /// script"
_SCRIPT_CLOSER = b"# ///"
_MINIMUM_UV_VERSION = (0, 5, 17)
_UV_VERSION_PATTERN = re.compile(r"^uv (\d+)\.(\d+)\.(\d+)")


class ExitCode(IntEnum):
    """Stable process outcomes exposed by the CLI."""

    SUCCESS = 0
    CHECK_FAILED = 1
    USAGE_ERROR = 2
    TOOL_ERROR = 3


@dataclass(frozen=True)
class DiscoveryResult:
    """Scripts found in a set of scopes, plus invalid-scope diagnostics."""

    scripts: tuple[Path, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LockFailure:
    """One completed ``uv lock --check`` subprocess that returned nonzero."""

    script: Path
    returncode: int
    output: str


@dataclass(frozen=True)
class CheckResult:
    """Aggregated subprocess results for a group of scripts."""

    failures: tuple[LockFailure, ...] = ()
    tool_error: str | None = None


@dataclass(frozen=True)
class RunResult:
    """End-to-end result suitable for programmatic or CLI use."""

    exit_code: ExitCode
    scripts: tuple[Path, ...]
    failures: tuple[LockFailure, ...] = ()
    errors: tuple[str, ...] = ()


CompletedProcess = subprocess.CompletedProcess[str]
Runner = Callable[..., CompletedProcess]


def _lexical_absolute(
    path: str | os.PathLike[str], *, base: Path | None = None
) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (base or Path.cwd()) / candidate
    return Path(os.path.abspath(candidate))


def _git_files(root: Path) -> tuple[Path, ...] | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return tuple(
        root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name
    )


def _filesystem_files(root: Path) -> Iterable[Path]:
    for directory, names, filenames in os.walk(root):
        names[:] = sorted(name for name in names if name not in _SKIPPED_DIRECTORIES)
        base = Path(directory)
        for filename in sorted(filenames):
            yield base / filename


def _candidate_files(root: Path) -> tuple[Path, ...]:
    git_files = _git_files(root)
    if git_files is not None:
        return git_files
    return tuple(_filesystem_files(root))


def _has_script_block(readline: Callable[[], bytes]) -> bool:
    """Recognize complete PEP 723 script blocks in a single pass."""

    in_block = False
    while line := readline():
        line = line.rstrip(b"\r\n")
        if not in_block:
            in_block = line == _SCRIPT_OPENER
        elif line == _SCRIPT_CLOSER:
            return True
        elif line != b"#" and not line.startswith(b"# "):
            in_block = False
    return False


def _inspect_script(path: Path, *, ordinary: bool) -> tuple[bool, str | None]:
    """Content-check one path, returning only actual read failures as errors."""

    suffix = path.suffix.casefold()
    if ordinary and suffix not in _SCRIPT_SUFFIXES and suffix:
        return False, None
    try:
        with path.open("rb") as file:
            if ordinary and not suffix:
                if not file.readline().startswith(b"#!"):
                    return False, None
                file.seek(0)
            return _has_script_block(file.readline), None
    except OSError as error:
        return False, f"could not read candidate {path}: {error}"


def discover_scripts(
    paths: Sequence[str | os.PathLike[str]] | None = None,
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> DiscoveryResult:
    """Discover PEP 723 scripts in the repository or explicit path scopes.

    Unscoped discovery scans downward, respecting Git ignore rules when Git is
    available. Explicit paths replace that default: files allow any extension,
    while directories are walked directly, including ignored contents.

    Unlike uv workspace discovery, this works without ``pyproject.toml``.
    """

    working_directory = _lexical_absolute(cwd or Path.cwd())
    scopes = tuple(paths or ())
    if not scopes:
        scripts: list[Path] = []
        errors: list[str] = []
        for candidate in _candidate_files(working_directory):
            if not candidate.is_file():
                continue
            is_script, error = _inspect_script(candidate, ordinary=True)
            if error:
                errors.append(error)
            elif is_script:
                scripts.append(candidate)
        return DiscoveryResult(tuple(sorted(scripts, key=os.fspath)), tuple(errors))

    files: set[Path] = set()
    explicit_files: set[Path] = set()
    directories: set[Path] = set()
    errors: list[str] = []
    for raw_path in scopes:
        path = _lexical_absolute(raw_path, base=working_directory)
        if path.is_file():
            files.add(path)
            explicit_files.add(path)
        elif path.is_dir():
            directories.add(path)
        else:
            errors.append(
                f"path does not exist or is not a file or directory: {raw_path}"
            )

    for directory in directories:
        files.update(_filesystem_files(directory))

    scripts: list[Path] = []
    for path in sorted(files, key=os.fspath):
        if not path.is_file():
            continue
        is_script, error = _inspect_script(path, ordinary=path not in explicit_files)
        if error:
            errors.append(error)
        elif is_script:
            scripts.append(path)
    return DiscoveryResult(tuple(scripts), tuple(errors))


def check_lockfiles(
    scripts: Iterable[Path],
    *,
    uv_executable: str = "uv",
    runner: Runner = subprocess.run,
) -> CheckResult:
    """Run uv's strict, non-mutating lock check for every script."""

    try:
        version = runner(
            [uv_executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return CheckResult(tool_error=f"could not run {uv_executable!r}: {error}")
    if version.returncode != 0:
        output = "\n".join(
            part.strip() for part in (version.stdout, version.stderr) if part.strip()
        )
        message = f"could not run {uv_executable!r} successfully"
        if output:
            message = f"{message}: {output}"
        return CheckResult(tool_error=message)
    if match := _UV_VERSION_PATTERN.match(version.stdout):
        installed = tuple(int(part) for part in match.groups())
        if installed < _MINIMUM_UV_VERSION:
            required = ".".join(str(part) for part in _MINIMUM_UV_VERSION)
            found = ".".join(match.groups())
            return CheckResult(
                tool_error=(
                    f"{uv_executable!r} {required} or newer is required; found {found}"
                )
            )

    failures: list[LockFailure] = []
    for script in scripts:
        command = [uv_executable, "lock", "--script", os.fspath(script), "--check"]
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=script.parent,
            )
        except OSError as error:
            return CheckResult(
                tuple(failures), f"could not run {uv_executable!r}: {error}"
            )
        if result.returncode != 0:
            output = "\n".join(
                part.strip() for part in (result.stdout, result.stderr) if part.strip()
            )
            failures.append(LockFailure(script, result.returncode, output))
    return CheckResult(tuple(failures))


def run_checks(
    paths: Sequence[str | os.PathLike[str]] | None = None,
    *,
    require_locks: bool = True,
    cwd: str | os.PathLike[str] | None = None,
    uv_executable: str = "uv",
    runner: Runner = subprocess.run,
) -> RunResult:
    """Discover scripts and verify all selected lockfiles are current."""

    discovery = discover_scripts(paths, cwd=cwd)
    if discovery.errors:
        return RunResult(
            ExitCode.USAGE_ERROR, discovery.scripts, errors=discovery.errors
        )

    scripts = discovery.scripts
    if not require_locks:
        scripts = tuple(
            script for script in scripts if Path(f"{script}.lock").is_file()
        )

    checks = check_lockfiles(scripts, uv_executable=uv_executable, runner=runner)
    if checks.tool_error:
        return RunResult(
            ExitCode.TOOL_ERROR,
            scripts,
            checks.failures,
            (checks.tool_error,),
        )
    if checks.failures:
        return RunResult(ExitCode.CHECK_FAILED, scripts, checks.failures)
    return RunResult(ExitCode.SUCCESS, scripts)
