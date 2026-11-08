# TOML configuration reference

AEM reads two independent UTF-8 TOML documents, with integer `version = 2` for the catalog and `version = 1` for the machine file.
Filenames are arbitrary: the CLI selects a machine file, and its `catalog` field selects a local catalog or a Git repository and catalog entry.
The catalog declares reusable content and update policies; the machine file binds them to this device.
Installation and update commands reject unknown fields in the catalog and machine configuration.
Maintenance commands can ignore unrelated fields; see [validation boundaries](configuration/machine.md#storage-and-validation-boundaries).
For the command interface, see [Commands](commands.md).

The package version communicates compatibility for catalog syntax and documented machine settings; neither document has an independent SemVer release cycle.
Their integer `version` fields identify format generations and need not change for compatible additions.
Default workflows let setup/bootstrap write machine settings; direct edits to documented settings remain supported.
AEM is responsible for compatibility handling of generated machine configuration and state, within the [supported format generations](configuration/machine.md#maintenance-without-valid-installation-configuration).
Do not manually change version markers to bypass validation.
See the [versioning policy](compatibility.md).

## Paths and identifiers

Names use ASCII letters, digits, `_`, `-`, and `.`, starting with a letter or digit.
Relative content paths use `/`, with no empty, `.` or `..` components, backslashes, drive prefixes, or leading slash.
Only `subdir` accepts `.` to select the source root.
Paths are literal: AEM does not expand environment variables, interpolate other fields, or evaluate shell expressions.
Machine paths must be absolute or begin with `~/`, except a local `catalog` string, which may be relative to the machine file's directory.
Git `catalog.path` is a literal relative file path within that repository, using the relative content path rules in this section.
In WSL, use Linux paths as visible inside that environment; native Windows paths are not installation bindings.
CLI path arguments have their own resolution rules described in [Commands](commands/catalog.md#bootstrap).

## Configuration topics

Choose the reference for the declaration or binding you are editing.
All topics use the path and identifier rules in this guide.

| Reference | Scope |
| --- | --- |
| [Catalog configuration](configuration/catalog.md) | Top-level catalog structure, sources, skills, and skill/directory update policies. |
| [Directory configuration](configuration/directories.md) | General directory fields and symbolic link preservation. |
| [Instruction bundle configuration](configuration/instructions.md) | Bundle and entry fields and ownership. |
| [Payload configuration](configuration/payload.md) | Exclusion patterns and permission preservation. |
| [Machine configuration](configuration/machine.md) | Catalog bindings, device paths, agent roots, setup, and storage. |
| [Automation configuration](configuration/automation.md) | Tool, catalog, and device scheduling fields. |
| [Settings configuration](configuration/settings.md) | Shared setting declarations, targets, and per-setting schedules. |
| [Personal hook configuration](configuration/hooks.md) | Scripts, native events, runtime bindings, and ownership. |
