"""Explicit local catalog delivery with a common baseline and recoverable writes.

Consumers always read the managed file. External availability never selects a
fallback, and neither direction implicitly starts a synchronization service.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib

import tomlkit

from .model import Config, Error, overlaps
from .settings import regular, transaction
from .storage import exists, observation


def protect_storage(config, state):
    protected = (config.catalog_path.parent, config.catalog_copy_source)
    for record in state.data['items'].values():
        if any(overlaps(Path(record['target']), p) for p in protected):
            raise Error('Catalog copy or original overlaps a saved installation target')


def read(path):
    regular(path)
    before = observation(path)
    content = path.read_bytes()
    if observation(path) != before:
        raise Error(f'Catalog changed while reading: {path}')
    return content, before


def binding(config):
    return {'source': str(config.catalog_copy_source), 'copy': str(config.catalog_path)}


def baseline(config, state):
    record = state.data.get('catalog_copy')
    if (not isinstance(record, dict) or any(record.get(k) != v for k, v in binding(config).items())
            or not isinstance(record.get('hash'), str)):
        raise Error('Catalog copy has no matching common baseline; inspect its binding and preserve both files')
    return record


def candidate(config, state, content):
    from .catalog import validate
    document = tomlkit.parse(content.decode('utf-8'))
    result = Config(config.path, document=config.doc, catalog_document=document)
    validate(result, state)
    return result


def commit(config, state, writes, record, guards):
    transaction(state, writes, {}, state_updates={'catalog_copy': record},
                guards=guards, operation='catalog-copy')


@contextmanager
def prepare(config, state):
    """Validate before binding publication; callers add their bootstrap preflight.

    Reusing a binding consumes the editable copy even if the original is absent.
    A rebind may replace only an unchanged owned copy, never an unowned file.
    The file, machine binding, and baseline commit through one rollback journal.
    """
    state.ready()
    protect_storage(config, state)
    machine_before = observation(config.path)
    old = state.data.get('catalog_copy')
    same = isinstance(old, dict) and all(old.get(k) == v for k, v in binding(config).items())
    regular(config.catalog_path, missing=True)
    copy_before = observation(config.catalog_path)
    writes, guards = [], []
    if same:
        baseline(config, state)
        content, copy_before = read(config.catalog_path)
        prepared = candidate(config, state, content)
        record = old
        guards.append((config.catalog_path, copy_before))
    else:
        if copy_before['kind'] != 'missing':
            if (not isinstance(old, dict) or old.get('copy') != str(config.catalog_path)
                    or hashlib.sha256(config.catalog_path.read_bytes()).hexdigest() != old.get('hash')):
                raise Error('Existing catalog copy is unowned or modified; preserve and reconcile it before rebinding')
        content, source_before = read(config.catalog_copy_source)
        prepared = candidate(config, state, content)
        record = {**binding(config), 'hash': hashlib.sha256(content).hexdigest()}
        writes.append((config.catalog_path, content, copy_before))
        guards.append((config.catalog_copy_source, source_before))
    report = {**binding(config), 'entry': str(config.catalog_path), 'status': 'prepared'}
    yield prepared, report
    writes.append((config.path, tomlkit.dumps(prepared.doc).encode('utf-8'), machine_before))
    commit(prepared, state, writes, record, guards)


def inspect(config, state):
    report = {'entry': str(config.catalog_path), 'checkout': None, 'repository': None,
              **binding(config), 'automation': state.data.get('catalog_automation', {})}
    try:
        regular(config.catalog_path)
        config.catalog()
        report['status'] = 'ready'
        report['copy_hash'] = hashlib.sha256(read(config.catalog_path)[0]).hexdigest()
    except (Error, OSError, ValueError) as exc:
        report.update(status='unavailable', error=str(exc))
    try:
        regular(config.catalog_copy_source)
        report.update(source_available=True, source_hash=hashlib.sha256(read(config.catalog_copy_source)[0]).hexdigest())
    except (Error, OSError, ValueError) as exc:
        report.update(source_available=False, source_error=str(exc))
    try:
        record = baseline(config, state)
        report['baseline_hash'] = record['hash']
        if 'copy_hash' in report:
            report['copy_modified'] = report['copy_hash'] != record['hash']
        if 'source_hash' in report:
            report['source_modified'] = report['source_hash'] != record['hash']
        if 'copy_hash' in report and 'source_hash' in report:
            report['conflict'] = (report['copy_modified'] and report['source_modified']
                                  and report['copy_hash'] != report['source_hash'])
    except Error as exc:
        report['baseline_error'] = str(exc)
    return report


def command(config, state, args):
    action = args.catalog_command
    if action == 'locate':
        path = config.catalog_copy_source if getattr(args, 'source', False) else config.catalog_path
        if not getattr(args, 'source', False):
            regular(path)
        return {'entry': str(path), 'checkout': None, 'repository': None, **binding(config)}, False
    if action == 'status':
        return inspect(config, state), False
    state.ready()
    if action == 'publish':
        if not getattr(args, 'from_copy', False):
            raise Error('Local catalog publication requires explicit --from-copy')
        if args.message is not None:
            raise Error('--message is only supported for Git catalog publication')
    report = {'entry': str(config.catalog_path), **binding(config), 'status': 'planned'}
    try:
        record = baseline(config, state)
        source_content, source_before = read(config.catalog_copy_source)
        copy_content, copy_before = read(config.catalog_path)
        source_hash = hashlib.sha256(source_content).hexdigest()
        copy_hash = hashlib.sha256(copy_content).hexdigest()
        source_changed, copy_changed = source_hash != record['hash'], copy_hash != record['hash']
        report.update(baseline_hash=record['hash'], source_hash=source_hash, copy_hash=copy_hash,
                      conflict=source_changed and copy_changed and source_hash != copy_hash,
                      compare=['git', 'diff', '--no-index', '--', str(config.catalog_copy_source), str(config.catalog_path)])
        if report['conflict']:
            raise Error('Catalog source and copy changed since their common baseline; reconcile both files and retry')
        publishing = action == 'publish'
        incoming, target = ((copy_content, config.catalog_copy_source) if publishing
                            else (source_content, config.catalog_path))
        incoming_hash = copy_hash if publishing else source_hash
        changed = (copy_changed if publishing else source_changed) and source_hash != copy_hash
        report.update(changed=changed, stale=source_changed and not copy_changed,
                      local_edits=copy_changed and not source_changed)
        # A source-only change must not export a stale copy, nor may update
        # erase copy-only edits. Validate exactly the content the command accepts.
        candidate(config, state, incoming if changed or source_hash == copy_hash else copy_content)
        if getattr(args, 'dry_run', False):
            return report, False
        writes = []
        guards = [(config.catalog_copy_source, source_before), (config.catalog_path, copy_before)]
        if changed:
            before = source_before if publishing else copy_before
            writes.append((target, incoming, before))
            guards = [(p, obs) for p, obs in guards if p != target]
        if changed or source_hash == copy_hash:
            commit(config, state, writes, {**binding(config), 'hash': incoming_hash}, guards)
        report['status'] = ('published' if publishing else 'updated') if changed else 'unchanged'
        if publishing:
            report.update(collection_complete=True, transport_complete=False)
        return report, False
    except (Error, OSError, ValueError) as exc:
        report.update(status='failed', error=str(exc))
        return report, True
