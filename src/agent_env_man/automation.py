"""Device-level orchestration; full runs use one clock and a fresh installed CLI."""
import time

from .model import Error
from .payload_links import unsupported_reason
from .updates import TRIGGERS, policy_fields, run_updates, run_settings_updates
from . import catalog, self_update

MODES = ('off', 'policies', 'full')
FIELDS = (('mode', 'automation'), ('trigger', 'automation_trigger'),
          ('min_interval', 'automation_interval'), ('timeout', 'automation_timeout'),
          ('skip_unsupported', 'automation_skip_unsupported'))


def policy(value):
    if not isinstance(value, dict) or set(value) - {'mode', 'trigger', 'min_interval', 'timeout', 'skip_unsupported'}:
        raise Error('automation accepts only mode, trigger, min_interval, timeout, and skip_unsupported')
    if value.get('mode', 'policies') not in MODES:
        raise Error('automation.mode must be off, policies, or full')
    if not isinstance(value.get('skip_unsupported', False), bool):
        raise Error('automation.skip_unsupported must be Boolean')
    fields = {k: v for k, v in value.items() if k not in ('mode', 'skip_unsupported')}
    return {'mode': value.get('mode', 'policies'), 'skip_unsupported': value.get('skip_unsupported', False),
            **policy_fields({'trigger': ['shell-start', 'agent-start'], 'min_interval': 3600, 'timeout': 30}, 'automation defaults'),
            **policy_fields(fields, 'automation')}


def set_options(document, args):
    values = {field: getattr(args, option) for field, option in FIELDS if getattr(args, option, None) is not None}
    if values:
        document.setdefault('automation', {}).update(values)
        policy(document['automation'])
    return bool(values)


def runtime(settings):
    self_update.validate(settings)
    if any(k not in settings for k in ('python', 'uv', 'tool_dir', 'bin_dir')):
        raise Error('Full automation requires runtime registration through scripts/setup.py')


def result_path(config):
    return config.state_dir / 'automation.json'


def status(config):
    return {'policy': policy(config.doc.get('automation', {})),
            'last_attempt': self_update.read_result(result_path(config))}


def schedule(config, trigger, *, dry_run=False):
    settings = dict(config.doc.get('self_update', {}))
    runtime(settings)
    current = time.time()
    previous = self_update.read_result(result_path(config))
    if trigger not in config.automation['trigger']:
        return {'mode': 'full', 'status': 'not-triggered'}
    if current - previous.get('time', 0) < config.automation['min_interval']:
        return {'mode': 'full', 'status': 'throttled'}
    if dry_run:
        return {'mode': 'full', 'status': 'planned', 'policy': config.automation,
                'stages': ['tool', 'catalog', 'content']}
    return self_update.launch(config, settings, {'mode': 'full', 'time': current, 'trigger': trigger, 'binding': self_update.full_binding(config.doc)},
                              filename='automation.json', extra={'full': True,
                              'saved_automation': dict(config.doc.get('automation', {}))})


def run(manager, trigger, *, dry_run=False):
    if trigger not in TRIGGERS:
        raise Error(f'Unknown automatic update trigger: {trigger}')
    config, state = manager.config, manager.state
    mode = config.automation['mode']
    if mode == 'off':
        return {'mode': mode, 'status': 'disabled', 'outcomes': [], 'failed': False}
    state.ready()
    if mode == 'full':
        report = schedule(config, trigger, dry_run=dry_run)
        if dry_run and report['status'] == 'planned':
            report['content'], failed = full_content(manager, config.automation['timeout'], dry_run=True)
            report['failed'] = failed
            if failed:
                report['status'] = 'failed'
        return report
    result = {'mode': mode, 'outcomes': [], 'failed': False}
    try:
        result['self_update'] = self_update.schedule(config, automatic=True, dry_run=dry_run)
    except (Error, OSError, ValueError) as exc:
        result['self_update'] = {'status': 'failed', 'error': str(exc)}
    try:
        result['catalog_update'], failed = catalog.run_auto(config, state, trigger, dry_run=dry_run)
        if failed:
            raise Error('Automatic catalog update failed; skill and settings updates skipped')
        if result['catalog_update']['status'] == 'updated':
            from .model import Config
            from .manager import Manager
            manager = Manager(Config(config.path), state)
        result['outcomes'], result['failed'] = run_updates(manager, trigger, dry_run=dry_run)
        result['settings_updates'], failed = run_settings_updates(manager, trigger, dry_run=dry_run)
        result['failed'] |= failed
    except (Error, OSError, ValueError) as exc:
        result.update(failed=True, error=str(exc))
        result.setdefault('catalog_update', {'status': 'failed', 'error': str(exc)})
    return result


