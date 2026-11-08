# Setup command reference

Use `setup` to connect or remove shell and agent integrations and save device policies.

## setup

Connect selected shells and agents, or change machine policies without registering integrations.
Omitted selections and policy fields retain their saved values.

```text
aem setup [--shell SHELL ...] [--agent AGENT ...]
          [--remove-shell NAME ...] [--remove-agent NAME ...]
          [--executable PATH] [--self-update MODE] [--dry-run]
          [--update-repository URL] [--update-python PATH] [--update-uv PATH]
          [--update-tool-dir PATH] [--update-bin-dir PATH]
          [--catalog-trigger TRIGGER ...] [--catalog-interval SECONDS]
          [--catalog-git-timeout SECONDS] [--startup-hook-timeout SECONDS]
          [--automation off|policies|full] [--automation-trigger EVENT ...]
          [--automation-interval SECONDS] [--automation-git-timeout SECONDS]
```

### Integration selection

The selection rules for shells, agents, and policy-only calls are:

- Shell choices are `bash` and `zsh`.
- Selections accumulate; omitted selections remain saved, and repeated setup avoids duplicate blocks/groups.
- Initial integration setup requires at least one shell or agent selection.
- **Callback duration**: `--startup-hook-timeout` may also be saved before agents are registered; with saved agents, setup updates their managed startup groups.
  Omission retains the saved value, defaulting to ten seconds.
  It does not change instruction-location hooks or Git phase limits.
- A call supplying only catalog/device automation policy options (and optionally `--dry-run`) can save policy without registering integrations or requiring an executable.
- Adding and removing the same integration in one call is invalid.

`--executable` overrides the saved absolute executable path, otherwise it defaults beside the running Python interpreter.
Setup edits startup integrations, links the packaged `idk-aem` skill for selected agents, and saves machine selections; it does not bootstrap or apply user catalog content.

### Official skill installation

General integration setup refreshes the official links of saved agents; shell-only initial setup and policy-only edits do not install official skills.
Official skills use links without automatic fallback to copies; platforms without symlink privileges report an official skill failure.
Unmanaged targets, changed links, overlapping ownership or catalog targets, and local source edits within the recorded package version skip that official skill without preventing core shell/hook setup and machine selection storage.
Core setup completes first; each ancillary skill attempt is reported separately in the additive `official_skills` array, leaving the existing `integrations` results unchanged.
Recoverable skill failures keep setup's successful exit status; shared-state errors and unresolved recovery still fail the command.
Official skill records are setup-owned and do not enter content command selection.

### Update policies

`--self-update` saves `off`, `compatible`, or `breaking`; omission preserves the saved mode.
The `--update-*` options register the release source and external installer runtime described in [Configuration](../configuration/automation.md#aem-self-update-settings).
Enabling updates requires runtime registration; the repository installer supplies those paths.
Changing self-update settings does not immediately update the package.
`--catalog-trigger` sets `manual` or a supported event; repeat it to replace the complete saved trigger list.
`--catalog-interval` sets the finite nonnegative attempt interval, and `--catalog-git-timeout` sets the finite positive per-Git-phase timeout.
Omitted policy options preserve their saved fields; configuring events requires a bound Git catalog.
Policy-only edits validate machine settings and use the configuration journal without reading or rewriting profiles, even when those profiles contain local edits.
They do not fetch, run automatic updates, or register startup integrations; the result includes the effective `catalog_update` policy.

### Removal and previews

Removing an agent requires first detaching its managed content.
Machine `settings` bindings that name the removed agent stay in the machine file; while the catalog declares that setting with the same `agent`, remove the binding as well, or every catalog load refuses it.
Dry run writes no files, including lock files.
When only `--remove-shell` / `--remove-agent` selections are supplied, setup uses saved ownership instead of validating installation declarations.
Removal accepts retired integration names and old state versions 1/2; unknown machine fields and unselected records are preserved.
It removes only the selected saved blocks/groups, unchanged official skill links, and corresponding selections, without rebuilding other integrations.
Changed official links, locally edited official sources, or substituted copies are preserved with ownership released; their `official_skills` result has `action = "preserve"` and the remaining `target` path.
Each official skill result uses `integration = "agent-skill:AGENT"`, `target`, and `action` (`write`, `unchanged`, `remove`, `preserve`, or `failed`).
A failed attempt adds `error` and a retry instruction in `next`; existing ownership and content remain intact, and other agents' skill attempts continue independently.
Removal also completes core integration removal before ancillary skill attempts; a failed official link removal can be retried using the same `--remove-agent` selection even after that agent selection has been removed.
A supplied `--executable` is ignored on removal-only calls; no executable or current agent profile is needed.
Locally edited selected blocks/groups, redirected targets, malformed records, and pending recovery still stop removal.
Calls that also add a shell/agent or change self-update/catalog policy settings retain full installation validation.
Device automation options save the [mode and full-run schedule](../configuration/automation.md#device-automation-settings), preserving omitted fields and replacing supplied trigger lists.
Changing these settings alone does not execute a run or rewrite profiles.
Initial interactive installation offers the device mode before tool release permission; unattended omission defaults to the existing `policies` behavior.
The repository installer `python scripts/setup.py` installs AEM using uv and delegates integration to this command; it is not an additional AEM subcommand.
