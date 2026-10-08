# Testing and distribution verification

[Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) provides the development setup and basic check commands.
Use this guide to select portability, distribution, and coverage checks for the affected contracts.
Tests must use temporary homes, configuration, targets, and local Git remotes rather than real user profiles or credentials.

## Writing for multiple execution environments

Consider supported environments while designing the change, even when only one is available for execution.
For affected behavior, identify relevant differences between native Windows and Linux/WSL, shell invocation, interactive terminals and redirected input, and editable versus installed or copied-worker execution.
Do not require every environment for every change; select the relevant dimensions and checks according to the affected contract.

- Treat filesystem paths and serialized representations as different values.
  Parse JSON before comparing path values, and decode encoded commands before checking their arguments.
  Assert exact bytes or quoting when serialization or byte preservation is the contract, with expectations appropriate to the platform.
- Account for drive and UNC paths, separators, case behavior, symlink/reparse capabilities, permissions, line endings, and non-ASCII or shell-sensitive characters where they affect the change.
  Do not normalize away distinctions that ownership, identity, or preservation checks rely on.
- Make test prerequisites explicit rather than inheriting the developer's machine state.
  Control home/configuration locations, relevant environment variables, executable discovery, working directory, TTY detection, and input responses when they influence the behavior under test.
  An unattended-flow test should fail if input is requested; interactive-flow tests should supply their expected responses.
- Use platform-appropriate fake executables and subprocess invocation.
  A POSIX shebang is not a portable executable fixture, and successful command serialization does not establish execution or exit-code propagation in the target shell.
  Keep portable policy and output checks runnable everywhere; isolate native process, shell, and filesystem checks behind explicit capability requirements.
- Exercise both success and failure behavior, especially preservation of user files, unrelated configuration, and saved ownership when an operation cannot proceed.
  A platform limitation should skip only checks requiring that capability, not portable validation of the corresponding error or refusal path.

When another relevant environment is unavailable, review its code paths and fixture assumptions and run the meaningful checks available locally.
Record the environments actually exercised, skipped capabilities, and remaining uncertainty with the change's validation results.
Mocks and static review support portability reasoning but do not establish native readiness; retain that distinction in compatibility claims.

## Installation and dependency boundaries

Base installation supports ordinary AEM use; the `dev` extra supports contribution work and the full test suite.
Both installations must have identical command behavior, configuration defaults, and automation policy.
Installing either package does not register shell or agent integrations; `aem setup` owns those explicit changes.
The repository installer combines package installation and requested setup as a user-facing workflow.

### Runtime dependency isolation

Runtime commands must not import development or build tools.
Build-system requirements provision isolated package builds independently of the `dev` extra; setuptools in `dev` supports source build-hook tests.
Keep the standalone installer and copied worker standard-library-only, and verify them with Python site packages disabled.

### Installed distribution checks

Source tests in an editable development environment and verification of an installed distribution are separate acceptance checks.
For packaging or dependency changes, also install a built wheel without extras into a fresh environment with neither coverage.py nor setuptools, and run the runtime verifier from the checkout:

```bash
python -m venv --without-pip /path/to/runtime-venv
python -m pip --python /path/to/runtime-venv install /path/to/agent_env_man-VERSION-py3-none-any.whl
python scripts/verify_runtime.py --python /path/to/runtime-venv/bin/python
```

