"""Declared scripts registered as native groups, never executed by AEM."""

import base64
from copy import deepcopy
import os
from pathlib import Path
import shlex

from . import hooks
from .model import Error, identifier, relative
from .storage import exists, is_reparse, observation, saved_path


FIELDS = {'event', 'runtime', 'script', 'args', 'timeout', 'matcher'}


def runtime_path(value):
    # Resolving a venv's interpreter symlink discards its environment.
    if not isinstance(value, str):
        raise Error('Hook runtime paths must be strings')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise Error('Hook runtime path must be absolute or start with ~/')
    return path


def validate_binding(data, adapter):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise Error('Hook binding accepts only ' + ', '.join(sorted(FIELDS)))
    if data.get('event') not in adapter.command_events:
        raise Error(f'{adapter.name}: unsupported command hook event {data.get("event")!r}')
    identifier(data.get('runtime'))
    relative(data.get('script'))
    if '\0' in data['script']:
        raise Error('Hook script path must not contain NUL')
    args = data.get('args', [])
    if not isinstance(args, list) or any(not isinstance(v, str) or '\0' in v for v in args):
        raise Error('Hook args must be an array of literal strings without NUL')
    limit = dict(adapter.hook_timeout_limits).get(data['event'])
    timeout = data.get('timeout', min(10, limit) if limit else 10)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0 or timeout > 2**32 - 1:
        raise Error('Hook timeout must be a positive integer number of seconds')
    if limit and timeout > limit:
        raise Error(f'{adapter.name} {data["event"]}: timeout must not exceed {limit} seconds')
    if 'matcher' in data:
        import re
        if not isinstance(data['matcher'], str) or '\0' in data['matcher']:
            raise Error('Hook matcher must be a literal regular expression')
        try:
            re.compile(data['matcher']) if data['matcher'] != '*' else None
        except re.error as exc:
            raise Error(f'Invalid hook matcher: {exc}') from exc
        if data['event'] in adapter.unmatched_hook_events:
            raise Error(f'{adapter.name} {data["event"]}: matchers are not supported')
    return {**data, 'args': list(args), 'timeout': timeout}


def runtime(config, name):
    value = config.runtimes.get(name)
    if not value:
        raise Error(f'Missing machine runtimes.{name}; bind it with bootstrap --runtime {name}=PATH')
    path = Path(value)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise Error(f'Hook runtime is missing or not executable: {path}')
    return path


def script(path):
    if not path.is_file() or path.is_symlink() or is_reparse(path):
        raise Error(f'Hook script must be a regular file: {path}')
    try:
        path.read_text(encoding='utf-8')
    except UnicodeError as exc:
        raise Error(f'Hook script must be UTF-8: {path}') from exc


def source_script(root, path):
    target = root / relative(path)
    cursor = target
    while cursor != root:
        if cursor.is_symlink() or is_reparse(cursor):
            raise Error(f'Hook source path redirects: {cursor}')
        cursor = cursor.parent
    script(target)
    return target


def guard_revision(git, source, revision, paths):
    for path in paths:
        relative(path)
        tree = git.run(source.path, 'ls-tree', '-z', revision, '--', path).stdout
        if not tree or tree.split(' ', 1)[0] not in ('100644', '100755'):
            raise Error(f'{source.name}: incoming revision removes or redirects hook script {path}; detach first')
        git.run(source.path, 'show', f'{revision}:{path}', strict_utf8=True)


def definition(config, item):
    from .agents import profile
    data = validate_binding(config._hooks[item.source_name]['agents'][item.agent], profile(item.agent))
    executable = runtime(config, data['runtime'])
    marker = hooks.marker(config.path, f'{item.source_name}:{item.agent}', 'personal hook')
    command = profile(item.agent).personal_command(marker, [str(executable), str(item.source), *data['args']])
    group = {'hooks': [{'type': 'command', 'command': command, 'timeout': data['timeout']}]}
    if 'matcher' in data:
        group['matcher'] = data['matcher']
    return marker, data['event'], group


def direct_command(marker, args):
    """Only literal argv is quoted; identity is outside the script's argument list."""
    if os.name == 'nt':
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        command = '$null=' + quote(marker) + '; & ' + ' '.join(map(quote, args)) + '; exit $LASTEXITCODE'
        return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + base64.b64encode(command.encode('utf-16le')).decode('ascii')
    return ': ' + shlex.quote(marker) + '; exec ' + shlex.join(args)


