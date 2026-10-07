# Maintenance and recovery

Use this guide when installation encounters a conflict, an operation is interrupted, or you want to release ownership or remove AEM.
Keep saved state and backups: they identify owned targets and support recovery without overwriting later edits.
See [Commands](commands.md) for complete options and [Removed interfaces](removed-interfaces.md) for existing-installation upgrade precautions.

## Conflicts and detach

AEM refuses unmanaged targets and locally modified copies unless explicitly authorized:

```bash
aem apply --item report --adopt     # Record matching existing content.
aem apply --item report --replace   # Back up and replace a conflict.
aem detach report                  # Keep contents and release ownership.
aem detach personal:bundle personal:entry
```

Skill backups are retained in `<machine-file>.state/skill-backups/<target-name>-<id>`, outside agent skill discovery roots.
They preserve previous contents or link identity and support recovery across filesystems.
Other target backups are retained as `<target>.aem-backup-<id>`.
Existing sibling backups are preserved; move reviewed old skill backups outside discovery roots if they appear as duplicate skills.
A directory item owns its entire subtree; local additions count as modifications.
Detach materializes links, preserves copies, and records a tombstone to prevent automatic reinstall.
General directories use these same preservation rules; `detach NAME` releases the single `NAME:directory` item without collecting its contents into the source.
After moving the preserved target aside, explicitly reattach with `aem apply --item report --reattach`.
Detaching instructions retains hook configuration and locator records for the preserved copy; disable the retained hook in Codex if no longer wanted.

## Interrupted operations and recovery

Apply preflights selected items and journals each replacement before changing targets.
Transactions are per target: earlier successful items can remain installed if a later item fails.
After an interruption, inspect `status` and run `recover`.
Recovery refuses to overwrite later user edits; keep state and backups.
Never delete state to bypass ownership conflicts or unsupported state versions.
Even when old or unknown machine fields block installation, `detach`, `recover`, `locate`, and removal-only `setup --remove-*` use saved ownership independently.
Offline `status` falls back to saved IDs and target observations.
These maintenance paths support state versions 1 and 2, preserving the original version and unknown fields without automatic migration.

## Git updates and payload limits

Git updates never stash, reset, rebase, commit, or push automatically.
They reject tracked changes, nonignored untracked files, unfinished operations, local-ahead/divergent history, wrong branches, and checkout identity changes.
Git-ignored regular files such as `__pycache__` may remain in managed checkouts; an incoming revision that would overwrite them is refused without deleting the local files.
Ignored files remain visible through directory links and are included in directory copies and detach, which preserve the complete payload except root Git metadata.
Changes made inside an installed copy, including newly generated caches, still count as local modifications and prevent automatic replacement.
For managed skill/directory copies, explicit [copy publication](commands.md#publish) can preserve those changes in the source and advance their common baseline; otherwise intentional replacement remains explicit.
Interrupted copy collection is recovered with `aem recover`, using the source-group journal and retained backups outside the source root; later source/stage/backup edits stop recovery.
Updates also guard active link sources and instruction entries against removal or unsupported type changes, even after declarations disappear.
Nested payload symlinks/junctions, special files, and submodules are unsupported.
Portable copy metadata is preserved; platform-specific ACLs, alternate streams, and power-loss atomicity are outside the guarantee.

## Remove integrations and uninstall

To remove integrations, detach managed agent content first, then use `aem setup --remove-agent codex` and the appropriate `--remove-shell` options.
Agent removal also attempts to remove the unchanged official skill link; failures are reported separately, and changed links, edited official sources, or substituted copies are preserved with their paths reported.
Disable any retained detached instruction hooks before uninstalling AEM with `uv tool uninstall agent-env-man`.

## Personal hook removal

Use `aem hooks remove NAME --dry-run`, then the same command without preview to
remove only unchanged saved personal groups. It works without the catalog or
runtime and preserves other groups and Claude preferences. Detach retains groups
and does not copy scripts; keep their source/runtime available. Recovery retains
the existing later-user-edit protection. See [Personal hooks](personal-hooks.md).
