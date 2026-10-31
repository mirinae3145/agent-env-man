"""Named product instances use isolated temporary targets and existing journals."""
import json
import io
from contextlib import redirect_stdout, redirect_stderr
import os
from pathlib import Path
from unittest.mock import patch

import tomlkit

from agent_env_man.agents import profile
from agent_env_man.model import Config, Error
from agent_env_man.cli import main
from test_setup import SetupFixture


class NamedProfiles(SetupFixture):
    def prepare(self):
        self.configure()
        doc = tomlkit.parse(self.catalog.read_text())
        del doc['instructions']['personal']['install']['entry']
        self.catalog.write_text(tomlkit.dumps(doc))
        # No real CLAUDE_CONFIG_DIR may enter a disposable fixture.
        self.env_patch_claude = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.home / '.claude')})
        self.env_patch_claude.start()
        self.addCleanup(self.env_patch_claude.stop)
        self.setup_cli('--agent', 'codex', '--agent', 'claude')
        self.run_cli('apply')

    def test_add_select_repeat_detach_preserves_existing_profiles(self):
        self.prepare()
        old = {p: p.read_bytes() for root in (self.agent, self.home / '.claude')
               for p in root.rglob('*') if p.is_file()}
        self.setup_cli('--agent', 'codex-lab', '--agent', 'claude-lab')
        for name, entry in [('codex-lab', 'AGENTS.md'), ('claude-lab', 'CLAUDE.md')]:
            root = self.home / ('.' + name)
            self.assertFalse((root / entry).exists())
            self.run_cli('apply', '--agent', name)
            self.assertTrue((root / entry).is_file())
            self.assertTrue((root / 'skills/report').is_symlink())
            definition = self.state()['items']['personal:hook@' + name]['hook_group']
            command = definition['hooks'][0]['command']
            if os.name != 'nt':
                self.assertIn('--agent ' + name, command)
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(['--config', str(self.config), 'agent-hook', 'personal', '--agent', name])
            self.assertEqual(result, 0, errors.getvalue())
            context = output.getvalue() if name.startswith('claude-') else json.loads(output.getvalue())['hookSpecificOutput']['additionalContext']
            self.assertEqual(json.loads(context.splitlines()[1])['global_entry'], str(root / entry))
            self.assertEqual(self.run_cli('locate', 'personal', '--agent', name)['entry'], str(self.bundle / 'start.md'))
            report = self.run_cli('status', '--agent', name)
            self.assertTrue(any(row['item'] == 'personal:entry@' + name for row in report['items']))
        self.setup_cli('--agent', 'codex-lab', '--agent', 'claude-lab')
        self.assertEqual({p: p.read_bytes() for p in old}, old)
        self.run_cli('detach', 'personal:bundle', 'personal:entry', 'report', '--agent', 'claude-lab')
        self.setup_cli('--remove-agent', 'claude-lab')
        self.assertTrue((self.home / '.claude-lab/CLAUDE.md').is_file())
        self.assertFalse(self.state()['items']['personal:entry@codex-lab']['detached'])
        self.assertEqual({p: p.read_bytes() for p in old}, old)

    def test_named_defaults_do_not_follow_personal_environment(self):
        for product in ('claude', 'codex'):
            name = product + '-lab'
            binding = profile(name).defaults()
            self.assertEqual(binding['root'], str(self.home / ('.' + name)))
            self.assertEqual(binding['skills'], str(self.home / ('.' + name) / 'skills'))

    def test_named_roots_cannot_alias_or_nest_another_profile(self):
        for root in (self.home / '.claude', self.home / '.claude/nested'):
            with self.subTest(root=root), self.assertRaises(Error):
                Config(self.config, document={'version': 1, 'agents': {
                    'claude': {'root': str(self.home / '.claude')},
                    'claude-lab': {'root': str(root)}}})

    def test_named_personal_hooks_reuse_product_declarations(self):
        self.prepare()
        self.setup_cli('--agent', 'claude-lab', '--agent', 'codex-lab')
        (self.external / 'stop.py').write_text('print("not executed by AEM")')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['hooks'] = {'stopper': {'source': 'personal', 'agents': {
            product: {'event': 'Stop', 'runtime': 'python', 'script': 'stop.py'}
            for product in ('claude', 'codex')}}}
        self.catalog.write_text(tomlkit.dumps(doc))
        import sys
        self.run_cli('bootstrap', '--runtime', 'python=' + sys.executable)
        self.run_cli('apply', '--item', 'stopper', '--agent', 'claude-lab')
        records = self.state()['items']
        self.assertIn('stopper:hook@claude-lab', records)
        self.assertNotIn('stopper:hook@codex-lab', records)
        self.run_cli('apply', '--item', 'stopper', '--agent', 'codex-lab')
        self.assertIn('stopper:hook@codex-lab', self.state()['items'])

    def test_profile_bound_settings_share_source_but_not_stage_or_target(self):
        self.prepare()
        self.setup_cli('--agent', 'claude-lab')
        (self.external / 'preferences.json').write_text('{"model":"sonnet"}')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {name: {'source': 'personal', 'path': 'preferences.json', 'format': 'json'}
                           for name in ('personal-preferences', 'lab-preferences')}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {
            'personal-preferences': {'target': str(self.home / '.claude/settings.json'), 'agent': 'claude'},
            'lab-preferences': {'target': str(self.home / '.claude-lab/settings.json'), 'agent': 'claude-lab'}}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('bootstrap', '--setting-target', 'lab-preferences=' + str(self.home / '.claude-lab/settings.json'))
        self.assertEqual(Config(self.config).doc['settings']['lab-preferences']['agent'], 'claude-lab')
        original = (self.home / '.claude/settings.json').read_bytes()
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertEqual((self.home / '.claude/settings.json').read_bytes(), original)
        self.assertEqual(json.loads((self.home / '.claude-lab/settings.json').read_text())['model'], 'sonnet')
        records = self.state()['items']
        self.assertNotEqual(records['lab-preferences:settings']['stage_root'], records['personal-preferences:settings']['stage_root'])
        self.run_cli('detach', 'lab-preferences', '--agent', 'claude-lab')
        self.assertTrue(self.state()['items']['lab-preferences:settings']['detached'])
        self.assertFalse(self.state()['items']['personal-preferences:settings']['detached'])
        self.run_cli('detach', 'personal:bundle', 'personal:entry', 'report', '--agent', 'claude-lab')
        self.setup_cli('--remove-agent', 'claude-lab')
        self.assertNotIn('catalog_error', self.run_cli('status'))
        self.run_cli('apply', '--item', 'lab-preferences', '--reattach', code=1)

    def test_profile_setup_and_removal_preserve_account_state(self):
        self.prepare()
        saved = {}
        for name in ('claude-lab', 'codex-lab'):
            root = self.home / ('.' + name)
            for relative in ('auth.json', '.credentials.json', 'sessions/one.json',
                             'plugins/data/example/state.json', 'plugins/store/example.json'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('account-specific fixture')
                saved[path] = path.read_bytes()
        self.setup_cli('--agent', 'claude-lab', '--agent', 'codex-lab')
        self.run_cli('apply', '--agent', 'claude-lab')
        self.run_cli('apply', '--agent', 'codex-lab')
        self.run_cli('detach', 'personal:bundle', 'personal:entry', 'report', '--agent', 'codex-lab')
        self.setup_cli('--remove-agent', 'codex-lab')
        self.assertEqual({p: p.read_bytes() for p in saved}, saved)

    def test_lab_failure_recovers_without_changing_personal_profile(self):
        self.prepare()
        self.setup_cli('--agent', 'claude-lab')
        path = self.home / '.claude-lab/settings.json'
        personal = self.home / '.claude/settings.json'
        before, original_personal = path.read_bytes(), personal.read_bytes()
        original_replace = os.replace
        def fail(src, dst):
            if Path(dst) == path and Path(src).name.startswith('.aem-stage-'):
                raise OSError('Injected lab hook failure')
            return original_replace(src, dst)
        with patch('agent_env_man.manager.os.replace', side_effect=fail):
            self.run_cli('apply', '--agent', 'claude-lab', code=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(personal.read_bytes(), original_personal)
        self.run_cli('recover')
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertTrue((self.home / '.claude-lab/CLAUDE.md').is_file())
        self.assertEqual(personal.read_bytes(), original_personal)

    def test_aliased_roots_refused_before_setup_writes(self):
        self.prepare()
        original = self.config.read_bytes()
        path = self.home / '.claude-lab'
        path.symlink_to(self.home / '.claude', target_is_directory=True)
        self.setup_cli('--agent', 'claude-lab', code=1)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertTrue(path.is_symlink())

    def test_invalid_profile_names_are_usage_errors_without_config(self):
        for name in ('lab', 'claude-', 'codex-../lab', 'claude-lab@other'):
            self.setup_cli('--agent', name, code=2)
            self.assertFalse(self.config.exists())

    def test_unregistered_named_selection_cannot_apply_global_items(self):
        self.prepare()
        before = self.config.read_bytes()
        error = self.run_cli('apply', '--agent', 'claude-typo', code=1)
        self.assertIn('not configured', error)
        self.assertEqual(self.config.read_bytes(), before)

    def test_settings_binding_cannot_target_another_profiles_root(self):
        self.prepare()
        self.setup_cli('--agent', 'claude-lab')
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {'preferences': {'agent': 'claude-lab',
                              'target': str(self.home / '.claude/settings.json')}}
        config = Config(self.config, document=machine)
        with self.assertRaisesRegex(Error, 'inside its agent root'):
            config.catalog()

    def test_codex_lab_settings_apply_common_fields_and_keep_local_values(self):
        self.prepare()
        self.setup_cli('--agent', 'codex-lab')
        source = self.external / 'codex.toml'
        source.write_text('model = "example-model"\n')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {'codex-lab-preferences': {'source': 'personal', 'path': 'codex.toml', 'format': 'toml'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        path = self.home / '.codex-lab/config.toml'
        path.write_text('local_value = "keep"\n')
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {'codex-lab-preferences': {'target': str(path), 'agent': 'codex-lab'}}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('bootstrap')
        before = path.read_bytes()
        self.run_cli('apply', '--agent', 'codex-lab', '--dry-run')
        self.assertEqual(path.read_bytes(), before)
        self.run_cli('apply', '--agent', 'codex-lab')
        self.assertEqual(tomlkit.parse(path.read_text()), {'local_value': 'keep', 'model': 'example-model'})
        path.write_text('local_value = "keep"\nmodel = "local-edit"\n')
        self.run_cli('apply', '--agent', 'codex-lab', code=1)
        self.assertEqual(tomlkit.parse(path.read_text())['model'], 'local-edit')
        machine = tomlkit.parse(self.config.read_text())
        del machine['settings']['codex-lab-preferences']['agent']
        self.config.write_text(tomlkit.dumps(machine))
        self.assertIn('agent binding changed', self.run_cli('apply', '--item', 'codex-lab-preferences', code=1))

    def test_new_setting_requires_registered_destination(self):
        self.prepare()
        (self.external / 'preferences.json').write_text('{"model":"sonnet"}')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {'missing': {'source': 'personal', 'path': 'preferences.json', 'format': 'json'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {'missing': {'target': str(self.home / '.claude-missing/settings.json'), 'agent': 'claude-missing'}}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('bootstrap', code=1)
        self.assertFalse((self.home / '.claude-missing').exists())

    def test_lab_selection_does_not_apply_unbound_personal_preferences(self):
        self.prepare()
        self.setup_cli('--agent', 'claude-lab')
        (self.external / 'preferences.json').write_text('{"model":"sonnet"}')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {'legacy': {'source': 'personal', 'path': 'preferences.json', 'format': 'json'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        path = self.home / '.claude/settings.json'
        machine['settings'] = {'legacy': {'target': str(path)}}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('bootstrap')
        before = path.read_bytes()
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertEqual(path.read_bytes(), before)
        self.run_cli('apply', '--agent', 'claude')
        self.assertEqual(json.loads(path.read_text())['model'], 'sonnet')

    def test_named_windows_hook_serialization_keeps_instance_identity(self):
        import base64
        from agent_env_man import hooks
        with patch.object(hooks.os, 'name', 'nt'):
            marker, group = profile('claude-lab').definition(self.config, 'rules')
        command = base64.b64decode(group['hooks'][0]['command'].split()[-1]).decode('utf-16le')
        self.assertIn(marker, command)
        self.assertIn('claude-lab', command)
        self.assertNotEqual(marker, profile('claude').definition(self.config, 'rules')[0])
