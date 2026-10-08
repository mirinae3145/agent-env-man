"""Staged settings, semantic changes, and recoverable grouped file writes.

Editable documents are separate from trusted comparison bases. Transport never
activates these settings: application is a separate phase of explicit or automatic sync.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import uuid

import tomlkit

from .model import Error, Item, identifier, overlaps, relative
from .settings_formats import FORMATS, SettingsFormat
from .storage import atomic_write, exists, is_reparse, observation, saved_path


def regular(path, *, missing=False):
    """Reject redirected ancestry and nonregular settings payloads."""
    saved_path(str(path))
    if not exists(path):
        if missing:
            return
        raise Error(f"Missing settings file: {path}")
    if path.is_symlink() or is_reparse(path) or not path.is_file():
        raise Error(f"Settings require a regular file: {path}")


def shares_hook_file(setting, hook):
    """Profiles explicitly opt into shared settings/hook-file ownership."""
    from .agents import profile
    return (setting.get("kind") == "setting" and setting.get("mode") == "settings"
            and setting.get("format") == "json" and hook.get("mode") == "agent-hook"
            and profile(hook.get("agent", "codex")).shared_settings_format == setting.get("format")
            and setting.get("target") == hook.get("target"))


def protect_hook_fields(bundle):
    if any(path[0] == "hooks" for path in bundle.operations()):
        raise Error("Agent hooks are owned by agent integration; JSON settings must not manage hooks")


def parse_path(value):
    try:
        parts = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise Error('Field path must be a JSON string array, such as ["section","key"]') from exc
    if not isinstance(parts, list) or not parts or any(not isinstance(p, str) for p in parts):
        raise Error("Field path must be a nonempty array of strings")
    return tuple(parts)


def prefix(a, b):
    return len(a) <= len(b) and b[:len(a)] == a


@dataclass
class Bundle:
    """Native settings document plus transportable deletion/release intent."""

    document: object
    deleted: set
    released: set
    adapter: SettingsFormat = FORMATS["toml"]

    @classmethod
    def empty(cls, *, format):
        if not isinstance(format, str) or format not in FORMATS:
            raise Error(f"Unsupported settings format: {format}")
        adapter = FORMATS[format]
        return cls(adapter.empty_document(), set(), set(), adapter)

    @classmethod
    def load(cls, path, metadata=None, *, missing=False, format="toml"):
        regular(path, missing=missing)
        observations = {str(path): observation(path)}
        present = exists(path)
        empty = cls.empty(format=format) if not present else None
        text = path.read_bytes().decode("utf-8") if present else empty.adapter.dump(empty.document)
        meta = ""
        if metadata is not None:
            regular(metadata, missing=True)
            observations[str(metadata)] = observation(metadata)
            meta = metadata.read_bytes().decode("utf-8") if exists(metadata) else ""
        bundle = cls.from_snapshot({"config": text, "management": meta}, format=format)
        if not present:
            bundle.document = empty.document
        for location, before in observations.items():
            if observation(Path(location)) != before:
                raise Error(f"Settings changed while reading: {location}")
        bundle.observations = observations
        return bundle

    @classmethod
    def from_snapshot(cls, snapshot, *, format="toml"):
        if not isinstance(snapshot, dict) or set(snapshot) != {"config", "management"}:
            raise Error("Invalid saved settings comparison base")
        if not isinstance(format, str) or format not in FORMATS:
            raise Error(f"Unsupported settings format: {format}")
        adapter = FORMATS[format]
        document = adapter.parse(snapshot["config"])
        meta = tomlkit.parse(snapshot["management"])
        if meta and (set(meta) - {"version", "deleted", "released"} or type(meta.get("version")) is not tomlkit.items.Integer or meta["version"] != 1):
            raise Error("Settings metadata requires version = 1 and only deleted/released")
        lists = {}
        for key in ("deleted", "released"):
            paths = meta.get(key, [])
            if not isinstance(paths, list):
                raise Error(f"Settings metadata {key} must be an array")
            parsed = []
            for path in paths:
                if not isinstance(path, list) or not path or any(not isinstance(p, str) for p in path):
                    raise Error("Metadata paths must be nonempty string arrays")
                parsed.append(tuple(path))
            if len(set(parsed)) != len(parsed):
                raise Error("Duplicate metadata field path")
            lists[key] = set(parsed)
        bundle = cls(document, lists["deleted"], lists["released"], adapter)
        bundle.validate()
        return bundle

    def validate(self):
        paths = list(self.adapter.fields(self.document)) + list(self.deleted) + list(self.released)
        for index, path in enumerate(paths):
            if any(prefix(path, other) or prefix(other, path) for other in paths[:index]):
                raise Error(f"Overlapping value/deletion/release paths: {json.dumps(list(path))}")

    def snapshot(self):
        meta = tomlkit.document()
        meta["version"] = 1
        for key, paths in (("deleted", self.deleted), ("released", self.released)):
            meta[key] = [list(p) for p in sorted(paths)]
        return {"config": self.adapter.dump(self.document), "management": tomlkit.dumps(meta)}

    def operations(self):
        return {**{p: ("value", v) for p, v in self.adapter.fields(self.document).items()},
                **{p: ("deleted", None) for p in self.deleted},
                **{p: ("released", None) for p in self.released}}

    def set_operation(self, path, operation):
        self.adapter.put(self.document, path, delete=True)
        self.deleted.discard(path)
        self.released.discard(path)
        if operation is None:
            return
        kind, value = operation
        if kind == "value":
            self.adapter.put(self.document, path, value)
        elif kind == "deleted":
            self.deleted.add(path)
        elif kind == "released":
            self.released.add(path)


def same(a, b, adapter):
    if a is None or b is None:
        return a is b
    return a[0] == b[0] and (a[0] != "value" or adapter.identity(a[1]) == adapter.identity(b[1]))


def changed(base, new):
    before, after = base.operations(), new.operations()
    return {p for p in before.keys() | after.keys() if not same(before.get(p), after.get(p), new.adapter)}


def normalize(bundle, previous):
    """Removing a previously managed leaf means deletion, never release."""
    present = bundle.operations()
    for path, op in previous.operations().items():
        if op[0] == "value" and path not in present:
            if not any(prefix(path, p) or prefix(p, path) for p in present):
                bundle.deleted.add(path)
    bundle.validate()
    return bundle


def merge(base, local, incoming):
    """Three-way merge operations, treating structural overlap as conflict."""
    result = deepcopy(local)
    local_changes, incoming_changes = changed(base, local), changed(base, incoming)
    left, right = local.operations(), incoming.operations()
    conflicts = set()
    for path in incoming_changes:
        for other in local_changes:
            if (prefix(path, other) or prefix(other, path)) and not (path == other and same(left.get(path), right.get(path), incoming.adapter)):
                conflicts.update((path, other))
    # Removing children before creating their parent permits table -> scalar.
    for path in sorted(incoming_changes, key=lambda p: (-len(p), p)):
        if not any(prefix(path, p) or prefix(p, path) for p in conflicts):
            result.set_operation(path, None)
    for path in sorted(incoming_changes, key=lambda p: (len(p), p)):
        if not any(prefix(path, p) or prefix(p, path) for p in conflicts):
            result.set_operation(path, right.get(path))
    result.validate()
    return result, sorted(conflicts)


def declaration(config, source, data):
    stage_root = config.path.parent / (config.path.name + ".stages")
    if stage_root.resolve() != stage_root:
        raise Error("Settings stage root redirects")
    target = Path(config.doc["settings"][source.name]["target"]).expanduser()
    saved_path(str(target))
    protected = [s.path for s in config.sources.values()] + [config.path, config.state_dir, config.checkout_root, stage_root]
    if config.catalog_path:
        protected.append(config.catalog_source.path if config.catalog_source else config.catalog_path)
    if config.catalog_copy_source is not None:
        protected.extend([config.catalog_path.parent, config.catalog_copy_source])
    if any(overlaps(target, p) for p in protected):
        raise Error(f"Setting target overlaps sources or manager storage: {target}")
    if any(overlaps(stage_root, p) for p in protected if p != stage_root):
        raise Error("Settings stage storage overlaps sources or manager storage")
    path = relative(data["path"])
    return Item(source.name, "settings", data["path"], source.path / path, target, "settings", "setting", agent="", agents=())


def metadata_path(path):
    return path.with_name(path.name + ".aem.toml")


def transaction(state, writes, records, *, dry_run=False, state_updates=None, guards=(), operation="settings-group"):
    """Commit multiple files and records with one rollback journal.

    Backups stay next to their files for same-filesystem renames. The durable
    state update commits the group; until then recovery restores every member.
    All observations are validated before any rollback, preserving later edits.
    Catalog delivery also commits its baseline and guards unchanged inputs;
    these optional additions leave existing settings ownership unchanged.
    """
    state.ready()
    if operation not in ("settings-group", "catalog-copy"):
        raise Error("Unsupported grouped file operation")
    guards = list(guards)
    def check_guards():
        for path, before in guards:
            regular(path, missing=True)
            if observation(path) != before:
                raise Error(f"Input changed during transaction: {path}")
    check_guards()
    paths = [path for path, _, _ in writes]
    if len(set(paths)) != len(paths):
        raise Error("Duplicate grouped settings write")
    for path, content, before in writes:
        regular(path, missing=True)
        if observation(path) != before:
            raise Error(f"Settings file changed after reading: {path}")
    if dry_run:
        return
    entries = []
    token = uuid.uuid4().hex
    try:
        for path, content, before in writes:
            if exists(path) and path.read_bytes() == content:
                guards.append((path, before))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            regular(path, missing=True)
            stage = path.with_name(".aem-stage-" + token + "-" + str(len(entries)))
            backup = path.with_name(path.name + ".aem-backup-" + token)
            mode = stat.S_IMODE(path.stat().st_mode) if exists(path) else 0o600
            atomic_write(stage, content, mode=mode)
            entries.append({"target": str(path), "stage": str(stage), "backup": str(backup),
                            "before": before, "after": observation(stage)})
        check_guards()
        state.data["pending"] = {"operation": operation, "files": entries}
        state.save()
        for entry in entries:
            path = Path(entry["target"])
            if observation(path) != entry["before"]:
                raise Error(f"Settings file changed before commit: {path}")
            if exists(path):
                os.replace(path, entry["backup"])
            os.replace(entry["stage"], path)
        for entry in entries:
            if observation(Path(entry["target"])) != entry["after"]:
                raise Error("Settings file changed before state commit")
        check_guards()
        old_data = deepcopy(state.data)
        state.data["items"].update(records)
        state.data.update(state_updates or {})
        state.data["pending"] = None
        try:
            state.save()
        except Exception:
            state.data = old_data
            raise
    except Exception:
        if state.path.exists():
            durable = json.loads(state.path.read_text(encoding="utf-8"))
            state.data = durable
        if state.data.get("pending") and state.data["pending"].get("operation") == operation:
            recover_group(state)
        else:
            for entry in entries:
                Path(entry["stage"]).unlink(missing_ok=True)
        raise


def recover_group(state):
    pending = state.data["pending"]
    if not isinstance(pending.get("files"), list):
        raise Error("Invalid grouped settings recovery journal")
    entries = pending["files"]
    seen = set()
    # Validate the complete group before restoring any member.
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"target", "stage", "backup", "before", "after"}:
            raise Error("Incomplete grouped settings recovery journal")
        target, stage, backup = [saved_path(entry[k]) for k in ("target", "stage", "backup")]
        if len({target, stage, backup}) != 3 or stage.parent != target.parent or backup.parent != target.parent:
            raise Error("Settings recovery paths must be distinct siblings")
        if not stage.name.startswith(".aem-stage-") or not backup.name.startswith(target.name + ".aem-backup-"):
            raise Error("Invalid settings recovery artifact paths")
        if {target, stage, backup} & seen:
            raise Error("Overlapping settings recovery paths")
        seen.update((target, stage, backup))
        for key in ("before", "after"):
            obs = entry[key]
            if not isinstance(obs, dict) or obs.get("kind") not in ("file", "missing") or (obs["kind"] == "file" and not isinstance(obs.get("hash"), str)):
                raise Error("Invalid settings recovery observation")
        regular(target, missing=True)
        regular(stage, missing=True)
        regular(backup, missing=True)
        current = observation(target)
        if exists(backup):
            safe = observation(backup) == entry["before"] and current in (entry["after"], {"kind": "missing"})
        else:
            safe = current == entry["before"] or (entry["before"] == {"kind": "missing"} and current == entry["after"])
        if not safe or (exists(stage) and observation(stage) != entry["after"]):
            raise Error("Recovery stopped: settings changed; preserve files and backups")
    for entry in reversed(entries):
        target, stage, backup = [Path(entry[k]) for k in ("target", "stage", "backup")]
        if exists(backup):
            os.replace(backup, target)
        elif entry["before"] == {"kind": "missing"}:
            target.unlink(missing_ok=True)
        stage.unlink(missing_ok=True)
    state.data["pending"] = None
    state.save()


class Settings:
    """Settings operations under the caller's configuration lock."""

    def __init__(self, manager):
        self.manager = manager
        self.config, self.state = manager.config, manager.state

    def item(self, name):
        identifier(name)
        sources = self.config.sources
        if name not in self.config._settings:
            raise Error(f"Unknown setting: {name}")
        item = self.config.declarations(sources[name])[0]
        self.manager.check_destinations([item])
        return item

    def record(self, name, *, required=True):
        record = self.state.data["items"].get(f"{name}:settings")
        if required and (not record or record.get("kind") != "setting"):
            raise Error(f"{name}: settings stage is not prepared; run bootstrap")
        if record:
            if (record.get("kind") != "setting" or record.get("mode") != "settings"
                    or record.get("source_name") != name or not isinstance(record.get("format"), str)
                    or record["format"] not in FORMATS
                    or not all(key in record for key in ("stage_root", "working", "shared", "applied", "conflicts"))
                    or not isinstance(record["conflicts"], list)):
                raise Error(f"{name}: invalid saved settings record")
            for path in record["conflicts"]:
                if not isinstance(path, list) or not path or any(not isinstance(p, str) for p in path):
                    raise Error(f"{name}: invalid saved conflict path")
        return deepcopy(record)

    def stage_paths(self, record):
        root = saved_path(record["stage_root"])
        if root.resolve() != root:
            raise Error("Settings stage directory redirects")
        return root / ("config." + record["format"]), root / "management.toml"

    def source(self, item):
        root = self.config.sources[item.source_name].path
        cursor = item.source
        while cursor != root:
            if exists(cursor) and (cursor.is_symlink() or is_reparse(cursor)):
                raise Error("Settings source path redirects")
            cursor = cursor.parent
        format = self.config._settings[item.source_name]["format"]
        bundle = Bundle.load(item.source, metadata_path(item.source), format=format)
        self.protect_hooks({"kind": "setting", "mode": "settings", "target": str(item.target), "format": format}, bundle)
        return bundle

    def check_hook_ownership(self, record, *, saved=False):
        # Removal consumes saved ownership, independently of current profiles
        # and editable stages. Installation must also inspect current intent.
        working = (Bundle.from_snapshot(record["working"], format="json") if saved
                   else self.working(record, conflicts=True))
        protect_hook_fields(working)
        if record.get("applied"):
            protect_hook_fields(Bundle.from_snapshot(record["applied"], format="json"))

    def protect_hooks(self, record, bundle):
        target = record["target"]
        from .agents import profile
        configured = any(profile(name).shared_settings_format == record.get("format")
                         and str(Path(binding["root"]) / profile(name).hook_name) == target
                         for name, binding in getattr(self.config, "agents", {}).items())
        shared = any(not old.get("detached") and shares_hook_file(record, old)
                     for old in self.state.data["items"].values())
        if record.get("format") == "json" and (configured or shared):
            protect_hook_fields(bundle)
            if record.get("applied"):
                protect_hook_fields(Bundle.from_snapshot(record["applied"], format="json"))

    def working(self, record, *, conflicts=False):
        if record.get("conflicts") and not conflicts:
            raise Error("Unresolved settings conflicts; use settings resolve")
        config, meta = self.stage_paths(record)
        current = Bundle.load(config, meta, format=record["format"])
        bundle = normalize(current, Bundle.from_snapshot(record["working"], format=record["format"]))
        self.protect_hooks(record, bundle)
        return bundle

    def save_stage(self, record, bundle, *, dry_run=False):
        self.protect_hooks(record, bundle)
        config, meta = self.stage_paths(record)
        snapshot = bundle.snapshot()
        record["working"] = snapshot
        guards = getattr(bundle, "observations", {})
        writes = [(config, snapshot["config"].encode(), guards.get(str(config), observation(config))),
                  (meta, snapshot["management"].encode(), guards.get(str(meta), observation(meta)))]
        transaction(self.state, writes, {f'{record["source_name"]}:settings': record}, dry_run=dry_run)

    def prepare(self, item, *, dry_run=False):
        source_binding = self.config.sources[item.source_name]
        if source_binding.git:
            from .git_source import Git
            git = Git()
            prepared = self.manager.delivery_source(source_binding)
            git.clean(prepared)
            git.tracked_payload(prepared, item.relative)
            if exists(metadata_path(item.source)):
                git.tracked_payload(prepared, item.relative + ".aem.toml")
        existing = self.record(item.source_name, required=False)
        if existing:
            self.working(existing, conflicts=True)
            return {"setting": item.source_name, "status": "already-prepared"}
        source = self.source(item)
        root = self.config.path.parent / (self.config.path.name + ".stages") / item.source_name
        if exists(root) and (root.is_symlink() or is_reparse(root) or not root.is_dir() or any(root.iterdir())):
            raise Error(f"Unmanaged settings stage exists: {root}")
        record = {"kind": "setting", "mode": item.mode, "id": "settings", "source_name": item.source_name,
                  "source": str(item.source), "relative": item.relative, "target": str(item.target),
                  "stage_root": str(root), "format": self.config._settings[item.source_name]["format"], "detached": False, "agent": "", "agents": [],
                  "applied": None, "shared": source.snapshot(), "published": source.snapshot(), "working": source.snapshot(), "conflicts": []}
        self.save_stage(record, source, dry_run=dry_run)
        return {"setting": item.source_name, "status": "planned" if dry_run else "prepared", "stage": str(root)}

    def receive(self, name, *, dry_run=False):
        item = self.item(name)
        record = self.record(name)
        if record.get("detached"):
            return {"setting": name, "status": "detached"}
        local = self.working(record)
        base = Bundle.from_snapshot(record["shared"], format=record["format"])
        incoming = normalize(self.source(item), base)
        result, paths = merge(base, local, incoming)
        if paths:
            record["conflicts"] = [list(p) for p in paths]
            record["conflict_base"] = base.snapshot()
            record["conflict_local"] = local.snapshot()
            record["conflict_shared"] = incoming.snapshot()
        record["shared"] = incoming.snapshot()
        record["published"] = incoming.snapshot()
        self.save_stage(record, result, dry_run=dry_run)
        return {"setting": name, "status": "conflict" if paths else "received", "conflicts": [list(p) for p in paths]}

    def resolve(self, name, path, take, *, dry_run=False):
        self.item(name)
        record = self.record(name)
        conflicts = [tuple(p) for p in record["conflicts"]]
        if path not in conflicts:
            raise Error("Field is not an unresolved conflict")
        working = self.working(record, conflicts=True)
        related = {path}
        while True:
            expanded = related | {p for p in conflicts if any(prefix(p, r) or prefix(r, p) for r in related)}
            if expanded == related:
                break
            related = expanded
        if take != "edited":
            chosen = Bundle.from_snapshot(record["conflict_" + ("local" if take == "local" else "shared")], format=record["format"])
            # Structural conflicts must be resolved as a connected group.
            roots = set(related)
            remove = [p for p in working.operations() if any(prefix(r, p) or prefix(p, r) for r in roots)]
            for p in sorted(remove, key=len, reverse=True):
                working.set_operation(p, None)
            for p, op in chosen.operations().items():
                if any(prefix(r, p) or prefix(p, r) for r in roots):
                    working.set_operation(p, op)
        working.validate()
        record["conflicts"] = [list(p) for p in conflicts if p not in related]
        if not record["conflicts"]:
            for key in ("conflict_base", "conflict_local", "conflict_shared"):
                record.pop(key, None)
        self.save_stage(record, working, dry_run=dry_run)
        return {"setting": name, "status": "resolved", "remaining": record["conflicts"]}

    def collect(self, name, paths=(), *, dry_run=False):
        item = self.item(name)
        record = self.record(name)
        if record.get("detached"):
            raise Error("Detached setting; reattach before collecting")
        local = self.working(record)
        base = Bundle.from_snapshot(record["applied"], format=record["format"]) if record["applied"] else deepcopy(local)
        actual = Bundle.load(item.target, format=record["format"])
        actual_fields = actual.adapter.fields(actual.document)
        incoming = deepcopy(base)
        managed = {p for p, op in base.operations().items() if op[0] != "released"}
        managed |= {p for p, op in local.operations().items() if op[0] != "released"}
        managed -= local.released
        for path in managed - {p for p in managed if any(prefix(p, q) or prefix(q, p) for q in paths)}:
            if path in actual_fields:
                incoming.set_operation(path, ("value", actual_fields[path]))
            else:
                incoming.set_operation(path, ("deleted", None))
        for path in paths:
            if path not in actual_fields:
                raise Error(f"Selected field does not exist: {json.dumps(list(path))}")
            for related in sorted(list(incoming.operations()), key=len, reverse=True):
                if prefix(path, related) or prefix(related, path):
                    incoming.set_operation(related, None)
            incoming.set_operation(path, ("value", actual_fields[path]))
        result, conflicts = merge(base, local, incoming)
        # Explicit selection intentionally reclaims deleted/released fields.
        for path in paths:
            result.set_operation(path, ("value", actual_fields[path]))
        conflicts = [p for p in conflicts if not any(prefix(p, q) or prefix(q, p) for q in paths)]
        if conflicts:
            raise Error(f"Collection conflicts: {json.dumps([list(p) for p in conflicts])}; reconcile and retry")
        self.save_stage(record, result, dry_run=dry_run)
        return {"setting": name, "status": "collected", "paths": [list(p) for p in sorted(changed(local, result))]}

    def release(self, name, path, *, dry_run=False):
        self.item(name)
        record = self.record(name)
        working = self.working(record)
        if path not in working.operations():
            raise Error("Only a declared field can be released")
        working.set_operation(path, ("released", None))
        self.save_stage(record, working, dry_run=dry_run)
        return {"setting": name, "status": "released", "path": list(path)}

    def apply_plan(self, item, *, replace=False, reattach=False):
        record = self.record(item.source_name)
        if record.get("detached") and not reattach:
            raise Error("Setting is detached; use --reattach")
        desired = self.working(record)
        actual = Bundle.load(item.target, missing=True, format=record["format"])
        base = Bundle.from_snapshot(record["applied"], format=record["format"]) if record.get("applied") and not record.get("detached") else Bundle.empty(format=record["format"])
        fields, prior = actual.operations(), base.operations()
        conflicts = []
        operations = desired.operations()
        for path, op in operations.items():
            if op[0] == "released":
                continue
            current = fields.get(path)
            expected = prior.get(path)
            # Missing is the concrete representation of a deletion in targets.
            expected = None if expected and expected[0] != "value" else expected
            wanted = None if op[0] == "deleted" else op
            if not same(current, expected, desired.adapter) and not same(current, wanted, desired.adapter):
                conflicts.append(path)
            for other in fields:
                if other != path and (prefix(path, other) or prefix(other, path)):
                    if other not in prior:
                        raise Error(f"Structural change would remove unmanaged field: {json.dumps(list(other))}")
        # A table/scalar transition also replaces its old owned ancestor or
        # descendants. Detect edits to those fields even when the new path is
        # absent, and never prune a current container with unmanaged siblings.
        for path, old_operation in prior.items():
            if path in fields and any(p != path and (prefix(p, path) or prefix(path, p)) for p in operations):
                if not same(fields[path], old_operation, desired.adapter):
                    conflicts.append(path)
        if conflicts and not replace:
            raise Error(f"Settings target conflicts: {json.dumps([list(p) for p in conflicts])}; use explicit --item and --replace")
        result = deepcopy(actual.document)
        # Remove old owned leaves involved in structural changes first.
        for path in sorted(prior, key=len, reverse=True):
            if path in fields and any(p != path and (prefix(p, path) or prefix(path, p)) for p in operations):
                desired.adapter.put(result, path, delete=True)
        for path, op in sorted(operations.items(), key=lambda entry: (-len(entry[0]), entry[0])):
            if op[0] == "deleted":
                desired.adapter.put(result, path, delete=True)
        for path, op in sorted(operations.items(), key=lambda entry: (len(entry[0]), entry[0])):
            if op[0] == "value" and not same(fields.get(path), op, desired.adapter):
                desired.adapter.put(result, path, op[1])
        text = desired.adapter.dump(result)
        if exists(item.target):
            raw = item.target.read_bytes()
            # Preserve an unchanged document verbatim, including mixed line
            # endings from existing content or TOML-generated blank lines.
            if text != actual.adapter.dump(actual.document) and b"\r\n" in raw:
                text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        record.update(detached=False, applied=desired.snapshot(), working=desired.snapshot(),
                      target=str(item.target), source=str(item.source), relative=item.relative)
        config, meta = self.stage_paths(record)
        snapshot = desired.snapshot()
        writes = [(item.target, text.encode(), actual.observations[str(item.target)]),
                  (config, snapshot["config"].encode(), desired.observations[str(config)]),
                  (meta, snapshot["management"].encode(), desired.observations[str(meta)])]
        return writes, record

    def export_plan(self, name):
        item = self.item(name)
        record = self.record(name)
        if record.get("detached"):
            raise Error("Detached setting; reattach before export")
        local = self.working(record)
        base = Bundle.from_snapshot(record["shared"], format=record["format"])
        incoming = normalize(self.source(item), base)
        result, conflicts = merge(base, local, incoming)
        if conflicts:
            raise Error("Shared source conflicts; run update and settings resolve before export")
        snapshot = result.snapshot()
        record.update(shared=snapshot, working=snapshot)
        if not self.config.sources[name].git:
            record["published"] = snapshot
        config, meta = self.stage_paths(record)
        writes = [(item.source, snapshot["config"].encode(), incoming.observations[str(item.source)]),
                  (metadata_path(item.source), snapshot["management"].encode(), incoming.observations[str(metadata_path(item.source))]),
                  (config, snapshot["config"].encode(), local.observations[str(config)]),
                  (meta, snapshot["management"].encode(), local.observations[str(meta)])]
        return writes, record, {"setting": name, "status": "exported",
                               "changed": any(before["kind"] != "file" or path.read_bytes() != content
                                              for path, content, before in writes[:2]), "paths": [list(p) for p in sorted(changed(incoming, result))]}

    def export(self, names, *, dry_run=False):
        self.state.ready()
        plans = [self.export_plan(name) for name in dict.fromkeys(names)]
        grouped = {}
        for plan in plans:
            for path, content, before in plan[0]:
                if path in grouped and grouped[path] != (content, before):
                    raise Error(f"Selected settings stages disagree about their shared source: {path}")
                grouped[path] = (content, before)
        writes = [(path, content, before) for path, (content, before) in grouped.items()]
        records = {f'{plan[1]["source_name"]}:settings': plan[1] for plan in plans}
        transaction(self.state, writes, records, dry_run=dry_run)
        return [{**plan[2], "status": "planned" if dry_run else "exported"} for plan in plans]

    def locate(self, name, *, source=False, target=False):
        self.state.ready()
        record = self.record(name, required=False)
        if source:
            item = self.item(name)
            self.source(item)
            src = self.config.sources[name]
            if src.git:
                self.manager.delivery_source(src)
                from .git_source import Git
                Git().validate(self.manager.delivery_source(src))
            path, meta, location = item.source, metadata_path(item.source), "source"
        else:
            if not record:
                raise Error(f"{name}: settings stage is not prepared; run bootstrap")
            if target:
                path, meta, location = saved_path(record["target"]), None, "target"
                regular(path, missing=True)
            else:
                path, meta = self.stage_paths(record)
                self.working(record, conflicts=True)
                location = "stage"
        return {"root": str(path.parent), "entry": str(path), "metadata": str(meta) if meta else None,
                "location": location, "prepared": record is not None,
                "detached": bool(record and record.get("detached"))}

    def status(self, record):
        if record.get("detached"):
            return {"status": "detached"}
        working = self.working(record, conflicts=True)
        report = {"status": "conflict" if record.get("conflicts") else "prepared" if not record["applied"] else "managed",
                  "conflicts": record.get("conflicts", []),
                  "unpublished": bool(changed(Bundle.from_snapshot(record.get("published", record["shared"]), format=record["format"]), working)),
                  "unexported": bool(changed(Bundle.from_snapshot(record["shared"], format=record["format"]), working))}
        if record["applied"]:
            report["unapplied"] = bool(changed(Bundle.from_snapshot(record["applied"], format=record["format"]), working))
            actual = Bundle.load(saved_path(record["target"]), missing=True, format=record["format"]).operations()
            report["modified_locally"] = any(not same(actual.get(p), op if op[0] == "value" else None, working.adapter)
                                             for p, op in Bundle.from_snapshot(record["applied"], format=record["format"]).operations().items()
                                             if op[0] != "released")
        return report
