"""Claude integration through the existing agent-profile boundary with temporary homes."""
import base64
from contextlib import redirect_stdout, redirect_stderr, nullcontext
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import tomlkit

from agent_env_man import agents, hooks, automation, self_update
from agent_env_man.manager import Manager
from agent_env_man.storage import State
from agent_env_man.cli import main
from agent_env_man.model import Config, Error
from test_setup import SetupFixture


class ClaudeIntegration(SetupFixture):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.home / '.claude')})
        env.start()
        self.addCleanup(env.stop)
        self.claude = self.home / '.claude'

    def callback(self, *args, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(['--config', str(self.config), *map(str, args)])
        self.assertEqual(result, code, errors.getvalue())
        return output.getvalue(), errors.getvalue()



    def test_claude_setup_repeat_preserves_settings_and_saved_defaults(self):
        self.claude.mkdir()
        path = self.claude / 'settings.json'
        initial = {'syncClaudeAiPlugins': False, 'syncClaudeAiSkills': False,
                   'permissions': {'allow': ['Read']}, 'hooks': {'SessionStart': [
                       {'hooks': [{'type': 'command', 'command': 'echo user'}]}]}}
        path.write_text(json.dumps(initial))
        self.setup_cli('--agent', 'claude')
        first = path.read_bytes()
        self.setup_cli('--agent', 'claude')
        self.assertEqual(first, path.read_bytes())
        doc = json.loads(first)
        self.assertEqual(doc['permissions'], initial['permissions'])
        self.assertFalse(doc['syncClaudeAiPlugins'])
        self.assertFalse(doc['syncClaudeAiSkills'])
        self.assertEqual(doc['hooks']['SessionStart'][:-1], initial['hooks']['SessionStart'])
        handler = doc['hooks']['SessionStart'][-1]['hooks'][0]
        self.assertEqual(set(handler), {'type', 'command', 'timeout'})
        command = handler['command']
        if os.name == 'nt':
            command = base64.b64decode(command.split()[-1]).decode('utf-16le')
        self.assertIn('--aem-hook-id', command)
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.home / 'new')}):
            self.setup_cli()
        self.assertFalse((self.home / 'new').exists())
        self.setup_cli('--remove-agent', 'claude')
        self.assertEqual(json.loads(path.read_text()), initial)

    def test_claude_instructions_callback_failure_detach_and_startup_coexist(self):
        self.configure()
        doc = tomlkit.parse(self.catalog.read_text())
        del doc['instructions']['personal']['install']['entry']
        self.catalog.write_text(tomlkit.dumps(doc))
        self.setup_cli('--agent', 'claude', '--agent', 'codex')
        self.run_cli('apply')
        path = self.claude / 'settings.json'
        self.assertEqual(len(json.loads(path.read_text())['hooks']['SessionStart']), 2)
        context, errors = self.callback('agent-hook', 'personal', '--agent', 'claude')
        self.assertEqual(json.loads(context.splitlines()[1])['root'], str(self.bundle))
        self.assertNotIn('Read development/rules.md', context)
        self.assertEqual(errors, '')
        self.run_cli('detach', 'personal:bundle', 'personal:entry', 'report', '--agent', 'claude')
        self.setup_cli('--remove-agent', 'claude')
        self.assertEqual(len(json.loads(path.read_text())['hooks']['SessionStart']), 1)
        self.assertIn('locations', self.callback('agent-hook', 'personal', '--agent', 'claude')[0])
        (self.claude / 'CLAUDE.md').unlink()
        output, error = self.callback('agent-hook', 'personal', '--agent', 'claude', code=2)
        self.assertEqual(output, '')
        self.assertIn('lookup failed', error)

    def test_claude_startup_plain_briefing_fail_open_and_throttle(self):
        self.setup_cli('--agent', 'claude')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 3600}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        output, _ = self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')
        self.assertIn('report: installed/refreshed', output)
        self.assertEqual(self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')[0].strip(), '')
        self.catalog.write_text('broken [')
        self.assertEqual(self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')[0].strip(), '')
        self.assertTrue(self.state()['startup']['failed'])

    def test_disabled_agent_startup_does_not_read_missing_or_invalid_catalog(self):
        self.setup_cli('--agent', 'codex', '--agent', 'claude', '--automation', 'off')
        self.run_cli('bootstrap', self.catalog)
        for missing in (False, True):
            if missing:
                self.catalog.unlink()
            else:
                self.catalog.write_text('broken [')
            for agent in ('codex', 'claude'):
                with self.subTest(agent=agent, missing=missing):
                    output, errors = self.callback('startup', '--trigger', 'agent-start', '--agent', agent)
                    self.assertEqual(errors, '')
                    if agent == 'codex':
                        self.assertEqual(json.loads(output), {})
                    else:
                        self.assertEqual(output.strip(), '')
                    result = self.state()['startup']
                    self.assertEqual(result['status'], 'disabled')
                    self.assertFalse(result['failed'])
                    self.assertEqual(result['outcomes'], [])

    def test_edited_claude_hook_and_duplicate_marker_block_setup(self):
        self.setup_cli('--agent', 'claude')
        path = self.claude / 'settings.json'
        doc = json.loads(path.read_text())
        doc['hooks']['SessionStart'][0]['hooks'][0]['command'] += ' --local-edit'
        path.write_text(json.dumps(doc))
        before = path.read_bytes()
        self.setup_cli('--shell', 'bash', code=1)
        self.setup_cli('--remove-agent', 'claude', code=1)
        self.assertEqual(before, path.read_bytes())
        self.assertFalse((self.home / '.bashrc').exists())

    def test_unrelated_malformed_encoded_hooks_survive_setup_and_removal(self):
        self.claude.mkdir()
        path = self.claude / 'settings.json'
        prefix = 'powershell.exe -NoProfile -NonInteractive -EncodedCommand '
        commands = [None, prefix + '!invalid-base64!', prefix + base64.b64encode(b'x').decode()]
        groups = [{'hooks': [{'type': 'command', 'command': value}]} for value in commands]
        initial = {'hooks': {'SessionStart': groups}, 'permissions': {'allow': ['Read']}}
        path.write_text(json.dumps(initial))
        self.setup_cli('--agent', 'claude')
        self.assertEqual(json.loads(path.read_text())['hooks']['SessionStart'][:-1], groups)
        self.setup_cli('--remove-agent', 'claude')
        self.assertEqual(json.loads(path.read_text()), initial)

    def test_invalid_saved_hook_identity_blocks_removal_without_losing_settings(self):
        self.setup_cli('--agent', 'claude')
        path = self.claude / 'settings.json'
        before = path.read_bytes()
        machine = self.config.read_bytes()
        state_path = Config(self.config).state_dir / 'state.json'
        state = self.state()
        for handlers in ([], [None], [{'type': 'command', 'command': 'echo unrelated'}]):
            with self.subTest(handlers=handlers):
                state['items']['setup:agent-claude']['hook_group'] = {'hooks': handlers}
                state_path.write_text(json.dumps(state))
                self.setup_cli('--remove-agent', 'claude', code=1)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.config.read_bytes(), machine)

    def test_windows_encoded_identity_and_retired_profile_removal(self):
        # Encode on Linux without claiming a native Windows integration run.
        with patch.object(hooks.os, 'name', 'nt'):
            marker, group = agents.profile('claude').definition(self.config, '', startup=True)
        handler = group['hooks'][0]
        self.assertIn(marker, base64.b64decode(handler['command'].split()[-1]).decode('utf-16le'))
        self.assertEqual(hooks.saved_matching({'hooks': {'SessionStart': [group]}}, marker, group), [0])
        self.setup_cli('--agent', 'claude')
        path = self.claude / 'settings.json'
        path.write_text(json.dumps({'keep': True, 'hooks': {'SessionStart': [group]}}))
        state = self.state()
        record = state['items'].pop('setup:agent-claude')
        record.update(hook_marker=marker, hook_group=group, agent='retired', agents=['retired'])
        state['items']['setup:agent-retired'] = record
        (Config(self.config).state_dir / 'state.json').write_text(json.dumps(state))
        doc = tomlkit.parse(self.config.read_text())
        doc['agents']['retired'] = doc['agents'].pop('claude')
        self.config.write_text(tomlkit.dumps(doc))
        self.run_cli('setup', '--remove-agent', 'retired')
        self.assertEqual(json.loads(path.read_text()), {'keep': True, 'hooks': {'SessionStart': []}})

    def test_reserved_claude_folder_names_fail_before_installation(self):
        self.setup_cli('--agent', 'claude')
        for name in ('synced', 'Synced', 'anthropic-skills'):
            self.catalog.write_text(tomlkit.dumps({'version': 2, 'sources': self.catalog_sources, 'skills': {name: self.skills['report']}}))
            self.run_cli('bootstrap', self.catalog, code=1)
            self.assertFalse((self.claude / 'skills' / name).exists())

    def test_malformed_redirected_claude_settings_prevent_shell_writes(self):
        path = self.claude / 'settings.json'
        self.claude.mkdir()
        for content in ('{bad', '{"hooks":{"SessionStart":{}}}', '{"hooks":{},"hooks":{}}'):
            path.write_text(content)
            self.setup_cli('--shell', 'bash', '--agent', 'claude', code=1)
            self.assertFalse((self.home / '.bashrc').exists())
            self.assertFalse(self.config.exists())
        self.require_links()
        path.unlink()
        other = self.root / 'settings.json'
        other.write_text('{}')
        path.symlink_to(other)
        self.setup_cli('--agent', 'claude', code=1)
        self.assertEqual(other.read_text(), '{}')

    def test_claude_grouped_instruction_failure_preserves_settings_and_retry(self):
        self.configure()
        doc = tomlkit.parse(self.catalog.read_text())
        first = doc['instructions']['personal']
        del first['install']['entry']
        import copy
        doc['instructions']['other'] = copy.deepcopy(first)
        doc['instructions']['other']['install'] = {'bundle': {'root': 'rules', 'destination': 'other'}, 'entry': {'destination': 'OTHER.md'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.setup_cli('--agent', 'claude')
        path = self.claude / 'settings.json'
        before = path.read_bytes()
        original = os.replace
        def fail(src, dst):
            if Path(dst) == path and Path(src).name.startswith('.aem-stage-'):
                raise OSError('Injected Claude grouped hook failure')
            return original(src, dst)
        with patch('agent_env_man.manager.os.replace', side_effect=fail):
            self.run_cli('apply', code=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertIsNone(self.state()['pending'])
        self.assertNotIn('personal:hook@claude', self.state()['items'])
        self.assertNotIn('other:hook@claude', self.state()['items'])
        self.run_cli('apply')
        first = path.read_bytes()
        self.assertEqual(len(json.loads(first)['hooks']['SessionStart']), 3)
        self.assertEqual(len(json.loads(first)['hooks']['SubagentStart']), 2)
        self.run_cli('apply')
        self.setup_cli()
        self.assertEqual(path.read_bytes(), first)
        doc = json.loads(first)
        doc['hooks']['SessionStart'].append(doc['hooks']['SessionStart'][-1])
        path.write_text(json.dumps(doc))
        self.run_cli('apply', '--item', 'other:entry', '--replace', code=1)
        self.assertEqual(json.loads(path.read_text()), doc)

    def test_windows_claude_command_preserves_callback_exit_code(self):
        with patch.object(hooks.os, 'name', 'nt'):
            marker, group = agents.profile('claude').definition(self.config, 'personal')
            _, codex = agents.profile('codex').definition(self.config, 'personal')
        decoded = base64.b64decode(group['hooks'][0]['command'].split()[-1]).decode('utf-16le')
        self.assertTrue(decoded.endswith('; exit $LASTEXITCODE'))
        self.assertIn('--aem-hook-id', decoded)
        self.assertEqual(hooks.saved_matching({'hooks': {'SessionStart': [group]}}, marker, group), [0])
        # Existing Codex hook serialization must retain its released contract.
        decoded_codex = base64.b64decode(codex['hooks'][0]['command'].split()[-1]).decode('utf-16le')
        self.assertNotIn('exit $LASTEXITCODE', decoded_codex)

    def test_claude_startup_reloads_initial_install_and_updated_skills(self):
        self.setup_cli('--agent', 'claude')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 0}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        result = self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'claude')
        context = result['hookSpecificOutput']
        self.assertTrue(context['reloadSkills'])
        self.assertIn('installed/refreshed', context['additionalContext'])
        self.assertEqual(self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')[0].strip(), '')
        (self.repo / 'skills/report/helper.py').write_text('Changed skill')
        self.commit(self.repo)
        result = self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'claude')
        self.assertTrue(result['hookSpecificOutput']['reloadSkills'])
        self.assertEqual((self.claude / 'skills/report/helper.py').read_text(), 'Changed skill')
        doc['updates']['defaults']['action'] = 'check'
        self.catalog.write_text(tomlkit.dumps(doc))
        self.assertEqual(self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')[0].strip(), '')

    def test_claude_does_not_reload_for_other_agent_only_skill_changes(self):
        self.setup_cli('--agent', 'claude', '--agent', 'codex')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 0}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        self.run_cli('detach', 'report', '--agent', 'claude')
        (self.repo / 'skills/report/helper.py').write_text('Codex-only change')
        self.commit(self.repo)
        output, _ = self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')
        self.assertIn('report:', output)
        self.assertNotIn('reloadSkills', output)


    def shared_checkout_reload(self, *, mode="link", detached=False, fail_apply=False):
        self.require_links()
        self.setup_cli('--agent', 'claude', '--agent', 'codex')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['skills']['summary'] = dict(doc['skills']['report'])
        doc['skills']['summary']['install'] = {'mode': mode}
        doc['skills']['summary']['update'] = {'trigger': []}
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 0},
                          'policies': {'summary': {'trigger': []}}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        self.run_cli('detach', 'report', '--agent', 'claude')
        self.run_cli('detach', 'summary', '--agent', 'codex')
        if detached:
            self.run_cli('detach', 'summary', '--agent', 'claude')
        target = self.claude / 'skills/summary/helper.py'
        before = target.read_text()
        (self.repo / 'skills/report/helper.py').write_text('Shared checkout advancement')
        self.commit(self.repo)
        guard = patch.object(Manager, 'apply', side_effect=Error('Test apply failure')) if fail_apply else nullcontext()
        with guard:
            output, _ = self.callback('startup', '--trigger', 'agent-start', '--agent', 'claude')
        expected = mode == 'link' and not detached
        self.assertEqual('reloadSkills' in output, expected)
        self.assertEqual(target.read_text(), 'Shared checkout advancement' if expected else before)
        outcomes = self.state()['startup']['outcomes']
        self.assertEqual(next(o for o in outcomes if o['skill'] == 'summary')['status'],
                         'not-triggered')
        report = next(o for o in outcomes if o['skill'] == 'report')
        self.assertEqual(report['status'], 'failed' if fail_apply else 'synced')
        applied = report.get('apply', [])
        self.assertFalse(any('summary' in item['item'] for item in applied))
        # A successful no-op must not repeatedly request reload.
        self.assertNotIn('reloadSkills', self.callback(
            'startup', '--trigger', 'agent-start', '--agent', 'claude')[0])

    def test_shared_checkout_reloads_excluded_claude_link(self):
        self.shared_checkout_reload()

    def test_shared_checkout_does_not_reload_unapplied_copy(self):
        self.shared_checkout_reload(mode='copy')

    def test_shared_checkout_does_not_reload_detached_skill(self):
        self.shared_checkout_reload(detached=True)

    def test_shared_checkout_reloads_live_link_after_apply_failure(self):
        self.shared_checkout_reload(fail_apply=True)

    def test_shipped_profiles_have_parallel_contracts(self):
        fields = ('name', 'entry_name', 'hook_name', 'notice')
        methods = ('defaults', 'definition', 'render', 'current', 'remove',
                   'context', 'failure', 'startup_result', 'validate_skill_name')
        for name in ('codex', 'claude'):
            with self.subTest(agent=name):
                adapter = agents.profile(name)
                self.assertTrue(all(isinstance(getattr(adapter, key), str) for key in fields))
                self.assertTrue(all(callable(getattr(adapter, key)) for key in methods))
                self.assertEqual(set(adapter.defaults()), {'root', 'skills'})
                self.assertIsInstance(adapter.failure_to_stderr, bool)
                self.assertIsInstance(adapter.failure_exit_code, int)
                marker, group = adapter.definition(self.config, '', startup=True)
                path = self.root / (name + '-contract.json')
                path.write_text(json.dumps({'keep': True, 'hooks': {'SessionEnd': []}}))
                original = json.loads(path.read_text())
                path.write_bytes(adapter.render(path, marker, group, None))
                self.assertTrue(adapter.current(path, marker, group))
                record = {'hook_marker': marker, 'hook_group': group}
                removed = json.loads(adapter.remove(path, record))
                self.assertTrue(removed['keep'])
                self.assertEqual(removed['hooks']['SessionEnd'], original['hooks']['SessionEnd'])
                self.assertEqual(removed['hooks']['SessionStart'], [])

    def test_third_plain_context_profile_uses_common_lifecycle(self):
        home = self.home
        class Future(agents.Claude):
            def defaults(adapter):
                return {'root': str(home / 'future'), 'skills': str(home / 'future/skills')}
        adapter = Future(name='future', entry_name='RULES.md', hook_name='events.json', notice='Fixture only')
        with patch.dict(agents.PROFILES, {'future': adapter}):
            self.configure()
            doc = tomlkit.parse(self.catalog.read_text())
            del doc['instructions']['personal']['install']['entry']
            self.catalog.write_text(tomlkit.dumps(doc))
            self.setup_cli('--agent', 'codex', '--agent', 'claude', '--agent', 'future')
            self.run_cli('apply')
            target = home / 'future/RULES.md'
            self.assertTrue(target.is_symlink())
            self.assertTrue((home / 'future/skills/report/SKILL.md').is_file())
            context, error = self.callback('agent-hook', 'personal', '--agent', 'future')
            self.assertEqual(json.loads(context.splitlines()[1])['root'], str(self.bundle))
            self.assertEqual(error, '')
            self.run_cli('detach', 'personal:entry', '--agent', 'future')
            self.assertFalse(target.is_symlink())
            self.assertIn('locations', self.callback('agent-hook', 'personal', '--agent', 'future')[0])
            self.run_cli('detach', 'report', 'personal:bundle', '--agent', 'future')
            self.setup_cli('--remove-agent', 'future')
            groups = json.loads((home / 'future/events.json').read_text())['hooks']['SessionStart']
            self.assertEqual(len(groups), 1)  # Detached instruction hook remains owned separately.
            self.assertTrue((self.claude / 'settings.json').is_file())

    def test_codex_failure_remains_structured_and_success_is_json(self):
        self.configure()
        self.setup_cli('--agent', 'codex')
        self.run_cli('apply')
        output, error = self.callback('agent-hook', 'personal', '--agent', 'codex')
        self.assertEqual(error, '')
        self.assertIn('additionalContext', json.loads(output)['hookSpecificOutput'])
        (self.agent / 'AGENTS.md').unlink()
        output, error = self.callback('agent-hook', 'personal', '--agent', 'codex')
        self.assertEqual(error, '')
        self.assertFalse(json.loads(output)['continue'])

    def test_future_failure_channel_is_explicit_not_inferred_from_payload(self):
        home = self.home
        class Future(agents.Codex):
            def defaults(adapter):
                return {'root': str(home / 'json-future'), 'skills': str(home / 'json-future/skills')}
            def failure(adapter, message):
                return message  # Plain output need not imply Claude's stderr/exit 2.
        adapter = Future(name='json-future', entry_name='RULES.md', hook_name='events.json', notice='Fixture only')
        with patch.dict(agents.PROFILES, {'json-future': adapter}):
            output, error = self.callback('agent-hook', 'missing', '--agent', 'json-future')
            self.assertIn('lookup failed', output)
            self.assertEqual(error, '')
