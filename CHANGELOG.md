<!-- markdownlint-disable MD024 -->

# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] &mdash; 2026-10-07

Git tag `v1.1.1` corresponds to Python package version `1.1.1`; based on `v1.1.0`.

### Fixed

- Full automation can receive a newly declared skill from an existing stale shared checkout, including when existing consumers are detached or excluded.
Validate all declared skills against incoming revisions before advancing shared checkouts, and report the affected skill with a supported update/bootstrap recovery sequence when standalone bootstrap finds an invalid local skill.

## [1.1.0] &mdash; 2026-10-04

Git tag `v1.1.0` corresponds to Python package version `1.1.0`; based on `v1.0.1`.

### Added

- General directory management from Git or external sources, with explicit target roots, link/copy installation, existing publication and preservation contracts, and skill-style automatic update policies.
- Configure the agent startup callback duration through setup and the standalone installer, retaining the ten-second default and preserving instruction hooks.
Codex rounds fractional seconds up to an unsigned integer while Claude retains precision.
- Introduce explicit Git timeout option names while retaining the previous CLI names as compatible aliases and preserving saved policy keys.
- Explicit personal command hook resources for Codex and Claude, with machine-local runtime bindings that preserve virtualenv interpreters, group ownership and existing transaction/recovery protections.
Saved offline removal uses ownership records without requiring current agent profiles or editable preference stages.
Personal registrations remain excluded from automatic full runs.

### Changed

- Expand preservation and validation tests for personal hooks and external directory retries, and native Windows coverage for timed lock contention, exception cleanup, and already-exited processes.

### Fixed

- Reuse shared-checkout fetch results within automatic skill-policy runs while preserving independent policies, attempts, and installation guards, and compare Git history against each reused commit.
- Wait for short startup contention and allow validated read-only instruction location snapshots during long configuration-lock holds; POSIX CLI readers share the installation lock while update workers remain exclusive.

- Preserve numeric precision in unrelated hook groups when registering or removing AEM hooks, fixing JSON reserialization loss.

## [1.0.1] &mdash; 2026-10-04

Git tag `v1.0.1` corresponds to Python package version `1.0.1`; based on `v1.0.0`.

### Fixed

- Compare physical CRLF and LF newlines consistently in TOML settings without discarding explicit carriage-return escapes, preventing false apply, collection, status, and shared merge differences after target serialization or Git checkout conversion.

## [1.0.0] &mdash; 2026-10-03

First stable major release; Git tag `v1.0.0` corresponds to Python package version `1.0.0`.

- Allow non-hook JSON preferences to share Claude's settings file with AEM setup and instruction hook groups. Reserve the entire hooks field for agent integration, including during collection, source reception, and explicit replacement; preserve settings on setup removal.

### Added

- Strict JSON application settings with exact numeric comparison, preserving field edits, and the existing staged merge, publication, automation, and recovery workflows.
- Independent per-setting automatic sync schedules that receive shared settings and apply their stages together, with offline previews, failure throttling, and existing conflict preservation.
- Installed-wheel runtime verification for TOML and JSON settings reception, staged edits, application, export, local Git publication, conflict preservation, and detach without development dependencies.

### Changed

