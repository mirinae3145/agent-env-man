# A complete personal instruction bundle example

Start with an external folder and instructions only.
Git skills are optional and are added separately at the end of this walkthrough.
The filenames `instructions.toml` and `machine.toml` are examples: AEM uses the catalog binding and `--config` argument, not filename-based behavior.

The canonical field and command definitions are in [TOML configuration](configuration.md) and [Commands](commands.md).

## Three things to keep separate

| Part | What it contains | Who manages it |
| --- | --- | --- |
| Original documents | Your entry document, development/research/workspace guidance, and references | You; optionally an external synchronization service |
| Shared catalog | Which bundle to use, its entry file, and logical installation destinations | You; the same declaration can be used on different devices |
| Machine configuration | Where this device keeps the catalog, external folders, checkouts, and installation roots | You; paths can differ on each device |

AEM reads the two TOML files, chooses the bundle installation directory, links the document tree and original entry, and registers a Codex SessionStart hook.
The hook discovers the actual bundle root and original entry file using AEM's local locator; it supplies path metadata to Codex without embedding commands or changing the original document.
It does not supply the personal instructions or decide when development, research, or workspace guidance applies.

## Original files before installation

Assume your existing documents have this layout on a Linux/WSL device:

```text
/home/me/Syncthing/agent-documents/       external source root
|-- guidance/                           selected bundle root
|   |-- start.md                        original entry document
|   |-- development/
|   |   `-- conventions.md
|   |-- research/
|   |   `-- workflow.md
|   |-- workspaces/
|   |   `-- project-alpha.md
|   `-- references/
|       `-- writing.md
`-- unrelated-notes/                    outside the selected bundle
```

These names are illustrative, not a required directory structure.
`start.md` could instead be `AGENTS.md`, `index.md`, or a file in a nested directory.
Your documents define which other documents to read and under which conditions.
For example, if your entry refers to `development/conventions.md`, that file must be supplied by you inside the bundle.
AEM does not scan links or include files outside the selected tree automatically.

Keep the catalog outside that source folder; bootstrap generates the device binding separately:

```text
/home/me/ai-config/instructions.toml                  shared catalog
/home/me/.config/agent-env-man/machine.toml            generated device-specific bindings
```

## Complete shared catalog

Save [examples/instructions.toml](../examples/instructions.toml) as `/home/me/ai-config/instructions.toml`:

```toml
version = 2

[sources.personal-documents]
type = "external"

[instructions.personal]
source = "personal-documents"
subdir = "guidance"
entry = "start.md"

[instructions.personal.install.entry]
root = "agent"
destination = "AGENTS.md"
```

| Field or table | How AEM interprets this example |
| --- | --- |
| `version = 2` | Selects catalog schema version 2. It is not the document bundle's version. |
| `[sources.personal-documents]` | Declares a logical external source named `personal-documents`. Set `type = "external"`; its actual path belongs in machine configuration. It neither creates the source directory nor configures synchronization. |
| `[instructions.personal]` | Registers a bundle named `personal`. This name identifies the source in commands and produces ownership IDs `personal:bundle`, `personal:entry`, and `personal:hook`. It does not automatically choose the installed directory name. |
| `source = "personal-documents"` | Looks up `external_paths.personal-documents` in machine configuration to find the source root. For a Git source, reference a source declared with `type = "git"`, as shown below. |
| `subdir = "guidance"` | Appends `guidance` to the source root, selecting `/home/me/Syncthing/agent-documents/guidance`. Omit it or use `"."` to select the entire source root. |
| `entry = "start.md"` | Selects the original file inside that bundle: `/home/me/Syncthing/agent-documents/guidance/start.md`. This is the link source, not the global destination filename. |
| `install.bundle.root` (omitted) | AEM chooses `/home/me/.config/agent-env-man/machine.toml.bundles` beside the machine file. No `roots.rules` setting is needed. An explicit value can still select a configured machine root. |
| `install.bundle.destination` (omitted) | Defaults to the bundle name `personal`, producing `/home/me/.config/agent-env-man/machine.toml.bundles/personal`. An explicit relative path can override it. |
| `install.entry.root = "agent"` | Looks up the Codex home base `roots.agent`, here `/home/me/.codex`. The name `agent` is a lookup key; hook registration uses `hooks.json` in this directory. |
| `install.entry.destination = "AGENTS.md"` | Appends this filename to the entry base. AEM links `/home/me/.codex/AGENTS.md` directly to the original `guidance/start.md`; its text remains unchanged. |

