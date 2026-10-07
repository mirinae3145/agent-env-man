"""Opt-in copy collection with a common hash baseline and recoverable source writes."""

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import stat
import uuid

from .model import Error, Item, overlaps, relative
from .payload_links import options as payload_options, scan, replace as replace_link_entry, chmod_directory, remove as remove_link_entry
from .storage import atomic_write, copy_payload, exists, fingerprint, is_reparse, observation, remove, saved_path


@dataclass
class Collection:
    item: Item
    record: dict
    source_hash: str
    copy_hash: str
    report: dict


def tree(path, *, exclude_git=False, **policy):
    """Describe payload paths for previews, including removals and empty directories."""
    if policy.get("preserve_symlinks"):
        return scan(path, exclude_git=exclude_git, source_relative=policy["source_relative"])[1]
    result = {}
    def visit(current):
        if current.is_symlink() or is_reparse(current):
            raise Error(f'Payload symlinks/junctions are unsupported: {current}')
        relative = current.relative_to(path)
        result[relative.as_posix()] = ('directory' if current.is_dir() else 'file',
                                     current.stat().st_mode & 0o111 if os.name != 'nt' else 0,
                                     None if current.is_dir() else fingerprint(current))
        if current.is_dir():
            for child in sorted(current.iterdir()):
                if not (exclude_git and current == path and child.name == '.git'):
                    visit(child)
    visit(path)
    return result


def plan(manager, names):
    """Inspect only selected, owned copies; never adopt or collect detached content."""
    result = []
    for name in names:
        items = manager.config.declarations(manager.config.sources[name])
        for item in items:
            if item.kind not in ('skill', 'directory') or item.mode != 'copy':
                raise Error(f'{name}: --from-copy requires installed skill or directory copies')
            record = manager.state.data['items'].get(item.key)
            if not record:
                raise Error(f'{item.key}: copy is not installed; run apply first')
            if record.get('detached'):
                raise Error(f'{item.key}: detached copies cannot be collected')
            if any(record.get(field) != value for field, value in
                   (('source', str(item.source)), ('target', str(item.target)), ('mode', 'copy'), ('kind', item.kind))):
                raise Error(f'{item.key}: copy ownership changed; inspect status')
            if not isinstance(record.get('hash'), str):
                raise Error(f'{item.key}: copy has no saved baseline')
            if record.get('exclude_git', False) != (item.relative == '.'):
                raise Error(f'{item.key}: copy payload boundary changed; inspect status')
            saved_path(str(item.target))
            if not item.target.is_dir():
                raise Error(f'{item.key}: installed copy directory is missing')
            source_hash = manager.payload(item)
            copy_hash = fingerprint(item.target, exclude_git=record.get('exclude_git', False), **payload_options(item))
            if item.kind == 'skill' and not (item.target / 'SKILL.md').is_file():
                raise Error(f'{item.key}: collected skill requires SKILL.md')
            baseline = record['hash']
            conflict = source_hash != baseline and copy_hash != baseline and source_hash != copy_hash
            changed = copy_hash != baseline and copy_hash != source_hash
            left = tree(item.source, exclude_git=record.get('exclude_git', False), **payload_options(item))
            right = tree(item.target, exclude_git=record.get('exclude_git', False), **payload_options(item))
            compare = ['git', 'difftool', '--no-index', '--', str(item.source), str(item.target)]
            command = ("& " + ' '.join("'" + part.replace("'", "''") + "'" for part in compare)
                       if os.name == 'nt' else shlex.join(compare))
            report = {'item': item.key, 'source': str(item.source), 'copy': str(item.target),
                      'baseline_hash': baseline, 'source_hash': source_hash, 'copy_hash': copy_hash,
                      'changed': changed, 'stale': copy_hash == baseline and source_hash != baseline,
                      'conflict': conflict, 'changes': sorted(p for p in left.keys() | right.keys() if left.get(p) != right.get(p)),
                      'compare': compare,
                      'compare_command': command}
            result.append(Collection(item, {**record, **({'preserve_symlinks': item.preserve_symlinks} if item.kind == 'directory' else {})}, source_hash, copy_hash, report))
    return result


def selected_writes(plans):
    """Coalesce identical overlapping exports and reject competing copy contents."""
    writes = []
    for plan in sorted((p for p in plans if p.report['changed']), key=lambda p: len(p.item.source.parts)):
        for other in writes:
            if not overlaps(plan.item.source, other.item.source):
                continue
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
                if write.record.get('exclude_git') and suffix.parts[:1] == ('.git',):
                    return path
                return write.item.target / suffix
        return path

    for key, record in records.items():
        if record.get('mode') != 'link' or record.get('detached'):
            continue
        source = Path(record['source'])
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
            if os.name != 'nt':
                scan(candidate, source_relative=logical, exclude_git=exclude_git,
                     allow_symlinks=bool(payload_options(record)))
            else:
                fingerprint(candidate, exclude_git=exclude_git)


