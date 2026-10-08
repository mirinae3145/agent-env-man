"""Platform requirements do not invalidate a shared catalog or weaken ownership."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import patch

import tomlkit

from agent_env_man import automation, payload_links, self_update
from agent_env_man.model import Config, Error
from agent_env_man.storage import fingerprint
import test_directories


class PlatformPayloadPolicy(unittest.TestCase):
    setUp = test_directories.Directories.setUp
    git = test_directories.Directories.git
    commit = test_directories.Directories.commit
    repository = test_directories.Directories.repository
    save_catalog = test_directories.Directories.save_catalog
    run_cli = test_directories.Directories.run_cli
    write = test_directories.Directories.write
    bootstrap = test_directories.Directories.bootstrap
    manager = test_directories.Directories.manager

    def windows(self):
        # Patch only the capability module; keep host filesystem and subprocess APIs real.
        return patch.object(payload_links, 'os', SimpleNamespace(name='nt'))

    def mixed(self, *, shared=False):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        if not shared:
            other = self.repository('other', 'files')
            self.document['sources']['other'] = {'type': 'git', 'repository': str(other)}
        self.document['directories']['portable'] = {
            'source': 'store' if shared else 'other', 'subdir': 'skills/report' if shared else 'files',
            'install': {'root': 'personal', 'destination': 'portable', 'mode': 'copy'}}
        self.write()
        self.bootstrap()
        self.document['directories']['cases']['preserve_symlinks'] = True
        self.write()

    def test_independent_selection_and_status_with_mixed_catalog(self):
        self.mixed()
        with self.windows():
            self.run_cli('bootstrap', '--item', 'portable')
            self.run_cli('update', 'portable')
            self.run_cli('apply', '--item', 'portable')
            report = self.run_cli('status')
        items = {entry['item']: entry for entry in report['items']}
        self.assertEqual(items['portable:directory']['status'], 'current')
        self.assertEqual(items['cases:directory']['status'], 'unavailable')
        self.assertIn('Windows', items['cases:directory']['error'])
        self.assertNotIn('catalog_error', report)
        self.assertFalse(self.target.exists())

    def test_bulk_and_direct_operations_refuse_before_content_changes(self):
        self.mixed()
        before = fingerprint(self.checkouts)
        state = deepcopy(self.manager().state.data['items'])
        config = self.config.read_bytes()
        with self.windows():
            for args in [('bootstrap',), ('apply',), ('apply', '--item', 'cases', '--dry-run'),
                         ('update',), ('update', 'cases'), ('sync', '--item', 'portable'),
                         ('publish', 'portable', 'cases', '--dry-run'),
                         ('publish', 'cases', '--from-copy', '--dry-run')]:
                with self.subTest(args=args):
                    self.assertIn('Windows', str(self.run_cli(*args, code=1)))
                    self.assertEqual(fingerprint(self.checkouts), before)
                    self.assertEqual(self.manager().state.data['items'], state)
                    self.assertEqual(self.config.read_bytes(), config)
                    self.assertFalse((self.destination / 'portable').exists())

    def test_initial_bootstrap_refuses_before_machine_binding(self):
        self.document['directories']['cases']['preserve_symlinks'] = True
        self.write()
        with self.windows():
            result = self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}', code=1)
        self.assertIn('Windows', str(result))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkout.exists())

    def test_shared_source_is_still_guarded_when_unsupported_item_unselected(self):
        self.mixed(shared=True)
        with self.windows():
            for args in [('bootstrap', '--item', 'portable'), ('update', 'portable'),
                         ('publish', 'portable', '--dry-run')]:
                self.assertIn('cases:directory', str(self.run_cli(*args, code=1)))
            # Applying a prepared independent subtree does not mutate the shared source.
            self.run_cli('apply', '--item', 'portable')

    def test_full_defaults_to_failure_and_explicit_skip_runs_independent_content(self):
        self.mixed()
        with self.windows():
            report, failed = automation.full_content(self.manager(), 30)
            self.assertTrue(failed)
            self.assertIn('Windows', report['error'])
            self.assertFalse((self.destination / 'portable').exists())
            self.run_cli('setup', '--automation-skip-unsupported')
            preview, failed = automation.full_content(self.manager(), 30, dry_run=True)
            self.assertFalse(failed)
            self.assertEqual(preview['sources'], ['portable'])
            self.assertEqual(preview['excluded'][0]['item'], 'cases:directory')
            self.assertFalse((self.destination / 'portable').exists())
            report, failed = automation.full_content(self.manager(), 30)
            self.assertFalse(failed)
            self.assertEqual(report['excluded'], preview['excluded'])
            self.assertEqual(report['status'], 'completed')
            self.assertFalse(self.target.exists())
            self.assertTrue((self.destination / 'portable/SKILL.md').is_file())

    def test_full_skip_does_not_bypass_shared_checkout_guards(self):
        self.mixed(shared=True)
        self.run_cli('setup', '--automation-skip-unsupported')
        with self.windows():
            report, failed = automation.full_content(self.manager(), 30)
        self.assertTrue(failed)
        self.assertIn('Windows', report['error'])
        self.assertEqual(report['excluded'][0]['item'], 'cases:directory')
        self.assertFalse((self.destination / 'portable').exists())

    def test_full_all_excluded_and_manual_exclusion_remain_distinct(self):
        self.mixed()
        self.document['directories']['portable']['update'] = {'trigger': []}
        self.write()
        self.run_cli('setup', '--automation-skip-unsupported')
        with self.windows():
            report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed)
        self.assertEqual(report['status'], 'skipped')
        self.assertEqual(report['excluded'][1]['reason'], 'manual')

    def test_policies_report_failure_continue_independent_item_and_throttle(self):
        self.mixed()
        for entry in self.document['directories'].values():
            entry['update'] = {'trigger': ['agent-start'], 'action': 'sync', 'min_interval': 3600}
        self.write()
        before = self.manager().state.data
        with self.windows():
            preview = self.run_cli('auto', '--trigger', 'agent-start', '--dry-run', code=1)
            self.assertEqual([entry['status'] for entry in preview], ['failed', 'planned'])
            self.assertEqual(self.manager().state.data, before)
            result = self.run_cli('auto', '--trigger', 'agent-start', code=1)
            self.assertEqual([entry['status'] for entry in result], ['failed', 'synced'])
            result = self.run_cli('auto', '--trigger', 'agent-start')
            self.assertEqual([entry['status'] for entry in result], ['throttled', 'throttled'])

    def full_mode(self):
        document = tomlkit.parse(self.config.read_text())
        document['self_update'] = {'mode': 'off', 'python': sys.executable,
            'uv': str(self.root / 'uv'), 'tool_dir': str(self.root / 'tools'), 'bin_dir': str(self.root / 'bin')}
        document['automation'] = {'mode': 'full', 'trigger': ['interval'], 'min_interval': 3600}
        self.config.write_text(tomlkit.dumps(document))

    def test_full_cli_preview_reports_local_failure_or_exclusions_without_writes(self):
        self.mixed()
        self.full_mode()
        with self.windows():
            before = deepcopy(self.manager().state.data)
            failed = self.run_cli('automation', '--trigger', 'interval', '--dry-run', code=1)
            self.assertEqual(failed['content']['status'], 'failed')
            self.assertEqual(self.manager().state.data, before)
            self.run_cli('setup', '--automation-skip-unsupported')
            before = deepcopy(self.manager().state.data)
            preview = self.run_cli('automation', '--trigger', 'interval', '--dry-run')
            self.assertEqual(preview['content']['excluded'][0]['item'], 'cases:directory')
            self.assertFalse(preview['content']['network'])
            self.assertEqual(self.manager().state.data, before)
            self.assertFalse(automation.result_path(self.manager().config).exists())
            self.assertFalse((self.destination / 'portable').exists())

    def test_full_skip_retains_ordinary_payload_failures(self):
        self.mixed()
        self.run_cli('setup', '--automation-skip-unsupported')
        self.document['directories']['portable']['subdir'] = 'absent'
        self.write()
        with self.windows():
            report, failed = automation.full_content(self.manager(), 30)
        self.assertTrue(failed)
        self.assertEqual(len(report['excluded']), 1)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse((self.destination / 'portable').exists())

    def test_external_sources_refuse_both_install_modes_without_links(self):
        self.document['sources']['store'] = {'type': 'external'}
        self.document['directories']['cases']['subdir'] = '.'
        self.write()
        external = self.root / 'external'
        external.mkdir()
        (external / 'ordinary.txt').write_text('regular content')
        self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}',
                     '--external', f'store={external}')
        self.document['directories']['cases']['preserve_symlinks'] = True
        for mode in ('copy', 'link'):
            self.document['directories']['cases']['install']['mode'] = mode
            self.write()
            with self.subTest(mode=mode), self.windows():
                self.assertIn('Windows', str(self.run_cli('apply', code=1)))
                self.assertIn('Windows', str(self.run_cli('update', code=1)))
                self.assertFalse(self.target.exists())
                self.assertEqual((external / 'ordinary.txt').read_text(), 'regular content')

    def test_saved_policy_refuses_detach_even_without_catalog(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        manager = self.manager()
        manager.state.data['items']['cases:directory']['preserve_symlinks'] = True
        manager.state.save()
        self.catalog.unlink()
        before = deepcopy(manager.state.data)
        contents = fingerprint(self.target)
        with self.windows():
            self.assertIn('Windows', str(self.run_cli('detach', 'cases', code=1)))
        self.assertEqual(self.manager().state.data, before)
        self.assertEqual(fingerprint(self.target), contents)

    def test_orphaned_live_link_still_blocks_shared_source(self):
        self.mixed(shared=True)
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        manager = self.manager()
        item = next(item for item in manager.items() if item.key == 'cases:directory')
        # A saved live record is sufficient for preflight; no link privileges are needed.
        manager.state.data['items'][item.key] = {'kind': 'directory', 'mode': 'link',
            'source': str(item.source), 'source_name': item.source_name, 'relative': item.relative,
            'target': str(item.target), 'preserve_symlinks': True, 'detached': False}
        manager.state.save()
        del self.document['directories']['cases']
        self.write()
        with self.windows():
            self.assertIn('cases:directory', str(self.run_cli('update', 'portable', code=1)))
        self.assertFalse(self.target.exists())

    def test_recovery_preserves_unsupported_journal_and_files(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        manager = self.manager()
        stage, backup = self.target.parent / '.stage', self.target.parent / '.backup'
        stage.mkdir(parents=True)
        (stage / 'data').write_text('retained')
        manager.state.data['pending'] = {'target': str(self.target), 'stage': str(stage),
            'backup': str(backup), 'preserve_symlinks': True, 'relative': 'cases',
            'before': {'kind': 'missing'}, 'after': {'kind': 'directory', 'hash': fingerprint(stage)}}
        manager.state.save()
        before = deepcopy(manager.state.data)
        with self.windows():
            self.assertIn('Windows', str(self.run_cli('recover', code=1)))
        self.assertEqual(self.manager().state.data, before)
        self.assertEqual((stage / 'data').read_text(), 'retained')

    def test_git_catalog_update_can_introduce_unsupported_declaration(self):
        self.mixed()
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        self.git(self.catalog.parent, 'init', '-b', 'main')
        self.commit(self.catalog.parent)
        self.run_cli('bootstrap', '--catalog-repository', self.catalog.parent,
                     '--catalog-path', self.catalog.name, '--item', 'portable')
        self.document['directories']['cases']['preserve_symlinks'] = True
        self.write()
        self.commit(self.catalog.parent)
        self.full_mode()
        manager = self.manager()
        self_update.write_json(automation.result_path(manager.config),
            {'token': 'test', 'status': 'continuing',
             'binding': self_update.full_binding(manager.config.doc), 'stages': {'tool': {'status': 'disabled'}}})
        with self.windows():
            result = self.run_cli('_full-run', '--token', 'test', code=1)
            self.assertEqual(result['stages']['catalog']['status'], 'updated')
            self.assertEqual(result['stages']['content']['status'], 'failed')
            self.assertFalse((self.destination / 'portable').exists())
            self.run_cli('catalog', 'update')
            self.run_cli('apply', '--item', 'portable')
            report = self.run_cli('status')
        self.assertEqual(report['items'][0]['status'], 'unavailable')

    def test_option_setup_preserves_and_resets_without_integrations(self):
        self.bootstrap()
        self.assertFalse(Config(self.config).automation['skip_unsupported'])
        self.run_cli('setup', '--automation-skip-unsupported', '--dry-run')
        self.assertFalse(Config(self.config).automation['skip_unsupported'])
        self.run_cli('setup', '--automation-skip-unsupported')
        self.run_cli('setup', '--automation', 'off')
        self.assertTrue(Config(self.config).automation['skip_unsupported'])
        self.run_cli('setup', '--no-automation-skip-unsupported')
        self.assertFalse(Config(self.config).automation['skip_unsupported'])
        for value in ('true', 1, []):
            with self.subTest(value=value), self.assertRaisesRegex(Error, 'Boolean'):
                automation.policy({'skip_unsupported': value})


if __name__ == '__main__':
    unittest.main()
