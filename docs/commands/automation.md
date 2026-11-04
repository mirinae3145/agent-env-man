# Automation and callback command reference

Automation commands run device modes or item policies; setup and instruction installation register the callbacks.
Queued work and callback output have separate completion and failure contracts.

## auto

```text
aem auto --trigger EVENT [--item NAME ...] [--dry-run]
```

Select catalog skills or directories; omitted names consider all their policies.
Due items require prepared sources and run independently.
One failure does not block another item, but an unresolved recovery journal stops further work.
Attempts are persisted before network access and throttle failures as well as successes.
Dry run shows effective policies and due work without fetching or saving attempts.
Automatic execution never adopts conflicts, replaces local edits, or reattaches detached items.
It exits `1` if any attempted item fails, otherwise `0`.

Directory policy results use `directory: NAME` instead of `skill: NAME`, retaining the same policy and attempt fields.
External directory checks report `external-no-fetch` without installing; sync validates and applies their local source without Git transport.
Directories participate in agent-filtered apply, status, detach, and locate as common items; a directory that declares `agent` is selected by apply, status, and detach only for that destination, and locate still finds it by name.


## startup

```text
aem startup --trigger EVENT [--agent AGENT]
```

Callback registered by setup; runs the selected device automation mode and remains fail-open.
In the default `policies` mode it independently queues due AEM self-updates, runs the machine catalog policy, then runs the same skill/directory policy engine as `auto`.
In `full` mode it queues the entire sequence for execution after the callback exits; in `off` mode it performs no automatic work.
An empty update result skips skill reload detection without reading the content catalog, so a missing or invalid catalog does not produce callback errors when automation is off.
A successful catalog update reloads declarations before resolving skill policies for that event.
A failed catalog attempt skips skill work for that event, preserving fail-open startup.
The saved startup report includes the catalog result as `catalog_update`.
No bound catalog means no skill update work; enabled self-updates still run.
Self-updates are throttled once per day across events, including failures, and start after the requesting process exits.
They do not delay startup for release discovery or package installation.
The saved startup report includes `self_update`; `status` also reports the latest worker result separately.
AEM self-update completion does not produce a skill-change briefing.
Operational failures are recorded in status when possible; failures before state access go to stderr.
It exits `0` on handled operational failures so startup can continue; CLI usage errors still exit `2`.
With an agent, completed changes can return an agent-specific briefing; shell callbacks return `{}`.
This command does not install integrations.

`setup --startup-hook-timeout SECONDS` saves the agent startup callback limit and rewrites registered startup hooks, preserving omitted values and unrelated hook groups.
The default is 10 seconds; this does not change instruction-location hooks, shell callbacks, or Git phase limits.
In policies mode, catalog and skill work shares the outer startup hook limit; full mode queues work after the callback exits.


## agent-hook

```text
aem agent-hook NAME --agent AGENT
```

Callback registered by instruction apply; emits only instruction reading locations and relative-reference guidance.
It does not update sources or inject document contents.
Instruction apply registers both `SessionStart` and `SubagentStart`; existing installations gain the child registration through ordinary apply.

Generated child commands use the internal `--hook-event SubagentStart` argument and return event-specific `hookSpecificOutput.additionalContext` JSON for either agent.
Calls without that argument retain their SessionStart output and failure behavior, regardless of stdin contents.
Apply reports retain the primary `hook_group` object and add `additional_hook_groups`, an object mapping additional event names to groups.
New Codex registrations require `/hooks` trust review; AEM never grants trust.

Unrelated machine fields and obsolete unselected state modes do not block lookup; the selected saved entry and bundle must still pass locator checks.
It waits up to five seconds total for the installation and configuration locks within the installed ten-second hook timeout.
For Codex SessionStart, handled lookup errors return a structured stop response with exit `0`; usage errors still exit `2`.
For SubagentStart, Codex instead returns a `systemMessage` warning with exit `0`; this event cannot prevent child creation.
Old source registration, `codex-hook`, and throttled `sync` syntax are removed; see [Removed interfaces](../removed-interfaces.md).


## Claude callback behavior

Claude agent-hook emits plain stdout path context for SessionStart and event-specific JSON context for SubagentStart.
Lookup failure uses stderr and exit 2; neither start event blocks creation.

Startup may request reloadSkills after a successful synchronous skill installation or checkout advancement affecting that consumer, including active links indirectly changed through shared checkouts.
Unapplied copies and detached skills do not request reload.
An advanced live-link source still requests reload if subsequent application fails.
No-op/check/throttled runs and failures without a relevant change do not request reload.
In full asynchronous mode, wait for worker completion and start a fresh session to discover changes.
The hidden --aem-hook-id identifies supported command-field ownership.
See [profile contracts](../agent-profiles.md).


## automation

Runs the selected device automation mode and reports immediate or queued outcomes.

```text
aem automation --trigger EVENT [--dry-run]
```

Runs the selected device mode.
`off` returns `mode = "off"`, `status = "disabled"`, empty `outcomes`, and `failed = false`.
`policies` returns the individual `self_update` / `catalog_update` outcomes, skill `outcomes`, settings `settings_updates`, and `failed`; catalog failures skip both skill and settings work.
`full` returns `not-triggered`, `throttled`, `planned` (preview), or `queued` and defers the whole sequence until requester termination.
Only full mode uses the shared device trigger list and interval; individual modes retain their existing clocks.
Dry run makes no remote requests or attempt records and creates no command lock files.
The full preview includes `policy` and `stages = ["tool", "catalog", "content"]`.
The full launch result includes `mode`, Unix `time`, `trigger`, `token`, and an opaque request `binding`.
A launch failure exits 1; a successfully queued run exits 0 and reports eventual failure through status.

### Automation result fields

`status` includes an `automation` object with effective `policy` and `last_attempt`.
Full attempt status can be `queued`, `continuing`, `completed`, `failed`, or `cancelled`.
Continuation results contain a `stages` object with the tool outcome and, when reached, catalog and content outcomes.
Terminal results include Unix `finished`, with `error` or `reason` on failure/cancellation.
The content result includes selected `sources`, `excluded` consumers/reasons, and preparation/update/application outcomes when reached.
The tool stage obeys the existing self-update release range; `off` skips it.
The fresh installed CLI then updates only a Git-bound catalog before resolving declarations, preparing eligible sources, updating them, and applying only after delivery succeeds.
Full runs can install new declarations, while preserving explicit manual exclusions, detached groups, conflict/recovery protections, and shared-link semantics.
They do not publish content or delete targets removed from the catalog.
The worker and fresh continuation release/reacquire installation-before-configuration locks; mode/runtime binding and one-use token checks prevent stale continuation.
The continuation has no total wall-clock timeout; individual Git phases and the tool subprocess remain bounded.

### Mode restrictions

In `off` mode, `auto` returns no skill work and `catalog auto` reports `not-triggered`.
In `full` mode these individual event commands fail with guidance to use `automation`, avoiding duplicate policy execution.
Explicit `self update`, `catalog update`, content `update`, and `sync` retain their contracts in every mode.
