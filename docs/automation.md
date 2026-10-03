# Automation and AEM updates

Choose a device automation mode, then configure the release range and any independent update policies that mode uses.
Manual AEM updates are also covered here.
For complete command syntax and configuration fields, see [Commands](commands.md) and [Configuration](configuration.md).

| Device mode | Startup and event behavior | Content installation |
| --- | --- | --- |
| `off` | Automatic work is disabled; explicit commands remain available. | Use explicit bootstrap and apply. |
| `policies` (default) | AEM, catalog, and skill updates use their independent opt-in policies. | Skill `sync` policies apply prepared skills; catalog updates do not install new declarations. |
| `full` | One queued sequence updates AEM, then the catalog, then eligible skill/instruction/settings sources. | Prepares new declarations and applies eligible content after delivery succeeds. |

Application settings have independent per-item sync policies in `policies` mode and participate by default in `full`, preserving explicit empty-trigger exclusions and detach.
Linked content changes as soon as its shared source checkout advances, including links excluded from installation.
See [Maintenance and recovery](maintenance.md) for conflicts, preservation, and repair.

## Device automation modes

```bash
python scripts/setup.py --shell bash --agent codex --automation full --self-update compatible
aem setup --automation full --automation-trigger shell-start --automation-trigger agent-start \
  --automation-interval 3600 --automation-git-timeout 30
aem automation --trigger agent-start --dry-run
aem setup --automation policies
aem setup --automation off
```

`policies` is the backward-compatible default: tool, catalog, and skill policies run as before.
`off` disables startup and event-driven automatic work; explicit update, sync, catalog update, and self update commands remain available.
`full` queues one sequential run after the requesting process exits:

1. Update AEM within its saved release range, or skip this stage when tool updates are off.
1. Invoke the installed AEM afresh and validate/fast-forward the Git catalog; local or unbound catalogs skip delivery.
1. Prepare and update eligible skill/instruction/settings sources, receiving settings into their stages, then apply after all selected delivery succeeds.

Full mode uses one shared trigger list and attempt interval, including failed attempts.
Its defaults are shell/agent startup, 3600 seconds between attempts, and 30 seconds per content/catalog Git phase.
It replaces individual automatic triggers, intervals, and check/sync actions for this run.
Skills without an explicit trigger policy participate; explicit `manual` exclusions resolve through catalog defaults, named policy, and skill fields.
Detached skills and detached instruction groups remain excluded.
Shared checkout updates can still change linked consumers excluded from installation, including manual skills; this is the existing shared-source contract.
It never adopts conflicts, replaces user edits, reattaches detached content, removes undeclared targets, or grants agent hook trust.
New valid catalog declarations can be prepared and installed in full mode.
A failed stage stops later stages; successful earlier work remains and normal per-target recovery rules apply.

The installer must register an external Python, uv, and the installation directories before full mode can be enabled, even when tool updates are off.
No OS scheduler or daemon is installed: use startup integrations or `aem automation --trigger interval` from an external scheduler.
`aem auto` and `aem catalog auto` require `policies` mode; use the unified automation command in full mode to avoid duplicate event paths.
Policy-only setup edits require no profile changes; omitted fields retain saved values and supplied trigger lists replace the saved list.
Inspect the eventual sequence and stage results under `automation` in `aem status`.
Queued work is not yet completed; changed mode/runtime settings cancel pending work.
Registered commands may report lock contention while the worker or continuation holds the installation/configuration locks.
Native Windows replacement and real uv reinstallation retain their existing validation limits.

## Update AEM itself

```bash
python scripts/setup.py --shell bash --agent codex --self-update compatible
aem setup --self-update off       # Change the saved automatic mode.
aem self status                  # Installed version, mode, and last attempt.
aem self update --dry-run         # Offline preview.
aem self update                  # Queue an explicit compatible release update.
aem self update --mode breaking  # Permit incompatible releases for this attempt.
```

For final releases from `1.0.0` onward, `compatible` permits newer final releases in the same major version.
For a prerelease, `compatible` permits only a higher numeric subversion with the same base `X.Y.Z` and the same `a`, `b`, or `rc` label (for example, `1.0.0rc1` to `1.0.0rc2`).
Changing the label, base version, or moving to a final release requires `breaking`.
This permission also gates the first stable release: `1.0.0rc0` to `1.0.0` requires `breaking`, without implying a `2.0.0` version requirement.
Same-series subversion releases must preserve compatibility because existing `compatible` installations can select them automatically.
Final installations retain their existing compatible range and do not select prereleases in `compatible` mode.
`breaking` permits any newer final or prerelease version, including incompatible changes; review migration instructions before enabling it.
Supported prereleases use Python package notation `X.Y.ZaN`, `X.Y.ZbN`, or `X.Y.ZrcN`, with an optional nonnegative numeric subversion without leading zeroes.
An omitted number is `0`: `1.0.0rc` and `1.0.0rc0` are equivalent, and `1.0.0rc1` is their next compatible release.
Git tags may also use `vX.Y.Z-alpha`, `vX.Y.Z-beta`, or `vX.Y.Z-rc`, with an optional `.N` number (for example, `v1.0.0-beta.1` maps to package version `1.0.0b1`).
Bare `v1.0.0-beta` maps to `1.0.0b0`; package metadata and installed versions continue to use Python notation.
When equivalent tags coexist, update selection prefers Python notation, then an explicit-zero spelling, and resolves annotated tags to their commits.
A release may start at any supported label; earlier phases need not exist.
Tag and package metadata comparisons accept the same omitted-zero equivalence.
Ordering is numeric by base version, then `a` < `b` < `rc` < final, then numeric subversion.
Development, post, local versions, and untagged commits are excluded.
AEM reads `vVERSION` tags from its upstream Git repository, verifies the matching package metadata, and installs the selected commit through uv.
Use the installer's `--update-repository URL` to select another release repository.
Development checkout edits are not published or installed by this path.

