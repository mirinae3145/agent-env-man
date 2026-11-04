# Configure independent update policies

In `policies` mode, configure catalog reception and skill/directory updates independently.
Settings use their own policy and never inherit skill schedules.

## Automatic catalog updates

Choose automatic catalog events during Git registration:

```bash
aem bootstrap --catalog-repository URL --catalog-path catalogs/personal.toml \
  --catalog-trigger shell-start --catalog-trigger agent-start
```

Change the saved policy later:

```bash
aem setup --catalog-trigger agent-start --catalog-interval 3600 --catalog-git-timeout 5
aem setup --catalog-trigger manual  # Disable automatic catalog updates.
aem setup --catalog-trigger interval --dry-run
```

These options write device-local settings; no manual `machine.toml` edit is required.
Repeated trigger options replace the complete event list; omitted options retain their saved values.
Policy-only setup needs no executable or startup selections and leaves existing profiles alone.
The underlying `catalog_update` table remains documented in [Configuration](../configuration/automation.md#catalog-automatic-update-settings).

### Eligibility and startup sequence

The default trigger is `manual`; automatic updates require a Git catalog binding.
In `policies` mode, setup's existing startup callback updates a due catalog first, then resolves skill policies from the validated new catalog.
If that catalog attempt fails, the callback skips skill updates for the event and still allows startup to continue.
External callers can use `aem catalog auto --trigger interval`; add `--dry-run` for an offline preview.
`aem auto` operates on skill and directory policies.

### Throttling and preservation

Catalog automation shares one attempt clock across events, throttling failures too.
It uses the same validation and fast-forward guards as `aem catalog update`, preserving local edits and the previous catalog on validation failure.
The catalog update itself does not bootstrap or apply content; startup's subsequent skill policies retain their existing scope and require prepared sources.
Explicit catalog updates bypass the automatic interval.
See `aem catalog status` or `aem status` for the last automatic result.

## Automatic skill updates

Skill and directory policies select events and a check or sync action per item.

### Configure events

In `policies` mode, automatic skill updates default to disabled (`trigger = []`).
Opt in through the catalog:

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
action = "sync"
min_interval = 600
timeout = 5

[skills.report.update]
trigger = []
```

These policies behave as follows:

- **Scope**: They apply to skills and directories and do not install integrations.
  Directories use the same defaults, named policies, per-item overrides, and attempt clocks.
  External directory checks validate local availability without fetching; sync applies the local source.
  Neither path collects installed copies or publishes changes.
- **Startup**: Setup connects interactive shell and agent startup to a fail-open `startup` callback.
- **External callers**: Without setup, external callers can invoke `aem auto --trigger shell-start`, `agent-start`, or `interval`.
  For `interval`, arrange an OS scheduler; AEM does not run a daemon.
- **Preview**: Preview due work with `aem auto --trigger agent-start --dry-run`.

### Independent outcomes

Each skill or directory has one attempt clock across events; failed attempts are throttled too.
Automatic sync handles skills and directories independently and preserves conflicts and detached items.
Explicit `update`, `apply`, `sync`, and `status --refresh` ignore automatic policies.

Agent startup shows a brief message for completed updates or installations; full outcomes and failures remain in status.
Instruction location hooks installed by apply do not trigger updates.
See [policy fields and precedence](../configuration/catalog.md#update-policies).

## Automatic settings sync

Settings reception and application use separate per-setting policies, including when upgrading from releases without automatic settings support.

### Configure settings events

Declare `[settings.NAME.update]` separately from skill update policies; see [per-setting automatic policy](../settings-management/automation.md#per-setting-automatic-policy) for fields and examples.
`aem automation --trigger EVENT` runs due settings policies after skill policies in `policies` mode, with results under `settings_updates`.
A failed catalog update skips both skill and settings work.

Each setting uses its own persisted attempt clock across events, including failed attempts; previews are offline.
Settings always receive and then apply, with no automatic collection, export, publication, replacement, or reattachment.
Full mode includes settings by default and uses its shared schedule instead of individual clocks, while preserving explicit `trigger = []` exclusions.

### Upgrading from manual-only settings

In releases through `1.0.0-rc`, settings participated only in explicit commands, including when device automation was `full`.
After upgrading, existing full-mode configurations also prepare, receive, and apply settings with omitted triggers.
To keep settings manual during the transition, disable device automation with `aem setup --automation off` before upgrading.
After upgrading, add an explicit empty trigger list to each setting that should remain manual before restoring full mode:

```toml
[settings.editor.update]
trigger = []
```

Repeat this for each setting that should remain manual.
Older packages reject the new settings `update` table, so add it only after upgrading.
In `policies` mode, omitted settings triggers still disable automatic settings work.
Once the exclusions are saved, restore full mode with `aem setup --automation full` and inspect `aem automation --trigger agent-start --dry-run` before invoking the next automatic event.
