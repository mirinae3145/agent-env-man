"""Release-tag updates; the copied worker runs outside the uv tool environment.

The worker and its copied locking/official-skill helpers use only the standard library.
Its stdin is a lifetime pipe: replacement starts only after the requesting AEM
process exits, including releasing its configuration and installation locks.
"""
import atexit
from importlib.metadata import version
import json
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

if __package__:
    from .official_skills import check as check_official_skills
else:
    from official_skills import check as check_official_skills

MODES = ('off', 'compatible', 'breaking')
REPOSITORY = 'https://github.com/mirinae3145/agent-env-man.git'
INTERVAL = 86400
TIMEOUT = 300
_children = []


def validate(settings):
    if not isinstance(settings, dict) or set(settings) - {'mode', 'repository', 'python', 'uv', 'tool_dir', 'bin_dir'}:
        raise ValueError('self_update accepts only mode, repository, python, uv, tool_dir, and bin_dir')
    if settings.get('mode', 'off') not in MODES:
        raise ValueError('self_update.mode must be off, compatible, or breaking')
    repository = settings.get('repository', REPOSITORY)
    if not isinstance(repository, str) or not repository or repository.startswith('-'):
        raise ValueError('self_update.repository must be a Git URL or absolute local path')
    if not (Path(repository).is_absolute() or repository.startswith(('https://', 'ssh://'))
            or re.fullmatch(r'git@[^:]+:.+', repository)):
        raise ValueError('Use HTTPS, SSH, or an absolute local release repository')
    for field in ('python', 'uv', 'tool_dir', 'bin_dir'):
        if field in settings and (not isinstance(settings[field], str) or not Path(settings[field]).is_absolute()):
            raise ValueError(f'self_update.{field} must be an absolute path')
    if settings.get('mode', 'off') != 'off' and any(field not in settings for field in ('python', 'uv', 'tool_dir', 'bin_dir')):
        raise ValueError('Register the self-update runtime with scripts/setup.py first')
    if 'python' in settings and 'tool_dir' in settings:
        interpreter, tools = Path(settings['python']).absolute(), Path(settings['tool_dir']).resolve()
        if interpreter == tools or tools in interpreter.parents or tools in interpreter.resolve().parents:
            raise ValueError('The updater Python must be outside the uv tools directory')
    return settings


def release_version(value):
    """Return an ordering key for final or Python a/b/rc releases.

    Keep this parser standard-library-only for the copied update worker.
    Final releases sort after every prerelease of the same base version.
    An omitted prerelease subversion is zero, matching Python packaging.
    Development, post, local, and other noncanonical versions are excluded.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)(0|[1-9]\d*)?)?', value)
    if not match:
        return None
    major, minor, patch, pre, number = match.groups()
    return (int(major), int(minor), int(patch),
            {'a': 0, 'b': 1, 'rc': 2, None: 3}[pre], int(number or 0))


def tag_version(value):
    """Convert supported Git version spellings to Python package notation.

    Git accepts SemVer-style alpha/beta/rc labels while package metadata
    remains in Python notation. An omitted tag subversion means zero.
    This deliberately does not accept arbitrary SemVer prerelease labels.
    """
    if release_version(value) is not None:
        return value
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))-(alpha|beta|rc)(?:\.(0|[1-9][0-9]*))?', value)
    if not match:
        return None
    base, label, number = match.groups()
    return base + {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}[label] + (number or '0')


def select_release(output, current, mode):
    """Select newer release tags, preferring peeled annotated-tag commits."""
    baseline = release_version(current)
    if baseline is None:
        raise ValueError('Self-update requires an installed X.Y.Z or X.Y.Z{a|b|rc}[N] release version')
    releases = {}
    preferences = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', parts[0]):
            continue
        revision, ref = parts
        match = re.fullmatch(r'refs/tags/v(.+?)(\^\{\})?', ref)
        package_version = tag_version(match[1]) if match else None
        candidate = release_version(package_version)
        if candidate is None or candidate <= baseline:
            continue
        if mode == 'compatible':
            if baseline[3] != 3:
                # Only the subversion may change within a prerelease series.
                if candidate[:4] != baseline[:4]:
                    continue
            elif candidate[3] != 3 or candidate[:2 if baseline[0] == 0 else 1] != baseline[:2 if baseline[0] == 0 else 1]:
                continue
        if mode == 'off':
            continue
        # Prefer Python tags over equivalent SemVer tags, then explicit zero
        # over bare labels. Peel only the selected spelling's annotated tag.
        preference = (release_version(match[1]) is not None, match[1], bool(match[2]))
        if candidate not in releases or preference > preferences[candidate]:
            preferences[candidate] = preference
            releases[candidate] = {'version': package_version, 'revision': revision}
    return releases[max(releases)] if releases else None


def full_binding(document):
    fields = {key: document.get(key, {}) for key in ('automation', 'self_update')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode('utf-8')).hexdigest()


def result_path(config):
    return config.state_dir / 'self-update.json'


def read_result(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Self-update result must be an object')
    timestamp = value.get('time', 0)
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError('Self-update attempt time must be a finite nonnegative number')
    return value


def write_json(path, value):
    # Also used by the standalone worker, which cannot import package storage.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.aem-self-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def status(config):
    settings = validate(config.doc.get('self_update', {}))
    return {'version': version('agent-env-man'), 'mode': settings.get('mode', 'off'),
            'repository': settings.get('repository', REPOSITORY),
            'runtime_registered': all(k in settings for k in ('python', 'uv', 'tool_dir', 'bin_dir')),
            'last_attempt': read_result(result_path(config))}


def installation_lock(settings):
    """Identify the shared lock without adding entries to uv's tool inventory."""
    if 'tool_dir' not in settings:
        return None
    # Resolve aliases so commands and copied workers sharing one installation
    # agree on its lock. uv treats even hidden children as tool environments.
    tools = Path(settings['tool_dir']).resolve()
    return tools.parent / f'.{tools.name}.aem-update-lock'