`subdir`, `entry`, `install.bundle.destination`, and `install.entry.destination` use literal `/`-separated relative paths, not shell expressions.
Traversal such as `../` and absolute paths are rejected; only `subdir` permits `.`.
The three installed targets must not overlap: the entry and `hooks.json` must be outside the directory owned by `personal:bundle`.
Within one machine configuration, one instruction bundle can own the AEM hook group in a given hooks file; use distinct Codex home roots for distinct bundles.

## Bootstrap arguments and saved machine configuration

Register the catalog and this device's external folder directly:

```bash
aem bootstrap /home/me/ai-config/instructions.toml --external personal-documents=/home/me/Syncthing/agent-documents
```

No machine file needs to be prepared first.
The positional argument selects the local catalog; `--catalog PATH` is an equivalent spelling.
Repeat `--external NAME=PATH` for each external source that needs a binding.
The name must be declared in `[externals]`; the path is expanded for `~` and resolved relative to the command's working directory before being saved as an absolute path.
Omitted bindings are reused on subsequent bootstrap calls; a required binding with no saved value is an error.
Duplicate names and unknown names are rejected before saving or cloning.
A Git-only catalog needs no external binding.

For this walkthrough, assume Linux/WSL with `XDG_CONFIG_HOME` and `CODEX_HOME` unset.
AEM generates `/home/me/.config/agent-env-man/machine.toml`, equivalent to the following (plus a default `skills` root):

```toml
version = 1
catalog = "/home/me/ai-config/instructions.toml"

[external_paths]
personal-documents = "/home/me/Syncthing/agent-documents"

[roots]
agent = "/home/me/.codex"
```

| Field | How AEM applies it |
| --- | --- |
| `version = 1` | Selects machine configuration schema version 1, independently of the catalog's version field. |
| `catalog` | Reads declarations from this local file. An absolute path selects it directly; a relative path is resolved relative to `machine.toml`'s directory. AEM does not download the catalog. |
| `checkout_root` (omitted) | AEM reserves `/home/me/.config/agent-env-man/machine.toml.checkouts` for managed Git clones. The external-only example does not clone anything here. An explicit machine path can override it. |
| `external_paths.personal-documents` | Binds the shared logical source name to an existing folder on this device. AEM expects `guidance/start.md` inside it for this catalog. |
| `roots.agent` | Supplies the base to which `install.entry.destination` is appended. Use the Codex home where global AGENTS.md and hooks.json are discovered. |

The default config directory is `$XDG_CONFIG_HOME/agent-env-man` or `~/.config/agent-env-man` on Linux/WSL, and `%LOCALAPPDATA%/agent-env-man` on Windows (falling back to `~/AppData/Local`).
The default `agent` root is `CODEX_HOME` or `~/.codex`; `skills` defaults to `~/.agents/skills`.
Saved roots take precedence over later environment changes.
Optional `--root NAME=ABSOLUTE_PATH` and `--checkout-root PATH` select custom locations during bootstrap.
An explicitly named `install.entry.root` other than `agent` must be supplied through `--root` or machine configuration.
For separate configurations, use `aem --config /custom/machine.toml bootstrap CATALOG ...` and retain that `--config` argument in subsequent commands.
[examples/instructions-machine.toml](../examples/instructions-machine.toml) remains an optional manual equivalent.

Machine source/storage/root paths must be absolute or start with `~/`; use forward slashes in TOML Windows examples to avoid backslash escaping.
AEM also keeps ownership and recovery data beside this machine file in `/home/me/.config/agent-env-man/machine.toml.state/`.
Retain that state directory to manage, inspect, recover, and detach the installed targets.
The shared catalog does not contain this installation state.

## Install and inspect the resulting paths

These commands assume AEM is installed and on PATH, the original documents exist, and both link targets are initially absent; an existing valid hooks.json is preserved and extended:

```bash
aem bootstrap
aem apply --dry-run
aem apply
aem status
```

Bootstrap reads the bound catalog, validates the external bundle, and saves the machine binding; it does not install the document targets.
It also supplies a default `skills` root if one is absent, but no skill is installed unless declared in the catalog.
Dry-run shows all three planned targets, the hook definition and trust notice without creating them.
Apply installs the directory link, original-entry link, and then the hook registration; status inspects their state without fetching anything.
If an existing global AGENTS.md occupies the destination, ordinary apply reports a conflict rather than overwriting it.
Use the existing conflict/adoption/replacement workflow only after deciding how to preserve that content.

After successful apply:

