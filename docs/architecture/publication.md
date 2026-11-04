# Publication contracts

Explicit publication shares reviewed repository state or collects managed copies without changing installation ownership.

## Repository selection

Explicit `publish` selects catalog skill, instruction bundle, or setting names and groups them by existing checkout identity.
Report all catalog consumers of each selected checkout.
Do not infer per-skill file ownership for publication: commit and push operate on the whole repository, including changes outside catalog subdirectories.
A supplied message authorizes staging all nonignored changes; without it, require a clean worktree and publish existing commits only.
Keep preview offline and preserve the index, HEAD, installation records, and automatic-policy attempt clocks.

## Remote preflight and push

Verify all advertised remote refs before staging, settings export, or explicit copy collection.
Only a successful empty listing permits initial publication without a remote branch; a populated remote must contain the registered branch and be fetched before staging.
Never reinterpret authentication, transport, listing, or fetch failures as an empty remote.

Refuse behind/diverged histories without rewriting or merging them.
Push only the registered branch to the registered origin, without force or implicit additional refs.
Preserve staged changes and commits after failures, report each repository's outcome independently, and never claim atomicity across repositories.
External synchronization and fork/PR workflows remain outside this command's scope.

## Managed copy collection

Ordinary publication never collects installed-copy edits.
Explicit `--from-copy` requires owned, non-detached skill, directory, or instruction bundle copies for every selected name and collects only their payloads; Git publication still selects whole checkouts.

Build collection hashes, observations, and changed-path reports from the same inspections.
Collection staging may project child observations and mode/type maps from a freshly verified parent traversal.
Revalidate whole input trees after staging and physically check replaced children before mutation.
When a root copy contains its own `.git`, keep its full transaction observation distinct from the `.git`-excluding collection hash.

Use the existing ownership hash as the last common baseline, updating it after successful collection or agreement; source observation/update alone never advances it.
Source-only changes leave stale copies untouched; competing source/copy changes or differing overlapping exports stop the group before writing.
Root collection automatically excludes top-level `.git` and honors catalog payload exclusions, retaining other Git-ignored regular payloads and executable bits without copying Git administration.
Before source mutation, project collected copies onto affected saved active link sources and preserve their file/directory kinds and required skill/instruction entries, including orphaned ownership.
Apply the same checks to previews and recheck before committing source writes; detached links impose no requirements, and content wording remains outside AEM's validation.

## Collection recovery and reporting

Journal source replacements before mutation, retain backups outside the source root, and validate all recovery observations before restoring.
Never claim tree-wide visibility atomicity to external readers.
Collected content and baselines survive later commit/push failures, separately reported from Git publication success.
External copy publication confirms local handoff without contacting its service; installed outer links cannot be collected, while opted-in nested symbolic links retain their opaque identity.
Text and JSON report the same conflict paths and comparison arguments without launching tools, merging, or force-overwriting.

## Prepared AEM release publication

Self publication is a separate prepared-release contract.
Require a clean AEM checkout and an existing version tag resolving to HEAD, and never generate commits, tags, or version edits.

Resolve its default checkout from local installation provenance or the running module's own development tree, never by searching the current directory or user homes.
Invalid recorded paths require explicit correction.
Keep it independent of machine/catalog state and self-update scheduling.

Use the checkout's origin and current branch.
Validate remote history and existing tag targets, and atomically publish only the reviewed branch commit and missing release tag.
Preserve equivalent existing remote tag objects, local release contents, and ordinary content/catalog publication contracts; do not fall back to sequential push or force.
