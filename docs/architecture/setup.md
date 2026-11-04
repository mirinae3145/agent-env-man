# Setup and self-update contracts

Setup connects an installed package to shells and agents; self-update replaces that package through an external worker.
These contracts preserve existing integrations and coordinate replacement with ordinary commands.

## Installer and release selection

The repository installer uses uv to install this checkout as a user tool, then delegates integration to `aem setup`.
Offer `off`, `compatible`, and `breaking` self-update modes on first interactive installation; unattended omission defaults to off, and omitted choices preserve saved settings.
Self-update policy and the external installer runtime belong to machine configuration, never the content catalog.
Preserve the authoritative [compatibility policy](../compatibility.md) and [release selection rules](../automation/self-update.md).
Keep tag parsing and ordering standard-library-only for the copied worker; exclude development, post, and local versions.
Prefer exact package tags during self publication and Python tags during update selection when equivalent aliases coexist; never bypass a mismatched exact tag with an alias.
Validate package identity and tag/version agreement before installation, and pin the selected commit.
Do not advance or publish the development checkout as a self-update side effect.
## Replacement worker and locks

The standalone worker must remain standard-library-only, run on a Python outside the replaced tool environment, and wait for its requesting AEM process to exit.
Copy worker code into a distinct request directory before launching; never depend on package files surviving replacement.
Registered commands and workers must acquire the shared installation lock before their configuration lock.
This order also applies across machine files that share one uv tools directory.
Recheck saved policy, recovery state, request identity, and actual installed version before replacement.
Snapshot the installed version under locks, then release both locks for remote release discovery and metadata validation in a private checkout.
Reacquire locks and reload policy, request identity, recovery state, and official skill ownership before replacement or recording preparation failure; a superseded request must not overwrite the newer result.
Cancel a prepared update if the installed version changed, and retain both locks through the actual uv replacement.
Persist attempts before launch, throttle failures across startup events, keep previews offline and read-only, and distinguish queued work from completed updates.
Keep self commands independent of content declarations; ordinary content operations and instruction location callbacks must not schedule self-updates.
Keep removal-only setup independent of runtime registration and policy edits.
Package-manager rollback and real Windows replacement require separate evidence before strengthening their documented guarantees.
Keep the installer standard-library-only; configuration and ownership logic belong in the package.
## Official skill lifecycle

Setup owns machine selection, startup registration, and official skill links, while bootstrap prepares catalog content and apply installs it.
Agent integration includes the startup hook and an ancillary link to the packaged official skill at the selected skills root.
Complete and persist core setup integrations before attempting optional skill installation or removal.
Report skill outcomes separately in `official_skills`, preserving the core `integrations` results and successful exit status.
Preflight ancillary skills independently per agent, preserve conflicting targets, and permit explicit setup retries after resolving their cause.
Do not suppress unresolved recovery journals or shared-state errors; the worker's strict refresh and pre-replacement edit guard remain independent of best-effort setup.
Keep official skill ownership under setup, independently of catalog declarations and content policies.
The package resource mapping in `pyproject.toml` must include the root-level skill in both wheel and sdist; update explicit package registration when adding a Python package.
Self-update validates recorded links and source edits before replacement, then releases locks before invoking the fresh CLI to refresh official links.
Refresh only active owned official integrations; a failed or uninstalled ancillary integration must not become a prerequisite for existing update workflows.
The continuation must validate its request token and saved policy binding and run at most once.
Keep package replacement outcomes separate from official link refresh outcomes; full automation stops if link refresh fails.
Older saved source hashes may differ after another configuration or an external installer replaces the package; compare payloads only for the recorded package version.
Catalog update policies must never register hooks implicitly.

## Setup transactions and removal

Selections accumulate, and repeated setup must preserve unrelated content and avoid duplicate groups or blocks.
Preflight all core profile edits before changing any of them, and commit each target through the existing recovery journal.
Save machine selection after core target transactions and before ancillary skill attempts.
A retry must recognize completed ownership records after a partial failure.
Setup removal must not delete user content or silently detach installed skills and instructions.
Official integration removal deletes only unchanged owned links, preserving their package sources and transaction backups.
Store official removal backups under the machine state directory's `setup-backups`, outside agent discovery roots; sibling link backups would remain discoverable skills.
Reject official skills roots containing machine state storage, and preserve link identity without requiring renames across filesystems during removal or restoration.
Recovery permits this backup location only for recorded official link removal with a missing post-transaction target, retaining sibling-path validation for ordinary replacements.
Changed official links, edited sources, and substituted copies are preserved and released from setup ownership, with their paths reported.
A setup invocation containing only removals must touch only requested saved integrations, without rebuilding remaining integrations or consulting current profile defaults.
Use saved shell blocks and hook groups, including retired integration names; ignore an executable override on removal-only calls.
Preflight selected removals and machine-document edits before writing, detect concurrent edits, group removals sharing a hook file, and retain the same journal/retry boundaries as setup installation.
Do not grant agent hook trust or rewrite user execution policies.

## Agent profile boundary

Resolve product-specific defaults, hook serialization, and callback output through internal agent profiles.
Codex and Claude Code are shipped profiles.
Named instances reuse the product implementation with a distinct installation identity, target roots and callback markers.
Retain existing default IDs and persisted hook commands; never relocate old destinations when registering another instance.
Catalog personal hooks remain product declarations expanded into configured instances.
Optional machine settings associations select one instance and retain separate per-item stage/conflict ownership.
Account authentication and runtime state are not copied or provisioned by this extension.
Keep product syntax in internal profiles and delivery/ownership in the shared manager.
Validate future extension with fake profiles without claiming third-product support.
See [profile contracts](../agent-profiles.md).
Generate instruction callbacks through agent-hook NAME --agent AGENT and the internal profile.
Store per-target ownership and shared consumers independently from per-skill Git delivery and automatic attempt clocks.
A shared target has one owner and cannot be materialized for just one of its consumers.
Explicit catalog roots retain their meaning; omitted destinations use selected agent defaults.
