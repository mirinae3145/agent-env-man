# Workflow design

These coordinated workflow changes simplify everyday operation while preserving saved ownership, explicit publication, and recoverable writes.
These decisions connect payload defaults, platform support, publication, and inspection; their public syntax belongs in the command and configuration references.

## Payload defaults and saved ownership

New catalog interpretation defaults to best-effort permission preservation and opaque nested symlinks in general directories.
Strict permissions and rejection of nested links remain explicit choices.
Only `**/._DAV` and `**/@eaDir` are excluded by default, based on generated storage metadata encountered in supported workflows; generic dotfiles, caches, and build outputs remain included.
An explicit `payload.defaults.exclude` array replaces the built-in list, including `[]` to include those names.
Source and item exclusions remain additive to that selected list.

Defaults apply to existing catalogs that omit these fields, without rewriting their files or incrementing the catalog format marker.
Saved ownership and recovery records keep their original interpretation: absent permissions mean strict, absent exclusions mean none, and absent symlink preservation means rejection.
Apply transitions an installation using the previous policy to protect edits before recording the new one.
Publication requires that transition before collecting copies.

## Supported execution and unsupported items

Native Windows execution is unsupported; Linux and WSL remain supported.
Reject native Windows at CLI and standalone installer entry points before changes.

The only platform-specific payload exclusion was nested directory links on native Windows, so full automation no longer needs a skip policy.
Accept the old Boolean machine field for migration without using it to suppress failures; remove its setup options.
Unsupported files, missing sources, and ordinary operation errors still fail visibly.

## One outward workflow

`publish` gathers selected installed managed copies and selected settings stages into their source, then commits and pushes Git sources or reports local handoff for external sources.
Mixed link, copy, and setting selections use the same workflow; uninstalled declarations and links already refer to source content.
Detached copies are never collected.

`publish --source-only` explicitly publishes source edits without gathering copies or stages.
`publish --local` performs only the local gathering phase, without Git transport or commits.
The older `export` spelling remains an alias for that local operation, and `--from-copy` retains its strict copy-only selection for existing callers.

Actual application settings remain a distinct privacy boundary: `settings collect` selects managed fields into the editable stage, and explicit paths add new fields.
Publication never gathers arbitrary application fields.
Preflight both settings exports and copy collection before source writes, reject overlapping writes between them, and retain per-source recovery and Git retry behavior.

## Inspection and history

Infer omitted locate agents from saved destinations first and current declarations otherwise; multiple eligible agents require an explicit selector.
Saved lookup continues to work without the catalog.
Read-only inspection uses shared configuration locks, while instruction callbacks try immediately and fall back to a stable, recovery-free saved snapshot on contention.
Startup callbacks fail open immediately when a command is active instead of consuming their hook budget waiting.
Mutations retain exclusive locking throughout their preservation checks and writes.

Status distinguishes current inspection errors from historical attempts.
Keep attempt details in JSON and verbose output, but do not display old failures as current errors in the concise view.
Successful operations clear the relevant saved source error; they do not erase independent attempt history.

## Release boundary

The compatibility policy protects explicit choices, usable workflows, and data/ownership guarantees rather than treating every documented observation as frozen.
Default changes require a reliance and migration assessment, with notices and explicit alternatives where needed.
These combined changes include incompatible interfaces and must follow that policy when released.
A package release number has not been selected, and the TOML format markers remain unchanged.

The distribution and CD mechanism is a separate pending decision; this implementation does not replace the existing release transport.
