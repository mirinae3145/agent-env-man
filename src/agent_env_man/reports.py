"""Add presentation metadata without changing operation reports or saved state."""

from copy import deepcopy


CONTENT_KINDS = ("instruction", "skill", "directory", "setting", "personal-hook")


def content_kind(kind):
    return "instruction" if kind in ("instruction-hook", "instruction-entry") else kind


def identities(config, state=None):
    """Use already loaded declarations and ownership; never load a catalog here."""
    result = {}
    if state is not None:
        for key, record in state.data.get("items", {}).items():
            kind = content_kind(record.get("kind", "skill"))
            if kind in CONTENT_KINDS:
                result[key] = kind
    for attribute, kind in (("_catalog", "skill"), ("_instructions", "instruction"),
                            ("_directories", "directory"), ("_settings", "setting"),
                            ("_hooks", "personal-hook")):
        for name in getattr(config, attribute, None) or {}:
            result[name] = kind
    return result


def row_identity(row, kinds, *, preparation=False):
    for key in ("item", "skill", "directory", "setting"):
        name = row.get(key)
        if not isinstance(name, str):
            continue
        kind = kinds.get(name) or kinds.get(name.split(":", 1)[0].split("@", 1)[0])
        if kind is None and key in ("directory", "setting"):
            kind = key
        if kind:
            return name, kind
    # Preparation's source field names a consumer. Other source reports can
    # represent whole repositories, so do not infer their type from a name.
    if preparation and isinstance(row.get("source"), str):
        name = row["source"]
        if name in kinds:
            return name, kinds[name]
    return None


def preparation_reports(report, config):
    """Return canonical items and a compatible copy of the legacy skills list."""
    kinds = identities(config)
    legacy = deepcopy(report)
    items = []
    for row in legacy:
        identity = row_identity(row, kinds, preparation=True)
        if identity is None:
            # Every preparation consumer is declared. Fail explicitly if a new
            # result shape is introduced without a corresponding identity.
            raise ValueError("Preparation result has no declared content identity")
        name, kind = identity
        items.append({**{key: value for key, value in row.items()
                         if key not in ("skill", "directory", "setting", "source")},
                      "name": name, "kind": kind,
                      "phase": "stage" if "setting" in row else "source"})
        if kind != "skill":
            row["kind"] = kind
            row["compatibility_note"] = (
                f"{kind} content included for legacy compatibility. Use items instead.")
    return items, legacy


# Only walk report containers, never user settings, hook definitions, policy
# objects or recovery journals that might themselves contain keys like item.
REPORT_CONTAINERS = {"items", "updates", "update", "apply", "outcomes", "results",
                     "stages", "content", "prepare", "integrations", "official_skills",
                     "excluded", "catalog", "automation", "self_update", "startup",
                     "catalog_automation", "last_attempt", "skill_updates", "settings_updates", "collection"}


def describe_report(report, config, state):
    """Copy additive metadata onto known result rows at the CLI boundary."""
    result = deepcopy(report)
    kinds = identities(config, state)

    def visit(value, *, preparation=False):
        if isinstance(value, list):
            for child in value:
                visit(child, preparation=preparation)
        elif isinstance(value, dict):
            identity = row_identity(value, kinds, preparation=preparation)
            if identity and ("status" in value or "action" in value or "reason" in value):
                value.setdefault("kind", identity[1])
            for key, child in value.items():
                if key in REPORT_CONTAINERS:
                    visit(child, preparation=key == "prepare")

    visit(result)
    return result
