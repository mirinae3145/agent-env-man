# Payload configuration

Payload policies define excluded paths and native permission preservation for skills, directories, and instruction bundles.
These policies govern inspection and copying without filtering the live filesystem view.

## Payload exclusions

Exclusions belong in the catalog and apply to skill, directory, and instruction bundle trees.
They do not exclude explicitly declared instruction entry links, application setting files, or personal hook scripts.
Omitting all exclusion declarations preserves the existing payload behavior.

```toml
[payload.defaults]
exclude = ["**/._DAV", "**/@eaDir"]

[sources.projects]
type = "external"
exclude = ["**/__pycache__"]

[directories.example]
source = "projects"
subdir = "example"
exclude = ["scratch"]

[directories.example.install]
mode = "copy"
```

Effective exclusions combine `payload.defaults.exclude`, `sources.NAME.exclude`, and the item's `exclude` array.
Lists add exclusions; there is no replacement or re-inclusion syntax.
Global and item patterns are relative to each item's payload root.
Source patterns are relative to the source root, including the item's `subdir`.
For example, source pattern `example/cache` excludes `cache` from `directories.example` in this example, whereas item pattern `cache` is relative to that item directly.

Patterns use `/` and are anchored to their declared root; matching is case-sensitive on every platform.
`*`, `?`, and character classes match within one component; a whole `**` component matches zero or more components.
`scratch` matches only the root entry; `**/scratch` matches that name at any depth.
A matched directory excludes its entire subtree without opening or inspecting its contents.
Absolute paths, drive prefixes, backslashes, empty components, `.` or `..`, negation, and partial `**` components are rejected.
Excluding a declared source subtree, a skill's required `SKILL.md`, or an instruction bundle's required entry is an error.

The same effective policy governs fingerprints, copying, status, detach materialization, and reverse copy collection previews and writes.
Links still expose the original source tree, including excluded entries; exclusions affect AEM's inspection and copy operations rather than the linked filesystem view.
The existing automatic omission of top-level `.git` for source-root payloads remains independent of configured exclusions; nested `.git` paths remain included unless explicitly excluded.
Git ignore rules do not automatically become payload exclusions.
Exclusions also do not change repository-wide Git publication scope: a requested commit still includes every nonignored change in the selected checkout.

Excluded entries already in an installed copy remain local and are preserved during replacement.
Reverse collection preserves the source's excluded entries and does not collect the copy's excluded entries.
AEM moves these entries opaquely through temporary storage beside the directory being replaced, without reading their contents or following links.
If an included ancestor would disappear or become a file or link, the operation stops rather than deleting or relocating the excluded entry.
Apply and reverse collection previews check this boundary before reporting a planned replacement.
If new excluded entries appear after preservation preflight, replacement stops so they remain available for inspection and retry.
`--replace` does not override that preservation boundary.

Ownership and recovery records retain the effective exclusion policy, so detach and recovery remain usable without the current catalog or source.
A changed exclusion policy is reported as `configuration-changed`; apply it before reverse collection.
Apply still checks local edits against the saved policy or requires a copy already matching the desired included contents; changing exclusions does not authorize overwriting unrelated edits.
Nested or differently filtered overlapping copy collection with exclusions requires separate selections.


## Permission preservation

`permissions` selects `"strict"` or `"best-effort"` for skill, directory, and instruction bundle payloads.
The item's value overrides its source's value, which overrides `payload.defaults.permissions`; omission at every level selects `"strict"`.
Unlike exclusion lists, permission levels replace rather than accumulate.
Application settings, generated instruction hooks, personal hook scripts, and instruction entry links do not inherit this option.

```toml
[payload.defaults]
permissions = "strict"

[sources.nas]
type = "external"
permissions = "best-effort"

[directories.documents]
source = "nas"
subdir = "documents"
[directories.documents.install]
mode = "copy"

[directories.scripts]
source = "nas"
subdir = "scripts"
permissions = "strict"
[directories.scripts.install]
mode = "copy"
```

The selected level controls copying and verification as follows:

| Level | Permission handling | Verification |
| --- | --- | --- |
| `strict` | Retains existing copy and permission-error behavior. | Retains existing payload hashes, including POSIX executable bits on files and directories. |
| `best-effort` | Attempts native permission-mode preservation, reports unsupported or denied setters and observed mode differences. | Requires identical contents, entry paths/types, empty directories, and opaque link targets, independently of native permission modes. |

Neither level guarantees complete preservation of ownership, ACLs, extended attributes, or other platform-specific metadata.
On Windows, native permission observation covers the writable/read-only flag supported by `chmod`, not ACL access rights.
Best-effort copying retains timestamp application; timestamp failures, content I/O errors, unsupported payload types, and source or target changes remain fatal.
It does not ensure that copied scripts can execute or reproduce the source's access restrictions.

Guarded POSIX inspection automatically rechecks a change confined to `mtime` or `ctime` once, including for strict payloads with `preserve_symlinks`.
It succeeds only if a fresh stable inspection matches the first content and identity capture, including native modes and included paths; persistent instability or actual changes still fail.
Copy retries support read-only directories and retain the final requested modes.
If another process replaces or recreates the temporary destination, AEM stops and reports where it preserved that content; retain that path and resolve the conflict before retrying.
This adds no permission level or catalog option and does not make timestamp-setting failures optional.

AEM records both source permissions and the actual installed permissions in best-effort ownership.
A changed source mode makes a managed copy stale; a later local mode edit remains a protected local modification.
Existing installations and records without this field retain strict behavior and their original hashes.
Changing the effective level is reported as `configuration-changed`; apply the new level before reverse collection, using the previous ownership to protect local edits.
`--replace` authorizes replacement of a conflicting target but never bypasses content or transaction checks.

Link installation does not alter source permissions.
Its effective level is saved for later detach materialization; detach and recovery use saved policies even without a readable catalog.
In best-effort reverse collection, existing source entries of the same type retain their native modes where possible.
New entries and entries replacing a different type attempt the copy's modes.
Permission-only edits are not exported; collection of content edits records any differences without treating installation-induced mode differences as content changes.
Overlapping collections with different permission levels require separate selections.
See [permission reports](../commands/output.md#permission-preservation-reports) and [maintenance](../maintenance.md#copy-verification-failures).
