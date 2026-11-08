---
name: idk-aem
description: Use AEM (agent-env-man) to configure agent integrations, manage catalogs, install or update managed skills and instructions, locate or publish their sources, and inspect or recover installations. Applies to AEM user operations rather than development of AEM itself.
---

# Use AEM

Use the installed `aem` CLI for the requested operation and preserve the user's selected catalog, machine configuration, and automation settings.
Choose the workflow by what the user wants to accomplish, then use its basic commands and sequencing.
This skill covers AEM operations; content editing follows the user's task and the content's applicable instructions.

## Prepare or install managed content

For first use, connect the requested agent or shell, bind the user's catalog, prepare its sources, then inspect and apply the installation plan.
For an already bound catalog, omit its path on subsequent bootstrap calls.

```bash
aem setup --agent codex --shell bash
aem bootstrap /absolute/catalog.toml
aem apply --dry-run
aem apply
```

### Connect agents and shells

Select only the agent and shell requested; Claude uses `--agent claude`, and the other supported shell is `zsh`.
A second profile of the same product is a named agent such as `--agent claude-lab` or `--agent codex-lab`, with its own default root.
`aem compare`, `aem copy-profile` and `aem check-tool-hooks` inspect, seed or check Claude Code profiles; read their help before use.

Codex and Claude use their own saved paths and hook formats.
Preserve unrelated settings and hooks.
Setup includes this official skill but does not install user catalog content or grant hook trust.

### Bind catalogs and prepare sources

For a Git catalog, replace the bootstrap example with `aem bootstrap --catalog-repository URL --catalog-path catalogs/personal.toml`.
For an external source, add `--external NAME=/absolute/source` to bootstrap.
Bootstrap prepares sources without updating existing checkouts or installing targets; apply installs from local prepared paths without fetching.

### Choose directory installation modes

General directories are independent of agent integrations and default to links under the saved `home` root.
A directory that declares `agent` instead installs below that destination's root and skips machines without it.
For custom destination roots, consult bootstrap help before preparing sources.
Use a link when writes at the installed path should reach the publish source; explicit `publish` gathers managed copy edits, and `publish --local` stops at local handoff.

For directories with symbolic links, consult the local directory configuration guidance for preservation and platform limits before choosing an installation mode.
Copy and detach preserve their target text, so relative referents may change after relocation; they do not produce dependency-free copies.

### Install newly declared content

To install newly declared content, use `aem bootstrap --item NAME`, then preview and apply the corresponding installation item with `aem apply --item ID --dry-run` and `aem apply --item ID`.
If a new skill is missing from an already prepared shared checkout but exists upstream, run `aem update NAME` before retrying bootstrap.
This also works when existing consumers are detached or excluded from automation.

Skill, directory and setting IDs are their catalog names; an instruction entry uses `NAME:entry`, which also selects its bundle and hook.
Omitting selectors prepares all declared sources and applies eligible items except personal hooks, which require explicit `apply --item NAME`.
For personal hook runtimes or removal, consult bootstrap or hooks help.
AEM does not install interpreters or grant native trust, and detach retains the hook group and its dependencies.

## Receive updates or inspect the installation

Inspection and updates are separate steps, and an update reaches the installation only as the following parts describe.

### Inspect status

For an inspection, use `aem status`; use global `--verbose` for detailed text or `--json` when later actions need to parse the report.
Read bootstrap JSON `items` for content names and kinds.
Historical failures remain available in verbose/JSON status and do not establish a current fault.
Status is offline; `aem status --refresh` fetches observations without advancing checkouts.

### Update a source and install it

To receive changes for a selected source and install them, use:

```bash
aem update NAME
aem apply --item ID --dry-run
aem apply --item ID
```

Update accepts catalog skill, directory, instruction, setting or personal hook names.
It also accepts catalog source names; use `source:NAME` when an item has the same name.
A source selection includes every consumer and receives all its shared settings into their stages.
Live links change immediately during update.
Copies need apply, and settings receive into their stage before apply changes the actual file.

For a complete source update followed by installation, use `aem sync`.
`sync --item ID` filters only installation: its update phase still visits all sources and must succeed before application starts.

### Update the catalog

If the catalog itself changed upstream, receive it with `aem catalog update`, then bootstrap newly declared sources and preview/apply their installation.
Content update and sync do not refresh the catalog.
Catalog updates, content updates, and AEM self-updates are separate operations.

## Edit managed content and share it

Locate the prepared source before editing, keep copies and sources distinct, and publish only when publication is requested.

