# Publication command reference

The `publish` command gathers selected managed copies and settings stages, then shares source edits.
Its Git scope is the entire selected repository, independently of installation item boundaries.

```text
aem publish NAME [NAME ...] [-m MESSAGE | --message MESSAGE]
            [--local | --source-only] [--from-copy] [--dry-run] [--git-timeout TIMEOUT]
```

Edit the prepared checkout directly, or edit through an installed link pointing to it.
Select catalog skill, directory, instruction bundle, or setting names, not ownership IDs or repository aliases:

```bash
aem publish report personal --dry-run
aem publish report personal -m "Clarify report and instruction guidance"
```

The optional dry run is offline and shows checkout paths, every inventory member sharing each checkout, changed files, the tracked diff against HEAD, and outgoing commit IDs/subjects relative to the last fetched remote reference.
Untracked files appear in the changed-file listing; their contents are not included in the diff.
Review full existing commit patches with Git in the reported checkout when needed.
Dry run does not stage, commit, push, fetch, or update ownership/source records.
Its remote comparison can be stale; actual publication fetches before staging.

## Local gathering and source-only publication

`publish NAME... --local` gathers selected copies and settings stages into their local Git or external sources without fetching, committing, or pushing.
`export NAME...` is an alias for this operation, with the same grouped result format.
Local gathering does not require a message and cannot be combined with `--message`.
Use `--dry-run` with either spelling to preview without writes.

`publish NAME... --source-only` publishes existing source edits without gathering copies or settings stages.
Use it when sharing edits made directly in the source while keeping installed edits local.
It cannot be combined with `--local` or `--from-copy`.
All variants retain the same ownership and conflict checks for the work they perform.

## Repository scope and Git safeguards

Selection chooses whole repositories, not file scopes.
Each shared checkout is processed once, even if several selected skills or bundles reference it.
With `-m`, all nonignored changes in that checkout are staged and committed, including deletions, untracked files, previously staged changes, and changes outside declared skill directories.
The same message is used for each selected checkout needing a commit.
AEM reports the repository scope but does not determine whether unrelated files belong in the commit or outgoing history.
Without `-m`, publish requires no uncommitted changes and pushes existing commits.
No interactive confirmation or editor is required; use the optional dry run for review and supply a message when committing.

Publication uses the configured Git identity and signing settings, the registered origin URL, and the inventory branch (or the default branch recorded at bootstrap).
As with other AEM Git operations, repository Git hooks are disabled and authentication cannot prompt.
Only the selected branch is pushed, without force, additional branches, or tags; a different origin push URL is rejected.
Before staging or committing, AEM successfully queries all advertised remote refs, including tags.
If no refs exist, the remote is treated as empty and AEM pushes the local registered branch for the first time, without requiring a pre-existing remote branch.
With `-m`, this includes committing checkout changes; without `-m`, the checkout must be clean with an existing local commit.
If the remote contains refs, the registered branch must exist and AEM fetches it before checking history.
Authentication, network, ref-listing, and fetch errors stop publication; they never trigger an initial-push fallback.
Dry runs remain offline and cannot confirm whether a remote is empty.
Behind/diverged histories, wrong branches, and unfinished Git operations must be reconciled explicitly with Git before retrying.
Ignored untracked files are left alone by publication; the existing update/apply cleanliness rules still apply afterward.

## Publication results and retry

With `--json`, results are grouped by checkout, with independent success/failure outcomes; any failure exits 1.
Publication is not atomic across repositories or between commit and push.
When an empty remote is confirmed, results include `initial_publish: true`; `remote_relation` remains `unknown` because there is no remote comparison base, and `commits` lists existing local history.
`last_fetch` records successful remote inspection even when an empty remote does not require fetching; `observed_revision` is populated after a successful first push.
A failed commit may leave staged changes, and a failed push retains the local commit; inspect the reported error and retry after resolving it.
Publication does not install content or update automatic-policy attempt clocks.

By default, selected installed managed copies and settings stages are gathered before publication.
External sources complete with `transport_complete = false`, indicating local handoff only.
Detached content is never collected.

## Collect managed copies

