# Maintenance command reference

Maintenance commands preserve installed content, recover interrupted replacements, or remove saved personal hook registrations.

## detach

```text
aem detach ID [ID ...] [--agent AGENT] [--dry-run]
```

Detach preserves contents according to the saved target kind:

- Materializes links as regular copies, preserves copy contents, and records detached tombstones.
- **Instruction entries**: Detaching an instruction entry also releases its hook ownership while retaining the hook configuration.
  For independent instruction copies, detach both `NAME:bundle` and `NAME:entry`.
- Detach does not restore pre-installation content or disable retained hooks.
- It refuses missing or unreadable content that cannot be preserved.
- `--agent` cannot detach only one consumer of a shared target; omit it to release all consumers.
- Dry run leaves targets and ownership unchanged.

Detach does not require valid installation fields or source declarations; it accepts state versions 1 and 2 without changing the version.
It materializes an actual symbolic link regardless of an obsolete saved mode, and checks regular contents are readable before releasing ownership.
Unknown fields and unselected records are preserved; no legacy config-merge parser is needed.

Opted-in directory links retain their raw target strings during detach; relative referents may change when the payload moves.
Saved ownership retains this capability after the catalog disables the option or becomes unavailable.

## recover

```text
aem recover
```

Restores the previous target from a pending replacement journal when observations still match.
Refuses to overwrite later user edits; retain the target, backup, and state for manual reconciliation.
Transactions are per target, so recovery does not undo earlier successful targets.
Recovery accepts the common journal format in state versions 1 and 2, validates paths and observations, and preserves the original state version and unrelated fields.
An unknown version or incomplete journal is rejected rather than inferred.

## hooks remove

```text
aem hooks remove NAME... [--agent AGENT] [--dry-run]
```

NAME selects saved personal hook resources, not source repository names or instruction hooks.
Omit `--agent` to remove all saved agent groups for those names.
Removal checks the exact saved group and stable identity, preserves unselected groups/preferences, and releases ownership.
Edited, duplicate, missing or detached groups are refused; no force removal is supplied.
It works offline without a catalog, runtime or source.
Dry run preserves targets and records.
Detach instead preserves groups.
Explicit selected reattachment is required after removal.
This operation does not remove AEM setup/instruction hooks or revoke product trust.

Prepare with `bootstrap --runtime NAME=ABSOLUTE_EXECUTABLE`, then register with `apply --item NAME` (or `NAME:hook` / `NAME:hook@claude`).
Plain apply and plain sync exclude personal hook registration.
Update visits the source without changing installed definitions; its live script contents may change immediately.
See [Personal hooks](../personal-hooks.md).
