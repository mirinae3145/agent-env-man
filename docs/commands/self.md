# AEM release command reference

The `self` commands inspect and update the installed tool or publish a prepared release checkout.

## self

Inspects the installed tool and queues version-permitted updates independently of content configuration.

```text
aem self status
aem self update [--mode compatible|breaking] [--dry-run]
aem self publish [--checkout PATH] [--dry-run] [--git-timeout SECONDS]
```

`status` is offline and reports `version`, `mode`, `repository`, `runtime_registered`, and `last_attempt`.
It works without a catalog, including when content declarations are malformed.
`update` queues an external worker and exits `0` when queued; asynchronous failure is reported by subsequent status, not the launch command's exit code.
It uses the saved enabled mode, or `compatible` if automatic updates are off.
`--mode` overrides only this attempt; explicit updates ignore the automatic daily interval.
Dry run requires a registered runtime but performs no remote access, launches no worker, and writes no files.
Pending recovery blocks an update.

### Update execution and preservation

The worker waits for the requesting AEM process to exit, locks the registered installation and configuration, then rechecks its request token, saved settings, and recovery state.
A superseded request does no work; changed settings or pending recovery cancel it.
The actual uv-installed version is checked under the installation lock so another configuration's completed update cannot cause a downgrade.
Before replacement, the worker validates official link identity and checks source contents when their recorded package version matches the installed version.
After replacement it releases locks and calls the fresh CLI to verify or refresh active owned official links for this machine configuration.
Previously uninstalled, failed, or detached official integrations are not installed by self-update; use general setup to install or retry them.
The self-update result keeps its existing `queued` status during that step and records separate `stages.tool` and `stages.official_skill` outcomes; full automation retains its existing `continuing` status.
If package replacement succeeds but link refresh fails, the result is `failed`, retains the successful tool stage and release version/revision, and advises retrying `setup --agent codex`.
Full automation also refreshes connected official links before catalog/content stages and stops if refresh fails.
Other machine configurations verify their own links on subsequent general setup or self-update; external package-manager replacement requires general setup to refresh links and does not provide the worker's pre-replacement edit guard.
Newer final or supported prerelease tags (`vVERSION`) qualify within the selected mode; annotated tags resolve to their commits.
SemVer-style `-alpha`/`-beta`/`-rc` tags with optional `.N` numbers convert to Python `a`/`b`/`rc` package versions; an omitted number means zero.
Prerelease `compatible` updates change only the numeric subversion within the same base version and label; final `compatible` updates retain their existing range and exclude prereleases.
See [release syntax and ordering](../automation.md#update-aem-itself).
The selected commit must contain `project.name = "agent-env-man"` and the matching release version in `pyproject.toml`.
Installation pins that commit through `uv tool install --reinstall`; neither the development checkout nor managed content is changed.
Git authentication is noninteractive.
Each Git/uv subprocess and worker lock wait is bounded to 300 seconds.
Package-manager rollback and coordination with external installers are not guaranteed.
If an installation is damaged, rerun the repository installer.

### Update result fields

A queued report contains `status`, `time` (Unix seconds), `token`, and `mode`.
Dry run returns `status = "planned"`, `mode`, and `network = false`.
The initially empty `last_attempt` subsequently contains those queued fields and can become `up-to-date`, `updated`, `failed`, or `cancelled`.
Completed results include `finished` (Unix seconds); an updated result also includes `version` and `revision`, failures include `error`, and cancellations include `reason`.
An interrupted worker can leave a queued result; explicit update queues a fresh attempt immediately.
During startup, disabled/throttled work is reported in the saved startup outcome as `disabled`/`throttled` and does not replace the last attempt.

### self publish

Publish an already prepared AEM release without machine configuration, a catalog, or self-update runtime registration.
This command does not create commits or tags, change versions, install AEM, or schedule updates.
It does not read or change installation records or automatic attempt clocks.

`--checkout PATH` selects the Git working-tree root; relative paths are resolved against the current directory.
When omitted, use the local directory recorded in the installed package's `direct_url.json`, including a non-editable local installation.
If no local directory is recorded, use the running module's own `src/agent_env_man` checkout when available; otherwise require `--checkout`.
A stale or invalid recorded local directory fails rather than selecting a different checkout.
The current directory, homes, and uv receipts are not searched for a replacement source.
Installed package code and bundled documentation directories are not publication sources.

Prepare the release with Git before invoking publication:

- The entire working tree must have no tracked edits or nonignored untracked files, and no unfinished Git operation.
- HEAD must be attached to a branch; the selected path must be the working-tree root.
- HEAD must contain a tracked regular `pyproject.toml` with `project.name = "agent-env-man"` and an `X.Y.Z` or `X.Y.ZaN`/`X.Y.ZbN`/`X.Y.ZrcN` version; the pre number may be omitted and means zero.
- A matching local `vVERSION` tag in Python or supported SemVer-style notation must already resolve to HEAD; lightweight and annotated tags are supported.

The exact package spelling is preferred when present, then equivalent Python spellings, then SemVer spellings.
An exact package tag pointing elsewhere is rejected even when an equivalent alias points to HEAD.

`origin` must have the same single fetch and push destination.

The target is `origin` and the current branch; no separate publication binding or remote/branch override is provided.
Use Git directly for other combinations.
Publication inspects all advertised remote refs and allows first publication only when the remote is verified empty.
A populated remote must contain the current branch; after fetching it, behind or diverged local history is rejected without merging or rewriting.
An existing remote release tag must resolve to the reviewed HEAD commit.
Equivalent remote tags are retained, including their existing annotation/signature; differing tag targets are rejected.

Push explicitly selects the reviewed commit for the current branch and, when absent remotely, the existing local release tag object.
Atomic push is required, even when the release tag already exists; unsupported or rejected atomic pushes fail without sequential fallback.
No force push or implicit additional branches/tags are permitted.
Authentication is noninteractive; `--git-timeout` bounds all Git operations together and defaults to 30 seconds.
The command preserves local commits, tags, index, and worktree on success or failure; actual execution may refresh the remote-tracking branch and `FETCH_HEAD`.
External Git processes do not participate in AEM coordination; keep the checkout stable during publication.

Dry run validates the local prepared release without contacting the remote or writing files.
It reports the remote relation only against cached tracking refs and cannot confirm remote history, tag compatibility, credentials, or atomic-push support.
Review the reported checkout, repository, branch, version, tag, and revision before publishing.

The JSON result is one object with `status` (`planned`, `published`, or `failed`), `network` (whether network work is enabled), and `remote_verified` (whether remote history and tag preflight completed).
After local validation it includes `checkout`, `repository`, `branch`, `version`, `tag`, `revision`, `changes`, `diff`, `commits`, and `remote_relation` from the checkout inspection.
`checkout` may appear before validation completes; other fields may be absent on early failure.
Actual execution adds `initial_publish = true` for a verified empty remote or `observed_revision` for a fetched branch, and `tag_present` after successful remote tag inspection.
`failed` includes `error` and exits `1`; `planned` and `published` exit `0`.
Operational failures are returned in this report on stdout, including with `--json`; usage errors remain on stderr with exit `2`.
