"""Preserve unrelated agent hooks while owning explicit groups per event."""

import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

from .model import Error
from .storage import exists


TRUST_NOTICE = ("Codex hook trust must be reviewed separately: in the next Codex session, "
                "open /hooks, review and trust the AEM hook, then start a new session. "
                "AEM does not grant trust or enable disabled hooks.")


def marker(config_path, identity, purpose):
    digest = hashlib.sha256(f"{config_path}\0{identity}".encode()).hexdigest()[:20]
    return f"AEM {purpose} [{digest}]"


HOOK_ID_ARGUMENT = "--aem-hook-id"
_MARKER = re.compile(r"AEM [^\[\]']+ \[[0-9a-f]{20}\]")


def generated(command):
    """Whether a hook command has the shape AEM writes: a hook-id argument or a quoted marker."""
    return isinstance(command, str) and (HOOK_ID_ARGUMENT in command or _MARKER.search(command) is not None)


def without_marker(command):
    """The command with its generated identity marker removed, so the same hook compares equal across agents."""
    return _MARKER.sub("AEM", command)


def interpreter():
    """The interpreter path written into hook commands.

    A virtual environment exposes the same interpreter as `python`, `python3`,
    and versioned names, and uv launchers switch between them on reinstall.
    Prefer the environment's `python` so reinstalling does not rewrite hooks.
    """
    if sys.prefix != sys.base_prefix:
        canonical = Path(sys.prefix) / "bin" / "python"
        if Path(sys.executable).parent == canonical.parent and canonical.exists():
            return str(canonical)
    return sys.executable


def command(config_path, arguments):
    return shlex.join([interpreter(), "-m", "agent_env_man", "--config", str(config_path), *arguments])


def read(path: Path) -> dict:
    """Reject invalid/redirected hook files rather than losing unrelated configuration."""
    if not exists(path):
        return {}
    if path.is_symlink() or not path.is_file():
        raise Error(f"Hook configuration must be a regular JSON file: {path}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Error(f"Duplicate JSON key in hook configuration: {key}")
            result[key] = value
        return result

    try:
        doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot read hook configuration {path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
        raise Error("Hook configuration and hooks must be JSON objects")
    for event, groups in doc.get("hooks", {}).items():
        if (not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get("hooks"), list)
                or any(not isinstance(h, dict) for h in g["hooks"]) for g in groups)):
            raise Error(f"{event} must be an array of hook groups")
    return doc


def serialize(path, doc):
    """Edit event arrays while retaining original tokens of unchanged groups."""
    from .settings_formats import FORMATS
    adapter = FORMATS['json']
    document = adapter.parse(path.read_text(encoding='utf-8')) if exists(path) else adapter.empty_document()
    original = document.root.children.get('hooks')
    if original is None:
        adapter.put(document, ('hooks',), adapter.parse('{}').root)
    for event, groups in doc['hooks'].items():
        previous = original.children.get(event) if original else None
        # read() supplies ordinary decoded values for ownership checks. Use
        # that same decoding only to find retained groups, never to emit their
        # numbers: float conversion can round, underflow, or overflow them.
        retained = [(json.loads(node.raw), node.raw) for node in previous.children] if previous else []
        raw_groups = []
        for group in groups:
            raw = next((raw for value, raw in retained if value == group), None)
            raw_groups.append(raw if raw is not None else json.dumps(group))
        value = adapter.parse('{"groups":[' + ', '.join(raw_groups) + ']}').root.children['groups']
        adapter.put(document, ('hooks', event), value)
    return adapter.dump(document).encode('utf-8')


def matching(doc: dict, marker: str, *, marker_field="statusMessage", event="SessionStart") -> list[int]:
    def owns(handler):
        value = handler.get(marker_field)
        if marker_field != "command":
            return value == marker
        return isinstance(value, str) and marker in value
    return [i for i, group in enumerate(doc.get("hooks", {}).get(event, []))
            if any(owns(h) for h in group["hooks"])]


def saved_matching(doc, marker, group):
    """Use the saved group's supported identity field, even for retired profiles."""
    handlers = group.get("hooks", [])
    if not isinstance(handlers, list) or not handlers or any(not isinstance(h, dict) for h in handlers):
        raise Error("Saved hook group must contain hook handlers")
    if any(h.get("statusMessage") == marker for h in handlers):
        return matching(doc, marker)
    if matching({"hooks": {"SessionStart": [group]}}, marker, marker_field="command"):
        return matching(doc, marker, marker_field="command")
    raise Error("Saved hook group has no usable identity marker")


def event_groups(group, additional_groups=None):
    """Legacy records own only SessionStart; new records add event ownership."""
    additional = {} if additional_groups is None else additional_groups
    if (not isinstance(additional, dict) or 'SessionStart' in additional
            or any(not isinstance(event, str) or not isinstance(value, dict)
                   or not isinstance(value.get('hooks'), list) for event, value in additional.items())):
        raise Error('Invalid additional AEM hook groups')
    return {'SessionStart': group, **additional}


def current(path: Path, marker: str, group: dict, *, marker_field="statusMessage", additional_groups=None) -> bool:
    doc = read(path)
    for event, desired in event_groups(group, additional_groups).items():
        indices = matching(doc, marker, marker_field=marker_field, event=event)
        if len(indices) != 1 or doc['hooks'][event][indices[0]] != desired:
            return False
    return True


def render(path: Path, marker: str, desired: dict, old: dict | None, *, adopt=False, replace=False,
           marker_field="statusMessage", additional_groups=None) -> bytes:
    """Merge owned event groups in one image, preserving unrelated configuration."""
    doc = read(path)
    wanted = event_groups(desired, additional_groups)
    previous = event_groups(old['hook_group'], old.get('additional_hook_groups')) if old else {}
    if previous.keys() - wanted.keys():
        raise Error('Saved AEM hook events are no longer supported; preserve and reconcile their ownership')
    for event, desired_group in wanted.items():
        groups = doc.setdefault('hooks', {}).setdefault(event, [])
        indices = matching(doc, marker, marker_field=marker_field, event=event)
        if len(indices) > 1:
            raise Error("Duplicate AEM hook markers; reconcile hook configuration before applying")
        if indices:
            index = indices[0]
            actual = groups[index]
            safe = (event in previous and actual in (previous[event], desired_group)) or (adopt and actual == desired_group)
            if not safe and not replace:
                raise Error("Existing or locally modified AEM hook; select its entry with --adopt or --replace")
            groups[index] = desired_group
        else:
            # An event absent from a legacy record is an addition, not a deleted
            # owned hook. Upgrade it without requiring --replace.
            if event in previous and exists(path) and not replace:
                raise Error("Managed AEM hook was removed; select its entry with --replace to restore it")
            groups.append(desired_group)
    # Preserve formatting and bytes as well when no semantic update is needed.
    if exists(path) and read(path) == doc:
        return path.read_bytes()
    return serialize(path, doc)


def remove(path, record, *, marker_field="statusMessage"):
    """Release just the recorded groups; local edits require reconciliation."""
    doc = read(path)
    for event, group in event_groups(record['hook_group'], record.get('additional_hook_groups')).items():
        indices = matching(doc, record['hook_marker'], marker_field=marker_field, event=event)
        if len(indices) != 1 or doc['hooks'][event][indices[0]] != group:
            raise Error("Managed hook changed or disappeared; reconcile before removal")
        del doc['hooks'][event][indices[0]]
    return serialize(path, doc)
