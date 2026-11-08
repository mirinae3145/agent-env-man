"""Timestamp-only races get one fresh inspection without adopting real edits."""

from copy import deepcopy
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man import payload_links
from agent_env_man.model import Error
from agent_env_man.storage import copy_payload, observation
import test_directories as directory_tests


class TimestampReinspection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-timestamps-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.leaf = self.source / 'file'
        self.leaf.write_bytes(b'original')
        self.policy = {'permissions': 'best-effort', 'exclusions': (('item', '**/._DAV'),)}

    def touch(self, path=None, *, ctime_only=False):
        path = path or self.leaf
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + (0 if ctime_only else 1000000000)))

    def changing_read(self, change, *, repeated=False):
        read = os.read
        calls = []
        def changing(fd, size):
            block = read(fd, size)
            if block:
                calls.append(fd)
                if repeated or len(calls) == 1:
                    change()
            return block
        return calls, patch.object(payload_links.os, 'read', side_effect=changing)

    def test_one_time_mtime_and_ctime_changes_preserve_combined_observation(self):
        for ctime_only in (False, True):
            with self.subTest(ctime_only=ctime_only):
                expected_modes, expected_entries = {}, {}
                expected = observation(self.source, modes=expected_modes, entries=expected_entries, **self.policy)
                calls, changing = self.changing_read(lambda: self.touch(ctime_only=ctime_only))
                modes, entries = {}, {}
                with changing:
                    actual = observation(self.source, modes=modes, entries=entries, **self.policy)
                self.assertEqual(actual, expected)
                self.assertEqual(modes, expected_modes)
                self.assertEqual(entries, expected_entries)
                self.assertEqual(len(calls), 2)

    def test_directory_time_change_without_exclusions_is_reinspected(self):
        policy = {'preserve_symlinks': True}
        expected = observation(self.source, **policy)
        calls, changing = self.changing_read(lambda: self.touch(self.source))
        with changing:
            self.assertEqual(observation(self.source, **policy), expected)
        self.assertEqual(len(calls), 2)

    def test_time_change_while_opening_is_reinspected(self):
        expected = observation(self.source, **self.policy)
        fstat = os.fstat
        inode = self.leaf.stat().st_ino
        changed = False
        def changing(fd):
            nonlocal changed
            info = fstat(fd)
            if info.st_ino == inode and not changed:
                changed = True
                self.touch()
                info = fstat(fd)
            return info
        with patch.object(payload_links.os, 'fstat', side_effect=changing):
            self.assertEqual(observation(self.source, **self.policy), expected)
        self.assertTrue(changed)

    def test_repeated_timestamp_changes_fail_without_exposing_captures(self):
        modes, entries = {'saved': 0o755}, {'saved': ('f', 0, b'saved')}
        before = deepcopy((modes, entries))
        calls, changing = self.changing_read(self.touch, repeated=True)
        with changing, self.assertRaisesRegex(Error, 'changed during inspection'):
            observation(self.source, modes=modes, entries=entries, **self.policy)
        self.assertEqual(len(calls), 2)
        self.assertEqual((modes, entries), before)

    def test_same_size_content_change_is_not_adopted_by_reinspection(self):
        calls, changing = self.changing_read(lambda: self.leaf.write_bytes(b'modified'))
        with changing, self.assertRaisesRegex(Error, 'changed during'):
            observation(self.source, **self.policy)
        self.assertEqual(self.leaf.read_bytes(), b'modified')

    def test_mode_inode_and_included_path_changes_remain_fatal(self):
        def replacement():
            replacement = self.source / 'replacement'
            replacement.write_bytes(b'original')
            replacement.replace(self.leaf)
        for change in (lambda: self.leaf.chmod(self.leaf.stat().st_mode ^ 0o100), replacement,
                       lambda: (self.source / 'new').write_bytes(b'included')):
            with self.subTest(change=change):
                calls, changing = self.changing_read(change)
                with changing, self.assertRaisesRegex(Error, 'changed during'):
                    observation(self.source, **self.policy)
                self.assertEqual(len(calls), 1)

    def test_time_change_during_final_identity_check_is_reinspected(self):
        expected = observation(self.source, **self.policy)
        stat = os.stat
        calls = 0
        def changing(path, *args, **kwargs):
            nonlocal calls
            if path == 'file' and kwargs.get('dir_fd') is not None:
                calls += 1
                if calls == 3:
                    self.touch()
            return stat(path, *args, **kwargs)
        with patch.object(payload_links.os, 'stat', side_effect=changing):
            self.assertEqual(observation(self.source, **self.policy), expected)
        self.assertGreater(calls, 3)

    def test_retry_rechecks_an_earlier_file_after_reading_later_siblings(self):
        later = self.source / 'later'
        later.write_bytes(b'sibling')
        leaf_inode, later_inode = self.leaf.stat().st_ino, later.stat().st_ino
        read = os.read
        reads = {leaf_inode: 0, later_inode: 0}
        def changing(fd, size):
            block = read(fd, size)
            if block:
                inode = os.fstat(fd).st_ino
                reads[inode] += 1
                if inode == leaf_inode and reads[inode] == 1:
                    self.touch()
                if inode == later_inode and reads[inode] == 2:
                    self.leaf.write_bytes(b'modified')
            return block
        with patch.object(payload_links.os, 'read', side_effect=changing), patch('agent_env_man.payload_io.perf_counter', return_value=0):
            with self.assertRaisesRegex(Error, 'changed during inspection'):
                observation(self.source, preserve_symlinks=True)
        self.assertEqual(reads, {leaf_inode: 2, later_inode: 2})

    def test_copy_restarts_stage_and_reports_only_successful_attempt(self):
        destination = self.root / 'stage'
        calls, changing = self.changing_read(self.touch)
        chmod = os.fchmod
        failures = []
        attempts = []
        def denied(fd, mode):
            attempts.append(fd)
            if len(attempts) == 1:
                raise OSError(errno.EPERM, 'first attempt only')
            chmod(fd, mode)
        with changing, patch.object(payload_links.os, 'fchmod', side_effect=denied):
            copy_payload(self.source, destination, permission_failures=failures, **self.policy)
        self.assertEqual(len(calls), 2)
        self.assertEqual(failures, [])
        self.assertEqual(observation(destination, **self.policy), observation(self.source, **self.policy))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['source', 'stage'])

    def test_preexisting_copy_destination_is_preserved(self):
        destination = self.root / 'stage'
        destination.mkdir()
        (destination / 'user').write_bytes(b'keep')
        calls, changing = self.changing_read(self.touch)
        with changing, self.assertRaises(FileExistsError):
            copy_payload(self.source, destination, **self.policy)
        self.assertEqual((destination / 'user').read_bytes(), b'keep')
        self.assertEqual(calls, [])

    def test_copy_retry_cleans_read_only_directories(self):
        nested = self.source / 'nested'
        nested.mkdir()
        (nested / 'child').write_bytes(b'nested content')
        def writable_tree():
            for directory, _, _ in os.walk(self.root):
                Path(directory).chmod(0o700)
        self.addCleanup(writable_tree)
        policies = ({'permissions': 'best-effort'}, {'preserve_symlinks': True},
                    {'permissions': 'best-effort', 'destination_modes': {'.': 0o555, 'nested': 0o555}})
        for index, policy in enumerate(policies):
            with self.subTest(policy=policy):
                self.source.chmod(0o555 if index < 2 else 0o755)
                nested.chmod(0o555 if index < 2 else 0o755)
                destination = self.root / f'stage-{index}'
                calls, changing = self.changing_read(self.touch)
                with changing:
                    copy_payload(self.source, destination, **policy)
                self.assertEqual(len(calls), 4)
                self.assertEqual((destination / 'nested' / 'child').read_bytes(), b'nested content')
                self.assertEqual((destination / 'file').read_bytes(), b'original')
                self.assertEqual(destination.stat().st_mode & 0o777, 0o555)
                self.assertEqual((destination / 'nested').stat().st_mode & 0o777, 0o555)
                self.assertFalse(list(self.root.glob('.aem-reinspection-*')))

    def test_copy_retry_preserves_replacement_after_identity_check(self):
        for kind in ('directory', 'file', 'link'):
            with self.subTest(kind=kind):
                destination = self.root / f'stage-{kind}'
                replacement = self.root / f'user-{kind}'
                if kind == 'directory':
                    replacement.mkdir()
                    (replacement / 'user-data').write_bytes(b'keep')
                    source = self.source
                elif kind == 'file':
                    replacement.write_bytes(b'keep')
                    source = self.leaf
                else:
                    replacement.symlink_to('user-referent')
                    source = self.source / 'alias'
                    source.symlink_to('file')
                info = replacement.lstat()
                expected = info.st_dev, info.st_ino
                original_stat = os.stat
                destination_stats = 0
                def replacing(path, *args, **kwargs):
                    nonlocal destination_stats
                    result = original_stat(path, *args, **kwargs)
                    if path == destination.name and kwargs.get('dir_fd') is not None:
                        destination_stats += 1
                        # Root links are also stat'ed immediately after creation.
                        if destination_stats == (2 if kind == 'link' else 1):
                            destination.rename(self.root / f'first-stage-{kind}')
                            replacement.rename(destination)
                    return result
                if kind == 'link':
                    original_readlink = os.readlink
                    changed = False
                    def readlink(path, *args, **kwargs):
                        nonlocal changed
                        target = original_readlink(path, *args, **kwargs)
                        if path == 'alias' and not changed:
                            changed = True
                            info = source.lstat()
                            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000), follow_symlinks=False)
                        return target
                    changing = patch.object(payload_links.os, 'readlink', side_effect=readlink)
                else:
                    _, changing = self.changing_read(self.touch)
                with changing, patch.object(payload_links.os, 'stat', side_effect=replacing):
                    with self.assertRaisesRegex(Error, 'changed before timestamp reinspection') as caught:
                        copy_payload(source, destination, preserve_symlinks=True)
                preserved = [p for p in self.root.rglob('*')
                             if (p.lstat().st_dev, p.lstat().st_ino) == expected]
                self.assertEqual(len(preserved), 1)
                self.assertIn(str(preserved[0]), str(caught.exception))
                if kind == 'directory':
                    self.assertEqual((preserved[0] / 'user-data').read_bytes(), b'keep')
                elif kind == 'file':
                    self.assertEqual(preserved[0].read_bytes(), b'keep')
                else:
                    self.assertEqual(os.readlink(preserved[0]), 'user-referent')

    def test_copy_retry_preserves_destination_recreated_before_removal(self):
        destination = self.root / 'stage'
        original_rmtree = payload_links.shutil.rmtree
        recreated = False
        def recreate(path, *args, **kwargs):
            nonlocal recreated
            if not recreated:
                recreated = True
                if destination.exists():
                    destination.rename(self.root / 'first-stage')
                destination.mkdir()
                (destination / 'user-data').write_bytes(b'keep')
            return original_rmtree(path, *args, **kwargs)
        calls, changing = self.changing_read(self.touch)
        with changing, patch.object(payload_links.shutil, 'rmtree', side_effect=recreate):
            with self.assertRaisesRegex(Error, 'preserved at'):
                copy_payload(self.source, destination, **self.policy)
        self.assertEqual((destination / 'user-data').read_bytes(), b'keep')
        self.assertEqual(len(calls), 1)
        self.assertFalse(list(self.root.glob('.aem-reinspection-*')))

    def test_timestamp_setter_failure_remains_fatal_without_retry(self):
        destination = self.root / 'stage'
        utime = os.utime
        def drift():
            info = self.leaf.stat()
            utime(self.leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
        calls, changing = self.changing_read(drift)
        with changing, patch.object(payload_links.os, 'utime', side_effect=OSError(errno.ENOTSUP, 'time setter unavailable')):
            with self.assertRaisesRegex(OSError, 'time setter unavailable'):
                copy_payload(self.source, destination, **self.policy)
        self.assertEqual(len(calls), 1)

    def test_opaque_link_copy_reinspection_preserves_referent(self):
        link = self.source / 'alias'
        try:
            link.symlink_to('file')
        except OSError as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')
        readlink = os.readlink
        calls = 0
        def changing(path, *args, **kwargs):
            nonlocal calls
            target = readlink(path, *args, **kwargs)
            if path == 'alias':
                calls += 1
                if calls == 1:
                    info = link.lstat()
                    os.utime(link, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000), follow_symlinks=False)
            return target
        destination = self.source / 'copy'
        with patch.object(payload_links.os, 'readlink', side_effect=changing):
            copy_payload(link, destination, preserve_symlinks=True)
        self.assertEqual(calls, 2)
        self.assertEqual(os.readlink(destination), 'file')
        self.assertEqual(self.leaf.read_bytes(), b'original')


