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

## Install and connect this machine

Requirements: Python 3.11 or later, Git, and [uv](https://docs.astral.sh/uv/).
Linux/WSL and native Windows are supported; link installation requires symbolic link privileges.
Configure Git credentials separately; AEM uses noninteractive authentication.

From this checkout on Linux/WSL:

```bash
python scripts/setup.py --shell bash --agent codex
```

On Windows:

```powershell
py -3 scripts/setup.py --shell powershell --agent codex
```

The installer installs AEM and connects the selected shell and agent, including the official `idk-aem` operations skill.
It does not bind a catalog or install user catalog content.
Open a new selected shell to use the updated PATH.
Supported integrations are Bash, Zsh, PowerShell, Codex, and Claude Code; use `--agent claude` for Claude or repeat `--agent` to select both.
Windows and WSL should use separate machine configurations, checkouts, and targets.

A new installation defaults to `policies` automation with AEM tool updates off; content automation requires opt-in.
See [Automation](docs/automation.md) to choose another mode and [setup](docs/commands.md#setup) to change or remove integrations.
For local development and editable installation, see [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md).

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

Replace the Git URL with a repository containing the selected skill directory and its `SKILL.md`.
The external folder must contain `AGENTS.md` and its referenced documents.
Skills and instructions are independent; omit either section if it is not needed.
Start from the [skill](examples/skills.toml), [instruction](examples/instructions.toml), or [combined catalog](examples/combined-catalog.toml) examples.

```bash
aem bootstrap ~/ai-config/catalog.toml --external documents=~/Synced/agent-documents
aem apply --dry-run
aem apply
aem status
```

| Phase | Result |
| --- | --- |
| `bootstrap` | Binds the catalog, saves device paths, and prepares sources without installing targets or pulling existing checkouts. |
| `apply --dry-run` | Previews installation from prepared local sources. |
| `apply` | Installs or refreshes selected content without fetching. |
| `status` | Inspects sources and saved installations offline. |

One machine configuration binds one catalog.
For a separate configuration, put `--config /absolute/machine.toml` before each command.
For a Git-delivered catalog, see [bootstrap](docs/commands.md#bootstrap).

Instruction installation reports the required Codex `/hooks` trust review; AEM does not grant trust.
The instruction callback supplies reading-location metadata, while your documents determine what guidance applies.
Follow the [instruction walkthrough](docs/instruction-bundles.md) for platform setup, trust, and copied bundles.

## Daily work

```bash
aem bootstrap                    # Prepare newly declared content.
aem update                       # Update sources; links change immediately.
aem apply --dry-run              # Preview installation or refresh.
aem apply                        # Install from local sources.
aem status                       # Inspect without network access.
```

Use `aem update NAME` followed by `aem apply --item ID` for selected content.
An instruction entry uses `NAME:entry`, which includes its bundle and hook.
`aem sync` updates all sources and applies only if all updates succeed; `sync --item ID` filters installation only.
If the catalog itself changed upstream, use `aem catalog update`, then bootstrap and preview/apply the new declarations.
Content updates do not refresh the catalog.

Default output summarizes results; use `aem --verbose status` for details or `aem --json status` for scripts.
Global options precede the command and `--verbose` cannot be combined with `--json`.
See [Commands](docs/commands.md) for selectors, output contracts, and preview limits.

## Edit and share content

Locate the prepared source, edit it, then preview and publish when you want to share the change:

```bash
aem locate report --source
aem publish report --dry-run
aem publish report -m "Clarify guidance"
```

Publication commits and pushes the whole selected Git repository, including changes outside the named skill or bundle.
Review unrelated edits and outgoing commits before publishing.
Editing through an installed link changes the source immediately.
To return managed-copy edits, use explicit `publish --from-copy`; ordinary publication does not collect them.
See [publish](docs/commands.md#publish) for collection, conflicts, external sources, and retry behavior.

## Preservation and recovery

- Links expose source updates immediately; copies refresh on apply and protect local edits.
- Removing a catalog declaration leaves its installed target and ownership intact.
- `aem detach ID` preserves contents and releases management; automatic work does not reinstall detached content.
- Transactions are per target, so earlier successful work can remain after a later failure.
- After an interrupted operation, retain state and backups and use `aem recover`; recovery preserves later user edits.

See [Maintenance and recovery](docs/maintenance.md) for conflicts, reattachment, backup locations, and uninstalling.
Before an incompatible upgrade, review [Compatibility](docs/compatibility.md) and [existing-installation precautions](docs/removed-interfaces.md).

## Find the detailed guide

| Task | Guide |
| --- | --- |
| Define catalog fields, device paths, and installation modes | [Configuration](docs/configuration.md) |
| Choose commands, selectors, and options | [Commands](docs/commands.md) |
| Install personal instruction bundles | [Instruction walkthrough](docs/instruction-bundles.md) |
| Share general directories | [Directory configuration](docs/configuration.md#directoriesname) and [example](examples/directories.toml) |
| Edit and share application TOML or JSON fields | [Staged settings](docs/settings-management.md) |
| Configure automation or update AEM | [Automation and AEM updates](docs/automation.md) |
| Register user-authored agent scripts | [Personal hooks](docs/personal-hooks.md) |
| Resolve conflicts, recover, or uninstall | [Maintenance](docs/maintenance.md) |
| Develop and validate AEM | [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) |
| Review release history | [Changelog](https://github.com/mirinae3145/agent-env-man/blob/master/CHANGELOG.md) |

The installed package includes this README, docs, examples, and license text.
Run `aem docs` for the local README path or `aem --json docs` for the documentation root and entry paths.
These files match the installed version and are available offline.

## License

[MIT License](LICENSE.txt).

## AI disclosure

OpenAI Codex assisted with design, implementation, documentation, and automated tests.
