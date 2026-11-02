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
| successful instruction context | SessionStart additionalContext JSON | plain stdout |
| instruction lookup failure | structured stop, exit 0 | stderr, exit 2; does not stop SessionStart |
| startup with skill changes | existing briefing | synchronous reloadSkills request |
| full async startup | worker queues; later changes need fresh session | same limitation |
| trust and preferences | owned by product/user | owned by product/user |

## Internal profile interface

| Interface members | Responsibility |
| --- | --- |
| `name`, `entry_name`, `hook_name`, `notice` | Identify the product, entry and hook files, and notices. |
| `defaults` | Return root and skill destinations. |
| `definition` | Return an identity marker and hook group. |
| `render`, `current`, `remove` | Respect saved ownership and preserve unrelated content. |
| `context`, `failure`, `startup_result` | Return the product's callback payloads. |
| `failure_to_stderr`, `failure_exit_code` | Control failure routing independently of payload type. |
| `validate_skill_name` | Validate product-specific skill directory reservations before installation. |
| `shared_settings_format` | Identify the application settings format shared with hooks, when supported. |
| `command_events`, `hook_timeout_limits`, `unmatched_hook_events`, `personal_command` | Define personal command hook events, limits, and rendering. |

Startup accepts the same `skills_changed` keyword even where the product ignores it.

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

## Named instances

The built-in `claude` and `codex` destinations retain their existing defaults, CLI meanings, ownership IDs, and callbacks.
A name prefixed with `claude-` or `codex-` selects another instance of that product; the nonempty suffix must be an AEM identifier.
For example, `claude-lab` uses Claude's native hook syntax but owns separate `@claude-lab` content IDs and callback markers.
Product implementations remain internal; instance names do not register new product implementations.

```bash
aem setup --agent claude-lab --agent codex-lab
aem bootstrap
aem apply --agent claude-lab --dry-run
aem apply --agent claude-lab
aem status --agent claude-lab
```

Setup saves default roots `~/.claude-lab` and `~/.codex-lab`, each with its own `skills` directory.
Named defaults do not reuse `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or legacy Codex roots belonging to the default destination.
Explicit machine `root` and `skills` bindings override these defaults and remain saved across environment changes.
Named root paths must not alias or nest any other configured instance root.
Existing symlinked settings or redirected target ancestry remain conflicts; setup never migrates or unlinks them automatically.
Inspect and preserve existing contents before an explicitly planned migration.

Omitting `--agent` retains the existing all-configured-destinations behavior, which includes instances explicitly added by setup.
`--agent claude` selects only the original destination, not every Claude instance.
Use `--agent claude-lab` for the additional destination; an unregistered named selection is refused rather than applying unrelated shared items.
Directories remain independent of agent selection unless they declare `agent`; a bound directory is selected only for that destination and skipped on machines that have not registered it.
Unbound legacy settings retain their existing apply behavior without a selector or with a default product selector.
A named selector excludes unbound settings so a lab-only apply cannot write a default profile's preferences; associate per-instance settings explicitly as described below.
`sync --agent` still updates all sources and filters only installation; an update can immediately affect links consumed by other instances.
Startup automation remains device-wide under the same configuration lock; an instance-specific callback does not imply instance-specific source reception.

The same skill and instruction source can supply each instance independently.
Catalog personal hooks remain product declarations (`agents.claude`, `agents.codex`); AEM expands them to matching configured instances.
Personal hook activation still requires explicit item selection, which can be narrowed by `--agent`.
Instruction entry/hook IDs include the instance suffix; skill IDs use `NAME@INSTANCE` and personal hook IDs use `NAME:hook@INSTANCE`.
Existing default IDs are unchanged.

### Independent settings from one source

Declare two catalog settings with distinct names but the same source/path/format to share intent with separate stages.
The machine binds each target and optionally its selection owner:

```toml
[settings.claude-preferences]
target = "/home/me/.claude/settings.json"
agent = "claude"

[settings.lab-preferences]
target = "/home/me/.claude-lab/settings.json"
agent = "claude-lab"
```

Here both setting names must exist in the catalog; the agent field does not clone declarations automatically.
Give the catalog declaration the same `agent` so that machines without that profile skip it instead of failing for a missing binding; see [settings declarations](configuration.md#application-settings-declarations-and-bindings).
The agent must be configured to prepare or apply an active setting, and its settings target must be inside that agent's root.
Detached associations may remain recorded after removing the instance; they cannot be reattached until it is configured again.
`apply --agent claude-lab` selects lab-preferences and leaves claude-preferences alone.
Each setting has independent conflict bases, an editable stage, and apply ownership.
The managed source fields can be equal while unrelated native values remain local.
Changing the association of an active setting requires detach and explicit reattachment; bootstrap target overrides preserve the association.
Settings source updates are still selected by setting/source names, not by agent.
There is no implicit collection from either profile or last-writer-wins propagation between them.

### Account and runtime boundaries

Instance names identify paths, not authenticated account identities.
Run each product with its selected path and use the product's own login flow:

```bash
CLAUDE_CONFIG_DIR="$HOME/.claude-lab" claude
CODEX_HOME="$HOME/.codex-lab" codex
```

On Windows, set those environment variables for the intended process using native PowerShell or the launching application.
AEM does not persist these launch variables or replace shell aliases, IDE launch settings, or Herdr launch configuration.
Authentication, expected-account checking, sessions, memory, plugin registries/caches/store/data, MCP authorization and product trust are outside this feature.
No plugin installation or account switch occurs during setup/bootstrap/apply.

This is installation separation, not a security sandbox or a guarantee of complete product discovery isolation.
Codex can also discover the global `~/.agents/skills` and repository skills; its named destination's `skills` directory does not hide those sources.
Projects, environment overrides, OS credential stores, shared servers, and external services need their own product-native isolation checks.
Native login concurrency and Windows instance execution are not established by the temporary filesystem tests.

### Removal and recovery

Detach the instance's managed content before removing its integration:

```bash
aem detach RULES:bundle RULES:entry SKILL --agent claude-lab
aem setup --remove-agent claude-lab
```

Use the actual catalog item names, and detach separately associated settings and personal hooks too.
A shared skill target still requires detaching all its consumers together.
Detach preserves files and leaves native hooks as specified by their existing contracts; setup removal removes only its owned startup integration and optional official-skill link.
Neither command deletes authentication, sessions, or plugin data.
The existing per-target journals and `recover` command also cover named destinations, including failures during grouped hook writes.
