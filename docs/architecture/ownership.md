# Ownership and preservation contracts

These contracts govern target ownership, payload policy, replacement transactions, and detach.
They apply independently of the command that triggers installation or recovery.

## Ownership and safety

Ownership comes from declared content and saved records, with explicit preservation boundaries.

### Ownership identity

- Only declared catalog skills, directories, and instruction bundles, and the package-owned official integration skill, may be installed.
- A content repository update cannot expand the local catalog.
- Catalog skill names identify ownership independently of repository URLs and paths.
- Instruction ownership uses the bundle name and bundle/entry/hook component.
- Do not infer ownership from an existing file or delete targets when declarations disappear.
- Reject overlapping target trees and require detach before changing an existing item's path or mode.
- A directory item owns its entire subtree, so extra local files are meaningful modifications.

Git identity checks still validate the managed checkout's origin and expected branch before applying or updating.

### Repository-root skills

Repository-root skills are valid and use direct links, not an extra content layer.
Automatically exclude their top-level `.git` administration entry from content fingerprints, copies, and detach materialization; honor explicit catalog exclusions at every depth.
Never duplicate a repository database or worktree pointer into an unmanaged skill.

### General directories

General directories reuse directory payloads, named sources, and per-target ownership without requiring an entry document or agent integration.
Omitted directory installation roots normalize to `home` unless the directory declares `agent`; bootstrap records the user's home path only when that binding is absent, preserving explicit roots and saved paths.
Their single ownership key is `NAME:directory`; agent filters include them as common items unless the directory declares `agent`.
A directory bound with `agent` installs below that registered destination's root, is selected, detached and reported only for that destination, and is skipped on machines that have not registered it; its saved record keeps `agents` and `agent_bound`.
Directory policies reuse skill policy composition and clocks, supporting local external checks/sync without Git transport.
Active directory link guards include orphaned consumers of shared checkouts.

### Payload exclusion preservation

Combine catalog-wide and item-root patterns with source-root patterns, retaining their logical anchors through subtree staging and recovery.
Do not follow, open, or recurse into excluded entries during inspection.
With exclusions enabled, POSIX directory scans guard inode, mode, and the included child name set rather than timestamps changed by excluded children; included file race checks remain intact.
Required descriptors and skill/instruction entries cannot be excluded.

Excluded existing destination entries are unowned and must survive apply and reverse collection.
Preflight their relative locations against the incoming tree, then journal opaque same-filesystem moves through a target-adjacent retention directory before replacing included contents.
Rollback restores both included contents and retained entries, including after interrupted moves or failed state commits.
Never delete a retention directory containing entries to resolve an error.
Refuse missing or redirected incoming ancestors and ambiguous duplicate recovery locations.
Save exclusion rules and subtree prefixes with each affected ownership and recovery record; absent rules preserve existing hashing and copy behavior.
A policy change requires apply before collection, and collections with nested or differently filtered overlapping excluded boundaries require separate selections.
Exclusion policies do not filter repository-wide Git commits.

### Permission preservation policy

Resolve the scalar permission level from item, source, catalog defaults, then strict; keep the existing strict hashing and copy path compatible.
Best-effort content equality excludes native permission modes, but transaction observations independently include their digest.
Record source observations and actual installed observations so inability to reproduce source modes never becomes an endless content conflict, while later local mode edits remain protected.
Permission snapshots use non-following descriptors on POSIX, preserve opaque link identity, and honor exclusion boundaries without rereading file contents.
Best-effort observations capture content hashes and native modes in the same guarded POSIX traversal.
Planning and staged-copy permission reports consume those captured modes; the later stage guard must still match the captured observation before replacement.
Only unsupported or denied permission setters are optional; timestamps, content writes, race guards, and structural validation retain their failure boundaries.

Save permission policy with ownership and journals, interpreting absent fields as strict.
Use the previous ownership policy to validate targets during transitions; changing policy never adopts an unrelated local edit.
Best-effort reverse collection preserves existing source modes only for matching node types and never exports permission-only edits or installation-induced differences.
New entries and replacements of a different type use incoming modes; opaque link targets remain part of payload equality.
Journal actual staged observations rather than assuming source and destination modes agree; recovery refuses later permission changes just as it refuses later content edits.

### Replacement transactions

Link and copy have different contracts.
Never silently fall back from link to copy.
Copy conflict detection uses the last applied content, desired content, and actual target; Git revision alone is insufficient.

Prepare and verify a replacement before moving the current target.
Write the recovery journal before the first rename and commit the ownership record only after installation succeeds.
Keep target backups; cleanup must never remove user changes discovered during recovery.
The process lock serializes commands for one configuration, not arbitrary editors or Git processes.
Retain the documented per-target transaction boundary instead of claiming global atomicity.

### Detach semantics

Detach preserves the current usable contents, then releases ownership and records a tombstone to prevent automatic reinstallation.
It does not restore pre-installation contents.
Do not discard state when a target is missing, unreadable, or cannot be safely materialized.
