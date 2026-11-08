# Shared command contracts

These contracts apply across ordinary commands unless a command documents an exception.
They define output, status codes, locking, platform preflight, and preservation reports.

## Exit codes

Ordinary operation errors use stderr and exit `1`, argument parsing errors exit `2`.
Invalid numeric CLI durations (non-finite values, nonpositive timeouts, or negative intervals) are argument errors and exit `2` before configuration reads or filesystem effects.
Help exits `0`; invoking a command group without a required subcommand shows usage/help and exits `2`.
Successful operations exit `0`; status also exits `0` when its report contains conflicts or unavailable sources.

## Platform support and preflight

Linux and WSL are supported; native Windows commands and the standalone installer refuse execution before configuration or target changes.
Use the last Windows-supporting release to recover, detach, and remove its integrations before moving to a separate WSL installation.

Unsupported payload types and ordinary operation failures remain errors; there is no automatic skip option.
Explicit content commands still preflight the complete selection and shared-source consumers.

## Compatibility

Compatibility guarantees and descriptions of current behavior are distinguished by the package's [compatibility policy](../compatibility.md).
JSON consumers must ignore unknown object fields; field additions may appear in compatible feature releases.
Enum values are closed unless their interface explicitly documents unknown-value handling.
JSON whitespace, object key order, and human-readable diagnostic wording are not stable interfaces.

## Locks and shared sources

Commands using machine state lock one configuration; installations registered for self-updates also share a lock for their uv tools directory.
`docs` and `self publish` operate independently of machine state and acquire neither lock.
Content and catalog updates allow Git-ignored regular caches in their checkouts and refuse any fast-forward that would overwrite them.
In content status, `sources[].checkout` is `dirty` for tracked edits or nonignored untracked files; ignored files alone leave it `clean`.
External editors and other package-manager processes do not participate in these locks.
Read-only commands and dry runs may create the lock directory/file; `setup --dry-run`, `self update --dry-run`, and `automation --dry-run` do not.

## Permission preservation reports

Catalog [permission levels](../configuration/payload.md#permission-preservation) apply to payload copying in `apply`, link materialization in `detach`, and explicit `publish --from-copy` collection.
For best-effort payloads, apply and detach results include `permissions = "best-effort"` and `permission_differences`.
Each difference identifies the payload-relative `path` (`.` for the root), integer native mode `requested`, observed `actual`, and an optional permission-setter `error`.
Modes are POSIX permission bits; these fields do not describe ACLs or effective access rights.
An empty array means no observed native mode difference or setter failure, not complete metadata preservation.

`apply --dry-run` and link `detach --dry-run` report `permission_check = "pending-copy"` when copying would be needed; it does not probe or promise permission support.
After installation, `status` exposes differences recorded by the last apply or successful collection, including in saved-state fallback when the catalog is unavailable.
Content can be `current` despite reported permission differences; later user changes to native permissions are still `modified-locally` or `conflict`.
An unchanged apply retains previous setter failures alongside observed differences.

Collection reports include `permission_differences` for completed best-effort staging when preservation was incomplete.
Status retains these as `collection_permission_differences`, describing the source destination; ordinary `permission_differences` describe source versus installed-copy modes.
Preview cannot determine setter failures because it does not stage or write payloads.
Best-effort differences alone do not change a successful command's exit code; content verification, races, ownership conflicts, recovery failures, and ordinary I/O errors remain fatal.

## Output formats

Output modes control the detail and encoding of completed results; progress reports ongoing work separately on stderr.

### Text and JSON results

Ordinary commands print concise summaries by default, including when stdout is redirected.
Content results are grouped as instructions, skills, directories, settings, or hooks when their type is known; source and repository results remain separate.
Result counts count operation results, so preparation and staging of one setting, or separate instruction installation components, can contribute multiple results.
Empty results are explicit; routine paths, revisions, empty fields, and duplicate compatibility views are omitted.
Errors, conflicts, pending recovery, comparison arguments, settings field paths, and required notices remain visible.
Use `--verbose` for detailed text, for example `aem --verbose status`; it cannot be combined with `--json` (usage error, exit `2`).
Text durations include units, and previews and last-fetch observations are distinguished from completed operations and current remote observations.
Use `--json` for the existing JSON report schema, for example `aem --json status` or `aem --json catalog status`.
Scripts that parse stdout must add `--json`; startup and agent-hook callbacks retain JSON automatically.

### Live progress

Ordinary operations show live progress on stderr when stderr is a terminal and `--json` is omitted.
In automatic mode, fast operations remain quiet; after about one second, longer work reports its current phase, target identifier, and elapsed command time.
Source inspection also identifies the source ordinal; updates are sampled at most once per second and repeated unchanged phases are reported at most once every five seconds.
This is useful for repository download/update/publication, content inspection and installation, detach/recovery, catalog delivery, settings reception/collection/export, and integration setup/removal, including previews.
It does not imply a percentage, estimated finish time, or completion of queued/background work.

Use global `--progress` to request progress explicitly, including when output is redirected or `--json` is selected; use `--no-progress` to suppress it.
Progress never changes the final stdout format or exit code, and informational stderr lines do not signify an error.
Startup, instruction-location callbacks, and internal workers suppress progress even when explicitly requested.
Progress reporting does not fetch, inspect additional files, or weaken transaction checks.

```bash
aem --progress update source:example
aem --json --progress status > status.json
aem --no-progress sync
```
