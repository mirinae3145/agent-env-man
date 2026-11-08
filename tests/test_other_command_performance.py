"""Command costs fall without weakening collection, Git, or recovery guards."""

from pathlib import Path
import shutil
import unittest

from agent_env_man import copy_publication, storage
from inspection_support import count_inspections
import test_directories as directory_tests


class PayloadCommandCosts(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager
    require_links = directory_tests.Directories.require_links

    def test_shared_external_bootstrap_hashes_each_policy_once(self):
        self.external(mode='copy')
        self.document['directories']['alias'] = dict(self.document['directories']['cases'])
        self.document['directories']['alias']['install'] = {'root': 'personal', 'destination': 'alias', 'mode': 'copy'}
        self.write()
        counts = count_inspections(self.config, ('bootstrap',), self.external_root, self.target)
        self.assertEqual(counts['content:source'], 1)
        self.document['directories']['alias']['permissions'] = 'best-effort'
        self.write()
        counts = count_inspections(self.config, ('bootstrap',), self.external_root, self.target)
        self.assertEqual(counts['content:source'], 2)

    def test_collection_preview_captures_hashes_and_changes_in_one_read(self):
        self.external(mode='copy')
        original = (self.external_root / 'first.md').read_bytes()
        for level in ('strict', 'best-effort'):
            with self.subTest(permissions=level):
                self.document['payload'] = {'defaults': {'permissions': level}}
                self.write()
                self.run_cli('apply', '--item', 'cases', '--replace')
                (self.target / 'first.md').write_bytes(b'edited')
                (self.target / 'added').write_bytes(b'new')
                (self.target / 'empty').mkdir(exist_ok=True)
                args = ('publish', 'cases', '--from-copy', '--dry-run')
                result = self.run_cli(*args)[0]['collection'][0]
                self.assertEqual(result['changes'], ['added', 'empty', 'first.md'])
                self.assertTrue(result['changed'])
                counts = count_inspections(self.config, args, self.external_root, self.target)
                self.assertEqual(counts.get('content:source'), 1)
                self.assertEqual(counts.get('content:target'), 1)
                self.assertEqual(counts.get('content:other', 0), 0)
                self.assertEqual((self.external_root / 'first.md').read_bytes(), original)

    def test_best_effort_detach_preview_reads_source_once(self):
        self.require_links()
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.external(mode='link')
        self.run_cli('apply', '--item', 'cases')
        counts = count_inspections(self.config, ('detach', 'cases', '--dry-run'), self.external_root, self.target)
        self.assertEqual(counts['content:source'], 1)
        self.assertTrue(self.target.is_symlink())

    def test_pre_rename_recovery_inspects_stage_once_and_refuses_edits(self):
        self.external(mode='copy')
        self.run_cli('apply', '--item', 'cases')
        original = (self.target / 'first.md').read_bytes()
        manager = self.manager()
        stage = self.target.with_name('.aem-stage-cost')
        backup = self.target.with_name('agent-loop.aem-backup-cost')
        shutil.copytree(self.target, stage)
        (stage / 'first.md').write_bytes(b'staged')
        manager.state.data['pending'] = {'key': manager.items()[0].key, 'target': str(self.target),
            'stage': str(stage), 'backup': str(backup), 'before': storage.observation(self.target),
            'after': storage.observation(stage)}
        manager.state.save()
        (stage / 'first.md').write_bytes(b'later edit')
        error = self.run_cli('recover', code=1)
        self.assertIn('staged content changed', error)
        self.assertEqual((stage / 'first.md').read_bytes(), b'later edit')
        self.assertEqual((self.target / 'first.md').read_bytes(), original)
        (stage / 'first.md').write_bytes(b'staged')
        counts = count_inspections(self.config, ('recover',), self.external_root, self.target)
        self.assertEqual(counts['content:target'], 1)
        self.assertEqual(counts['content:other'], 1)
        self.assertFalse(stage.exists())
        self.assertFalse(self.manager().state.data['pending'])

    def test_copy_local_git_still_has_distinct_guard_and_included_hash(self):
        self.external(mode='copy')
        self.run_cli('apply', '--item', 'cases')
        (self.target / '.git').mkdir()
        (self.target / '.git/config').write_bytes(b'local metadata')
        item = self.manager().items()[0]
        entries = {}
        actual, included = copy_publication.copy_inspection(self.target, exclude_git=True, entries=entries)
        self.assertEqual(actual, storage.observation(self.target))
        self.assertEqual(included, storage.fingerprint(self.target, exclude_git=True))
        self.assertNotEqual(actual['hash'], included)
        self.assertNotIn('.git', entries)
        self.assertNotIn('.git/config', entries)

    def test_projected_children_match_physical_observations(self):
        from agent_env_man.payload_policy import child_options
        self.external(mode='copy')
        (self.external_root / 'nested').mkdir()
        (self.external_root / 'nested/file').write_bytes(b'nested content')
        (self.external_root / 'nested/ignored').write_bytes(b'unowned')
        (self.external_root / 'empty').mkdir()
        (self.external_root / 'nested/file').chmod(0o751)
        try:
            (self.external_root / 'alias').symlink_to('nested/file')
        except OSError:
            pass  # Regular-node projection remains testable without links.
        for permission in ('strict', 'best-effort'):
            with self.subTest(permissions=permission):
                policy = {'permissions': permission, 'exclusions': (('', 'nested/ignored'),),
                          'preserve_symlinks': True, 'source_relative': '.'}
                entries, modes = {}, {}
                storage.observation(self.external_root, entries=entries, modes=modes, **policy)
                projected = copy_publication.child_observations(entries, modes, permissions=permission)
                for name, observed in projected.items():
                    self.assertEqual(observed, storage.observation(self.external_root / name, **child_options(policy, name)))

    def test_collection_does_not_reinspect_every_unchanged_child(self):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.external(mode='copy')
        for number in range(20):
            (self.external_root / f'unchanged-{number}').write_bytes(b'unchanged')
        self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').write_bytes(b'edited')
        counts = count_inspections(self.config, ('publish', 'cases', '--from-copy'), self.external_root, self.target)
        self.assertLessEqual(counts.get('content:source-child', 0), 2)
        self.assertLessEqual(counts.get('content:target-child', 0), 1)
        self.assertEqual((self.external_root / 'first.md').read_bytes(), b'edited')
        self.assertEqual((self.external_root / 'unchanged-19').read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