### Locate and edit the source

For a skill, directory or instruction edit, locate its prepared source first and use the returned path as the explicit working directory for editing tools.
For inspection of the installed content instead, omit `--source`.
To locate an entire catalog source root, use `locate source:NAME --source`; `--repo` requires a Git source and locates its checkout root.
Source selectors are supported only by `locate --source`, `locate --repo`, and `update`; other commands retain item selection.

```bash
aem --json locate NAME --source
```

Before editing, identify and follow the guidance applicable to the located content, including referenced documents, using the user's and content's existing rules for discovery, scope, and precedence.
Locating content through AEM does not replace or waive that guidance.

### Installed copies and detached content

Installed copies and detached contents can differ from the source.
Explicit publication gathers selected managed copies by default; detached content is excluded.
Editing through an active link changes the source immediately.
For copies, edit the source, then preview and apply to refresh the installation.

For requested publication of installed-copy edits, preview collection with `publish NAME --dry-run` before proceeding.
Use `--source-only` when the request covers source edits alone.
Collection compares source and copy against their saved baseline and preserves active links' required paths.
Reconcile reported conflicts rather than bypassing them.

Catalog payload exclusions skip matching entries during inspection and copying, preserve excluded destination entries, and do not filter repository-wide Git commits.
Apply changed exclusion policies before collection.
Consult the local configuration guide for the global/source/item scopes and path rules.
Detached content, entry links, hooks, and actual application settings are not gathered.

### Publish content

When publication is requested, inspect all changes in the reported repository, then review and publish:

```bash
aem publish NAME --dry-run
aem publish NAME -m "Clarify guidance"
```

Publication acts on the entire selected repository, including files outside the selected content directory.
Supplying a message stages all nonignored changes; without a message, `aem publish NAME` pushes existing commits from a clean checkout.
Review unrelated edits and outgoing commits before selecting that scope.
Publication does not install content, and a request to locate or edit does not itself authorize publication.
External-source synchronization remains the responsibility of its existing service.
A preview is offline and cannot confirm remote state; a remote failure does not establish an empty remote.

### Edit and publish the catalog

For Git catalog edits, locate with `aem --json catalog locate`, edit the reported entry, and use `aem catalog publish --dry-run` followed by the authorized `aem catalog publish -m "Update catalog"`.
For copied external catalogs, consult catalog locate and publish help to distinguish the managed entry from its original.
Return edits to the original explicitly; ordinary use does not refresh or write the original.

## Change application settings

Settings use an editable stage between the shared source and actual application file.

### Edit a prepared setting

For an already prepared setting, locate the stage, edit its reported entry, then preview and apply:

```bash
aem --json locate NAME
aem apply --item NAME --dry-run
aem apply --item NAME
```

### Bind, collect, and share settings

For first preparation, bind the actual application file with `aem bootstrap --setting-target NAME=/absolute/app/config.toml`, supplying the catalog if it is not already bound.
To collect edits made in the application, use `aem settings collect NAME --dry-run`, then `aem settings collect NAME`.
Ordinary collection includes only already managed fields; consult the relevant help when adding or reclaiming fields with `--path`.

To gather stage edits locally, use `aem publish NAME --local` for a Git or external source.
Authorized `aem publish NAME -m "Update preferences"` also commits and pushes Git sources; external sources report local handoff only.
Publication never implicitly collects actual-file edits.

Removing a managed field from the stage requests deletion.
`aem settings release NAME --path '["section","key"]'` releases management while leaving the actual value in place.

## Configure automation or update AEM itself

Automation settings and AEM tool updates are separate operations, each inspected before it is changed.

### Configure automation

For automation changes, inspect `aem --json status` and choose the requested device mode and schedule before changing settings.
Use `aem automation --trigger EVENT --dry-run` to inspect the current mode's planned work for the requested `shell-start`, `agent-start`, or `interval` event.
When mode or schedule choices remain unresolved, consult setup help first, then the local automation guide only if more behavioral detail is needed.
For individual policies, use the relevant command help before consulting the guide as needed.
Check the selected mode's scope and exclusions before enabling automation.
Shared-source updates can affect live links even when their consumers are excluded from installation.
Collection, export, and publication remain explicit.

### Update or publish AEM itself

For an AEM tool update, inspect `aem self status`, then use `aem self update --dry-run` and the requested `aem self update`.
A queued update is not a completed update; check subsequent status for the result.
For full asynchronous startup, inspect status and start a fresh product session after completion to discover updated skills.

