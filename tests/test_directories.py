"""General directory delivery, installation and sharing preserve existing contracts."""

from copy import deepcopy
from pathlib import Path
import shutil
from unittest.mock import patch
import unittest

import tomlkit

from agent_env_man import automation
from agent_env_man.git_source import Git
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State
from agent_env_man.updates import startup_skills_changed
import test_skill_catalog as skill_tests


class Directories(unittest.TestCase):
    git = skill_tests.SkillCatalog.git
    commit = skill_tests.SkillCatalog.commit
    repository = skill_tests.SkillCatalog.repository
    save_catalog = skill_tests.SkillCatalog.save_catalog
    run_cli = skill_tests.SkillCatalog.run_cli
    require_links = skill_tests.SkillCatalog.require_links

    def setUp(self):
        skill_tests.SkillCatalog.setUp(self)
        (self.repo / 'cases').mkdir()
        (self.repo / 'cases/first.md').write_text('First case\n', encoding='utf-8')
        self.commit(self.repo)
        self.document = {'version': 2, 'sources': {'store': {'type': 'git', 'repository': str(self.repo)}},
                         'directories': {'cases': {'source': 'store', 'subdir': 'cases',
                                                   'install': {'root': 'personal', 'destination': 'agent-loop'}}}}
        self.write()
        self.target = self.destination / 'agent-loop'
        self.checkout = self.checkouts / '.aem-repositories/store'

    def write(self):
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')

    def bootstrap(self):
        return self.run_cli('bootstrap', self.catalog, '--checkout-root', self.checkouts,
                            '--root', f'personal={self.destination}')

    def external(self, *, mode='copy'):
        self.external_root = self.root / 'external'
        self.external_root.mkdir()
        (self.external_root / 'first.md').write_text('External case\n', encoding='utf-8')
        self.document['sources']['store'] = {'type': 'external'}
        self.document['directories']['cases']['subdir'] = '.'
        self.document['directories']['cases']['install']['mode'] = mode
        self.write()
        return self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}',
                            '--external', f'store={self.external_root}')

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def test_defaults_schema_namespace_and_mode_override(self):
        before = deepcopy(self.document)
        config = Config(self.config, document={'version': 1, 'catalog': str(self.catalog),
                        'roots': {'personal': str(self.destination)}}, catalog_document=self.document)
        item, = config.declarations(config.sources['cases'])
        self.assertEqual((item.key, item.mode, item.target), ('cases:directory', 'link', self.target))
        self.assertEqual(config.update_policies()['cases']['trigger'], ['manual'])
        self.assertEqual(config.full_update_policies()['cases']['trigger'], ['shell-start', 'agent-start', 'interval'])
        self.assertEqual(self.document, before)
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        machine = tomlkit.parse(self.config.read_text(encoding='utf-8'))
        machine['modes'] = {'cases': 'link'}
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.assertEqual(self.manager().items()[0].mode, 'link')
        self.document['skills'] = {'cases': {'source': 'store'}}
        self.write()
        with self.assertRaisesRegex(Error, 'collides'):
            Config(self.config).catalog()

    def test_invalid_declarations_fail_before_network_or_machine_write(self):
        variants = [({'subdir': '../cases'}, None), ({'entry': 'first.md'}, None),
                    ({'source': 'missing'}, None), ({}, {}),
                    ({}, {'root': 'missing'}), ({}, {'root': 'personal', 'destination': '.'}),
                    ({}, {'root': 'personal', 'mode': 'other'})]
        original = deepcopy(self.document)
        for fields, install in variants:
            with self.subTest(fields=fields, install=install):
                self.document = deepcopy(original)
                self.document['directories']['cases'].update(fields)
                if install is not None:
                    self.document['directories']['cases']['install'] = install
                self.write()
                with patch.object(Git, 'run', side_effect=AssertionError('Unexpected Git operation')):
                    self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}', code=1)
                self.assertFalse(self.config.exists())

    def test_link_is_agent_independent_and_locate_needs_no_entry_file(self):
        self.require_links()
        self.assertEqual(self.bootstrap()['skills'][0]['directory'], 'cases')
        self.run_cli('apply', '--item', 'cases', '--agent', 'claude')
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')
        self.assertFalse((self.target / 'SKILL.md').exists())
        self.assertEqual(self.run_cli('locate', 'cases', '--agent', 'claude')['root'], str(self.checkout / 'cases'))
        self.assertEqual(self.run_cli('status', '--agent', 'claude')['items'][0]['item'], 'cases:directory')
        self.run_cli('detach', 'cases', '--agent', 'claude')
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.run_cli('apply'), [])
        self.catalog.unlink()
        location = self.run_cli('locate', 'cases', '--agent', 'claude')
        self.assertEqual((location['entry'], location['location'], location['detached']), (str(self.target), 'copy', True))
        self.assertEqual(self.run_cli('status', '--agent', 'claude')['items'][0]['item'], 'cases:directory')

    def test_locate_source_before_install_and_replaced_link_refusal(self):
        self.require_links()
        self.bootstrap()
        self.assertEqual(self.run_cli('locate', 'cases')['entry'], str(self.checkout / 'cases'))
        self.run_cli('apply')
        self.target.unlink()
        self.target.mkdir()
        self.assertIn('link was replaced', self.run_cli('locate', 'cases', code=1))
        self.assertEqual(self.run_cli('locate', 'cases', '--source')['root'], str(self.checkout / 'cases'))

    def test_copy_local_changes_are_preserved_and_not_published(self):
        self.external()
        self.run_cli('apply', '--item', 'cases')
        (self.target / 'local.md').write_text('Local only', encoding='utf-8')
        (self.external_root / 'first.md').write_text('Upstream change', encoding='utf-8')
        self.assertIn('locally modified copy', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertFalse((self.external_root / 'local.md').exists())
        self.assertEqual(self.run_cli('publish', 'cases', '--dry-run', code=1)[0]['status'], 'failed')
        self.run_cli('detach', 'cases')
        self.assertEqual((self.target / 'local.md').read_text(encoding='utf-8'), 'Local only')
        self.assertEqual(self.run_cli('locate', 'cases')['location'], 'copy')

    def test_git_root_copy_excludes_git_and_preserves_ignored_files(self):
        self.document['directories']['cases']['subdir'] = '.'
        self.document['directories']['cases']['install']['mode'] = 'copy'
        (self.repo / '.gitignore').write_text('cache/\n', encoding='utf-8')
        self.commit(self.repo)
        self.write()
        self.bootstrap()
        (self.checkout / 'cache').mkdir()
        (self.checkout / 'cache/value').write_text('Keep', encoding='utf-8')
        self.run_cli('apply')
        self.assertFalse((self.target / '.git').exists())
        self.assertEqual((self.target / 'cache/value').read_text(encoding='utf-8'), 'Keep')
        self.run_cli('detach', 'cases')
        self.assertTrue((self.target / 'cache/value').exists())

    def test_root_link_detach_materializes_without_git(self):
        self.require_links()
        self.document['directories']['cases']['subdir'] = '.'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        self.run_cli('detach', 'cases')
        self.assertFalse(self.target.is_symlink())
        self.assertFalse((self.target / '.git').exists())
        self.assertTrue((self.target / 'cases/first.md').exists())

    def test_default_destination_component_selection_and_offline_preview(self):
        self.external()
        del self.document['directories']['cases']['install']['destination']
        self.document['directories']['cases']['update'] = {'trigger': ['agent-start']}
        self.write()
        state_file = self.manager().state.path
        before = state_file.read_bytes() if state_file.exists() else None
        with patch.object(Git, 'fetch', side_effect=AssertionError('Preview fetched')):
            self.assertEqual(self.run_cli('auto', '--trigger', 'agent-start', '--dry-run')[0]['status'], 'planned')
            self.run_cli('apply', '--item', 'cases:directory', '--dry-run')
        self.assertEqual(state_file.read_bytes() if state_file.exists() else None, before)
        self.assertFalse((self.destination / 'cases').exists())
        self.run_cli('apply', '--item', 'cases:directory')
        self.assertTrue((self.destination / 'cases/first.md').exists())

    def test_external_empty_directory_and_invalid_payload_preservation(self):
        self.external()
        (self.external_root / 'first.md').unlink()
        self.run_cli('apply')
        self.assertTrue(self.target.is_dir())
        self.assertEqual(list(self.target.iterdir()), [])
        self.external_root.rmdir()
        self.external_root.write_text('Not a directory', encoding='utf-8')
        self.assertIn('source must be a directory', self.run_cli('apply', code=1))
        self.assertTrue(self.target.is_dir())

    def test_external_nested_link_is_refused_without_installation(self):
        self.require_links()
        self.external()
        (self.external_root / 'redirect').symlink_to(self.catalog)
        self.run_cli('apply', code=1)
        self.assertFalse(self.target.exists())

    def test_git_auto_check_and_sync_filter_keep_installation_scope(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.document['directories']['other'] = {'source': 'store', 'subdir': 'cases',
            'install': {'root': 'personal', 'mode': 'copy'}, 'update': {'trigger': []}}
        self.document['directories']['cases']['update'] = {'trigger': ['agent-start'], 'action': 'check'}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        (self.repo / 'cases/first.md').write_text('Remote case', encoding='utf-8')
        self.commit(self.repo)
        report = self.run_cli('auto', '--trigger', 'agent-start', '--item', 'cases')
        self.assertEqual(report[0]['status'], 'checked')
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')
        self.run_cli('sync', '--item', 'cases')
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'Remote case')
        self.assertEqual((self.destination / 'other/first.md').read_text(encoding='utf-8'), 'First case\n')

    def test_skill_check_and_directory_sync_share_fetch_within_each_event(self):
        self.document['skills'] = {'observe': {'source': 'store', 'subdir': 'skills/report',
            'install': {'root': 'personal', 'mode': 'copy'}, 'update': {'action': 'check'}}}
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.document['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 0}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        original_skill = (self.destination / 'observe/SKILL.md').read_bytes()
        (self.repo / 'cases/first.md').write_text('Shared fetch', encoding='utf-8')
        (self.repo / 'skills/report/SKILL.md').write_text('# Received skill\n', encoding='utf-8')
        self.commit(self.repo)
        original_run = Git.run
        fetches = []

        def record(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                fetches.append(path)
            return original_run(git, path, *args, **kwargs)

        with patch.object(Git, 'run', record):
            report = self.run_cli('auto', '--trigger', 'agent-start')
            self.assertEqual([entry['status'] for entry in report], ['checked', 'synced'])
            self.assertEqual(fetches, [self.checkout])
            self.run_cli('auto', '--trigger', 'agent-start')
            self.assertEqual(fetches, [self.checkout, self.checkout])
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'Shared fetch')
        self.assertEqual((self.destination / 'observe/SKILL.md').read_bytes(), original_skill)

    def test_root_link_update_rejects_git_link_and_preserves_checkout(self):
        self.require_links()
        self.document['directories']['cases']['subdir'] = '.'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.git(self.repo, 'update-index', '--add', '--cacheinfo',
                 '120000', self.git(self.repo, 'hash-object', '-w', 'cases/first.md'), 'redirect')
        self.git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Git link')
        self.assertIn('Git symlink or submodule', self.run_cli('update', 'cases', code=1)[0]['error'])
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertTrue((self.target / 'cases/first.md').exists())

    def test_ignored_file_collision_is_preserved_during_update(self):
        self.require_links()
        (self.repo / '.gitignore').write_text('cases/cache.txt\n', encoding='utf-8')
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli('apply')
        (self.target / 'cache.txt').write_text('Local cache', encoding='utf-8')
        (self.repo / 'cases/cache.txt').write_text('Incoming file', encoding='utf-8')
        self.git(self.repo, 'add', '-f', 'cases/cache.txt')
        self.git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Tracked cache')
        self.assertEqual(self.run_cli('update', 'cases', code=1)[0]['status'], 'failed')
        self.assertEqual((self.target / 'cache.txt').read_text(encoding='utf-8'), 'Local cache')

    def test_two_devices_record_publish_and_update(self):
        self.require_links()
        remote = self.root / 'remote.git'
        remote.mkdir()
        self.git(remote, 'init', '--bare')
        self.git(self.repo, 'push', str(remote), 'main')
        self.document['sources']['store'] = {'type': 'git', 'repository': str(remote), 'branch': 'main'}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        other_config = self.root / 'other.toml'
        other_root = self.root / 'other-targets'
        self.run_cli('bootstrap', self.catalog, '--root', f'personal={other_root}', config=other_config)
        self.run_cli('apply', config=other_config)
        self.git(self.checkout, 'config', 'user.name', 'Test')
        self.git(self.checkout, 'config', 'user.email', 'test@example.invalid')
        (self.target / 'device-one.md').write_text('Shared case', encoding='utf-8')
        self.assertEqual(self.run_cli('publish', 'cases', '-m', 'Record case')[0]['status'], 'published')
        self.run_cli('update', 'cases', config=other_config)
        self.assertEqual((other_root / 'agent-loop/device-one.md').read_text(encoding='utf-8'), 'Shared case')
        (other_root / 'agent-loop/local.md').write_text('Unpublished', encoding='utf-8')
        self.assertEqual(self.run_cli('update', 'cases', config=other_config, code=1)[0]['status'], 'failed')

    def test_update_guards_orphaned_shared_live_links(self):
        self.require_links()
        self.document['skills'] = {'report': {'source': 'store', 'subdir': 'skills/report', 'install': {'root': 'personal'}}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        self.document.pop('directories')
        self.write()
        shutil.rmtree(self.repo / 'cases')
        (self.repo / 'cases').write_text('Now a file', encoding='utf-8')
        self.commit(self.repo)
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        report = self.run_cli('update', 'report', code=1)
        self.assertIn('directory must be a tracked Git tree', report[0]['error'])
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')
        self.run_cli('detach', 'cases')
        self.run_cli('update', 'report')

    def test_bootstrap_validates_unselected_shared_directory_and_git_modes(self):
        self.document['directories']['cases']['subdir'] = 'missing'
        self.document['skills'] = {'report': {'source': 'store', 'subdir': 'skills/report', 'install': {'root': 'personal'}}}
        self.write()
        result = self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}', '--item', 'report', code=1)
        self.assertEqual(result['skills'][0]['status'], 'failed')
        self.assertFalse(self.checkout.exists())
        self.document['directories']['cases']['subdir'] = 'cases'
        self.write()
        self.git(self.repo, 'update-index', '--add', '--cacheinfo',
                 '120000', self.git(self.repo, 'hash-object', '-w', 'cases/first.md'), 'cases/link')
        self.git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Git link')
        result = self.run_cli('bootstrap', self.catalog, '--checkout-root', self.checkouts,
                              '--root', f'personal={self.destination}', code=1)
        self.assertEqual(result['skills'][0]['status'], 'failed')

    def test_external_check_sync_throttle_and_empty_trigger(self):
        self.external()
        self.document['updates'] = {'defaults': {'trigger': ['shell-start'], 'min_interval': 0},
                                    'policies': {'observe': {'action': 'check'}}}
        self.document['directories']['cases']['update'] = {'policy': 'observe', 'min_interval': 600}
        self.write()
        with patch.object(Git, 'run', side_effect=AssertionError('External operation used Git')):
            report = self.run_cli('auto', '--trigger', 'shell-start')
        self.assertEqual((report[0]['directory'], report[0]['status']), ('cases', 'external-no-fetch'))
        self.assertFalse(self.target.exists())
        self.assertEqual(self.run_cli('auto', '--trigger', 'shell-start')[0]['status'], 'throttled')
        self.document['directories']['cases']['update'] = {'action': 'sync', 'min_interval': 0}
        self.write()
        self.assertEqual(self.run_cli('auto', '--trigger', 'shell-start')[0]['status'], 'synced')
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'External case\n')
        self.document['directories']['cases']['update']['trigger'] = []
        self.write()
        self.assertEqual(self.run_cli('auto', '--trigger', 'shell-start')[0]['status'], 'not-triggered')
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['excluded'], [{'source': 'cases', 'reason': 'manual'}])

    def test_full_mode_default_includes_directory_and_preserves_detach(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['status'], 'completed')
        self.assertTrue((self.target / 'first.md').exists())
        self.run_cli('detach', 'cases')
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['excluded'], [{'source': 'cases', 'reason': 'detached'}])

    def test_full_mode_receives_new_directory_in_existing_shared_checkout(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        (self.repo / 'new-cases').mkdir()
        (self.repo / 'new-cases/new.md').write_text('New case', encoding='utf-8')
        (self.repo / 'cases/first.md').write_text('Received case', encoding='utf-8')
        self.commit(self.repo)
        self.document['directories']['new'] = {'source': 'store', 'subdir': 'new-cases',
                                               'install': {'root': 'personal', 'mode': 'copy'}}
        self.write()
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), self.git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'Received case')
        self.assertEqual((self.destination / 'new/new.md').read_text(encoding='utf-8'), 'New case')

    def test_update_rejects_unselected_directory_replaced_by_file(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.document['directories']['other'] = {'source': 'store', 'subdir': 'skills/report',
                                                 'install': {'root': 'personal', 'mode': 'copy'}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        ownership = deepcopy(self.manager().state.data['items'])
        shutil.rmtree(self.repo / 'cases')
        (self.repo / 'cases').write_text('Invalid directory', encoding='utf-8')
        self.commit(self.repo)
        report = self.run_cli('update', 'other', code=1)
        self.assertIn('directory must be a tracked Git tree', report[0]['error'])
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertEqual(self.manager().state.data['items'], ownership)
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')

    def test_update_rejects_unselected_directory_git_links_and_submodules(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.document['directories']['other'] = {'source': 'store', 'subdir': 'skills/report',
                                                 'install': {'root': 'personal', 'mode': 'copy'}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        ownership = deepcopy(self.manager().state.data['items'])
        blob = self.git(self.repo, 'hash-object', '-w', 'cases/first.md')
        for mode, object_id in (('120000', blob), ('160000', previous)):
            with self.subTest(mode=mode):
                self.git(self.repo, 'update-index', '--add', '--cacheinfo', mode, object_id, 'cases/redirect')
                self.git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                         'commit', '-m', 'Invalid directory entry')
                report = self.run_cli('update', 'other', code=1)
                self.assertIn('Git symlink or submodule', report[0]['error'])
                self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
                self.assertEqual(self.manager().state.data['items'], ownership)
                self.assertFalse((self.target / 'redirect').exists())

    def test_full_mode_preserves_dirty_directory_source(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        ownership = deepcopy(self.manager().state.data['items'])
        (self.checkout / 'cases/first.md').write_text('Local edit', encoding='utf-8')
        (self.repo / 'cases/first.md').write_text('Remote edit', encoding='utf-8')
        self.commit(self.repo)
        with patch.object(Git, 'fetch', side_effect=AssertionError('Dirty source fetched')):
            report, failed = automation.full_content(self.manager(), 30)
        self.assertTrue(failed, report)
        self.assertIn('dirty checkout', report['prepare'][0]['error'])
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertEqual((self.checkout / 'cases/first.md').read_text(encoding='utf-8'), 'Local edit')
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')
        self.assertEqual(self.manager().state.data['items'], ownership)

    def test_full_mode_preserves_diverged_directory_history(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        ownership = deepcopy(self.manager().state.data['items'])
        (self.checkout / 'cases/first.md').write_text('Local commit', encoding='utf-8')
        self.commit(self.checkout)
        previous = self.git(self.checkout, 'rev-parse', 'HEAD')
        (self.repo / 'cases/first.md').write_text('Remote commit', encoding='utf-8')
        self.commit(self.repo)
        report, failed = automation.full_content(self.manager(), 30)
        self.assertTrue(failed, report)
        self.assertIn('diverged', report['update'][0]['error'])
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), previous)
        self.assertEqual((self.checkout / 'cases/first.md').read_text(encoding='utf-8'), 'Local commit')
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'First case\n')
        self.assertEqual(self.manager().state.data['items'], ownership)

    def test_full_mode_new_directory_preserves_locally_modified_copy(self):
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        ownership = deepcopy(self.manager().state.data['items'])
        (self.target / 'first.md').write_text('Local copy edit', encoding='utf-8')
        (self.repo / 'new-cases').mkdir()
        (self.repo / 'new-cases/new.md').write_text('New case', encoding='utf-8')
        self.commit(self.repo)
        self.document['directories']['new'] = {'source': 'store', 'subdir': 'new-cases',
                                               'install': {'root': 'personal', 'mode': 'copy'}}
        self.write()
        with self.assertRaisesRegex(Error, 'locally modified copy'):
            automation.full_content(self.manager(), 30)
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'Local copy edit')
        self.assertFalse((self.destination / 'new').exists())
        self.assertEqual(self.manager().state.data['items'], ownership)

    def test_target_overlap_and_mode_change_require_detach(self):
        self.external()
        self.run_cli('apply')
        self.document['directories']['nested'] = {'source': 'store', 'install': {'root': 'personal', 'destination': 'agent-loop/nested'}}
        self.write()
        self.assertIn('Overlapping targets', self.run_cli('apply', code=1))
        del self.document['directories']['nested']
        self.document['directories']['cases']['install']['mode'] = 'link'
        self.write()
        self.assertIn('detach before reconfiguration', self.run_cli('apply', code=1))

    def test_failed_copy_replacement_restores_original_and_clears_journal(self):
        self.external()
        self.run_cli('apply')
        (self.external_root / 'first.md').write_text('New case', encoding='utf-8')
        from agent_env_man import manager as manager_module
        original_replace = manager_module.os.replace
        def fail_stage(source, target):
            if Path(source).name.startswith('.aem-stage-') and Path(target) == self.target:
                raise OSError('Simulated interrupted replacement')
            return original_replace(source, target)
        with patch.object(manager_module.os, 'replace', side_effect=fail_stage):
            self.run_cli('apply', '--item', 'cases', code=1)
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'External case\n')
        self.assertIsNone(self.manager().state.data['pending'])
        self.run_cli('recover')
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / 'first.md').read_text(encoding='utf-8'), 'New case')

    def test_unavailable_link_does_not_fall_back_to_copy(self):
        self.external(mode='link')
        with patch.object(Path, 'symlink_to', side_effect=OSError('No privilege')):
            self.assertIn('Cannot create a symbolic link', self.run_cli('apply', code=1))
        self.assertFalse(self.target.exists())
        self.assertFalse(self.manager().state.data['items'])

    def test_directory_advancement_only_requests_reload_for_shared_skill_links(self):
        self.require_links()
        self.document['skills'] = {'report': {'source': 'store', 'subdir': 'skills/report', 'install': {'root': 'personal'}}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        manager = self.manager()
        outcome = [{'directory': 'cases', 'status': 'synced', 'previous_revision': 'before', 'revision': 'after', 'apply': []}]
        self.assertTrue(startup_skills_changed(outcome, manager.state.data['items'], 'codex', manager.config.sources))
        self.run_cli('detach', 'report')
        manager = self.manager()
        self.assertFalse(startup_skills_changed(outcome, manager.state.data['items'], 'codex', manager.config.sources))


if __name__ == '__main__':
    unittest.main()
