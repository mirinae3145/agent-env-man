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

Bootstrap prepares the source and initializes `<machine-file>.stages/editor/config.toml` (or `config.json`) and `management.toml` without writing the application file.
`settings prepare NAME [--dry-run]` also initializes a stage from an already prepared source, with no cloning or binding changes.
Existing stages retain edits and require an explicit update to receive shared changes.
A file has at most one AEM setting owner, although that owner manages only its declared fields.
Claude's `settings.json` can also contain AEM setup and instruction hook groups.
A JSON setting may share that exact file with Claude hook integrations, but cannot
manage the top-level `hooks` field or any of its descendants, including deletion
or release metadata. Setup and settings preserve each other's fields; two settings
owners still cannot share a target. Overlapping directory targets remain rejected.
Removal validates the saved hook group and settings ownership without requiring the current agent profile or reading the editable settings stage.
Targets and stage storage must not overlap sources, catalog storage, AEM state, or other managed targets.
Symlinks, junctions, redirected ancestry, and special files are rejected.
Changing the source, target, or format of an active item requires detach first.

## Edit, apply, and share

```bash
aem locate editor                        # Editable stage; entry and metadata paths.
aem locate editor --source               # Shared source for inspection or direct edits.
aem locate editor --target               # Actual application file.
aem locate editor --cd                   # Stage directory through shell integration.
aem apply --item editor --dry-run
aem apply --item editor
aem export editor --dry-run
aem export editor
aem publish editor -m "Update editor preferences"
```

Default locate for settings always identifies the stage; a missing or damaged stage never silently redirects to another location.
`--source` and `--target` are mutually exclusive.
Saved stage and target locations remain available without the catalog, including after detach.
The target path may be reported before the application file exists.
Locate reports `root`, `entry`, `metadata` (null for the actual file), `location` (`stage`, `source`, or `target`), `prepared`, and `detached`.
`--cd` prints the root directory and retains the existing shell integration semantics.

Edit the reported stage entry (`config.toml` or `config.json`) to prepare added or changed values.
Removing a previously managed field prepares a deletion; AEM records the deletion in metadata on the next successful stage operation, apply, or export.
Arrays, including arrays of tables, and empty tables are managed as complete values.
Ordinary tables expose individual leaves.
Quoted keys containing dots remain distinct from nested keys.
TOML types remain distinct during comparison, including integer versus float and boolean, dates, times, and special float values.
Physical LF and CRLF newlines in TOML multiline strings compare equally across shared sources, stages, actual settings, and saved comparison snapshots, including strings inside arrays and tables.
Explicit carriage-return escapes such as `\r` and `\u000D` remain meaningful string content and are not normalized.
Comparison does not rewrite the original TOML tokens or snapshot formatting.

For a JSON setting, declare the application's file using the same catalog and target binding workflow:

```toml
[settings.assistant]
source = "preferences"
path = "assistant.json"
format = "json"
```

```bash
aem bootstrap --setting-target assistant=/absolute/app/settings.json
```

JSON files must contain one top-level object, with unique keys in every nested object, including inside arrays.
Comments, trailing commas, `NaN`, and `Infinity` are unsupported; JSONC is not accepted.
An existing empty or whitespace-only file is invalid, while a missing target is initialized as an empty object before applying fields.
Nonempty objects expose their leaves; arrays and empty objects are atomic values.
`null` is a value, distinct from deleting or releasing a field.
Literal dotted keys, empty keys, and escaped keys use the same string-array path selection as TOML.
Numbers compare by exact numeric value: `1`, `1.0`, and `1e0` are equal, as are signed and unsigned zero, while `true` is distinct from `1`.
Numeric tokens are retained without binary floating-point conversion, preserving large integers and precise decimal values.
Object key order is ignored for comparison; array order remains meaningful.

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

Apply and publication are independent: apply before publishing to try a change locally, or publish without applying here.
`update editor` receives shared changes into the stage but does not apply them.
`sync --item editor` updates sources and applies selected content only after successful delivery.
Settings have a separate per-item automatic policy, independent of skill policies:

```toml
[settings.editor.update]
trigger = ["agent-start", "interval"]
min_interval = 600
timeout = 30
```

