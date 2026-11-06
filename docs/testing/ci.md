# CI and agent integration checks

Use this guide to understand CI coverage, reproduce its jobs, and check agent integration boundaries.

## Continuous integration

The [CI workflow](https://github.com/mirinae3145/agent-env-man/blob/master/.github/workflows/ci.yml) checks pull requests targeting master and manual dispatches.
Pull requests test GitHub's merge revision.
A separate [agent integration workflow](https://github.com/mirinae3145/agent-env-man/blob/master/.github/workflows/agents.yml) runs on pull requests targeting master (including drafts), daily, and on manual dispatch.
Both workflows use read-only repository permissions and do not publish packages or configure required checks.

### Jobs and prerequisites

The CI workflow runs these independent checks:

| Check | Runners | Python | Commands |
| --- | --- | --- | --- |
| Source | Ubuntu 24.04, Windows Server 2025 | 3.11, 3.15 | Full unittest discovery under coverage, and compileall |
| Distribution | Ubuntu 24.04, Windows Server 2025 | 3.11 | Direct wheel and sdist-rebuilt wheel runtime verification |
| Upgrade | Ubuntu 24.04 | 3.11 | Self-update from previous releases to the tested revision |
| Documents | Ubuntu 24.04 | 3.11 | Markdown structure check with mddt's current default branch |

Every matrix job requires working file and directory symlinks; Windows also requires Windows PowerShell.
A missing capability fails preparation instead of silently skipping its success paths.
Verbose unittest logs retain individual skips, including tests for the other operating system.
Source jobs install the development extra and uv to exercise tool-discovery tests.
They report coverage totals in the job summary and logs without a minimum threshold.

One Ubuntu source job checks whitespace against the PR base or the push's previous revision.
Manual dispatch checks the last commit; an initial push or root commit is compared with an empty tree.
Matrix jobs have a 45-minute timeout and do not cancel other matrix jobs on failure.
A newer PR revision cancels the previous run for that PR.

### Logs and limits

Each job uploads command logs for 14 days, including on failure when logs are available.
Inspect the failed step and skip reasons before interpreting a run as platform coverage.
Hosted Linux and Windows checks do not cover WSL interoperability, real mounted filesystems, or authenticated agent sessions.

### Document structure

The documents job runs the [mddt](https://github.com/mirinae3145/mddt) checker from mddt's current default branch on tracked Markdown files.
It prints the mddt commit in its log and job summary, and supplies the automated minimum check within the [writing procedure](../documentation-authoring.md#guide-structure).
Following the current branch instead of a pinned revision is one of the two approaches in mddt's [adoption guide](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/adopting.md#continuous-integration).
A pass does not establish that document meaning, placement, or organization meets the model; authors and reviewers make those judgments locally.

Errors fail the job across all files, since a change can break links in documents it did not edit.
Warnings mark places that need a writer's judgment, so the job annotates only those in files the pull request changed and never fails on them.
Because the branch is not pinned, findings can change without a change to this repository.
A new checker rule can therefore fail the job on unchanged documents.
The printed commit identifies the rules a run applied.

### Upgrade verification

The upgrade job installs the first and latest final releases of each minor series from 1.0 onward.
It also installs the first and latest releases in the candidate's prerelease series.
It uses tags merged into the tested revision and no newer than its package version.
Each installation uses its own repository installer in a disposable profile with copied, linked, and settings content.

The tested revision is published to a local release repository under the next version, then installed by `aem self update`.
Permitted transitions must succeed in `compatible` mode.
Other transitions must leave the installation unchanged before succeeding in `breaking` mode.
The job checks that installed contents, local edits, and existing status fields survive, allowing additive JSON output fields, and that ordinary updates continue afterwards.

Rerunning setup afterwards must leave the agent profile files unchanged.
Native Windows self-update remains outside this job.

### Agent integration workflow

The agent integration workflow installs the latest Codex and Claude Code CLIs.
It checks that they read a fresh AEM setup without account credentials, as described in [agent integration checks](#agent-integration-checks).
A failure can come from a CLI release rather than an AEM change.
Inspect the installed CLI versions and logs when diagnosing a failed PR check.

### Local reproduction

To reproduce both distribution paths, install build and run the helper from a development environment:

```bash
python -m pip install build
python scripts/verify_distribution.py
```

The helper builds in isolation and creates separate runtime environments without pip, setuptools, coverage, or build.
It invokes the existing runtime verifier for each wheel and exits unsuccessfully if any build, installation, or verification fails.
Temporary build and runtime directories are removed when the helper exits.

The upgrade and agent checks run from a checkout with full tags, using Python, Git, and uv on PATH:

```bash
python scripts/verify_upgrade.py                       # Default baselines.
python scripts/verify_upgrade.py --baseline v1.2.1     # A selected release.
python scripts/verify_agents.py                        # Requires codex and claude on PATH.
```

Both helpers install AEM into temporary homes and uv tool directories and remove them when they exit.

The document check needs uv and an mddt checkout; check out the commit a CI run printed to reproduce its findings:

```bash
python scripts/verify_documents.py --mddt ../mddt/skills/mddt/scripts/mddt.py --base master
```

Without `--base`, it reports warnings for every file.

## Agent integration checks

Use temporary profiles to check startup integration and distinguish unauthenticated CLI acceptance from actual hook execution.

### Development fixtures

During development, switch `STARTUP_BRIEFING_OUTPUT` in `src/agent_env_man/agents.py` between `"systemMessage"` (UI warning) and `"additionalContext"` (model context) to try both startup briefing behaviors.
For a regular uv tool installation, reinstall the updated checkout before testing the installed hook.

Test setup with temporary homes and fake installer subprocesses, never actual user profiles or live remote repositories.
Exercise repeat/add/remove, edited blocks, invalid hook files, redirected paths, grouped hook writes, partial failure/retry, offline previews, and fail-open startup.
Shell quoting and PowerShell serialization tests do not establish native shell or Windows readiness.

### Installed CLI verification

`scripts/verify_agents.py` checks a fresh setup against the installed agent CLIs without account credentials.
Codex must load its configuration and list the official skill in `codex debug prompt-input`.
Claude Code must report no invalid settings in `claude doctor` and run AEM's session-start hook before its login failure.
Model requests, authenticated features, and Codex hook execution remain outside this check.
