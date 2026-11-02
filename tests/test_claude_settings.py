"""Claude setup hooks and non-hook JSON preferences share one temporary file."""
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import tomlkit

from test_setup import SetupFixture


class ClaudeSettings(SetupFixture):
    def setUp(self):
        super().setUp()
        self.target = self.home / '.claude/settings.json'
        self.source = self.root / 'preferences'
        self.source.mkdir()
        self.payload = self.source / 'claude.json'
        self.payload.write_text('{"awaySummaryEnabled": false}\n', encoding='utf-8')
        self.catalog.write_text(tomlkit.dumps({'version': 2,
            'sources': {'preferences': {'type': 'external'}},
            'settings': {'preferences': {'source': 'preferences', 'path': 'claude.json',
                'format': 'json', 'update': {'trigger': []}}}}), encoding='utf-8')
        self.stage = self.config.parent / (self.config.name + '.stages/preferences/config.json')

    def bootstrap(self, *, code=0):
        return self.run_cli('bootstrap', self.catalog, '--external', f'preferences={self.source}',
                            '--setting-target', f'preferences={self.target}', code=code)

    def apply_preferences(self, *args, code=0):
        return self.run_cli('apply', '--item', 'preferences', *args, code=code)

    def test_shared_file_capability_comes_from_profile(self):
        from agent_env_man import agents
        fake = replace(agents.Claude(), name='fake', hook_name='events.json')
        self.target = self.home / '.claude/events.json'
        with patch.dict(agents.PROFILES, {'fake': fake}):
            self.setup_cli('--agent', 'fake')
            self.bootstrap()
            self.apply_preferences()
            self.assertFalse(json.loads(self.target.read_text())['awaySummaryEnabled'])
            self.setup_cli('--agent', 'fake')
            self.assertIn('hooks', json.loads(self.target.read_text()))

    def test_setup_first_apply_repeat_and_removal_preserve_preferences(self):
        self.setup_cli('--agent', 'claude')
        document = json.loads(self.target.read_text())
        document.update(awaySummaryEnabled=True, permissions={'allow': ['Read']})
        self.target.write_text(json.dumps(document), encoding='utf-8')
        self.bootstrap()
        before = self.target.read_bytes()
        self.apply_preferences('--replace', '--dry-run')
        self.assertEqual(self.target.read_bytes(), before)
        self.apply_preferences('--replace')
        expected = dict(document, awaySummaryEnabled=False)
        self.assertEqual(json.loads(self.target.read_text()), expected)
        before = self.target.read_bytes()
        self.apply_preferences()
        self.assertEqual(self.target.read_bytes(), before)
        self.setup_cli('--agent', 'claude')
        self.assertEqual(json.loads(self.target.read_text()), expected)
        self.setup_cli('--remove-agent', 'claude')
        self.assertFalse(json.loads(self.target.read_text())['awaySummaryEnabled'])
        self.assertEqual(json.loads(self.target.read_text())['permissions'], document['permissions'])
        self.apply_preferences()

    def test_settings_first_setup_and_detach_preserve_hooks(self):
        self.bootstrap()
        self.apply_preferences()
        self.setup_cli('--agent', 'claude')
        before = self.target.read_bytes()
        self.run_cli('detach', 'preferences')
        self.assertEqual(self.target.read_bytes(), before)
        self.setup_cli('--agent', 'claude')
        self.assertEqual(self.target.read_bytes(), before)

    def test_apply_together_installs_instruction_hook_and_preferences(self):
        self.require_links()
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        (self.source / 'RULES.md').write_text('Personal rules', encoding='utf-8')
        catalog = tomlkit.parse(self.catalog.read_text(encoding='utf-8'))
        catalog['instructions'] = {'rules': {'source': 'preferences', 'entry': 'RULES.md'}}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        self.run_cli('bootstrap', '--item', 'rules')
        before, records = self.target.read_bytes(), self.state()['items']
        self.run_cli('apply', '--dry-run')
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.state()['items'], records)

        self.run_cli('apply')
        actual = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertFalse(actual['awaySummaryEnabled'])
        self.assertEqual(len(actual['hooks']['SessionStart']), 2)
        self.assertEqual(len(actual['hooks']['SubagentStart']), 1)
        records = self.state()['items']
        for key in ('setup:agent-claude', 'rules:hook@claude'):
            self.assertIn(records[key]['hook_group'], actual['hooks']['SessionStart'])
        self.assertIsNotNone(records['preferences:settings']['applied'])
        before = self.target.read_bytes()
        self.run_cli('apply')
        self.assertEqual(self.target.read_bytes(), before)

    def test_remove_multiple_agents_preserves_shared_preferences(self):
        self.setup_cli('--agent', 'claude', '--agent', 'codex')
        self.bootstrap()
        self.apply_preferences()
        applied = self.state()['items']['preferences:settings']['applied']

        self.setup_cli('--remove-agent', 'claude', '--remove-agent', 'codex')
        actual = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertFalse(actual['awaySummaryEnabled'])
        records = self.state()['items']
        for agent in ('claude', 'codex'):
            record = records[f'setup:agent-{agent}']
            self.assertTrue(record['detached'])
            document = json.loads(Path(record['target']).read_text(encoding='utf-8'))
            self.assertNotIn(record['hook_group'], document['hooks']['SessionStart'])
        self.assertEqual(records['preferences:settings']['applied'], applied)
        self.assertFalse(records['preferences:settings']['detached'])
        self.apply_preferences()

    def test_hook_fields_refused_from_source_stage_collect_and_metadata(self):
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        self.apply_preferences()
        before = self.target.read_bytes()
        stage = self.stage.read_bytes()
        self.payload.write_text('{"hooks": {"SessionStart": []}}', encoding='utf-8')
        self.assertIn('hooks', str(self.run_cli('update', 'preferences', code=1)))
        self.assertEqual(self.stage.read_bytes(), stage)
        self.stage.write_text('{"hooks": {}}', encoding='utf-8')
        self.assertIn('hooks', self.apply_preferences('--replace', code=1))
        self.stage.write_bytes(stage)
        self.assertIn('hooks', self.run_cli('settings', 'collect', 'preferences',
                                           '--path', '["hooks"]', code=1))
        self.assertEqual(self.stage.read_bytes(), stage)
        metadata = self.stage.with_name('management.toml')
        original = metadata.read_bytes()
        metadata.write_text('version = 1\ndeleted = [["hooks"]]\n', encoding='utf-8')
        self.assertIn('hooks', self.apply_preferences('--replace', code=1))
        metadata.write_bytes(original)
        self.assertEqual(self.target.read_bytes(), before)

    def test_setup_refuses_existing_hook_field_owner(self):
        self.payload.write_text('{"hooks": {}}', encoding='utf-8')
        self.bootstrap()
        self.apply_preferences()
        before = self.target.read_bytes()
        self.assertIn('hooks', self.setup_cli('--agent', 'claude', code=1))
        self.assertEqual(self.target.read_bytes(), before)

    def test_instruction_hook_and_second_setting_owner_boundaries(self):
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        self.apply_preferences()
        (self.source / 'RULES.md').write_text('Personal rules', encoding='utf-8')
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['instructions'] = {'rules': {'source': 'preferences', 'entry': 'RULES.md'}}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        self.run_cli('bootstrap', '--item', 'rules')
        self.run_cli('apply', '--item', 'rules:entry@claude')
        before = json.loads(self.target.read_text())
        self.assertEqual(len(before['hooks']['SessionStart']), 2)
        self.stage.write_text('{"awaySummaryEnabled": true}', encoding='utf-8')
        self.apply_preferences()
        actual = json.loads(self.target.read_text())
        self.assertEqual(actual['hooks'], before['hooks'])
        self.assertTrue(actual['awaySummaryEnabled'])
        self.run_cli('apply', '--item', 'rules:entry@claude')
        self.assertEqual(json.loads(self.target.read_text()), actual)
        catalog['settings']['another'] = {'source': 'preferences', 'path': 'claude.json', 'format': 'json'}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        self.assertIn('Overlapping targets', self.run_cli('bootstrap', '--item', 'another',
            '--setting-target', f'another={self.target}', code=1))
        self.assertEqual(json.loads(self.target.read_text()), actual)

    def test_failed_apply_rolls_back_shared_file_and_hook_ownership(self):
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        self.apply_preferences()
        before = self.target.read_bytes()
        records = self.state()['items']
        self.stage.write_text('{"awaySummaryEnabled": true}', encoding='utf-8')
        from agent_env_man.storage import State
        original = State.save
        count = 0
        def fail_commit(state):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('simulated state commit failure')
            return original(state)
        with patch.object(State, 'save', fail_commit):
            self.apply_preferences(code=1)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.state()['items'], records)

    def prepare_combined_apply(self):
        self.require_links()
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        (self.source / 'RULES.md').write_text('Personal rules', encoding='utf-8')
        catalog = tomlkit.parse(self.catalog.read_text(encoding='utf-8'))
        catalog['instructions'] = {'rules': {'source': 'preferences', 'entry': 'RULES.md'}}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        self.run_cli('bootstrap', '--item', 'rules')

    def test_combined_apply_rolls_back_hook_preferences_and_records(self):
        from agent_env_man.storage import State
        self.prepare_combined_apply()
        before, stage = self.target.read_bytes(), self.stage.read_bytes()
        original = State.save
        def fail_commit(state):
            if (state.data['items'].get('preferences:settings', {}).get('applied')
                    and 'rules:hook@claude' in state.data['items']):
                raise OSError('injected shared-file commit failure')
            return original(state)
        with patch.object(State, 'save', fail_commit):
            self.run_cli('apply', code=1)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.stage.read_bytes(), stage)
        records = self.state()['items']
        self.assertIsNone(records['preferences:settings']['applied'])
        self.assertNotIn('rules:hook@claude', records)
        self.assertIsNone(self.state()['pending'])

    def test_combined_apply_preserves_concurrent_target_edit(self):
        from agent_env_man import settings
        self.prepare_combined_apply()
        original = settings.transaction
        def edit_before_commit(state, writes, records, **options):
            document = json.loads(self.target.read_text(encoding='utf-8'))
            document['later_user_edit'] = True
            self.target.write_text(json.dumps(document), encoding='utf-8')
            return original(state, writes, records, **options)
        with patch.object(settings, 'transaction', edit_before_commit):
            self.run_cli('apply', code=1)
        document = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertTrue(document['later_user_edit'])
        self.assertNotIn('awaySummaryEnabled', document)
        self.assertEqual(len(document['hooks']['SessionStart']), 1)
        self.assertNotIn('rules:hook@claude', self.state()['items'])

    def assert_combined_apply_refuses_source_change(self, *, delete=False):
        from agent_env_man.manager import Manager
        self.prepare_combined_apply()
        before, stage = self.target.read_bytes(), self.stage.read_bytes()
        entry = self.source / 'RULES.md'
        original = Manager.install
        def change_after_entry_install(manager, plan):
            result = original(manager, plan)
            if plan.item.kind == 'instruction-entry':
                if delete:
                    entry.unlink()
                else:
                    entry.write_text('Concurrent user edit', encoding='utf-8')
            return result
        with patch.object(Manager, 'install', change_after_entry_install):
            error = self.run_cli('apply', code=1)
        self.assertIn('regular entry document' if delete else 'source changed', error)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.stage.read_bytes(), stage)
        records = self.state()['items']
        self.assertNotIn('rules:hook@claude', records)
        self.assertIsNone(records['preferences:settings']['applied'])
        self.assertIsNone(self.state()['pending'])
        if delete:
            self.assertFalse(entry.exists())
        else:
            self.assertEqual(entry.read_text(encoding='utf-8'), 'Concurrent user edit')

    def test_combined_apply_refuses_source_edit_after_entry_install(self):
        self.assert_combined_apply_refuses_source_change()

    def test_combined_apply_refuses_source_deletion_after_entry_install(self):
        self.assert_combined_apply_refuses_source_change(delete=True)

    def test_retired_agent_removal_preserves_shared_preferences(self):
        from agent_env_man.model import Config
        self.setup_cli('--agent', 'claude')
        self.bootstrap()
        self.apply_preferences()
        state = self.state()
        preferences = state['items']['preferences:settings']
        record = state['items'].pop('setup:agent-claude')
        record.update(agent='retired', agents=['retired'])
        state['items']['setup:agent-retired'] = record
        (Config(self.config).state_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        document = tomlkit.parse(self.config.read_text(encoding='utf-8'))
        document['agents']['retired'] = document['agents'].pop('claude')
        self.config.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.catalog.unlink()
        before = json.loads(self.target.read_text(encoding='utf-8'))

        self.run_cli('setup', '--remove-agent', 'retired')

        expected = dict(before, hooks=dict(before['hooks'], SessionStart=[]))
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8')), expected)
        records = self.state()['items']
        self.assertTrue(records['setup:agent-retired']['detached'])
        self.assertEqual(records['preferences:settings'], preferences)
        document = tomlkit.parse(self.config.read_text(encoding='utf-8'))
        self.assertNotIn('retired', document.get('agents', {}))
