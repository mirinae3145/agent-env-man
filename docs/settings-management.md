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

## Apply, share, and recover

Detailed behavior for each later step of the workflow is in its own reference:

- The [apply and publish reference](settings-management/apply-and-publish.md) defines what apply preserves, when it replaces values, and how export and Git publish write the shared source.
- The [collection reference](settings-management/collection.md) defines collecting actual application edits into the stage, and releasing field ownership while leaving the actual value in place.
- The [conflicts and recovery reference](settings-management/conflicts-and-recovery.md) defines shared and application conflict resolution, status and detach, previews, and grouped recovery.
