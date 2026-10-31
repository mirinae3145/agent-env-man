"""Copy a Claude Code profile's reusable state into a new, independent root.

Copied: every settings field outside AEM-generated hook groups (env values
included), the instruction entry, output styles, skill links and hook scripts.
Credentials, sessions, history and plugin data are never read, and installed
plugins are listed but not copied.
Links are recreated against their own targets, so the copy never points back
into the source profile, and strings that name the source root are rewritten
to the new root. Hook groups AEM generated are skipped: they name the source's
agent, so the new profile gets its own once it is registered and applied.
"""

from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile

from .hooks import generated
from .model import Error, absolute, overlaps
from .profile_compare import CLAUDE, Profile, _hook_events, _normalize, _read_json, _target, compare


@dataclass
class Plan:
    source: Profile
    target: Path
    mode: int
    settings: dict | None
    links: dict  # relative path -> link target
    files: dict  # relative path -> (bytes, mode)
    skipped: list  # (item, reason)
    sets: list
    install: list  # product CLI invocations that would install the plugins; never run


def _without_aem(group):
    """The group with AEM-generated handlers removed; None when nothing else is left in it."""
    handlers = group.get('hooks', [])
    kept = [hook for hook in handlers if not (isinstance(hook, dict) and generated(hook.get('command', '')))]
    if len(kept) == len(handlers):
        return group
    return {**group, 'hooks': kept} if kept else None


def _no_constant(name):
    raise ValueError(f'{name} is not valid JSON')


def _json(value, level=0):
    """JSON text indented like json.dumps(indent=2), writing Decimal numbers with their exact digits."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)) and value:
        inner, outer = '  ' * (level + 1), '  ' * level
        items = ([json.dumps(key, ensure_ascii=False) + ': ' + _json(item, level + 1) for key, item in value.items()]
                 if isinstance(value, dict) else [_json(item, level + 1) for item in value])
        opening, closing = ('{', '}') if isinstance(value, dict) else ('[', ']')
        return opening + '\n' + inner + (',\n' + inner).join(items) + '\n' + outer + closing
    return json.dumps(value, ensure_ascii=False)


def _assign(document, spec):
    field, separator, raw = spec.partition('=')
    keys = field.split('.')
    if not separator or not all(keys) or keys[0] == 'hooks':
        raise Error(f'--set expects FIELD=VALUE outside hooks: {spec}')
    try:
        value = json.loads(raw, parse_float=Decimal, parse_constant=_no_constant)
    except ValueError:
        value = raw
    node = document
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise Error(f'--set {field}: {key} is not an object')
    node[keys[-1]] = value
    return field


def _link(path, source, target):
    """Absolute link target with the source root replaced; relative links are resolved first."""
    return _normalize(_target(path), source.root, target)


def _text(data, source, target):
    try:
        return _normalize(data.decode('utf-8'), source.root, target).encode('utf-8')
    except UnicodeDecodeError:
        return data


def _leave_to_aem(path, relative, managed, skipped):
    """AEM re-creates what it installed; copying it would make the new profile's apply a conflict."""
    if os.path.normpath(path) in managed:
        skipped.append((relative.as_posix(), 'installed by AEM; run aem apply for the target'))
        return True
    return False


def _entries(directory, relative, source, target, links, skipped, managed):
    for entry in sorted(directory.iterdir()):
        if _leave_to_aem(entry, relative / entry.name, managed, skipped):
            continue
        if entry.is_symlink():
            links[relative / entry.name] = _link(entry, source, target)
        else:
            skipped.append(((relative / entry.name).as_posix(), 'not a link'))


def _plugin_install(source, target, skipped):
    """Product CLI steps that would reinstall the source's user-scope plugins in the target.

    Plugins belong to the product CLI, so nothing here is executed; the steps are
    returned for the user to run. The marketplace sources come from the source
    profile's registry, and a plugin whose marketplace is unknown cannot be installed.
    """
    plugins = [(name, install) for name, installs in (_read_json(source.root / 'plugins' / 'installed_plugins.json') or {}).get('plugins', {}).items()
               for install in installs if isinstance(install, dict) and install.get('scope', 'user') == 'user']
    if not plugins:
        return []
    registry = _read_json(source.root / 'plugins' / 'known_marketplaces.json') or {}
    env = {'CLAUDE_CONFIG_DIR': str(target)}
    adds, installs = {}, []
    for name, install in plugins:
        marketplace = name.partition('@')[2]
        entry = registry.get(marketplace, {}).get('source', {})
        argument = {'github': entry.get('repo'), 'directory': entry.get('path'), 'git': entry.get('url')}.get(entry.get('source'))
        if not argument:
            skipped.append((f'plugins/{name}', 'marketplace source unknown; add the marketplace and install it by hand'))
            continue
        adds.setdefault(marketplace, ['claude', 'plugin', 'marketplace', 'add', _normalize(argument, source.root, target)])
        installs.append(['claude', 'plugin', 'install', name, '--scope', 'user'])
    skipped.append(('plugins', f'{len(plugins)} installed plugin(s) are not copied; run the listed steps with the product CLI'))
    return [{'env': env, 'args': args} for args in [*adds.values(), *installs]]