In `policies` mode the omitted trigger defaults to `[]`; configure events to opt in.
Settings always receive and then apply as one sync workflow; there is no check-only or receive-only automatic action.
The policy accepts only `trigger`, `min_interval`, and `timeout`, and does not inherit skill defaults or named policies.
Automatic policy runs require a prepared stage, persist attempts before delivery, and throttle failures as well as successes.
Previews remain offline and do not write stages, actual files, or attempt records.
Full automation prepares, receives, and applies settings by default, using its shared schedule; explicit `trigger = []` and detached items remain excluded.
Git and external settings use the same workflow, while synchronization of an external folder remains outside AEM.
A shared reception failure or conflict stops application; actual-file conflicts preserve the actual file and require explicit resolution or replacement.
Successful reception remains in the stage if application fails; this workflow does not promise rollback across reception and application.
Collection, export, publication, and reattachment are never automatic.
Another item sharing the same Git checkout can advance its source files without receiving or applying an unselected setting.

## Collect, delete, and release

```bash
aem settings collect editor --dry-run
aem settings collect editor
aem settings collect editor --path '["appearance","theme"]'
aem settings release editor --path '["appearance","theme"]'
```

Collect compares actual values with the last applied state and the stage.
It collects only existing managed fields; new fields require repeatable `--path` selections.
Paths are nonempty JSON arrays of strings, so `["a.b"]` and `["a","b"]` have different meanings.
Explicit collection also reclaims a previously deleted or released field if it exists in the actual file.
A missing actual file is an error for collection; a missing managed field in an existing file is a deletion candidate.
Conflicting stage and actual edits abort collection without writing the stage.

Release is an explicit change in ownership, not a deletion.
It removes the field from the desired values and records `released`; apply leaves the current actual value untouched even if the user changed it.
A released field is excluded from subsequent collection unless explicitly selected.
To restore management manually, remove its deletion/release record and add the desired value to the stage; alternatively collect that actual field explicitly.

Shared intent is stored next to the settings file as `<filename>.aem.toml`:

```toml
version = 1
deleted = [["obsolete","option"]]
released = [["local","path"]]
```

Initial metadata may be absent, meaning empty intent lists.
A settings value, deletion, or release cannot overlap another declaration at the same or an ancestor/descendant path.
Records persist until explicitly changed, allowing new devices and long-offline devices to receive deletions and ownership releases.
A source edit that removes a previously received field is also interpreted as deletion; export materializes its metadata so devices without that history can receive the intent.
Publish the settings file and metadata together.
AEM propagates current state and persistent intent, not a replay of every intermediate edit.

## Conflicts, status, and recovery

Shared merges compare the last accepted shared state, current stage, and incoming source.
Application merges compare the last applied state, current actual settings, and stage.
One-sided changes and identical concurrent changes merge; different edits, deletion versus modification, and overlapping structural changes conflict.
A conflict in an actual file aborts the whole file operation.
A shared conflict is saved separately from the valid editable settings file and blocks apply/export/publish until resolved:

```bash
aem settings resolve editor --path '["color"]' --take local
aem settings resolve editor --path '["color"]' --take shared
# Or edit the stage, then explicitly accept the edited result:
aem settings resolve editor --path '["color"]' --take edited
```

A structural conflict resolves all connected overlapping paths together.
`--take edited` validates the edited stage and explicitly acknowledges that choice.
Commands report conflict paths without embedding configuration values in ordinary diagnostics.

Setting item IDs are `NAME:settings`; `--item NAME` also selects the item.
Status reports `not-prepared`, `prepared`, `managed`, `conflict`, `detached`, or `unavailable`, plus `conflicts`, `unpublished`, `unexported`, and (after apply) `unapplied` and `modified_locally` where available.
`unpublished` compares against the last received or successfully published shared state; for external folders export updates that local shared baseline without claiming synchronization completed.
Git source status separately reports uncommitted changes and outgoing commits.

`detach NAME` preserves actual settings and all stage edits, including a prepared item that has never been applied.
It releases management locally and does not publish a field release.
Reattach requires explicit `apply --item NAME --reattach`, with `--replace` if the new target conflicts.
Saved location, detach, and recover work without the catalog.

All stage-editing commands, apply, export, resolve, and publish offer `--dry-run`; previews do not normalize or save metadata, write state, or contact Git publication remotes.
Update itself retains the existing networked delivery command behavior.

Related settings/metadata writes and comparison-state updates use one grouped recovery journal.
Writes are checked against their read observations, and actual application writes are committed as whole files.
After an interrupted group, subsequent operations are blocked until `aem recover` restores the previous group.
Recovery validates every member before restoring any and refuses to overwrite later user edits.
Backups are retained alongside their files after successful writes.
Different application files retain AEM's per-target transaction boundary; a later failure does not undo earlier successful items.
Native Windows behavior and power-loss guarantees require separate platform evidence.
