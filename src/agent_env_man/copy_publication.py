"""Opt-in copy collection with a common hash baseline and recoverable source writes."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import uuid

from .model import Error, Item, overlaps, relative
from .payload_links import CopyCleanupError, options as payload_options, scan, replace as replace_link_entry, chmod_directory, remove as remove_link_entry
from .payload_policy import excluded, child_options, saved as saved_policy, preservation_paths, retention, park, restore_retained, validate_retention
from .storage import atomic_write, copy_payload, exists, fingerprint, is_reparse, observation, remove, saved_path


@dataclass
class Collection:
    item: Item
    record: dict
    source_hash: str
    copy_hash: str
    report: dict
    source_observation: dict
    copy_observation: dict


def copy_inspection(path, *, exclude_git=False, entries=None, modes=None, **policy):
    """Capture one copy's guard and included hash, preserving its .git boundary.

    The guard historically includes a copy-local .git while its collection hash
    does not. Without that entry the two hashes agree, so one traversal suffices;
    when present retain both inspections rather than weakening the guard.
    """
    captured = {} if exclude_git else entries
    observed = observation(path, entries=captured, modes=modes, **policy)
    hashed = observed.get('hash')
    if exclude_git:
        if '.git' in captured:
            hashed = fingerprint(path, exclude_git=True, **policy)
        if entries is not None:
            entries.update({name: value for name, value in captured.items()
                            if name != '.git' and not name.startswith('.git/')})
    return observed, hashed


def child_observations(entries, modes, *, permissions='strict', details=None):
    """Project top-level child observations from one verified parent traversal.

    Each group's normalized preorder encoding is the same as inspecting that
    child directly. Group once instead of filtering the whole tree per child.
    These values prepare stages only; physical guards still precede replacement.
    """
    groups = {}
    for path, value in entries.items():
        if path == '.':
            continue
        name, _, suffix = path.partition('/')
        groups.setdefault(name, ({}, {}))[0][suffix or '.'] = value
    if permissions == 'best-effort':
        for path, mode in modes.items():
            name, _, suffix = path.partition('/')
            if name in groups:
                groups[name][1][suffix or '.'] = mode
    if details is not None:
        details.update(groups)
    observations = {}
    for name, (children, native_modes) in groups.items():
        kind, _, value = children['.']
        if kind == 'l':
            observations[name] = {'kind': 'link', 'to': value}
            continue
        hashed = hashlib.sha256()
        for relative in sorted(children, key=lambda p: () if p == '.' else tuple(p.split('/'))):
            node, executable, value = children[relative]
            hashed.update(json.dumps(['' if relative == '.' else '/' + relative, node, executable],
                                     ensure_ascii=True).encode() + b'\0')
            if node == 'l':
                hashed.update(json.dumps(value, ensure_ascii=True).encode() + b'\0')
            elif node == 'f':
                hashed.update(value)
        observed = {'kind': 'directory' if kind == 'd' else 'file', 'hash': hashed.hexdigest()}
        if permissions == 'best-effort':
            from .permissions import digest
            observed['permissions_hash'] = digest(native_modes)
        observations[name] = observed
    return observations


def plan(manager, names):
    """Inspect only selected, owned copies; never adopt or collect detached content."""
    result = []
    for name in names:
        items = manager.config.declarations(manager.config.sources[name])
        for item in items:
            if item.kind in ('instruction-entry', 'instruction-hook'):
                continue
            if item.kind not in ('skill', 'directory', 'instruction') or item.mode != 'copy':
                raise Error(f'{name}: --from-copy requires installed skill, directory, or instruction copies')
            record = manager.state.data['items'].get(item.key)
            if not record:
                raise Error(f'{item.key}: copy is not installed; run apply first')
            if record.get('detached'):
                raise Error(f'{item.key}: detached copies cannot be collected')
            if item.kind == 'instruction' and bool(record.get('shared_bundle')) != item.shared_bundle:
                raise Error(f'{item.key}: bundle sharing changed; detach before reconfiguration')
            if any(record.get(field) != value for field, value in
                   (('source', str(item.source)), ('target', str(item.target)), ('mode', 'copy'), ('kind', item.kind))):
                raise Error(f'{item.key}: copy ownership changed; inspect status')
            if not isinstance(record.get('hash'), str):
                raise Error(f'{item.key}: copy has no saved baseline')
            if record.get('exclude_git', False) != (item.relative == '.'):
                raise Error(f'{item.key}: copy payload boundary changed; inspect status')
            if record.get('permissions', 'strict') != item.permissions:
                raise Error(f'{item.key}: permission policy changed; apply before collection')
            if record.get('exclusions', []) != saved_policy(payload_options(item)).get('exclusions', []):
                raise Error(f'{item.key}: exclusion policy changed; apply before collection')
            saved_path(str(item.target))
            if not item.target.is_dir():
                raise Error(f'{item.key}: installed copy directory is missing')
            left, right = {}, {}
            source_observed = manager.source_observation(item, entries=left)
            source_hash = source_observed['hash']
            copy_observed, copy_hash = copy_inspection(item.target, exclude_git=record.get('exclude_git', False),
                                                       entries=right, **payload_options(item))
            if copy_observed['kind'] != 'directory':
                raise Error(f'{item.key}: copy changed during inspection')
            if item.kind == 'skill' and not (item.target / 'SKILL.md').is_file():
                raise Error(f'{item.key}: collected skill requires SKILL.md')
            if item.kind == 'instruction':
                manager.locate_entry(item.target, item.target / item.entry)
            baseline = record['hash']
            source_changed = source_hash != baseline or (item.permissions == 'best-effort' and source_observed != record.get('source_observation'))
            conflict = source_changed and copy_hash != baseline and source_hash != copy_hash
            changed = copy_hash != baseline and copy_hash != source_hash
            if changed and not conflict:
                preservation_paths(item.source, item.target, payload_options(item))
            compare = ['git', 'difftool', '--no-index', '--', str(item.source), str(item.target)]
            command = ("& " + ' '.join("'" + part.replace("'", "''") + "'" for part in compare)
                       if os.name == 'nt' else shlex.join(compare))
            report = {'item': item.key, 'source': str(item.source), 'copy': str(item.target),
                      'baseline_hash': baseline, 'source_hash': source_hash, 'copy_hash': copy_hash,
                      'changed': changed, 'stale': copy_hash == baseline and source_changed,
                      'conflict': conflict, 'changes': sorted(p for p in left.keys() | right.keys() if left.get(p) != right.get(p)),
                      'compare': compare,
                      'compare_command': command}
            result.append(Collection(item, {**record, **({'preserve_symlinks': item.preserve_symlinks} if item.kind == 'directory' else {})}, source_hash, copy_hash, report, source_observed, copy_observed))
    return result


def selected_writes(plans):
    """Coalesce identical overlapping exports and reject competing copy contents."""
    writes = []
    for plan in sorted((p for p in plans if p.report['changed']), key=lambda p: len(p.item.source.parts)):
        for other in writes:
            if not overlaps(plan.item.source, other.item.source):
                continue
            if plan.item.permissions != other.item.permissions:
                raise Error('Differently permissioned overlapping copy collection requires separate selections')
            if (plan.item.exclusions or other.item.exclusions) and (plan.item.source != other.item.source
                    or plan.item.exclusions != other.item.exclusions):
                raise Error('Nested or differently filtered overlapping copy collection requires separate selections')
            relative = plan.item.source.relative_to(other.item.source)
            incoming = other.item.target / relative
            cursor = incoming
            while cursor != other.item.target:
                if cursor.is_symlink() or (exists(cursor) and is_reparse(cursor)):
                    raise Error('Overlapping collection redirects through a link')
                cursor = cursor.parent
            if not incoming.is_dir() or fingerprint(incoming, exclude_git=plan.record.get('exclude_git', False), **payload_options(plan.item)) != plan.copy_hash:
                plan.report['conflict'] = other.report['conflict'] = True
                raise Error('Conflicting copies select the same or overlapping source content; reconcile the reported copies')
            break
        else:
            writes.append(plan)
    return writes


def guard_links(writes, records):
    """Check affected saved links against the source tree after collection.

    Coalesced writes are disjoint and their copy payloads have been validated
    under each writer's policy. Project required paths into those copies, retaining the
    unchanged source for ancestors and excluded Git metadata. Saved ownership
    also protects links whose catalog declarations have disappeared.
    """
    def incoming(path):
        for write in writes:
            root = write.item.source
            if path == root or root in path.parents:
                suffix = path.relative_to(root)
                if (write.record.get('exclude_git') and suffix.parts[:1] == ('.git',)) or excluded(suffix.as_posix(), write.item.exclusions):
                    return path
                return write.item.target / suffix
        return path

    for key, record in records.items():
        if record.get('mode') != 'link' or record.get('detached'):
            continue
        source = Path(record.get('link_target', record['source']))
        if not any(overlaps(source, write.item.source) for write in writes):
            continue
        required = [(source, record['directory'])]
        if record.get('kind') == 'skill':
            required.append((source / 'SKILL.md', False))
        elif record.get('kind') == 'instruction':
            required.append((source / relative(record['entry']), False))
        for path, directory in required:
            candidate = incoming(path)
            for write in writes:
                if write.item.target in candidate.parents:
                    cursor = candidate.parent
                    while cursor != write.item.target:
                        if cursor.is_symlink() or (exists(cursor) and is_reparse(cursor)):
                            raise Error(f'{key}: collection redirects a required live link source; detach first')
                        cursor = cursor.parent
            redirected = candidate.is_symlink() or (exists(candidate) and is_reparse(candidate))
            valid = not redirected and (candidate.is_dir() if directory else candidate.is_file())
            if not valid:
                raise Error(f'{key}: collection removes or changes a required live link source: {path}; '
                            'detach the affected item first or reconcile the copy')

        for write in writes:
            if source == write.item.source or write.item.source in source.parents:
                candidate = incoming(source)
                logical = record.get('relative', '.')
                exclude_git = record.get('exclude_git', False)
            elif source in write.item.source.parents:
                candidate = write.item.target
                logical = str(Path(record.get('relative', '.')) / write.item.source.relative_to(source))
                exclude_git = False
            else:
                continue
            if candidate != write.item.target and write.item.target not in candidate.parents:
                continue  # Excluded live sources remain in place.
            if os.name != 'nt':
                scan(candidate, source_relative=logical, exclude_git=exclude_git,
                     allow_symlinks=bool(payload_options(record).get('preserve_symlinks')),
                     exclusions=write.item.exclusions,
                     exclude_prefix=candidate.relative_to(write.item.target).as_posix() if candidate != write.item.target else '')
            else:
                fingerprint(candidate, exclude_git=exclude_git, exclusions=write.item.exclusions,
                            exclude_prefix=candidate.relative_to(write.item.target).as_posix() if candidate != write.item.target else '')


def validate(manager, plans, *, capture=False):
    """Recheck source and copy observations before and after temporary staging."""
    manager.state.ready()
    captured = {}
    for plan in plans:
        source_entries, copy_entries, source_modes, copy_modes = {}, {}, {}, {}
        actual = manager.source_observation(plan.item, entries=source_entries if capture else None,
                                            modes=source_modes if capture else None)
        if actual.get('hash') != plan.source_hash or (plan.item.permissions == "best-effort" and actual != plan.source_observation):
            raise Error(f'{plan.item.key}: source changed during collection; retry after inspection')
        saved_path(str(plan.item.target))
        actual, hashed = copy_inspection(plan.item.target, exclude_git=plan.record.get('exclude_git', False),
            entries=copy_entries if capture else None, modes=copy_modes if capture else None, **payload_options(plan.item))
        if hashed != plan.copy_hash or (plan.item.permissions == 'best-effort' and actual != plan.copy_observation):
            raise Error(f'{plan.item.key}: copy changed during collection; retry after inspection')
        if capture:
            source_parts, copy_parts = {}, {}
            captured[plan.item.key] = (
                child_observations(source_entries, source_modes, permissions=plan.item.permissions, details=source_parts),
                child_observations(copy_entries, copy_modes, permissions=plan.item.permissions, details=copy_parts),
                source_parts, copy_parts)
    guard_links(selected_writes(plans), manager.state.data['items'])
    return captured if capture else None


def collect(manager, source, plans):
    """Replace changed payload children as one source group, leaving its .git intact.

    Temporary stages and retained backups live beside the source root so they
    never become source payload or Git publication content. The durable journal
    precedes mutations; baseline records commit only after both sides are checked.
    """
    writes = selected_writes(plans)
    captured = validate(manager, plans, capture=True)
    state = manager.state
    entries, modes = [], []
    scratch = None
    old_items = deepcopy(state.data['items'])
    try:
        if writes:
            saved_path(str(source.path))
            candidate = source.path.with_name('.aem-collection-' + uuid.uuid4().hex)
            candidate.mkdir()
            scratch = candidate
            (scratch / 'stages').mkdir(parents=True)
            (scratch / 'backups').mkdir()
        for plan in writes:
            item = plan.item
            source_children, copy_children, source_parts, copy_parts = captured[item.key]
            names = source_children.keys() | copy_children.keys()
            if item.permissions == 'strict':
                modes.append({'target': str(item.source), 'before': stat.S_IMODE(item.source.stat().st_mode),
                              'after': stat.S_IMODE(item.target.stat().st_mode)})
            for name in sorted(names):
                if excluded(name, item.exclusions):
                    continue
                target, incoming = item.source / name, item.target / name
                policy = child_options(payload_options(item), name)
                source_modes, incoming_modes = {}, {}
                source_entries, incoming_entries = {}, {}
                before = source_children.get(name, {'kind': 'missing'})
                after = copy_children.get(name, {'kind': 'missing'})
                if before == after or (item.permissions == 'best-effort'
                        and before.get('kind') == after.get('kind')
                        and before.get('hash') == after.get('hash')
                        and before.get('to') == after.get('to')):
                    continue
                index = str(len(entries))
                stage, backup = scratch / 'stages' / index, scratch / 'backups' / index
                if exists(incoming):
                    if item.permissions == "best-effort":
                        from .permissions import differences
                        # Only changed children need per-node mode/type maps.
                        # The maps are already captured by the fresh parent guard.
                        source_entries, source_modes = source_parts.get(name, ({}, {}))
                        incoming_entries, incoming_modes = copy_parts.get(name, ({}, {}))
                        source_types = {path: value[0] for path, value in source_entries.items() if value[0] != 'l'}
                        incoming_types = {path: value[0] for path, value in incoming_entries.items() if value[0] != 'l'}
                        # Replaced node types use incoming modes; a file's mode
                        # can make a new directory inaccessible, and a directory's
                        # mode can make a replacement file executable.
                        destination_modes = {path: mode for path, mode in source_modes.items()
                                             if source_types[path] == incoming_types.get(path)}
                        failures = []
                        copy_payload(incoming, stage, destination_modes=destination_modes, permission_failures=failures, **policy)
                        actual_modes = {}
                        staged = observation(stage, modes=actual_modes, **policy)
                        if (staged.get("kind") != after.get("kind") or staged.get("hash") != after.get("hash")
                                or staged.get("to") != after.get("to")):
                            raise Error(f'{item.key}: copy changed while staging')
                        requested = {**incoming_modes, **destination_modes}
                        changes = differences(requested, actual_modes, failures)
                        plan.report.setdefault("permission_differences", []).extend(
                            {**change, "path": name if change["path"] == "." else name + "/" + change["path"]}
                            for change in changes)
                        after = staged
                    else:
                        copy_payload(incoming, stage, **policy)
                    if observation(stage, **policy) != after:
                        raise Error(f'{item.key}: copy changed while staging')
                retained = retention(target, stage, policy)
                entries.append({'target': str(target), 'stage': str(stage), 'backup': str(backup),
                                'before': before, 'after': after,
                                **saved_policy(policy), **({'retained': retained} if retained else {})})
        validate(manager, plans)
        journal = {'operation': 'copy-collection', 'root': str(source.path), 'scratch': str(scratch),
                   'files': entries, 'modes': modes}
        if scratch:
            atomic_write(scratch / 'manifest.json', (json.dumps(journal, indent=2) + '\n').encode('utf-8'))
            state.data['pending'] = journal
            state.save()
        for entry in entries:
            target = Path(entry['target'])
            policy = payload_options(entry)
            saved_path(str(target))
            if observation(target, **policy) != entry['before']:
                raise Error('Source changed before collection commit')
            park(target, entry.get('retained'), policy)
            if exists(target):
                (replace_link_entry if policy.get("preserve_symlinks") else os.replace)(target, entry['backup'])
            if entry['after']['kind'] != 'missing':
                (replace_link_entry if policy.get("preserve_symlinks") else os.replace)(entry['stage'], target)
            restore_retained(target, entry.get('retained'), policy)
        for mode in modes:
            (chmod_directory if any(p.item.preserve_symlinks for p in plans) else os.chmod)(mode['target'], mode['after'])
        for entry in entries:
            if observation(Path(entry['target']), **payload_options(entry)) != entry['after']:
                raise Error('Source changed before collection state commit')
        for plan in plans:
            source_modes, copy_modes = {}, {}
            if plan.item.permissions == 'best-effort':
                source_observed = manager.source_observation(plan.item, modes=source_modes)
                current = source_observed['hash']
            else:
                current = manager.payload(plan.item)
            copy_observed, hashed = copy_inspection(plan.item.target, exclude_git=plan.record.get('exclude_git', False),
                                                    modes=copy_modes, **payload_options(plan.item))
            if hashed != plan.copy_hash or (plan.item.permissions == 'best-effort' and copy_observed != plan.copy_observation):
                raise Error(f'{plan.item.key}: copy changed before collection state commit')
            if plan.report['changed'] and current != plan.copy_hash:
                raise Error(f'{plan.item.key}: source changed before collection state commit')
            if current == plan.copy_hash:
                record = {**plan.record, 'hash': plan.copy_hash}
                if plan.item.permissions == "best-effort" and plan.report['changed']:
                    record['source_observation'] = source_observed
                    manager.permission_record(record, plan.item.source, plan.item.target, payload_options(plan.item),
                        observed=copy_observed, requested=source_modes, actual=copy_modes)
                    record["collection_permission_differences"] = plan.report.get("permission_differences", [])
                state.data['items'][plan.item.key] = record
        state.data['pending'] = None
        try:
            state.save()
        except Exception:
            state.data['items'] = old_items
            state.data['pending'] = journal if scratch else None
            raise
    except Exception as exc:
        if state.path.exists():
            state.data = json.loads(state.path.read_text(encoding='utf-8'))
        pending = state.data.get('pending')
        if pending and pending.get('operation') == 'copy-collection':
            recover(state)
        elif scratch and exists(scratch) and not isinstance(exc, CopyCleanupError):
            (remove_link_entry if any(p.item.preserve_symlinks for p in plans) else remove)(scratch)
        raise
    return str(scratch) if scratch else None


def recover(state):
    """Restore a source group only when every journal observation is still safe."""
    journal = state.data['pending']
    root, scratch = saved_path(journal.get('root')), saved_path(journal.get('scratch'))
    if scratch.parent != root.parent or not scratch.name.startswith('.aem-collection-'):
        raise Error('Invalid copy collection recovery storage')
    if not isinstance(journal.get('files'), list) or not isinstance(journal.get('modes'), list):
        raise Error('Incomplete copy collection recovery journal')
    targets = []
    for index, entry in enumerate(journal['files']):
        if not isinstance(entry, dict) or set(entry) - {'preserve_symlinks', 'relative', 'exclusions', 'exclude_prefix', 'retained', 'permissions'} != {'target', 'stage', 'backup', 'before', 'after'}:
            raise Error('Invalid copy collection recovery entry')
        policy = payload_options(entry)
        target, stage, backup = [saved_path(entry[k]) for k in ('target', 'stage', 'backup')]
        if (root not in target.parents or target.relative_to(root).parts[0] == '.git'
                or any(overlaps(target, p) for p in targets)
                or stage != scratch / 'stages' / str(index) or backup != scratch / 'backups' / str(index)):
            raise Error('Invalid copy collection recovery paths')
        if entry.get('retained'):
            validate_retention(target, entry['retained'], policy)
        targets.append(target)
        for key in ('before', 'after'):
            observed = entry[key]
            if (not isinstance(observed, dict) or observed.get('kind') not in (('file', 'directory', 'missing', 'link') if policy.get("preserve_symlinks") else ('file', 'directory', 'missing'))
                    or (observed['kind'] in ('file', 'directory') and not isinstance(observed.get('hash'), str))
                    or (observed['kind'] == 'link' and not isinstance(observed.get('to'), str))):
                raise Error('Invalid copy collection recovery observation')
        current = observation(target, **policy)
        if exists(backup):
            safe = observation(backup, **policy) == entry['before'] and current in (entry['after'], {'kind': 'missing'}, entry['before'])
        else:
            safe = current == entry['before'] or (entry['before'] == {'kind': 'missing'} and current == entry['after'])
        if not safe or (exists(stage) and observation(stage, **policy) not in (entry['after'], entry['before'])):
            raise Error('Recovery stopped: source, stage or backup changed; preserve them and resolve manually')
    for mode in journal['modes']:
        if not isinstance(mode, dict) or set(mode) != {'target', 'before', 'after'}:
            raise Error('Invalid copy collection recovery mode')
        target = saved_path(mode['target'])
        if ((target != root and root not in target.parents) or not target.is_dir()
                or (target != root and target.relative_to(root).parts[0] == '.git')
                or target.is_symlink() or is_reparse(target)):
            raise Error('Invalid copy collection mode path')
        for key in ('before', 'after'):
            if isinstance(mode[key], bool) or not isinstance(mode[key], int) or not 0 <= mode[key] <= 0o7777:
                raise Error('Invalid copy collection mode')
        if stat.S_IMODE(target.stat().st_mode) not in (mode['before'], mode['after']):
            raise Error('Recovery stopped: source directory permissions changed')
    for entry in reversed(journal['files']):
        policy = payload_options(entry)
        target, stage, backup = [Path(entry[k]) for k in ('target', 'stage', 'backup')]
        if exists(backup):
            park(target, entry.get('retained'), policy)
        if exists(backup) and observation(target, **policy) != entry['before']:
            if exists(target):
                (remove_link_entry if policy.get("preserve_symlinks") else remove)(target)
            # Keep the original backup through interrupted restoration attempts.
            if exists(stage):
                (remove_link_entry if policy.get("preserve_symlinks") else remove)(stage)
            copy_payload(backup, stage, **policy)
            if observation(stage, **policy) != entry["before"]:
                raise Error("Recovery stopped: restored content or permissions differ from backup")
            (replace_link_entry if policy.get("preserve_symlinks") else os.replace)(stage, target)
        elif entry['before'] == {'kind': 'missing'} and exists(target):
            (remove_link_entry if policy.get("preserve_symlinks") else remove)(target)
        restore_retained(target, entry.get('retained'), policy)
    for mode in journal['modes']:
        (chmod_directory if any(e.get('preserve_symlinks') for e in journal['files']) else os.chmod)(mode['target'], mode['before'])
    state.data['pending'] = None
    state.save()
