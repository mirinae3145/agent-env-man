# Source delivery contracts

These contracts separate preparation from installation and protect shared live sources and catalog-independent maintenance.

## Delivery and live sources

These contracts cover live source visibility and the inspection that protects installed consumers.

### Delivery and link visibility

Delivery prepares local source paths; installation consumes those paths without network access.
Git must remain an end-to-end supported delivery path, not an external setup prerequisite that bypasses the core.
AEM does not own the service that synchronizes an external folder.
Keep source roots disjoint, and never nest externally synchronized sources inside managed Git checkouts.

Targets directly link to local source content.
Compare Windows link destinations with equivalent extended drive/UNC prefixes normalized, without following aliases or changing raw transaction observations.
Do not add snapshot activation semantics silently: changing this contract requires an explicit design decision and updated user documentation.
An `update` can therefore change live instruction contents without `apply`.
The incoming-revision guard protects active link source paths, even if the latest catalog no longer declares those items.
Allow Git-ignored runtime files in checkouts while continuing to reject tracked changes and nonignored untracked files.
All content and catalog fast-forwards must refuse to overwrite ignored local files when mutating the Git checkout.
Never delete caches or weaken local-file preservation to make an update succeed.
Git-ignored regular files and directories remain part of directory payloads for hashing, copying, and detach unless explicitly excluded by catalog payload policy.
Check the included installed-copy tree for local modifications, and reject included nested links unless the general directory explicitly enables POSIX `preserve_symlinks`.
Special files remain unsupported.
### Payload inspection and revalidation

Payload inspection starts with synchronous leaf I/O and enables up to four readers after observing an operation taking at least two milliseconds, with at most eight outstanding tasks.
This decision is scoped to one inspection and independent of filesystem or transport type; results combine in the existing deterministic traversal order.
Ordinary fingerprints consume a bounded window of results during traversal rather than retaining completed reads for the whole tree.
POSIX link-preserving scans retain pinned parent descriptors until all child tasks finish, including failure paths, and retain identity and included-name revalidation.
Every new payload inspection reads included file contents; it does not infer unchanged contents from timestamps or reuse a persistent cache.
Hashes and per-path comparison entries may be captured in the same traversal instead of downloading contents again for a change list.
Within one item's status judgment, installation planning step, or shared-source preparation step, reuse an observation only when the physical path and payload policy agree.
Saved and current policies remain separate during transitions; source and target guards are freshly read at installation, staging, backup, and commit boundaries.
Guarded POSIX scans recheck a timestamp-only change once, retaining the first complete content and identity capture for comparison with a fresh strict traversal.
Only matching contents, included paths, link text, inode identity, size, and native modes permit success; another timestamp race or a real change remains fatal.
Publish mode/type maps and permission failures only from the successful attempt, after all sibling readers finish.
Copy reinspection retires its newly created destination into an exclusive private directory, checks the moved inode identity, and deletes only a matching copy before recreating the destination.
Owner access is restored through a verified copy-root descriptor before moving read-only directories; included copied directories are made writable through non-following descriptors for cleanup, without changing source modes or link referents.
A raced replacement or cleanup failure aborts and reports a preserved path; installation, restoration, and collection callers retain the enclosing temporary storage instead of deleting that content.
Preexisting destinations and timestamp-setter failures never qualify for retry.
### Symbolic link payloads

Link-enabled payloads hash link identity and raw target text without accessing referents; regular-node hash encoding stays unchanged.
Apply relative-link policy at the logical location in the source root, including during temporary staging, backup, detach, and reverse collection.
Use pinned non-following POSIX descriptors for enabled payload traversal and entry replacement; reject concurrent kind changes rather than following them.
Save the policy and logical source-relative path with ownership and recovery observations; absent fields retain the old rejection behavior.
Catalog policy removal cannot disable saved detach/recovery support.

### Shared consumers and platform checks

A shared checkout must satisfy every affected consumer's policy, including orphaned active links.
Keep catalog schema validation platform-independent; check selected items and affected source consumers for platform support before content mutations.
Do not put execution capability checks in general selection or catalog validation: inspection and catalog delivery must remain usable.
Saved ownership and recovery policies retain their execution requirements even when current declarations change.


## Catalog and maintenance boundaries

Catalog normalization separates reusable declarations from device bindings and saved ownership.

### Declaration and source binding

The primary input is a user-owned skill, instruction, and settings catalog, independent of the repositories it lists.
The loader reads a local TOML file supplied directly or prepared through Git catalog delivery; policy composition must remain independent of this transport and any future auxiliary-file layout.
Each skill has a stable name and selects one Git repository and optional subdirectory.
Catalog v2 requires named sources with explicit Git or external types and one source reference per item.
Validate its surface syntax separately, then normalize to the existing runtime model; do not accept that private model as input.
Keep skill installation fields under `install`, instruction installation fields under `install.bundle`/`install.entry`, and skill entry files fixed to `SKILL.md`.
Catalog trigger arrays replace inherited values; `[]` disables automatic execution even in full mode, while omitted policies retain their full-mode participation.
Preserve machine policy syntax, effective policy JSON, per-skill attempt records and callback contracts when normalizing catalog policies.
Do not require upstream skill repositories to add manager manifests or aggregate their content in this repository.
The catalog owns repository URLs, requested branches, and declarative skill automatic update policies; machine configuration owns its catalog binding, checkout storage, target roots, and explicit mode overrides.
Bootstrap clones missing repositories directly from the catalog, discovers and records their default branches when unspecified, and validates SKILL.md before publishing a checkout.
Retain each prepared named source's branch binding with its repository and checkout path independently of consumer membership, while preserving per-item delivery and automatic-policy records.
Installation consumes these prepared local checkouts without fetching.
Share a checkout only when skills explicitly reference the same named repository; equal URLs under different source names do not imply shared ownership.
Preserve named-source checkout paths; do not migrate or remove old direct-declaration checkouts automatically.
Validate every skill in a shared checkout before publishing it, and guard all active links from that checkout before advancing it.
Full automation may defer skill payload checks in an existing checkout until delivery validates every declared skill against the incoming revision before fast-forwarding.
Standalone bootstrap continues to validate local HEAD without updating existing checkouts.
Derive shared consumer bindings with one physical check per unique checkout path in each source-map construction, and revalidate paths on the next access.
Git operation markers may be located in one query; preserve linked-worktree paths and fall back to individual queries when newline-containing paths make the batch ambiguous.
Publication remote preflight validates identity, idle state, and push destinations without generating unused status/diff/log reports; publication still refreshes changes after remote verification.

### Ownership and maintenance boundaries

Keep installation ownership and automatic policies per skill, even when delivery is shared.
Do not introduce a provider framework without a demonstrated need.
Content rendering and arbitrary shell evaluation are not part of path substitution.
The catalog is the only content declaration format.
Do not restore source-local links.conf parsing, machine sources tables, legacy codex-merge declarations, or removed command aliases.
Staged application settings follow the independent contracts in [Settings management](../settings-management.md); they do not revive legacy installation semantics.
Installation requires state version 2; maintenance may read the shared ownership/journal envelope of versions 1 and 2 without conversion.
Keep detach, recover, saved-state lookup, offline status fallback, and removal-only setup independent of installation declarations.
These paths may ignore unknown machine fields and opaque modes, but must validate the specific saved paths, blocks, groups, and observations they consume.
Preserve unknown fields, unselected records, and the original state version when saving maintenance results.
Reject unknown state envelopes instead of guessing how to undo them.
Keep the breaking-change instructions in [Removed interfaces](../removed-interfaces.md) aligned with this boundary.
