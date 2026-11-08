"""Repeated command decisions share observations without caching across guards."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man import payload_links, permissions, storage
from agent_env_man.model import Error
from inspection_support import count_inspections
import test_directories as directory_tests


class InspectionReuse(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager

    def test_unchanged_copy_avoids_repeated_planning_and_status_reads(self):
        for level in ('strict', 'best-effort'):
            with self.subTest(permissions=level):
                self.document['payload'] = {'defaults': {'permissions': level}}
                if not hasattr(self, 'external_root'):
                    self.external(mode='copy')
                else:
                    self.write()
                original = (self.external_root / 'first.md').read_bytes()
                self.run_cli('apply', '--item', 'cases')
                for args, source_limit, target_limit in (
                    (('status',), 1, 1),
                    (('apply', '--item', 'cases', '--dry-run'), 1, 1),
                    (('apply', '--item', 'cases'), 2, 2),
                ):
                    with self.subTest(command=args):
                        counts = count_inspections(self.config, args, self.external_root, self.target)
                        self.assertLessEqual(counts.get('content:source', 0), source_limit)
                        self.assertLessEqual(counts.get('content:target', 0), target_limit)
                        if os.name != 'nt' and level == 'best-effort':
                            self.assertEqual(sum(n for kind, n in counts.items() if kind.startswith('permissions:')), 0)
                (self.target / 'first.md').write_bytes(b'fixture replacement edit')
                counts = count_inspections(self.config, ('apply', '--item', 'cases', '--replace'),
                                           self.external_root, self.target)
                self.assertEqual((self.target / 'first.md').read_bytes(), original)
                if level == 'best-effort':
                    # Windows validates the source separately before copying;
                    # POSIX combines that validation with its copy scan.
                    self.assertLessEqual(counts.get('content:source', 0), 4 if os.name == 'nt' else 3)
                    self.assertLessEqual(counts.get('content:target', 0), 4)
                    self.assertLessEqual(counts.get('content:other', 0), 2)
                    if os.name != 'nt':
                        self.assertEqual(sum(n for kind, n in counts.items() if kind.startswith('permissions:')), 0)

    def test_install_still_rechecks_source_and_target_after_plan(self):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.external(mode='copy')
        self.run_cli('apply', '--item', 'cases')
        for path, error in ((self.external_root / 'first.md', 'source changed after preflight'),
                            (self.target / 'first.md', 'target changed after preflight')):
            original = path.read_bytes()
            manager = self.manager()
            plan = manager.plan(manager.items()[0])
            path.write_bytes(b'concurrent edit')
            with self.subTest(path=path), self.assertRaisesRegex(Error, error):
                manager.install(plan)
            self.assertEqual(path.read_bytes(), b'concurrent edit')
            path.write_bytes(original)

    def test_status_keeps_saved_and_current_exclusion_policies_separate(self):
        self.external(mode='copy')
        self.run_cli('apply', '--item', 'cases')
        (self.target / 'local').write_bytes(b'local edit')
        self.document['payload'] = {'defaults': {'exclude': ['local'], 'permissions': 'strict'}}
        self.write()
        report = self.run_cli('status')['items'][0]
        self.assertEqual(report['status'], 'configuration-changed')
        self.assertEqual(report['installation'], 'modified-locally')
        self.assertEqual(self.run_cli('apply', '--item', 'cases')[0]['action'], 'record')
        self.assertEqual((self.target / 'local').read_bytes(), b'local edit')

    def test_stage_edits_during_source_revalidation_do_not_reach_commit(self):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.external(mode='copy')
        self.run_cli('apply', '--item', 'cases')
        original = (self.target / 'first.md').read_bytes()
        (self.external_root / 'first.md').write_bytes(b'updated source')
        manager = self.manager()
        plan = manager.plan(manager.items()[0])
        observe_source = manager.source_observation
        def changing(item, **options):
            actual = observe_source(item, **options)
            for stage in self.target.parent.glob('.aem-stage-*'):
                (stage / 'first.md').write_bytes(b'concurrent stage edit')
            return actual
        with patch.object(manager, 'source_observation', side_effect=changing):
            with self.assertRaisesRegex(Error, 'Copied payload changed during permission inspection'):
                manager.install(plan)
        self.assertEqual((self.target / 'first.md').read_bytes(), original)
        self.assertFalse(manager.state.data['pending'])

    @unittest.skipIf(os.name == 'nt', 'POSIX source-root link race')
    def test_observed_source_root_cannot_be_replaced_with_a_link(self):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.external(mode='copy')
        manager = self.manager()
        item = manager.items()[0]
        moved = self.external_root.with_name('moved')
        self.external_root.rename(moved)
        self.external_root.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(Error, 'Payload changed during inspection'):
            manager.source_observation(item)


class CombinedPermissionObservation(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor and permission checks')
    def test_combined_observation_matches_legacy_hash_and_permission_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'file').write_bytes(b'content')
            (root / 'file').chmod(0o751)
            (root / 'empty').mkdir()
            (root / 'excluded').write_bytes(b'ignored')
            for links in (False, True):
                if links:
                    (root / 'alias').symlink_to('file')
                policy = {'permissions': 'best-effort', 'preserve_symlinks': links,
                          'exclusions': (('item', 'excluded'),)}
                expected = {'kind': 'directory', 'hash': storage.fingerprint(root, **policy),
                            'permissions_hash': permissions.digest(permissions.snapshot(root, **policy))}
                self.assertEqual(storage.observation(root, **policy), expected)
                modes = {}
                self.assertEqual(storage.observation(root, modes=modes, **policy), expected)
                self.assertEqual(modes, permissions.snapshot(root, **policy))

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor and permission checks')
    def test_permission_change_during_content_read_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            leaf = root / 'file'
            leaf.write_bytes(b'content')
            leaf.chmod(0o644)
            read = payload_links.os.read
            changed = False
            def changing(fd, size):
                nonlocal changed
                block = read(fd, size)
                if block and not changed:
                    leaf.chmod(0o755)
                    changed = True
                return block
            with patch.object(payload_links.os, 'read', side_effect=changing):
                with self.assertRaisesRegex(Error, 'Payload changed during inspection'):
                    storage.observation(root, permissions='best-effort')
            self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), 0o755)


if __name__ == '__main__':
    unittest.main()