To publish AEM itself, use `aem self publish --checkout /absolute/aem-checkout --dry-run`, then the authorized invocation without `--dry-run`.
Self publication requires a clean committed release with its matching tag already prepared in Git.
Verify the reported checkout and destination.
It does not prepare a release or update the installation.

## Preserve contents during conflicts or removal

Investigate conflicts without changing contents, then recover or detach with the user's content preserved.

### Investigate conflicts

Inspect reported targets and ownership with `aem status` before resolving a conflict.
When an update, installation, collection, publication, or other operation fails because of a conflict, investigate and report the actual differences rather than stopping at the error message.
Start with the failed operation's diagnostics and relevant AEM status, location, comparison, or dry-run reports.
If they are insufficient or unavailable, use Git inspection and direct file or directory comparison as appropriate.
Try other available comparison methods when one fails, without changing the conflicting contents or bypassing ownership checks.

The comparison depends on the kind of conflict:

- **Git conflicts**: Distinguish staged, unstaged, and relevant untracked changes from committed local and incoming changes.
  Use a common ancestor when available to explain divergent histories.
  Identify the compared revisions and whether the remote observation is current or from the last fetch.
  Obtain a current observation without advancing the checkout when needed and accessible.
- **Source/copy conflicts**: Compare the actual source and installed copy, including additions, deletions, and relevant type or link-target differences.
  Use a saved baseline for attribution only when its contents are available; hashes alone do not explain what changed.
- **Settings conflicts**: Compare the affected fields across the shared source, editable stage, and actual application file as relevant to the failed operation.
  Use available baseline values to distinguish each side's edits.

### Report differences

Report the failed operation and reason, comparison paths or revisions and baseline, affected files or fields, and the key substantive differences in a concise summary.
Do not include full diffs or create separate diff artifacts unless requested.
When a comparison remains unavailable, report the methods attempted, the limitation, and any partial findings; do not infer missing contents or treat an unavailable remote as unchanged.
Difference investigation does not authorize conflict resolution or replacement.

### Recover interrupted operations

After an interrupted replacement, use `aem recover` before retrying.
Preserve local changes, state, and recovery backups; do not delete state, reset checkouts, or adopt/replace content merely to bypass a diagnostic.
Use explicit item selections for intentional adoption, replacement, or reattachment, checking the relevant help when needed.

### Detach or remove integrations

To keep installed contents while releasing management, preview with `aem detach ID --dry-run`, then run `aem detach ID`.
For independent instruction copies, select both `NAME:bundle` and `NAME:entry`.
Detach does not restore pre-installation contents; instruction detach retains hook configuration.
For integration removal or uninstalling, follow the local maintenance guide to detach managed content and handle retained hooks before removing the requested integrations.

## Resolve only the missing detail

Use these basic workflows directly when they answer the task; do not make help or documentation reading a prerequisite for every operation.
Consult help first and the installed documentation only when help does not resolve the question.

### Use command help

When an unfamiliar operation, uncertain selector/option, version difference, or diagnostic leaves a decision unresolved, inspect the relevant `aem COMMAND --help` first.
Use `aem --help` when the command itself is unclear; for grouped commands, read group help only if the needed subcommand is unclear.
Reuse already verified help and documentation for the same installed runtime; recheck after a runtime change or an incompatibility.

### Use the installed documentation

If help does not resolve the question, run `aem docs` to locate the installed README and follow its local documentation index to the relevant guide:

| Unresolved task detail | Local guide reached through the documentation index |
| --- | --- |
| Exact options, selection scope, or report fields | Command reference, then the matching command group |
| Catalog declarations, directory link preservation, machine bindings, or defaults | TOML configuration reference, then the matching topic |
| Instruction bundle installation and hook trust | Personal instruction bundles, then the installation or hook guide |
| Settings field selection, deletion/release, or conflicts | Staged settings |
| Device modes, schedules, or asynchronous tool updates | Automation and AEM updates |
| Ownership conflicts, recovery, integration removal, or uninstalling | Maintenance and recovery |
| Separate agent destinations and setting stages | Named agent instances |
| Agent paths, hook formats, or session reload behavior | Agent profile contracts |

### Pass global options

Global `--config PATH`, `--json`, and `--verbose` precede the command; `--json` and `--verbose` are mutually exclusive.
Preserve the user's chosen machine configuration on every call.
Use installed-version help and documentation rather than assuming options are shared between subcommands.
Treat missing or incomplete advertised materials as an installation or documentation issue.