```text
/home/me/.config/agent-env-man/machine.toml.bundles/personal
  -> /home/me/Syncthing/agent-documents/guidance     directory symlink

/home/me/.config/agent-env-man/machine.toml.bundles/personal/start.md
/home/me/.config/agent-env-man/machine.toml.bundles/personal/development/conventions.md
/home/me/.config/agent-env-man/machine.toml.bundles/personal/research/workflow.md
/home/me/.config/agent-env-man/machine.toml.bundles/personal/workspaces/project-alpha.md
/home/me/.config/agent-env-man/machine.toml.bundles/personal/references/writing.md
  All are accessible through the directory symlink; they are not extra copies.

/home/me/.codex/AGENTS.md
  -> /home/me/Syncthing/agent-documents/guidance/start.md
/home/me/.codex/hooks.json                        merged hook configuration
```

`/home/me/.codex/AGENTS.md` now reads exactly the original `start.md` contents.
No locator command is inserted into that document.
Instead, AEM appends a group like the following to `hooks.json`, keeping other events, groups and metadata:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "^(startup|resume|clear|compact)$",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/python -m agent_env_man --config /home/me/.config/agent-env-man/machine.toml agent-hook personal --agent codex",
            "timeout": 10,
            "statusMessage": "AEM instruction roots [generated-identity]",
            "additionalContextLimit": 1000
          }
        ]
      }
    ]
  }
}
```

The actual interpreter is the absolute Python executable used for installation; the marker is a stable hash of the machine file path, agent, and bundle name.
Neither value needs to be supplied in the catalog.
Keep this Python environment and its installed AEM package available; rerun apply after moving the environment to update the command.

Apply includes this notice in its JSON result:

> Codex hook trust must be reviewed separately: in the next Codex session, open /hooks, review and trust the AEM hook, then start a new session. AEM does not grant trust or enable disabled hooks.

AEM registration is not Codex approval.
Do not bypass hook trust: review the generated command in Codex before trusting it.
Codex requires review for new/changed non-managed hooks and supplies SessionStart output as extra developer context; AEM supplies only path metadata, not the personal instruction text.
See the [official hook documentation](https://learn.chatgpt.com/docs/hooks).

For the external example, the callback's `hookSpecificOutput.additionalContext` contains these location fields plus relative-reference guidance:

```json
{
  "root": "/home/me/Syncthing/agent-documents/guidance",
  "entry": "/home/me/Syncthing/agent-documents/guidance/start.md",
  "global_entry": "/home/me/.codex/AGENTS.md"
}
```

`global_entry` identifies the installed entry file to which these locations apply; the existing field name is retained for compatibility.
`entry` identifies its corresponding document location within the bundle, and `root` identifies the bundle directory.
An entry may be nested, so its parent directory need not equal `root`.
These fields describe locations, not the entry's subject matter or applicability.

The callback does not request another reading of the entry.
If its contents are already present in the agent's context, the agent should not reread them solely to establish these paths; the callback does not assume that the host has loaded them.
Relative references in the entry resolve from the parent directory of `entry`, not the installed entry's directory or the working directory.
References in supplemental documents resolve from each referring document's own directory, unless the user documents explicitly specify another base.
For example, an entry at `root/entry/start.md` resolves `../research/workflow.md` to `root/research/workflow.md`; a reference in that workflow uses `root/research` as its base.
The user documents continue to determine applicability and reading order; location metadata does not trigger a scan or reading of every file in the bundle.
The hook omits installation diagnostics: `aem locate personal` still reports `installed_root` (AEM's installed bundle path) and `detached` (bundle ownership released).
After detaching only the bundle directory, that installed path holds a preserved copy while the global entry still links to the live source; the hook continues to supply the live source's `root` and `entry` until the global entry is detached too.
The callback reads saved installation records without fetching, loading the catalog, or rewriting ownership records.
If lookup fails, it returns a structured `continue: false` stop request and visible error instead of a guessed path.
Codex cannot receive that response if the interpreter itself is missing or the hook is disabled/untrusted; verify registration and trust through `/hooks`.
Keep the machine file and state directory, including after detach.
For manual diagnostics, run `aem locate personal`.

```text
Codex loads the original instructions through ~/.codex/AGENTS.md
SessionStart hook supplies the actual bundle root and original entry path
  -> reader resolves referenced documents using those locations
  -> e.g. /home/me/Syncthing/agent-documents/guidance/development/conventions.md
```

The hook does not inspect instruction meaning or choose which auxiliary documents apply.
The presence of `workspaces/project-alpha.md` does not create an automatic workspace rule; your documents define when to read it.
No repository-local AGENTS.md is generated.
This version registers root-session events, not a separate SubagentStart hook.

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
  merged SessionStart group invoking the AEM callback
```