def validate(manager, plans):
    """Recheck source and copy observations before and after temporary staging."""
    manager.state.ready()
    for plan in plans:
        if manager.payload(plan.item) != plan.source_hash:
            raise Error(f'{plan.item.key}: source changed during collection; retry after inspection')
        saved_path(str(plan.item.target))
        if fingerprint(plan.item.target, exclude_git=plan.record.get('exclude_git', False), **payload_options(plan.item)) != plan.copy_hash:
            raise Error(f'{plan.item.key}: copy changed during collection; retry after inspection')
    guard_links(selected_writes(plans), manager.state.data['items'])


def collect(manager, source, plans):
    """Replace changed payload children as one source group, leaving its .git intact.

    Temporary stages and retained backups live beside the source root so they
    never become source payload or Git publication content. The durable journal
    precedes mutations; baseline records commit only after both sides are checked.
    """
    writes = selected_writes(plans)
    validate(manager, plans)
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
            names = {p.name for p in item.source.iterdir()} | {p.name for p in item.target.iterdir()}
            if plan.record.get('exclude_git'):
                names.discard('.git')
            modes.append({'target': str(item.source), 'before': stat.S_IMODE(item.source.stat().st_mode),
                          'after': stat.S_IMODE(item.target.stat().st_mode)})
            for name in sorted(names):
                target, incoming = item.source / name, item.target / name
                policy = payload_options(item)
                if policy:
                    policy['source_relative'] = str(Path(item.relative) / name)
                before, after = observation(target, **policy), observation(incoming, **policy)
                if before == after:
                    continue
                index = str(len(entries))
                stage, backup = scratch / 'stages' / index, scratch / 'backups' / index
                if exists(incoming):
                    copy_payload(incoming, stage, **policy)
                    if observation(stage, **policy) != after:
                        raise Error(f'{item.key}: copy changed while staging')
                entries.append({'target': str(target), 'stage': str(stage), 'backup': str(backup),
                                'before': before, 'after': after,
                                **({'preserve_symlinks': True, 'relative': policy['source_relative']} if policy else {})})
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
            if exists(target):
                (replace_link_entry if policy else os.replace)(target, entry['backup'])
            if entry['after']['kind'] != 'missing':
                (replace_link_entry if policy else os.replace)(entry['stage'], target)
        for mode in modes:
            (chmod_directory if any(p.item.preserve_symlinks for p in plans) else os.chmod)(mode['target'], mode['after'])
        for entry in entries:
            if observation(Path(entry['target']), **payload_options(entry)) != entry['after']:
                raise Error('Source changed before collection state commit')
        for plan in plans:
            if fingerprint(plan.item.target, exclude_git=plan.record.get('exclude_git', False), **payload_options(plan.item)) != plan.copy_hash:
                raise Error(f'{plan.item.key}: copy changed before collection state commit')
            current = manager.payload(plan.item)
            if plan.report['changed'] and current != plan.copy_hash:
                raise Error(f'{plan.item.key}: source changed before collection state commit')
            if current == plan.copy_hash:
                state.data['items'][plan.item.key] = {**plan.record, 'hash': plan.copy_hash}
        state.data['pending'] = None
        try:
            state.save()
        except Exception:
            state.data['items'] = old_items
            state.data['pending'] = journal if scratch else None
            raise
    except Exception:
        if state.path.exists():
            state.data = json.loads(state.path.read_text(encoding='utf-8'))
        pending = state.data.get('pending')
        if pending and pending.get('operation') == 'copy-collection':
            recover(state)
        elif scratch and exists(scratch):
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
        if not isinstance(entry, dict) or set(entry) - {'preserve_symlinks', 'relative'} != {'target', 'stage', 'backup', 'before', 'after'}:
            raise Error('Invalid copy collection recovery entry')
        policy = payload_options(entry)
        target, stage, backup = [saved_path(entry[k]) for k in ('target', 'stage', 'backup')]
        if (root not in target.parents or target.relative_to(root).parts[0] == '.git'
                or any(overlaps(target, p) for p in targets)
                or stage != scratch / 'stages' / str(index) or backup != scratch / 'backups' / str(index)):
            raise Error('Invalid copy collection recovery paths')
        targets.append(target)
        for key in ('before', 'after'):
            observed = entry[key]
            if (not isinstance(observed, dict) or observed.get('kind') not in (('file', 'directory', 'missing', 'link') if policy else ('file', 'directory', 'missing'))
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
        if exists(backup) and observation(target, **policy) != entry['before']:
            if exists(target):
                (remove_link_entry if policy else remove)(target)
            # Keep the original backup through interrupted restoration attempts.
            if exists(stage):
                (remove_link_entry if policy else remove)(stage)
            copy_payload(backup, stage, **policy)
            (replace_link_entry if policy else os.replace)(stage, target)
        elif entry['before'] == {'kind': 'missing'} and exists(target):
            (remove_link_entry if policy else remove)(target)
    for mode in journal['modes']:
        (chmod_directory if any(e.get('preserve_symlinks') for e in journal['files']) else os.chmod)(mode['target'], mode['before'])
    state.data['pending'] = None
    state.save()
