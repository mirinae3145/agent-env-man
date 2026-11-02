# Agent profile contracts

Codex and Claude Code use the same internal registry and machine bindings.
Profiles own product paths, supported hook syntax, callback output and notices.
The manager owns preparation, target conflicts, shared consumers, transactions, detach and recovery.
This is an internal extension boundary, not a public plugin API or a general application-settings manager.

## Product contracts

| Contract | Codex | Claude Code |
| --- | --- | --- |
| root | CODEX_HOME or ~/.codex | CLAUDE_CONFIG_DIR or ~/.claude |
| skills | ~/.agents/skills | \<root>/skills |
| entry | AGENTS.md | CLAUDE.md |
| hook file | hooks.json | settings.json; unrelated fields preserved |
| owned marker | statusMessage | command argument; supported fields only |
| successful instruction context | event-specific additionalContext JSON | SessionStart plain stdout; SubagentStart additionalContext JSON |
| instruction lookup failure | SessionStart structured stop; SubagentStart warning; exit 0 | stderr, exit 2; neither start event stops |
| startup with skill changes | existing briefing | synchronous reloadSkills request |
| full async startup | worker queues; later changes need fresh session | same limitation |
| trust and preferences | owned by product/user | owned by product/user |

## Internal profile interface

Profiles expose these internal capabilities to the shared manager and runtime.

| Interface members | Responsibility |
| --- | --- |
| `name`, `entry_name`, `hook_name`, `notice` | Identify the product, entry and hook files, and notices. |
| `defaults` | Return root and skill destinations. |
| `instruction_events`, `definition` | Select instruction events and return each event's identity marker and group; startup stays on SessionStart. |
| `render`, `current`, `remove` | Respect saved ownership and preserve unrelated content. |
| `context`, `failure`, `startup_result` | Return the product's callback payloads. |
| `failure_to_stderr`, `failure_exit_code` | Control failure routing independently of payload type. |
| `validate_skill_name` | Validate product-specific skill directory reservations before installation. |
| `shared_settings_format` | Identify the application settings format shared with hooks, when supported. |
| `command_events`, `hook_timeout_limits`, `unmatched_hook_events`, `personal_command` | Define personal command hook events, limits, and rendering. |

Startup accepts the same `skills_changed` keyword even where the product ignores it.
Instruction rendering retains `hook_group` for SessionStart and records additional event groups separately.
Legacy ownership without additional groups remains valid; apply adds new groups without treating them as deleted managed hooks.
Each event retains conflict checks, and all groups for a target share one replacement transaction.

No manager or command branch tests an agent name to implement product behavior.
Shared runtime serialization accepts mapping or plain-text callback payloads; failure_to_stderr and failure_exit_code explicitly control failure routing, independently of payload type.
Codex retains stdout/exit 0, Claude stderr/exit 2.
A future profile requiring a different transport should demonstrate that need before changing this contract.

## Add an agent profile

Add a future agent only after documenting its real paths, hook format, lifecycle, trust and failure semantics.
An internal registry entry then participates in the same setup/bootstrap/apply/status/locate/detach/recover pipeline.
CLI choices derive from the registry; the standalone installer choices must be updated explicitly.
Fake-profile fixtures demonstrate reuse of both JSON and plain-text contracts; they do not claim support for any third real product or hook schema.

Instruction catalogs use bundle/entry/hook declarations.
Consumers sharing a skill target share ownership; ancillary official skill installation warns when agent bindings select the same destination.
Use separate agent skill roots for new installations.

## Shared settings and personal hooks

Profiles declare `shared_settings_format` when their hook file also accepts application preferences.
Claude opts into JSON; Codex keeps separate files.
Shared ownership reserves the top-level hooks subtree for group-owned integration.

Personal bindings use direct native commands with a silent identity prefix outside script arguments.
Profiles define event and field limits; the manager does not translate payloads.
See [Personal hooks](personal-hooks.md).
