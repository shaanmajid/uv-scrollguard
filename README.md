# uv-scrollguard

`uv-scrollguard` finds Python scripts with
[PEP 723 inline metadata](https://packaging.python.org/en/latest/specifications/inline-script-metadata/),
requires an adjacent uv lockfile for each one, and verifies that every lockfile
is current.

[uv](https://docs.astral.sh/uv/) 0.5.17 or newer must be installed and available
on `PATH`. Use `uv-scrollguard` as a GitHub Action or prek/pre-commit hook to
catch missing, stale, and invalid script locks in CI. CI is pinned to uv 0.11.28.

The project delegates lock validation to `uv lock --script ... --check` and may
be archived if uv provides an equivalent repository-wide check natively.

> **Disclaimer:** This project was built by AI coding agents under human
> supervision, for personal use. Use your own judgment before relying on it.

## Policy

The default policy is strict: every discovered PEP 723 script must have a
current adjacent lockfile, including scripts with `dependencies = []`. Missing,
stale, and invalid locks fail without modifying the repository.

An opt-in existing-only policy validates sidecars that already exist without
requiring new ones:

| Policy | CLI and hook | GitHub Action | Behavior |
| --- | --- | --- | --- |
| Strict (default) | No option | `existing-only: "false"` | Require and validate every discovered script lock |
| Existing only | `--existing-only` | `existing-only: "true"` | Validate existing script locks and ignore missing ones |

## GitHub Action

Install uv before running the Action. The Action may be referenced by a release
tag or a commit SHA. The examples use full-length commit SHAs because
[GitHub recommends them when an immutable reference is desired](https://docs.github.com/en/actions/reference/security/secure-use#pin-actions-to-a-full-length-commit-sha).
After release, replace `<commit-sha>` with the SHA tagged `v0.1.0`.

```yaml
- uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
- uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
- uses: shaanmajid/uv-scrollguard@<commit-sha> # v0.1.0
```

Use existing-only mode when a repository wants to validate committed locks
without requiring every PEP 723 script to adopt one:

```yaml
- uses: shaanmajid/uv-scrollguard@<commit-sha> # v0.1.0
  with:
    existing-only: "true"
```

The optional `paths` input accepts newline-delimited files and directories:

```yaml
- uses: shaanmajid/uv-scrollguard@<commit-sha> # v0.1.0
  with:
    paths: |
      scripts
      tools/release.py
```

## prek and pre-commit

Set the hook revision to the release tag or its commit SHA. The example uses the
SHA for reproducibility:

```yaml
repos:
  - repo: https://github.com/shaanmajid/uv-scrollguard
    rev: <commit-sha> # v0.1.0
    hooks:
      - id: uv-scrollguard
```

For existing-only mode:

```yaml
      - id: uv-scrollguard
        args: [--existing-only]
```

The hook performs a repository-wide check rather than receiving staged
filenames.

## CLI

The CLI is useful for local audits and CI systems that do not use the packaged
integrations. Run it from PyPI with `uvx`:

```console
uvx uv-scrollguard
```

With no paths, the command scans downward from the current directory and
respects Git ignore rules. Explicit paths replace default discovery and are
combined and deduplicated:

```console
uv-scrollguard scripts/ tools/release.py
uv-scrollguard --existing-only scripts/
```

Explicit directories include ignored contents because they were requested
directly. Explicit files may use any extension. `--paths-from-env NAME` adds
newline-delimited scopes from an environment variable and is primarily used by
the GitHub Action.

Ordinary discovery considers `.py`, `.pyw`, and extensionless shebang files.
Files without PEP 723 metadata are ignored. The checker deliberately does not
guess whether an ordinary Python module, test, or utility was intended to be a
standalone script.

To repair a reported script, run:

```console
uv lock --script path/to/script.py
```

Exit statuses are `0` for success, `1` for failed lock checks, `2` for invalid
usage or paths, and `3` when uv cannot be executed.

## License

MIT
