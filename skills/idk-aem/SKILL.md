---
name: idk-aem
description: Use AEM (agent-env-man) to configure agent integrations, manage catalogs, install or update managed skills and instructions, locate or publish their sources, and inspect or recover installations. Applies to AEM user operations rather than development of AEM itself.
---

# Use AEM

Use the installed `aem` CLI for the requested operation and preserve the user's selected catalog, machine configuration, and automation settings.
Choose the workflow by what the user wants to accomplish, then run the relevant basic commands below.
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

Select only the agent and shell requested; Claude uses `--agent claude`, and other supported shells are `zsh` and `powershell`.
Codex and Claude use their own saved paths and hook formats; preserve unrelated settings and hooks.
Setup includes this official skill but does not install user catalog content or grant hook trust.
For a Git catalog, replace the bootstrap example with `aem bootstrap --catalog-repository URL --catalog-path catalogs/personal.toml`.
For an external source, add `--external NAME=/absolute/source` to bootstrap.
General directories use a required named target root bound with `--root NAME=/absolute/parent`; they are independent of agent integrations and default to links.
Use a link when writes at the installed path should reach the publish source; copy edits reach it only through explicit `publish --from-copy`.
Bootstrap prepares sources without updating existing checkouts or installing targets; apply installs from local prepared paths without fetching.

To install newly declared content, use `aem bootstrap --item NAME`, then preview and apply the corresponding installation item with `aem apply --item ID --dry-run` and `aem apply --item ID`.
Skill, directory and setting IDs are their catalog names; an instruction entry uses `NAME:entry`, which also selects its bundle and hook.
Omitting selectors prepares all declared sources and applies eligible items except
personal hooks: register those only with explicit `apply --item NAME`. Bind a
requested interpreter with bootstrap `--runtime NAME=/absolute/executable`; AEM
never installs it or grants native trust. Remove an unchanged saved personal
group using `aem hooks remove NAME --dry-run`, then without preview. Detach retains
the group and its source/runtime dependency.

## Receive updates or inspect the installation

For an inspection, use `aem status`; add global `--json` when later actions need to parse the report.
Status is offline; `aem status --refresh` fetches observations without advancing checkouts.
To receive changes for a selected source and install them, use:

```bash
aem update NAME
aem apply --item ID --dry-run
aem apply --item ID
```

Update accepts catalog skill, directory, instruction, setting or personal hook names.
Live links change immediately during update; copies need apply, and settings receive into their stage before apply changes the actual file.
For a complete source update followed by installation, use `aem sync`.
`sync --item ID` filters only installation: its update phase still visits all sources and must succeed before application starts.

If the catalog itself changed upstream, receive it with `aem catalog update`, then bootstrap newly declared sources and preview/apply their installation.
Content update and sync do not refresh the catalog.
Catalog updates, content updates, and AEM self-updates are separate operations.

## Edit managed content and share it

For a skill, directory or instruction edit, locate its prepared source first and use the returned path as the explicit working directory for editing tools.
For inspection of the installed content instead, omit `--source`.

```bash
aem --json locate NAME --source
```

Before editing managed content, inspect the located source directory and each parent directory up to and including the reported repository checkout root for applicable contribution and writing guidance.
Read relevant guidance and follow its referenced documents according to their stated scope and the user's instruction hierarchy; directory placement alone does not establish precedence.

Installed copies and detached contents can differ from the source; ordinary publishing does not collect their edits.
Editing through an active link changes the source immediately.
For copies, edit the source and apply after committing to refresh the installation.
To share edits made in an installed, managed skill or directory copy, use `aem publish NAME --from-copy --dry-run`, then authorized `aem publish NAME --from-copy -m "Share copy edits"` for Git, or omit the message for an external source.
Collection refuses differing changes on both sides and reports source/copy paths and Git comparison arguments; inspect and reconcile them rather than replacing content to bypass the conflict.
It also preserves affected active links' required paths and file kinds, including saved links removed from the catalog; reconcile the copy or explicitly detach the affected item before intentional removal.
External completion confirms local source handoff only; detached content, instruction bundles, hooks, and actual settings are not collected by this option.
`locate --cd` requires registered shell integration and a reloaded profile; do not assume shell navigation persists between tool subprocesses.

When publication is requested, inspect all changes in the reported repository, then review and publish:

```bash
aem publish NAME --dry-run
aem publish NAME -m "Clarify guidance"
```

