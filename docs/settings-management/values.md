# Settings stages, values, and intent

This reference defines stage storage, field ownership, format-specific comparison, and persistent deletion or release intent.
Use the [settings guide](../settings-management.md) for the editing and sharing workflow.

## Stage storage and ownership

Bootstrap prepares the source and initializes `<machine-file>.stages/editor/config.toml` (or `config.json`) and `management.toml` without writing the application file.
`settings prepare NAME [--dry-run]` also initializes a stage from an already prepared source, with no cloning or binding changes.
Existing stages retain edits and require an explicit update to receive shared changes.

- A file has at most one AEM setting owner, although that owner manages only its declared fields.
- **Shared hook file**: Claude's `settings.json` can also contain AEM setup and instruction hook groups.
  A JSON setting may share that exact file with Claude hook integrations, but cannot manage the top-level `hooks` field or any of its descendants, including deletion or release metadata.
  Setup and settings preserve each other's fields; two settings owners still cannot share a target.
  Overlapping directory targets remain rejected.
- Removal validates the saved hook group and settings ownership without requiring the current agent profile or reading the editable settings stage.
- Targets and stage storage must not overlap sources, catalog storage, AEM state, or other managed targets.
- Symlinks, junctions, redirected ancestry, and special files are rejected.
- Changing the source, target, or format of an active item requires detach first.

## Choose the editing location

Default locate for settings always identifies the stage; a missing or damaged stage never silently redirects to another location.
`--source` and `--target` are mutually exclusive.
Saved stage and target locations remain available without the catalog, including after detach.
The target path may be reported before the application file exists.
Locate reports `root`, `entry`, `metadata` (null for the actual file), `location` (`stage`, `source`, or `target`), `prepared`, and `detached`.
`--cd` prints the root directory and retains the existing shell integration semantics.

## TOML values and deletion intent

Edit the reported stage entry (`config.toml` or `config.json`) to prepare added or changed values.
Removing a previously managed field prepares a deletion; AEM records the deletion in metadata on the next successful stage operation, apply, or export.
Arrays, including arrays of tables, and empty tables are managed as complete values.
Ordinary tables expose individual leaves.
Quoted keys containing dots remain distinct from nested keys.
TOML types remain distinct during comparison, including integer versus float and boolean, dates, times, and special float values.
Physical LF and CRLF newlines in TOML multiline strings compare equally across shared sources, stages, actual settings, and saved comparison snapshots, including strings inside arrays and tables.
Explicit carriage-return escapes such as `\r` and `\u000D` remain meaningful string content and are not normalized.
Comparison does not rewrite the original TOML tokens or snapshot formatting.

## JSON values

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

JSON values follow these format and comparison rules:

- **Objects**: JSON files must contain one top-level object, with unique keys in every nested object, including inside arrays.
  Comments, trailing commas, `NaN`, and `Infinity` are unsupported; JSONC is not accepted.
- **Empty targets**: An existing empty or whitespace-only file is invalid, while a missing target is initialized as an empty object before applying fields.
- **Field boundaries**: Nonempty objects expose their leaves; arrays and empty objects are atomic values.
- **Null**: `null` is a value, distinct from deleting or releasing a field.
- **Paths**: Literal dotted keys, empty keys, and escaped keys use the same string-array path selection as TOML.
- **Numbers**: Numbers compare by exact numeric value: `1`, `1.0`, and `1e0` are equal, as are signed and unsigned zero, while `true` is distinct from `1`.
  Numeric tokens are retained without binary floating-point conversion, preserving large integers and precise decimal values.
- **Order**: Object key order is ignored for comparison; array order remains meaningful.

## Shared intent metadata

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