class TimestampCommands(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager

    def race_recreated_stage(self, leaf, find_stage):
        read = os.read
        rmtree = payload_links.shutil.rmtree
        identity = leaf.stat().st_dev, leaf.stat().st_ino
        raced = {}
        def changing(fd, size):
            block = read(fd, size)
            info = os.fstat(fd)
            stage = find_stage()
            if block and not raced and stage is not None and (info.st_dev, info.st_ino) == identity:
                raced['stage'] = stage
                os.utime(leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
            return block
        def recreate(path, *args, **kwargs):
            if raced and not raced.get('recreated'):
                stage = raced['stage']
                if stage.exists():
                    stage.rename(stage.with_name('first-stage'))
                stage.mkdir()
                (stage / 'user-data').write_bytes(b'keep')
                raced['recreated'] = True
            return rmtree(path, *args, **kwargs)
        return raced, patch.object(payload_links.os, 'read', side_effect=changing), patch.object(payload_links.shutil, 'rmtree', side_effect=recreate)

    def test_install_preserves_recreated_stage_after_copy_refusal(self):
        self.document['directories']['cases']['permissions'] = 'best-effort'
        self.external()
        self.run_cli('apply', '--item', 'cases')
        leaf = self.external_root / 'first.md'
        leaf.write_bytes(b'incoming')
        before = observation(self.target, permissions='best-effort')
        records = deepcopy(self.manager().state.data['items'])
        def stage():
            return next(self.target.parent.glob('.aem-stage-*'), None)
        raced, changing, recreate = self.race_recreated_stage(leaf, stage)
        with changing, recreate:
            error = self.run_cli('apply', '--item', 'cases', code=1)
        self.assertIn('preserved at', error)
        self.assertEqual((raced['stage'] / 'user-data').read_bytes(), b'keep')
        self.assertEqual(observation(self.target, permissions='best-effort'), before)
        self.assertEqual(self.manager().state.data['items'], records)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_preserves_recreated_child_after_copy_refusal(self):
        self.document['directories']['cases']['permissions'] = 'best-effort'
        self.external()
        nested = self.external_root / 'nested'
        nested.mkdir()
        (nested / 'file').write_bytes(b'original')
        self.run_cli('apply', '--item', 'cases')
        leaf = self.target / 'nested' / 'file'
        leaf.write_bytes(b'incoming')
        before = observation(self.external_root, permissions='best-effort')
        records = deepcopy(self.manager().state.data['items'])
        def stage():
            return next(self.external_root.parent.glob('.aem-collection-*/stages/0'), None)
        raced, changing, recreate = self.race_recreated_stage(leaf, stage)
        with changing, recreate:
            report = self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertIn('preserved at', report[0]['error'])
        self.assertEqual((raced['stage'] / 'user-data').read_bytes(), b'keep')
        self.assertEqual(observation(self.external_root, permissions='best-effort'), before)
        self.assertEqual(self.manager().state.data['items'], records)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_failed_copy_reinspection_preserves_installation_and_ownership(self):
        self.document['directories']['cases']['permissions'] = 'best-effort'
        self.external()
        self.run_cli('apply', '--item', 'cases')
        leaf = self.external_root / 'first.md'
        leaf.write_bytes(b'incoming')
        before = observation(self.target, permissions='best-effort')
        records = deepcopy(self.manager().state.data['items'])
        read = os.read
        for content_change in (False, True):
            leaf.write_bytes(b'incoming')
            changed = False
            def changing(fd, size):
                nonlocal changed
                block = read(fd, size)
                info = os.fstat(fd)
                if (block and any(self.target.parent.glob('.aem-stage-*'))
                        and info.st_ino == leaf.stat().st_ino):
                    if content_change:
                        if not changed:
                            leaf.write_bytes(b'modified')
                            changed = True
                    else:
                        os.utime(leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
                return block
            with self.subTest(content_change=content_change), patch.object(payload_links.os, 'read', side_effect=changing):
                self.assertIn('changed during', self.run_cli('apply', '--item', 'cases', code=1))
            self.assertEqual(observation(self.target, permissions='best-effort'), before)
            self.assertEqual(self.manager().state.data['items'], records)
            self.assertIsNone(self.manager().state.data['pending'])
            self.assertFalse(list(self.target.parent.glob('.aem-stage-*')))

    def test_one_time_timestamp_change_during_status_and_apply_succeeds(self):
        self.document['directories']['cases'].update(permissions='best-effort', exclude=['**/._DAV'])
        self.external()
        self.run_cli('apply', '--item', 'cases')
        leaf = self.external_root / 'first.md'
        identity = leaf.stat().st_dev, leaf.stat().st_ino
        read = os.read
        def execute(args, *, copying=False):
            changed = False
            def changing(fd, size):
                nonlocal changed
                block = read(fd, size)
                in_copy = copying and any(self.target.parent.glob('.aem-stage-*'))
                info = os.fstat(fd)
                if (block and not changed and (not copying or in_copy)
                        and (info.st_dev, info.st_ino) == identity):
                    changed = True
                    info = leaf.stat()
                    os.utime(leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
                return block
            with patch.object(payload_links.os, 'read', side_effect=changing):
                result = self.run_cli(*args)
            self.assertTrue(changed)
            return result
        self.assertEqual(execute(('status',))['items'][0]['status'], 'current')
        leaf.write_text('incoming content', encoding='utf-8')
        self.assertEqual(execute(('apply', '--item', 'cases'), copying=True)[0]['action'], 'install')
        self.assertEqual((self.target / 'first.md').read_text(), 'incoming content')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertFalse(list(self.target.parent.glob('.aem-stage-*')))
