# Agent Environment Manager (AEM)

Install and update AI agent skills, personal instruction bundles, and general directories from a user-owned TOML catalog, supplied as a local file or delivered through Git.
Skills stay in their own Git repositories; directories, instructions, and staged application settings can come from Git or an existing local folder.
Upstream repositories need no AEM manifest.

```text
catalog.toml + machine.toml
             |
         bootstrap: clone or validate sources
             |
           apply
             |
     installed links or explicit skill copies
```

Links point directly to source contents, so an update changes them immediately.
Copies change on apply.
Prepared sources remain usable offline.

- [TOML specification](docs/configuration.md): every field, default, constraint, and path rule.
- [Command reference](docs/commands.md): complete command and option list.
- [Instruction walkthrough](docs/instruction-bundles.md): external and Git bundles on Linux/WSL and Windows.
- [Staged settings](docs/settings-management.md): edit and share selected application TOML or JSON fields.
- [Automation and AEM updates](docs/automation.md): device modes, independent policies, and tool updates.
- [Maintenance and recovery](docs/maintenance.md): conflicts, detach, backups, repair, and uninstalling.
- [Removed interfaces](docs/removed-interfaces.md): breaking changes and existing-installation precautions.
- [Changelog](https://github.com/mirinae3145/agent-env-man/blob/master/CHANGELOG.md): release history and upcoming changes.
- [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md): development and validation contracts.

The installed package includes this README, detailed docs, catalog examples, and the license text.
Run `aem docs` to print the local README path, or `aem --json docs` for the documentation root and entry paths.
These files match the installed package and can be read without a repository checkout or network access.

## Versioning and compatibility

AEM uses one package version for command, catalog, and existing-installation compatibility.
Review the [compatibility policy](docs/compatibility.md) and [existing-installation precautions](docs/removed-interfaces.md) before upgrading across an incompatible release.

CLI commands show readable fields and indented lists by default.
For scripts, add the global `--json` option before the command, for example `aem --json status`.
Put global options (`--config`, `--json`) before the command and command-specific options after their command.
Installed startup and instruction callbacks continue to emit their required JSON automatically.

## Install and connect this machine

Requirements: Python 3.11 or later and Git.
Linux/WSL and native Windows are supported in the implementation.
Native Windows tests cover link installation and recovery, generated PowerShell command execution, and process locking/waiting in temporary environments.
Link tests require symlink privileges; real agent-session delivery and replacement of a live tool installation remain separate integration checks.
Configure Git credentials separately; AEM uses noninteractive authentication and SSH batch mode.

With [uv](https://docs.astral.sh/uv/) installed, run from this checkout:

```bash
python scripts/setup.py --shell bash --agent codex
```

On Windows:

```powershell
py -3 scripts/setup.py --shell powershell --agent codex
```

The installer uses `uv tool install --reinstall` and then `aem setup` to connect startup integrations and link the official `idk-aem` skill for selected agents.
On first interactive installation, select the device automation mode (`policies`, `full`, or `off`), then the AEM release range (`off`, `compatible`, or `breaking`) when automation is enabled.
For unattended installation, supply `--automation full --self-update compatible` to enable the full sequence.
Omission preserves existing settings; a new installation defaults to `policies` with tool updates off.
Reinstallation preserves a saved mode and release repository unless explicitly overridden.
It does not bind a catalog or install user catalog skills/instructions.
Open a new selected shell to use the updated PATH.
Bash, Zsh, PowerShell, Codex, and Claude Code are the built-in integrations.
Select both with `aem setup --agent codex --agent claude`.
See [agent profiles](docs/agent-profiles.md) for shared contracts and product differences.
Repeat `--shell` or `--agent` to add selections; omitted selections remain configured.
The official skill guides AEM operations, including locating and publishing sources; content authoring remains governed by your task and its applicable instructions.
If its link cannot be installed, setup completes the shell/agent connection and reports the skill failure separately; resolve the cause and repeat `aem setup --agent codex` to retry.
It ships with AEM and is linked from the agent skills directory to the installed package, independently of your catalog.
After upgrading AEM with an external package manager, run `aem setup --agent codex` to verify or refresh the link.
To change integrations without reinstalling:

```bash
aem setup --shell zsh
aem setup --remove-shell bash
aem setup --dry-run
```

Setup preserves unrelated profile content, hooks, newline style, and permissions.
It owns an identified block in `.bashrc`, `$ZDOTDIR/.zshrc` (or `~/.zshrc`), or PowerShell's `$PROFILE.CurrentUserAllHosts`.
PowerShell discovery prefers `pwsh`, then `powershell.exe`.
Agent hooks use absolute interpreter and machine paths.
Setup rejects locally edited blocks, duplicate markers, invalid hook JSON, and redirected profiles.
After a partial failure, fix the error and retry the same setup selections.

For local use from this checkout without startup integrations:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/aem --help
```

On Windows use `py -3 -m venv .venv`, then `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\aem.exe`.
Activate the environment or use the executable's full path for the following examples.
For contribution work and the full test suite, install with `python -m pip install -e ".[dev]"` in the activated environment; see [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md).
The development extra adds tools without changing AEM behavior or registering integrations.
Run `aem setup` explicitly when you want to connect this environment to a shell or agent.

## Declare and install content

Save a catalog outside managed checkout storage:

```toml
version = 2

[sources.tools]
type = "git"
repository = "https://github.com/OWNER/TOOLS.git"

[skills.report]
source = "tools"
subdir = "skills/report"

[sources.documents]
type = "external"

[instructions.personal]
source = "documents"
entry = "AGENTS.md"

[instructions.personal.install.entry]
root = "agent"
```

Replace the repository with one containing the selected directory and its `SKILL.md`.
The external folder must contain `AGENTS.md` and any documents it references.
Skills and instructions are independent; omit either section if it is not needed.
Start from [skills](examples/skills.toml), [instructions](examples/instructions.toml), or the [combined catalog](examples/combined-catalog.toml).

```bash
aem bootstrap ~/ai-config/catalog.toml --external documents=~/Synced/agent-documents
aem apply --dry-run
aem apply
aem status
```

Bootstrap binds this catalog, saves device-local paths, and prepares sources.
It never installs targets, pulls existing checkouts, or modifies the catalog.
`apply` installs from prepared sources without fetching.
Adding a catalog declaration registers content; run bootstrap and apply for the new item.
Removing a declaration never deletes its installed target, hook, or checkout.

One machine file binds one catalog.
To use a separate configuration, put `--config /path/machine.toml` before each command.
Bootstrap accepts a positional catalog or `--catalog`, plus `--checkout-root`, repeated `--root NAME=PATH`, and repeated `--external NAME=PATH` bindings.
Omitted bindings are reused on later runs.
The [TOML reference](docs/configuration.md#machine-configuration) describes default locations and storage.

If the catalog lives in Git, supply its repository and relative file path instead of a local file:

```bash
aem bootstrap --catalog-repository git@github.com:OWNER/environment.git --catalog-path catalogs/personal.toml
aem apply --dry-run
aem apply
```

No hand-written machine file is needed.
AEM clones and validates the catalog, records its repository, file path, and branch in `machine.toml`, then prepares its declared content.
Use `--catalog-branch NAME` to select a branch; otherwise AEM records the remote default.
Include any required `--external` bindings just as with a local catalog.
Later `aem bootstrap` calls reuse these settings without pulling the catalog.

Explicit catalog maintenance:

```bash
aem catalog update               # Validate and fast-forward the catalog only.
aem bootstrap                    # Prepare newly declared sources.
aem apply --dry-run
aem apply
aem catalog locate               # Find the catalog checkout for editing.
aem catalog publish --dry-run
aem catalog publish -m "Update catalog"
```

`aem catalog status` inspects the catalog offline.
Publishing includes all nonignored changes in its repository, not just the TOML file.
Content `update`, `sync`, and skill automatic policies never refresh the catalog itself.
Catalog automatic updates are an independent device policy described below.
The catalog has a separate checkout even when it shares a remote repository with content.

Skill links default to `~/.agents/skills`; instruction entries default to the selected Codex home when using agent bindings, or the explicitly declared entry root.
The instruction bundle directory defaults to `<machine-file>.bundles/NAME`.
To copy a skill on one device, add to its machine file:

```toml
[modes]
report = "copy"
```

Copy is never a silent fallback when symlink creation fails.
Windows and WSL should use separate machine configurations, checkouts, and targets.

Instruction apply links the original entry and registers one SessionStart hook invoking `agent-hook NAME --agent codex`.
It preserves unrelated hook groups and reports the required Codex `/hooks` trust review.
AEM does not grant trust or modify Codex `config.toml`.
The callback supplies source-root and entry-path metadata, never document contents or applicability rules.
See the [walkthrough](docs/instruction-bundles.md) for trust, lookup failure, and detach behavior.

## Share a general directory

Declare a directory independently of agent skill discovery or instruction hooks:

```toml
[directories.cases]
source = "case-store"
subdir = "."

[directories.cases.install]
destination = "agent-loop"
```

Declare `sources.case-store` as Git or external, then prepare and install:

```bash
aem bootstrap /absolute/catalog.toml
aem apply --item cases --dry-run
aem apply --item cases
aem locate cases
```

This installs `~/agent-loop` as a link to the prepared source directory.
When `install.root` is omitted, directories use the saved `home` root; bootstrap records the user's home directory if that binding is absent.
Choose another initial path with `--root home=/absolute/parent`, or declare `install.root = "personal"` and bind it with `--root personal=/absolute/parent`.
Omit the entire `install` table to use the item name as the directory name under `home`.
Record through the link, then use authorized `aem publish cases -m "Record cases"` to share a Git source and `aem update cases` on another device to receive it.
Local edits and diverged histories retain the ordinary Git refusal rules and require explicit reconciliation.
For explicit copies, set `install.mode = "copy"`; copy edits are protected and can be shared with explicit `publish --from-copy`.
External sources need `--external case-store=/absolute/source`; their transport stays with their existing service.
On POSIX, `directories.cases.preserve_symlinks = true` preserves nested symbolic links without copying their targets.
Relative links must stay within the source root; copy and detach preserve link text but may change what it resolves to.
Directories use the same automatic policies as skills and participate in full mode, preserving empty-trigger exclusions and detach.
See [directory configuration](docs/configuration.md#directoriesname) and the [example](examples/directories.toml).

## Daily work

```bash
aem bootstrap                    # Prepare newly declared content.
aem update                       # Update sources; links change immediately.
aem apply                        # Install or refresh from local sources.
aem sync                         # Update all, then apply if all updates succeed.
aem status                       # Inspect without network access.
aem status --refresh             # Fetch observations without advancing checkouts.
aem locate personal              # Resolve installed instruction paths.
```

`bootstrap --item NAME` and `update NAME` select skill, directory, instruction, setting, or personal hook source names.
`apply --item report` selects a skill; `apply --item personal:entry` includes the entry's bundle and hook.
`sync --item` filters only installation, while its update phase still visits all sources.
See [Commands](docs/commands.md) for all arguments, previews, callbacks, and exit codes.

## Edit and publish

Find the prepared source with `locate --source`, edit it directly or through its installed link, then publish by catalog skill or instruction bundle name:

```bash
aem locate report --source                  # Find the prepared source to edit.
aem locate report --source --cd             # Enter it with the registered shell integration.
aem locate report --repo --cd               # Enter the source Git repository root.
aem locate source:tools --source --cd       # Enter a named catalog source root.
aem publish report --dry-run                # Review local changes and outgoing commits.
aem publish report -m "Clarify guidance"    # Commit checkout changes and push.
aem publish report                         # Push changes already committed.
```

Pass multiple names to publish several sources; shared checkouts are grouped and processed once, with all connected skills, instructions, and settings listed.
Selection covers the whole repository, including files outside declared skills.
The optional dry run is offline; publication fetches first and leaves behind/diverged histories for explicit reconciliation.
A failed push retains the local commit for retry.
For copy installations, edit the checkout and apply after committing; installed-copy edits are not collected automatically.
To share edits made in a managed skill, directory, or instruction bundle copy, use:

```bash
aem publish report --from-copy --dry-run
aem publish report --from-copy -m "Share copy edits"
```

Collection compares the last common baseline and stops when both the source and copy changed differently.
It retains source backups and reports paths for manual or agent resolution without launching tools.
For an external directory copy, omit the message: completion means local source handoff, leaving device-to-device synchronization to its service.
External-folder synchronization stays with its existing service.
AEM also supports the first push to a registered empty remote after successfully confirming that it advertises no refs, including tags.
A populated remote with a missing registered branch, or an authentication/network/fetch failure, stops publication before committing.
Dry runs remain offline.

See [publish](docs/commands.md#publish) for commit scope, Git settings, and failure behavior.

## Application settings

Manage selected application TOML or JSON fields through an editable local stage.
Declare `[settings.NAME]` with `source`, `path`, and `format = "toml"` or `format = "json"` in the catalog, then bind its actual file:

```bash
aem bootstrap /absolute/catalog.toml --setting-target editor=/absolute/app/config.toml
aem locate editor                         # Edit the stage at the reported entry.
aem apply --item editor --dry-run
aem apply --item editor
aem settings collect editor               # Collect edits to existing managed fields.
aem export editor                         # Reflect the stage in Git/external source.
aem publish editor -m "Update preferences" # Export, commit, and push a Git source.
```

Update receives shared changes without applying them; publication never collects actual settings automatically.
Unmanaged fields remain local, deleted fields propagate through metadata, and explicit release preserves actual values.
Settings have independent per-item automatic sync policies and participate by default in full automation, preserving empty-trigger exclusions and detached items.
See [Staged settings](docs/settings-management.md) for declarations, conflicts, deletion/release, and recovery.

## Device automation modes

A new installation defaults to `policies`, with AEM updates off and catalog/skill automation requiring opt-in.
Choose `full` to queue AEM, catalog, and eligible skill/directory/instruction/settings updates in sequence, including preparation and installation of new declarations.
Choose `off` to disable automatic work while retaining explicit commands.
Settings automation receives and applies changes together; collection, export, and publication remain explicit.

```bash
python scripts/setup.py --shell bash --agent codex --automation full --self-update compatible
aem automation --trigger agent-start --dry-run
aem setup --automation off
```

Automatic work preserves conflicts and detached content.
Shared checkout updates can still change linked consumers excluded from installation.
Queued work is not yet completed; inspect `aem status` for eventual results.
See [Automation and AEM updates](docs/automation.md) for mode comparisons, schedules, catalog and skill policies, and failure behavior.

## Update AEM itself

```bash
aem self update --dry-run
aem self update
aem self status
```

For final releases from `1.0.0` onward, `compatible` permits newer final releases in the same major version.
For `a`/`b`/`rc` prereleases, it permits only subversion increases with the same base version and pre label; moving to a different series or a final release requires `breaking`.
Explicit updates work with automation off and queue a worker; use `aem self status` to check completion.
See [AEM update guidance](docs/automation.md#update-aem-itself) for automatic updates, incompatible releases, runtime requirements, and repair.

To publish a prepared AEM release, use `aem self publish --dry-run`, then `aem self publish`.
This uses the recorded local installation source, or accepts `--checkout PATH` to select another AEM checkout.
Prepare a clean committed checkout and its matching `vVERSION` tag with Git first; publication creates neither commits nor tags.
Tags may use Python notation or `-alpha`/`-beta`/`-rc` with optional `.N` numbers; for example, `v1.0.0-beta` matches package version `1.0.0b0`.
The current branch and release tag are published to `origin` with atomic push.
See [release publication](docs/commands.md#self-publish) for prerequisites and preview limits.

## Conflicts, detach, and recovery

AEM refuses unmanaged targets and locally modified copies unless explicitly authorized.
Detach preserves current contents and releases ownership; automatic work does not reinstall detached content.

```bash
aem apply --item report --dry-run
aem detach report
aem status
aem recover
```

Transactions are per target, so earlier successful work can remain after a later failure.
Recovery preserves later user edits; keep state and backups instead of deleting them to bypass conflicts.
See [Maintenance and recovery](docs/maintenance.md) for adoption/replacement, reattachment, Git safety, backup locations, and uninstalling.

## Personal command hooks

Declare user-authored scripts separately from skills/plugins, bind their runtime
on each machine, and register only with explicit `apply --item NAME`. AEM never
executes scripts or grants product trust. See [Personal hooks](docs/personal-hooks.md).

## License

[MIT License](LICENSE.txt).

## AI disclosure

OpenAI Codex assisted with design, implementation, documentation, and automated tests.

### Retain an external catalog offline

Register a local catalog with `aem bootstrap /path/to/catalog.toml --catalog-copy` to keep a managed editable copy.
Commands always read that copy; `aem catalog update` explicitly receives original changes.
To return edits, preview `aem catalog publish --from-copy --dry-run`, then publish with `aem catalog publish --from-copy`.
Conflicting changes stop without overwriting; the external synchronization service remains responsible for transport.
See [copied local catalog bindings](docs/configuration.md#copied-local-catalog-binding) for storage and recovery details.
