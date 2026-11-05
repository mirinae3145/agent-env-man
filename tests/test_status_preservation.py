"""Offline status preserves installed evidence when declarations are unusable."""

import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.git_source import Git
import test_personal_hooks
import test_settings
import test_setup


class SavedInstallations(test_setup.SetupFixture):
    def state_path(self):
        return Path(str(self.config) + '.state/state.json')

    def test_invalid_configuration_keeps_broken_links_and_common_copy_diagnostics(self):
        self.configure()
        document = tomlkit.parse(self.catalog.read_text(encoding='utf-8'))
        document['directories'] = {'common': {'source': 'personal', 'permissions': 'best-effort',
            'install': {'root': 'rules', 'destination': 'common', 'mode': 'copy'}}}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.run_cli('apply')
        self.config.write_text('version = 1\nroots = "unusable"\n', encoding='utf-8')
        shutil.rmtree(self.external)
        state_before = self.state_path().read_bytes()
        config_before = self.config.read_bytes()
        copy_file = self.rules / 'common/start.md'
        copy_before = copy_file.read_bytes()
        with patch.object(Git, 'run', side_effect=AssertionError('Status must stay offline')):
            report = self.run_cli('status')
            selected = self.run_cli('status', '--agent', 'claude')
        self.assertTrue(report['saved_only'])
        self.assertIn('configuration_error', report)
        items = {item['item']: item for item in report['items']}
        for key in ('personal:bundle', 'personal:entry'):
            self.assertEqual(items[key]['observation']['kind'], 'link')
            self.assertFalse(items[key]['link_available'])
        common = items['common:directory']
        self.assertEqual(common['permissions'], 'best-effort')
        self.assertIn('permissions_hash', common['observation'])
        saved = json.loads(state_before)['items']['common:directory']
        self.assertEqual(common['permission_differences'], saved.get('permission_differences', []))
        self.assertEqual(common['collection_permission_differences'],
                         saved.get('collection_permission_differences', []))
        self.assertEqual([item['item'] for item in selected['items']], ['common:directory'])
        self.assertEqual(self.state_path().read_bytes(), state_before)
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(copy_file.read_bytes(), copy_before)

    def test_retargeted_entry_and_unreadable_hook_are_reported_without_repair(self):
        self.configure()
        self.run_cli('apply')
        replacement = self.root / 'local-rules.md'
        replacement.write_text('Keep local rules\n', encoding='utf-8')
        entry = self.agent / 'AGENTS.md'
        entry.unlink()
        entry.symlink_to(replacement)
        hook = self.agent / 'hooks.json'
        hook.write_text('{invalid JSON', encoding='utf-8')
        state_before = self.state_path().read_bytes()
        report = self.run_cli('status')
        items = {item['item']: item for item in report['items']}
        self.assertEqual(items['personal:entry']['installation'], 'modified-locally')
        self.assertEqual(items['personal:hook']['installation'], 'unreadable')
        self.assertEqual(self.state_path().read_bytes(), state_before)
        self.assertTrue(entry.samefile(replacement))
        self.assertEqual(replacement.read_text(encoding='utf-8'), 'Keep local rules\n')
        self.assertEqual(hook.read_text(encoding='utf-8'), '{invalid JSON')

    def test_shell_status_distinguishes_owned_block_edits_and_unreadable_text(self):
        self.setup_cli('--shell', 'bash')
        record = self.state()['items']['setup:shell-bash']
        target = Path(record['target'])
        original = target.read_bytes()
        state_before = self.state_path().read_bytes()
        variants = ((original + b'\n# User customization\n', 'matches-last-apply'),
                    (original + record['block'].encode('utf-8'), 'modified-locally'),
                    (b'\xff\xfe', 'unreadable'))
        for content, expected in variants:
            with self.subTest(expected=expected):
                target.write_bytes(content)
                items = {item['item']: item for item in self.run_cli('status')['items']}
                self.assertEqual(items['setup:shell-bash']['installation'], expected)
                self.assertEqual(target.read_bytes(), content)
                self.assertEqual(self.state_path().read_bytes(), state_before)


class SavedPersonalHooks(unittest.TestCase):
    setUp = test_personal_hooks.PersonalHooks.setUp
    save = test_personal_hooks.PersonalHooks.save
    call = test_personal_hooks.PersonalHooks.call
    bootstrap = test_personal_hooks.PersonalHooks.bootstrap
    apply = test_personal_hooks.PersonalHooks.apply
    target = test_personal_hooks.PersonalHooks.target
    document = test_personal_hooks.PersonalHooks.document
    write = test_personal_hooks.PersonalHooks.write

    def test_invalid_machine_keeps_filtered_hook_identity_and_local_edits(self):
        self.bootstrap()
        self.apply()
        self.machine.write_text('version = 999\n', encoding='utf-8')
        state_path = Path(str(self.machine) + '.state/state.json')
        state_before = state_path.read_bytes()
        machine_before = self.machine.read_bytes()
        codex_before = self.target().read_bytes()
        with patch.object(Git, 'run', side_effect=AssertionError('Status must stay offline')):
            report = self.call('status', '--agent', 'claude')
        self.assertTrue(report['saved_only'])
        self.assertEqual([item['item'] for item in report['items']], ['observer:hook@claude'])
        self.assertEqual(report['items'][0]['hook_event'], 'SessionEnd')
        self.assertEqual(report['items'][0]['installation'], 'matches-last-apply')
        document = self.document('claude')
        document['hooks']['SessionEnd'][0]['hooks'][0]['command'] = 'echo local edit'
        self.write(document, 'claude')
        edited = self.target('claude').read_bytes()
        report = self.call('status', '--agent', 'claude')
        self.assertEqual(report['items'][0]['installation'], 'modified-locally')
        self.assertEqual(self.target('claude').read_bytes(), edited)
        self.assertEqual(self.target().read_bytes(), codex_before)
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(self.machine.read_bytes(), machine_before)


class OrphanedSettings(unittest.TestCase):
    setUp = test_settings.StagedSettings.setUp
    call = test_settings.StagedSettings.call
    bootstrap = test_settings.StagedSettings.bootstrap
    apply = test_settings.StagedSettings.apply

    def test_removed_declaration_keeps_settings_status_and_reports_damaged_stage(self):
        self.apply()
        self.catalog.write_text('version = 2\n', encoding='utf-8')
        self.target.write_text('color = "local"\ncount = 1\n', encoding='utf-8')
        state_path = Path(str(self.machine) + '.state/state.json')
        state_before = state_path.read_bytes()
        target_before = self.target.read_bytes()
        report = self.call('status')
        item, = report['items']
        self.assertEqual(item['item'], 'editor:settings')
        self.assertEqual(item['status'], 'orphaned-or-source-unavailable')
        self.assertEqual(item['installation'], 'managed')
        self.stage.write_text('invalid = [', encoding='utf-8')
        item, = self.call('status')['items']
        self.assertEqual(item['installation'], 'unreadable')
        self.assertEqual(self.stage.read_text(encoding='utf-8'), 'invalid = [')
        self.assertEqual(self.target.read_bytes(), target_before)
        self.assertEqual(state_path.read_bytes(), state_before)