def schedule(config, *, automatic=False, mode=None, dry_run=False):
    """Queue replacement after exit; explicit requests bypass the daily throttle.

    A queued result is never reported as a successful installation. Workers
    check their token and saved policy again before any remote access.
    """
    settings = dict(validate(config.doc.get('self_update', {})))
    selected_mode = mode or settings.get('mode', 'off')
    if selected_mode == 'off':
        return {'status': 'disabled'}
    settings['mode'] = selected_mode
    validate(settings)
    previous = read_result(result_path(config))
    current = time.time()
    if automatic and current - previous.get('time', 0) < INTERVAL:
        return {'status': 'throttled'}
    if dry_run:
        return {'status': 'planned', 'mode': selected_mode, 'network': False}
    return launch(config, settings, {'mode': selected_mode, 'time': current}, extra={'automatic': automatic})


def launch(config, settings, attempt, *, filename='self-update.json', extra=None):
    """Persist a request and launch a copied worker on the external interpreter."""
    token = uuid.uuid4().hex
    directory = config.state_dir / 'self-update-worker' / token
    result = config.state_dir / filename
    attempt = {**attempt, 'status': 'queued', 'token': token}
    write_json(result, attempt)
    try:
        required = ('python',) if extra and extra.get('full') and settings.get('mode', 'off') == 'off' else ('python', 'uv')
        for field in required:
            if not Path(settings[field]).is_file():
                raise ValueError(f'Updater {field} is missing; rerun scripts/setup.py')
        directory.mkdir(parents=True, exist_ok=True)
        from .storage import atomic_write
        for name in ('self_update.py', 'process_lock.py', 'official_skills.py', 'link_paths.py'):
            atomic_write(directory / name, Path(__file__).with_name(name).read_bytes())
        request = {'token': token, 'parent_pid': os.getpid(), 'config': str(config.path), 'settings': settings,
                   'saved_settings': dict(config.doc.get('self_update', {})), 'filename': filename, **(extra or {})}
        request_path = directory / 'request.json'
        write_json(request_path, request)
        child = subprocess.Popen([settings['python'], str(directory / 'self_update.py'), str(request_path)],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True, start_new_session=True)
    except (OSError, ValueError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        write_json(result, {**attempt, 'status': 'failed', 'error': str(exc), 'finished': time.time()})
        raise
    _children.append(child)
    return attempt


def close_workers():
    for child in _children:
        if child.stdin:
            child.stdin.close()
    _children.clear()


atexit.register(close_workers)


def git(*arguments, cwd=None):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_SSH_COMMAND='ssh -oBatchMode=yes')
    return subprocess.run(['git', *arguments], cwd=cwd, env=environment, check=True,
                          capture_output=True, text=True, encoding='utf-8', timeout=TIMEOUT).stdout.strip()


def git_url(repository):
    if Path(repository).is_absolute():
        return 'git+' + Path(repository).as_uri()
    if repository.startswith('git@'):
        host, path = repository.split(':', 1)
        return f'git+ssh://{host}/{path}'
    return 'git+' + repository


def tool_environment(settings):
    return dict(os.environ, UV_TOOL_DIR=settings['tool_dir'], UV_TOOL_BIN_DIR=settings['bin_dir'],
                GIT_TERMINAL_PROMPT='0', GIT_SSH_COMMAND='ssh -oBatchMode=yes')


