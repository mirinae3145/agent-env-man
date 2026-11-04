# Agent profile command reference

Profile commands compare or seed Claude Code profiles and check tool-owned hooks.
Named destination selection also applies to ordinary installation commands.

## Named agent destination selection

`setup --agent` accepts `claude-NAME` and `codex-NAME` in addition to the existing product destinations.
It saves separate roots, startup groups and official-skill ownership without authenticating an account or installing plugins.
Other `--agent` selectors accept those saved names as exact destinations; `--agent claude` still means only the original Claude destination.
Omitting the selector includes all configured destinations under each command's existing selection contract.
An instance name is not a product-wide selector or Codex's native configuration preset.
Catalog hook bindings select products and expand to their configured instances.
Agent-associated settings are selected only for their bound instance.
Unbound settings preserve their previous apply behavior without a selector or with the original product selectors; named selectors exclude them.
Directories remain agent-independent unless they declare `agent`, and `sync` still updates all sources before filtering installation.
See [named instances](../agent-instances.md) for binding examples, setting stages, callbacks and removal.

## compare

```text
aem compare LEFT RIGHT [--expect ITEM]... [--values]
```

LEFT and RIGHT are registered agent names such as `claude` and `claude-lab`, or absolute profile root paths.
A path needs no machine configuration, catalog or saved state; the command takes no locks and writes nothing.
It supports the Claude Code profile layout and refuses other products.

The comparison covers the settings fields outside `hooks`, hook groups by owner, skill links, output styles, the instruction entry and the installed plugin names with their versions.
It never opens credentials, sessions, project history or plugin data.

- **Settings fields**: Settings fields are compared leaf by leaf; arrays and empty objects are atomic, numbers compare by exact value and stay apart from booleans, and a missing field is distinct from `null`.
  In reported field names, literal dots and backslashes in JSON keys are escaped as `\.` and `\\`; nested fields still use an unescaped dot.
  For example, the literal key `a.b` is reported as `a\.b`, separately from the nested field `a.b`; use that reported spelling with `--expect`.
- **Hook groups**: A hook command is AEM-owned when it carries `--aem-hook-id` or an AEM personal-hook identity marker, including inside the encoded PowerShell command AEM writes on Windows; this is the same rule `copy-profile` uses.
  A group's AEM-owned commands and its other commands are compared as separate items, each reporting its `owner`.
  An AEM-owned item with `--aem-hook-id` names its own machine configuration, so only its presence is compared.
  Other items, including personal hooks, are compared by their commands with the identity marker removed, so the same hook compares equal across agents; their labels carry a short digest of the command.
  A group repeated a different number of times on each side is a difference that shows both counts.
- **Links and entries**: Skill links, output styles and the instruction entry compare link targets, with relative targets resolved against the link's folder; an instruction file compares by its text.
- **Profile paths**: A string that contains a profile's own root, ending at a path boundary, is compared with the root replaced by `{root}`, so a profile-specific path is not a difference while a sibling such as `.claude-lab` next to `.claude` is left alone.
  The root is recognized as an absolute path, with forward slashes, and, inside the home folder, after `~/`, `$HOME/` or `${HOME}/`.

Each item is `same`, `different`, or `expected` when `--expect ITEM` names it as the report prints it, for example `model`, `statusLine.command`, `skills/NAME`, `plugins/NAME@MARKETPLACE` or a hook label; naming a settings object such as `permissions` also covers every field below it.
`unmatched_expect` lists names that matched no item.
A difference shows a short digest of each value, because settings can hold secrets; `--values` shows the values.
Plugin versions and the entry are always shown.
Exit status is 0 whether or not differences exist; scripts read the totals from `--json`.
Malformed hook event or group structures are refused with an error instead of being treated as absent hooks.

## check-tool-hooks

```text
aem check-tool-hooks [--agent NAME]...
```

Reads the machine's [`tool_hooks`](../configuration/machine.md#tool-hooks) declarations and the settings files of the registered Claude Code agents; it takes no locks and writes nothing.
A tool whose `command` is not on `PATH` is reported as skipped.
For an installed tool, each selected agent must have a hook under the declared event whose command contains the declared text; otherwise the agent is `missing` and the report says how to install the tool's integration for that profile.
AEM never installs or changes tool hooks.
`--agent` limits the check to registered Claude Code agents.
Exit status is 1 when any hook is missing, so `--json` is for details rather than for deciding success.

## copy-profile

```text
aem copy-profile SOURCE TARGET [--set FIELD=VALUE]... [--write]
```

SOURCE is a registered agent name or an absolute profile root; TARGET is a new absolute root that does not exist or is an empty folder and must not overlap the source.
Without `--write` the command only shows what would be copied.
It needs no machine configuration and never changes it or the saved state; register TARGET as an agent yourself.
A preview takes no locks; `--write` takes the same operation lock as other writing commands, which creates the configuration's state directory if it does not exist yet.
It supports the Claude Code profile layout and refuses other products.

Copied: the settings fields outside AEM-generated hooks, with exact numbers and the source file's permissions, and the instruction entry, output styles, skill links and `hooks/` files that AEM did not install (links you made yourself are kept).
Links are recreated against their own targets (relative links are resolved first), so the copy does not point into the source, and strings containing the source root, in any spelling `compare` recognizes, are rewritten to TARGET.
`--set` changes a settings field in the copy only; the path is dotted, the value is JSON or plain text, and `hooks` cannot be set.
Not copied: anything recorded as an AEM installation target in the machine's saved state (reported as skipped; `aem apply --agent NAME` creates it for the new profile, which a copied link would turn into a conflict), credentials, sessions, project history, plugin data, installed plugins, skill entries that are not links, and AEM-generated hook commands (other commands in the same group are kept).
The report lists the product CLI steps that would reinstall the source's user-scope plugins in TARGET (`claude plugin marketplace add`, then `claude plugin install`, each with `CLAUDE_CONFIG_DIR` set to TARGET) as `plugin_steps`; AEM never runs them, a plugin whose marketplace source is unknown is listed as skipped, and the installed versions follow each marketplace's current release.
Hook groups and links AEM installed belong to the source's agent, so register TARGET with `aem setup --agent NAME` and run `aem apply --agent NAME --dry-run`, then without `--dry-run`, to give it its own.

The copied settings are an independent file: later changes to either profile do not reach the other.
To share selected fields afterwards, declare them as settings for each profile as described in [named instances](../agent-instances.md#independent-settings-from-one-source) and [staged settings](../settings-management.md).

The profile is built in a staging folder beside TARGET and moved into place, so a failure leaves no partial profile.
If the final move fails after removing an existing empty TARGET, AEM recreates the empty folder with its previous permissions unless another writer has created a new target.
A target populated during staging is preserved and the copy is refused.
After writing, the copy is compared with the source: `expected` counts the `--set` fields, `not_copied` counts plugins, AEM-owned hooks and AEM-installed links left out, and `unexpected` lists anything else that differs, including a hook of your own missing from the copy.
