# Device automation behavior

This reference defines full-run sequencing, eligibility, failure boundaries, and completion reporting.
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

Unsupported payloads and ordinary operation failures stop the content stage; native Windows is no longer a supported execution environment.
The former Boolean `automation.skip_unsupported` field remains readable but has no effect, and its setup options are removed.
Manual-policy and detached-item exclusions remain visible in `excluded`; these do not suppress errors in selected work or shared-source guards.

The check uses the updated catalog; earlier tool and catalog stages are not rolled back.
Dry run checks the local catalog without fetching or recording attempts, and actual execution checks again after catalog delivery.

## Runtime requirements and results

Full mode needs registered runtime paths, and its progress is reported in `aem status`.

### Runtime requirements

The installer must register an external Python, uv, and the installation directories before full mode can be enabled, even when tool updates are off.
No OS scheduler or daemon is installed: use startup integrations or `aem automation --trigger interval` from an external scheduler.
`aem auto` and `aem catalog auto` require `policies` mode; use the unified automation command in full mode to avoid duplicate event paths.
Policy-only setup edits require no profile changes; omitted fields retain saved values and supplied trigger lists replace the saved list.

### Results and locks

Inspect the eventual sequence and stage results under `automation` in `aem --verbose status` or `aem --json status`.
Queued work is not yet completed; changed mode/runtime settings cancel pending work.
Registered commands may report lock contention while the worker or continuation holds the installation/configuration locks.
Real uv replacement and agent hook continuity require integration validation.