Use a separate temporary environment; on Windows pass its `Scripts/python.exe` to the verifier.
The pip installation command uses the development environment's pip to install only the wheel and its runtime dependencies into the target environment.
Package acquisition may require network access; verification itself uses only temporary local Git repositories and never registers integrations.
The verifier rejects editable installations and environments containing development dependencies, disables Python source-path inheritance, and checks installed CLI help, local documentation, and bootstrap/apply/status/detach behavior.
It also exercises TOML and JSON settings reception, stage editing, application, export, local Git publication, conflict preservation, and detach through the installed CLI.
Verify both a direct wheel and a wheel rebuilt from the sdist as required by the installed-documentation contract in [Documentation authoring](documentation-authoring.md#installed-documentation).

## Coverage measurement

Run coverage separately from ordinary tests, from the repository root in the activated development environment.
The configuration measures statements and branches in `src/` and `scripts/`, including the build hook and standalone installer.
Python subprocesses are also measured; combine their data before generating reports.

```bash
python -m coverage erase
python -m coverage run -m unittest discover -s tests -v
python -m coverage combine
python -m coverage report
python -m coverage html
python -m coverage json
```

Check the test command's exit status before treating a report as a successful baseline.
Reports from a failed run may help diagnosis but do not establish successful validation.
The terminal report shows missing lines and branch destinations; `htmlcov/index.html` provides file-level detail and `coverage.json` contains machine-readable results.
Coverage data and reports are ignored local artifacts.
There is no minimum coverage threshold or automatic CI or hook enforcement.
Keep coverage.py's default exclusions; do not exclude whole files to improve the percentage.

### Interpret coverage results

Review unmeasured failure, recovery, and platform paths for meaningful behavior tests before choosing a minimum threshold.
Record the source revision, environment, test outcomes and skips, statement and branch coverage, and combined percentage with validation results rather than embedding changing baselines in this guidance.
Linux/WSL measurement does not establish coverage of Windows-only behavior.
The same commands work with the native Windows environment's Python, but report its results separately.
Workers copied into temporary request directories are outside the configured source roots; subprocess measurement does not map those copies back to their originals.
Test the original worker's policy, failure, and continuation behavior separately from copied-worker lifetime integration.
Mocked Windows API tests check branching and resource handling; they do not establish native Windows lock or process behavior.

## Validation expectations

Choose checks by the affected contract, using temporary local Git fixtures and fake installers where needed.

| Affected area | Required behavior checks |
| --- | --- |
| Source delivery | Clone, fast-forward, dirty/divergent histories, network/remote failures, and active live-link guards. |
| Catalog declarations and delivery | No source-local `links.conf` prerequisite; root and nested skills; inventory independent of checkouts/targets; registration and saved-binding reuse; invalid incoming catalogs; ownership conflicts; offline maintenance; local edits and remote failures. |
| Installation | Unmanaged targets, local edits, directory contents, unrelated hook preservation, detach, and failure recovery. |
| Automatic policies | Precedence, empty-trigger opt-out, event selection, offline previews and check-only behavior, per-item throttling including failures, independent outcomes, local edits, and detached content. |
| Content publication | Shared skill/instruction consumers, unrelated files, existing commits, offline previews, rejected histories, remote failure, and retry. |
| Full automation | Actual fresh-CLI continuation, stage ordering, new declarations, exclusions, throttling, cancellation, lock handoff, and failure gates. |
| AEM self-update | Release boundaries, annotated tags, metadata mismatches, policy cancellation, contention, failure/retry, and worker lifetime. |

Cross-cutting requirements:

- Verify that missing inventory files still allow status to observe installed contents and detach to preserve them.
- Test meaningful user-visible behavior and preservation boundaries rather than mirroring private implementation functions.
- For workflows spanning commands, verify that outputs and selection scope match the next command's inputs and operation targets, including update/bootstrap/apply and locate/edit/publish.
- Where source and installation can differ, cover link, copy, and detached states and verify which content editing and subsequent commands consume.
- Installation and update paths must reject unknown fields and invalid types rather than accepting misspelled or removed settings.
- Update examples and platform limitations with interface changes.

## Agent integration checks

During development, switch `STARTUP_BRIEFING_OUTPUT` in `src/agent_env_man/agents.py` between `"systemMessage"` (UI warning) and `"additionalContext"` (model context) to try both startup briefing behaviors.
For a regular uv tool installation, reinstall the updated checkout before testing the installed hook.

Test setup with temporary homes and fake installer subprocesses, never actual user profiles or live remote repositories.
Exercise repeat/add/remove, edited blocks, invalid hook files, redirected paths, grouped hook writes, partial failure/retry, offline previews, and fail-open startup.
Shell quoting and PowerShell serialization tests do not establish native shell or Windows readiness.
