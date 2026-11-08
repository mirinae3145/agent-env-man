# Architecture and preservation contracts

These contracts guide changes to delivery, installation, automation, and ownership.
Read the sections affected by a change alongside the authoritative [command](commands.md) and [configuration](configuration.md) references.
For contribution setup and check selection, see [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) and [Testing](testing.md).

## Managed content

The manager owns reusable installation and delivery behavior.
Personal instructions, research guidance, skills, and settings remain user-supplied content outside this repository.
Do not introduce personal policies as built-in payloads.
The official `idk-aem` skill is the exception: it documents AEM user operations and ships with the package from `skills/idk-aem/SKILL.md`.
It must not prescribe how to author managed content or restrict user-requested edits.

## Core responsibilities

The implementation separates command adaptation, shared execution, and content operations.

| Layer | Responsibility |
| --- | --- |
| Click | CLI parsing, help, and command groups. |
| Command callbacks | Adapt inputs to core operations. |
| Shared execution | Configuration loading, locks, report output, and callback failure behavior. |
| Core operations | Installation, delivery, ownership, and policy behavior, independent of Click contexts for worker and non-CLI reuse. |

These boundaries apply across the layers:

- Help and usage validation must complete before reading machine configuration or acquiring locks.
- Global options belong before the command; repeated policy options must preserve the distinction between omission and an explicit replacement list.
- Machine callbacks must emit the JSON required by their agent or worker contracts regardless of ordinary output mode.
- Release operation locks before formatting or emitting results, including specialized path output; presentation uses the completed operation's in-memory snapshot.
- The standalone installer and external update worker remain standard-library-only because they run outside the installed package environment.
- **Progress observation**: Core operations expose optional phase observations independently of Click; the CLI owns terminal detection, stderr rendering, throttling, and the reporter lifetime.
  Progress samples the current operation while a blocking read or Git subprocess runs, without touching configuration/state or performing extra filesystem inspections.
  Disabled progress creates no reporter thread; callbacks and internal workers always disable it.
  Stop and join the reporter before final output or error handling, restore nested observation scopes, and keep stdout/exit codes and queued-work outcomes authoritative.
- **Background processes**: Keep the worker lifetime pipe, process-group termination, captured output, and exit-code behavior intact.

## Contract areas

Use the contract for the behavior a change affects.
These references preserve shared boundaries while keeping each area independently readable.

| Contract | Scope |
| --- | --- |
| [Workflow design](architecture/workflows.md) | Coordinated defaults, platform support, publication, inspection, and compatibility decisions. |
| [Source delivery](architecture/delivery.md) | Live consumers, payload inspection, catalog normalization, and maintenance independence. |
| [Catalog delivery](architecture/catalog.md) | Candidate validation, local copies, Git reception, and catalog automation. |
| [Publication](architecture/publication.md) | Whole-repository publication, reverse copy collection, and prepared AEM releases. |
| [Ownership and preservation](architecture/ownership.md) | Exclusions, permissions, target transactions, and detach. |
| [Automatic execution](architecture/automation.md) | Individual policies and queued device orchestration. |
| [Setup and self-update](architecture/setup.md) | Integrations, tool replacement, official skills, and agent profile boundaries. |
| [Instruction integration](architecture/instructions.md) | Bundle installation, saved locations, metadata, and callback transport. |
| [Staged settings](architecture/settings.md) | Format adapters, comparison state, and grouped recovery. |
| [Personal hook integration](architecture/hooks.md) | Script preparation, registration ownership, and removal. |
