# Automatic execution contracts

These contracts separate individual policy execution from full device orchestration and preserve their scheduling and failure boundaries.

## Automatic update contracts

Resolve policies by explicit field override: built-in defaults, catalog-wide defaults, one named policy, then skill-local fields.
Catalog trigger arrays replace earlier arrays; `[]` disables all automatic events for the skill.
Keep the existing `["manual"]` sentinel in effective policy JSON and the existing machine policy syntax.
Validate all policy declarations, including unused named policies, before network access.
Keep common trigger/action/interval settings separate from source-specific delivery options; reject unsupported capabilities rather than substituting another action.

External callers supply `shell-start`, `agent-start`, or `interval` events to `auto`.

- Policy configuration does not install hooks, modify shell profiles, register OS tasks, or imply an in-process scheduler.
- Ordinary `apply`, `status`, and `bootstrap` must not perform implicit automatic updates.
- Explicit commands retain their existing contracts and ignore automatic policy throttles.

Under the existing configuration lock, persist each skill's attempt before network access and throttle failures as well as successes across all its events.
Preview must not fetch or record attempts.
Automatic sync applies each successfully updated skill independently.
Explicit sync instead requires all updates to succeed before applying.
Preserve existing per-target transactions, stop if recovery is pending, and never adopt, replace conflicts, or reattach detached skills automatically.
Skill automatic policies cover catalog skills; settings schedules remain independent, and explicit sync is unthrottled.

## Device orchestration contracts

Default to `policies` so existing installations retain independent automatic behavior.
Expose `off`/`policies`/`full` and full trigger/interval/timeout options in installer/setup, preserving omitted fields and supporting configuration-only journaled edits.
`off` disables automatic events; explicit maintenance and update commands remain available.
Full mode owns one persisted attempt clock across events and failures; do not consult or modify individual automatic clocks during its stages.
Reject individual skill/catalog event entrypoints in full mode to avoid duplicating the unified schedule.
Queue full runs through the existing external standard-library worker after the requesting process exits, including when tool updates are off.
Apply the saved tool release permission first, then invoke the freshly installed CLI before catalog/content work; never import the replacing package into the external worker.
Release installation/configuration locks before invoking the fresh CLI, and validate mode/runtime binding and a one-use token under its locks.
Cancel queued work when automation settings change, and cancel queued individual tool updates when switching to `off` or `full`.
Validate and fast-forward the catalog before loading full content selection; skip transport for local/unbound catalogs.
Full mode opts in otherwise unconfigured skills but preserves explicit or inherited empty-trigger exclusions using the existing precedence.
Prepare/update eligible sources before applying selected items, with no adoption, replacement, reattachment, deletion, publication, or hook trust granting.
Keep shared-checkout validation and live-link side effects intact, including excluded consumers; document this boundary.
Full mode refuses unsupported payload requirements before its content stage unless the machine explicitly enables `skip_unsupported`.
That option excludes only known platform limitations, reports every exclusion, and never suppresses shared-source guards or ordinary errors.
Include it in the saved automation settings used to cancel obsolete worker requests.
Policy-based automation keeps independent attempts and failure throttling; previews report unsupported due work without recording attempts.
Stop later stages on failure without claiming cross-repository rollback; preserve ordinary per-target journals and recovery.
