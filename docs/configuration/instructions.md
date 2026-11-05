# Instruction bundle configuration

Catalog `instructions.NAME` declarations select a document bundle, its global entry, and installation destinations.
This reference defines their fields and ownership; the [instruction walkthrough](../instruction-bundles.md) provides installation steps.

## Declaration fields

Each instruction declaration selects the source bundle and its installation settings.

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name of a Git or external source in `sources`; a used external source requires a machine path binding. |
| `exclude` | Array of strings | Additional [payload exclusions](payload.md#payload-exclusions); defaults to `[]`. |
| `subdir` | String | Bundle directory under the source; defaults to `"."`. |
| `entry` | String | Required relative path to a regular entry document inside the selected bundle directory. |
| `install` | Table | Optional `bundle` and `entry` tables defined in this section. |

`install.bundle` accepts optional `root`, `destination`, `mode` (`"link"` by default, or `"copy"`), and Boolean `shared` (`false` by default).
Machine `modes.NAME` overrides the bundle mode; the global entry always remains a link.

- `root` names a machine root for bundle installation; omission uses `<machine-file>.bundles`.
- `destination` is a relative bundle destination and defaults to the instruction name.
- `install.entry` accepts only optional `root` and `destination`.
- `root` names a machine root for the global entry and hook file; omission uses selected agent roots.
- `destination` is a relative global entry destination and defaults to the agent's entry filename (`AGENTS.md` for Codex).

## Shared installation

Set `install.bundle.shared = true` to install one bundle for all agents selected by the declaration.
Its target uses the unsuffixed `destination` under the chosen bundle root; its ownership ID is always `NAME:bundle`.
Without this option, each agent keeps its separate bundle target and ownership.
An explicit `install.entry.root` still selects only one agent, even with sharing enabled.

Each agent retains its own global entry link, hook group, and entry/hook ownership IDs.
Both link and copy modes point these entries through the shared bundle, so their reading trees stay consistent after bundle detach.
Named instances participate like the default agent destinations.
`publish --from-copy` collects the shared copy once.
The [shared-copy example](../instruction-bundles/variants.md#share-one-copy-between-agents) shows setup and transition steps.

Applying through one agent can refresh content used by every consumer of the shared bundle.
Detach the shared bundle without `--agent` to release all consumers; individual entries can still be detached independently.
Full automation skips the shared instruction group when any component is detached.
Changing the sharing setting on an existing installation requires explicit detach and reattachment; AEM preserves old copies instead of merging their edits.

## Installation and ownership

An explicit `install.entry.root` selects one destination; without it at least one machine agent must be selected.
Bootstrap supplies `roots.agent`, but an instruction declaration must either refer to it or use an agent binding.
Codex and Claude use their respective entry filenames and hook formats.

An instruction creates `NAME:bundle`, `NAME:entry`, and `NAME:hook` ownership IDs.
A linked bundle exposes the original entry; a copied bundle links the global entry to the installed copy.
The hook owns one agent-specific group under the entry root and resolves the same installed reading tree.

Copied bundles stay usable without their external source; explicit apply refreshes them while protecting local edits.
Instruction-specific automatic policies are not supported.
Explicitly selected full device automation may prepare, update, and apply instruction bundles, while preserving detached groups.
Changing a managed source path, target path, or mode requires detach before reconfiguration.
AEM does not interpret document contents, reading order, or applicability.
See the [instruction walkthrough](../instruction-bundles.md) and [catalog v2 transition](../removed-interfaces.md#catalog-v2-transition).
