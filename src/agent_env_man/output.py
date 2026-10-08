"""Concise command summaries and detailed text, independent of JSON contracts."""

from .reports import CONTENT_KINDS


def format_report(report):
    """Render reports as indented fields and lists, preserving multiline values."""
    lines = []

    def scalar(value):
        if value is None:
            return "none"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    def render(value, indent=0, label=None):
        prefix = " " * indent
        heading = "-" if label == "-" else f"{label}:" if label is not None else ""
        if isinstance(value, (dict, list)) and value:
            if heading:
                lines.append(prefix + heading)
                indent += 2
                prefix = " " * indent
            if isinstance(value, dict):
                for key, child in value.items():
                    render(child, indent, str(key).replace("_", " "))
            else:
                for child in value:
                    if isinstance(child, (dict, list)) and child:
                        start = len(lines)
                        render(child, indent + 2)
                        lines[start] = prefix + "- " + lines[start][indent + 2:]
                    else:
                        render(child, indent, "-")
        else:
            text = "none" if isinstance(value, (dict, list)) else scalar(value)
            parts = text.split("\n")
            separator = " " if heading else ""
            # Align continuation lines with the value, so errors/notices remain
            # readable without looking like additional report fields.
            lead = prefix + heading + separator
            lines.append(lead + parts[0])
            lines.extend(" " * len(lead) + part for part in parts[1:])

    render(report)
    return "\n".join(lines)


KIND_LABELS = {"instruction": "Instructions", "skill": "Skills", "directory": "Directories",
               "setting": "Settings", "personal-hook": "Hooks"}
STATUS_LABELS = {
    "matches-last-apply": "matches last installation",
    "equal-at-last-fetch": "up to date at last fetch",
    "externally-managed-unknown": "managed externally; remote state unknown",
    "already-prepared": "already prepared", "external-ready": "external content ready",
    "external-no-fetch": "external source checked; no fetch",
    "not-prepared": "not prepared", "changed-live": "linked content changed",
    "orphaned-or-source-unavailable": "not declared or source unavailable",
    "would-register": "would register", "not-managed-by-aem": "not managed by AEM",
}
SECONDS_FIELDS = {"min_interval", "timeout", "git_timeout", "startup_hook_timeout"}
DETAIL_FIELDS = {"revision", "observed_revision", "head", "last_fetch", "last_update",
                 "last_attempt", "repository", "config", "hook_group", "hook_groups",
                 "runtime_registered", "state_version"}
PATH_FIELDS = {"path", "target", "checkout", "stage", "root", "entry", "installed_root"}
IDENTITY_FIELDS = ("name", "item", "skill", "directory", "setting", "source", "agent")
ROW_STATES = ("status", "action", "installation", "availability", "checkout", "remote_relation", "hook")


def _word(value, key):
    if key == "checkout" and value not in ("clean", "dirty"):
        return value
    if key == "remote_relation" and value in ("ahead", "behind", "diverged"):
        return f"{value} at last fetch"
    if key in SECONDS_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g} seconds"
    if isinstance(value, str) and key in (*ROW_STATES, "mode", "note", "trust"):
        return STATUS_LABELS.get(value, value.replace("-", " "))
    return value


def _display(value):
    """Drop only duplicate compatibility views, retaining all real details."""
    if isinstance(value, list):
        return [_display(child) for child in value]
    if not isinstance(value, dict):
        return value
    return {key: _display(child) if isinstance(child, (dict, list)) else _word(child, key)
            for key, child in value.items()
            if key != "compatibility_note" and not (key == "skills" and "items" in value)}


def _attention(value):
    if isinstance(value, list):
        return any(_attention(child) for child in value)
    if not isinstance(value, dict):
        return False
    for key, child in value.items():
        if child and (key in {"error", "last_update_error", "configuration_error", "catalog_error",
                             "failed", "conflict", "conflicts", "pending", "remaining"}
                      or key in ("status", "installation", "availability", "checkout") and child in (
                          "failed", "conflict", "unavailable", "missing", "broken-link",
                          "modified", "dirty", "orphaned-or-source-unavailable")):
            return True
        if isinstance(child, (dict, list)) and _attention(child):
            return True
    return False


