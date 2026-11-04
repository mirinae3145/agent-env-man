# Content command reference

Content commands receive sources, install prepared content, and synchronize installation.
For sharing edits, see the [Publication command reference](publish.md).
Source delivery and installation have different selection and failure boundaries.

## update

```text
aem update [NAME ...] [--git-timeout TIMEOUT]
```

Select catalog skill, directory, instruction, setting, personal hook, or source names.
Bare names prefer catalog items when an item and a source have the same name; use `source:NAME` to select that source explicitly.
A source selects all its consumer items, including receiving shared settings into their editable stages without applying their application files.
An item selection retains its individual settings-reception scope, although updating its shared checkout affects every live link.
Mixed item/source selectors are deduplicated, and each shared checkout is updated once.
Omit names to retain the existing all-consumer selection; sources without consumers are visited only when explicitly selected.
For a source without consumers, the update report identifies it as `source:NAME`.
Lookup of an unknown selector fails before any source is updated.
Shared checkouts advance once and guard every active link, including orphaned declarations.
Incoming revisions must also contain valid trees for every declared skill and directory in a shared checkout, including unselected copies; validation failure preserves the current checkout.
Links change immediately; copies are refreshed by apply.
External sources only receive an existence check (`external-no-fetch`).
Selected external settings also receive their shared contents into their stages.
Dirty, divergent, local-ahead, detached, misidentified, or unsupported incoming checkouts are refused.

## apply

```text
aem apply [--agent AGENT] [--item ID ...] [--git-timeout TIMEOUT]
          [--adopt | --replace] [--reattach] [--dry-run]
```

Selection follows these rules:

- Omit items to install all declared, non-detached items except personal hooks, which require explicit selection.
- Skill and directory selectors are catalog names (directories also accept `NAME:directory`); instruction IDs are `NAME:bundle`, `NAME:entry`, and `NAME:hook`.
- Selecting an entry or hook also selects its bundle and the other instruction items.
- Selecting only a bundle installs its linked or copied directory without selecting the entry or hook.
- `--agent` filters installation destinations; directories remain included as agent-independent targets unless they declare `agent`.

Explicit installation permissions have these requirements:

| Option | Effect | Selection requirement |
| --- | --- | --- |
| `--adopt` | Record matching existing content. | Explicit `--item`. |
| `--replace` | Back up and replace a conflict. | Explicit `--item`. |
| `--reattach` | Reinstall detached content. | Explicit `--item`. |

An implicitly selected bundle does not gain replacement permission.
Dry run validates and shows planned actions without changing targets or ownership.
Prepared checkouts must be clean even though this command does not fetch.
[Catalog payload exclusions](../configuration/payload.md#payload-exclusions) skip inspection and copying of matching entries while preserving existing excluded entries in installed copies.
Replacing an included ancestor of an excluded entry with a file, link, or absence is refused, including with `--replace`.
General directories may opt into POSIX nested symbolic links through [directory configuration](../configuration/directories.md#directoriesname); apply preserves raw link text and never copies referent contents.

## sync

```text
aem sync [--agent AGENT] [--item ID ...] [--git-timeout TIMEOUT]
```

Updates all sources, then applies only if every update succeeds.
`--item` and `--agent` filter the apply phase only; they do not narrow the update phase.
This command has no throttle and ignores automatic policy clocks.
For throttled event-based work, configure policies and use `auto`.
