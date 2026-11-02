"""Mocked Windows calls verify lock ownership without claiming native OS behavior."""
from process_support import popen_hidden

import errno
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_env_man import process_lock


class WindowsLock(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-windows-lock-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
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
            root = Path(directory).resolve()
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


@unittest.skipUnless(os.name == 'posix', 'POSIX process locking')
class PosixProcesses(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-posix-lock-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / 'lock').write_bytes(b'persistent user bytes')
        self.identity = (self.root / 'lock').stat().st_ino

    def owner(self, *, shared=False, timeout=0):
        program = """
import sys
from pathlib import Path
from agent_env_man.process_lock import lock
print('starting', flush=True)
with lock(Path(sys.argv[1]), shared=sys.argv[2] == 'True', timeout=float(sys.argv[3])):
    print('locked', flush=True)
    sys.stdin.read(1)
"""
        child = popen_hidden([sys.executable, '-c', program, str(self.root), str(shared), str(timeout)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        self.message(child, b'starting\n')
        return child

    def message(self, child, expected):
        import select
        # Read one byte at a time: buffered readline can hide the next ready
        # line from select when a child writes both handshake lines together.
        line = b''
        while not line.endswith(b'\n'):
            self.assertTrue(select.select([child.stdout], [], [], 10)[0], 'Child did not signal readiness')
            byte = os.read(child.stdout.fileno(), 1)
            self.assertTrue(byte, 'Child exited before its readiness handshake')
            line += byte
        self.assertEqual(line, expected)

    def release(self, child):
        child.stdin.write(b'x')
        child.stdin.flush()
        self.assertEqual(child.wait(timeout=10), 0)

    def assert_preserved(self):
        self.assertEqual((self.root / 'lock').read_bytes(), b'persistent user bytes')
        self.assertEqual((self.root / 'lock').stat().st_ino, self.identity)

    def test_shared_processes_exclude_replacement_until_last_reader_exits(self):
        first, second = self.owner(shared=True), self.owner(shared=True)
        self.message(first, b'locked\n')
        self.message(second, b'locked\n')
        for owner in (first, second):
            with self.assertRaisesRegex(RuntimeError, 'holds this config'):
                with process_lock.lock(self.root):
                    self.fail('Replacement entered with an active reader')
            self.release(owner)
        with process_lock.lock(self.root):
            self.assert_preserved()

    def test_terminated_owner_releases_lock_without_replacing_lock_file(self):
        child = self.owner()
        self.message(child, b'locked\n')
        with self.assertRaises(RuntimeError), process_lock.lock(self.root, shared=True):
            self.fail('Reader entered during replacement')
        child.kill()
        child.wait(timeout=10)
        with process_lock.lock(self.root):
            self.assert_preserved()

    def test_waiter_acquires_after_owner_exits(self):
        owner = self.owner()
        self.message(owner, b'locked\n')
        waiter = self.owner(timeout=5)
        self.release(owner)
        self.message(waiter, b'locked\n')
        with self.assertRaises(RuntimeError), process_lock.lock(self.root):
            self.fail('Waiter failed to retain ownership')
        self.release(waiter)
        with process_lock.lock(self.root):
            self.assert_preserved()

    def test_timeout_does_not_release_another_process_lock(self):
        owner = self.owner()
        self.message(owner, b'locked\n')
        with self.assertRaisesRegex(RuntimeError, 'holds this config'):
            with process_lock.lock(self.root, timeout=0.05):
                self.fail('Waiter entered while owner remained alive')
        self.assertIsNone(owner.poll())
        with self.assertRaises(RuntimeError), process_lock.lock(self.root):
            self.fail('Timed-out waiter released another owner')
        self.release(owner)
        with process_lock.lock(self.root):
            self.assert_preserved()
