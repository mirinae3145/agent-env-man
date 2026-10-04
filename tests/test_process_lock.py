"""Mocked Windows calls verify lock ownership without claiming native OS behavior."""

import errno
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_env_man import process_lock


class WindowsLock(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-windows-lock-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.api = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=Mock())
        # Replace only this module's OS view: changing os.name globally also
        # changes pathlib's concrete path class on a non-Windows host.
        for patcher in (patch.object(process_lock, "os", SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)),
                        patch.dict(sys.modules, {"msvcrt": self.api})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_locks_first_byte_and_releases_after_body_failure(self):
        def check_position(fd, operation, size):
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
            self.assertEqual(size, 1)
        self.api.locking.side_effect = check_position
        with self.assertRaisesRegex(ValueError, "body failed"):
            with process_lock.lock(self.root):
                self.assertEqual((self.root / "lock").read_bytes(), b"0")
                raise ValueError("body failed")
        self.assertEqual([call.args[1] for call in self.api.locking.call_args_list], [1, 2])
        (self.root / "lock").write_bytes(b"user bytes")
        with process_lock.lock(self.root):
            pass
        self.assertEqual((self.root / "lock").read_bytes(), b"user bytes")

    def test_contention_retries_then_releases(self):
        self.api.locking.side_effect = [OSError(errno.EACCES, "busy"), None, None]
        with patch.object(process_lock.time, "sleep") as sleep:
            with process_lock.lock(self.root, timeout=1):
                pass
        sleep.assert_called_once()
        self.assertEqual([call.args[1] for call in self.api.locking.call_args_list], [1, 1, 2])

    def test_contention_timeout_and_unexpected_error_do_not_unlock(self):
        for error in (errno.EACCES, errno.EIO):
            with self.subTest(error=error):
                self.api.locking.reset_mock(side_effect=True)
                self.api.locking.side_effect = OSError(error, "failed")
                expected = RuntimeError if error == errno.EACCES else OSError
                with self.assertRaises(expected):
                    with process_lock.lock(self.root):
                        self.fail("Entered without acquiring the lock")
                self.api.locking.assert_called_once()


@unittest.skipIf(os.name == 'nt', 'POSIX shared installation locks')
class SharedInstallationLock(unittest.TestCase):
    def test_readers_coexist_and_replacement_waits_for_all_readers(self):
        with tempfile.TemporaryDirectory(prefix='aem-shared-lock-') as directory:
            root = Path(directory)
            with process_lock.lock(root, shared=True):
                with process_lock.lock(root, shared=True):
                    with self.assertRaises(RuntimeError):
                        with process_lock.lock(root):
                            self.fail('Replacement entered while CLI readers were active')
                with self.assertRaises(RuntimeError):
                    with process_lock.lock(root):
                        self.fail('Replacement entered before the last reader exited')
            with process_lock.lock(root):
                with self.assertRaises(RuntimeError):
                    with process_lock.lock(root, shared=True):
                        self.fail('CLI reader entered during package replacement')
