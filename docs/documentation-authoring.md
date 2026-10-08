# Documentation authoring

Use the README for getting started and user workflows, and [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) for development setup and contribution decisions.
Keep CLI and TOML details canonical in [Commands](commands.md) and [Configuration](configuration.md).
Detailed contributor contracts live in [Architecture](architecture.md) and [Testing](testing.md).
Keep change-specific validation results with the change, rather than adding them to durable contributor guidance.

## Guide structure

Keep the README focused on installation, a minimal working example, everyday commands, and preservation boundaries.
Link advanced workflows to their detailed guides.

Within detailed guides, group related information under descriptive subheadings so readers can find prerequisites, steps, selection scope, constraints, outcomes, and recovery.
Choose the structure for the topic rather than repeating a fixed template in every section.
Use ordered lists for sequential procedures, bullets for independent requirements, and tables for comparable choices or field contracts.
Keep explanatory prose for rationale and relationships; avoid turning every sentence into a list item.
Preserve existing linked headings when adding structure, or update every affected cross-reference.

## CLI help scope

CLI help is the installed, version-matched entry point for choosing and invoking commands.
Explain the target being read or changed, selection identifiers and scope, omitted-option behavior, and non-obvious prerequisites or option incompatibilities when these affect correct use.
For workflows spanning multiple commands, make clear which phase a selector filters and which content each command consumes, such as a source, editable stage, or actual application file.
Describe consequential defaults and preview limits concisely enough to choose the operation without reading a full guide.

### Keep help concise and available

Keep help focused on invocation decisions; retain full schemas, output contracts, detailed recovery procedures, and extended examples in the authoritative documentation.
Do not reproduce a manual in command help or compensate for missing help by copying syntax and procedures into the official skill.
When removing operational detail from the skill in favor of CLI discovery, verify that the relevant help actually supplies the information needed for the task.
A repository-local document is not necessarily available in an installed package; only advertise local documentation entry points that the installation provides.
Help must remain available without valid machine configuration, loading catalogs, acquiring locks, or running operations.
For help changes, inspect rendered command output and verify this boundary; avoid tests that lock down exact prose.

## Installed documentation

Ship `README.md`, `docs/`, `examples/`, and `LICENSE.txt` as version-matched local package resources, preserving their repository-relative directory structure.
`aem docs` identifies the local README and documentation root without reading machine configuration, acquiring locks, fetching, or requiring an agent/shell integration.
Package installation provides these resources; setup only connects integrations and does not download documentation.
Keep canonical sources at the repository root and copy them unchanged during builds; do not maintain a second authored copy or rewrite Markdown links at build time.
The documentation copy of LICENSE.txt and the packaging-standard metadata license must both come from the same source file; do not add installation-time symlinks.

### Links and build verification

Exclude CONTRIBUTING.md and CHANGELOG.md from installed documentation resources.
Links to contribution instructions and release history use repository web URLs as optional references, not required paths for ordinary tool use.
User-facing compatibility policy lives in [Compatibility](compatibility.md); both contributor guidance and user documentation reference this single policy.
Use relative links among bundled documents and examples so they work in a checkout and an installation.
Build hooks must resolve from the configured source layout without relying on the caller's Python module search path.
Verify isolated wheel builds, wheel contents, wheel builds from the sdist, installed local lookup, and local link/anchor resolution when changing packaging or documentation structure.

## Official skill guidance

The packaged [idk-aem skill](https://github.com/mirinae3145/agent-env-man/blob/master/skills/idk-aem/SKILL.md) should help agents choose and carry out AEM operations, with emphasis on important behavior, sequencing, and non-obvious consequences.
Organize the skill by the user's intended task, with enough basic commands and sequencing to carry out ordinary workflows directly.
Do not lead with command inventories or require interface discovery before every operation.
Keep exhaustive options, configuration schemas, and detailed procedures in installed CLI help and authoritative local documentation.
When a workflow leaves a decision unresolved, consult the relevant installed command help first, then the matching local documentation only if help is insufficient.
Give agents concrete local entry points, explain when to consult them, and reuse already verified guidance until the runtime changes or an incompatibility appears.
Use documentation paths only when they resolve in the installed environment; do not rely on repository-relative paths to unbundled files or web links that require fetching documentation.
Use the local help and documentation provided by the installation.
Treat missing or incomplete advertised materials as an installation or documentation issue; do not add fallback instructions to the skill.
Keep essential guidance inline when it prevents a material mistake, rather than making ordinary use depend on loading an entire manual.
Do not move duplicated manuals into skill references merely to shorten the entrypoint.

### Preserve decision guidance

Retain distinctions that affect the requested outcome, such as preparation versus installation, source versus installed copy, live-link update effects, settings stages versus actual files, repository-wide publication, and preservation during recovery.
The skill must not impose content-authoring policies or infer publication authorization from an editing request.
When changing user-facing commands, options, configuration, or workflows, review the skill's guidance and documentation entry points in the same change.
Update the skill when its decision guidance or discovery route changes; a new option or documentation detail alone does not require copying it into the skill.
Verify that referenced documentation is available and retained guidance agrees with the actual command behavior.