Publication acts on the entire selected repository, including files outside the selected content directory.
Supplying a message stages all nonignored changes; without a message, `aem publish NAME` pushes existing commits from a clean checkout.
Review unrelated edits and outgoing commits before selecting that scope.
For catalog edits, locate with `aem --json catalog locate`, edit the reported entry, and use `aem catalog publish --dry-run` followed by the authorized `aem catalog publish -m "Update catalog"`.
Publication does not install content, and a request to locate or edit does not itself authorize publication.
External-source synchronization remains the responsibility of its existing service.
A preview is offline and cannot confirm remote state; a remote failure does not establish an empty remote.

## Change application settings

Settings use an editable stage between the shared source and actual application file.
For an already prepared setting, locate the stage, edit its reported entry, then preview and apply:

```bash
aem --json locate NAME
aem apply --item NAME --dry-run
aem apply --item NAME
```

For first preparation, bind the actual application file with `aem bootstrap --setting-target NAME=/absolute/app/config.toml`, supplying the catalog if it is not already bound.
To collect edits made in the application, use `aem settings collect NAME --dry-run`, then `aem settings collect NAME`.
Ordinary collection includes only already managed fields; consult the relevant help when adding or reclaiming fields with `--path`.
To share stage edits, use `aem export NAME` for a Git or external source, or authorized `aem publish NAME -m "Update preferences"` for export, commit, and push to Git.
Publication never implicitly collects actual-file edits.
Removing a managed field from the stage requests deletion; `aem settings release NAME --path '["section","key"]'` releases management while leaving the actual value in place.

## Configure automation or update AEM itself

For automation changes, inspect `aem --json status` and choose the requested device mode and schedule before changing settings.
Use `aem automation --dry-run` to inspect the current mode's planned work.
When mode or schedule choices remain unresolved, consult setup help first, then the local automation guide only if more behavioral detail is needed.
For individual policies, use the relevant command help before consulting the guide as needed.
Directories share the skill update policy system and participate in full runs, preserving empty-trigger exclusions and detach.
Settings have independent automatic sync policies and participate by default in full runs, receiving then applying changes while preserving conflicts, explicit exclusions, and detach.
Collection, export, and publication remain explicit.

For an AEM tool update, inspect `aem self status`, then use `aem self update --dry-run` and the requested `aem self update`.
A queued update is not a completed update; check subsequent status for the result.
For full asynchronous startup, inspect status and start a fresh product session after completion to discover updated skills.
To publish AEM itself, use `aem self publish --checkout /absolute/aem-checkout --dry-run`, then the authorized invocation without `--dry-run`.
Self publication requires a clean committed release with its matching tag already prepared in Git; verify the reported checkout and destination.
It does not prepare a release or update the installation.

## Preserve contents during conflicts or removal

Inspect reported targets and ownership with `aem status` before resolving a conflict.
After an interrupted replacement, use `aem recover` before retrying.
Preserve local changes, state, and recovery backups; do not delete state, reset checkouts, or adopt/replace content merely to bypass a diagnostic.
Use explicit item selections for intentional adoption, replacement, or reattachment, checking the relevant help when needed.

To keep installed contents while releasing management, preview with `aem detach ID --dry-run`, then run `aem detach ID`.
For independent instruction copies, select both `NAME:bundle` and `NAME:entry`.
Detach does not restore pre-installation contents; instruction detach retains hook configuration.
For integration removal or uninstalling, follow the local maintenance guide to detach managed content and handle retained hooks before removing the requested integrations.

## Resolve only the missing detail

Use these basic workflows directly when they answer the task; do not make help or documentation reading a prerequisite for every operation.
When an unfamiliar operation, uncertain selector/option, version difference, or diagnostic leaves a decision unresolved, inspect the relevant `aem COMMAND --help` first.
Use `aem --help` when the command itself is unclear; for grouped commands, read group help only if the needed subcommand is unclear.
Reuse already verified help and documentation for the same installed runtime; recheck after a runtime change or an incompatibility.

If help does not resolve the question, run `aem docs` to locate the installed README and follow only its relevant local links:

| Unresolved task detail | Local guide linked from the README |
| --- | --- |
| Exact options, selection scope, or report fields | Command reference |
| Catalog declarations, machine bindings, or defaults | TOML specification |
| Instruction bundle installation and hook trust | Instruction walkthrough |
| Settings field selection, deletion/release, or conflicts | Staged settings |
| Device modes, schedules, or asynchronous tool updates | Automation and AEM updates |
| Ownership conflicts, recovery, integration removal, or uninstalling | Maintenance and recovery |
| Agent paths, hook formats, or session reload behavior | Agent profiles |

Global `--config PATH` and `--json` precede the command; preserve the user's chosen machine configuration on every call.
Use installed-version help and documentation rather than assuming options are shared between subcommands.
Treat missing or incomplete advertised materials as an installation or documentation issue.
