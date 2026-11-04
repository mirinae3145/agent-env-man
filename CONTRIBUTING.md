# Contributing

## Development setup

Use Python 3.11 or later and Git.
Create and activate a virtual environment, then install the project with its development extra:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On native Windows, activate with `.\.venv\Scripts\Activate.ps1` in PowerShell, or invoke `.\.venv\Scripts\python.exe` directly.
Runtime dependencies are Click and TOML Kit.
The development extra adds coverage.py for optional coverage measurement and setuptools for build-hook regression tests.
Installing the package does not register integrations; use `aem setup` explicitly, with temporary profiles for development checks.

## Verification

Tests use standard-library `unittest` and Click's `CliRunner`.
Run from the repository root in the development environment:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

Select checks according to the affected behavior and remaining uncertainty; a complete suite run is not required for every change.
Reuse passing results when subsequent changes cannot affect them.
Tests must use temporary sources, targets, configuration, state, and local Git remotes, never actual user homes, credentials, or network remotes.

On Windows, noninteractive development and test runs must not open visible terminal windows, including fixture, helper, and descendant processes.
Apply hiding controls at process creation and verify representative descendant launches before long or parallel runs; redirected output or a hidden parent alone is insufficient.
Preserve the semantics of native console and process-lifetime tests when adding these controls.
If unexpected windows appear, stop the responsible process tree and correct its launch behavior before resuming.

Tests requiring successful symlink creation may skip when the host lacks that capability; tests of the unavailable-symlink refusal path must still run.
Verify user-visible behavior and preservation boundaries, including failure and recovery, rather than mirroring private implementation functions.
For workflows spanning commands, check that each command's output and selection scope match the next command's inputs and operation targets.

GitHub Actions runs the full source suite with coverage and installed-distribution checks on Linux and native Windows.
A Linux job also checks self-updates from previous releases, and a separate workflow checks the latest agent CLIs on pull requests, daily, and on manual dispatch.
See [CI coverage and local reproduction](docs/testing.md#continuous-integration) for the matrix, logs, and capability boundaries.

See [Testing and distribution verification](docs/testing.md) for environment-specific fixtures, installed-wheel checks, coverage measurement, and validation expectations.
Record the environments exercised, skipped capabilities, and remaining uncertainty with the change's validation results rather than in durable project guidance.
Static review and mocks do not establish native Windows readiness.

## Design and preservation boundaries

AEM manages delivery and installation; user-authored instructions, skills, and settings remain outside the package.
The bundled `idk-aem` skill documents AEM operations and must not impose content-authoring policies.
Delivery prepares local sources, and installation consumes them without fetching.
Links expose source updates immediately; copies change on apply and must preserve local edits.
Keep ownership, conflict checks, per-target transactions, and recovery intact, and never silently fall back from links to copies.

Preserve Linux/WSL and native Windows path handling.
Use Python filesystem and subprocess APIs, explicit UTF-8 encoding, argument lists, and `/` in shared relative paths.
Core operations must not depend on a POSIX shell; Windows-only code must not import POSIX locking or signal primitives at runtime.
Runtime commands must not import development or build tools, and the standalone installer and copied update worker remain standard-library-only.

Read the affected sections of [Architecture and preservation contracts](docs/architecture.md) before changing delivery, installation, automation, settings, or agent integration.
The [agent profile contracts](docs/agent-profiles.md) define the internal extension boundary for product paths, hooks, and callback output.

## Documentation and releases

Keep [Configuration](docs/configuration.md) and [Commands](docs/commands.md) authoritative for TOML fields and CLI contracts.
Update relevant documentation, examples, and platform limitations when interfaces or workflows change.
Follow [Documentation authoring](docs/documentation-authoring.md) for CLI help, installed resources, and official skill guidance.
The README retains essential user setup and workflows; detailed references and contributor contracts belong in the linked guides.

Follow the authoritative [compatibility policy](docs/compatibility.md) when changing public contracts or classifying releases.
It covers package versioning, supported interfaces, and machine/state format compatibility.
Maintain [CHANGELOG.md](CHANGELOG.md) alongside notable user-visible changes and contributor workflow changes.
Release entries identify their `vVERSION` Git tag and the corresponding Python package version in `pyproject.toml`, using the supported tag conversion and compatibility policy.
