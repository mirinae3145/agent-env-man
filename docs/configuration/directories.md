# Directory configuration

Catalog `directories.NAME` declarations install general directories from Git or external sources.
This reference defines installation fields, symbolic link support, and preservation during policy changes.

## `directories.NAME`

General directories use Git or external sources and require no entry document, skill metadata, or agent binding.

| Field | Type | Requirement/default |
| --- | --- | --- |
| `source` | String | Required name in `sources`; Git or external. |
| `exclude` | Array of strings | Additional [payload exclusions](payload.md#payload-exclusions); defaults to `[]`. |
| `subdir` | String | Source directory; defaults to `"."`. |
| `preserve_symlinks` | Boolean | `false`; require opaque symbolic link preservation for this directory only. Execution is supported on POSIX. |
| `agent` | String | Optional destination name such as `claude-lab`; binds the directory to that destination. |
| `install` | Table | Optional installation settings below. |
| `update` | Table | Optional policy selection and overrides, using the same rules as skills. |

### Installation fields

`directories.NAME.install` accepts `root`, `destination`, and `mode`.
The entire `install` table may be omitted to use these defaults.

| Field | Default and constraints |
| --- | --- |
| `root` | Machine root name; defaults to `"home"` when no `agent` is declared. An explicit name requires a machine binding and never falls back to `home`. |
| `destination` | Literal relative directory path below the root; defaults to the item name. |
| `mode` | `"link"` by default, or explicit `"copy"`; machine `modes.NAME` overrides it. |

Bootstrap preserves a saved `roots.home`, or records the current user's absolute home directory when the binding is absent.
Use `--root home=PATH` for an explicit initial binding, or `--root NAME=PATH` to bind another declared root.

With `agent`, a machine that has not registered that destination skips the declaration, as for `settings.NAME.agent`.
A registered machine installs below that destination's root unless `install.root` names another root, and `--agent` selects the item only for that destination.
Older AEM versions reject the field.

Each declaration creates one target and ownership ID `NAME:directory`, agent-independent unless it declares `agent`; commands also accept the catalog name.
The target cannot own an entire configured root or overlap sources, other targets, catalog, stages, or manager storage.
Path and mode changes require detach before reconfiguration.

### Payload and platform support

The selected source must be a directory; its root and selected ancestry cannot redirect through links.
By default its payload accepts only regular files and directories.
Set `preserve_symlinks = true` directly under `directories.NAME` to preserve nested symbolic links in either installation mode on POSIX.
The declaration is valid on every platform; native Windows execution is unsupported and is not planned.
AEM never substitutes junctions, ordinary text files, or copies of referents.
Windows can read and update a catalog containing the declaration and operate on independent supported items.
Selecting the opted-in directory fails before content changes, even if it currently contains no links and regardless of installation mode.
Shared-source preparation, updates, and publication still check every affected consumer, including unselected declarations and orphaned active links.
Ordinary machine bindings, destination checks, and saved ownership requirements remain in force.
Use explicit item selection for independent operations; `sync --item` still updates all sources.
Full automation can explicitly exclude unsupported items through the machine's [`automation.skip_unsupported` setting](automation.md#device-automation-settings).
Other reparse points, special files, and Git submodules remain unsupported.
This option does not enable links in skills, instructions, settings, or hooks.

### Symbolic link identity and relocation

Relative link targets are interpreted component by component from the link's parent and must never step above the source root, even if later components would return inside it.
The boundary is the entire Git checkout or bound external root, not `subdir`, an entry document, or an installation/staging directory.
Absolute POSIX link targets and dangling links are allowed.
AEM preserves the original target string, without expanding, normalizing, or following it or intermediate link chains.
Link identity contributes to payload hashes; referent contents and availability do not.
Copy, detach, and recovery preserve link text, not the identity or availability of its resolved target: a relative link outside the copied subtree can resolve differently afterward.
Absolute links depend on each device's filesystem layout.
These are payload rules, not a sandbox for programs consuming the installed directory.

### Policy changes and preservation

Git tree links must materialize as actual filesystem links; text checkouts such as `core.symlinks=false` are refused without automatic configuration changes.
Ignored links participate in local payload validation, copies, and detach, but are not transmitted by Git.
External handling confirms local link preservation only; synchronization-service behavior remains outside AEM.
All affected active live consumers must permit a source change, including saved live links removed from the catalog.
When enabling the option for an existing live installation, apply the new policy before receiving a Git revision that introduces links; update protects the last installed policy until apply records its replacement.
Disabling the option refuses ordinary installation or collection while links remain in the source or managed copy; Source updates also refuse this policy transition while links remain.
Remove those links and reconcile local edits before applying the disabled policy, or detach using saved ownership.
Detach and recovery retain the saved policy and logical source location, even without a readable catalog.
Git subdirectories must exist as tracked trees; an empty directory requires a tracked placeholder file because Git does not track empty directories.
An external directory may be empty.
Source-root copy and detach automatically omit the top-level `.git` entry; Git-ignored regular files remain part of the payload unless explicitly excluded.
Existing link/copy conflict, transaction, backup, detach, and recovery contracts apply.
Ordinary publication does not collect copy edits; use explicit `publish NAME --from-copy` to collect an installed, managed directory copy.
Collection compares the last common baseline, preserves conflicting source edits, and retains backups; see [publication](../commands/publish.md).
Links expose writes and source updates immediately.
External transport remains outside AEM; copy publication only hands content to the local external source.
