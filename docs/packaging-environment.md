# Packaging environment boundary

`simplicio-loop` is installed as an independent Python distribution. Its supported
closure is that one wheel (Loop plus the Mapper and Dev CLI packages built into it)
and the declared optional extras in `pyproject.toml`. It does **not** install
`hermes-agent` or `simplicio-sprint` and does not declare `rich` directly.

## Supported installation

Use one virtual environment per product boundary:

```bash
python3.11 -m venv .venv-loop
. .venv-loop/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python -m pip check
python -m pytest -q
```

Loop is the single distribution for its two mandatory operators. A normal
`pip install simplicio-loop` ships Mapper and Dev CLI inside the wheel and provides the
`simplicio-mapper` and `simplicio-dev-cli` entrypoints itself; it does not depend on the
separate `simplicio-mapper` / `simplicio-cli` PyPI distributions. Verify the
installed bundle, including entrypoint ownership and PATH entrypoints, with:

```bash
simplicio-loop-stack --check
simplicio-loop preflight --repo . --strict --json
```

### Single source of the Mapper

The Mapper the loop uses is **only** `packages/mapper` in this monorepo, built into the
single wheel. The standalone `simplicio-mapper` repository is not a source for the loop:
its builds use the same version number (`0.26.35`) and write to `.simplicio/`, while this
monorepo writes to `.simplicio-loop/`. Installing that build next to the loop breaks it (#1475).

Every wheel build stamps its origin and source commit into `simplicio_mapper/_build_stamp.json`
(`packages/mapper/hatch_build.py` for the Mapper wheel, `setup.py` for the Loop wheel). The
identity is readable at runtime with `simplicio_mapper.build_identity.build_identity()`.
Check it with:

```bash
simplicio-loop doctor mapper --json
```

It reports `status` and a `reason_code`: `verified`, `mapper_identity_missing` (a build that
predates the identity), `origin_mismatch`, `state_dir_mismatch` (not `.simplicio-loop`),
`build_unstamped`, `commit_mismatch` (inside a checkout, the installed commit differs from
`HEAD`), or `mapper_not_importable`. Every blocker carries a `fix` command. Exit `0` when verified,
`2` otherwise.

To replace a foreign build on a host (for example, a VPS that installed the standalone one):

```bash
python3 -m pip uninstall -y simplicio-mapper
python3 -m pip install --force-reinstall simplicio-loop
simplicio-loop doctor mapper
```

The check is expected to fail for `pip install --no-deps`, a manually removed
operator, an install whose operator entrypoints belong to the retired standalone
`simplicio-cli` / `simplicio-mapper` distributions (`simplicio-loop update` replaces
it), or an environment where the console scripts are not on `PATH`.
Runtime and other accelerators remain separate optional components.

Hermes Agent and Simplicio Sprint are separate consumers. Do not install both
into the Loop environment. Their currently published requirements are
incompatible (`hermes-agent` requires `rich==14.3.3`, while `simplicio-sprint`
requires `rich>=15.0.0`), so a combined environment is intentionally outside
the supported boundary and must fail the packaging gate rather than silently
select a pin.

The boundary is deterministic: dependency ownership is declared by each
project's own manifest, and Loop must not add a compatibility pin for a package
it does not import. The executable verification in
`tests/test_packaging_environment.py` prevents an accidental direct dependency
on Hermes, Sprint, or `rich` from entering the Loop distribution.
