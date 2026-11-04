# Catalog configuration

The catalog declares shared sources and installable content.
This reference defines its top-level structure, Git skills, and skill/directory update policies.

## Catalog

The only top-level fields are `version`, `sources`, `skills`, `directories`, `instructions`, `settings`, `hooks`, `updates`, and `payload`.
All tables are optional; an instruction-only catalog needs no skills table.
Skill, directory, instruction, setting and personal hook names share a namespace; source names have a separate namespace.
A source declaration is not an installable item by itself.

```toml
version = 2

[sources.tools]
type = "git"
repository = "https://github.com/OWNER/TOOLS.git"

[sources.documents]
type = "external"

[skills.report]
source = "tools"
subdir = "skills/report"

[skills.report.install]
mode = "link"

[instructions.personal]
source = "documents"
entry = "AGENTS.md"

[instructions.personal.install.entry]
root = "agent"

[updates.defaults]
trigger = []
```

## `sources.NAME`

Every source requires an explicit `type`, either `"git"` or `"external"`.
Git sources accept only `type`, required `repository`, and optional `branch`, `exclude`, and `permissions`.
`repository` is a Git URL, SSH repository location, or absolute local repository path.
When `branch` is absent, bootstrap discovers and records the remote default branch.
External sources accept `type` and optional `exclude` and `permissions`; their device-local paths belong in machine `external_paths.NAME`.
External sources support directories, instruction bundles, staged settings and personal hooks; skills still require Git sources.
AEM neither fetches external folders nor administers the service that synchronizes them.

Items referencing the same source name share its checkout; different names have independent checkouts even with equal URLs.
Git storage is `CHECKOUT_ROOT/.aem-repositories/NAME`, preserving the former named-repository path.
All consumers are validated before bootstrap publishes a shared checkout.
Unknown source names and unknown fields are rejected.
TOML duplicate source names are invalid, including Git/external name collisions.

## `skills.NAME`

A skill declaration accepts these fields:

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name of a Git source in `sources`. |
| `exclude` | Array of strings | Additional [payload exclusions](payload.md#payload-exclusions); defaults to `[]`. |
| `subdir` | String | Directory containing the fixed entry file `SKILL.md`; defaults to `"."`. |
| `install` | Table | Optional installation settings defined in this section. |
| `update` | Table | Optional [update policy](#update-policies) selection and overrides. |

`skills.NAME.install` accepts only `root` and `mode`.
`root` is an optional name in machine `roots`; the target directory is `ROOT/NAME`.
`mode` is `"link"` (default) or `"copy"`; machine `modes.NAME` overrides it.
With `install.root` omitted, selected agents supply their skill destinations.
Without selected agents, machine `roots.skills` is required; bootstrap supplies its default.
An explicit root overrides agent destinations; agents sharing a target share one ownership record.

Skill names identify installation ownership and directory names, independently of the name inside `SKILL.md`.
Root skills link directly to the repository root; copy and detach automatically exclude its top-level `.git` entry and honor configured payload exclusions.

Git-ignored regular files, including runtime caches, may coexist with prepared sources and are part of the directory payload.
Directory links expose them, and copy/detach preserve them; AEM does not guess which ignored files are disposable or delete them.
Tracked changes and nonignored untracked files still block bootstrap, apply, and update.
Fast-forwards refuse incoming paths that would overwrite ignored local files, including file/directory collisions; relocate or reconcile the conflicting files explicitly before retrying.
Installed copies retain full-tree ownership checks, so a cache created or changed in the installed copy counts as a local edit and blocks automatic replacement.

## Update policies

Policy tables are `updates.defaults`, `updates.policies.NAME`, and `skills.NAME.update`, and `directories.NAME.update`.
No other fields belong directly under `updates`.

| Field | Type | Built-in default and constraints |
| --- | --- | --- |
| `trigger` | String array | `[]` disables automatic execution; otherwise unique events: `"shell-start"`, `"agent-start"`, `"interval"`. Strings and `"manual"` are invalid. |
| `action` | String | `"sync"` or `"check"`; default `"sync"`. |
| `min_interval` | Integer or float | `600` seconds; finite and nonnegative. Boolean values are invalid. |
| `timeout` | Integer or float | `30` seconds per Git phase; finite and positive. Boolean values are invalid. |
| `policy` | String | Optional name in `updates.policies`; allowed only in `skills.NAME.update` or `directories.NAME.update`. |

Resolution order is built-ins, catalog defaults, selected named policy, then item-local fields.
Only supplied fields override earlier values; trigger arrays replace earlier arrays.
In full mode, omitted policies participate by default, but an explicit or inherited `[]` excludes the skill or directory.

Effective policy JSON retains the existing `["manual"]` representation for disabled automatic execution; machine policy syntax is unchanged.
Named policies cannot inherit another policy.
All declarations, including unused named policies, are validated before network access.

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
min_interval = 600

[updates.policies.observe]
action = "check"

[skills.report.update]
policy = "observe"
timeout = 5
```

`check` fetches references without moving the checkout or installing targets.
`sync` fast-forwards and applies each successful skill or directory independently.
For an external directory, `check` validates local source availability without Git transport and reports `external-no-fetch`; `sync` validates and applies the local source.

Each skill or directory records attempts before network access; failures and successes share its throttle across events.
A shared checkout update changes all live links immediately, including linked instructions; copy installation still follows selected items.

Policies do not register hooks or launch a scheduler; use `setup` or arrange external `auto` calls.
Explicit commands ignore these policies and clocks.
