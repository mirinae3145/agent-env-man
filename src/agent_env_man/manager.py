"""Explicit ownership and per-target transactions; delivery lives elsewhere."""

from dataclasses import dataclass, replace, field
import os
from pathlib import Path
import shutil
import json
import stat
import tempfile
import uuid

from .agents import profile, suffix
from .git_source import Git, now
from .model import Config, MachineFile, Error, Item, identifier, overlaps, relative
from .storage import State, copy_payload, exists, fingerprint, is_reparse, observation, remove, saved_path, link_matches


@dataclass
class Plan:
    item: Item
    before: dict
    record: dict
    change: bool
    content: bytes | None = None
    materialize: Path | None = None
    records: dict = field(default_factory=dict)
    peers: list = field(default_factory=list)
    delete: bool = False


class Manager:
    def __init__(self, config: MachineFile, state: State):
        self.config, self.state = config, state

    def delivery_source(self, source):
        if source.git and source.branch is None:
            branch = self.state.data["sources"].get(source.name, {}).get("branch")
            if not branch:
                raise Error(f"{source.name}: run bootstrap to prepare the checkout and record its default branch")
            return replace(source, branch=branch)
        return source

    def prepare_skills(self, names=(), *, timeout=30, defer_payloads=False):
        """Clone listed repositories, validating consumers before publishing a checkout.

        Clone success does not install anything. Existing checkouts are checked
        in place and never reset or pulled by bootstrap.
        Full automation may defer directory, settings, and personal-hook
        payload validation in existing checkouts until validated delivery
        succeeds, so new declarations can refer to incoming paths.
        """
        self.state.ready()
        sources = self.config.sources
        if set(names) - sources.keys():
            raise Error("Unknown catalog source selection")
        self.check_destinations([i for s in sources.values() for i in self.config.declarations(s)])
        report, failed = [], False
        groups = {}
        for name, source in sources.items():
            groups.setdefault(source.path, []).append((name, source))
        for members in groups.values():
            selected = [(name, source) for name, source in members if not names or name in names]
            if not selected:
                continue
            name, source = members[0]
            temporary = None
            try:
                if not source.git:
                    for _, member in members:
                        for item in self.config.declarations(member):
                            self.payload(item)
                    report.extend({"source": n, "status": "external-ready", "path": str(source.path)} for n, _ in selected)
                    continue
                git = Git(timeout)
                created = not exists(source.path)
                source_state = self.state.data["sources"].setdefault(name, {})
                previous_branch = source_state.get("branch") if source_state.get("repository") == source.git else None
                branch = source.branch or previous_branch
                if created:
                    source.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = Path(tempfile.mkdtemp(prefix=".aem-clone-", dir=source.path.parent))
                    options = ("--branch", branch) if branch else ()
                    git.run(None, "clone", "--single-branch", *options, "--", source.git, str(temporary))
                local_path = temporary or source.path
                if branch is None:
                    branch = git.run(local_path, "symbolic-ref", "--quiet", "--short", "HEAD").stdout
                prepared = replace(source, path=local_path, branch=branch)
                git.clean(prepared)
                # A shared checkout is published only when every declared consumer is valid.
                for skill_name, skill_source in members:
                    item = self.config.declarations(skill_source)[0]
                    if item.kind == "skill":
                        git.skill_descriptor(prepared, item.relative)
                    elif item.kind == "directory":
                        if defer_payloads and not created:
                            continue
                        git.directory_descriptor(prepared, item.relative)
                    elif item.kind == "setting":
                        if defer_payloads and not created:
                            continue
                        from .settings import Bundle, metadata_path
                        git.tracked_payload(prepared, item.relative)
                        Bundle.load(local_path / item.relative, metadata_path(local_path / item.relative),
                                    format=self.config._settings[skill_name]["format"])
                        if metadata_path(local_path / item.relative).exists():
                            git.tracked_payload(prepared, item.relative + ".aem.toml")
                    elif item.kind == 'personal-hook':
                        if defer_payloads and not created:
                            continue
                        from .personal_hooks import source_script
                        for member_item in self.config.declarations(skill_source):
                            git.tracked_payload(prepared, member_item.relative)
                            source_script(local_path, member_item.relative)
                    else:
                        git.instruction_descriptor(prepared, item.relative, item.entry)
                    payload = local_path / item.relative
                    if item.kind == "skill" and not (payload / "SKILL.md").is_file():
                        raise Error(f"{skill_name}: skill path must contain SKILL.md")
                    cursor = payload
                    while cursor != local_path:
                        if cursor.is_symlink() or is_reparse(cursor):
                            raise Error(f"Skill source contains a symlink/junction: {cursor}")
                        cursor = cursor.parent
                    fingerprint(payload, exclude_git=item.relative == ".")
                revision = git.run(local_path, "rev-parse", "HEAD").stdout
                if temporary:
                    if exists(source.path):
                        raise Error("Checkout destination appeared while cloning; refusing replacement")
                    os.rename(temporary, source.path)
                    temporary = None
                for skill_name, _ in members:
                    member_state = self.state.data["sources"].setdefault(skill_name, {})
                    member_state.update(repository=source.git, branch=branch, revision=revision, error=None)
                    if created:
                        member_state.update(last_fetch=now(), observed_revision=revision)
                for skill_name, _ in selected:
                    report.append({"directory" if skill_name in self.config._directories else "skill": skill_name,
                                   "status": "cloned" if created else "already-prepared", "checkout": str(source.path)})
            except (Error, OSError, ValueError) as exc:
                failed = True
                for skill_name, _ in selected:
                    self.state.data["sources"].setdefault(skill_name, {})["error"] = str(exc)
                    report.append({"directory" if skill_name in self.config._directories else "skill": skill_name,
                                   "status": "failed", "error": str(exc)})
            finally:
                if temporary:
                    # Git can mark object files read-only on Windows; a failed
                    # staged clone must still be removable before returning.
                    def writable_retry(operation, path, error):
                        os.chmod(path, stat.S_IWRITE)
                        operation(path)

                    shutil.rmtree(temporary, onerror=writable_retry)
            for skill_name, _ in selected:
                self.state.data["sources"].setdefault(skill_name, {})["last_attempt"] = now()
            self.state.save()
        from .settings import Settings
        ready_names = {entry.get("skill", entry.get("source")) for entry in report
                       if entry.get("status") in ("cloned", "already-prepared", "external-ready")}
        for name, source in sources.items():
            if not defer_payloads and name in self.config._settings and name in ready_names and (not names or name in names):
                try:
                    report.append(Settings(self).prepare(self.config.declarations(source)[0]))
                except (Error, OSError, ValueError) as exc:
                    failed = True
                    report.append({"setting": name, "status": "failed", "error": str(exc)})
        return report, failed

    def items(self):
        self.config.catalog()
        result = []
        for source in self.config.sources.values():
            result.extend(self.config.declarations(source))
        return result

    @staticmethod
    def matches(item, requested):
        logical = item.source_name if item.kind in ("skill", "directory", "setting", 'personal-hook') else f"{item.source_name}:{item.id.split('@')[0]}"
        return item.key in requested or logical in requested

    def selected(self, requested=(), *, reattach=False, agent=None):
        all_items = self.items()
        # Entry installation includes its directory and hook; selecting a hook
        # likewise needs a usable entry. Flags still require explicit selection.
        requested = set(requested)
        expanded = {i.key for i in all_items if self.matches(i, requested)}
        logical = {i.source_name if i.kind in ("skill", "directory", "setting", 'personal-hook') else f"{i.source_name}:{i.id.split('@')[0]}" for i in all_items}
        requested = expanded | (requested - logical - {i.key for i in all_items})
        for item in all_items:
            if item.key in requested and item.kind in ("instruction-entry", "instruction-hook"):
                requested.update(f"{item.source_name}:{part}{suffix(item.agent)}" for part in ("bundle", "entry", "hook"))
        registered = {i.key for i in all_items}
        detached = {k for k, r in self.state.data["items"].items() if r.get("detached")}
        if requested - registered:
            raise Error("Unknown item selection: " + ", ".join(sorted(requested - registered)))
        if reattach and not requested:
            raise Error("--reattach requires explicit --item selections")
        items = [i for i in all_items if not requested or i.key in requested]
        items = [i for i in items if i.kind != 'personal-hook' or i.key in requested]
        items = [i for i in items if reattach or not self.state.data["items"].get(i.key, {}).get("detached")]
        self.check_destinations([i for i in all_items if i.key not in detached])
        if agent is not None:
            profile(agent)
            items = [i for i in items if (i.kind in ("setting", "directory") or agent in (i.agents or (i.agent,)))]
        self.check_destinations(items)
        return items

    def check_destinations(self, items):
        # Include inactive/orphaned ownership, not only the current catalog.
        owners = {k: Path(r["target"]) for k, r in self.state.data["items"].items() if not r.get("detached")}
        stage_roots = {Path(r["stage_root"]).parent for r in self.state.data["items"].values()
                       if r.get("kind") == "setting"}
        if getattr(self.config, "_settings", {}):
            stage_roots.add(self.config.path.parent / (self.config.path.name + ".stages"))
        if any(overlaps(target, root) for target in list(owners.values()) + [i.target for i in items]
               for root in stage_roots):
            raise Error("Managed targets must be separate from settings stages")
        skill_roots = {i.target.parent for i in items if i.kind == "skill"}
        skill_roots.update(Path(r["target"]).parent for r in self.state.data["items"].values()
                           if r.get("kind") == "skill")
        if any(overlaps(root, self.config.state_dir) for root in skill_roots):
            raise Error("Skill roots must be separate from manager state and backups")
        for item in items:
            old = self.state.data["items"].get(item.key)
            if old and not old.get("detached") and (old["target"] != str(item.target) or old["mode"] != item.mode
                                                    or old["source"] != str(item.source)):
                raise Error(f"{item.key}: path or mode changed; detach before reconfiguration")
            for key, target in owners.items():
                if key != item.key and overlaps(item.target, target):
                    other = next((i for i in items if i.key == key), None)
                    old_other = self.state.data["items"].get(key, {})
                    if (item.target == target and item.mode == "agent-hook"
                            and ((other and other.mode == "agent-hook" and other.agent == item.agent)
                                 or (old_other.get("mode") == "agent-hook"
                                     and old_other.get("agent", "codex") == item.agent))):
                        continue
                    from .settings import Settings, shares_hook_file
                    current = {"kind": item.kind, "mode": item.mode, "agent": item.agent,
                               "target": str(item.target),
                               "format": getattr(self.config, "_settings", {}).get(item.source_name, {}).get("format")}
                    peer = dict(old_other)
                    if other:
                        peer.update(kind=other.kind, mode=other.mode, agent=other.agent, target=str(other.target),
                                    format=getattr(self.config, "_settings", {}).get(other.source_name, {}).get("format"))
                    if shares_hook_file(current, peer) or shares_hook_file(peer, current):
                        saved = old if item.kind == "setting" else old_other
                        if saved and saved.get("kind") == "setting":
                            Settings(self).check_hook_ownership(saved)
                        continue
                    raise Error(f"Overlapping targets: {item.key} and {key}")
            owners[item.key] = item.target

    def payload(self, item):
        if item.kind == "setting":
            from .settings import Settings
            Settings(self).source(item)
        root = self.config.sources[item.source_name].path
        if item.kind == 'personal-hook':
            from .personal_hooks import source_script, definition
            source_script(root, item.relative)
            definition(self.config, item)
        # Intermediate source symlinks would bypass directory-tree validation.
        cursor = item.source
        while cursor != root:
            if cursor.is_symlink() or is_reparse(cursor):
                raise Error(f"Source path contains a symlink/junction: {cursor}")
            cursor = cursor.parent
        if item.kind == "skill" and (not item.source.is_dir() or not (item.source / "SKILL.md").is_file()):
            raise Error(f"{item.key}: skill path must be a directory containing SKILL.md")
        if item.kind == "directory" and not item.source.is_dir():
            raise Error(f"{item.key}: source must be a directory")
        if item.kind in ("instruction", "instruction-hook"):
            if not item.source.is_dir() or not (item.source / item.entry).is_file():
                raise Error(f"{item.key}: instruction bundle needs a regular entry document: {item.entry}")
        if item.kind == "instruction-entry" and not item.source.is_file():
            raise Error(f"{item.key}: instruction entry must be a regular file")
        return fingerprint(item.source, exclude_git=item.kind in ("skill", "directory", "instruction", "instruction-hook") and item.relative == ".")

    def locate(self, name, agent="codex", *, source=False, target=False):
        """Locate saved content by default, or current catalog source content explicitly.

        Saved locations take precedence even when broken: never silently redirect
        an installed-copy edit to the source. Only a missing record falls back to
        the catalog; instruction callbacks retain their saved-only lookup.
        """
        self.state.ready()
        identifier(name)
        from .settings import Settings
        if f"{name}:settings" in self.state.data["items"]:
            if source:
                self.config = Config(self.config.path)
            return Settings(self).locate(name, source=source, target=target)
        if not any(r.get("source_name") == name for r in self.state.data["items"].values()):
            current = Config(self.config.path)
            current.catalog()
            if name in current._settings:
                self.config = current
                return Settings(self).locate(name, source=source, target=target)
        hook_record = self.state.data['items'].get(f'{name}:hook{suffix(agent)}')
        if hook_record and hook_record.get('kind') == 'personal-hook' and not source:
            if target:
                raise Error('--target is supported only for settings')
            path = saved_path(hook_record.get('source'))
            if not path.is_file() or path.is_symlink() or is_reparse(path):
                raise Error('Saved hook source is missing or redirected; inspect status')
            return {'root': str(path.parent), 'entry': str(path), 'hook_file': hook_record['target'],
                    'hook_event': hook_record['hook_event'], 'detached': bool(hook_record.get('detached')),
                    'location': 'source'}
        if target:
            raise Error("--target is supported only for settings")
        profile(agent)
        if not source:
            record = self.state.data["items"].get(f"{name}:directory")
            if record is not None:
                target = saved_path(record.get("target"))
                linked = record.get("mode") == "link" and not record.get("detached")
                if linked:
                    if not link_matches(observation(target), record.get("source")):
                        raise Error(f"{name}: installed directory link was replaced; inspect status")
                elif record.get("mode") not in ("link", "copy"):
                    raise Error(f"{name}: unsupported saved directory mode")
                elif target.is_symlink() or is_reparse(target):
                    raise Error(f"{name}: saved directory copy was replaced by a link")
                root = target.resolve(strict=True)
                if not root.is_dir():
                    raise Error(f"{name}: saved directory is missing or is not a directory")
                return {"root": str(root), "entry": str(root), "installed_root": str(target),
                        "detached": bool(record.get("detached")), "location": "source" if linked else "copy"}
            record = self.state.data["items"].get(f"{name}:bundle{suffix(agent)}")
            if record is not None:
                return self.locate_instruction(name, agent)
            records = [r for r in self.state.data["items"].values()
                       if r.get("kind") == "skill" and r.get("source_name") == name
                       and agent in (r.get("agents") or [r.get("agent", "codex")])]
            if len(records) > 1:
                raise Error(f"{name}: ambiguous saved skill locations for {agent}")
            if records:
                record = records[0]
                target = saved_path(record.get("target"))
                linked = record.get("mode") == "link" and not record.get("detached")
                if linked:
                    if not link_matches(observation(target), record.get("source")):
                        raise Error(f"{name}: installed skill link was replaced; inspect status")
                elif record.get("mode") not in ("link", "copy"):
                    raise Error(f"{name}: unsupported saved skill mode")
                elif target.is_symlink() or is_reparse(target):
                    raise Error(f"{name}: saved skill copy was replaced by a link")
                root = target.resolve(strict=True)
                self.locate_entry(root, root / "SKILL.md")
                return {"root": str(root), "entry": str(root / "SKILL.md"),
                        "installed_root": str(target), "detached": bool(record.get("detached")),
                        "location": "source" if linked else "copy"}
        config = Config(self.config.path)
        sources = config.sources
        if name not in sources:
            raise Error(f"{name}: unknown catalog skill, directory, instruction bundle, setting or personal hook")
        selected = sources[name]
        items = [i for i in config.declarations(selected) if i.kind in ("skill", "directory", "instruction", 'personal-hook')
                 and (i.kind == "directory" or agent in (i.agents or (i.agent,)))]
        if not items:
            raise Error(f"{name}: no declaration for agent {agent}")
        item = items[0]
        if not selected.path.is_dir():
            raise Error(f"{name}: source is missing; run bootstrap or restore the external folder")
        if selected.git:
            Git().validate(self.delivery_source(selected))
        entry = item.source if item.kind in ('personal-hook', 'directory') else item.source / ("SKILL.md" if item.kind == "skill" else item.entry)
        if item.kind == "directory":
            cursor = entry
            while cursor != selected.path:
                if cursor.is_symlink() or is_reparse(cursor):
                    raise Error(f"Directory source redirects through a link: {cursor}")
                cursor = cursor.parent
            if not entry.is_dir():
                raise Error(f"{name}: directory source is missing")
        else:
            self.locate_entry(selected.path, entry)
        return {"root": str(item.source.parent if item.kind == 'personal-hook' else item.source), "entry": str(entry), "installed_root": None,
                "detached": False, "location": "source", "repository": selected.git,
                "checkout": str(selected.path) if selected.git else None,
                "members": sorted(n for n, s in sources.items() if s.path == selected.path)}

    @staticmethod
    def locate_entry(root, entry):
        """Validate the entry and its ancestry without reading or hashing content."""
        if not root.is_dir():
            raise Error(f"Source directory is missing: {root}")
        cursor = entry
        while True:
            if cursor.is_symlink() or (cursor.exists() and is_reparse(cursor)):
                raise Error(f"Source entry contains a symlink/junction: {cursor}")
            if cursor == root:
                break
            cursor = cursor.parent
        if not entry.is_file():
            raise Error(f"Source entry is missing: {entry}")

    def locate_instruction(self, name, agent="codex"):
        """Resolve a saved installation without loading its catalog or fetching sources.

        Detached bundles resolve to their preserved directory; active bundles
        must still have the recorded link so an unrelated replacement is not read.
        """
        self.state.ready()
        key = f"{identifier(name)}:bundle{suffix(agent)}"
        record = self.state.data["items"].get(key)
        if not record or record.get("kind") != "instruction":
            raise Error(f"{name}: instruction bundle has not been installed")
        target = Path(record["target"])
        if record.get("detached"):
            if target.is_symlink() or is_reparse(target):
                raise Error(f"{name}: detached bundle directory was replaced by a link")
        elif not target.is_symlink() or not link_matches(observation(target), record["source"]):
            raise Error(f"{name}: installed bundle link was replaced; inspect status")
        root = target.resolve(strict=True)
        if not root.is_dir():
            raise Error(f"{name}: installed bundle root is not a directory")
        entry = root / relative(record["entry"])
        # Refuse redirected entry paths, including intermediate links/junctions.
        cursor = entry
        while cursor != root:
            if cursor.is_symlink() or is_reparse(cursor):
                raise Error(f"{name}: entry path contains a symlink/junction")
            cursor = cursor.parent
        if not entry.is_file():
            raise Error(f"{name}: original entry document is missing: {entry}")
        return {"root": str(root), "entry": str(entry), "installed_root": str(target),
                "detached": bool(record.get("detached"))}

    def hook_context(self, name, agent="codex"):
        """Return location metadata only; personal instruction text stays in AGENTS.md."""
        found = self.locate_instruction(name, agent)
        record = self.state.data["items"].get(f"{name}:entry{suffix(agent)}")
        if not record or record.get("kind") != "instruction-entry" or record["mode"] != "link":
            raise Error(f"{name}: original instruction entry link is not installed")
        target = Path(record["target"])
        if not target.is_file():
            raise Error(f"{name}: installed global entry is unavailable")
        if record.get("detached") and (target.is_symlink() or is_reparse(target)):
            raise Error(f"{name}: detached global entry was replaced by a link")
        if not record.get("detached") and not link_matches(observation(target), record["source"]):
            raise Error(f"{name}: global entry link was replaced; inspect status")
        if found["detached"] and not record.get("detached"):
            # A directory can be detached independently while AGENTS.md still
            # links to the live original. Its references must use that original
            # tree until the entry is materialized too, not the frozen copy.
            source_entry = Path(record["source"])
            source_root = source_entry
            for _ in relative(record["entry"]).parts:
                source_root = source_root.parent
            cursor = source_entry
            while True:
                if cursor.is_symlink() or is_reparse(cursor):
                    raise Error(f"{name}: live entry source was redirected")
                if cursor == source_root:
                    break
                cursor = cursor.parent
            found.update(root=str(source_root.resolve(strict=True)), entry=str(source_entry.resolve(strict=True)))
        # Expose reading locations only: after partial detach, installed_root
        # can name a preserved copy that no longer matches the live entry.
        locations = {"root": found["root"], "entry": found["entry"], "global_entry": str(target)}
        context = ("AEM instruction document locations (not instruction contents):\n"
                   + json.dumps(locations, ensure_ascii=True)
                   + "\nThe global_entry field identifies the installed entry file to which these locations apply. "
                   "The entry field identifies its corresponding document location within the bundle; "
                   "root identifies the bundle directory, not necessarily the entry's parent directory. "
                   "These locations do not request another reading of the entry. If its contents are already "
                   "present in your context, do not reread them solely to establish these paths. "
                   "For relative references in the entry, use the parent directory of entry, not the "
                   "installed entry's directory or the working directory. For references in supplemental "
                   "documents, use each referring document's own directory. Use another base only when "
                   "the user documents explicitly specify it. "
                   "Follow those documents for applicability and reading order.")
        return profile(agent).context(context)

    def plan(self, item, *, adopt=False, replace=False, reattach=False):
        payload_hash = self.payload(item)
        before = observation(item.target)
        old = self.state.data["items"].get(item.key)
        if old and old.get("detached"):
            if not reattach:
                raise Error(f"{item.key}: detached; use --reattach")
            if item.mode != "agent-hook":
                old = None
        record = {"source_name": item.source_name, "relative": item.relative, "source": str(item.source),
                  "id": item.id,
                  "target": str(item.target), "mode": item.mode, "hash": payload_hash,
                  "directory": item.source.is_dir(), "detached": False, "kind": item.kind,
                  "exclude_git": item.kind in ("skill", "directory", "instruction", "instruction-hook") and item.relative == ".",
                  "entry": item.entry, "agent": item.agent, "agents": list(item.agents or (item.agent,))}
        if item.kind == "directory":
            record.pop("agent")
            record.pop("agents")
        present = before["kind"] != "missing"
        if item.mode == "agent-hook":
            if item.kind == 'personal-hook':
                from .personal_hooks import definition, render
                marker, event, group = definition(self.config, item)
                content = render(item.target, marker, event, group, None if old and old.get('removed') else old,
                                 adopt=adopt, replace=replace)
                record.update(hook_event=event, shared_settings_format=profile(item.agent).shared_settings_format)
            else:
                marker, group = profile(item.agent).definition(self.config.path, item.source_name)
                content = profile(item.agent).render(item.target, marker, group, old, adopt=adopt, replace=replace)
            record.update(hook_marker=marker, hook_group=group)
            changed = not present or item.target.read_bytes() != content
            return Plan(item, before, record, changed, content=content)
        if item.mode == "link":
            correct = link_matches(before, str(item.source))
            if old:
                safe = correct or not present
            else:
                safe = not present or (adopt and correct)
            if not safe and not replace:
                raise Error(f"{item.key}: existing or modified target; use explicit --adopt or --replace")
            return Plan(item, before, record, not correct)
        if item.mode == "copy":
            regular = before["kind"] in ("file", "directory")
            desired = regular and before["hash"] == payload_hash
            if old:
                safe = not present or (regular and before["hash"] in (old["hash"], payload_hash))
            else:
                safe = not present or (adopt and desired)
            if not safe and not replace:
                raise Error(f"{item.key}: existing or locally modified copy; use explicit --adopt or --replace")
            return Plan(item, before, record, not desired)
        raise Error(f"Unsupported installation mode: {item.mode}")

    def install(self, plan):
        item = plan.item
        if item.target.parent.resolve() / item.target.name != item.target:
            raise Error(f"{item.key}: target ancestry changed after preflight")
        if observation(item.target) != plan.before:
            raise Error(f"{item.key}: target changed after preflight")
        if plan.record.get('official_skill') and (plan.change or not plan.record.get('detached')):
            from .official_skills import signature
            if (not plan.delete or item.source.exists()) and signature(item.source) != plan.record['official_hash']:
                raise Error(f'{item.key}: official skill source changed after preflight')
        if plan.materialize is None and item.kind != "setup" and self.payload(item) != plan.record["hash"]:
            raise Error(f"{item.key}: source changed after preflight")
        for peer in plan.peers:
            if self.payload(peer.item) != peer.record["hash"]:
                raise Error(f"{peer.item.key}: source changed after preflight")
        if not plan.change:
            self.state.data["items"].update({item.key: plan.record, **plan.records})
            self.state.save()
            return
        item.target.parent.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex
        stage = item.target.with_name(".aem-stage-" + suffix)
        backup = item.target.with_name(item.target.name + ".aem-backup-" + suffix)
        isolated_skill = item.kind == "skill" and plan.record.get("kind", "skill") == "skill"
        if isolated_skill:
            backup = self.config.state_dir / 'skill-backups' / (item.target.name + '-' + suffix)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.parent.resolve() != backup.parent or overlaps(item.target.parent, self.config.state_dir):
                raise Error('Skill backup storage redirects or overlaps the skill root')
        if plan.delete:
            if not plan.record.get('official_skill'):
                raise Error('Deletion plans require official skill ownership')
            # A sibling backup link would still be discovered as an agent skill.
            # Keep it outside skills roots while retaining recoverable link identity.
            backup = self.config.state_dir / 'setup-backups' / (item.target.name + '-' + suffix)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.parent.resolve() != backup.parent:
                raise Error('Official skill backup directory redirects')
        try:
            if plan.materialize is not None:
                exclude_git = plan.record.get("exclude_git", False)
                copy_payload(plan.materialize, stage, exclude_git=exclude_git)
                if fingerprint(stage) != plan.record["hash"] or fingerprint(plan.materialize, exclude_git=exclude_git) != plan.record["hash"]:
                    raise Error(f"{item.key}: linked contents changed during detach")
            elif plan.delete:
                pass  # Removal stages absence; the backup and journal allow rollback.
            elif item.mode == "link":
                try:
                    stage.symlink_to(item.source, target_is_directory=item.source.is_dir())
                except OSError as exc:
                    raise Error("Cannot create a symbolic link; enable Windows Developer Mode/link privileges "
                                "or explicitly configure this item as copy") from exc
            elif item.mode == "copy":
                copy_payload(item.source, stage, exclude_git=plan.record.get("exclude_git", False))
                if fingerprint(stage) != plan.record["hash"] or self.payload(item) != plan.record["hash"]:
                    raise Error(f"{item.key}: source changed while copying")
            else:
                fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(plan.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(stage, stat.S_IMODE(item.target.stat().st_mode) if exists(item.target) else 0o600)
            if observation(item.target) != plan.before:
                raise Error(f"{item.key}: target changed during staging")
            if plan.record.get('official_skill') and (not plan.delete or item.source.exists()):
                from .official_skills import signature
                if signature(item.source) != plan.record['official_hash']:
                    raise Error(f'{item.key}: official skill source changed during staging')
            after = observation(stage)
            if isolated_skill and exists(item.target):
                # Copy before journaling/removal so cross-filesystem backups are
                # complete and verified while the original is still usable.
                if item.target.is_symlink():
                    backup.symlink_to(os.readlink(item.target), target_is_directory=True)
                else:
                    copy_payload(item.target, backup)
                if observation(backup) != plan.before or observation(item.target) != plan.before:
                    raise Error(f'{item.key}: target changed during backup')
            # Persist recovery paths before moving the old target. No journal is
            # needed for pure ownership adoption, which only writes state once.
            self.state.data["pending"] = {"key": item.key, "target": str(item.target), "stage": str(stage),
                                          "backup": str(backup), "before": plan.before, "after": after}
            if isolated_skill:
                self.state.data["pending"]["operation"] = "skill-replacement"
            self.state.save()
            if exists(item.target):
                if isolated_skill:
                    remove(item.target)
                elif plan.delete:
                    # Copy link identity, not its payload: state and skills may
                    # live on different filesystems, where rename cannot work.
                    backup.symlink_to(os.readlink(item.target), target_is_directory=True)
                    if observation(item.target) != plan.before or observation(backup) != plan.before:
                        raise Error(f'{item.key}: link changed during removal')
                    item.target.unlink()
                else:
                    os.replace(item.target, backup)
            if not plan.delete:
                os.replace(stage, item.target)
            if observation(item.target) != after:
                raise Error(f"{item.key}: installed target changed before commit")
            old_records = dict(self.state.data["items"])
            self.state.data["items"].update({item.key: plan.record, **plan.records})
            self.state.data["pending"] = None
            try:
                self.state.save()
            except Exception:
                self.state.data["items"] = old_records
                # Reload the durable journal for recovery after a failed commit.
                self.state.data["pending"] = State(self.config.state_dir, maintenance=self.state.maintenance).data["pending"]
                raise
        except Exception:
            if self.state.data.get("pending"):
                self.recover()
            raise
        finally:
            if exists(stage) and not self.state.data.get("pending"):
                remove(stage)

    def recover(self):
        pending = self.state.data.get("pending")
        if pending is None:
            return
        if pending.get("operation") == "settings-group":
            from .settings import recover_group
            recover_group(self.state)
            return
        if not all(k in pending for k in ("target", "backup", "stage", "before", "after")):
            raise Error("Incomplete recovery journal; cannot safely recover")
        target, backup, stage = (saved_path(pending[k]) for k in ("target", "backup", "stage"))
        if len({target, backup, stage}) != 3 or stage.parent != target.parent:
            raise Error("Recovery paths must be distinct siblings")
        for field in ("before", "after"):
            value = pending[field]
            if (not isinstance(value, dict) or value.get("kind") not in ("missing", "link", "file", "directory")
                    or (value["kind"] == "link" and not isinstance(value.get("to"), str))
                    or (value["kind"] in ("file", "directory") and not isinstance(value.get("hash"), str))):
                raise Error("Invalid recovery observation; cannot safely recover")
        record = self.state.data['items'].get(pending.get('key'), {})
        official_removal = (record.get('official_skill') and record.get('kind') == 'setup'
                            and record.get('mode') == 'link' and record.get('target') == str(target)
                            and link_matches(pending['before'], record.get('source'))
                            and pending['after'] == {'kind': 'missing'}
                            and backup.parent == self.config.state_dir / 'setup-backups'
                            and backup.parent.resolve() == backup.parent)
        isolated_skill = (pending.get('operation') == 'skill-replacement'
                          and backup.parent == self.config.state_dir / 'skill-backups'
                          and backup.parent.resolve() == backup.parent
                          and backup.name.startswith(target.name + '-')
                          and not overlaps(target.parent, self.config.state_dir))
        if pending.get('operation') == 'skill-replacement' and not isolated_skill:
            raise Error('Invalid skill backup recovery paths')
        if backup.parent != target.parent and not official_removal and not isolated_skill:
            raise Error('Recovery paths must be distinct siblings')
        current = observation(target)
        before, after = pending["before"], pending["after"]
        if exists(stage) and observation(stage) != after:
            raise Error("Recovery stopped: staged content changed")
        if exists(backup):
            if isolated_skill:
                allowed = (before, after, {'kind': 'missing'})
            else:
                allowed = (before, after) if official_removal else (after, {'kind': 'missing'})
            if observation(backup) != before or current not in allowed:
                raise Error("Recovery stopped: target or backup changed; preserve both and resolve manually")
            if isolated_skill:
                if current != before:
                    # Restore through a target-local stage, retaining the backup
                    # so another interruption remains recoverable across devices.
                    restore = target.with_name('.aem-restore-' + uuid.uuid4().hex)
                    try:
                        if backup.is_symlink():
                            restore.symlink_to(os.readlink(backup), target_is_directory=True)
                        else:
                            copy_payload(backup, restore)
                        if observation(restore) != before or observation(target) != current:
                            raise Error('Recovery stopped: contents changed during restoration')
                        if exists(target):
                            remove(target)
                        os.replace(restore, target)
                    finally:
                        if exists(restore):
                            remove(restore)
            elif official_removal:
                if current != before:
                    target.symlink_to(os.readlink(backup), target_is_directory=True)
            else:
                if exists(target):
                    remove(target)
                os.replace(backup, target)
        elif current == before:
            pass  # Crash before the first rename, or recovery already restored it.
        elif before == {"kind": "missing"} and current == after:
            remove(target)
        else:
            raise Error("Recovery stopped: cannot safely restore the recorded target")
        if exists(stage):
            if observation(stage) != after:
                raise Error("Recovery stopped: staged content changed")
            remove(stage)
        self.state.data["pending"] = None
        self.state.save()

    def apply(self, requested=(), *, adopt=False, replace=False, reattach=False, dry_run=False, timeout=30, agent=None):
        self.state.ready()
        if (adopt or replace) and not requested:
            raise Error("--adopt and --replace require explicit --item selections")
        items = self.selected(requested, reattach=reattach, agent=agent)
        from .settings import Settings, transaction
        settings = Settings(self)
        setting_items = [i for i in items if i.kind == "setting"]
        items = [i for i in items if i.kind != "setting"]
        setting_plans = [(i, *settings.apply_plan(i, replace=replace and self.matches(i, requested), reattach=reattach))
                         for i in setting_items]
        revisions = {}
        for name in {i.source_name for i in items}:
            source = self.config.sources[name]
            if source.git:
                git = Git(timeout)
                source = self.delivery_source(source)
                git.clean(source)
                revisions[name] = git.run(source.path, "rev-parse", "HEAD").stdout
                for item in [i for i in items if i.source_name == name]:
                    if item.kind == "skill":
                        git.skill_descriptor(source, item.relative)
                    elif item.kind == "directory":
                        git.directory_descriptor(source, item.relative)
                    elif item.kind in ("instruction", "instruction-hook"):
                        git.instruction_descriptor(source, item.relative, item.entry)
                    else:
                        git.tracked_payload(source, item.relative)
        def explicit(item):
            return self.matches(item, requested) or (item.kind == "instruction-hook" and
                (f"{item.source_name}:entry" in requested or f"{item.source_name}:entry{suffix(item.agent)}" in requested))
        plans = [self.plan(i, adopt=adopt and explicit(i), replace=replace and explicit(i), reattach=reattach)
                 for i in items]
        for plan in plans:
            plan.record["revision"] = revisions.get(plan.item.source_name)
        report = [{"item": p.item.key, "action": "install" if p.change else "record", "target": str(p.item.target)} for p in plans]
        for entry, plan in zip(report, plans):
            if plan.item.mode == "agent-hook":
                entry.update(hook="would-register" if dry_run and plan.change else "registered" if plan.change else "unchanged",
                             trust="not-managed-by-aem", notice=profile(plan.item.agent).notice,
                             hook_group=plan.record["hook_group"])
        grouped = self.group_hooks(plans)
        # Shared Claude preferences and hook groups commit one target image and
        # all comparison records, rather than racing two precomputed writes.
        settings_by_target = {i.target: (i, writes, record) for i, writes, record in setting_plans}
        joint_records = {}
        joint_hooks = {}
        ordinary = []
        for plan in grouped:
            if plan.item.mode != 'agent-hook' or plan.item.target not in settings_by_target:
                ordinary.append(plan)
                continue
            item, writes, record = settings_by_target[plan.item.target]
            from .settings_formats import FORMATS
            adapter = FORMATS['json']
            path, content, before = writes[0]
            if before != plan.before:
                raise Error('Shared settings/hook target changed during preflight')
            for peer in [plan, *plan.peers]:
                if self.payload(peer.item) != peer.record['hash']:
                    raise Error('Hook source changed during shared-file preflight')
            document = adapter.parse(content.decode())
            value = adapter.parse(plan.content.decode('utf-8')).root.children['hooks']
            adapter.put(document, ('hooks',), value)
            writes[0] = (path, adapter.dump(document).encode(), before)
            joint_records[item.key] = {plan.item.key: plan.record, **plan.records}
            joint_hooks[item.key] = [plan, *plan.peers]
        if not dry_run:
            for plan in ordinary:
                self.install(plan)
        for item, writes, record in setting_plans:
            # Ordinary installs can take time; retain install's source guard at
            # the shared hook commit boundary, including every grouped peer.
            for hook in joint_hooks.get(item.key, ()):
                if self.payload(hook.item) != hook.record['hash']:
                    raise Error(f'{hook.item.key}: source changed before shared-file commit')
            transaction(self.state, writes, {item.key: record, **joint_records.get(item.key, {})}, dry_run=dry_run)
            report.append({"item": item.key, "action": "apply", "target": str(item.target)})
        return report

    def group_hooks(self, plans):
        """Preflight each group, but commit one replacement per hook file."""
        grouped = {}
        result = []
        for plan in plans:
            if plan.item.mode != "agent-hook":
                result.append(plan)
                continue
            grouped.setdefault(plan.item.target, []).append(plan)
        for target, group in grouped.items():
            first = group[0]
            if len(group) > 1:
                with tempfile.TemporaryDirectory() as directory:
                    shadow = Path(directory) / "hooks.json"
                    if exists(target):
                        shadow.write_bytes(target.read_bytes())
                    for plan in group:
                        old = self.state.data["items"].get(plan.item.key)
                        if plan.item.kind == 'personal-hook':
                            from .personal_hooks import render
                            content = render(shadow, plan.record['hook_marker'], plan.record['hook_event'],
                                             plan.record['hook_group'], old, adopt=True, replace=True)
                        else:
                            content = profile(plan.item.agent).render(shadow, plan.record["hook_marker"],
                                           plan.record["hook_group"], old, adopt=True, replace=True)
                        shadow.write_bytes(content)
                    first.content = shadow.read_bytes()
                first.change = not exists(target) or first.content != target.read_bytes()
                first.records = {p.item.key: p.record for p in group[1:]}
                first.peers = group[1:]
            result.append(first)
        return result

    def detach(self, keys, *, dry_run=False, agent=None):
        self.state.ready()
        requested = set(keys)
        records = self.state.data["items"]
        def logical(key, record):
            return record.get("source_name") if record.get("kind") in ("skill", "directory", "setting", 'personal-hook') else key.split('@')[0]
        expanded = [k for k, r in records.items() if k in requested or logical(k, r) in requested]
        unknown = requested - records.keys() - {logical(k, r) for k, r in records.items()}
        if unknown:
            raise Error(f"Not a managed item: {sorted(unknown)}")
        keys = [k for k in expanded if agent is None or records[k].get("kind") == "directory"
                or agent in records[k].get("agents", [records[k].get("agent", "codex")])]
        if agent:
            profile(agent)
            for key in keys:
                if len(records[key].get("agents", [])) > 1:
                    raise Error(f"{key}: shared target; detach without --agent to release all consumers")
        # Preserve the registered hook on detach, but release its ownership with
        # the entry. Saved bundle records let it locate materialized contents.
        for key in list(keys):
            old = self.state.data["items"].get(key, {})
            hook_key = f"{old.get('source_name')}:hook{suffix(old.get('agent', 'codex'))}"
            if old.get("kind") == "instruction-entry" and hook_key in self.state.data["items"] and hook_key not in keys:
                keys.append(hook_key)
        plans, untouched = [], []
        for key in keys:
            old = self.state.data["items"].get(key)
            if old is None:
                raise Error(f"Not a managed item: {key}")
            if old.get("detached"):
                continue
            target = saved_path(old.get("target"))
            if old.get("kind") == "setting":
                from .settings import Settings, regular
                Settings(self).working(old, conflicts=True)
                regular(target, missing=True)
                untouched.append((key, dict(old, detached=True)))
                continue
            if not exists(target):
                raise Error(f"{key}: target is missing; cannot preserve usable contents")
            record = dict(old, detached=True)
            if target.is_symlink():
                content = target.resolve(strict=True)
                exclude_git = old.get("exclude_git", False)
                if not isinstance(exclude_git, bool):
                    raise Error(f"{key}: invalid saved copy exclusion")
                record["hash"] = fingerprint(content, exclude_git=exclude_git)
                # Use the saved key as an opaque transaction identity. No old
                # source declaration or install-mode interpreter is needed.
                item = Item("", key, ".", content, target, "link", "skill")
                plans.append(Plan(item, observation(target), record, True, materialize=content))
            else:
                # Preserve regular contents for any recorded mode, including
                # opaque partial ownership. Never release unreadable payloads.
                fingerprint(target)
                untouched.append((key, record))
        if not dry_run:
            for plan in plans:
                self.install(plan)
            for key, record in untouched:
                self.state.data["items"][key] = record
            self.state.save()
        return [{"item": key, "action": "detach"} for key in keys]

    def publish(self, names, *, message=None, dry_run=False, timeout=30):
        """Publish each selected checkout once, reporting every catalog consumer.

        Names select sources, not file scopes. Installation records and automatic
        update clocks are independent of publication and remain untouched.
        """
        self.state.ready()
        sources = self.config.sources
        if not names or set(names) - sources.keys():
            raise Error("publish requires known catalog skill, directory, instruction bundle, setting or personal hook names")
        if message is not None and not message.strip():
            raise Error("--message must not be empty")
        groups = {}
        for name, source in sources.items():
            groups.setdefault(source.path, []).append((name, source))
        results, failed = [], False
        for path, members in groups.items():
            selected = sorted(name for name, _ in members if name in names)
            if not selected:
                continue
            source = members[0][1]
            report = {"checkout": str(path), "repository": source.git,
                      "selected": selected, "members": sorted(name for name, _ in members),
                      "status": "planned"}
            results.append(report)
            try:
                if not source.git:
                    raise Error(f"{source.name}: external source publication is managed outside AEM")
                source = self.delivery_source(source)
                git = Git(timeout)
                report.update(git.publication(source))
                from .settings import Settings, changed, Bundle
                settings = Settings(self)
                setting_names = [n for n in selected if n in self.config._settings]
                report["unpublished_settings"] = [n for n, _ in members if n not in selected and n in self.config._settings
                    and (r := settings.record(n, required=False))
                    and changed(Bundle.from_snapshot(r["shared"], format=r["format"]), settings.working(r, conflicts=True))]
                if setting_names:
                    if not dry_run:
                        observed = git.publication_preflight(source)
                        if observed is not None and git.relation(source) not in ("ahead", "equal-at-last-fetch"):
                            raise Error("Reconcile Git history before settings export/publication")
                    report["export"] = settings.export(setting_names, dry_run=True)
                    if message is None and (any(e["changed"] for e in report["export"]) or report["changes"]):
                        raise Error("Settings changes require --message for publication")
                    if not dry_run:
                        report["export"] = settings.export(setting_names)
                if not dry_run:
                    git.publish(source, report, message=message)
                    for setting_name in setting_names:
                        key = f"{setting_name}:settings"
                        self.state.data["items"][key]["published"] = self.state.data["items"][key]["shared"]
                    if setting_names:
                        self.state.save()
            except (Error, OSError) as exc:
                failed = True
                report.update(status="failed", error=str(exc))
            if not dry_run and "last_fetch" in report:
                for name, _ in members:
                    self.state.data["sources"].setdefault(name, {}).update(
                        {key: report[key] for key in ("last_fetch", "observed_revision", "last_publish", "revision")
                         if key in report})
                self.state.save()
        return results, failed

    def update(self, names=(), *, timeout=30, prepare_settings=False):
        self.state.ready()
        if set(names) - self.config.sources.keys():
            raise Error("Unknown source selection")
        results, failed = [], False
        groups = {}
        for name, source in self.config.sources.items():
            groups.setdefault(source.path, []).append((name, source))
        for members in groups.values():
            selected = [(name, source) for name, source in members if not names or name in names]
            if not selected:
                continue
            name, source = members[0]
            source_state = self.state.data["sources"].setdefault(name, {})
            try:
                if source.git:
                    Git(timeout).update(self.delivery_source(source), self.state.data["items"], source_state,
                        validate_candidate=lambda git, src, rev: self.validate_consumers_revision(git, src, rev, members))
                    status = "updated"
                else:
                    if not source.path.is_dir():
                        raise Error(f"External source missing: {source.path}")
                    for member_name, member in members:
                        if member_name in self.config._hooks:
                            for item in self.config.declarations(member):
                                self.payload(item)
                    status = "external-no-fetch"
                    source_state["error"] = None
                for skill_name, _ in members:
                    if skill_name != name:
                        self.state.data["sources"].setdefault(skill_name, {}).update(
                            {key: source_state[key] for key in ("last_fetch", "observed_revision", "last_update", "revision", "error")
                             if key in source_state})
                results.extend({"source": skill_name, "status": status} for skill_name, _ in selected)
                from .settings import Settings
                for selected_name, _ in selected:
                    if selected_name in self.config._settings:
                        settings = Settings(self)
                        if prepare_settings:
                            # Initialize new full-run stages from delivered content;
                            # existing stages retain edits and comparison bases.
                            settings.prepare(self.config.declarations(self.config.sources[selected_name])[0])
                        received = settings.receive(selected_name)
                        results.append(received)
                        failed |= received["status"] == "conflict"
            except (Error, OSError) as exc:
                failed = True
                for skill_name, _ in selected:
                    self.state.data["sources"].setdefault(skill_name, {})["error"] = str(exc)
                    results.append({"source": skill_name, "status": "failed", "error": str(exc)})
            for skill_name, _ in selected:
                self.state.data["sources"].setdefault(skill_name, {})["last_attempt"] = now()
            self.state.save()
        return results, failed

    def validate_consumers_revision(self, git, source, revision, members):
        """Validate declared consumers before advancing their shared checkout."""
        from .settings import Bundle
        from .personal_hooks import guard_revision
        paths = {item.relative for name, member in members if name in self.config._hooks
                 for item in self.config.declarations(member)}
        paths.update(record['relative'] for record in self.state.data['items'].values()
                     if record.get('kind') == 'personal-hook' and not record.get('detached')
                     and str(source.path / record.get('relative', '')) == record.get('source'))
        guard_revision(git, source, revision, paths)
        for name, member in members:
            if name in self.config._directories:
                for item in self.config.declarations(member):
                    git.directory_descriptor(source, item.relative, revision)
            if name not in self.config._settings:
                continue
            path = self.config._settings[name]["path"]
            snapshot = {}
            for key, entry in (("config", path), ("management", path + ".aem.toml")):
                tree = git.run(source.path, "ls-tree", "-z", revision, "--", entry).stdout
                if not tree and key == "management":
                    snapshot[key] = ""
                    continue
                if not tree or tree.split(" ", 1)[0] not in ("100644", "100755"):
                    raise Error(f"{name}: settings must be tracked regular files")
                snapshot[key] = git.run(source.path, "show", f"{revision}:{entry}", strict_utf8=True).stdout
            Bundle.from_snapshot(snapshot, format=self.config._settings[name]["format"])

    def item_status(self, item, old):
        if old and old.get("detached"):
            return "detached", None
        desired = self.payload(item)
        current = observation(item.target)
        if old is None:
            return "unmanaged-existing" if current["kind"] != "missing" else "not-installed", None
        if old["target"] != str(item.target) or old["mode"] != item.mode or old["source"] != str(item.source):
            return "configuration-changed", None
        if current["kind"] == "missing":
            return "missing", None
        if item.mode == "agent-hook":
            if item.kind == 'personal-hook':
                from .personal_hooks import definition, current
                marker, event, group = definition(self.config, item)
                if current(item.target, marker, event, group):
                    return 'current', ('changed-live' if desired != old['hash'] else None)
                return ('stale' if current(item.target, old['hook_marker'], old['hook_event'], old['hook_group'])
                        else 'modified-locally'), None
            marker, group = profile(item.agent).definition(self.config.path, item.source_name)
            if profile(item.agent).current(item.target, marker, group):
                return "current", None
            return ("stale" if profile(item.agent).current(item.target, old["hook_marker"], old["hook_group"])
                    else "modified-locally"), None
        if item.mode == "link":
            good = link_matches(current, str(item.source))
            return ("current" if good else "modified-locally"), ("changed-live" if desired != old["hash"] else None)
        if item.mode == "copy":
            if current["kind"] not in ("file", "directory"):
                return "modified-locally", None
            actual = current["hash"]
            if actual == desired:
                return "current", None
            if actual == old["hash"]:
                return "stale", None
            return ("conflict" if desired != old["hash"] else "modified-locally"), None
        raise Error(f"Unsupported installation mode: {item.mode}")

    def status(self, *, refresh=False, timeout=30, agent=None):
        report = {"sources": [], "items": [], "pending": self.state.data.get("pending")}
        if "startup" in self.state.data:
            report["startup"] = self.state.data["startup"]
        try:
            sources = self.config.sources
        except Error as exc:
            report["catalog_error"] = str(exc)
            sources = {}
        seen = set()
        for name, source in sources.items():
            entry = {"source": name, "path": str(source.path), "transport": "git" if source.git else "external",
                     **self.state.data["sources"].get(name, {})}
            entry["last_update_error"] = entry.pop("error", None)
            entry["availability"] = "present" if source.path.is_dir() else "missing"
            try:
                if source.git:
                    git = Git(timeout)
                    source = self.delivery_source(source)
                    if refresh:
                        revision = git.fetch(source)
                        stored = self.state.data["sources"].setdefault(name, {})
                        stored.update(last_fetch=now(), observed_revision=revision)
                        self.state.save()
                        entry.update({k: v for k, v in stored.items() if k != "error"})
                    git.validate(source)
                    entry["head"] = git.run(source.path, "rev-parse", "HEAD").stdout
                    branch = git.run(source.path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
                    entry["branch"] = branch.stdout if branch.returncode == 0 else "detached"
                    entry["checkout"] = "dirty" if git.run(source.path, "status", "--porcelain", "--untracked-files=all").stdout else "clean"
                    entry["remote_relation"] = git.relation(source)
                else:
                    entry["remote_relation"] = "externally-managed-unknown"
            except (Error, OSError, ValueError) as exc:
                entry["error"] = str(exc)
            try:
                for item in self.config.declarations(source):
                    seen.add(item.key)
                    if agent and item.kind != "directory" and agent not in (item.agents or (item.agent,)):
                        continue
                    item_entry = {"item": item.key, "target": str(item.target), "mode": item.mode}
                    old = self.state.data["items"].get(item.key)
                    if item.kind == "setting":
                        from .settings import Settings
                        try:
                            item_entry.update(Settings(self).status(old) if old else {"status": "not-prepared"})
                        except (Error, OSError, ValueError) as exc:
                            item_entry.update(status="unavailable", error=str(exc))
                        report["items"].append(item_entry)
                        continue
                    if old:
                        item_entry["installation"] = self.installed_status(old)
                    try:
                        status, note = self.item_status(item, old)
                        item_entry.update(status=status)
                        if note:
                            item_entry["note"] = note
                    except (Error, OSError, ValueError) as exc:
                        item_entry.update(status="unavailable", error=str(exc))
                    report["items"].append(item_entry)
            except (Error, OSError, ValueError) as exc:
                entry["error"] = str(exc)
            report["sources"].append(entry)
        for key, old in self.state.data["items"].items():
            if old.get("mode") == "setup-config":
                continue
            if key not in seen and (agent is None or old.get("kind") == "directory"
                                    or agent in old.get("agents", [old.get("agent", "codex")])):
                report["items"].append({"item": key, "target": old["target"],
                                        "installation": self.installed_status(old),
                                        "status": "detached" if old.get("detached") else "setup" if old.get("kind") == "setup" else "orphaned-or-source-unavailable"})
        return report

    def saved_status(self, *, agent=None, error=None):
        """Inspect recorded targets without interpreting source declarations or modes."""
        report = {"sources": [], "items": [], "pending": self.state.data["pending"],
                  "state_version": self.state.data["version"], "saved_only": True}
        if error:
            report["configuration_error"] = str(error)
        for key, record in self.state.data["items"].items():
            if agent and record.get("kind") != "directory" and agent not in record.get("agents", [record.get("agent", "codex")]):
                continue
            item = {"item": key, "target": record.get("target"), "mode": record.get("mode"),
                    "status": "detached" if record.get("detached") else "recorded"}
            try:
                target = saved_path(record.get("target"))
                item["observation"] = observation(target)
                if record.get("kind") == "personal-hook":
                    item["installation"] = self.installed_status(record)
                    item["hook_event"] = record.get("hook_event")
                if target.is_symlink():
                    item["link_available"] = target.exists()
            except (Error, OSError, ValueError) as exc:
                item["error"] = str(exc)
            report["items"].append(item)
        return report

    def installed_status(self, record):
        """Inspect the last installed target even when its source is unavailable."""
        try:
            target = Path(record["target"])
            actual = observation(target)
            if record.get("detached"):
                return "unmanaged"
            if actual["kind"] == "missing":
                return "missing"
            if record.get("kind") == "setting":
                from .settings import Settings
                return Settings(self).status(record)["status"]
            if record["mode"] == "link":
                if not link_matches(actual, record["source"]):
                    return "modified-locally"
                return "linked" if target.exists() else "broken-link"
            if record["mode"] == "agent-hook":
                if record.get('kind') == 'personal-hook':
                    from .personal_hooks import current
                    matches = current(target, record['hook_marker'], record['hook_event'], record['hook_group'])
                else:
                    matches = profile(record.get("agent", "codex")).current(target, record["hook_marker"], record["hook_group"])
            elif record.get("kind") == "setup":
                block = record.get("block")
                matches = bool(block) and target.read_bytes().decode("utf-8").count(block) == 1
            elif record["mode"] == "copy":
                matches = actual.get("hash") == record["hash"]
            else:
                raise Error(f"Unsupported installation mode: {record['mode']}")
            return "matches-last-apply" if matches else "modified-locally"
        except (Error, OSError, ValueError):
            return "unreadable"
