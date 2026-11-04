# Settings command reference

Settings commands receive, edit, apply, export, and resolve staged application fields.
Collection from the actual application and publication to a shared source remain explicit.

## Staged settings commands

`bootstrap --setting-target NAME=PATH` prepares a setting stage and binds the actual application file.
`update NAME` receives shared settings changes; `apply --item NAME` applies the stage; explicit sync updates then applies.
Settings have independent per-item automatic sync policies and participate by default in full automation; collection, export, and publication remain explicit.
See [settings automation](../settings-management/automation.md) for schedules and exclusions, and [settings conflicts](../settings-management/conflicts-and-recovery.md) for conflict behavior.

| Command | Behavior |
| --- | --- |
| `locate NAME [--source \| --target] [--repo]` | Stage by default, shared source or actual target explicitly; `--repo` selects the source Git checkout root and cannot accompany `--target`; `--cd` returns the selected directory. |
| `export NAME... [--dry-run]` | Merge stages into Git/external sources without network access. |
| `settings prepare NAME [--dry-run]` | Initialize from a prepared source, preserving existing stage edits. |
| `settings collect NAME [--path JSON_ARRAY]... [--dry-run]` | Collect managed actual edits; explicitly select new fields. |
| `settings release NAME --path JSON_ARRAY [--dry-run]` | Prepare field ownership release without deleting the actual value. |
| `settings resolve NAME --path JSON_ARRAY --take local\|shared\|edited [--dry-run]` | Resolve shared conflicts by field or overlapping structural group. |

Git `publish NAME...` includes export for selected settings and retains whole-checkout commit/push behavior; external publication remains unsupported.
`publish --dry-run` reports planned export changes offline.
Settings export reports `setting`, `status`, `changed` (source bytes would change), and `paths` (semantic operation changes as string arrays).
Setting publish reports add `export` and `unpublished_settings`; ordinary publication reports may include an empty `unpublished_settings` list.
Collection reports changed `paths`; release reports its `path`; resolve reports `remaining` conflicts.

Global JSON, exit-code, locking, explicit replacement, and preview contracts remain applicable.
Operational conflicts exit 1; malformed CLI paths and mutually exclusive locate options exit 2 before file access.
See [Staged settings](../settings-management.md) for complete behavior, locate/status fields, intent metadata, and recovery.