In `policies` mode with tool updates enabled, the existing startup callback queues at most one attempt per day across shell and agent events; failures are throttled too.
It works without a bound content catalog.
The worker waits for the requesting AEM process to exit, then uses the installer's external Python rather than the environment being replaced.
The saved external Python and uv executables must remain available; rerun the installer if they move.
A queued result means the attempt has been scheduled, not completed; use `aem self status` for the eventual result.
Explicit updates bypass the daily throttle and work even with automatic updates off.
Content updates, catalog delivery, instruction location callbacks, and `auto` do not update AEM itself.
No daemon or OS scheduler is installed.

Self-updates coordinate registered AEM commands sharing the same uv tools directory.
Commands can report lock contention during replacement; startup remains fail-open.
Other package-manager processes and external editors are not covered by these locks.
A failed uv replacement is reported without a rollback guarantee; rerun `scripts/setup.py` to repair the installation if AEM cannot start.
Native Windows worker/replacement and actual agent hook continuity require platform validation.

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
The underlying `catalog_update` table remains documented in [Configuration](configuration.md#catalog-automatic-update-settings).

The default trigger is `manual`; automatic updates require a Git catalog binding.
In `policies` mode, setup's existing startup callback updates a due catalog first, then resolves skill policies from the validated new catalog.
If that catalog attempt fails, the callback skips skill updates for the event and still allows startup to continue.
External callers can use `aem catalog auto --trigger interval`; add `--dry-run` for an offline preview.
`aem auto` continues to operate on skills only.

Catalog automation shares one attempt clock across events, throttling failures too.
It uses the same validation and fast-forward guards as `aem catalog update`, preserving local edits and the previous catalog on validation failure.
The catalog update itself does not bootstrap or apply content; startup's subsequent skill policies retain their existing scope and require prepared sources.
Explicit catalog updates bypass the automatic interval.
See `aem catalog status` or `aem status` for the last automatic result.

## Automatic skill updates

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

Policies apply only to skills and do not install integrations.
Setup connects interactive shell and agent startup to a fail-open `startup` callback.
Without setup, external callers can invoke `aem auto --trigger shell-start`, `agent-start`, or `interval`.
For `interval`, arrange an OS scheduler; AEM does not run a daemon.
Preview due work with `aem auto --trigger agent-start --dry-run`.

Each skill has one attempt clock across events; failed attempts are throttled too.
Automatic sync handles skills independently and preserves conflicts and detached items.
Explicit `update`, `apply`, `sync`, and `status --refresh` ignore automatic policies.
Agent startup shows a brief message for completed updates or installations; full outcomes and failures remain in status.
Instruction location hooks installed by apply do not trigger updates.
See [policy fields and precedence](configuration.md#update-policies).

## Automatic settings sync

Declare `[settings.NAME.update]` separately from skill update policies; see [Staged settings](settings-management.md) for fields and examples.
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

## Personal hooks

Personal hook registrations are always excluded from policies and full mode.
Explicit `apply --item NAME` is required. A skill sharing a source checkout can
still update a live script; registration definitions and trust remain unchanged.
See [Personal hooks](personal-hooks.md).

## Startup contention and shared fetches

Startup callbacks wait up to five seconds for short lock contention. On Linux/WSL, instruction callbacks can return validated saved location metadata while a content update holds the configuration lock. They still refuse package-replacement contention, pending recovery, replaced links, or a saved configuration/state change during lookup. Native Windows retains exclusive installation locking.

In one automatic skill-policy run, skills sharing a prepared checkout, remote, branch, and Git timeout reuse the same fetch observation, including a network failure. Different timeout budgets fetch separately. Each skill retains its own selection, attempt clock, outcome, local-file checks, and application. Later events fetch again when due; manual commands remain unthrottled.

Policy updates remain synchronous and must fit the configured outer startup hook duration. Reusing fetches reduces network work but does not impose a total run deadline or queue policy runs in the background.
