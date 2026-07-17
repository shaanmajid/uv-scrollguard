from __future__ import annotations

from pathlib import Path

from uv_scrollguard import cli
from uv_scrollguard.core import ExitCode, LockFailure, RunResult


def test_newline_paths_preserve_spaces(monkeypatch, capsys) -> None:
    captured: list[tuple[list[str] | None, bool]] = []

    def fake_run(paths: list[str] | None, *, require_locks: bool) -> RunResult:
        captured.append((paths, require_locks))
        return RunResult(ExitCode.SUCCESS, ())

    monkeypatch.setenv("ACTION_PATHS", "scripts/one file.py\nscripts/two.py\n")
    monkeypatch.setattr(cli, "run_checks", fake_run)

    status = cli.main(["direct.py", "--paths-from-env", "ACTION_PATHS"])
    capsys.readouterr()

    assert status == 0
    assert captured == [(["direct.py", "scripts/one file.py", "scripts/two.py"], True)]


def test_existing_only_selects_non_strict_policy(monkeypatch, capsys) -> None:
    captured: list[bool] = []

    def fake_run(paths: list[str] | None, *, require_locks: bool) -> RunResult:
        captured.append(require_locks)
        return RunResult(ExitCode.SUCCESS, ())

    monkeypatch.setattr(cli, "run_checks", fake_run)

    status = cli.main(["--existing-only"])
    output = capsys.readouterr()

    assert status == 0
    assert captured == [False]
    assert output.out == "No existing PEP 723 script lockfiles found.\n"


def test_aggregated_failure_diagnostics_and_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    result = RunResult(
        ExitCode.CHECK_FAILED,
        (first, second),
        (
            LockFailure(first, 1, "first is stale"),
            LockFailure(second, 2, "invalid metadata"),
        ),
    )
    monkeypatch.setattr(cli, "run_checks", lambda paths, *, require_locks: result)

    status = cli.main([])
    captured = capsys.readouterr()

    assert status == 1
    assert "uv check failed for" in captured.err
    assert "first is stale" in captured.err
    assert "invalid metadata" in captured.err
    assert "2 of 2 uv script check(s) failed" in captured.err


def test_no_scripts_is_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_checks",
        lambda paths, *, require_locks: RunResult(ExitCode.SUCCESS, ()),
    )

    status = cli.main([])
    captured = capsys.readouterr()

    assert status == 0
    assert captured.out == "No PEP 723 scripts found.\n"