- Reorganize contributor guidance into linked architecture, testing, and documentation-authoring guides while retaining development setup and essential preservation rules in CONTRIBUTING.
- Restore basic usage in the bundled AEM skill, organized by task workflows, with command help and local documentation consulted in sequence only when needed.
- **Breaking relative to `1.0.0-rc`:** Full device automation now prepares, receives, and applies settings by default, retaining explicit empty-trigger exclusions and detached items.
To retain manual-only settings in an existing full-mode configuration, disable device automation before upgrading, then set `trigger = []` in each setting's catalog `update` table before restoring full mode; settings remain opt-in in policies mode.
See [upgrade guidance](docs/automation.md#upgrading-from-manual-only-settings).
- Clarify that the first final `1.0.0` establishes the stable public contract, while prerelease self-update series retain their compatibility boundaries and graduation to final requires `breaking` permission.

### Fixed

- Apply shared Claude preferences and instruction hooks in one file transaction, revalidating all hook sources before committing; preserve shared preferences when removing multiple or retired agent integrations.

- Reapplying unchanged TOML or JSON settings preserves mixed line endings byte for byte on Windows.
- Settings publication comparisons use each item's saved format, including unselected stages in shared checkouts.
- Disabled agent startup callbacks remain independent of missing or invalid content catalogs.
- Suppress transient Windows console windows for captured Git, self-update worker children, and PowerShell profile discovery while preserving output and process exit handling.

## [1.0.0-rc] &mdash; 2026-10-01

First release candidate of 1.0.0; Git tag `v1.0.0-rc` corresponds to Python package version `1.0.0rc0`.

### Added

- Claude Code integration through the existing agent-profile boundary, preserving unrelated settings and Codex callback behavior.
- Native Windows integration tests for encoded PowerShell hooks, literal-path shell navigation, interprocess locking, process-exit waits, and official skill link refresh.

### Changed

- Expand contributor guidance for designing portable implementations and tests, controlling environment-dependent fixtures, and reporting validation limits when a supported environment is unavailable.

### Fixed

- Recognize Windows extended drive and UNC link destination spellings as the recorded source for skills, instruction bundles, and official skill checks, while preserving raw recovery observations and rejecting substituted aliases.
- Make filesystem, hook metadata, rollback, and timeout tests portable across Windows drives, path separators, JSON escaping, and read-only Git objects; execute prerelease worker tests with a Windows-compatible fake installer.

- Clarify instruction hook location metadata to discourage redundant entry reads and resolve references relative to each source document, including nested entries, without changing link installation or metadata fields.

## [1.0.0-beta] &mdash; 2026-10-01

First beta of 1.0.0; Git tag `v1.0.0-beta` corresponds to Python package version `1.0.0b0`.

### Added

- Recognize Python `a`/`b`/`rc` and SemVer-style `-alpha`/`-beta`/`-rc` prerelease tags in AEM self-update and prepared release publication.
Convert tag labels to Python package notation and treat an omitted subversion as zero in version ordering and tag/package comparisons.
Prerelease compatible updates increase only the subversion within the same base version and pre label; breaking updates may cross series or graduate to final, while final compatible updates retain their existing range and exclude prereleases.
- Optional statement and branch coverage measurement for the existing unittest suite, including Python subprocesses, with terminal, HTML, and JSON reports through the development extra.
- Regression coverage for documentation build hooks, original update-worker failure and continuation paths, and mocked Windows locking and process-exit APIs.
- A standalone verifier for installed wheels without development dependencies, plus standard-library-only installer and copied-worker regression checks.
- `aem self publish` publishes a prepared clean AEM checkout's current branch and matching release tag to origin with atomic push, using the recorded local installation source or an explicit `--checkout`.
Local release preparation remains explicit in Git; publication is independent of machine/catalog state and offers an offline preview.

### Changed

- Distinguish base local use, contribution environments, isolated builds, and explicit shell/agent setup in installation and validation guidance.

### Fixed

- Recreate documentation output directories on repeated builds despite setuptools directory caching, and preserve existing documentation during build dry-runs.

### Removed

- Remove pre-1.0 versioning exceptions and update guidance from documentation; retain historical release identifiers.

## [0.5.3] &mdash; 2026-10-01

### Fixed

- Store the shared AEM installation lock beside the uv tools directory so uv does not discover it as an invalid tool environment.

## [0.5.2] &mdash; 2026-10-01

### Added

- Version-matched local README, detailed docs, catalog examples, and license resources, located offline with `aem docs` independently of setup or machine configuration.

### Changed

- Move the authoritative compatibility policy into bundled user documentation; keep contribution and release-history references as optional repository links and document the installed documentation strategy.
- Expand CLI help with selection scope, settings stage locations and field choices, shell navigation requirements, and publication defaults without changing command behavior; define contributor guidance for concise, sufficient installed help.
- Move detailed automation, AEM self-update, and maintenance/recovery guidance into dedicated docs guides; retain core workflows and preservation reminders in the README, and clarify contributor guidance without changing its structure or contracts.
- Official skill contribution guidance prioritizes installed CLI help and authoritative local documentation; streamline `idk-aem` around important operation boundaries, publication scope, and preservation.

## [0.5.1] &mdash; 2026-10-01

### Fixed

- Allow first publication of the registered local branch to a verified empty Git remote, including catalog and settings publication; keep authentication/network failures and missing branches in populated remotes fatal.
- Keep catalog skill replacement and detach backups outside agent discovery roots to prevent duplicate skills, with verified copies and recovery across filesystems while preserving older recovery journals.

## [0.5.0] &mdash; 2026-10-01

### Added

- Staged application TOML settings with Git/external sources, explicit field collection, persistent deletion/release intent, source export, Git publication, conflict resolution, and grouped recovery.
- Settings-aware locate/status and bootstrap `--setting-target` bindings; settings stages and actual files remain outside automatic/full runs.
- `locate --cd` and `catalog locate --cd` enter the selected directory through the Bash, Zsh, or PowerShell setup integration; standalone use prints the directory path.

### Changed

- Contributor guidance requires reviewing and updating affected official skill guidance alongside user-facing changes; the `idk-aem` skill now covers directory navigation with `locate --cd`.

## [0.4.2] &mdash; 2026-10-01

### Fixed

- Instruction callbacks wait for installation-lock contention within the same five-second budget as configuration-lock contention, instead of stopping immediately when another AEM command holds the installation lock.

## [0.4.1] &mdash; 2026-10-01

This release preserves existing setup behavior and adds the official skill as an ancillary integration.

### Added

- Official `idk-aem` skill for AEM user operations, authored at `skills/idk-aem/SKILL.md` and included in wheel and source distributions.
Self-update validates owned skill links and local source edits before package replacement, then verifies or refreshes links through the fresh CLI with separate stage results.

### Changed

- Agent setup attempts the official skill link after completing core integrations and machine selection storage, reporting recoverable skill failures separately without failing setup.
Agent removal also removes unchanged owned official links; changed links, edited sources, and substituted copies are preserved and released from ownership.
User catalog installation and content editing remain independent of the official skill.

## [0.4.0] &mdash; 2026-10-01

This release requires catalog v2 and changes CLI parsing and default report formatting.
Follow the [catalog transition instructions](docs/removed-interfaces.md#catalog-v2-transition) before upgrading existing installations.

### Changed

- **Breaking:** Require catalog `version = 2`, named `sources` with explicit Git/external types, one `source` reference per item, and nested skill/instruction installation tables.
Catalog update triggers accept only event arrays; `[]` disables automatic execution, including inherited exclusions in full mode.
Machine format/policies, state version 2, policy JSON and callbacks retain their contracts; saved-state maintenance remains available with old catalogs.
Named checkout identities are retained; direct-declaration or relocated installations require manual detach and explicit reattachment/replacement, with old contents and backups preserved.
See [transition instructions](docs/removed-interfaces.md#catalog-v2-transition).
- **Breaking:** Ordinary CLI commands now print human-readable fields and indented lists by default, including redirected stdout.
Add the global `--json` option before the command to retain the existing JSON report schema; installed startup and instruction callbacks continue to emit JSON automatically.
- **Breaking:** Replace argparse with Click command groups and consistent option scope.
Place global `--config` and `--json` before the command, for example `aem --json status`.
Abbreviated long options are rejected, and invalid numeric CLI durations now exit `2` as usage errors before configuration reads or filesystem effects.
- Centralize CLI configuration/locking, report output, and operational error handling while keeping command callbacks and reusable core operations separate.
- Allow Git-ignored runtime files in prepared checkouts during bootstrap, apply, and content/catalog updates; ignored files alone no longer mark a content checkout dirty.
Fast-forwards preserve local ignored files by refusing incoming path collisions.
Directory links, copies, and detach retain ignored regular contents; installed-copy local edits and unsupported nested links/special files remain protected.

## [0.3.0] &mdash; 2026-09-30

Existing configurations retain policy-driven automation by default; full automation requires explicit opt-in.

### Added

- Installer/setup-selected device automation modes (`off`, `policies`, `full`), a unified event/preview command, and sequential full runs through tool replacement, fresh-CLI catalog refresh, and eligible content preparation/update/application with shared throttling.
Full runs preserve explicit manual exclusions and detached installations, stop later stages on failure, and retain the existing live-link effects of shared checkouts.
- Opt-in machine-owned catalog automatic triggers configured through bootstrap/setup options, independent attempt throttling, `catalog auto`, and validated catalog refresh before startup skill policies.
- Installer-selected `off`, `compatible`, and `breaking` AEM self-update modes, release-tag updates queued after startup exits, and independent `self status` / `self update` commands.
Updates validate release metadata, use an external worker after the requesting process exits, and serialize replacement across configurations sharing an installation.
- Changelog with release history and contributor guidance for maintaining release notes.
- Git-delivered catalogs registered through bootstrap repository/path arguments, with automatic machine binding and separate checkouts.
- Explicit `catalog status`, `locate`, `update`, and `publish` commands, including validation before catalog updates and offline publication previews.

### Changed

- Automation settings can be changed through configuration-only `setup` calls without registering integrations or rewriting shell profiles.
- Require validation across connected command workflows, including the distinction between installed content and editable source checkouts.

## [0.2.0] &mdash; 2026-09-29

This release includes incompatible installation and CLI changes.
See [Removed interfaces and existing installations](docs/removed-interfaces.md) for replacements and migration precautions.

### Added

- Shared Git checkouts through named catalog repositories, with validation of all declared skills and protection of active links before updates.
- Composable automatic skill update policies, per-skill attempt throttling, and an `auto` command for externally supplied startup or interval events.
- Instruction bundles from Git repositories or external folders, with direct entry-document links and Codex hooks that report saved reading locations.
- Repeatable machine setup and a uv-based installer, with Bash, Zsh, PowerShell, and Codex startup integrations and brief startup update reports.
- `locate` for saved skill/instruction installations and catalog source paths, including explicit source lookup for editing.
- `publish` to commit and push selected catalog sources by shared repository, with offline preview and retryable push failures.
- MIT license and a package-level compatibility policy covering commands, catalogs, generated configuration, and existing integrations.

### Changed

- **Breaking:** Installation requires state version 2, without automatic conversion of version-1 installations.
Maintenance commands can still inspect, detach, recover, and remove saved integrations using known version-1/version-2 ownership records independently of current installation declarations.
- Bootstrap accepts a positional catalog and external-folder bindings; explicit catalog and machine path overrides remain supported.
- Separate the configuration specification and command reference from the README workflows.

### Removed

- **Breaking:** Source-local `links.conf`, machine `[sources]`, legacy source bootstrap options, and partial Codex configuration merging; the catalog is the only content declaration format.
- **Breaking:** The `codex-hook` alias and generated instruction-guide upgrade path; instruction callbacks use `agent-hook NAME --agent codex` and direct entry links.
- **Breaking:** `sync --min-interval` and configuration-wide throttling; explicit sync is unthrottled, while automatic updates use per-skill catalog policies.

## [0.1.0] &mdash; 2026-09-26

### Added

- Initial agent environment manager with a user-owned TOML skill catalog and Git delivery independent of upstream repository manifests.
- Bootstrap, update, apply, sync, status, detach, and recovery commands with JSON output and offline installation from prepared checkouts.
- Direct skill links and explicit copies, ownership tracking, conflict adoption/replacement, retained backups, and journaled per-target recovery.
- Conservative Git updates that reject local changes and divergent histories and protect active skill link sources.
- Linux/WSL and native Windows path handling, with Python 3.11 or later and Git required.
- Legacy source-local `links.conf` delivery and partial Codex configuration merging, retained alongside the initial catalog workflow.

[Unreleased]: https://github.com/mirinae3145/agent-env-man/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mirinae3145/agent-env-man/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/mirinae3145/agent-env-man/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mirinae3145/agent-env-man/compare/v1.0.0-rc...v1.0.0
[1.0.0-rc]: https://github.com/mirinae3145/agent-env-man/compare/v1.0.0-beta...v1.0.0-rc
[1.0.0-beta]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.3...v1.0.0-beta
[0.5.3]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mirinae3145/agent-env-man/tree/v0.1.0
