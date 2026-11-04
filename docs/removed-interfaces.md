# Removed interfaces and existing installations

The catalog is now the only content declaration format.
This is a breaking cleanup for installation: there is no legacy source parser, command alias, or automatic conversion.
Saved ownership remains available for maintenance without restoring legacy installation semantics.

| Removed interface | Current approach |
| --- | --- |
| Source-local `links.conf` (four or six fields) and machine `[sources]` | Catalog `skills`, `instructions`, and named `sources`. |
| `bootstrap NAME --path`, `--git`, `--branch`, `--manifest`, `--attach` | `bootstrap CATALOG`; put Git declarations in the catalog and external bindings in machine configuration or `--external`. |
| `codex-merge` JSON declarations and leaf-key ownership | Use the independent [staged settings](settings-management.md) catalog workflow for selected TOML or JSON fields; legacy declarations and ownership are not converted or accepted. |
| `codex-hook NAME` | `agent-hook NAME --agent codex`; new instruction hooks use this command. |
| `sync --min-interval` and the configuration-wide attempt clock | Per-skill catalog policies and `auto --trigger EVENT`. Explicit sync is unthrottled. |
| Generated instruction guides and their in-place upgrade | Direct links to original entry documents, plus location hooks. |
| Installing/updating through state version `1` | New installations require state version `2`; maintenance can release version-1 ownership without converting it. |

Catalog TOML requires version `2`; machine TOML remains version `1` and installation state remains version `2`.
Installation/update commands reject machine `[sources]` even when empty and reject unknown machine fields.
Maintenance ignores unrelated declarations and preserves them.
Explicit catalog installation roots and `bootstrap --catalog` remain supported.
Direct skill repository declarations and the catalog `repositories`/`externals` tables are removed.

## Catalog v2 transition

Old catalogs are rejected by installation and update commands with a transition diagnostic.
There is no automatic conversion tool.
Saved-state locate, detach, recover, and offline status remain usable with an old or unavailable catalog.
Do not edit machine/state version markers, delete ownership records, or restore machine `[sources]` or source-local `links.conf`.

1. Back up the catalog, machine file, state, and source content.
1. For existing named Git sources, replace `repositories.NAME` with `sources.NAME` and add `type = "git"`.
Replace empty `externals.NAME` tables with `sources.NAME` and `type = "external"`; keep their machine `external_paths.NAME` bindings.
If Git and external names collide, rename the Git source and its item references first to preserve the external binding.
A Git source rename changes its checkout path and therefore requires the detach procedure below.
1. Replace item `repo` or `external` with `source`.
Move skill `root`/`mode` under `install`, instruction `root`/`destination` under `install.bundle`, and `entry_root`/`entry_destination` to `install.entry.root`/`install.entry.destination`.
Keep instruction `entry` relative to its selected `subdir` and skill entry files named `SKILL.md`.
1. Replace every catalog trigger string with an event array; replace `"manual"` or `["manual"]` with `[]`.
Set catalog `version = 2` after updating its declarations.
Machine update policies retain their existing string/array syntax.
1. When source names, item names, paths and modes stay the same for named sources, preview and apply without detaching; their checkout paths and ownership records are retained.

For old direct-declaration skills or any installation whose source/target path or mode changes:

1. Use saved-state status/locate and detach the affected item IDs before reconfiguration.
Detach materializes linked contents and preserves modified copies.
1. Register each former direct skill under its own independent Git source name; equal URLs do not imply sharing.
Keep any old checkout in place and run bootstrap to prepare the new named checkout.
1. Preview apply, then explicitly reattach detached items and authorize replacement only for selected preserved targets that need it, for example `aem apply --item report --reattach --replace`.
Inspect backup and conflict reports before continuing.

AEM never automatically deletes or moves old checkouts, state, detached contents, or replacement backups.
Editing the catalog does not itself create a package release or Git tag.
See the [configuration reference](configuration/catalog.md#catalog) for the complete grammar.

## Before upgrading an existing installation

Use current AEM maintenance commands against the old machine file:

```bash
aem --config /path/old-machine.toml status
aem --config /path/old-machine.toml recover
aem --config /path/old-machine.toml detach ITEM_ID ...
aem --config /path/old-machine.toml setup --remove-shell bash --remove-agent codex
```

Inspect status for saved IDs and run recovery only when a replacement is pending.
Detach the relevant managed content before removing its agent integration.
Removal-only setup accepts saved integration names even if the current build no longer ships their profiles.
It does not refresh remaining integrations and does not require the old executable to exist.
Disable/remove retained old instruction hooks through the agent's hook controls.
Detach preserves contents; it does not disable retained instruction hooks.
Keep a backup of the old machine file and state together, along with source contents and target backups.

Prepare a new machine configuration and state location with the current catalog format.
Preserved old targets remain unmanaged conflicts: inspect them, move them aside, or explicitly adopt matching content/replace selected targets with backups.
Run bootstrap, preview apply, then apply and review new hook trust.
The new build does not clean old checkouts, delete preserved targets, or automatically adopt them.
Maintenance preserves the old state's version and unknown fields, so releasing everything does not convert it into a current installation state.
Only the known version-1/version-2 ownership envelope and per-target journal format are accepted; unknown versions and incomplete/unsafe journals still require the matching tool or manual reconciliation.

Do not edit the old state's version number or delete its ownership records to force acceptance.
If an old hook still invokes `codex-hook`, the removed command will return a CLI usage error until that registration is replaced.
This repository cleanup does not modify an installed AEM tool, live machine configuration, shell profile, or agent home.
