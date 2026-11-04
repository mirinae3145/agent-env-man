# Machine configuration

The machine file binds a catalog and its sources to device-local paths.
This reference covers catalog delivery, agent roots, saved setup, and storage and maintenance boundaries.

## Top-level fields

These top-level fields bind the catalog and control device-local storage and integrations.

| Field/table | Type | Meaning/default |
| --- | --- | --- |
| `version` | Integer | Required, exactly `1`. |
| `catalog` | String or table | Optional direct local path, local copy binding, or [Git binding](#git-catalog-binding); required for bootstrap/content preparation. One binding per machine file. |
| `checkout_root` | String | Managed Git storage; defaults to sibling `<machine-file>.checkouts`. |
| `roots` | Table of paths | User-named installation roots; bootstrap defaults missing `skills`, `agent`, and `home`. |
| `agents` | Table | Product destinations and named instance path bindings, normally written by setup. |
| `runtimes` | Table of paths | Personal hook interpreter bindings; bootstrap never installs executables. |
| `tool_hooks` | Table | Hooks that other tools install for themselves and that `aem check-tool-hooks` expects; see [Tool hooks](#tool-hooks). |
| `external_paths` | Table of paths | Logical external source bindings; every used external must be bound. |
| `modes` | Table of strings | Catalog skill, directory, or instruction names mapped to `"link"` or `"copy"`. Unknown names fail catalog validation. |
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
home = "/home/me"

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

## Roots and agents

`agents.codex`, `agents.claude`, and named instances such as `agents.codex-lab` and `agents.claude-lab` accept only `root` and `skills` path strings.
Named instances default to `~/.NAME` and `~/.NAME/skills`, independently of default-profile environment overrides.
Their roots cannot overlap another configured instance root.
See [named instances](../agent-instances.md) for setup, selection, discovery limits, and removal.

For the original Codex destination, omitted fields default to `CODEX_HOME` (or `~/.codex`) and `~/.agents/skills`, respectively.
Setup persists resolved defaults; saved values take precedence over later environment changes.
Setup initially respects existing `roots.agent` and `roots.skills` when adding Codex.
Bootstrap root overrides for `agent` and `skills` also update an existing Codex binding.
Custom roots must be declared explicitly.
AEM derives `aem-agent-codex` and `aem-skills-codex` roots from the agent binding; conflicting manual definitions are rejected.

Machine `settings.NAME` accepts `target` and optional `agent`.
The agent names a destination and restricts installation selection to that instance; preparing or applying an active setting requires that destination to be configured, with the target inside its root.
Detached associations may remain after instance removal.
Omission preserves the setting's existing behavior without an agent selector or with the original product selectors; named selectors exclude unbound settings.
Changing an active setting's association requires detach first.
Each catalog setting name still has exactly one stage and target; use distinct declarations sharing one source/path to deploy common fields independently.

## Tool hooks

A tool hook is a hook a tool such as herdr installs for itself in a Claude Code profile.
AEM does not own, install, edit or remove it; the machine declares what to expect, and `aem check-tool-hooks` reports when it is missing.

```toml
[tool_hooks.herdr]
command = "herdr"
event = "SessionStart"
contains = "herdr-agent-state.sh"
agents = ["claude", "claude-lab"]
```

Tool hook declarations accept these fields:

| Field | Meaning |
| --- | --- |
| `command` | Executable looked up on `PATH`. When it is not found, the tool is skipped without checking any profile. |
| `event` | Claude Code hook event that must carry the hook. |
| `contains` | Text that one hook command under that event must contain. |
| `agents` | Optional registered Claude Code agents to check; omitted means every registered Claude Code agent. |

The declaration is per machine, so a tool installed on one machine does not make another machine report a missing hook.
Older AEM versions reject a machine file that contains `tool_hooks`.

## Copied local catalog binding

Use `bootstrap /absolute/external/catalog.toml --catalog-copy` (or `--catalog PATH --catalog-copy`) to retain a managed local file:

```toml
[catalog]
type = "local"
path = "/absolute/external/catalog.toml"
mode = "copy"
```

`path` identifies the original regular file; relative paths and redirected ancestry are rejected in this machine table.
The managed entry is `<machine-file>.catalog-copy/catalog.toml`.
Ordinary catalog operations always consume that copy, even when the original is available.
The copied file remains editable; valid edits are used on the next command, while malformed edits require repair before content operations.
`catalog locate` finds the editable copy without parsing its TOML, and `catalog locate --source` reports the original even when absent.

### Reception and reverse publication

`catalog update` explicitly receives original changes, and `catalog publish --from-copy` explicitly returns copy edits.
Both compare a saved common content hash: one-sided changes flow only in their selected direction, equal contents advance the baseline, and competing changes stop without overwriting.
No automatic merge, force publication, or local catalog automatic refresh is provided.
Source absence does not prevent use of the copy, but update/publication require an existing regular original and never recreate it.
External synchronization remains outside AEM.

### Rebinding and storage

Bootstrap with an unchanged binding reuses the copy without refreshing it.
Rebinding can replace only an unchanged owned copy; preserve and reconcile local edits first.
Unowned files at the managed location are not adopted implicitly.
Registration, refresh, and publication retain recoverable backups and commit the file and comparison state together.
Copy storage and the original must not overlap manager storage, content roots, or installation targets.
Existing string bindings remain direct local file bindings unless explicitly registered with `--catalog-copy`.

## Git catalog binding

Bootstrap writes this table when given `--catalog-repository URL --catalog-path PATH`; no manual machine-file setup is required.
The local string form remains supported with its existing behavior.

### Declaration

```toml
[catalog]
type = "git"
repository = "git@github.com:OWNER/environment.git"
branch = "main"
path = "catalogs/personal.toml"
```

Git catalog bindings accept these fields:

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

### Git binding maintenance

Only `catalog update` advances an existing catalog checkout.
Bootstrap reuses it without pulling, and content update/sync/skill automatic policies do not refresh it.
Catalog updates can run automatically only through the independent [catalog update policy](automation.md#catalog-automatic-update-settings).

Catalog status and locate also support local bindings.
Update and publish support Git bindings and the explicit local copy workflow; direct local file bindings do not support either operation.

Switching to a local binding preserves the old Git checkout.
Reusing the same Git checkout requires a matching origin and branch; a new binding never resets or replaces a mismatching repository.
To switch repositories, preserve or move the old `<machine-file>.catalog` checkout explicitly before bootstrapping the new binding.
See [catalog commands](../commands/catalog.md#catalog) for validation, publication, and failure behavior.

## Saved setup

Saved setup records startup integrations and controls the package-owned operations skill.

### Saved fields

`setup` accepts only `executable`, `shells`, and `startup_hook_timeout`.
See [Agent startup hook duration](automation.md#agent-startup-hook-duration) for the independent callback limit.
`executable` is an absolute path to the installed `aem` executable.
`setup.shells` maps `bash`, `zsh`, or `powershell` to absolute profile paths.
Manage these selections with `aem setup`; editing TOML does not itself install or remove profile blocks, hook groups, or official skill links.
Setup rejects an invalid executable path before writing profiles and requires an existing executable except during dry run.

### Official skill installation

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

## Storage and validation boundaries

Manager storage separates device state from sources and targets.
Maintenance uses saved ownership even when installation configuration is no longer valid.

### Storage paths

Named Git sources use `CHECKOUT_ROOT/.aem-repositories/NAME`; former direct-skill checkouts are preserved during manual transition.
Ownership, attempt records, and recovery journals live in sibling `<machine-file>.state`; default bundle links live in `<machine-file>.bundles`.
Do not synchronize machine files, checkouts, or state between devices.
Share a Git catalog through its repository, letting each device prepare its own checkout and machine binding.
External roots must be disjoint from each other, managed checkout storage, the catalog, machine file, and state.
Targets may not overlap sources, manager storage, or another owned target tree.

### Maintenance without valid installation configuration

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
See [Removed interfaces](../removed-interfaces.md) before upgrading an existing installation.
