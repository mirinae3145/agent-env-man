# Testing and distribution verification

[Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) provides the development setup and basic check commands.
Use this guide to select portability, distribution, and coverage checks for the affected contracts.
Tests must use temporary homes, configuration, targets, and local Git remotes rather than real user profiles or credentials.

## Validation expectations

Choose checks by the affected contract, using temporary local Git fixtures and fake installers where needed.

| Affected area | Required behavior checks |
| --- | --- |
| Source delivery | Clone, fast-forward, dirty/divergent histories, network/remote failures, and active live-link guards. |
| Catalog declarations and delivery | No source-local `links.conf` prerequisite; root and nested skills; inventory independent of checkouts/targets; registration and saved-binding reuse; invalid incoming catalogs; ownership conflicts; offline maintenance; local edits and remote failures. |
| Installation | Unmanaged targets, local edits, directory contents, unrelated hook preservation, detach, and failure recovery. |
| Automatic policies | Precedence, empty-trigger opt-out, event selection, offline previews and check-only behavior, per-item throttling including failures, independent outcomes, local edits, and detached content. |
| Content publication | Shared skill/instruction consumers, unrelated files, existing commits, offline previews, rejected histories, remote failure, and retry. |
| Full automation | Actual fresh-CLI continuation, stage ordering, new declarations, exclusions, throttling, cancellation, lock handoff, and failure gates. |
| AEM self-update | Release boundaries, annotated tags, metadata mismatches, policy cancellation, contention, failure/retry, and worker lifetime. |

Cross-cutting requirements:

- Verify that missing inventory files still allow status to observe installed contents and detach to preserve them.
- Test meaningful user-visible behavior and preservation boundaries rather than mirroring private implementation functions.
- For workflows spanning commands, verify that outputs and selection scope match the next command's inputs and operation targets, including update/bootstrap/apply and locate/edit/publish.
- Where source and installation can differ, cover link, copy, and detached states and verify which content editing and subsequent commands consume.
- Installation and update paths must reject unknown fields and invalid types rather than accepting misspelled or removed settings.
- Update examples and platform limitations with interface changes.

## Mounted filesystem checks

For a mounted POSIX filesystem, verify exclusions using disposable source and target directories on that filesystem:

```bash
PYTHONPATH=src python scripts/verify_payload_mount.py --root /path/to/mount
```

The verifier removes only its own temporary test directory and keeps machine state in a separate local temporary directory.
It checks copy installation, excluded metadata preservation, status, reverse collection, preservation refusals in previews, and detach through fresh CLI processes.
Record the actual filesystem and mount used; a successful check on a mount's parent directory does not establish remote-filesystem behavior.

## Choose an execution guide

Select the checks required by the affected contract, then use the appropriate execution guide.

- [Test environment contracts](testing/environments.md) covers isolated fixtures, supported environments, and limits of platform evidence.
- [CI and agent integration checks](testing/ci.md) describes the CI jobs, local reproduction, and unauthenticated agent checks.
- [Installed distribution verification](testing/distribution.md) covers isolated builds and runtime environments without development dependencies.
- [Coverage measurement](testing/coverage.md) covers measurement commands, reports, and interpretation limits.