def positions(doc, marker):
    """Recognize the exact generated prefix, including saved commands on another OS."""
    prefixes = (': ' + shlex.quote(marker) + '; exec ',
                "$null='" + marker.replace("'", "''") + "'; & ")
    found = []
    for event, groups in doc.get('hooks', {}).items():
        for index, group in enumerate(groups):
            for handler in group['hooks']:
                command = handler.get('command')
                if not isinstance(command, str):
                    continue
                encoded = 'powershell.exe -NoProfile -NonInteractive -EncodedCommand '
                if command.startswith(encoded):
                    try:
                        command = base64.b64decode(command[len(encoded):], validate=True).decode('utf-16le')
                    except (ValueError, UnicodeError):
                        continue
                if command.startswith(prefixes):
                    found.append((event, index))
                    break
    if len(found) > 1:
        raise Error('Duplicate personal hook identity; reconcile before applying or removing')
    return found


def current(path, marker, event, group):
    doc = hooks.read(saved_path(str(path)))
    found = positions(doc, marker)
    return bool(found) and found[0][0] == event and doc['hooks'][event][found[0][1]] == group


def render(path, marker, event, desired, old, *, adopt=False, replace=False):
    doc = hooks.read(saved_path(str(path)))
    found = positions(doc, marker)
    if found:
        actual_event, index = found[0]
        actual = doc['hooks'][actual_event][index]
        safe = (old and actual_event == old['hook_event'] and actual == old['hook_group']) or (
            actual_event == event and actual == desired and (old or adopt))
        if not safe and not replace:
            raise Error('Existing or locally modified personal hook; use explicit --adopt or --replace')
        if actual_event == event:
            doc['hooks'][event][index] = desired
        else:
            del doc['hooks'][actual_event][index]
            doc['hooks'].setdefault(event, []).append(desired)
    else:
        if old and not replace:
            raise Error('Managed personal hook disappeared; use explicit --replace to restore it')
        doc.setdefault('hooks', {}).setdefault(event, []).append(desired)
    if exists(path) and hooks.read(path) == doc:
        return path.read_bytes()
    return hooks.serialize(path, doc)


def remove_group(doc, record):
    marker, event, group = record.get('hook_marker'), record.get('hook_event'), record.get('hook_group')
    if not isinstance(marker, str) or not isinstance(event, str) or not isinstance(group, dict):
        raise Error('Invalid saved personal hook ownership')
    found = positions(doc, marker)
    if not found or found[0][0] != event or doc['hooks'][event][found[0][1]] != group:
        raise Error('Managed personal hook changed or disappeared; reconcile before removal')
    del doc['hooks'][event][found[0][1]]


def remove(manager, names, *, agent=None, dry_run=False):
    """Catalog-independent selected removal; detach itself never deletes groups."""
    manager.state.ready()
    for name in names:
        identifier(name)
    records = manager.state.data['items']
    selected = {k: r for k, r in records.items() if r.get('kind') == 'personal-hook'
                and r.get('source_name') in names and (agent is None or r.get('agent') == agent)
                and not r.get('removed')}
    if set(names) - {r['source_name'] for r in selected.values()}:
        raise Error('No saved personal hook for the selected name/agent')
    grouped = {}
    updates = {}
    for key, record in selected.items():
        if record.get('detached'):
            raise Error('Detached hook is no longer owned; reconcile manually or explicitly reattach first')
        target = saved_path(record.get('target'))
        if target not in grouped:
            before = observation(target)
            grouped[target] = (deepcopy(hooks.read(target)), before)
        remove_group(grouped[target][0], record)
        updates[key] = dict(record, detached=True, removed=True)
    for target in grouped:
        for key, record in records.items():
            if key in selected or record.get('detached'):
                continue
            from .model import overlaps
            if not overlaps(target, saved_path(record.get('target'))):
                continue
            if record.get('mode') == 'agent-hook' and record['target'] == str(target):
                continue
            from .settings import Settings
            owner = next(r for r in selected.values() if r['target'] == str(target))
            if (record.get('kind') == 'setting' and record.get('mode') == 'settings'
                    and record.get('format') == owner.get('shared_settings_format') == 'json'
                    and record.get('target') == str(target)):
                Settings(manager).check_hook_ownership(record, saved=True)
                continue
            raise Error(f'Hook removal overlaps {key}')
    from .settings import transaction
    writes = [(p, hooks.serialize(p, doc), before)
              for p, (doc, before) in grouped.items()]
    transaction(manager.state, writes, updates, dry_run=dry_run)
    return [{'item': key, 'action': 'would-remove' if dry_run else 'removed', 'target': r['target']}
            for key, r in selected.items()]
