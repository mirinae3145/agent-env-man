# Device automation behavior

This reference defines full-run sequencing, eligibility, platform exclusions, and completion reporting.
Use the [automation guide](../automation.md) to select and configure a mode.

## Execution sequence

`policies` is the backward-compatible default: tool, catalog, and skill policies run as before.
`off` disables startup and event-driven automatic work.
Explicit update, sync, catalog update, and self update commands remain available.
`full` queues one sequential run after the requesting process exits:

1. Update AEM within its saved release range, or skip this stage when tool updates are off.
1. Invoke the installed AEM afresh and validate/fast-forward the Git catalog; local or unbound catalogs skip delivery.
1. Prepare and update eligible skill/directory/instruction/settings sources, receiving settings into their stages, then apply after all selected delivery succeeds.

For a newly declared skill in an existing shared checkout, full mode validates the skill against the fetched revision before advancing the checkout.
It does not require the skill's path in the older local revision.
Missing checkouts are still cloned and validated during preparation; standalone `bootstrap` never updates existing checkouts.

## Schedule and eligibility

Full mode uses one shared trigger list and attempt interval, replacing individual triggers, intervals, and check/sync actions for the run.
Its schedule defaults are as follows:

| Schedule field | Full-mode default |
| --- | --- |
| Events | Shell and agent startup. |
| Attempt interval | 3600 seconds, including failed attempts. |
| Git timeout | 30 seconds per content/catalog phase. |

Participation in the run follows these rules:

- Skills and directories without an explicit trigger policy participate.
- Explicit empty-trigger exclusions resolve through catalog defaults, named policy, and item fields.
- Detached skills, directories, and instruction groups remain excluded.

## Preservation and failure boundaries

- Shared checkout updates can still change linked consumers excluded from installation, including manual skills; this is the existing shared-source contract.
- It never adopts conflicts, replaces user edits, reattaches detached content, removes undeclared targets, or grants agent hook trust.
- New valid catalog declarations can be prepared and installed in full mode.
- For existing shared Git checkouts, directory paths introduced by new declarations are validated against the incoming revision before fast-forwarding, so they need not exist in the current revision.
- Dirty sources and divergent histories require explicit reconciliation; automation never merges or stashes them.
- A failed stage stops later stages; successful earlier work remains and normal per-target recovery rules apply.

## Unsupported items

By default, a platform-unsupported item stops the content stage before preparation, source updates, or installation.
On native Windows this includes directories declaring `preserve_symlinks = true`, even when their current contents contain no links.

### Exclude unsupported items

To explicitly exclude these items from subsequent full runs on this machine, use `aem setup --automation full --automation-skip-unsupported` (full mode still requires registered runtime paths).
Use `aem setup --no-automation-skip-unsupported` to restore refusal; omitting the option preserves its saved value.
The installer accepts the same options.
Exclusions appear with item names and reasons in the content result's `excluded` list; an entirely excluded content selection is `skipped`.

### Limits of exclusion

The skip option does not suppress invalid bindings, conflicts, or filesystem errors, and does not authorize link conversion.
An excluded item sharing a source with a remaining item still participates in source validation and can stop the content stage.
The check uses the updated catalog; earlier tool and catalog stages are not rolled back.
Dry run reports support and exclusions against the local catalog without fetching or recording attempts; actual execution checks again after catalog delivery.
In policies mode, unsupported due items fail independently while other independent items continue, retaining normal failure throttling.

## Runtime requirements and results

Full mode needs registered runtime paths, and its progress is reported in `aem status`.

### Runtime requirements

The installer must register an external Python, uv, and the installation directories before full mode can be enabled, even when tool updates are off.
No OS scheduler or daemon is installed: use startup integrations or `aem automation --trigger interval` from an external scheduler.
`aem auto` and `aem catalog auto` require `policies` mode; use the unified automation command in full mode to avoid duplicate event paths.
Policy-only setup edits require no profile changes; omitted fields retain saved values and supplied trigger lists replace the saved list.

### Results and locks

Inspect the eventual sequence and stage results under `automation` in `aem status`.
Queued work is not yet completed; changed mode/runtime settings cancel pending work.
Registered commands may report lock contention while the worker or continuation holds the installation/configuration locks.
Native Windows replacement and real uv reinstallation retain their existing validation limits.
