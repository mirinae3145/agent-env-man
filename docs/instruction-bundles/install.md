# Install an external instruction bundle

This walkthrough installs a linked instruction bundle from an existing external folder on Linux/WSL.
It assumes AEM is installed, the source files exist, and the entry and bundle destinations are initially absent.
The catalog and machine filenames are examples; AEM selects them through bindings and `--config`.

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

Save [examples/instructions.toml](../../examples/instructions.toml) as `/home/me/ai-config/instructions.toml`:

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

The catalog fields select the source, bundle, and installation destinations:

| Field or table | How AEM interprets this example |
| --- | --- |
| `version = 2` | Selects catalog schema version 2. It is not the document bundle's version. |
| `[sources.personal-documents]` | Declares a logical external source named `personal-documents`. Set `type = "external"`; its actual path belongs in machine configuration. It neither creates the source directory nor configures synchronization. |
| `[instructions.personal]` | Registers a bundle named `personal`. This name identifies the source in commands and produces ownership IDs `personal:bundle`, `personal:entry`, and `personal:hook`. It does not automatically choose the installed directory name. |
| `source = "personal-documents"` | Looks up `external_paths.personal-documents` in machine configuration to find the source root. For a Git source, reference a source declared with `type = "git"`, as shown in the [Git variant](variants.md#use-git-for-the-instruction-source-instead). |
| `subdir = "guidance"` | Appends `guidance` to the source root, selecting `/home/me/Syncthing/agent-documents/guidance`. Omit it or use `"."` to select the entire source root. |
| `entry = "start.md"` | Selects the original file inside that bundle: `/home/me/Syncthing/agent-documents/guidance/start.md`. This is the link source, not the global destination filename. |
| `install.bundle.root` (omitted) | AEM chooses `/home/me/.config/agent-env-man/machine.toml.bundles` beside the machine file. No `roots.rules` setting is needed. An explicit value can still select a configured machine root. |
| `install.bundle.destination` (omitted) | Defaults to the bundle name `personal`, producing `/home/me/.config/agent-env-man/machine.toml.bundles/personal`. An explicit relative path can override it. |
| `install.entry.root = "agent"` | Looks up the Codex home base `roots.agent`, here `/home/me/.codex`. The name `agent` is a lookup key; hook registration uses `hooks.json` in this directory. |
| `install.entry.destination = "AGENTS.md"` | Appends this filename to the entry base. AEM links `/home/me/.codex/AGENTS.md` directly to the original `guidance/start.md`; its text remains unchanged. |

`subdir`, `entry`, `install.bundle.destination`, and `install.entry.destination` use literal `/`-separated relative paths, not shell expressions.
Traversal such as `../` and absolute paths are rejected; only `subdir` permits `.`.
The three installed targets must not overlap: the entry and `hooks.json` must be outside the directory owned by `personal:bundle`.
Each instruction bundle owns its marked event groups in the hooks file; unrelated registrations remain intact.

## Bootstrap arguments and saved machine configuration

Register the catalog and this device's external folder directly:

```bash
aem bootstrap /home/me/ai-config/instructions.toml --external personal-documents=/home/me/Syncthing/agent-documents
```

No machine file needs to be prepared first.
The positional argument selects the local catalog; `--catalog PATH` is an equivalent spelling.
Repeat `--external NAME=PATH` for each external source that needs a binding.
The name must be declared in `[sources.NAME]` with `type = "external"`; the path is expanded for `~` and resolved relative to the command's working directory before being saved as an absolute path.
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

The generated machine fields bind those declarations to this device:

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
[examples/instructions-machine.toml](../../examples/instructions-machine.toml) remains an optional manual equivalent.

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

## Installed tree

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

## Review trust and verify locations

AEM registration does not grant Codex hook trust.
After installation, complete these steps:

1. Open `/hooks` in the next Codex session and review and trust the registered AEM commands.
1. Start a new session so the approved hooks can supply the reading locations.
1. Run `aem locate personal` to inspect the saved bundle and entry locations if reading-location metadata is missing.

The [hook reference](locations.md) describes generated groups, callback fields, and diagnostic behavior.
For Windows, Git sources, and copy mode, use the [installation variants](variants.md).
