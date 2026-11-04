# Staged application settings

AEM can manage selected fields in application settings independently of its own machine configuration.
Supported file formats are TOML and strict JSON objects.
Settings use an editable local stage instead of linking an application's entire configuration to a shared source.
Explicit commands can receive, collect, apply, export, or publish settings changes.
Automatic settings sync receives shared changes and applies the stage; collection, export, and publication remain explicit.

```text
shared repository/folder <-> prepared source <-> editable stage <-> actual settings
                           update / export                  apply / collect
                           Git publish: export, commit, push
```

## Declare and prepare

Add a setting to your catalog:

```toml
version = 2

[sources.preferences]
type = "git"
repository = "https://example.com/me/preferences.git"

[settings.editor]
source = "preferences"
path = "editor.toml"
format = "toml"
```

Names are unique across skills, instructions, and settings.
The required `path` is a literal source-relative file path using `/`; `format` accepts `toml` or `json`.
Git settings must be tracked regular UTF-8 files.
An external source uses `type = "external"` with a machine `--external preferences=PATH` binding instead of a repository declaration.
The catalog declares the shared content; the machine binds the actual application file:

```bash
aem bootstrap /absolute/catalog.toml --setting-target editor=/absolute/app/config.toml
```

`--setting-target` is repeatable and requires an absolute path (or `~/...`).
Omitted bindings retain their saved values.
The corresponding machine table is:

```toml
[settings.editor]
target = "/absolute/app/config.toml"
```

