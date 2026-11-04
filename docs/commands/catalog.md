# Catalog command reference

Bootstrap binds a catalog and prepares local sources; catalog commands inspect, receive, and publish that catalog independently of its content.

## bootstrap

Binds a catalog, saves device paths, and prepares selected sources without installing content.

```text
aem bootstrap [CATALOG | --catalog PATH] [--catalog-copy] [--checkout-root PATH]
              [--catalog-repository URL --catalog-path RELATIVE_PATH [--catalog-branch BRANCH]]
              [--root NAME=PATH ...] [--external NAME=PATH ...]
              [--setting-target NAME=PATH ...] [--runtime NAME=PATH ...]
              [--item NAME ...] [--git-timeout TIMEOUT]
              [--catalog-trigger TRIGGER ...] [--catalog-interval SECONDS]
              [--catalog-git-timeout SECONDS]
```

### Catalog binding

Omit the catalog argument to reuse the saved binding.
For an explicit local file, add `--catalog-copy` to prepare an editable managed copy; this flag cannot be combined with Git registration.
Reusing a copy binding never refreshes from the external original; use `catalog update` explicitly.
A copied catalog and its machine binding are published together only after validation, with recovery through `recover`.
A positional catalog and `--catalog` cannot both be supplied.
Bootstrap accepts the same catalog policy options as setup, allowing initial Git registration and automatic policy selection in one call.
Omitted options retain saved policy fields, and repeated triggers replace the saved list.
Policy validation precedes cloning or configuration writes; enabling events for a local catalog is rejected.
`--catalog-git-timeout` controls future automatic updates; `--git-timeout` controls the current bootstrap delivery.
Git catalog registration requires `--catalog-repository` and `--catalog-path` together, optionally with `--catalog-branch`; these cannot be combined with a local catalog argument.
`--catalog-path` is relative to the repository root, not the working directory, and must identify a tracked regular TOML file.
Repository syntax matches catalog repository declarations: a URL, SSH location, or absolute local repository path.
The default branch is discovered and written to the machine binding; repeating registration for the same repository without `--catalog-branch` retains the recorded branch.

### Device paths and content selection

