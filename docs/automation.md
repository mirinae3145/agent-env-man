# Automation and AEM updates

Choose a device automation mode, then configure the release range and any independent update policies that mode uses.
Manual AEM updates are also covered here.
For complete command syntax and configuration fields, see [Commands](commands.md) and [Configuration](configuration.md).

| Device mode | Startup and event behavior | Content installation |
| --- | --- | --- |
| `off` | Automatic work is disabled; explicit commands remain available. | Use explicit bootstrap and apply. |
| `policies` (default) | AEM, catalog, skill, and directory updates use their independent opt-in policies. | Skill/directory `sync` policies apply prepared content; catalog updates do not install new declarations. |
| `full` | One queued sequence updates AEM, then the catalog, then eligible skill/directory/instruction/settings sources. | Prepares new declarations and applies eligible content after delivery succeeds. |

Application settings have independent per-item sync policies in `policies` mode and participate by default in `full`, preserving explicit empty-trigger exclusions and detach.
Linked content changes as soon as its shared source checkout advances, including links excluded from installation.
See [Maintenance and recovery](maintenance.md) for conflicts, preservation, and repair.

## Choose and configure a mode

Configure automation for the behavior you want on this device:

1. Choose `off`, `policies`, or `full` using the mode table.
   For full mode, first register the external runtime through the repository installer, for example `python scripts/setup.py --shell bash --agent codex --automation full --self-update compatible`.
1. Save the selected mode with `aem setup --automation MODE`.
   To customize a full schedule, use `aem setup --automation full --automation-trigger shell-start --automation-trigger agent-start --automation-interval 3600 --automation-git-timeout 30`.
1. Preview the applicable event with `aem automation --trigger agent-start --dry-run`.
1. After an event runs, inspect `aem status` for completed stages, exclusions, or failures.
   A queued result is not completed work.

Omitted setup fields retain their saved values; supplied trigger lists replace the saved list.
To disable event-driven work, use `aem setup --automation off`; explicit commands remain available.

## Configure the selected work

The [device behavior reference](automation/device.md) defines full-mode sequencing, eligibility, unsupported items, runtime requirements, and preservation.
The [independent policy guide](automation/policies.md) covers catalog, skill/directory, and settings schedules in `policies` mode.
The [AEM update guide](automation/self-update.md) covers manual or automatic tool updates and repair.
Use the [release selection reference](automation/releases.md) to choose the allowed release range and understand version/tag matching.

## Personal hooks

Personal hook registrations are always excluded from policies and full mode.
Explicit `apply --item NAME` is required.
A skill sharing a source checkout can still update a live script; registration definitions and trust remain unchanged.
See [Personal hooks](personal-hooks.md).

## Startup contention and shared fetches

Startup callbacks wait up to five seconds for short lock contention.
On Linux/WSL, instruction callbacks can return validated saved location metadata while a content update holds the configuration lock.
They still refuse package-replacement contention, pending recovery, replaced links, or a saved configuration/state change during lookup.
Native Windows retains exclusive installation locking.

In one automatic skill-policy run, skills sharing a prepared checkout, remote, branch, and Git timeout reuse the same fetch observation, including a network failure.
Different timeout budgets fetch separately.
Each skill retains its own selection, attempt clock, outcome, local-file checks, and application.
Later events fetch again when due; manual commands remain unthrottled.
Checks and sync guards compare HEAD with their fetched or reused commit, even if a different timeout's fetch updates the shared remote-tracking ref during the run.

Policy updates remain synchronous and must fit the configured outer startup hook duration.
Reusing fetches reduces network work but does not impose a total run deadline or queue policy runs in the background.
