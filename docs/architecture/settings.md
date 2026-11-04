# Staged settings contracts

Keep settings transport, editable stages, and actual application files distinct.
Collection, export, and publication require explicit operations.
Settings have independent per-item automatic schedules; never inherit skill defaults or named policies.
Automatic settings work always receives shared changes and then applies the stage, stopping application on reception failure or conflicts.
Full device automation includes settings by default, preserving explicit empty-trigger exclusions and detached items, and uses the shared full-run clock.
A shared checkout update by another consumer may change the source but must not activate or rewrite an unselected settings stage.
Automatic settings application retains the ordinary field conflict checks and must never replace local edits or reattach detached items.

## Format adapters

Keep format parsing, value identity, field enumeration, and preserving edits behind the format adapter.
Do not use TOML parser nodes as persisted ownership values or expose them in CLI reports.
Shared intent metadata is an AEM contract, independent of the supported application format.
Support TOML and strict JSON objects, treat arrays and empty tables/objects as atomic values, and permit one owner per target file.
JSON numbers compare by exact numeric value regardless of spelling, with booleans kept distinct; preserve numeric tokens without conversion through binary floats.
Keep JSON edits local to changed values and required punctuation, preserving untouched tokens and returning unchanged documents verbatim.
Reject duplicate JSON keys, comments, trailing commas, and nonstandard numeric constants.
Distinguish format-specific empty document construction from parsing an existing file; an existing empty JSON file is invalid.

## Comparison state and recovery

Editable stages never replace trusted shared/apply comparison bases.
Deletion, ownership release, and local detach have distinct semantics; preserve intent records for newly connected and offline devices.
Preflight grouped settings/metadata writes before mutation and commit comparison records with their journal.
Recovery must validate the complete group before rollback and remain compatible with existing single-target journals.
Reuse existing whole-checkout publication and Git safety rules; field merging never reconciles Git history.
