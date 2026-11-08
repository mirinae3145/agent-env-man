"""Catalog exclusions skip opaque metadata while preserving local ownership."""

import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import payload_links
from agent_env_man.catalog_schema import normalize
from agent_env_man.model import Error
from agent_env_man.payload_policy import effective, excluded
from agent_env_man.storage import fingerprint
import test_directories as directory_tests


class PayloadExclusions(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    require_links = directory_tests.Directories.require_links
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager

    def prepare(self, links=False):
        self.document['payload'] = {'defaults': {'exclude': ['**/._DAV']}}
        self.document['directories']['cases']['preserve_symlinks'] = links
        self.external()
        self.source = self.external_root
        (self.source / 'nested').mkdir()
        (self.source / 'nested/doc.md').write_text('original')
        for folder in (self.source / '._DAV', self.source / 'nested/._DAV'):
            folder.mkdir(); (folder / 'metadata').write_text('source metadata')
        self.run_cli('apply', '--item', 'cases')

    def test_hierarchy_anchoring_and_globstar(self):
        rules = effective(['**/._DAV'], ['cases/source-cache'], ['scratch', '**/*.tmp'], 'cases')
        for path in ('._DAV', 'nested/._DAV/file', 'source-cache', 'source-cache/file', 'scratch', 'a.tmp', 'nested/a.tmp'):
            self.assertTrue(excluded(path, rules), path)
        for path in ('nested/scratch', 'nested/source-cache', 'scratchpad', 'nested/a.md'):
            self.assertFalse(excluded(path, rules), path)
        self.assertFalse(excluded('', effective(['**'], [], [], '.')))

    def test_invalid_patterns_and_required_entries_rejected(self):
        for bad in ('/cache', '../cache', 'a/../b', 'a\\b', 'C:/cache', '!cache', '', 'a/**b', 'a//b'):
            self.document['payload'] = {'defaults': {'exclude': [bad]}}
            with self.subTest(pattern=bad), self.assertRaises(Error):
                normalize(self.document)
        for bad in ('**/*.md', 'SKILL.md', '**'):
            document = {'version': 2, 'sources': {'repo': {'type': 'git', 'repository': str(self.repo)}},
                        'payload': {'defaults': {'exclude': [bad]}}, 'skills': {'test': {'source': 'repo'}}}
            with self.subTest(pattern=bad), self.assertRaisesRegex(Error, 'required entry'):
                normalize(document)

    def test_catalog_source_relative_rules(self):
        self.document['sources']['store'] = {'type': 'external', 'exclude': ['cases/cache', 'outside']}
        self.document['directories']['cases']['exclude'] = ['scratch']
        self.document['directories']['cases']['install']['mode'] = 'copy'
        self.write()
        source = self.root / 'external'; (source / 'cases/cache').mkdir(parents=True)
        (source / 'cases/cache/file').write_text('excluded')
        (source / 'cases/keep').write_text('included')
        self.run_cli('bootstrap', self.catalog, '--root', f'personal={self.destination}', '--external', f'store={source}')
        self.run_cli('apply', '--item', 'cases')
        self.assertFalse((self.target / 'cache').exists())
        self.assertEqual((self.target / 'keep').read_text(), 'included')

    def test_excluded_metadata_not_copied_or_read(self):
        for links in (False, True):
            with self.subTest(links=links):
                if links:
                    self.document['directories']['cases']['preserve_symlinks'] = True; self.write()
                else:
                    self.prepare()
                if hasattr(os, 'mkfifo'):
                    os.mkfifo(self.source / '._DAV/fifo')
                self.run_cli('apply', '--item', 'cases')
                self.assertFalse((self.target / '._DAV').exists())
                self.assertFalse((self.target / 'nested/._DAV').exists())
                if hasattr(os, 'mkfifo'):
                    (self.source / '._DAV/fifo').unlink()

    def test_apply_preserves_local_excluded_entries(self):
        self.prepare(links=True)
        cache = self.target / 'nested/._DAV'; cache.mkdir()
        (cache / 'local').write_text('keep local')
        inode = cache.stat().st_ino
        (self.source / 'nested/doc.md').write_text('updated')
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'updated')
        self.assertEqual((cache / 'local').read_text(), 'keep local')
        self.assertEqual(cache.stat().st_ino, inode)
        self.assertFalse(list(self.target.parent.glob('.aem-retained-*')))
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')

    def test_changes_to_excluded_entries_do_not_conflict(self):
        self.prepare()
        cache = self.target / '._DAV'; cache.mkdir(); (cache / 'metadata').write_text('local')
        (self.source / '._DAV/metadata').write_text('source changed')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        preview = self.run_cli('publish', 'cases', '--from-copy', '--dry-run')
        self.assertFalse(preview[0]['collection'][0]['changed'])
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual((cache / 'metadata').read_text(), 'local')

    def test_included_local_edits_still_refused(self):
        self.prepare()
        (self.target / 'nested/doc.md').write_text('local edit')
        error = self.run_cli('apply', '--item', 'cases', code=1)
        self.assertIn('modified copy', error)
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'local edit')

    def test_apply_refuses_deleting_ancestor_of_excluded_entry(self):
        self.prepare()
        cache = self.target / 'nested/._DAV'; cache.mkdir(); (cache / 'local').write_text('keep')
        shutil.rmtree(self.source / 'nested')
        error = self.run_cli('apply', '--item', 'cases', code=1)
        self.assertIn('Cannot preserve excluded entry', error)
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_preserves_source_metadata_not_copy_metadata(self):
        self.prepare(links=True)
        cache = self.target / 'nested/._DAV'; cache.mkdir(); (cache / 'metadata').write_text('local metadata')
        source_inode = (self.source / 'nested/._DAV').stat().st_ino
        (self.target / 'nested/doc.md').write_text('local content')
        preview = self.run_cli('publish', 'cases', '--from-copy', '--dry-run')
        self.assertNotIn('nested/._DAV/metadata', preview[0]['collection'][0]['changes'])
        self.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual((self.source / 'nested/doc.md').read_text(), 'local content')
        self.assertEqual((self.source / 'nested/._DAV/metadata').read_text(), 'source metadata')
        self.assertEqual((self.source / 'nested/._DAV').stat().st_ino, source_inode)
        self.assertEqual((cache / 'metadata').read_text(), 'local metadata')

    def test_apply_failure_restores_content_and_metadata(self):
        self.prepare()
        cache = self.target / 'nested/._DAV'; cache.mkdir(); (cache / 'local').write_text('keep')
        (self.source / 'nested/doc.md').write_text('updated')
        from agent_env_man import manager as module
        real_replace = module.os.replace
        failed = False
        def fail(source, target, *args, **kwargs):
            nonlocal failed
            if Path(source).name.startswith('.aem-stage-') and Path(target) == self.target and not failed:
                failed = True
                raise OSError('injected replacement failure')
            return real_replace(source, target, *args, **kwargs)
        with patch.object(module.os, 'replace', side_effect=fail):
            self.run_cli('apply', '--item', 'cases', code=1)
        self.assertTrue(failed)
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_failure_restores_content_and_metadata(self):
        self.prepare()
        (self.target / 'nested/doc.md').write_text('local content')
        from agent_env_man import copy_publication as module
        real_replace = module.os.replace
        failed = False
        def fail(source, target, *args, **kwargs):
            nonlocal failed
            if Path(source).parent.name == 'stages' and Path(target) == self.source / 'nested' and not failed:
                failed = True; raise OSError('injected collection failure')
            return real_replace(source, target, *args, **kwargs)
        with patch.object(module.os, 'replace', side_effect=fail):
            self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertTrue(failed)
        self.assertEqual((self.source / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((self.source / 'nested/._DAV/metadata').read_text(), 'source metadata')
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'local content')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_excluded_directory_created_during_scan_is_ignored(self):
        self.prepare(links=True)
        shutil.rmtree(self.source / '._DAV')
        real_read = payload_links.os.read
        created = False
        def read(fd, size):
            nonlocal created
            block = real_read(fd, size)
            if block and not created:
                created = True; (self.source / '._DAV').mkdir()
            return block
        expected = fingerprint(self.source, preserve_symlinks=True, exclusions=(('', '**/._DAV'),))
        with patch.object(payload_links.os, 'read', side_effect=read):
            actual = fingerprint(self.source, preserve_symlinks=True, exclusions=(('', '**/._DAV'),))
        self.assertTrue(created)
        self.assertEqual(expected, actual)

    def test_included_directory_changes_during_scan_still_fail(self):
        self.prepare(links=True)
        real_read = payload_links.os.read
        created = False
        def read(fd, size):
            nonlocal created
            block = real_read(fd, size)
            if block and not created:
                created = True; (self.source / 'new-content').write_text('concurrent edit')
            return block
        with patch.object(payload_links.os, 'read', side_effect=read):
            with self.assertRaisesRegex(Error, 'changed during inspection'):
                fingerprint(self.source, preserve_symlinks=True, exclusions=(('', '**/._DAV'),))
        self.assertTrue(created)

    def test_policy_changes_require_apply_before_collection(self):
        self.prepare()
        self.document['directories']['cases']['exclude'] = ['scratch']; self.write()
        report = self.run_cli('status')['items'][0]
        self.assertEqual(report['status'], 'configuration-changed')
        report = self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertIn('apply before collection', report[0]['error'])
        self.run_cli('apply', '--item', 'cases')
        self.assertFalse(self.run_cli('publish', 'cases', '--from-copy', '--dry-run')[0]['collection'][0]['changed'])

    def test_collection_refuses_deleting_source_ancestor_of_excluded_entry(self):
        self.prepare()
        shutil.rmtree(self.target / 'nested')
        report = self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertIn('Cannot preserve excluded entry', report[0]['error'])
        self.assertEqual((self.source / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((self.source / 'nested/._DAV/metadata').read_text(), 'source metadata')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_commit_failure_after_restoration_preserves_excluded_entries(self):
        self.prepare()
        cache = self.target / 'nested/._DAV'; cache.mkdir(); (cache / 'local').write_text('keep')
        (self.source / 'nested/doc.md').write_text('updated')
        from agent_env_man.storage import State
        real_save = State.save
        failed = False
        def save(state):
            nonlocal failed
            if state.data['pending'] is None and not failed:
                failed = True; raise OSError('injected state commit failure')
            return real_save(state)
        with patch.object(State, 'save', side_effect=save, autospec=True):
            self.run_cli('apply', '--item', 'cases', code=1)
        self.assertTrue(failed)
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_excluded_links_are_opaque_and_preserved(self):
        self.require_links(); self.prepare()
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'secret').write_text('private')
        (self.target / '._DAV').symlink_to(outside, target_is_directory=True)
        original_link = os.readlink(self.target / '._DAV')
        (self.source / 'first.md').write_text('updated')
        self.run_cli('apply', '--item', 'cases')
        self.assertTrue((self.target / '._DAV').is_symlink())
        self.assertEqual(os.readlink(self.target / '._DAV'), original_link)
        self.assertEqual((outside / 'secret').read_text(), 'private')

    def test_instruction_required_entry_cannot_be_excluded(self):
        document = {'version': 2, 'sources': {'docs': {'type': 'external', 'exclude': ['rules/entry']}},
                    'instructions': {'rules': {'source': 'docs', 'subdir': 'rules', 'entry': 'entry/global.md'}}}
        with self.assertRaisesRegex(Error, 'required entry'):
            normalize(document)
        document['sources']['docs']['exclude'] = ['rules']
        with self.assertRaisesRegex(Error, 'hides the declared payload'):
            normalize(document)

    def test_defaults_do_not_exclude_explicit_settings_or_hook_scripts(self):
        document = {'version': 2, 'payload': {'defaults': {'exclude': ['**']}},
                    'sources': {'settings': {'type': 'external'}},
                    'settings': {'prefs': {'source': 'settings', 'path': 'prefs.toml', 'format': 'toml'}}}
        normalized = normalize(document)
        self.assertNotIn('exclusions', normalized['settings']['prefs'])

    def test_detach_preserves_excluded_local_entries_without_source(self):
        self.prepare()
        cache = self.target / '._DAV'; cache.mkdir(); (cache / 'local').write_text('keep')
        shutil.rmtree(self.source)
        self.run_cli('detach', 'cases')
        self.assertEqual((cache / 'local').read_text(), 'keep')

    def test_git_bootstrap_apply_and_update_ignore_excluded_links(self):
        self.require_links()
        self.document['payload'] = {'defaults': {'exclude': ['**/._DAV']}}
        self.document['directories']['cases']['install']['mode'] = 'copy'
        (self.repo / 'cases/._DAV').symlink_to('/outside/excluded')
        self.commit(self.repo); self.write()
        self.run_cli('bootstrap', self.catalog, '--checkout-root', self.checkouts,
                     '--root', f'personal={self.destination}')
        self.run_cli('apply', '--item', 'cases')
        self.assertFalse(os.path.lexists(self.target / '._DAV'))
        (self.repo / 'cases/first.md').write_text('received')
        (self.repo / 'cases/._DAV').unlink()
        (self.repo / 'cases/._DAV').symlink_to('/another/excluded')
        self.commit(self.repo)
        self.run_cli('update', 'cases'); self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / 'first.md').read_text(), 'received')
        self.assertFalse(os.path.lexists(self.target / '._DAV'))

    def test_git_skill_copy_preserves_excluded_entries_and_isolated_recovery(self):
        self.require_links()
        (self.repo / 'skills/report/._DAV').symlink_to('/excluded/metadata')
        self.commit(self.repo)
        self.document = {'version': 2, 'sources': {'repo': {'type': 'git', 'repository': str(self.repo)}},
                         'skills': {'report': {'source': 'repo', 'subdir': 'skills/report', 'exclude': ['**/._DAV'],
                                               'install': {'root': 'personal', 'mode': 'copy'}}}}
        self.write()
        self.run_cli('bootstrap', self.catalog, '--checkout-root', self.checkouts,
                     '--root', f'personal={self.destination}')
        self.run_cli('apply', '--item', 'report')
        target = self.destination / 'report'
        cache = target / '._DAV'; cache.mkdir(); (cache / 'local').write_text('keep')
        (self.repo / 'skills/report/helper.py').write_text('updated')
        self.commit(self.repo); self.run_cli('update', 'report')
        from agent_env_man.storage import State
        real_save = State.save
        failed = False
        def save(state):
            nonlocal failed
            if state.data['pending'] is None and not failed:
                failed = True; raise OSError('injected state commit failure')
            return real_save(state)
        with patch.object(State, 'save', side_effect=save, autospec=True):
            self.run_cli('apply', '--item', 'report', code=1)
        self.assertTrue(failed)
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertEqual((target / 'helper.py').read_text(), "print('test')\n")
        self.run_cli('apply', '--item', 'report')
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertEqual((target / 'helper.py').read_text(), 'updated')

    def test_identical_copies_with_same_exclusions_can_be_collected_together(self):
        self.prepare()
        self.document['directories']['mirror'] = {'source': 'store', 'exclude': [],
                'install': {'root': 'personal', 'mode': 'copy'}}
        self.write(); self.run_cli('apply', '--item', 'mirror')
        mirror = self.destination / 'mirror'
        (self.target / 'first.md').write_text('shared edit'); (mirror / 'first.md').write_text('shared edit')
        result = self.run_cli('publish', 'cases', 'mirror', '--from-copy')
        self.assertTrue(result[0]['collection_complete'])
        self.assertEqual((self.source / 'first.md').read_text(), 'shared edit')
        self.assertEqual((self.source / '._DAV/metadata').read_text(), 'source metadata')
        records = self.manager().state.data['items']
        self.assertEqual(records['cases:directory']['hash'], records['mirror:directory']['hash'])

    def test_previously_scanned_included_file_is_rechecked(self):
        self.prepare(links=True)
        real_read = payload_links.os.read
        nested_inode = (self.source / 'nested/doc.md').stat().st_ino
        edited = False
        def read(fd, size):
            nonlocal edited
            block = real_read(fd, size)
            if block and not edited and os.fstat(fd).st_ino == nested_inode:
                edited = True; (self.source / 'first.md').write_text('late concurrent edit')
            return block
        with patch.object(payload_links.os, 'read', side_effect=read):
            with self.assertRaisesRegex(Error, 'changed during inspection'):
                fingerprint(self.source, preserve_symlinks=True, exclusions=(('', '**/._DAV'),))
        self.assertTrue(edited)

    def test_skill_replacement_refuses_metadata_created_during_backup(self):
        from agent_env_man import manager as module
        self.document = {'version': 2, 'sources': {'repo': {'type': 'git', 'repository': str(self.repo)}},
                         'skills': {'report': {'source': 'repo', 'subdir': 'skills/report',
                                              'exclude': ['**/._DAV', 'scratch'],
                                              'install': {'root': 'personal', 'mode': 'copy'}}}}
        self.write()
        self.run_cli('bootstrap', self.catalog, '--checkout-root', self.checkouts,
                     '--root', f'personal={self.destination}')
        self.run_cli('apply', '--item', 'report')
        target = self.destination / 'report'
        (target / '._DAV').mkdir()
        (target / '._DAV/local').write_text('existing metadata')
        original = (target / 'helper.py').read_text()
        (self.repo / 'skills/report/helper.py').write_text('updated')
        self.commit(self.repo); self.run_cli('update', 'report')
        real_copy = module.copy_payload
        def copy(source, destination, **policy):
            real_copy(source, destination, **policy)
            if source == target:
                (target / 'scratch').mkdir()
                (target / 'scratch/local').write_text('late metadata')
        with patch.object(module, 'copy_payload', side_effect=copy):
            error = self.run_cli('apply', '--item', 'report', code=1)
        self.assertIn('Excluded entries changed', error)
        self.assertEqual((target / 'helper.py').read_text(), original)
        self.assertEqual((target / 'scratch/local').read_text(), 'late metadata')
        self.assertEqual((target / '._DAV/local').read_text(), 'existing metadata')
        self.assertIsNone(self.manager().state.data['pending'])
        self.run_cli('apply', '--item', 'report')
        self.assertEqual((target / 'helper.py').read_text(), 'updated')
        self.assertEqual((target / 'scratch/local').read_text(), 'late metadata')
        self.assertEqual((target / '._DAV/local').read_text(), 'existing metadata')

    def test_apply_preview_refuses_removing_excluded_ancestor(self):
        self.prepare()
        cache = self.target / 'nested/._DAV'; cache.mkdir()
        (cache / 'local').write_text('keep')
        shutil.rmtree(self.source / 'nested')
        error = self.run_cli('apply', '--item', 'cases', '--dry-run', code=1)
        self.assertIn('Cannot preserve excluded entry', error)
        self.assertEqual((cache / 'local').read_text(), 'keep')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_preview_refuses_removing_excluded_ancestor(self):
        self.prepare()
        shutil.rmtree(self.target / 'nested')
        report = self.run_cli('publish', 'cases', '--from-copy', '--dry-run', code=1)
        self.assertIn('Cannot preserve excluded entry', report[0]['error'])
        self.assertEqual((self.source / 'nested/._DAV/metadata').read_text(), 'source metadata')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_copy_closes_write_handle_before_metadata_updates(self):
        import fcntl
        self.prepare(links=True)
        (self.source / 'nested/doc.md').write_text('updated')
        real_chmod = payload_links.os.fchmod
        affected = False
        def chmod(fd, mode):
            nonlocal affected
            # Model the mounted davfs behavior: metadata updates on an open
            # write handle reset a newly copied file to its stale zero size.
            if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_WRONLY:
                affected = True
                os.ftruncate(fd, 0)
            real_chmod(fd, mode)
        with patch.object(payload_links.os, 'fchmod', side_effect=chmod):
            self.run_cli('apply', '--item', 'cases')
        self.assertFalse(affected)
        self.assertEqual((self.target / 'nested/doc.md').read_text(), 'updated')