The generated command explicitly invokes an encoded PowerShell command on Windows and uses POSIX quoting on Linux/WSL; paths containing spaces are supported.
Tests execute the generated encoded command in native Windows PowerShell with quoted configuration paths; delivery through a real approved agent session remains a separate integration check.
AEM does not transfer the catalog or source documents between these devices.

## Changes, missing sources, and management removal

| Action or event | Links and hook behavior |
| --- | --- |
| Edit `guidance/development/conventions.md` externally | The installed path sees the edit immediately through the link. No apply is needed. Status reports a live content change relative to the last apply. |
| Run `update personal` for the external source | AEM checks that the external root exists and reports `external-no-fetch`. It does not run Syncthing or restore documents. |
| Delete an auxiliary document | That installed document disappears too. AEM does not detect broken prose references; the remaining bundle can still be valid. |
| Remove `guidance/start.md` | Apply cannot validate the entry, and status reports the bundle unavailable. The directory link remains and the global entry link breaks; the hook reports lookup failure. |
| Remove or temporarily disconnect the whole external source | Both installed links break and the registered hook reports lookup failure. Restore the source before detaching so AEM can preserve its contents. |
| Delete `[instructions.personal]` from the catalog | Existing targets and ownership remain. This is not an uninstall command. |
| Write through the global AGENTS.md link | The original entry changes immediately. Replace the link with a regular file to keep a separate local edit; apply then reports a conflict. |
| Detach bundle and entry | AEM materializes both links, releases their ownership and the associated hook ownership, and retains hook configuration for continued root discovery. |
| Edit/remove the AEM hook group | Ordinary apply reports a conflict. Explicit replacement restores only the owned group and preserves other hooks. |

To detach the example:

```bash
aem detach personal:bundle personal:entry
```

The same locator command now returns `/home/me/.config/agent-env-man/machine.toml.bundles/personal` as `root` and its `start.md` as `entry`, with `detached: true`.
It uses the saved installation record even if the catalog or original source is gone.
Later edits in the external source no longer affect this copy.
Ordinary apply skips all detached items; explicit reattachment is needed to manage them again.
Detach preserves instructions and the registered hook for continued use; it does not disable them or restore a global AGENTS.md from before installation.
Disable the retained hook through Codex `/hooks` if you no longer want it to execute.

`bootstrap --item personal` selects the whole source for preparation.
`apply --item personal:entry` includes the bundle and hook automatically; explicit `personal:hook` selection also includes both links.
`personal:bundle` alone installs only the directory link for staged preparation.
Detach uses the two link ownership IDs without `--item` and includes the saved hook record automatically when detaching the entry.
Transactions are per target, so links and hook configuration are not one atomic installation.
If hook installation fails after the links were installed, recovery restores the previous hook file; retry apply after fixing the error.
For an existing global entry, use `apply --item personal:entry --replace`; also select `personal:bundle` if an existing bundle destination intentionally needs replacement.
An implicitly selected bundle never gains replacement permission.
If you detach only the directory while leaving the global entry linked, the hook continues to report the live original root for that entry; detach both links for an independent local copy.

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
To manage both kinds of content together, use [examples/combined-catalog.toml](../examples/combined-catalog.toml), which adds:

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
| `personal:hook` | `/home/me/.codex/hooks.json` | One owned SessionStart group; unrelated hooks are preserved |

The skill is not a prerequisite for the instruction bundle; they simply share one inventory and the same management commands.

## Existing installations

Explicit `install.bundle.root` and `install.bundle.destination` settings remain supported; retaining their values avoids relocating an existing installation.
For example, `install.bundle.root = "rules"`, `install.bundle.destination = "personal"`, and machine `roots.rules = "/home/me/.agent-rules"` retain the earlier destination.
Removing those fields from an installed bundle can change its target path, so detach and deliberately reattach if you want to move to the default.
For old catalogs, follow the [catalog v2 transition](removed-interfaces.md#catalog-v2-transition).
Older state and generated-guide installations are not upgraded in place; follow [Removed interfaces](removed-interfaces.md) before installing the current version.

## Validation performed

The offline tests cover bootstrap/preview without registration, exact original-entry links, preserved unrelated hooks, idempotence, local edits, failed writes and recovery, detached copies, missing sources, and command quoting.
Native Windows tests also execute the generated hook in PowerShell and verify literal-path shell navigation in temporary environments.
Delivery into a real approved model session remains unverified.

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
