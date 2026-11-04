# Instruction integration contracts

Instruction bundles select a named Git repository or a logical external source without source-local manifests.
Keep external path bindings in machine configuration and shared source/root/entry selections in the catalog.

## Bootstrap and bindings

Bootstrap accepts a positional catalog and optional repeated `--external NAME=PATH` bindings.
Persist them in the selected or default machine file, and reuse saved bindings when omitted.
Default agent, skills, and home roots only when absent; validate declarations and existing ownership before saving bindings or contacting content repositories.
Support explicit `--config`, `--catalog`, and root and storage overrides.
Do not parse document policy, applicability, or reading order.

## Installation and ownership

An instruction bundle owns a linked or copied directory, a global entry link, and groups for `SessionStart` and `SubagentStart`.
The agent profile selects the hook file and event syntax.
For copy mode, the entry points inside the installed directory; preserve its delivery source separately from its link destination.
Preflight validates the original payload before the installed copy exists.
Install the bundle before its entry, retaining per-target recovery and completed targets after later failures.

Bootstrap only prepares and validates sources.
Apply installs the selected bundle mode, links its entry, and merges the hook without granting Codex trust or modifying `config.toml`.
Default bundle installation to `<machine-file>.bundles/<bundle-name>` without requiring a configured rules root; preserve explicit location overrides and relocation guards.

Hook ownership and detach follow these rules:

- Preserve unrelated JSON events, groups, and metadata; malformed or redirected hook files must fail preflight.
- Own the complete AEM group identified by its saved marker, not the whole hooks file.
  Aggregate selected groups into one replacement per target file to avoid competing transactions.
- Entry selection includes bundle and hook installation, but never extends replacement permission to an implicitly selected bundle.
- Report the required `/hooks` trust review after apply; preview must show the planned group without registering it.
- Detach materializes both links and releases hook ownership while retaining its configuration, so saved locator records still support preserved documents.

## Saved location lookup

- Resolve roots from saved installation records and actual filesystem links, not from prompt text or the current catalog.
- Saved location lookup must remain offline and avoid updating ownership records.
  It must work for managed and detached copies without a catalog or source, and reject missing or redirected entries and replaced active links.
- User-facing `locate` also supports saved skills and current catalog source lookup for uninstalled content or explicit `--source` requests.
- Keep callbacks on saved instruction lookup only; never fall back from a broken saved installation to a different source.
- Source lookup validates paths and Git identity without requiring a clean checkout, fetching, or installing content.
- Keep copy/detached locations distinct from source editing paths; ordinary publication never implies collecting installed-copy edits, and reverse collection requires explicit `--from-copy`.

## Callback transport and locking

Use an absolute interpreter for hook execution, quote POSIX arguments, and explicitly encode a PowerShell command on Windows without evaluating user paths.
Instruction callbacks emit only path metadata, never document contents.

Callback output follows these rules:

- SessionStart retains Codex `additionalContext` and structured-stop responses, and Claude plain stdout with stderr/exit 2 on failure.
- Both profiles use event-specific `additionalContext` JSON for SubagentStart; lookup failure warns without claiming to block child creation.
- Claude's failure transport remains stderr/exit 2 for both events.
- Generated child callbacks select their event explicitly; existing callback commands retain SessionStart behavior without reading stdin.

Callback lock handling follows these rules:

- Instruction callbacks wait at most 5 seconds total for the installation and configuration locks within their 10-second hook limit.
- On POSIX, CLI processes hold a shared installation lock; package-replacement workers retain the exclusive lock.
- Windows retains exclusive installation locking.
- If only the configuration lock remains busy, instruction callbacks may resolve read-only location metadata from saved state.
- Reject pending recovery, invalid or replaced links, and any change to the machine file or ownership state during lookup before emitting context.
- Startup callbacks also wait up to 5 seconds for contention instead of skipping immediately; other commands retain immediate configuration contention failure.

## Reading-location metadata

Limit callback metadata to the effective `root`, `entry`, and `global_entry` reading locations.
Explain their correspondence without assuming the entry's contents have already been loaded or requesting a redundant read when they have.
Resolve entry-relative references from its parent directory and supplemental references from the referring document's directory, unless the user documents explicitly specify another base.
Do not infer applicability or reading order from bundle placement or the entry filename.
Keep `installed_root` and `detached` in locator diagnostics so a preserved copy cannot be mistaken for the live entry's source tree.

## Preservation and automation

Preserve original documents and use the existing per-target conflict/recovery machinery.
Guard the saved entry path of active linked Git bundles even when their catalog declarations disappear or a shared skill initiates update.
Entry links into installed copies do not consume the delivery checkout and must not block its updates as live-source links.
Instruction-specific automatic policies are not supported; skill policies may still advance shared checkouts.
Explicit full device automation may prepare/update/apply instruction bundles, excluding an agent group if any of its saved components is detached.
