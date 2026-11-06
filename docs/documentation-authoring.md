# Documentation authoring

This guide defines the Markdown writing procedure, content placement, CLI help, installed documentation, and official skill guidance.
Use the README for getting started and user workflows, and [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) for development setup and contribution decisions.
Keep CLI and TOML details canonical in [Commands](commands.md) and [Configuration](configuration.md).
Detailed contributor contracts live in [Architecture](architecture.md) and [Testing](testing.md).
Keep change-specific validation results with the change, rather than adding them to durable contributor guidance.

## Guide structure

For Markdown changes, including root documents, guides, and the official skill, follow the [mddt](https://github.com/mirinae3145/mddt) skill's [writing procedure](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/writing.md).
Place content in the document tree before writing it, and reread each changed topic whole once it settles.
The checker then covers only the requirements a parser can decide, and authors and reviewers judge the rest of the [document model](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/model.md).
Read the procedure from an installed mddt skill or a checkout of the mddt repository, which also provides the checker.
Sentence-only corrections and formatting changes that preserve structure need no new placement plan.

A requested reorganization of existing documents follows the procedure's [restructuring order](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/writing.md#restructuring-an-existing-tree).

### Plan and revise

The procedure's [placement steps](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/writing.md#placing-a-document) decide where content goes, and AEM adds these placement rules:

- **Canonical homes**: Locate the content's home through the [documentation index](README.md), and keep CLI and TOML contracts canonical in their references.
- **README**: Keep the README focused on installation, a minimal example, everyday commands, and preservation boundaries, with links to detailed guides.
- **Code and documentation together**: When code and documentation change together, rewrite overviews, parent summaries, and affected links after the behavior settles.

### Review and check

Authors and reviewers remain responsible for meaning, placement, and organization even where the checker reports no findings.
Complete the procedure's [checking](https://github.com/mirinae3145/mddt/blob/main/skills/mddt/references/writing.md#checking) before treating the documentation change as ready:

1. Reread each changed topic as a whole against the model and its reader's task, including whether parent summaries introduce the settled content.
1. Run the mddt checker on the changed Markdown files, or on the whole tree when documents or headings were added, moved, or renamed.
1. Judge the findings in context as the procedure describes, and rerun the checker once after corrections.
1. Report the checker commit, the checked scope, and each warning kept after judgment with its reason.

Run the local check from the repository root with uv and an installed skill or a checkout:

```bash
uv run <mddt-skill-dir>/scripts/mddt.py --root . FILE...
```

Replace `FILE...` with the changed files, or `.` for the whole tree.
The [CI document check](testing/ci.md#document-structure) runs the checker from mddt's current default branch and prints the commit it used.
When local findings differ from CI, compare the two commits before judging them, and use the [local reproduction command](testing/ci.md#local-reproduction) to rerun the CI check.

## CLI help scope

CLI help must support invocation decisions and remain available independently of machine configuration.

### Invocation decisions

CLI help is the installed, version-matched entry point for choosing and invoking commands.
Explain the target being read or changed, selection identifiers and scope, omitted-option behavior, and non-obvious prerequisites or option incompatibilities when these affect correct use.
For workflows spanning multiple commands, make clear which phase a selector filters.
Also make clear which content each command consumes, such as a source, editable stage, or actual application file.
Describe consequential defaults and preview limits concisely enough to choose the operation without reading a full guide.

### Keep help concise and available

Keep help focused on invocation decisions; retain full schemas, output contracts, detailed recovery procedures, and extended examples in the authoritative documentation.
Do not reproduce a manual in command help or compensate for missing help by copying syntax and procedures into the official skill.
When removing operational detail from the skill in favor of CLI discovery, verify that the relevant help actually supplies the information needed for the task.
A repository-local document is not necessarily available in an installed package; only advertise local documentation entry points that the installation provides.

Help must remain available without valid machine configuration, loading catalogs, acquiring locks, or running operations.
For help changes, inspect rendered command output and verify this boundary; avoid tests that lock down exact prose.

## Installed documentation

Installed documentation provides the same canonical guides as the checkout, with working offline links.

### Resource contents

Ship `README.md`, `docs/`, `examples/`, and `LICENSE.txt` as version-matched local package resources, preserving their repository-relative directory structure.
`aem docs` identifies the local README and documentation root without reading machine configuration, acquiring locks, fetching, or requiring an agent/shell integration.
Package installation provides these resources; setup only connects integrations and does not download documentation.

Keep canonical sources at the repository root and copy them unchanged during builds.
Do not maintain a second authored copy or rewrite Markdown links at build time.
The documentation copy of LICENSE.txt and the packaging-standard metadata license must both come from the same source file; do not add installation-time symlinks.

### Links and build verification

Exclude CONTRIBUTING.md and CHANGELOG.md from installed documentation resources.
Links to contribution instructions and release history use repository web URLs as optional references, not required paths for ordinary tool use.
User-facing compatibility policy lives in [Compatibility](compatibility.md); both contributor guidance and user documentation reference this single policy.
Use relative links among bundled documents and examples so they work in a checkout and an installation.

Build hooks must resolve from the configured source layout without relying on the caller's Python module search path.
Verify isolated wheel builds, wheel contents, wheel builds from the sdist, installed local lookup, and local link/anchor resolution when changing packaging or documentation structure.

## Official skill guidance

The official operations skill guides task selection and execution using installed interfaces.

### Workflow guidance

The packaged [idk-aem skill](https://github.com/mirinae3145/agent-env-man/blob/master/skills/idk-aem/SKILL.md) should help agents choose and carry out AEM operations, with emphasis on important behavior, sequencing, and non-obvious consequences.
Organize the skill by the user's intended task, with enough basic commands and sequencing to carry out ordinary workflows directly.
Do not lead with command inventories or require interface discovery before every operation.
Keep exhaustive options, configuration schemas, and detailed procedures in installed CLI help and authoritative local documentation.

Keep essential guidance inline when it prevents a material mistake, rather than making ordinary use depend on loading an entire manual.
Do not move duplicated manuals into skill references merely to shorten the entrypoint.

### Documentation entry points

When a workflow leaves a decision unresolved, consult the relevant installed command help first, then the matching local documentation only if help is insufficient.
Give agents concrete local entry points, explain when to consult them, and reuse already verified guidance until the runtime changes or an incompatibility appears.

Use documentation paths only when they resolve in the installed environment.
Do not rely on repository-relative paths to unbundled files or web links that require fetching documentation.
Use the local help and documentation provided by the installation.
Treat missing or incomplete advertised materials as an installation or documentation issue; do not add fallback instructions to the skill.

### Preserve decision guidance

Retain distinctions that affect the requested outcome, such as preparation versus installation, source versus installed copy, live-link update effects, settings stages versus actual files, repository-wide publication, and preservation during recovery.
The skill must not impose content-authoring policies or infer publication authorization from an editing request.

When changing user-facing commands, options, configuration, or workflows, review the skill's guidance and documentation entry points in the same change.
Update the skill when its decision guidance or discovery route changes.
A new option or documentation detail alone does not require copying it into the skill.
Verify that referenced documentation is available and retained guidance agrees with the actual command behavior.
