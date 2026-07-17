from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from uv_scrollguard.core import ExitCode, check_lockfiles, run_checks

MARKER = "# " + "///"
SCRIPT = f"""\
{MARKER} script
# dependencies = []
{MARKER}
"""


def test_strict_uv_command_and_aggregated_failures(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    calls: list[list[str]] = []
    working_directories: list[object] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        working_directories.append(kwargs.get("cwd"))
        if command == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.5.17\n")
        return subprocess.CompletedProcess(
            command,
            0 if command[3] == str(first) else 1,
            stdout="",
            stderr="lockfile is stale",
        )

    result = check_lockfiles([first, second], runner=runner)

    assert calls == [
        ["uv", "--version"],
        ["uv", "lock", "--script", str(first), "--check"],
        ["uv", "lock", "--script", str(second), "--check"],
    ]
    assert working_directories == [None, tmp_path, tmp_path]
    assert len(result.failures) == 1
    assert result.failures[0].script == second
    assert result.failures[0].output == "lockfile is stale"


def test_unavailable_uv_is_a_tool_error_even_without_scripts() -> None:
    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    result = check_lockfiles([], runner=runner)

    assert result.failures == ()
    assert result.tool_error is not None
    assert "could not run 'uv'" in (result.tool_error or "")


def test_broken_uv_fails_before_lock_checks(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="uv installation is broken"
        )

    result = check_lockfiles([tmp_path / "tool.py"], runner=runner)

    assert calls == [["uv", "--version"]]
    assert result.failures == ()
    assert result.tool_error == (
        "could not run 'uv' successfully: uv installation is broken"
    )


def test_unsupported_uv_fails_before_lock_checks(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="uv 0.5.16\n")

    result = check_lockfiles([tmp_path / "tool.py"], runner=runner)

    assert calls == [["uv", "--version"]]
    assert result.failures == ()
    assert result.tool_error == "'uv' 0.5.17 or newer is required; found 0.5.16"


def test_unrecognized_uv_version_defers_to_the_lock_command(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="uv future\n")

    script = tmp_path / "tool.py"
    result = check_lockfiles([script], runner=runner)

    assert calls == [
        ["uv", "--version"],
        ["uv", "lock", "--script", str(script), "--check"],
    ]
    assert result.tool_error is None


def test_run_checks_returns_tool_error_status(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    result = run_checks([script], cwd=tmp_path, runner=runner)

    assert result.exit_code is ExitCode.TOOL_ERROR
    assert "could not run 'uv'" in result.errors[0]


def test_bad_scope_returns_usage_error(tmp_path: Path) -> None:
    result = run_checks(["missing"], cwd=tmp_path)

    assert result.exit_code is ExitCode.USAGE_ERROR
    assert result.errors == (
        "path does not exist or is not a file or directory: missing",
    )


def test_candidate_read_error_makes_end_to_end_result_nonzero(tmp_path: Path) -> None:
    script = tmp_path / "private.py"
    script.write_text(SCRIPT, encoding="utf-8")
    error = PermissionError(13, "Permission denied", script)

    with patch.object(Path, "open", side_effect=error):
        result = run_checks([script], cwd=tmp_path)

    assert result.exit_code is ExitCode.USAGE_ERROR
    assert "could not read candidate" in result.errors[0]


def test_completed_nonzero_uv_check_is_check_failed_regardless_of_stderr(
    tmp_path: Path,
) -> None:
    script = tmp_path / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.28\n")
        return subprocess.CompletedProcess(
            command, 2, stdout="", stderr="temporary registry failure"
        )

    result = run_checks([script], cwd=tmp_path, runner=runner)

    assert result.exit_code is ExitCode.CHECK_FAILED
    assert result.failures[0].output == "temporary registry failure"


def test_explicit_scope_with_no_scripts_returns_success(tmp_path: Path) -> None:
    result = run_checks([tmp_path], cwd=tmp_path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.scripts == ()


def test_existing_only_skips_scripts_without_sidecars(tmp_path: Path) -> None:
    locked = tmp_path / "locked.py"
    missing = tmp_path / "missing.py"
    locked.write_text(SCRIPT, encoding="utf-8")
    missing.write_text(SCRIPT, encoding="utf-8")
    Path(f"{locked}.lock").touch()
    calls: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.28\n")

    result = run_checks(
        [locked, missing], cwd=tmp_path, require_locks=False, runner=runner
    )

    assert result.exit_code is ExitCode.SUCCESS
    assert result.scripts == (locked,)
    assert calls == [
        ["uv", "--version"],
        ["uv", "lock", "--script", str(locked), "--check"],
    ]


def test_real_uv_check_succeeds_then_detects_missing_sidecar(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")
    subprocess.run(
        ["uv", "lock", "--script", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    current = run_checks([script], cwd=tmp_path)
    script.with_suffix(".py.lock").unlink()
    missing = run_checks([script], cwd=tmp_path)

    assert current.exit_code is ExitCode.SUCCESS
    assert missing.exit_code is ExitCode.CHECK_FAILED
    assert missing.failures[0].script == script
