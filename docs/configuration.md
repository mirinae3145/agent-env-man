# TOML configuration reference

AEM reads two independent UTF-8 TOML documents, with integer `version = 2` for the catalog and `version = 1` for the machine file.
Filenames are arbitrary: the CLI selects a machine file, and its `catalog` field selects a local catalog or a Git repository and catalog entry.
The catalog declares reusable content and update policies; the machine file binds them to this device.
Installation and update commands reject unknown fields in the catalog and machine configuration.
Maintenance commands can ignore unrelated fields; see [validation boundaries](#storage-and-validation-boundaries).
For the command interface, see [Commands](commands.md).

The package version communicates compatibility for catalog syntax and documented machine settings; neither document has an independent SemVer release cycle.
Their integer `version` fields identify format generations and need not change for compatible additions.
Default workflows let setup/bootstrap write machine settings; direct edits to documented settings remain supported.
AEM is responsible for compatibility handling of generated machine configuration and state, within the supported versions described below.
Do not manually change version markers to bypass validation.
See the [versioning policy](compatibility.md).

## Paths and identifiers

Names use ASCII letters, digits, `_`, `-`, and `.`, starting with a letter or digit.
Relative content paths use `/`, with no empty, `.` or `..` components, backslashes, drive prefixes, or leading slash.
Only `subdir` accepts `.` to select the source root.
Paths are literal: AEM does not expand environment variables, interpolate other fields, or evaluate shell expressions.
Machine paths must be absolute or begin with `~/`, except a local `catalog` string, which may be relative to the machine file's directory.
Git `catalog.path` is a literal relative file path within that repository, using the relative content path rules above.
On Windows, use forward slashes such as `C:/Users/me/.codex` in TOML strings.
CLI path arguments have their own resolution rules described in [Commands](commands.md#bootstrap).

## Catalog

The only top-level fields are `version`, `sources`, `skills`, `directories`, `instructions`, `settings`, `hooks`, and `updates`.
All tables are optional; an instruction-only catalog needs no skills table.
Skill, directory, instruction, setting and personal hook names share a namespace; source names have a separate namespace.
A source declaration is not an installable item by itself.

```toml
version = 2

[sources.tools]
type = "git"
repository = "https://github.com/OWNER/TOOLS.git"

[sources.documents]
type = "external"

[skills.report]
source = "tools"
subdir = "skills/report"

[skills.report.install]
mode = "link"

[instructions.personal]
source = "documents"
entry = "AGENTS.md"

[instructions.personal.install.entry]
root = "agent"

[updates.defaults]
trigger = []
```

### `sources.NAME`

Every source requires an explicit `type`, either `"git"` or `"external"`.
Git sources accept only `type`, required `repository`, and optional `branch`.
`repository` is a Git URL, SSH repository location, or absolute local repository path.
When `branch` is absent, bootstrap discovers and records the remote default branch.
External sources accept only `type`; their device-local paths belong in machine `external_paths.NAME`.
External sources support directories, instruction bundles, staged settings and personal hooks; skills still require Git sources.
AEM neither fetches external folders nor administers the service that synchronizes them.

Items referencing the same source name share its checkout; different names have independent checkouts even with equal URLs.
Git storage is `CHECKOUT_ROOT/.aem-repositories/NAME`, preserving the former named-repository path.
All consumers are validated before bootstrap publishes a shared checkout.
Unknown source names and unknown fields are rejected.
TOML duplicate source names are invalid, including Git/external name collisions.

### `skills.NAME`

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name of a Git source in `sources`. |
| `subdir` | String | Directory containing the fixed entry file `SKILL.md`; defaults to `"."`. |
| `install` | Table | Optional installation settings below. |
| `update` | Table | Optional policy selection and overrides; see below. |

`skills.NAME.install` accepts only `root` and `mode`.
`root` is an optional name in machine `roots`; the target directory is `ROOT/NAME`.
`mode` is `"link"` (default) or `"copy"`; machine `modes.NAME` overrides it.
With `install.root` omitted, selected agents supply their skill destinations.
Without selected agents, machine `roots.skills` is required; bootstrap supplies its default.
An explicit root overrides agent destinations; agents sharing a target share one ownership record.
Skill names identify installation ownership and directory names, independently of the name inside `SKILL.md`.
Root skills link directly to the repository root; copy and detach exclude only its top-level `.git` entry.
Git-ignored regular files, including runtime caches, may coexist with prepared sources and are part of the directory payload.
Directory links expose them, and copy/detach preserve them; AEM does not guess which ignored files are disposable or delete them.
Tracked changes and nonignored untracked files still block bootstrap, apply, and update.
Fast-forwards refuse incoming paths that would overwrite ignored local files, including file/directory collisions; relocate or reconcile the conflicting files explicitly before retrying.
Installed copies retain full-tree ownership checks, so a cache created or changed in the installed copy counts as a local edit and blocks automatic replacement.

### `directories.NAME`

General directories use Git or external sources and require no entry document, skill metadata, or agent binding.

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name in `sources`; Git or external. |
| `subdir` | String | Source directory; defaults to `"."`. |
| `install` | Table | Required installation settings below. |
| `update` | Table | Optional policy selection and overrides, using the same rules as skills. |

`directories.NAME.install` accepts `root`, `destination`, and `mode`.
`root` is a required machine root name; bootstrap binds it with `--root NAME=PATH`.
`destination` is a literal relative directory path below that root, defaulting to the item name.
`mode` is `"link"` by default or explicit `"copy"`; machine `modes.NAME` overrides it.
Each declaration creates one agent-independent target and ownership ID `NAME:directory`; commands also accept the catalog name.
The target cannot own an entire configured root or overlap sources, other targets, catalog, stages, or manager storage.
Path and mode changes require detach before reconfiguration.

The selected source must be a directory of regular files and directories.
Nested symlinks/junctions, special files, and Git submodules are unsupported.
Git subdirectories must exist as tracked trees; an empty directory requires a tracked placeholder file because Git does not track empty directories.
An external directory may be empty.
Source-root copy and detach omit only the top-level `.git` entry; ignored regular files remain part of the payload.
Existing link/copy conflict, transaction, backup, detach, and recovery contracts apply.
Copy edits are never collected into the source or published; edit the prepared source and apply after committing for Git sources.
Links expose writes and source updates immediately.
External delivery and publication remain outside AEM.

### `instructions.NAME`

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name of a Git or external source in `sources`; a used external source requires a machine path binding. |
| `subdir` | String | Bundle directory under the source; defaults to `"."`. |
| `entry` | String | Required relative path to a regular entry document inside the selected bundle directory. |
| `install` | Table | Optional `bundle` and `entry` tables below. |

`install.bundle` accepts only optional `root` and `destination`.
`root` names a machine root for bundle installation; omission uses `<machine-file>.bundles`.
`destination` is a relative bundle destination and defaults to the instruction name.
`install.entry` accepts only optional `root` and `destination`.
`root` names a machine root for the global entry and hook file; omission uses selected agent roots.
`destination` is a relative global entry destination and defaults to the agent's entry filename (`AGENTS.md` for Codex).

An explicit `install.entry.root` selects one destination; without it at least one machine agent must be selected.
Bootstrap supplies `roots.agent`, but an instruction declaration must either refer to it or use an agent binding.
Codex is the only shipped agent profile.
An instruction creates `NAME:bundle`, `NAME:entry`, and `NAME:hook` ownership IDs.
The bundle and entry are links; the hook owns one group in `hooks.json` under the entry root.
Instruction copy modes and per-bundle automatic policies are not supported.
Explicitly selected full device automation may prepare, update, and apply instruction bundles, while preserving detached groups.
Changing a managed source path, target path, or mode requires detach before reconfiguration.
AEM does not interpret document contents, reading order, or applicability.
See the [instruction walkthrough](instruction-bundles.md) and [catalog v2 transition](removed-interfaces.md#catalog-v2-transition).

### Update policies

Policy tables are `updates.defaults`, `updates.policies.NAME`, and `skills.NAME.update`, and `directories.NAME.update`.
No other fields belong directly under `updates`.

| Field | Type | Built-in default and constraints |
| --- | --- | --- |
| `trigger` | String array | `[]` disables automatic execution; otherwise unique events: `"shell-start"`, `"agent-start"`, `"interval"`. Strings and `"manual"` are invalid. |
| `action` | String | `"sync"` or `"check"`; default `"sync"`. |
| `min_interval` | Integer or float | `600` seconds; finite and nonnegative. Boolean values are invalid. |
| `timeout` | Integer or float | `30` seconds per Git phase; finite and positive. Boolean values are invalid. |
| `policy` | String | Optional name in `updates.policies`; allowed only in `skills.NAME.update` or `directories.NAME.update`. |

Resolution order is built-ins, catalog defaults, selected named policy, then item-local fields.
Only supplied fields override earlier values; trigger arrays replace earlier arrays.
In full mode, omitted policies participate by default, but an explicit or inherited `[]` excludes the skill or directory.
Effective policy JSON retains the existing `["manual"]` representation for disabled automatic execution; machine policy syntax is unchanged.
Named policies cannot inherit another policy.
All declarations, including unused named policies, are validated before network access.

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
min_interval = 600

[updates.policies.observe]
action = "check"

[skills.report.update]
policy = "observe"
timeout = 5
```

`check` fetches references without moving the checkout or installing targets.
`sync` fast-forwards and applies each successful skill or directory independently.
For an external directory, `check` validates local source availability without Git transport and reports `external-no-fetch`; `sync` validates and applies the local source.
Each skill or directory records attempts before network access; failures and successes share its throttle across events.
A shared checkout update changes all live links immediately, including linked instructions; copy installation still follows selected items.
Policies do not register hooks or launch a scheduler; use `setup` or arrange external `auto` calls.
Explicit commands ignore these policies and clocks.

## Machine configuration

| Field/table | Type | Meaning/default |
| --- | --- | --- |
| `version` | Integer | Required, exactly `1`. |
| `catalog` | String or table | Optional local catalog path or Git binding described below; required for bootstrap/content preparation. One binding per machine file. |
| `checkout_root` | String | Managed Git storage; defaults to sibling `<machine-file>.checkouts`. |
| `roots` | Table of paths | User-named installation roots; bootstrap defaults missing `skills` and `agent`. |
| `agents` | Table | Agent selections and path bindings, normally written by setup. |
| `runtimes` | Table of paths | Personal hook interpreter bindings; bootstrap never installs executables. |
| `external_paths` | Table of paths | Logical external source bindings; every used external must be bound. |
| `modes` | Table of strings | Catalog skill or directory names mapped to `"link"` or `"copy"`. Unknown names fail catalog validation. |
| `setup` | Table | Saved startup selections; normally written by setup. |
| `automation` | Table | Device orchestration mode and full-run schedule; omission preserves individual policy behavior. |
| `catalog_update` | Table | Device-local automatic policy for a Git catalog; defaults to manual. |
| `self_update` | Table | Device-local AEM release policy and installer runtime; omission disables automatic self-updates. |

```toml
version = 1
catalog = "catalog.toml"

[roots]
skills = "/home/me/.agents/skills"
agent = "/home/me/.codex"

[agents.codex]
root = "/home/me/.codex"
skills = "/home/me/.agents/skills"

[external_paths]
documents = "/home/me/Synced/documents"

[modes]
report = "copy"
```

Machine selection defaults to `$XDG_CONFIG_HOME/agent-env-man/machine.toml` or `~/.config/agent-env-man/machine.toml` on Linux/WSL.
On Windows it uses `%LOCALAPPDATA%/agent-env-man/machine.toml`, falling back to `~/AppData/Local/agent-env-man/machine.toml`.
Pass `--config PATH` before the command to select another file.

### Git catalog binding

Bootstrap writes this table when given `--catalog-repository URL --catalog-path PATH`; no manual machine-file setup is required.
The local string form remains supported with its existing behavior.

```toml
[catalog]
type = "git"
repository = "git@github.com:OWNER/environment.git"
branch = "main"
path = "catalogs/personal.toml"
```

| Field | Type | Requirement/default |
| --- | --- | --- |
| `type` | String | `"git"` only; defaults to `"git"`. |
| `repository` | String | Required Git URL, SSH location, or absolute local repository path. |
| `branch` | String | Optional nonempty branch name; bootstrap discovers and persists the remote default when absent. |
| `path` | String | Required repository-relative path to a tracked, regular UTF-8 TOML file. |

Unknown fields are rejected.
The catalog's own format is unchanged; its repository binding belongs only in the machine file.
The checkout is sibling `<machine-file>.catalog`, independent of `checkout_root` and of all content checkouts, including those using the same remote URL.
It cannot overlap external sources, content checkout storage, machine/state files, or installation targets.
The entry and checkout must not redirect through symlinks or junctions.
Reading a Git catalog validates its checkout origin, recorded branch, and tracked entry without fetching; local edits remain readable.
Run bootstrap after manually specifying a Git binding without a branch.

Only `catalog update` advances an existing catalog checkout.
Bootstrap reuses it without pulling, and content update/sync/skill automatic policies do not refresh it.
Catalog updates can run automatically only through the independent device policy below.
Catalog status and locate also support local bindings; update and publish require Git.
Switching to a local binding preserves the old Git checkout.
Reusing the same Git checkout requires a matching origin and branch; a new binding never resets or replaces a mismatching repository.
To switch repositories, preserve or move the old `<machine-file>.catalog` checkout explicitly before bootstrapping the new binding.
See [catalog commands](commands.md#catalog) for validation, publication, and failure behavior.

### Roots and agents

`agents.codex` accepts only `root` and `skills` path strings.
Omitted fields default to `CODEX_HOME` (or `~/.codex`) and `~/.agents/skills`, respectively.
Setup persists resolved defaults; saved values take precedence over later environment changes.
Setup initially respects existing `roots.agent` and `roots.skills` when adding Codex.
Bootstrap root overrides for `agent` and `skills` also update an existing Codex binding.
Custom roots must be declared explicitly.
AEM derives `aem-agent-codex` and `aem-skills-codex` roots from the agent binding; conflicting manual definitions are rejected.

### Saved setup

`setup` accepts only `executable`, `shells`, and `startup_hook_timeout`.
See [Agent startup hook duration](#agent-startup-hook-duration) for the independent callback limit.
`executable` is an absolute path to the installed `aem` executable.
`setup.shells` maps `bash`, `zsh`, or `powershell` to absolute profile paths.
Manage these selections with `aem setup`; editing TOML does not itself install or remove profile blocks, hook groups, or official skill links.
Setup rejects an invalid executable path before writing profiles and requires an existing executable except during dry run.
General setup also attempts to install an owned `idk-aem` link for each connected agent under its configured `skills` directory, pointing to the official skill shipped in the installed AEM package.
This ancillary link is attempted after core setup is saved; a recoverable link failure is reported separately without preventing the agent selection from being connected or removed.
The root-level source `skills/idk-aem/SKILL.md` is included through setuptools package-resource mapping; a development checkout is not required for installed use.
Ownership uses `setup:skill-AGENT-idk-aem`, with the existing `setup` kind and `link` mode, plus official source signature and package version fields.
No catalog declaration, machine option, or format-version migration is required.
Official link removal retains its backup in `<machine-file>.state/setup-backups`, outside the agent's skill discovery root.
Skill roots must not overlap machine state storage, so retained backups cannot become discoverable skills.
Catalog skill replacement and detach backups are retained in `<machine-file>.state/skill-backups`; regular contents are copied and verified before the original is removed, and symbolic links retain their recorded link identity.
Recovery continues to accept older sibling-backup journals.
Existing agent integrations acquire the link on general setup; policy-only setup does not add it.
Self-update refreshes successfully owned links and does not turn an uninstalled, failed, or detached ancillary skill into a new update prerequisite.

### Storage and validation boundaries

Named Git sources use `CHECKOUT_ROOT/.aem-repositories/NAME`; former direct-skill checkouts are preserved during manual transition.
Ownership, attempt records, and recovery journals live in sibling `<machine-file>.state`; default bundle links live in `<machine-file>.bundles`.
Do not synchronize machine files, checkouts, or state between devices.
Share a Git catalog through its repository, letting each device prepare its own checkout and machine binding.
External roots must be disjoint from each other, managed checkout storage, the catalog, machine file, and state.
Targets may not overlap sources, manager storage, or another owned target tree.

The catalog is loaded lazily so status, detach, locate, recover, and setup can still operate when it is unavailable.
Status reports catalog errors alongside saved installation observations.
The machine file must still be parseable TOML.
`detach`, `recover`, `locate`, `agent-hook`, and removal-only `setup` use its location and saved ownership without interpreting installation fields or the machine schema version.
They preserve unknown fields; setup removal only edits requested saved selections.
Offline `status` falls back to saved target observations when strict machine or state validation fails.
`status --refresh` still requires valid installation configuration.
Automatic policy attempts and ownership are generated state, not user-editable TOML settings.
New installations use state version `2`.
Maintenance accepts the common ownership/journal structure of versions `1` and `2` and retains its version and opaque fields on save.
It validates only the records and operations needed for the requested cleanup; it does not restore legacy installation behavior.
Unknown state versions or malformed ownership/journal structures are still rejected.
Regular setup, bootstrap, apply, update, sync, automatic updates, and refreshed status continue to require current configuration and state.
See [Removed interfaces](removed-interfaces.md) before upgrading an existing installation.

## AEM self-update settings

This policy belongs to the machine, independently of the content catalog and skill update policies.
The installer records runtime paths; manage the mode with `aem setup --self-update MODE`.
An omitted field on subsequent setup/installer calls retains its saved value.
Unknown fields are rejected.

| Field | Type | Meaning/default |
| --- | --- | --- |
| `mode` | String | `off` (default), `compatible`, or `breaking`. |
| `repository` | String | Release Git repository; defaults to `https://github.com/mirinae3145/agent-env-man.git`. Supports HTTPS, SSH, and absolute local paths. |
| `python` | Absolute path string | External Python 3.11+ used by the standalone worker and uv installation. Must be outside the uv tools directory, including resolved symlink locations. |
| `uv` | Absolute path string | Installer-discovered uv executable. |
| `tool_dir` | Absolute path string | Installer-discovered uv tools directory; also identifies the shared installation lock. |
| `bin_dir` | Absolute path string | Installer-discovered executable directory; passed to uv to preserve executable locations. |

All four runtime paths are required when enabling automatic updates or requesting an explicit update.
For final releases from `1.0.0` onward, `compatible` permits the same major.
For a prerelease, `compatible` permits only a higher numeric subversion with the same base `X.Y.Z` and the same `a`, `b`, or `rc` label (for example, `1.0.0rc1` to `1.0.0rc2`).
Changing the label, base version, or moving to a final release requires `breaking`.
Final installations retain their existing compatible range and do not select prereleases in `compatible` mode.
`breaking` permits any newer final or `a`/`b`/`rc` prerelease.
Release tags use `vVERSION` in Python notation or supported SemVer-style `-alpha`/`-beta`/`-rc` notation with an optional `.N` number.
Tag conversion and omitted-zero normalization must match the Python package version.
Development, post, local versions, and untagged commits are excluded.
See [version syntax and ordering](automation.md#update-aem-itself).
Attempts share a fixed 86,400-second interval across startup events and are recorded before launching the worker.
An explicit update bypasses the interval and can override the mode for that attempt without changing the saved policy.
Existing machine files remain usable with self-updates disabled until runtime registration through the installer.

## Catalog automatic update settings

The machine-owned `catalog_update` table controls the bound Git catalog, without relying on policies inside the file it updates.
Manage it with `bootstrap` during registration or `setup` afterward: repeat `--catalog-trigger` for events, set `--catalog-interval` for `min_interval`, and use `--catalog-git-timeout` for `timeout`.
Supplied triggers replace the saved list; omitted options retain their existing fields.
`--catalog-trigger manual` disables automatic catalog updates.
Policy-only setup supports `--dry-run`, requires no integration selections or executable, and does not rewrite existing profiles.
Omission leaves catalog delivery manual.
Unknown fields are rejected, and an enabled event policy requires a Git catalog binding; local catalogs remain externally managed.

| Field | Type | Default/meaning |
| --- | --- | --- |
| `trigger` | String or array of strings | `"manual"`; alternatively one or more unique `shell-start`, `agent-start`, or `interval` events. `manual` cannot be combined with events. |
| `min_interval` | Integer or float | `3600` seconds; finite and nonnegative. One clock shared across events for the repository/branch/entry binding. |
| `timeout` | Integer or float | `5` seconds per Git phase; finite and positive. |

Boolean numeric values are rejected.
There is no action field: catalog automation always performs the existing validated fast-forward update, without bootstrapping or applying declarations.
Attempts are persisted before remote access and failures are throttled too.
A changed repository, branch, or entry binding starts a separate attempt clock.
Explicit catalog update/publication commands do not consult or reset this clock.
The policy does not register startup hooks or an OS scheduler; use setup's existing callback or invoke `catalog auto` externally.

## Device automation settings

Manage the machine-owned `automation` table through installer/setup options.
Use `--automation MODE`, repeated `--automation-trigger EVENT`, `--automation-interval SECONDS`, and `--automation-git-timeout SECONDS`.
Omitted fields retain saved values; a supplied trigger list replaces the saved list.
Policy-only setup uses the machine journal and does not rewrite profiles or require integration selections.
Unknown fields are rejected.

| Field | Type | Default/meaning |
| --- | --- | --- |
| `mode` | String | `policies` (default), `off`, or `full`. |
| `trigger` | String or array of strings | Defaults to `shell-start` and `agent-start`. May contain unique supported events or only `manual`. Used in full mode. |
| `min_interval` | Integer or float | `3600` seconds, finite and nonnegative; full runs share one clock across events, including failures. |
| `timeout` | Integer or float | `30` seconds per content/catalog Git phase, finite and positive; used in full mode. |

Boolean numeric values are rejected.
`policies` retains the independent self-update, catalog-update, and skill policies and their clocks.
`off` disables all event-driven automatic entrypoints while leaving explicit commands available.
`full` uses the shared schedule, without consulting or modifying individual attempt clocks.
Its tool stage retains the self-update release permission (`off`, `compatible`, or `breaking`); the copied worker uses the existing 300-second tool subprocess bounds.
Full mode requires installer-registered runtime paths even when tool updates are off.

In full mode the implicit skill/directory trigger default becomes eligible for the full run, while explicitly declared trigger fields keep the existing precedence.
A resulting explicit or inherited `[]` excludes a skill or directory; other trigger lists and per-item actions/intervals are replaced by the full-run schedule and prepare/update/apply behavior.
Instruction groups with detached components are excluded together; remaining bundles participate without introducing instruction-specific policy tables.
A shared repository can still advance live links of excluded consumers.
Local or unbound catalogs skip Git delivery and use the existing local declarations.
Mode, schedule, or runtime changes cancel queued work; the fresh continuation also verifies the saved request binding before advancing content.

## Application settings declarations and bindings

Catalog `[settings.NAME]` requires `source` (a declared Git/external source), `path` (a literal source-relative settings file), and `format` (`"toml"` or `"json"`).
JSON settings require a strict top-level object with unique keys; comments and trailing commas are unsupported.
See [Settings management](settings-management.md) for field ownership, exact numeric comparison, and preserving edits.
Its optional `update` table defines a separate automatic sync policy:

| Field | Type | Behavior |
| --- | --- | --- |
| `trigger` | Array of unique events | `shell-start`, `agent-start`, or `interval`; defaults to `[]` in policies mode. Explicit `[]` also excludes the item from full mode. |
| `min_interval` | Integer or float | `600` seconds by default, finite and nonnegative; failures are throttled too. |
| `timeout` | Integer or float | `30` seconds by default, finite and positive. |

Settings do not inherit `updates.defaults` or named skill policies, and reject `action` and `policy` fields.
Every automatic settings attempt receives shared changes and applies the stage after successful reception.
Full mode includes settings with omitted triggers and replaces their individual schedule with the full-run schedule.
Attempt observations are generated under `sources.NAME.settings_automation` in saved state; full runs do not change this clock.
No other item fields are accepted; names cannot collide with skills or instructions.
Machine `[settings.NAME]` requires only `target`, an absolute application-file path or `~/...`.
Bootstrap `--setting-target NAME=PATH` persists these bindings and preserves omitted values.

Catalog version remains 2, machine version 1, and state envelope version 2.
Existing states require no conversion; new settings records and grouped journals are interpreted by the current AEM.
Older AEM versions cannot operate on these new declarations or recovery operations.
See [Staged settings](settings-management.md) for the canonical metadata grammar, storage, ownership, and merge semantics.

## Personal hook declarations and runtime bindings

`hooks.NAME` accepts exactly `source` (a declared source name) and `agents` (a
nonempty table of product bindings). Names share the content namespace. At least
one declared agent must be selected by the machine. Each binding accepts:

| Field | Contract |
|---|---|
| `event` | Required supported native event, case-sensitive. |
| `runtime` | Required identifier in machine `runtimes`. |
| `script` | Required literal source-relative regular UTF-8 file; no redirected paths. Git files must be tracked. |
| `args` | Optional array of literal strings, default `[]`; no shell templates or NUL. |
| `timeout` | Positive integer seconds; defaults to 10, except Codex SessionEnd/Interrupt default and maximum 3. |
| `matcher` | Optional native regular-expression string; expressions must pass Python regex syntax validation (`"*"` is also accepted as match-all), and unsupported matcher events are refused. Use expressions supported by the target product. |

Both profiles support SessionStart, SessionEnd, PreToolUse, PermissionRequest,
PostToolUse, PreCompact, PostCompact, SubagentStart, Stop, SubagentStop and
UserPromptSubmit. Codex additionally supports Interrupt; Claude additionally
supports PostToolUseFailure. UserPromptSubmit and Stop do not accept matchers; Codex Interrupt also refuses them.
Claude SessionEnd timeout is capped at 60 seconds.
Only command hooks are supported; async/prompt/agent hooks, environment maps and
plugin-only fields are not part of this declaration. Native products may impose
additional event restrictions; the script must follow their actual contract.

Machine `runtimes` maps identifiers to absolute existing executable paths:

```toml
[runtimes]
python = "/absolute/python"
```

Interpreter paths preserve symlinks, including virtualenv interpreter paths, so
execution uses the bound environment rather than its base interpreter.
Bootstrap's repeated `--runtime NAME=PATH` binds these paths without installing
anything. Omitted bindings persist. Duplicate names in one call are refused.
This additive syntax keeps catalog version 2 and machine version 1; older AEM
packages reject the new fields. No migration is needed for existing catalogs.
Personal ownership IDs are `NAME:hook` for Codex and `NAME:hook@claude` for Claude.
Select `NAME` to apply all declared agent bindings, or an exact ID for one binding;
`--agent` further filters the selection. Plain apply and automatic full mode
exclude these items. See [Personal hooks](personal-hooks.md) for the lifecycle.

## Agent startup hook duration

Machine `[setup].startup_hook_timeout` is a finite positive integer or float in seconds, defaulting to `10`; Boolean values are invalid.
Set it with `aem setup --startup-hook-timeout 60` or `python scripts/setup.py --startup-hook-timeout 60`.
Setup updates the registered Codex and Claude startup hooks and preserves the saved value when the option is omitted.
It can also save the value before agents are registered.
Instruction-location hooks retain their ten-second limit, and shell callbacks have no corresponding agent hook limit.
Git policy `timeout` fields remain independent; in policies mode, all synchronous startup work must fit within the outer agent limit.
In full mode, the callback queues the update sequence for execution after it exits.
