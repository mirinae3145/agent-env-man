# Collect and release settings

This reference defines how actual application edits are collected into the stage and how a field's ownership is released while its actual value stays in place.
Use the [settings guide](../settings-management.md) for the editing and sharing workflow.

## Choose collection or release

Collect actual application edits into the stage, or release field ownership while leaving the actual value in place.
The commands illustrate separate choices; releasing a field is not a required step after collection.

```bash
aem settings collect editor --dry-run
aem settings collect editor
aem settings collect editor --path '["appearance","theme"]'
aem settings release editor --path '["appearance","theme"]'
```

## Collect application edits

Collect compares actual values with the last applied state and the stage.
It collects only existing managed fields; new fields require repeatable `--path` selections.
Paths are nonempty JSON arrays of strings, so `["a.b"]` and `["a","b"]` have different meanings.
Explicit collection also reclaims a previously deleted or released field if it exists in the actual file.
A missing actual file is an error for collection; a missing managed field in an existing file is a deletion candidate.
Conflicting stage and actual edits abort collection without writing the stage.

## Release field ownership

Release is an explicit change in ownership, not a deletion.
It removes the field from the desired values and records `released`; apply leaves the current actual value untouched even if the user changed it.
A released field is excluded from subsequent collection unless explicitly selected.
To restore management manually, remove its deletion/release record and add the desired value to the stage; alternatively collect that actual field explicitly.
