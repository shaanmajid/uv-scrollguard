from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

MARKER = "# " + "///"
SCRIPT = f"""\
{MARKER} script
# requires-python = ">=3.10"
# dependencies = []
{MARKER}
print("hello")
"""


def test_real_cli_accepts_current_and_rejects_stale_and_missing_locks(
    tmp_path: Path,
) -> None:
    executable = shutil.which("uv-scrollguard")
    if executable is None:
        pytest.fail("uv-scrollguard executable is not installed")

    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    script = tmp_path / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")
    subprocess.run(["uv", "lock", "--script", script], check=True, cwd=tmp_path)

    current = subprocess.run([executable], cwd=tmp_path, capture_output=True, text=True)

    script.write_text(SCRIPT.replace(">=3.10", ">=3.11"), encoding="utf-8")
    stale = subprocess.run([executable], cwd=tmp_path, capture_output=True, text=True)
    stale_existing_only = subprocess.run(
        [executable, "--existing-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    subprocess.run(["uv", "lock", "--script", script], check=True, cwd=tmp_path)
    script.with_suffix(".py.lock").unlink()
    missing = subprocess.run([executable], cwd=tmp_path, capture_output=True, text=True)
    existing_only = subprocess.run(
        [executable, "--existing-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert current.returncode == 0, current.stderr
    assert "Checked 1 script(s): lockfiles are current" in current.stdout
    assert stale.returncode == 1
    assert "uv check failed" in stale.stderr
    assert stale_existing_only.returncode == 1
    assert "uv check failed" in stale_existing_only.stderr
    assert missing.returncode == 1
    assert "uv check failed" in missing.stderr
    assert existing_only.returncode == 0
    assert "No existing PEP 723 script lockfiles found" in existing_only.stdout