def plan(source, target, sets=(), managed=frozenset()):
    target = absolute(str(target))
    if overlaps(target, source.root.resolve()):
        raise Error(f'Target {target} overlaps the source profile; use an independent root')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise Error(f'Target {target} already exists and is not empty')
    links, files, skipped = {}, {}, []

    settings, fields = _read_json(source.root / CLAUDE.hook_name), []
    if settings is not None or sets:
        settings, owned, kept = settings or {}, 0, {}
        hooks = _hook_events(settings, source.root / CLAUDE.hook_name)
        settings.pop('hooks', None)
        for event, groups in hooks.items():
            remaining = [_without_aem(group) for group in groups]
            owned += sum(kept is not group for kept, group in zip(remaining, groups))
            mine = [group for group in remaining if group is not None]
            if mine:
                kept[event] = mine
        if kept:
            settings['hooks'] = kept
        settings = _normalize(settings, source.root, target)
        if owned:
            skipped.append(('hooks', f'{owned} AEM-generated hook group(s); register the target and run aem apply to recreate them'))
        fields = [_assign(settings, spec) for spec in sets]

    if source.skills.is_dir():
        _entries(source.skills, Path('skills'), source, target, links, skipped, managed)
    entry = source.root / CLAUDE.entry_name
    if _leave_to_aem(entry, Path(CLAUDE.entry_name), managed, skipped):
        pass
    elif entry.is_symlink():
        links[Path(CLAUDE.entry_name)] = _link(entry, source, target)
    elif entry.is_file():
        files[Path(CLAUDE.entry_name)] = (_text(entry.read_bytes(), source, target), entry.stat().st_mode & 0o777)
    styles = source.root / 'output-styles'
    if _leave_to_aem(styles, Path('output-styles'), managed, skipped):
        pass
    elif styles.is_symlink():
        links[Path('output-styles')] = _link(styles, source, target)
    elif styles.is_dir():
        _entries(styles, Path('output-styles'), source, target, links, skipped, managed)
    hook_dir = source.root / 'hooks'
    if hook_dir.is_dir() and not hook_dir.is_symlink():
        for script in sorted(hook_dir.iterdir()):
            relative = Path('hooks') / script.name
            if _leave_to_aem(script, relative, managed, skipped):
                continue
            if script.is_symlink():
                links[relative] = _link(script, source, target)
            elif script.is_file():
                files[relative] = (_text(script.read_bytes(), source, target), script.stat().st_mode & 0o777)

    install = _plugin_install(source, target, skipped)
    return Plan(source, target, source.root.stat().st_mode & 0o777, settings, links, files, skipped, fields, install)


def apply(plan):
    """Write the plan into a staging folder beside the target, then move it into place."""
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.aem-copy-', dir=plan.target.parent))
    try:
        staging.chmod(plan.mode)
        if plan.settings is not None:
            written = staging / CLAUDE.hook_name
            written.write_text(_json(plan.settings) + '\n', encoding='utf-8')
            original = plan.source.root / CLAUDE.hook_name
            # Settings can hold secrets in env, so the copy keeps the source file's permissions.
            written.chmod(original.stat().st_mode & 0o777 if original.is_file() else 0o600)
        for relative, (data, mode) in plan.files.items():
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            (staging / relative).write_bytes(data)
            (staging / relative).chmod(mode)
        for relative, destination in plan.links.items():
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(destination, staging / relative)
        if plan.target.exists():
            plan.target.rmdir()
        staging.rename(plan.target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def report(plan, applied):
    """Describe the plan; after writing, include a read-only comparison against the source."""
    result = {'source': {'name': plan.source.name, 'root': str(plan.source.root)},
              'target': str(plan.target), 'applied': applied,
              'settings': plan.settings is not None, 'set': plan.sets,
              'links': sorted(path.as_posix() for path in plan.links),
              'files': sorted(path.as_posix() for path in plan.files),
              'skipped': [{'item': item, 'reason': reason} for item, reason in plan.skipped],
              'plugin_steps': plan.install}
    if applied:
        comparison = compare(plan.source, Profile(plan.target.name, plan.target, plan.target / 'skills'), expect=plan.sets)
        different = [{'section': section, **item} for section, items in comparison['sections'].items()
                     for item in items if item['status'] == 'different']
        # Plugins, hook groups and AEM-installed links the copy leaves out show up as present only in the source.
        left = {item for item, _ in plan.skipped}
        left_out = [item for item in different if item.get('only') == 'left' and (
            item['section'] == 'plugins' or item.get('owner') == 'aem'
            or any(item['item'] == name or item['item'].startswith(name + '/') for name in left))]
        result['verification'] = {'same': comparison['totals']['same'], 'expected': comparison['totals']['expected'],
                                  'not_copied': len(left_out),
                                  'unexpected': [item for item in different if item not in left_out]}
    return result


def render(result):
    lines = [f"{'Copied' if result['applied'] else 'Would copy'} {result['source']['name']} -> {result['target']}"]
    if result['settings']:
        lines.append(CLAUDE.hook_name + (f" (set {', '.join(result['set'])})" if result['set'] else ''))
    lines += [f'link  {path}' for path in result['links']] + [f'file  {path}' for path in result['files']]
    lines += [f"skip  {item['item']}: {item['reason']}" for item in result['skipped']]
    if result['plugin_steps']:
        lines.append('Plugin steps (not run; use the product CLI):')
        lines += ['  ' + ' '.join(f'{key}={shlex.quote(value)}' for key, value in step['env'].items()) + ' ' + shlex.join(step['args'])
                  for step in result['plugin_steps']]
    if result['applied']:
        check = result['verification']
        lines.append(f"verification: same {check['same']}, expected {check['expected']}, "
                     f"not copied {check['not_copied']}, unexpected {len(check['unexpected'])}")
        lines += [f"  different {item['item']}" for item in check['unexpected']]
    else:
        lines.append('Nothing was written; add --write to create the profile.')
    lines.append('Settings are an independent copy; to share fields later, see staged settings for named instances in the AEM docs.')
    return '\n'.join(lines)
