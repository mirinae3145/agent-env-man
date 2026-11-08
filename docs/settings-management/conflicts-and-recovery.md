# Settings conflicts, status, and recovery

This reference defines how shared-source and application conflicts are detected and resolved, what status and detach report, and how previews and grouped recovery protect writes.
Use the [settings guide](../settings-management.md) for the editing and sharing workflow.

## Resolve shared conflicts

Shared-source and application conflicts use separate comparison bases and preserve the conflicting edits.
The two merges differ as follows:

| Merge | Comparison inputs | Conflict effect |
| --- | --- | --- |
| Shared reception/export | Last accepted shared state, current stage, and incoming source. | Saved separately from the valid stage; blocks apply/export/publish until resolved. |
| Application | Last applied state, current actual settings, and stage. | Aborts the whole application-file operation. |

One-sided changes and identical concurrent changes merge.
Different edits, deletion versus modification, and overlapping structural changes conflict.
Resolve a saved shared conflict explicitly:

```bash
aem settings resolve editor --path '["color"]' --take local
aem settings resolve editor --path '["color"]' --take shared
# Or edit the stage, then explicitly accept the edited result:
aem settings resolve editor --path '["color"]' --take edited
```

A structural conflict resolves all connected overlapping paths together.
`--take edited` validates the edited stage and explicitly acknowledges that choice.
Commands report conflict paths without embedding configuration values in ordinary diagnostics.

## Status and detach

Setting item IDs are `NAME:settings`; `--item NAME` also selects the item.
Status reports `not-prepared`, `prepared`, `managed`, `conflict`, `detached`, or `unavailable`, plus `conflicts`, `unpublished`, `unexported`, and (after apply) `unapplied` and `modified_locally` where available.
`unpublished` compares against the last received or successfully published shared state; for external folders export updates that local shared baseline without claiming synchronization completed.
Git source status separately reports uncommitted changes and outgoing commits.

`detach NAME` preserves actual settings and all stage edits, including a prepared item that has never been applied.
It releases management locally and does not publish a field release.
Reattach requires explicit `apply --item NAME --reattach`, with `--replace` if the new target conflicts.
Saved location, detach, and recover work without the catalog.

## Previews and grouped recovery

All stage-editing commands, apply, export, resolve, and publish offer `--dry-run`; previews do not normalize or save metadata, write state, or contact Git publication remotes.
Update itself retains the existing networked delivery command behavior.

Related settings/metadata writes and comparison-state updates use one grouped recovery journal.
Writes are checked against their read observations, and actual application writes are committed as whole files.
After an interrupted group, subsequent operations are blocked until `aem recover` restores the previous group.
Recovery validates every member before restoring any and refuses to overwrite later user edits.
Backups are retained alongside their files after successful writes.
Different application files retain AEM's per-target transaction boundary; a later failure does not undo earlier successful items.
Power-loss guarantees require separate filesystem evidence.
