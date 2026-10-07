"""Strict catalog v2 syntax, normalized to the delivery/installation model.

The private normalized representation keeps runtime policy JSON, checkout
identity and ownership contracts independent of the catalog's surface syntax.
It is never accepted as an input catalog or written back to the user's file.
"""

from .model import Config, Error, identifier
from .updates import TRIGGERS, policy_fields


TOP_LEVEL = {"version", "sources", "skills", "directories", "instructions", "settings", "hooks", "updates"}
SKILL_FIELDS = {"source", "subdir", "install", "update"}
INSTRUCTION_FIELDS = {"source", "subdir", "entry", "install"}


def table(value, allowed, location):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise Error(f"{location}: expected a table with only {', '.join(sorted(allowed))}")
    return value


def _policy_model(value):
    # Keep the existing effective JSON representation and runtime exclusion
    # checks, without exposing machine-policy shorthand in catalog syntax.
    result = dict(value)
    if "trigger" in result:
        result["trigger"] = list(result["trigger"]) or ["manual"]
    return result


def _validate_policy(value, location, *, allow_policy=False):
    if isinstance(value, dict) and "trigger" in value:
        trigger = value["trigger"]
        if (not isinstance(trigger, list)
                or any(not isinstance(event, str) or event not in TRIGGERS for event in trigger)
                or len(set(trigger)) != len(trigger)):
            raise Error(f"{location}: trigger must be an array of unique events; use [] to disable automatic updates")
    # Reuse numeric/action validation and retain the machine policy contract.
    policy_fields(_policy_model(value) if isinstance(value, dict) else value, location, allow_policy=allow_policy)


def validate(document):
    """Reject unsupported surface syntax before normalization or delivery."""
    version = document.get("version") if isinstance(document, dict) else None
    if isinstance(version, bool) or not isinstance(version, int) or version != 2:
        raise Error("Catalog requires version = 2. Manually migrate sources and install tables; "
                    "see docs/removed-interfaces.md. Detach direct-declaration or relocated installations "
                    "before reconfiguring; existing checkouts and saved state are preserved.")
    table(document, TOP_LEVEL, "Catalog")
    sources = document.get("sources", {})
    if not isinstance(sources, dict):
        raise Error("Catalog sources must be a TOML table")
    for name, data in sources.items():
        identifier(name)
        if not isinstance(data, dict) or data.get("type") not in ("git", "external"):
            raise Error(f"Source {name}: type must be git or external")
        if data["type"] == "git":
            table(data, {"type", "repository", "branch"}, f"Source {name}")
            Config._validate_repository(data, f"Source {name}")
        else:
            table(data, {"type"}, f"Source {name}")
    for kind in ("skills", "directories", "instructions"):
        entries = document.get(kind, {})
        if not isinstance(entries, dict):
            raise Error(f"Catalog {kind} must be a TOML table")
        for name, data in entries.items():
            identifier(name)
            table(data, INSTRUCTION_FIELDS if kind == "instructions" else SKILL_FIELDS | ({"preserve_symlinks"} if kind == "directories" else set()), f"{kind}.{name}")
            if kind == "directories":
                enabled = data.get("preserve_symlinks", False)
                if not isinstance(enabled, bool):
                    raise Error(f"{kind}.{name}.preserve_symlinks: expected Boolean")
                if enabled:
                    from .payload_links import require_posix
                    require_posix()
            source = data.get("source")
            if not isinstance(source, str) or source not in sources:
                raise Error(f"{kind}.{name}: source must name a declared source")
            install = data.get("install", {})
            if kind in ("skills", "directories"):
                if kind == "skills" and sources[source]["type"] != "git":
                    raise Error(f"Skill {name}: external sources are supported only for instructions")
                table(install, {"root", "mode", "destination"} if kind == "directories" else {"root", "mode"}, f"{kind}.{name}.install")
                if "update" in data:
                    _validate_policy(data["update"], f"{kind}.{name}.update", allow_policy=True)
            else:
                table(install, {"bundle", "entry"}, f"instructions.{name}.install")
                for part in ("bundle", "entry"):
                    table(install.get(part, {}), {"root", "destination"}, f"instructions.{name}.install.{part}")
    settings = document.get("settings", {})
    if not isinstance(settings, dict):
        raise Error("Catalog settings must be a table")
    for name, data in settings.items():
        identifier(name)
        table(data, {"source", "path", "format", "update"}, f"settings.{name}")
        if "update" in data:
            table(data["update"], {"trigger", "min_interval", "timeout"}, f"settings.{name}.update")
            _validate_policy(data["update"], f"settings.{name}.update")
        if not isinstance(data.get("source"), str) or data["source"] not in sources:
            raise Error(f"settings.{name}: source must name a declared source")
        from .model import relative
        relative(data.get("path"))
        from .settings_formats import FORMATS
        if not isinstance(data.get("format"), str) or data["format"] not in FORMATS:
            raise Error(f"settings.{name}: unsupported format; choose from {', '.join(FORMATS)}")
    declared_hooks = document.get('hooks', {})
    if not isinstance(declared_hooks, dict):
        raise Error('Catalog hooks must be a table')
    for name, data in declared_hooks.items():
        identifier(name)
        table(data, {'source', 'agents'}, f'hooks.{name}')
        if not isinstance(data.get('source'), str) or data['source'] not in sources:
            raise Error(f'hooks.{name}: source must name a declared source')
        if not isinstance(data.get('agents'), dict) or not data['agents']:
            raise Error(f'hooks.{name}: agents must be a nonempty table')
        from .agents import profile
        from .personal_hooks import validate_binding
        for agent, binding in data['agents'].items():
            validate_binding(binding, profile(agent))
    names = [set(document.get(kind, {})) for kind in ("skills", "directories", "instructions", "settings", "hooks")]
    collision = set().union(*(a & b for i, a in enumerate(names) for b in names[i + 1:]))
    if collision:
        raise Error(f"Instruction name collides with another source: {sorted(collision)[0]}")
    updates = table(document.get("updates", {}), {"defaults", "policies"}, "updates")
    _validate_policy(updates.get("defaults", {}), "updates.defaults")
    named = updates.get("policies", {})
    if not isinstance(named, dict):
        raise Error("updates.policies must be a table")
    for name, value in named.items():
        identifier(name)
        _validate_policy(value, f"updates.policies.{name}")