To associate a setting with a named destination, add `agent = "claude-lab"` to its machine binding.
The active destination must be configured, and the target must be inside its root.
`apply --agent claude-lab` selects its associated settings and excludes unbound settings.
Existing invocations without an agent selector or with the original product selectors retain the unbound-setting behavior.
Use distinct catalog setting names sharing one source/path/format for independent stages and targets; see [named instances](agent-instances.md#independent-settings-from-one-source).

## Edit, apply, and share

Edit the stage to prepare desired values, then apply locally and publish only when ready to share.

1. Locate the editable stage with `aem locate editor` and edit its `config.toml` or `config.json`.
   Removing a managed field requests deletion; use explicit release to leave its actual value unmanaged.
1. Preview with `aem apply --item editor --dry-run`, then run `aem apply --item editor` to use the staged values locally.
1. To share changes without Git publication, preview `aem export editor --dry-run`, then run `aem export editor`.
1. To export, commit, and push to Git, run `aem publish editor -m "Update editor preferences"`.
   Review the entire selected repository because publication includes changes outside the setting.

For other editing locations, use `aem locate editor --source`, `--target`, or `--cd` as described in [stage lookup](settings-management/values.md#choose-the-editing-location).
The [value reference](settings-management/values.md) defines TOML/JSON comparison, storage, ownership, and deletion/release metadata.
The [reception and automation guide](settings-management/automation.md) explains receiving shared changes and configuring per-setting schedules.

### Apply to the application

Apply consumes the stage without fetching, exporting, or collecting application changes.
It preserves nonmanaged fields and their comments, preserves existing file permissions and line endings, and avoids rewriting semantically unchanged values.
Formatting within changed nodes can change.
JSON edits preserve untouched value tokens and key order, changing only the selected values and necessary punctuation or separators.
Semantically unchanged JSON targets retain their original bytes, including numeric spelling and string escapes.
New JSON targets use two-space indentation and a final newline; inserted members in existing objects follow their indentation when available.
A missing application file is created; deleting all managed fields leaves a file rather than deleting it.
Initial identical values and already absent deletion targets are adopted automatically.
Different existing values require `aem apply --item editor --replace`; replacement is limited to managed fields.
Even explicit replacement cannot remove unmanaged descendants during a table/scalar transition.

### Export and publish

If several selected stages share one source file, identical exports are grouped and differing exports are rejected before any write.
Export merges the stage with the current shared source and writes the source settings plus metadata without network access.
It works for both Git and external folders.
External synchronization remains the responsibility of its existing service; external `publish` remains unsupported.
Git publish includes export and then uses AEM's existing whole-repository commit and push semantics.
A message is required if export would change either source file or the checkout already has uncommitted changes.
Publication never implicitly collects actual application settings.
Git behind/diverged history must be reconciled before publication; AEM does not merge Git histories or reset local work.
Failed publication preserves successful local exports and commits for retry.
Unselected settings with unexported stage changes in a published checkout are listed under `unpublished_settings` and are not exported implicitly.

## Collect, delete, and release

Collect actual application edits into the stage, or release field ownership while leaving the actual value in place.
The commands illustrate separate choices; releasing a field is not a required step after collection.

```bash
aem settings collect editor --dry-run
aem settings collect editor
aem settings collect editor --path '["appearance","theme"]'
aem settings release editor --path '["appearance","theme"]'
```

### Collect application edits

Collect compares actual values with the last applied state and the stage.
It collects only existing managed fields; new fields require repeatable `--path` selections.
Paths are nonempty JSON arrays of strings, so `["a.b"]` and `["a","b"]` have different meanings.
Explicit collection also reclaims a previously deleted or released field if it exists in the actual file.
A missing actual file is an error for collection; a missing managed field in an existing file is a deletion candidate.
Conflicting stage and actual edits abort collection without writing the stage.

### Release field ownership

Release is an explicit change in ownership, not a deletion.
It removes the field from the desired values and records `released`; apply leaves the current actual value untouched even if the user changed it.
A released field is excluded from subsequent collection unless explicitly selected.
To restore management manually, remove its deletion/release record and add the desired value to the stage; alternatively collect that actual field explicitly.

## Conflicts, status, and recovery

Shared-source and application conflicts use separate comparison bases and preserve the conflicting edits.

### Resolve shared conflicts

| Merge | Comparison inputs | Conflict effect |
| --- | --- | --- |
| Shared reception/export | Last accepted shared state, current stage, and incoming source. | Saved separately from the valid stage; blocks apply/export/publish until resolved. |
| Application | Last applied state, current actual settings, and stage. | Aborts the whole application-file operation. |

One-sided changes and identical concurrent changes merge.
Different edits, deletion versus modification, and overlapping structural changes conflict.
Resolve a saved shared conflict explicitly:

```bash
aem settings resolve editor --path '["color"]' --take local
aem settings resolve editor --path '["color"]' --take shared
# Or edit the stage, then explicitly accept the edited result:
aem settings resolve editor --path '["color"]' --take edited
```

A structural conflict resolves all connected overlapping paths together.
`--take edited` validates the edited stage and explicitly acknowledges that choice.
Commands report conflict paths without embedding configuration values in ordinary diagnostics.

### Status and detach

Setting item IDs are `NAME:settings`; `--item NAME` also selects the item.
Status reports `not-prepared`, `prepared`, `managed`, `conflict`, `detached`, or `unavailable`, plus `conflicts`, `unpublished`, `unexported`, and (after apply) `unapplied` and `modified_locally` where available.
`unpublished` compares against the last received or successfully published shared state; for external folders export updates that local shared baseline without claiming synchronization completed.
Git source status separately reports uncommitted changes and outgoing commits.

`detach NAME` preserves actual settings and all stage edits, including a prepared item that has never been applied.
It releases management locally and does not publish a field release.
Reattach requires explicit `apply --item NAME --reattach`, with `--replace` if the new target conflicts.
Saved location, detach, and recover work without the catalog.

### Previews and grouped recovery

All stage-editing commands, apply, export, resolve, and publish offer `--dry-run`; previews do not normalize or save metadata, write state, or contact Git publication remotes.
Update itself retains the existing networked delivery command behavior.

Related settings/metadata writes and comparison-state updates use one grouped recovery journal.
Writes are checked against their read observations, and actual application writes are committed as whole files.
After an interrupted group, subsequent operations are blocked until `aem recover` restores the previous group.
Recovery validates every member before restoring any and refuses to overwrite later user edits.
Backups are retained alongside their files after successful writes.
Different application files retain AEM's per-target transaction boundary; a later failure does not undo earlier successful items.
Native Windows behavior and power-loss guarantees require separate platform evidence.
