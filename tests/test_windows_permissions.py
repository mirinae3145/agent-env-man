"""Windows payload policy checks with real files and isolated platform selection.

The same cases run on native Windows. Selecting Windows branches on another
host verifies policy behavior, without substituting for native OS validation.
"""

from contextlib import ExitStack
import errno
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_env_man import permissions, storage
from agent_env_man.model import Error


class WindowsPermissions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-windows-permissions-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source'
        (self.source / 'nested').mkdir(parents=True)
        (self.source / 'nested/value').write_bytes(b'payload')
        (self.source / '.git').mkdir()
        (self.source / '.git/config').write_bytes(b'Git metadata')
        (self.source / 'cache').mkdir()
        (self.source / 'cache/local').write_bytes(b'excluded metadata')
        self.policy = {'permissions': 'best-effort', 'exclude_git': True,
                       'exclusions': (('', 'cache'),)}
        namespace = SimpleNamespace(**{key: getattr(os, key) for key in dir(os)})
        namespace.name = 'nt'
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(storage, 'os', namespace))
        stack.enter_context(patch.object(permissions, 'os', namespace))

    def test_copy_preserves_content_excludes_metadata_and_applies_mode_overrides(self):
        destination = self.root / 'copy'
        failures = []
        storage.copy_payload(self.source, destination, permission_failures=failures,
                             destination_modes={'nested/value': stat.S_IREAD}, **self.policy)
        self.assertEqual((destination / 'nested/value').read_bytes(), b'payload')
        self.assertFalse((destination / '.git').exists())
        self.assertFalse((destination / 'cache').exists())
        self.assertEqual(failures, [])
        modes, kinds = {}, {}
        result = storage.observation(destination, modes=modes, **self.policy)
        captured = permissions.snapshot(destination, node_types=kinds, **self.policy)
        self.assertEqual(modes, captured)
        self.assertEqual(modes['nested/value'], 0)
        self.assertEqual(kinds, {'.': 'd', 'nested': 'd', 'nested/value': 'f'})
        self.assertEqual(result['permissions_hash'], permissions.digest(captured))
        self.assertEqual(result['hash'], storage.fingerprint(self.source, **self.policy))
        self.assertEqual((self.source / 'cache/local').read_bytes(), b'excluded metadata')

    def test_single_file_copy_and_readonly_edit_have_separate_content_and_mode_identity(self):
        source = self.source / 'nested/value'
        source.chmod(stat.S_IREAD | stat.S_IWRITE)
        destination = self.root / 'single-file'
        storage.copy_payload(source, destination, permissions='best-effort')
        self.assertEqual(destination.read_bytes(), b'payload')
        before = storage.observation(destination, permissions='best-effort')
        destination.chmod(stat.S_IREAD)
        after = storage.observation(destination, permissions='best-effort')
        self.assertEqual(before['hash'], after['hash'])
        self.assertNotEqual(before['permissions_hash'], after['permissions_hash'])
        self.assertEqual(permissions.snapshot(destination), {'.': 0})
        self.assertEqual(destination.read_bytes(), b'payload')

    def test_denied_setters_leave_payload_intact_and_report_each_affected_path(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                destination = self.root / ('reported' if recorded else 'unreported')
                failures = [] if recorded else None
                with patch.object(permissions.os, 'chmod', side_effect=OSError(errno.EACCES, 'denied setter')):
                    storage.copy_payload(self.source, destination, permission_failures=failures, **self.policy)
                self.assertEqual((destination / 'nested/value').read_bytes(), b'payload')
                self.assertEqual(storage.fingerprint(destination, **self.policy),
                                 storage.fingerprint(self.source, **self.policy))
                if recorded:
                    self.assertEqual({item['path'] for item in failures}, {'.', 'nested', 'nested/value'})
                    self.assertTrue(all('denied setter' in item['error'] for item in failures))
                    self.assertTrue(all(item['requested'] in (0, stat.S_IWRITE) for item in failures))

    def test_io_and_timestamp_failures_are_fatal_even_under_best_effort(self):
        source = self.source / 'nested/value'
        for api, failure in (('chmod', errno.EIO), ('utime', errno.EPERM)):
            with self.subTest(api=api):
                destination = self.root / api
                with patch.object(storage.os, api, side_effect=OSError(failure, 'injected I/O failure')):
                    with self.assertRaisesRegex(OSError, 'injected I/O failure'):
                        storage.copy_payload(source, destination, permissions='best-effort')
                self.assertEqual(source.read_bytes(), b'payload')

    def test_snapshot_rejects_reparse_entries_before_traversing_them(self):
        redirected = self.source / 'nested'
        with patch.object(storage, 'is_reparse', side_effect=lambda path: path == redirected):
            with self.assertRaisesRegex(Error, 'symlinks/junctions are unsupported'):
                permissions.snapshot(self.source, **self.policy)
        self.assertEqual((redirected / 'value').read_bytes(), b'payload')

    def test_snapshot_does_not_visit_excluded_reparse_entries(self):
        inspected = []
        def reparse(path):
            inspected.append(path)
            return path == self.source / 'cache' or path == self.source / '.git'
        with patch.object(storage, 'is_reparse', side_effect=reparse):
            modes = permissions.snapshot(self.source, **self.policy)
        self.assertEqual(set(modes), {'.', 'nested', 'nested/value'})
        self.assertNotIn(self.source / 'cache', inspected)
        self.assertNotIn(self.source / '.git', inspected)

    def test_snapshot_rejects_special_nodes_without_modifying_the_actual_file(self):
        leaf = self.source / 'nested/value'
        lstat = Path.lstat
        def special(path, *args, **kwargs):
            info = lstat(path, *args, **kwargs)
            if path == leaf:
                return SimpleNamespace(st_mode=stat.S_IFIFO, st_dev=info.st_dev, st_ino=info.st_ino)
            return info
        with patch.object(Path, 'lstat', new=special):
            with self.assertRaisesRegex(Error, 'Special files are unsupported'):
                permissions.snapshot(self.source, **self.policy)
        self.assertEqual(leaf.read_bytes(), b'payload')

    def test_snapshot_refuses_permissions_changed_during_inspection(self):
        leaf = self.source / 'nested/value'
        leaf.chmod(stat.S_IREAD | stat.S_IWRITE)
        lstat = Path.lstat
        calls = 0
        def racing(path, *args, **kwargs):
            nonlocal calls
            if path == leaf:
                calls += 1
                if calls == 3:
                    leaf.chmod(stat.S_IREAD)
            return lstat(path, *args, **kwargs)
        with patch.object(Path, 'lstat', new=racing):
            with self.assertRaisesRegex(Error, 'permissions changed during inspection'):
                permissions.snapshot(leaf)
        self.assertEqual(permissions.snapshot(leaf), {'.': 0})
        self.assertEqual(leaf.read_bytes(), b'payload')


if __name__ == '__main__':
    unittest.main()