def installed_version(settings):
    listing = subprocess.run([settings['uv'], 'tool', 'list'], env=tool_environment(settings), check=True,
                             capture_output=True, text=True, timeout=TIMEOUT).stdout
    installed = re.search(r'^agent-env-man v(\S+)', listing, re.MULTILINE)
    if installed is None:
        raise ValueError('Registered uv installation is missing; rerun scripts/setup.py')
    return installed[1]


def prepare_release(settings, current):
    """Inspect remote metadata using only a private checkout, without locks."""
    repository = settings.get('repository', REPOSITORY)
    selected = select_release(git('ls-remote', '--tags', repository), current, settings['mode'])
    if selected is None:
        return None
    with tempfile.TemporaryDirectory(prefix='aem-release-') as temporary:
        checkout = Path(temporary)
        git('init', str(checkout))
        git('fetch', '--depth', '1', repository, selected['revision'], cwd=checkout)
        descriptor = git('ls-tree', 'FETCH_HEAD', '--', 'pyproject.toml', cwd=checkout)
        if not descriptor.startswith(('100644 blob ', '100755 blob ')):
            raise ValueError('Release pyproject.toml must be a tracked regular file')
        metadata = tomllib.loads(git('show', 'FETCH_HEAD:pyproject.toml', cwd=checkout))
        project = metadata.get('project', {})
        # Package tools normalize a bare pre label to subversion zero.
        # Accept only this supported equivalence, preserving metadata checks.
        if (not isinstance(project, dict) or project.get('name') != 'agent-env-man'
                or release_version(project.get('version')) != release_version(selected['version'])):
            raise ValueError('Release tag does not match agent-env-man package metadata')
    return selected


def perform(request, records=None, *, prepared=None):
    """Replace under locks, rejecting a plan made for a different installation."""
    settings = validate(request['settings'])
    installed = installed_version(settings)
    if records is not None:
        check_official_skills(records, package_version=installed)
    if prepared is not None and installed != prepared['current']:
        return {'status': 'cancelled', 'reason': 'Installed version changed during release preparation; retry'}
    selected = prepared['selected'] if prepared is not None else prepare_release(settings, installed)
    if selected is None:
        return {'status': 'up-to-date'}
    repository = settings.get('repository', REPOSITORY)
    command = [settings['uv'], 'tool', 'install', '--reinstall', '--python', settings['python'],
               '--from', git_url(repository) + '@' + selected['revision'], 'agent-env-man']
    if records is not None:
        check_official_skills(records, package_version=installed)
    subprocess.run(command, env=tool_environment(settings), check=True, capture_output=True, text=True, timeout=TIMEOUT)
    return {'status': 'updated', **selected}


def wait_for_parent(pid):
    """Wait for OS termination as well as EOF, which can arrive during atexit.

    The child observes reparenting without signalling or probing an unrelated
    process that might reuse the original PID.
    """
    if not pid:
        return True
    deadline = time.monotonic() + TIMEOUT
    while os.getppid() == pid:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def worker_state(request, config, state_dir, parent_exited):
    """Read cancellation gates afresh while holding both operation locks."""
    document = tomllib.loads(config.read_text(encoding='utf-8'))
    if not parent_exited:
        return document, {}, {'status': 'failed', 'error': 'Could not confirm requesting process exit'}
    reason = None
    if document.get('self_update', {}) != request['saved_settings']:
        reason = 'Self-update settings changed'
    elif request.get('automatic') and document.get('automation', {}).get('mode', 'policies') != 'policies':
        reason = 'Automation mode changed'
    elif request.get('full') and document.get('automation', {}) != request['saved_automation']:
        reason = 'Automation settings changed'
    if reason:
        return document, {}, {'status': 'cancelled', 'reason': reason}
    state = json.loads((state_dir / 'state.json').read_text(encoding='utf-8'))
    if state.get('pending') is not None:
        return document, {}, {'status': 'cancelled', 'reason': 'Recovery is pending'}
    return document, state['items'], None


def worker_failure(exc):
    # Git URLs/build logs may contain credentials; never persist their output.
    return {'status': 'failed', 'error': (str(exc) if isinstance(exc, ValueError)
                                        else f'{type(exc).__name__}: release update failed')}


