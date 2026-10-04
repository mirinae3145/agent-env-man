"""Preserve unrelated agent hooks while owning explicit SessionStart groups."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from .model import Error
from .storage import exists, is_reparse


TRUST_NOTICE = ("Codex hook trust must be reviewed separately: in the next Codex session, "
                "open /hooks, review and trust the AEM hook, then start a new session. "
                "AEM does not grant trust or enable disabled hooks.")


def marker(config_path, identity, purpose):
    digest = hashlib.sha256(f"{config_path}\0{identity}".encode()).hexdigest()[:20]
    return f"AEM {purpose} [{digest}]"


def command(config_path, arguments, *, preserve_exit=False):
    args = [sys.executable, "-m", "agent_env_man", "--config", str(config_path), *arguments]
    result = ("& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
              if os.name == "nt" else shlex.join(args))
    if os.name == "nt":
        if preserve_exit:
            result += "; exit $LASTEXITCODE"
        encoded = base64.b64encode(result.encode("utf-16le")).decode("ascii")
        return "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded
    return result


def read(path: Path) -> dict:
    """Reject invalid/redirected hook files rather than losing unrelated configuration."""
    if not exists(path):
        return {}
    if path.is_symlink() or is_reparse(path) or not path.is_file():
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


def matching(doc: dict, marker: str, *, marker_field="statusMessage") -> list[int]:
    def owns(handler):
        value = handler.get(marker_field)
        if marker_field != "command":
            return value == marker
        if not isinstance(value, str):
            return False
        prefix = "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
        if value.startswith(prefix):
            try:
                value = base64.b64decode(value[len(prefix):], validate=True).decode("utf-16le")
            except (ValueError, UnicodeError):
                return False
        return marker in value
    return [i for i, group in enumerate(doc.get("hooks", {}).get("SessionStart", []))
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


def current(path: Path, marker: str, group: dict, *, marker_field="statusMessage") -> bool:
    doc = read(path)
    indices = matching(doc, marker, marker_field=marker_field)
    return len(indices) == 1 and doc["hooks"]["SessionStart"][indices[0]] == group


def render(path: Path, marker: str, desired: dict, old: dict | None, *, adopt=False, replace=False,
           marker_field="statusMessage") -> bytes:
    """Merge only the saved group, preserving other events, groups and top-level fields."""
    doc = read(path)
    groups = doc.setdefault("hooks", {}).setdefault("SessionStart", [])
    indices = matching(doc, marker, marker_field=marker_field)
    if len(indices) > 1:
        raise Error("Duplicate AEM hook markers; reconcile hook configuration before applying")
    if indices:
        index = indices[0]
        actual = groups[index]
        safe = (old and actual in (old["hook_group"], desired)) or (adopt and actual == desired)
        if not safe and not replace:
            raise Error("Existing or locally modified AEM hook; select its entry with --adopt or --replace")
        groups[index] = desired
    else:
        if old and exists(path) and not replace:
            raise Error("Managed AEM hook was removed; select its entry with --replace to restore it")
        groups.append(desired)
    # Preserve formatting and bytes as well when no semantic update is needed.
    if exists(path) and read(path) == doc:
        return path.read_bytes()
    return serialize(path, doc)


def remove(path, record, *, marker_field="statusMessage"):
    """Release just the recorded group; local edits require manual reconciliation."""
    doc = read(path)
    indices = matching(doc, record["hook_marker"], marker_field=marker_field)
    if len(indices) != 1 or doc["hooks"]["SessionStart"][indices[0]] != record["hook_group"]:
        raise Error("Managed hook changed or disappeared; reconcile before removal")
    del doc["hooks"]["SessionStart"][indices[0]]
    return serialize(path, doc)
