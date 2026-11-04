# Instruction installation variants

These variants adapt the [external bundle walkthrough](install.md#original-files-before-installation) for Windows, Git, shared skills, or offline copies.
Each example uses the same `guidance/start.md` bundle unless stated otherwise.

## The same catalog on a Windows device

Keep `instructions.toml` unchanged and bind this device's folder:

```powershell
aem bootstrap C:/Users/me/ai-config/instructions.toml --external personal-documents=D:/Synced/agent-documents
aem apply
```

With the default environment, the generated `%LOCALAPPDATA%/agent-env-man/machine.toml` contains the following bindings (plus a default `skills` root):

```toml
version = 1
catalog = "C:/Users/me/ai-config/instructions.toml"

[external_paths]
personal-documents = "D:/Synced/agent-documents"

[roots]
agent = "C:/Users/me/.codex"
```

With symbolic link creation enabled, the same commands using this machine file produce:

```text
C:/Users/me/AppData/Local/agent-env-man/machine.toml.bundles/personal
  -> D:/Synced/agent-documents/guidance
C:/Users/me/.codex/AGENTS.md
  -> D:/Synced/agent-documents/guidance/start.md
C:/Users/me/.codex/hooks.json
  merged SessionStart and SubagentStart groups invoking the AEM callback
```

The generated command explicitly invokes an encoded PowerShell command on Windows and uses POSIX quoting on Linux/WSL; paths containing spaces are supported.
AEM does not transfer the catalog or source documents between these devices.

## Use Git for the instruction source instead

For a new installation backed by Git, use this complete alternative catalog:

```toml
version = 2

[sources.personal-documents]
type = "git"
repository = "https://github.com/OWNER/PERSONAL-DOCUMENTS.git"
branch = "main"

[instructions.personal]
source = "personal-documents"
subdir = "guidance"
entry = "start.md"

[instructions.personal.install.entry]
root = "agent"
destination = "AGENTS.md"
```

Replace the example URL with your repository; it must contain the same `guidance/start.md` and auxiliary document tree as tracked files.
No AEM manifest is required in that repository.
On a fresh device, bootstrap this Git catalog without `--external`; AEM chooses the checkout path automatically.
When migrating an existing installation, detach before changing its source binding; an unused saved external binding may be removed from machine configuration.
The other machine fields and installation commands remain the same.

| Changed field | Result |
| --- | --- |
| `[sources.personal-documents]` | Names one managed Git checkout that bundles and skills can explicitly share. |
| `repository` | Supplies the clone URL. A local Git fixture can instead use an absolute repository path. |
| `branch = "main"` | Selects the branch to clone and fast-forward. If omitted, bootstrap discovers and records the remote's default branch. |
| `source = "personal-documents"` | Selects that named repository instead of looking up `external_paths`. Set `type = "git"` on that source. |

Bootstrap clones to `/home/me/.config/agent-env-man/machine.toml.checkouts/.aem-repositories/personal-documents`.
Apply links `/home/me/.config/agent-env-man/machine.toml.bundles/personal` directly to that checkout's `guidance` directory.
The hook callback now resolves to the Git checkout's `guidance` root and entry document; the global entry directly links to that original file.
`update personal` fetches and fast-forwards this checkout, immediately changing linked content; the active entry/tree removal guard can block the update.
Switching an already installed bundle between external and Git sources changes its source path and requires detach and deliberate reattachment, rather than simply editing the source selector and applying.

## Add Git skills alongside the external bundle

The original external-only catalog needs no `[skills]` or Git source declarations.
To manage both kinds of content together, use [examples/combined-catalog.toml](../../examples/combined-catalog.toml), which adds:

```toml
[sources.tools]
type = "git"
repository = "https://github.com/OWNER/TOOLS.git"

[skills.report]
source = "tools"
subdir = "skills/report"
```

Replace the repository URL with your skill repository and add `skills = "/home/me/.agents/skills"` inside the existing machine `[roots]` table.
Bind `catalog` to the combined catalog's actual local filename.
`sources.tools` names the Git source; `skills.report.source` selects it, and `subdir` selects the directory containing its tracked SKILL.md.
The skill's omitted `install.root` defaults to `skills`, and its omitted `install.mode` defaults to `link`.
The registration name `report` determines the installed skill directory name.

Bootstrap now prepares the tools checkout as well as validating the external instruction bundle.
Apply installs four managed targets:

| Ownership ID | Installed target | Content source |
| --- | --- | --- |
| `report` | `/home/me/.agents/skills/report` | Direct link to `/home/me/.config/agent-env-man/machine.toml.checkouts/.aem-repositories/tools/skills/report` |
| `personal:bundle` | `/home/me/.config/agent-env-man/machine.toml.bundles/personal` | Direct link to `/home/me/Syncthing/agent-documents/guidance` |
| `personal:entry` | `/home/me/.codex/AGENTS.md` | Direct link to the original `guidance/start.md` |
| `personal:hook` | `/home/me/.codex/hooks.json` | Owned SessionStart and SubagentStart groups; unrelated hooks are preserved |

The skill is not a prerequisite for the instruction bundle; they simply share one inventory and the same management commands.

## Keep a managed copy for offline reading

Set `mode = "copy"` under `[instructions.personal.install.bundle]`, or set `personal = "copy"` under the machine `[modes]` table.
The bundle is copied on apply and the global entry links to its entry inside that copy.
All referenced documents remain together when the external source disappears; `locate personal` and the instruction hook resolve the installed tree without reading the catalog.
`locate personal --source` still selects the original for source editing.
Windows still needs symbolic link capability for the global entry; there is no automatic fallback to an entry copy.

Existing linked installations require an explicit transition:

```bash
aem detach personal:bundle personal:entry
# Set the bundle mode to copy in the catalog or machine configuration.
aem apply --item personal:bundle --reattach --adopt
aem apply --item personal:entry --reattach --replace
```

Adoption requires the preserved bundle to match the source; reconcile differing contents first.
The entry replacement preserves the detached entry in a backup and re-registers its hook.
For multiple agents these selectors cover each agent destination; use `--agent` for a single agent.

Source updates reach the copy only on apply, which refuses to overwrite local edits without explicit replacement.
To return installed edits, preview `aem publish personal --from-copy --dry-run`, then use `aem publish personal --from-copy` for an external source or add `-m "Update instructions"` for Git.
Competing source/copy changes and differing exports from multiple agent copies stop collection.
External publication confirms writing the local original, not synchronization by its external service.