Catalog, checkout-root, and external CLI paths resolve relative to the working directory and are saved as absolute paths.
Root paths must be absolute or begin with `~/`.
Bootstrap fills missing `skills`, `agent`, and `home` root bindings, preserving saved values and explicit `--root` bindings.
An explicit `skills` or `agent` binding that would move the Codex binding of active setup integrations is refused.
Remove them with `setup --remove-agent codex` before relocating, then run setup again.
An unbound `home` is saved as the current user's absolute home directory; use `--root home=PATH` to choose another initial path.
Directories without `install.root` use this saved `home` root.
Apply and status use saved bindings without inferring a missing home path.
Repeated `--external` binds declared external names; duplicate names in one invocation are invalid, and omitted saved bindings remain.
`--item` selects catalog skill, directory, instruction, setting or personal hook names for preparation, not ownership IDs or repository names.
No selection prepares all declared sources.
Missing repositories are cloned and validated; existing checkouts are validated without pulling or resetting.
If a newly declared skill is missing from an existing checkout but available upstream, run `aem update NAME`, then `aem bootstrap --item NAME`, `aem apply --item NAME --dry-run`, and `aem apply --item NAME`.
Update validates the incoming skill before advancing the shared checkout and refuses dirty or divergent history; it does not reinstall detached consumers.
A failed content download leaves the machine binding saved so bootstrap can be retried.
Content installation and updates require catalog `version = 2`; see the [syntax reference](../configuration/catalog.md#catalog) and [manual transition](../removed-interfaces.md#catalog-v2-transition).
Saved-state maintenance stays available with an old catalog.

### Preflight and retry

For a local catalog, declaration and ownership preflight failures do not save a new binding or contact repositories.
For a missing Git catalog, bootstrap must clone the catalog into a temporary directory before validating its declarations and current ownership.
It publishes that checkout and saves the binding only after preflight succeeds, then prepares content repositories.
Failed catalog download or validation preserves the previous binding and leaves no new catalog checkout; fix the input or remote and repeat the registration command.
An interrupted machine-file save may leave a validated checkout that the same registration can reuse.
Existing machine settings and omitted external/root bindings are preserved.

### Bootstrap result fields

The JSON result adds `items`, an ordered array of preparation and settings-stage results.
Each item has `name` (the catalog content name), `kind` (`skill`, `instruction`, `directory`, `setting`, or `personal-hook`), `phase` (`source` for content preparation or `stage` for settings-stage preparation), and the original status and applicable path, checkout, stage, or error fields.
Separate operations for the same content remain separate results, including source preparation and settings-stage preparation.
The result retains `skills`, `config`, and `next` for compatibility.
The legacy `skills` array preserves its existing values and order, including non-skill results and their historical `skill`, `directory`, `setting`, or `source` identity keys.
Non-skill entries additionally carry their actual `kind` and a `compatibility_note` directing consumers to `items`.
There is no scheduled removal of the legacy fields; new consumers should read `items`.
Other ordinary command results add `kind` to identifiable content rows using already loaded declarations or saved ownership, without changing source/repository result identity or forcing catalog reads during maintenance.
Text output uses the canonical items and omits the legacy duplicate in both default and verbose mode.
For Git bindings it also includes `catalog`, with `status` (`cloned` or `already-prepared`), absolute `checkout` and `entry` paths, `repository`, resolved `branch`, and `revision`.


## catalog

Inspects, updates, or publishes the bound catalog without installing its declarations.

```text
aem catalog status [--git-timeout TIMEOUT]
aem catalog locate [--git-timeout TIMEOUT] [--source] [--cd]
aem catalog update [--git-timeout TIMEOUT]
aem catalog auto --trigger EVENT [--dry-run]
aem catalog publish [-m MESSAGE | --message MESSAGE] [--from-copy] [--dry-run] [--git-timeout TIMEOUT]
```

### Inspection and location

These commands select the bound catalog, independently of the skill/instruction namespace.
They never install content or run content automatic policies.
`status` and `locate` are offline and do not change saved state; their Git subprocesses still respect `--git-timeout`.
`status` reports the entry, checkout, repository, `status` (`ready`, `unavailable`, or `unbound`), and `automation` (the last automatic attempt, or an empty object).
For Git catalogs it also reports the branch, current revision, local changes, tracked diff, outgoing commits, and remote relation at the last fetch, using the same fields as publication inspection.
Catalog reading/inspection failures appear as `error` with status `unavailable` and exit 0; machine/state loading failures still exit 1.
`locate` returns absolute `entry`, `checkout`, and `repository`; the latter two are null for a local catalog.
Locate validates Git identity and the tracked file but does not parse its TOML or require cleanliness, so it can locate a malformed file for repair.
`--source` selects a copied catalog's external original, including when unavailable; other binding types keep their existing entry.
`--cd` uses the selected entry directory through the existing shell integration.

### Local copy update and publication

For a [local copy binding](../configuration/machine.md#copied-local-catalog-binding), `catalog update` validates and receives the original without installing its declarations.
`catalog publish --from-copy` validates and returns copy edits to that external file; omitting `--from-copy` or supplying `--message` is an error.
Direct local bindings still do not support update/publication; Git bindings reject `--from-copy`.
Source-only changes leave a stale copy untouched during publication; copy-only changes are preserved during update.
Different changes on both sides stop with source/copy paths and comparison arguments; reconcile manually and retry.
Publication `--dry-run` is read-only, including the common baseline.
The external original must exist; AEM does not recreate missing originals or contact a synchronization service.

Copy reports add `source` and `copy` absolute paths, while `checkout` and `repository` remain null in status/location results.
Copy bootstrap reports `catalog.status = prepared` with `entry`, `source`, and `copy`.
Status keeps `ready` for a usable copy even without its original, reporting `source_available` and, on failure, `source_error` separately.
Available comparison fields are `baseline_hash`, `source_hash`, `copy_hash`, `source_modified`, `copy_modified`, and `conflict`; missing baseline metadata is reported as `baseline_error`.
Update/publication report `planned` for previews, `updated`/`published` for writes, `unchanged` for no write, or `failed` with `error` and exit 1.
Their comparison includes `changed`, `stale` (source-only changes), `local_edits` (copy-only changes), and `compare` arguments when observations succeed.
Successful publication reports `collection_complete = true` and `transport_complete = false`; it confirms local handoff only.

### Git update and publication

For Git catalogs, `update` requires a clean checkout on the recorded branch with the expected origin.
It fetches that branch, validates the incoming tracked UTF-8 TOML, declarations, machine bindings, target paths, and existing ownership, then fast-forwards only after all checks pass.
Dirty, local-ahead, diverged, misidentified, detached, or unfinished checkouts are refused without reset or merge reconciliation.
Validation failures leave the previous HEAD and working catalog intact, although fetched references and observations may change.
No newly declared content is cloned or installed by this command.
Use `bootstrap`, then `apply --dry-run` / `apply`, after adding declarations.
Removed declarations leave existing installations and ownership intact; path/mode changes for owned items require detach first.
New required external paths must be bound in the machine file before the catalog update can pass validation.

For Git catalogs, `publish` uses the [content publication rules](publish.md), but selects the whole catalog repository.
The working catalog must pass declaration and ownership validation before publication.
Dry run reports the checkout, entry, repository, branch, changed files, tracked diff, outgoing commits, and last-fetched relation without fetching, staging, committing, pushing, or recording attempts.
With a message it commits all nonignored changes, including files outside the catalog path; without a message it pushes existing commits from a clean worktree.
Fetch precedes staging, behind/diverged histories are refused, and only the registered branch is pushed without force.
A failed push retains the local commit so publication can be retried without a message.
Publication never applies declarations or collects installed-copy edits.

Update and publish return one JSON object with `checkout`, `entry`, `repository`, `branch`, and `status` (`updated`, `planned` for dry run, `published`, or `failed`).
Operation failures include `error` and exit 1; binding/precondition errors may use stderr instead.
Update includes `previous_revision`, `observed_revision`, and `last_fetch` once fetched, and `revision` / `last_update` after success.
Publish uses the [inspection/result fields](#inspection-and-location) and adds `created_commit` when it commits, and `revision`, `observed_revision`, `last_fetch`, and `last_publish` after successful publication.
Fetch/publication observations are saved separately from content ownership and automatic attempt clocks.
Direct local catalog bindings reject update and publish; use a Git binding or the explicit local copy workflow to manage delivery.

### Catalog automation

`auto` runs the machine's [catalog policy](../configuration/automation.md#catalog-automatic-update-settings) for the supplied event.
It shares update's validation and fast-forward behavior and does not prepare or install content.
Its JSON object contains the effective `policy` and `status`: `not-triggered`, `throttled`, `planned` (dry run), `updated`, or `failed`.
An executed update includes its ordinary result as `outcome`; failures before that result exists include `error`.
Failed automatic operations exit 1; skipped, planned, and successful work exit 0.
Dry run does not fetch or record an attempt, although ordinary command locks may be created.
Pending recovery blocks due work.

`automation` contains `binding` (`repository`, `branch`, `entry`), `last_attempt` (Unix seconds), `trigger`, and `status` (`running`, `updated`, or `failed`).
Successful attempts also include `last_success`; failed attempts include `error`.
The same saved record appears as `catalog_automation` in ordinary status, separately from skill clocks and catalog delivery observations.

Content `update`, `sync`, `auto`, and `status --refresh` never fetch or advance the catalog repository.
Bootstrap validates an existing catalog checkout without pulling it.
