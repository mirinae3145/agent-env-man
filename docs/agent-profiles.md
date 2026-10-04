# Agent profile contracts

Codex and Claude Code use the same internal registry and machine bindings.
Profiles own product paths, supported hook syntax, callback output and notices.
The manager owns preparation, target conflicts, shared consumers, transactions,
detach and recovery. This is an internal extension boundary, not a public plugin
API or a general application-settings manager.

| Contract | Codex | Claude Code |
| --- | --- | --- |
| root | CODEX_HOME or ~/.codex | CLAUDE_CONFIG_DIR or ~/.claude |
| skills | ~/.agents/skills | \<root>/skills |
| entry | AGENTS.md | CLAUDE.md |
| hook file | hooks.json | settings.json; unrelated fields preserved |
| owned marker | statusMessage | command argument; supported fields only |
| successful instruction context | SessionStart additionalContext JSON | plain stdout |
| instruction lookup failure | structured stop, exit 0 | stderr, exit 2; does not stop SessionStart |
| startup with skill changes | existing briefing | synchronous reloadSkills request |
| full async startup | worker queues; later changes need fresh session | same limitation |
| trust and preferences | owned by product/user | owned by product/user |

Every profile supplies name, entry_name, hook_name, notice, failure_to_stderr,
failure_exit_code, defaults, definition,
render, current, remove, context, failure, startup_result, validate_skill_name and shared_settings_format. Personal command hooks additionally use
command_events, hook_timeout_limits, unmatched_hook_events and personal_command.
Defaults return root/skills. definition returns an identity marker and hook group.
render/current/remove respect saved ownership and preserve unrelated content.
context/failure/startup_result return the product's payload. Startup accepts the
same skills_changed keyword even where the product ignores it. Profile-specific
skill directory reservations are validated before any installation.

No manager or command branch tests an agent name to implement product behavior.
Shared runtime serialization accepts mapping or plain-text callback payloads;
failure_to_stderr and failure_exit_code explicitly control failure routing,
independently of payload type. Codex retains stdout/exit 0, Claude stderr/exit 2.
A future profile requiring
a different transport should demonstrate that need before changing this contract.

Add a future agent only after documenting its real paths, hook format, lifecycle,
trust and failure semantics. An internal registry entry then participates in the
same setup/bootstrap/apply/status/locate/detach/recover pipeline. CLI choices derive
from the registry; the standalone installer choices must be updated explicitly.
Fake-profile fixtures demonstrate reuse of both JSON and plain-text contracts;
they do not claim support for any third real product or hook schema.

Instruction catalogs remain existing bundle/entry/hook declarations. No documents
resource, owner-ID migration or application preference synchronization is added.
Consumers sharing a skill target retain upstream shared ownership behavior.
The upstream ancillary official skill still warns if two agent bindings select
the same destination; use native separate roots for new installs.

Profiles declare `shared_settings_format` when their hook file also accepts
application preferences. Claude opts into JSON; Codex keeps separate files. Shared
ownership reserves the top-level hooks subtree for group-owned integration.

Personal bindings use direct native commands with a silent identity prefix outside
script arguments. Profiles define event and field limits; the manager does not
translate payloads. See [Personal hooks](personal-hooks.md).
