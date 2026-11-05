# Inspection command reference

These offline entry points locate documentation, report installation state, and distinguish installed content from its source.
Only explicit status refresh requests remote observations.

## docs

```text
aem [--json] docs
```

Print the absolute path to the bundled README.md.
With global `--json`, return `root` (the local documentation directory) and `entry` (the README path).
The directory also contains docs/, examples/, and LICENSE.txt with working relative links.
Lookup is offline and independent of machine configuration, catalogs, state, and setup integrations.
Editable/source development resolves to the repository's canonical documentation.

## status

```text
aem status [--agent AGENT] [--refresh] [--git-timeout TIMEOUT]
```

Reports local checkout observations, last observed remote state, ownership, and startup outcomes.
`--refresh` fetches remote references without moving checkout branches or installing content.
`--agent` filters installation observations, not source fetching.
Saved installed targets are still inspected if the catalog or source is unavailable.
Deleting a declaration leaves its target and ownership intact, reported as orphaned.
If strict machine/state validation fails, offline status returns `saved_only: true`, `state_version`, the validation error, and saved item IDs with filesystem observations.
This fallback does not interpret obsolete modes or claim that saved items match current declarations.
It never fetches; `--refresh` does not use the fallback.

## locate

Locates saved installations or explicitly selected sources, including editable setting stages.

```text
aem locate NAME [--agent AGENT] [--source | --target] [--repo] [--cd]
```

Use `--cd` to change the current shell directory after registering the shell integration with `aem setup --shell bash`, `--shell zsh`, or `--shell powershell` and reloading the profile.
It moves to the selected content root; `--source --cd` moves to the prepared source, while `catalog locate --cd` moves to the directory containing the catalog entry.
Use `--repo --cd` to move to the source Git checkout root rather than the item's content subdirectory.
Without the shell integration, `--cd` prints only the absolute directory path, so Bash/Zsh can also use `cd -- "$(aem locate NAME --cd)"`.
The option cannot be combined with `--json`.
Lookup failures leave the shell directory unchanged; help still prints normally.
Existing shell registrations need setup run again to install this function.

The agent defaults to `codex`; NAME is a catalog skill, directory, instruction bundle, setting, or personal hook name; directory and setting locations do not depend on an agent.
With `--source` or `--repo`, NAME may also be a catalog source name; `source:NAME` explicitly selects a source when names collide.
Bare names prefer existing catalog item names, preserving their content-subdirectory lookup.
Source-name lookup selects the source root, is agent-independent, and does not require consumer payloads; `--source` accepts Git and external sources, while `--repo` requires Git.
Basic installed lookup and `--target` do not accept source selectors.
By default, returns `root`, `entry`, `installed_root`, and `detached` from the selected agent's saved installation when one exists.
For skills, `entry` is SKILL.md, and `location` distinguishes a linked source from a copy.
For directories, both `root` and `entry` identify the directory; no entry file is required.
An installed copy or detached item resolves to its preserved local contents, not the publish source.
Saved lookup works without loading the catalog or validating installation fields, accepts state versions 1 and 2, and never changes ownership.
Missing or redirected entries and replaced active links are errors; a broken installation never silently falls back to its source.

### Prepared source lookup

If no saved installation exists for the selected agent, locate resolves the prepared source from the current catalog.
Use `--source` to request that source explicitly even when a copy, detached item, or broken installation exists.
Source lookup returns `location: "source"`, `root`, `entry`, `checkout` (null for external folders), `repository`, and all source names sharing the checkout in `members`.
It sets `installed_root` to null and `detached` to false because it describes the source, not an installation.
It requires a valid current machine/catalog configuration and existing source content; it does not clone or fetch.
Git source lookup validates the registered repository and branch but allows uncommitted edits.
Use the returned root/entry to edit, then `publish NAME` for Git content; external synchronization stays outside AEM.

### Repository and named source lookup

Use `--repo` to locate the current catalog item's prepared source Git checkout root, independently of installed copies, detached contents, and the selected agent.
It can be combined with `--source`, but not `--target`; external folder sources are rejected even if the folder happens to be in a Git repository.
Repository lookup returns `root`, `entry`, and `checkout` all identifying the checkout directory, plus `repository`, `members`, `location: "source"`, `installed_root: null`, and `detached: false`.
It requires valid current configuration and a prepared checkout matching the registered Git URL and branch, permits uncommitted edits, and does not clone or fetch.
When a named Git source omits its branch, lookup uses the prepared branch recorded by bootstrap for that source's repository and checkout path, even after its last consumer is removed.
Older consumer-only records remain usable while their consumers are declared; rerun bootstrap before removing the last consumer to retain the source binding.
Missing or conflicting records require bootstrap with a consumer, or an explicit `sources.NAME.branch` when none remain; lookup never adopts the checkout's current branch or fetches to discover one.
The item's payload may be missing: repository lookup validates the checkout rather than its content entry.
For named-source lookup with `--source`, the same root-level report is returned, with `checkout` and `repository` set to null for an external source.

```bash
aem locate source:tools --source --cd  # Enter the entire source root.
aem locate source:tools --repo --cd    # Require a Git source and enter its root.
aem update source:tools               # Update the source and receive all its settings stages.
```

Source selectors are limited to `locate --source`, `locate --repo`, and `update`; installation, ownership, publication, and individual settings commands continue to select items.

```bash
aem locate report --source
# Edit the returned entry or other files under root.
aem publish report -m "Clarify guidance"
```

For an opted-in shared instruction bundle, participating agents resolve the same installed root.
Saved entries retain the bundle reference, so lookup and callbacks remain usable without the catalog or source.
The existing default agent selection still applies.

Instruction callbacks continue to use saved instruction installations only, without catalog fallback or source lookup.