Ordinary `publish` collects selected installed, managed skill, directory, or instruction bundle copies into their source before publication:

```bash
aem publish report --dry-run
aem publish report -m "Share copy edits"
aem --json publish external-files
```

Mixed links, copies, and settings may be selected together.
Uninstalled declarations and links use the prepared source directly; detached copies are excluded and reported in `excluded_copies`.
The retained `--from-copy` option instead requires installed copies for every selected name, including all agent destinations.

Settings stages are exported automatically; actual application edits require explicit `settings collect` before publication.
All selected copy and settings plans are checked before source writes; overlapping settings and changed-copy source paths require separate publication.

Instruction collection includes the bundle only, validates its required entry, and excludes the global entry link and hook file.
Different edits from agent copies targeting the same source conflict; reconcile them before retrying.
Collection is explicit, never automatic, and introduces no editable stage.
It compares the saved last common hash, current source, and current copy.
Copy-only changes are collected, including additions, deletions, empty directories, executable bits, and directory symbolic links under their effective policy; source-only changes leave the copy and its baseline untouched and report `stale = true`.

If both sides changed differently, collection fails before source writes.
Identical content refreshes the common baseline without rewriting the source.
Identical overlapping collections are grouped; differing collections into overlapping source content fail before any write in that source group.
Unselected copies are not collected or given a new baseline.

Root payloads automatically omit their top-level `.git`; Git-ignored regular contents remain included unless removed by [catalog payload exclusions](../configuration/payload.md#payload-exclusions).
Collection preserves excluded source entries, and apply preserves excluded entries in the installed copy.
Exclusions do not change the repository-wide scope of a Git commit.
Apply changed exclusion policies before collection; nested or differently filtered overlapping collection with exclusions requires separate selections.

Collection and dry run check affected active links using saved ownership, including items removed from the catalog.
The resulting source must retain each linked file or directory's kind, each linked skill's regular `SKILL.md`, and each linked instruction bundle's regular entry file.
Violations stop the source group before source writes, baseline changes, or Git remote inspection; reconcile the copy or detach the affected item before retrying.
These checks enforce AEM's structural requirements, not document wording or meaning; ordinary content edits and removal of nonessential files remain allowed.

Git remote history is checked before collection; behind/diverged histories and remote inspection failures preserve the source and copies.
Actual Git collection requires `--message` when collection or existing checkout changes need a commit.
Git still commits all nonignored checkout changes, including unselected source files, under the ordinary publication contract.
External collection does not require a message or invoke Git; completion means only that content was handed to the local source, with no confirmation of other devices receiving it.

Installed outer links already edit the source and are not collected; nested symbolic links in general directory copies are preserved as links.
Collection validates their relative targets at the final source location before writing, including effects on other active consumers.

## Collection recovery

Changed source children are staged temporarily and replaced under a recovery journal; backups are retained beside the source root, outside its payload and Git checkout.
Live links and external synchronizers may observe source writes immediately; collection is not a tree-wide atomic activation.
After interruption, use `aem recover`; later edits to source, stages or backups stop recovery instead of being discarded.
After collection succeeds, commit/push failure retains collected content, the new common baseline and any created commit for retry.
Source groups have independent outcomes, with no cross-source transaction.

## Collection result fields

Publication uses `planned`, `published`, `exported` (completed local gathering), and `failed` result values.
Additional `collection` entries contain `item`, `source`, `copy`, `baseline_hash`, `source_hash`, `copy_hash`, boolean `changed`, `stale`, `conflict`, and relative `changes` (including `.` for root permission changes).
`compare` contains argument-list data for `git difftool --no-index -- SOURCE COPY`; `compare_command` is a POSIX-shell command for manual inspection.
Neither text nor JSON output launches an editor or comparison tool, and conflict exits `1`.

Successful collection adds `collection_complete = true` and `collection_backup` (null when no source writes were needed); the backup directory includes a recovery manifest.
External results add `transport_complete = false`, including when `status = "published"`; they never assert synchronization completion.
Dry run reads copy differences offline without collecting, staging Git changes, changing baselines, or creating transaction artifacts.
