# Settings configuration

Catalog and machine settings tables connect shared TOML or JSON fields to one editable stage and application target per declaration.

## Application settings declarations and bindings

Catalog `[settings.NAME]` requires `source` (a declared Git/external source), `path` (a literal source-relative settings file), and `format` (`"toml"` or `"json"`), and optionally accepts `agent`.
JSON settings require a strict top-level object with unique keys; comments and trailing commas are unsupported.
See [Settings management](../settings-management.md) for field ownership, exact numeric comparison, and preserving edits.
Its optional `update` table defines a separate automatic sync policy:

| Field | Type | Behavior |
| --- | --- | --- |
| `trigger` | Array of unique events | `shell-start`, `agent-start`, or `interval`; defaults to `[]` in policies mode. Explicit `[]` also excludes the item from full mode. |
| `min_interval` | Integer or float | `600` seconds by default, finite and nonnegative; failures are throttled too. |
| `timeout` | Integer or float | `30` seconds by default, finite and positive. |

Settings do not inherit `updates.defaults` or named skill policies, and reject `action` and `policy` fields.
Every automatic settings attempt receives shared changes and applies the stage after successful reception.
Full mode includes settings with omitted triggers and replaces their individual schedule with the full-run schedule.
Attempt observations are generated under `sources.NAME.settings_automation` in saved state; full runs do not change this clock.
No other item fields are accepted; names cannot collide with skills or instructions.
Machine `[settings.NAME]` requires `target`, an absolute application-file path or `~/...`, and optionally accepts `agent`.
An associated setting has one stage and target and is selected only for that destination.
Preparing or applying an active association requires a configured destination and a target inside its root.
Detached associations can remain recorded after instance removal.
For common settings in multiple profiles, use distinct catalog declarations with the same source/path/format and separate target bindings.
A catalog declaration with `agent = "claude-lab"` belongs to that destination: a machine that has not registered it skips the declaration without a binding, while a machine that has registered it must bind a target and name the same `agent`.
A binding for a skipped declaration is refused.
A declaration without `agent` still needs a binding on every machine.
Older AEM versions reject the catalog field.
Bootstrap `--setting-target NAME=PATH` persists these bindings and preserves omitted values.

Catalog version remains 2, machine version 1, and state envelope version 2.
Existing states require no conversion; new settings records and grouped journals are interpreted by the current AEM.
Older AEM versions cannot operate on these new declarations or recovery operations.
See [Staged settings](../settings-management.md) for the canonical metadata grammar, storage, ownership, and merge semantics.