def normalize(document):
    """Validate v2 input and copy it into the private, existing runtime model.

    Device-dependent roots, paths, external bindings and effective policy
    composition are validated by Config after this syntax boundary.
    """
    validate(document)
    sources = document.get("sources", {})
    result = {"repositories": {name: dict(data) for name, data in sources.items() if data["type"] == "git"},
              "externals": {name: {} for name, data in sources.items() if data["type"] == "external"}}
    for kind in ("skills", "directories", "instructions"):
        result[kind] = {}
        for name, data in document.get(kind, {}).items():
            source = data["source"]
            field = "repo" if sources[source]["type"] == "git" else "external"
            entry = {field: source, **{k: data[k] for k in ("subdir", "entry") if k in data}}
            install = data.get("install", {})
            if kind in ("skills", "directories"):
                entry.update(install)
                if kind == "directories":
                    entry.setdefault("root", "home")
                    entry["preserve_symlinks"] = data.get("preserve_symlinks", False)
                if "update" in data:
                    entry["update"] = _policy_model(data["update"])
            else:
                entry.update(install.get("bundle", {}))
                entry.update({"entry_" + key: value for key, value in install.get("entry", {}).items()})
            result[kind][name] = entry
    result["settings"] = {}
    for name, data in document.get("settings", {}).items():
        field = "repo" if sources[data["source"]]["type"] == "git" else "external"
        result["settings"][name] = {field: data["source"], "path": data["path"], "format": data["format"]}
        if "update" in data:
            result["settings"][name]["update"] = _policy_model(data["update"])
    result['hooks'] = {}
    for name, data in document.get('hooks', {}).items():
        field = 'repo' if sources[data['source']]['type'] == 'git' else 'external'
        result['hooks'][name] = {field: data['source'], 'agents': data['agents']}
    updates = document.get("updates", {})
    result["updates"] = {"defaults": _policy_model(updates.get("defaults", {})),
                         "policies": {name: _policy_model(value) for name, value in updates.get("policies", {}).items()}}
    return result