def full_content(manager, timeout, *, dry_run=False):
    """Prepare/update eligible sources, then apply only after delivery succeeds.

    Explicit manual policies remain excluded. Instruction components sharing
    an agent are excluded together if any component is detached, preventing
    hook selection from implicitly expanding into a preserved installation.
    Shared Git checkouts retain their ordinary cross-consumer link effects.
    """
    policies = {**manager.config.full_update_policies(),
                **manager.config.settings_update_policies(full=True)}
    sources, items, excluded = [], [], []
    for name, source in manager.config.sources.items():
        if name in manager.config._hooks:
            excluded.append({'source': name, 'reason': 'personal-hook-requires-explicit-apply'})
            continue
        if name in policies and policies[name]['trigger'] == ['manual']:
            excluded.append({'source': name, 'reason': 'manual'})
            continue
        declarations = manager.config.declarations(source)
        detached_agents = {item.agent for item in declarations if item.kind not in ('skill', 'directory')
                           and manager.state.data['items'].get(item.key, {}).get('detached')}
        selected = [item.key for item in declarations
                    if not manager.state.data['items'].get(item.key, {}).get('detached')
                    and (item.kind in ('skill', 'directory') or item.agent not in detached_agents)]
        if not selected:
            excluded.append({'source': name, 'reason': 'detached'})
            continue
        unsupported = [(item.key, unsupported_reason(item)) for item in declarations if item.key in selected]
        unsupported = [(key, reason) for key, reason in unsupported if reason]
        if unsupported and manager.config.automation['skip_unsupported']:
            excluded.extend({'source': name, 'item': key, 'reason': reason} for key, reason in unsupported)
            continue
        sources.append(name)
        items.extend(selected)
    report = {'sources': sources, 'excluded': excluded}
    if not sources:
        return {**report, 'status': 'skipped'}, False
    try:
        manager.require_items_supported(manager.selected(items))
        manager.require_sources_supported(sources)
    except (Error, OSError, ValueError) as exc:
        return {**report, 'status': 'failed', 'error': str(exc)}, True
    if dry_run:
        return {**report, 'status': 'planned', 'network': False,
                'notice': 'Local catalog only; content is checked again after catalog update.'}, False
    report['prepare'], failed = manager.prepare_skills(sources, timeout=timeout, defer_payloads=True)
    if failed:
        return {**report, 'status': 'failed'}, True
    report['update'], failed = manager.update(sources, timeout=timeout, prepare_settings=True)
    if failed:
        return {**report, 'status': 'failed'}, True
    report['apply'] = manager.apply(items, timeout=timeout)
    return {**report, 'status': 'completed'}, False


def complete(manager, token):
    """Continue a worker-authorized run using the currently installed package."""
    config, state = manager.config, manager.state
    saved = self_update.read_result(result_path(config))
    if (config.automation['mode'] != 'full' or saved.get('token') != token
            or saved.get('status') != 'continuing'
            or saved.get('binding') != self_update.full_binding(config.doc)):
        raise Error('No matching full automation continuation')
    state.ready()
    report = dict(saved)
    report['stages'] = dict(saved.get('stages', {}))
    try:
        if config.catalog_source:
            from types import SimpleNamespace
            outcome, failed = catalog.command(config, state, SimpleNamespace(
                catalog_command='update', timeout=config.automation['timeout']))
            report['stages']['catalog'] = outcome
            if failed:
                raise Error('Catalog stage failed; content stage skipped')
            from .model import Config
            from .manager import Manager
            manager = Manager(Config(config.path), state)
        else:
            report['stages']['catalog'] = {'status': 'skipped', 'reason': 'local-or-unbound'}
        report['stages']['content'], failed = full_content(manager, config.automation['timeout'])
        report['status'] = 'failed' if failed else 'completed'
    except (Error, OSError, ValueError) as exc:
        report.update(status='failed', error=str(exc))
        report['stages'].setdefault('content', {'status': 'skipped'})
    report['finished'] = time.time()
    self_update.write_json(result_path(config), report)
    return report, report['status'] == 'failed'
