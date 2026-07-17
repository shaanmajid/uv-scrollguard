from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from uv_scrollguard.core import discover_scripts

MARKER = "# " + "///"
SCRIPT = f"""\
{MARKER} script
# dependencies = []
{MARKER}
print("hello")
"""
SHEBANG_SCRIPT = "#!/usr/bin/env -S uv run --script\n" + SCRIPT


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", path], check=True)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def test_unscoped_ordinary_candidates_include_pyw_and_shebang_files(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    expected = (
        tmp_path / "app.py",
        tmp_path / "app.pyw",
        tmp_path / "run-app",
        tmp_path / "latin-1-script",
        tmp_path / "upper.PY",
    )
    expected[0].write_text(SCRIPT, encoding="utf-8")
    expected[1].write_text(SCRIPT, encoding="utf-8")
    expected[2].write_text(SHEBANG_SCRIPT, encoding="utf-8")
    expected[3].write_bytes(
        b"#!/usr/bin/env python\n# coding: latin-1\n" + SCRIPT.encode() + b"# caf\xe9\n"
    )
    expected[4].write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "no-shebang").write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "non-utf8").write_bytes(b"#!/usr/bin/env python\n\xff\n")
    (tmp_path / "script.txt").write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts(cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == tuple(sorted(path.resolve() for path in expected))


def test_directory_scope_uses_the_same_ordinary_candidate_set(tmp_path: Path) -> None:
    _git_init(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()
    expected = (scope / "window.pyw", scope / "run-window")
    expected[0].write_text(SCRIPT, encoding="utf-8")
    expected[1].write_text(SHEBANG_SCRIPT, encoding="utf-8")
    (scope / "no-shebang").write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "outside.py").write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts([scope], cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == tuple(sorted(expected))


def test_unscoped_scans_cwd_down_and_respects_gitignore(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    wanted = tmp_path / "scripts" / "tool.py"
    wanted.parent.mkdir()
    wanted.write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "scripts" / "module.py").write_text("answer = 42\n", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "hidden.py").write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts(cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == (_lexical_absolute(wanted),)


def test_unscoped_does_not_ascend_above_cwd(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "root.py").write_text(SCRIPT, encoding="utf-8")
    nested = tmp_path / "sub" / "tool.py"
    nested.parent.mkdir()
    nested.write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts(cwd=tmp_path / "sub")

    assert result.errors == ()
    assert result.scripts == (_lexical_absolute(nested),)


def test_explicit_directory_includes_gitignored_scripts(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text("generated/\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    script = generated / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")

    unscoped = discover_scripts(cwd=tmp_path)
    scoped = discover_scripts([generated], cwd=tmp_path)

    assert unscoped.scripts == ()
    assert scoped.errors == ()
    assert scoped.scripts == (_lexical_absolute(script),)


def test_explicit_scopes_deduplicate_and_files_allow_any_extension(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    directory = tmp_path / "tools"
    directory.mkdir()
    standard = directory / "standard.py"
    standard.write_text(SCRIPT, encoding="utf-8")
    nonstandard = tmp_path / "run-tool"
    nonstandard.write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts(
        ["tools", "tools/standard.py", "run-tool", "run-tool"], cwd=tmp_path
    )

    assert result.errors == ()
    assert result.scripts == tuple(
        sorted((_lexical_absolute(nonstandard), _lexical_absolute(standard)))
    )


def test_explicit_directory_with_no_scripts_is_successfully_empty(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "module.py").write_text("value = 1\n", encoding="utf-8")

    result = discover_scripts([empty], cwd=tmp_path)

    assert result.scripts == ()
    assert result.errors == ()


def test_marker_on_same_line_as_string_content_is_not_a_script(tmp_path: Path) -> None:
    _git_init(tmp_path)
    module = tmp_path / "fixture.py"
    module.write_text('EXAMPLE = """# /// script\n# ///\n"""\n', encoding="utf-8")

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == ()


def test_marker_lines_inside_string_follow_reference_discovery(tmp_path: Path) -> None:
    _git_init(tmp_path)
    module = tmp_path / "fixture.py"
    module.write_text(
        'EXAMPLE = """\n# /// script\n# dependencies = []\n# ///\n"""\n',
        encoding="utf-8",
    )

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(module),)


def test_complete_script_block_accepts_crlf_newlines(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "windows.py"
    script.write_bytes(b"# /// script\r\n# dependencies = []\r\n# ///\r\n")

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)


def test_unknown_encoding_cookie_does_not_hide_script_block(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "unknown-encoding.py"
    script.write_bytes(b"# coding: unknown\n# /// script\n# dependencies = []\n# ///\n")

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)


def test_unclosed_script_block_is_ignored(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "unfinished.py"
    script.write_text(
        "# /// script\n# dependencies = []\n",
        encoding="utf-8",
    )

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == ()


def test_complete_script_block_survives_later_token_error(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "unfinished.py"
    script.write_text(
        '# /// script\n# dependencies = []\n# ///\n"""\n',
        encoding="utf-8",
    )

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)


def test_complete_script_block_survives_earlier_syntax_error(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "unfinished.py"
    script.write_text(
        "if True:\n    pass\n  pass\n# /// script\n# dependencies = []\n# ///\n",
        encoding="utf-8",
    )

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)


def test_complete_script_block_can_be_followed_by_a_comment(tmp_path: Path) -> None:
    _git_init(tmp_path)
    script = tmp_path / "copyrighted.py"
    script.write_text(
        "# /// script\n# dependencies = []\n# ///\n# Copyright 2026\n",
        encoding="utf-8",
    )

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)


def test_candidate_permission_error_is_reported(tmp_path: Path) -> None:
    _git_init(tmp_path)
    candidate = tmp_path / "private.py"
    candidate.write_text(SCRIPT, encoding="utf-8")
    error = PermissionError(13, "Permission denied", candidate)

    with patch.object(Path, "open", side_effect=error):
        result = discover_scripts(cwd=tmp_path)

    assert result.scripts == ()
    assert len(result.errors) == 1
    assert "could not read candidate" in result.errors[0]
    assert "Permission denied" in result.errors[0]


def test_unscoped_discovery_skips_directories_and_missing_tracked_files(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    directory = tmp_path / "nested-repository"
    directory.mkdir()
    missing = tmp_path / "deleted.py"

    with patch("uv_scrollguard.core._git_files", return_value=(directory, missing)):
        result = discover_scripts(cwd=tmp_path)

    assert result.scripts == ()
    assert result.errors == ()


def test_malformed_source_is_not_reported_as_an_io_error(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "broken.py").write_text("value = '''\n", encoding="utf-8")

    result = discover_scripts(cwd=tmp_path)

    assert result.scripts == ()
    assert result.errors == ()


def test_directory_member_symlink_keeps_lexical_identity(tmp_path: Path) -> None:
    _git_init(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()
    target = tmp_path / "target.py"
    target.write_text(SCRIPT, encoding="utf-8")
    link = scope / "linked.py"
    link.symlink_to(target)

    result = discover_scripts([scope], cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == (link,)


def test_explicit_directory_symlink_keeps_lexical_member_paths(tmp_path: Path) -> None:
    _git_init(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "tool.py").write_text(SCRIPT, encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    result = discover_scripts([alias], cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == (alias / "tool.py",)


def test_explicit_file_symlink_keeps_lexical_identity_and_any_extension(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.py"
    target.write_text(SCRIPT, encoding="utf-8")
    link = tmp_path / "script.custom"
    link.symlink_to(target)

    result = discover_scripts(["script.custom"], cwd=tmp_path)

    assert result.errors == ()
    assert result.scripts == (link,)


def test_broken_and_self_referential_symlinks_are_skipped(tmp_path: Path) -> None:
    _git_init(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "broken.py").symlink_to("missing.py")
    (scope / "loop.py").symlink_to("loop.py")

    result = discover_scripts([scope], cwd=tmp_path)

    assert result.scripts == ()
    assert result.errors == ()


def test_missing_path_is_reported_even_with_another_valid_scope(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(SCRIPT, encoding="utf-8")

    result = discover_scripts([script, "missing"], cwd=tmp_path)

    assert result.scripts == (_lexical_absolute(script),)
    assert result.errors == (
        "path does not exist or is not a file or directory: missing",
    )
