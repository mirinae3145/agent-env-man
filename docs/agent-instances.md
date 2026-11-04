# Named agent instances

Use named instances to install reusable content into separate Codex or Claude Code roots.
Instance names select filesystem destinations, not authenticated accounts.

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

## Setup defaults

Setup saves default roots `~/.claude-lab` and `~/.codex-lab`, each with its own `skills` directory.
Named defaults do not reuse `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or legacy Codex roots belonging to the default destination.
Explicit machine `root` and `skills` bindings override these defaults and remain saved across environment changes.
Named root paths must not alias or nest any other configured instance root.
Existing symlinked settings or redirected target ancestry remain conflicts; setup never migrates or unlinks them automatically.
Inspect and preserve existing contents before an explicitly planned migration.

## Agent selection

Omitting `--agent` retains the existing all-configured-destinations behavior, which includes instances explicitly added by setup.
`--agent claude` selects only the original destination, not every Claude instance.
Use `--agent claude-lab` for the additional destination; an unregistered named selection is refused rather than applying unrelated shared items.
Directories remain independent of agent selection unless they declare `agent`; a bound directory is selected only for that destination and skipped on machines that have not registered it.

Unbound legacy settings retain their existing apply behavior without a selector or with a default product selector.
A named selector excludes unbound settings so a lab-only apply cannot write a default profile's preferences.
Associate per-instance settings using [independent stages](#independent-settings-from-one-source).

`sync --agent` still updates all sources and filters only installation.
An update can immediately affect links consumed by other instances.
Startup automation remains device-wide under the same configuration lock; an instance-specific callback does not imply instance-specific source reception.

## Shared sources and content IDs

The same skill and instruction source can supply each instance independently.
Catalog personal hooks remain product declarations (`agents.claude`, `agents.codex`); AEM expands them to matching configured instances.
Personal hook activation still requires explicit item selection, which can be narrowed by `--agent`.
Instruction entry/hook IDs include the instance suffix; skill IDs use `NAME@INSTANCE` and personal hook IDs use `NAME:hook@INSTANCE`.
Existing default IDs are unchanged.

## Independent settings from one source

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
Give the catalog declaration the same `agent` so that machines without that profile skip it instead of failing for a missing binding; see [settings declarations](configuration/settings.md#application-settings-declarations-and-bindings).
The agent must be configured to prepare or apply an active setting, and its settings target must be inside that agent's root.
Detached associations may remain recorded after removing the instance; they cannot be reattached until it is configured again.

`apply --agent claude-lab` selects lab-preferences and leaves claude-preferences alone.
Each setting has independent conflict bases, an editable stage, and apply ownership.
The managed source fields can be equal while unrelated native values remain local.
Changing the association of an active setting requires detach and explicit reattachment; bootstrap target overrides preserve the association.
Settings source updates are still selected by setting/source names, not by agent.
There is no implicit collection from either profile or last-writer-wins propagation between them.

## Account and runtime boundaries

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

## Removal and recovery

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
