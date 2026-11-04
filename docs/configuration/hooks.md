# Personal hook configuration

Catalog hook declarations select scripts and native events; machine runtime bindings select their interpreters.
This reference covers fields, supported events, and ownership identities.

## Personal hook declarations and runtime bindings

`hooks.NAME` accepts exactly `source` (a declared source name) and `agents` (a nonempty table of product bindings).
Names share the content namespace.
At least one declared agent must be selected by the machine.
Each binding accepts:

| Field | Contract |
|---|---|
| `event` | Required supported native event, case-sensitive. |
| `runtime` | Required identifier in machine `runtimes`. |
| `script` | Required literal source-relative regular UTF-8 file; no redirected paths. Git files must be tracked. |
| `args` | Optional array of literal strings, default `[]`; no shell templates or NUL. |
| `timeout` | Positive integer seconds; defaults to 10, except Codex SessionEnd/Interrupt default and maximum 3. |
| `matcher` | Optional native regular-expression string; expressions must pass Python regex syntax validation (`"*"` is also accepted as match-all), and unsupported matcher events are refused. Use expressions supported by the target product. |

### Supported personal hook events

Both profiles support SessionStart, SessionEnd, PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SubagentStart, Stop, SubagentStop and UserPromptSubmit.
Codex additionally supports Interrupt; Claude additionally supports PostToolUseFailure.
UserPromptSubmit and Stop do not accept matchers; Codex Interrupt also refuses them.
Claude SessionEnd timeout is capped at 60 seconds.
Only command hooks are supported; async/prompt/agent hooks, environment maps and plugin-only fields are not part of this declaration.
Native products may impose additional event restrictions; the script must follow their actual contract.

### Runtime binding and ownership

Machine `runtimes` maps identifiers to absolute existing executable paths:

```toml
[runtimes]
python = "/absolute/python"
```

Interpreter paths preserve symlinks, including virtualenv interpreter paths, so execution uses the bound environment rather than its base interpreter.
Bootstrap's repeated `--runtime NAME=PATH` binds these paths without installing anything.
Omitted bindings persist.
Duplicate names in one call are refused.

This additive syntax keeps catalog version 2 and machine version 1; older AEM packages reject the new fields.
No migration is needed for existing catalogs.

Personal ownership IDs are `NAME:hook` for Codex and `NAME:hook@claude` for Claude.
Select `NAME` to apply all declared agent bindings, or an exact ID for one binding; `--agent` further filters the selection.
Plain apply and automatic full mode exclude these items.
See [Personal hooks](../personal-hooks.md) for the lifecycle.
