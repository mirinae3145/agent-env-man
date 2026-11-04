# Command reference

This reference defines command syntax, selection scope, result fields, and failure boundaries.
For guided setup and everyday workflows, start with the [README](../README.md).

```text
aem [--config PATH] [--json | --verbose] [--progress | --no-progress] COMMAND [ARGS]
```

`--config`, `--json`, `--verbose`, `--progress`, and `--no-progress` are global options and must precede the command.
Command-specific options follow their command, for example `aem --json catalog publish --dry-run`.
Options require their full spelling; abbreviated long options are rejected.
Every command accepts `-h` or `--help`.

## Common argument values

Git duration options use `--git-timeout`, `--catalog-git-timeout`, and `--automation-git-timeout`.
The previous names `--timeout`, `--catalog-timeout`, and `--automation-timeout` remain supported aliases with identical behavior.
Saved TOML `timeout` keys and effective JSON policy fields retain their names.

`TIMEOUT` in the command references defaults to `30` seconds and must be positive and finite.
It bounds each Git phase, not the entire command or filesystem copying.
`AGENT` selects a registered destination: `codex`, `claude`, or a [named instance](commands/profiles.md#named-agent-destination-selection).
`EVENT` is `shell-start`, `agent-start`, or `interval`.

## Reference groups

Read the [shared command contracts](commands/output.md) for output formats, exit codes, locks, platform preflight, and permission reports.
Choose a group for the command-specific contract.

| Reference | Scope |
| --- | --- |
| [Setup](commands/setup.md) | Integration selection, saved policies, and removal. |
| [Catalog](commands/catalog.md) | Bootstrap, catalog binding, reception, and publication. |
| [Content](commands/content.md) | Update, apply, and sync selection and preservation. |
| [Publication](commands/publish.md) | Repository-wide publication and explicit collection of managed copies. |
| [Inspection](commands/inspection.md) | Local documentation, status, and source or installed lookup. |
| [Maintenance](commands/maintenance.md) | Detach, recovery, and personal hook removal. |
| [Settings](commands/settings.md) | Stage operations and field conflict resolution. |
| [Agent profiles](commands/profiles.md) | Named destinations, comparison, copying, and tool hook inspection. |
| [Automation and callbacks](commands/automation.md) | Device modes, item policies, and registered callbacks. |
| [AEM releases](commands/self.md) | Tool status, self-update, and prepared-release publication. |

## Command overview

| Command | Purpose | Network |
| --- | --- | --- |
| [`docs`](commands/inspection.md#docs) | Locate version-matched local documentation and examples. | None. |
| [`setup`](commands/setup.md#setup) | Connect or remove startup integrations and official agent skill links. | None. |
| [`self`](commands/self.md#self) | Inspect, update, or publish a prepared release of AEM itself. | Status and dry runs are offline; update workers fetch/install releases; publish inspects, fetches, and pushes Git refs. |
| [`bootstrap`](commands/catalog.md#bootstrap) | Bind a catalog and prepare sources. | Clone missing Git repositories. |
| [`catalog`](commands/catalog.md#catalog) | Inspect, update, or publish the catalog itself. | Update/publish only; publication dry run is offline. |
| [`update`](commands/content.md#update) | Fetch and fast-forward prepared sources. | Yes for Git. |
| [`publish`](commands/publish.md) | Publish selected checkouts, optionally collecting managed copies first. | Git remote inspection/fetch/push only; external collection and dry run are offline. |
| [`apply`](commands/content.md#apply) | Install from local prepared sources. | None. |
| [`sync`](commands/content.md#sync) | Update all sources, then apply if every update succeeds. | Yes for Git. |
| [`auto`](commands/automation.md#auto) | Run due skill/directory policies for an event. | Due Git items only; none in dry run. |
| [`status`](commands/inspection.md#status) | Inspect sources and saved installations. | Only with `--refresh`. |
| [`detach`](commands/maintenance.md#detach) | Preserve contents and release ownership. | None. |
| [`locate`](commands/inspection.md#locate) | Find installed content or prepared editing sources. | None. |
| [`compare`](commands/profiles.md#compare) | Compare two Claude Code profiles read-only. | None. |
| [`check-tool-hooks`](commands/profiles.md#check-tool-hooks) | Check that hooks other tools install for themselves are present. | None. |
| [`copy-profile`](commands/profiles.md#copy-profile) | Copy a Claude Code profile's reusable state into a new independent root. | None; writes only the new root. |
| [`recover`](commands/maintenance.md#recover) | Recover an interrupted target replacement. | None. |
| [`automation`](commands/automation.md#automation) | Run or preview device automation. | According to selected mode; no network in dry run. |
| [`startup`](commands/automation.md#startup) | Fail-open automatic-update callback. | According to due policies. |
| [`agent-hook`](commands/automation.md#agent-hook) | Emit instruction locations for the selected agent. | None. |