def human_report(report, *, command="", verbose=False, planned=False, failed=False):
    """Present results without implying success from an inspection's exit code."""
    title = (command or "Result").capitalize()
    if planned:
        title += " preview"
    if failed:
        title += " (failed)"
    if verbose:
        return title + "\n" + format_report(_display(report))

    rows = report if isinstance(report, list) else report.get("items") if isinstance(report, dict) else None
    if isinstance(rows, list):
        if rows:
            title += f": {len(rows)} result{'s' if len(rows) != 1 else ''}"
        else:
            empty = {"apply": "no items to install", "bootstrap": "no content to prepare",
                     "update": "no sources to update", "status": "no content items",
                     "detach": "no items to detach"}.get(command, "no results")
            title += ": " + empty
    lines = [title]

    def detail(value, indent, key=None):
        rendered = format_report(_display({key: value} if key else value))
        lines.extend(" " * indent + line for line in rendered.splitlines())

    def emit(value, indent=0, label=None):
        if value is None or value == [] or value == {}:
            return
        prefix = " " * indent
        if isinstance(value, list):
            if not value:
                return
            if all(isinstance(row, dict) for row in value):
                groups = {}
                for row in value:
                    groups.setdefault(row.get("kind"), []).append(row)
                typed = any(kind in CONTENT_KINDS for kind in groups)
                if label and not (label == "items" and typed):
                    lines.append(prefix + label.replace("_", " ").capitalize() + ":")
                    indent += 2
                for kind in (*CONTENT_KINDS, *(key for key in groups if key not in CONTENT_KINDS)):
                    if kind not in groups:
                        continue
                    row_indent = indent
                    if typed:
                        lines.append(" " * indent + KIND_LABELS.get(kind, "Other results") + ":")
                        row_indent += 2
                    for row in groups[kind]:
                        emit(row, row_indent)
            else:
                detail(value, indent, label)
            return
        if not isinstance(value, dict):
            detail(_word(value, label), indent, label)
            return

        identity_key = next((key for key in IDENTITY_FIELDS if isinstance(value.get(key), str)), None)
        is_row = identity_key is not None and any(key in value for key in ROW_STATES)
        if is_row:
            states = []
            for key in ROW_STATES:
                state = value.get(key)
                # A checkout path is not a state; it belongs in detailed output.
                if key == "checkout" and state not in ("clean", "dirty"):
                    continue
                if isinstance(state, str):
                    word = _word(state, key)
                    if word not in states:
                        states.append(word)
            name = value[identity_key]
            if value.get("kind") == "setting" and value.get("phase") in ("source", "stage"):
                name += f" ({value['phase']})"
            lines.append(prefix + name + ": " + "; ".join(states))
            indent += 2
        elif label:
            lines.append(prefix + label.replace("_", " ").capitalize() + ":")
            indent += 2
        needs_attention = _attention(value)
        location = "locate" in command.split()
        for key, child in value.items():
            if key == "compatibility_note" or key == "skills" and "items" in value:
                continue
            if child is None or child == [] or child == {}:
                continue
            if is_row and (key in (*IDENTITY_FIELDS, "kind", "phase", *ROW_STATES)
                           and not (key == "checkout" and child not in ("clean", "dirty"))):
                continue
            if key == "pending":
                lines.append(" " * indent + "Recovery required: run aem recover after reviewing the pending operation.")
                detail(child, indent + 2, "pending")
                continue
            if key in ("notice", "error", "last_update_error", "configuration_error", "catalog_error",
                       "conflicts", "remaining", "reason", "comparison", "comparisons", "next"):
                if key == "next" and command == "bootstrap" and failed:
                    child = "Resolve the reported failures, then retry aem bootstrap."
                detail(child, indent, key)
                continue
            if key in DETAIL_FIELDS and not location:
                # Historical failures must remain visible; routine metadata is
                # available with --verbose, including raw timestamps and hashes.
                if not isinstance(child, (dict, list)) or not _attention(child):
                    continue
            # Settings field paths are arrays identifying the operation's
            # subject, not routine filesystem locations.
            if (is_row and key in PATH_FIELDS and isinstance(child, str)
                    and not needs_attention and not location):
                continue
            if is_row and key in ("mode", "transport", "branch") and not needs_attention:
                continue
            if key in ("unpublished", "unexported") and child is False:
                continue
            if key == "policy" and is_row and not needs_attention:
                continue
            if key == "policy" and isinstance(child, dict):
                fields = []
                for field, setting in child.items():
                    if isinstance(setting, list) and all(isinstance(item, str) for item in setting):
                        setting = ", ".join(setting)
                    if not isinstance(setting, (dict, list)):
                        word = "yes" if setting is True else "no" if setting is False else _word(setting, field)
                        fields.append(f"{field.replace('_', ' ')}: {word}")
                    else:
                        detail(setting, indent, field)
                if fields:
                    lines.append(" " * indent + "Policy: " + "; ".join(fields))
                continue
            if key == "failed" and child is False:
                continue
            emit(child, indent, key)

    emit(report)
    if len(lines) == 1 and not isinstance(rows, list):
        lines[0] += ": no results"
    return "\n".join(lines)
