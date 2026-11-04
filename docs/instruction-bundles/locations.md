# Instruction hooks and reading locations

This reference describes the registered Codex hooks, trust requirements, reading-location metadata, and lookup failures.
For installation steps, use the [external bundle walkthrough](install.md#original-files-before-installation).

## Hook registration and trust

`/home/me/.codex/AGENTS.md` now reads exactly the original `start.md` contents.
No locator command is inserted into that document.
Instead, AEM appends groups like the following to `hooks.json`, keeping unrelated events, groups and metadata:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "^(startup|resume|clear|compact)$",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/python -m agent_env_man --config /home/me/.config/agent-env-man/machine.toml agent-hook personal --agent codex",
            "timeout": 10,
            "statusMessage": "AEM instruction roots [generated-identity]",
            "additionalContextLimit": 1000
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/python -m agent_env_man --config /home/me/.config/agent-env-man/machine.toml agent-hook personal --agent codex --hook-event SubagentStart",
            "timeout": 10,
            "statusMessage": "AEM instruction roots [generated-identity]",
            "additionalContextLimit": 1000
          }
        ]
      }
    ]
  }
}
```

The actual interpreter is the absolute Python executable used for installation; the marker is a stable hash of the machine file path, agent, and bundle name.
Neither value needs to be supplied in the catalog.
Keep this Python environment and its installed AEM package available; rerun apply after moving the environment to update the command.

Apply includes this notice in its JSON result:

> Codex hook trust must be reviewed separately: in the next Codex session, open /hooks, review and trust the AEM hook, then start a new session.
> AEM does not grant trust or enable disabled hooks.

AEM registration is not Codex approval.
Do not bypass hook trust: review the generated command in Codex before trusting it.
Codex requires review for new or changed non-managed hooks.
Both events supply extra developer context containing path metadata, not personal instruction text.
See the [official hook documentation](https://learn.chatgpt.com/docs/hooks).

For an existing installation, run `aem apply --item personal:entry` to add the SubagentStart group, then review it through `/hooks`.
Existing SessionStart callbacks keep working; no catalog edits or ownership reset are needed.
The child group matches every subagent type and performs only saved-location lookup.
Startup update automation remains attached to SessionStart.

## Reading-location metadata

For the external example, the callback's `hookSpecificOutput.additionalContext` contains these location fields plus relative-reference guidance:

```json
{
  "root": "/home/me/Syncthing/agent-documents/guidance",
  "entry": "/home/me/Syncthing/agent-documents/guidance/start.md",
  "global_entry": "/home/me/.codex/AGENTS.md"
}
```

`global_entry` identifies the installed entry file to which these locations apply; the existing field name is retained for compatibility.
`entry` identifies its corresponding document location within the bundle, and `root` identifies the bundle directory.
An entry may be nested, so its parent directory need not equal `root`.
These fields describe locations, not the entry's subject matter or applicability.

## Resolve document references

The callback does not request another reading of the entry.
If its contents are already present in the agent's context, the agent should not reread them solely to establish these paths; the callback does not assume that the host has loaded them.
Relative references in the entry resolve from the parent directory of `entry`, not the installed entry's directory or the working directory.
References in supplemental documents resolve from each referring document's own directory, unless the user documents explicitly specify another base.
For example, an entry at `root/entry/start.md` resolves `../research/workflow.md` to `root/research/workflow.md`; a reference in that workflow uses `root/research` as its base.
The user documents continue to determine applicability and reading order; location metadata does not trigger a scan or reading of every file in the bundle.
The hook omits installation diagnostics: `aem locate personal` still reports `installed_root` (AEM's installed bundle path) and `detached` (bundle ownership released).
After detaching only the bundle directory, that installed path holds a preserved copy while the global entry still links to the live source; the hook continues to supply the live source's `root` and `entry` until the global entry is detached too.

## Lookup failures and diagnostics

The callback reads saved installation records without fetching, loading the catalog, or rewriting ownership records.
If SessionStart lookup fails, it returns a structured `continue: false` stop request and visible error instead of a guessed path.
SubagentStart lookup failure returns a visible warning without locations; that event cannot stop child creation.

Codex cannot receive that response if the interpreter itself is missing or the hook is disabled/untrusted; verify registration and trust through `/hooks`.
Keep the machine file and state directory, including after detach.
For manual diagnostics, run `aem locate personal`.

```text
Codex loads the original instructions through ~/.codex/AGENTS.md
SessionStart and SubagentStart hooks supply the actual bundle root and entry path
  -> reader resolves referenced documents using those locations
  -> e.g. /home/me/Syncthing/agent-documents/guidance/development/conventions.md
```

The hook does not inspect instruction meaning or choose which auxiliary documents apply.
The presence of `workspaces/project-alpha.md` does not create an automatic workspace rule; your documents define when to read it.
No repository-local AGENTS.md is generated.