def worker(request_path):
    from process_lock import lock
    request_path = Path(request_path)
    # The pipe also prevents inheriting callback stdout or keeping its host waiting.
    sys.stdin.buffer.read()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    config = Path(request['config'])
    state_dir = config.parent / (config.name + '.state')
    result = state_dir / request.get('filename', 'self-update.json')
    continue_full = False
    refresh_skills = False
    try:
        parent_exited = wait_for_parent(request['parent_pid'])
        prepared = None
        outcome = None
        tool_disabled = request.get('full') and request['settings'].get('mode', 'off') == 'off'
        # Snapshot only the installed version. Remote discovery and metadata
        # fetching do not mutate the registered tool or configuration.
        with lock(installation_lock(request['settings']), timeout=TIMEOUT), lock(state_dir, timeout=TIMEOUT):
            if read_result(result).get('token') != request['token']:
                return
            try:
                _, records, outcome = worker_state(request, config, state_dir, parent_exited)
                if outcome is None:
                    check_official_skills(records, payload=False)
                    if not tool_disabled:
                        settings = validate(request['settings'])
                        current = installed_version(settings)
                        check_official_skills(records, package_version=current)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                outcome = worker_failure(exc)
        if outcome is None and not tool_disabled:
            try:
                prepared = {'current': current, 'selected': prepare_release(settings, current)}
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                outcome = worker_failure(exc)
        # A new request or policy edit may have arrived while preparing. Never
        # install or overwrite a newer result using the initial snapshot.
        with lock(installation_lock(request['settings']), timeout=TIMEOUT), lock(state_dir, timeout=TIMEOUT):
            previous = read_result(result)
            if previous.get('token') != request['token']:
                return
            try:
                document, records, cancellation = worker_state(request, config, state_dir, parent_exited)
                outcome = cancellation or outcome
                if outcome is None:
                    check_official_skills(records, payload=False)
                    outcome = ({'status': 'disabled'} if tool_disabled
                               else perform(request, records, prepared=prepared))
                    continue_full = bool(request.get('full')) and outcome['status'] != 'cancelled'
                    owned_skill = any(record.get('official_skill') and not record.get('detached')
                                      and record.get('agent') in document.get('agents', {}) for record in records.values())
                    refresh_skills = owned_skill and (outcome['status'] in ('updated', 'up-to-date') or continue_full)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                outcome = worker_failure(exc)
            if continue_full or refresh_skills:
                write_json(result, {**previous, 'status': 'continuing' if continue_full else 'queued', 'skill_binding': full_binding(document),
                                    'stages': {'tool': outcome}})
            else:
                write_json(result, {**previous, **outcome, 'finished': time.time()})
        if refresh_skills:
            executable = Path(request['settings']['bin_dir']) / 'aem'
            try:
                process = subprocess.run([str(executable), '--config', str(config), '--json', '_self-skill-refresh',
                                          '--token', request['token'], '--result-file', result.name],
                                         capture_output=True, text=True, timeout=TIMEOUT)
                if process.returncode:
                    raise ValueError('Official skill refresh failed; retry setup --agent codex')
                refresh = {'status': 'completed', **json.loads(process.stdout)}
            except (OSError, ValueError, subprocess.SubprocessError):
                refresh = {'status': 'failed', 'error': 'Official skill refresh failed; retry setup --agent codex'}
            with lock(installation_lock(request['settings']), timeout=TIMEOUT), lock(state_dir, timeout=TIMEOUT):
                latest = read_result(result)
                if latest.get('token') != request['token']:
                    return
                stages = {**latest.get('stages', {}), 'official_skill': refresh}
                if not continue_full or refresh['status'] == 'failed':
                    write_json(result, {**latest, **outcome, 'status': 'failed' if refresh['status'] == 'failed' else outcome['status'],
                                        **({'error': refresh['error']} if refresh['status'] == 'failed' else {}),
                                        'stages': stages, 'finished': time.time()})
                    continue_full = False
                else:
                    write_json(result, {**latest, 'stages': stages})
        if continue_full:
            # Release both locks before the fresh CLI acquires them. Keep a
            # one-use token in the result so retries cannot repeat a continuation.
            executable = Path(request['settings']['bin_dir']) / 'aem'
            try:
                process = subprocess.run([str(executable), '--config', str(config), '_full-run',
                                          '--token', request['token']], capture_output=True)
                failed = process.returncode != 0
            except (OSError, subprocess.SubprocessError):
                failed = True
            if failed:
                with lock(installation_lock(request['settings']), timeout=TIMEOUT), lock(state_dir, timeout=TIMEOUT):
                    latest = read_result(result)
                    if latest.get('token') == request['token'] and latest.get('status') == 'continuing':
                        write_json(result, {**latest, 'status': 'failed', 'error': 'Fresh AEM continuation failed',
                                            'finished': time.time()})
    finally:
        shutil.rmtree(request_path.parent, ignore_errors=True)


if __name__ == '__main__':
    worker(sys.argv[1])
