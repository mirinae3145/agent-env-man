"""Failed atomic writes preserve the destination and remove temporary files."""

import os
import hashlib
import json
import stat
import time
import tracemalloc
from itertools import count
from threading import Barrier, Lock, Event
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man.model import Error
from agent_env_man.storage import atomic_write, fingerprint


class StorageSafety(unittest.TestCase):
    def test_atomic_write_failure_preserves_target_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory(prefix="aem-atomic-write-") as directory:
            target = Path(directory) / "state.json"
            target.write_bytes(b"original\n")
            for operation in ("fsync", "chmod", "replace"):
                with self.subTest(operation=operation), patch(
                        "agent_env_man.storage.os." + operation, side_effect=OSError("write failed")):
                    with self.assertRaisesRegex(OSError, "write failed"):
                        atomic_write(target, b"replacement\n")
                self.assertEqual(target.read_bytes(), b"original\n")
                self.assertEqual(list(target.parent.iterdir()), [target])
            atomic_write(target, b"replacement\n")
            self.assertEqual(target.read_bytes(), b"replacement\n")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO payload fixture requires POSIX")
    def test_fingerprint_rejects_special_files_without_reading_them(self):
        with tempfile.TemporaryDirectory(prefix="aem-special-file-") as directory:
            root = Path(directory).resolve()
            fifo = root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(Error, "Special files are unsupported"):
                fingerprint(root)
            self.assertTrue(fifo.exists())


class ParallelPayloadInspection(unittest.TestCase):
    def test_fingerprint_memory_stays_bounded_across_many_directories(self):
        with tempfile.TemporaryDirectory(prefix="aem-bounded-hash-") as directory:
            root = Path(directory).resolve()
            for index in range(300):
                child = root / f"directory-{index:03}"
                child.mkdir()
                for number in range(20):
                    (child / f"file-{number:02}").touch()
            # Many small directories keep enumeration memory small. Only the
            # fingerprint call is measured, excluding fixture construction.
            for parallel in (False, True):
                with self.subTest(parallel=parallel):
                    timer = count(step=0.003).__next__ if parallel else lambda: 0
                    with patch("agent_env_man.payload_io.perf_counter", new=timer):
                        tracemalloc.start()
                        try:
                            fingerprint(root)
                            _, peak = tracemalloc.get_traced_memory()
                        finally:
                            tracemalloc.stop()
                    # Allow four simultaneous 1 MiB read buffers plus overhead,
                    # but not thousands of retained futures and their results.
                    self.assertLess(peak, 8 * 1024 * 1024)

    def test_parallel_reads_preserve_serial_hash_encoding(self):
        with tempfile.TemporaryDirectory(prefix="aem-parallel-hash-") as directory:
            root = Path(directory).resolve()
            (root / "0-probe").write_bytes(b"probe")
            (root / "a").mkdir()
            (root / "a" / "empty").mkdir()
            for name in ("a/one", "a/two", "a/three", "a/four", "a/five", "a/six", "a/seven", "a/eight", "a-", "z"):
                (root / name).write_bytes(name.encode() * 100)
            (root / "z").chmod(0o755)
            digest = hashlib.sha256()

            def serial(current, relative):
                info = current.lstat()
                kind = "d" if stat.S_ISDIR(info.st_mode) else "f"
                executable = info.st_mode & 0o111
                digest.update(json.dumps([relative, kind, executable], ensure_ascii=True).encode() + b"\0")
                if kind == "d":
                    for child in sorted(current.iterdir(), key=lambda p: p.name):
                        serial(child, relative + "/" + child.name)
                else:
                    digest.update(hashlib.sha256(current.read_bytes()).digest())

            serial(root, "")
            expected = digest.hexdigest()
            barrier = Barrier(4, timeout=5)
            real_open = Path.open

            class Reader:
                def __init__(self, stream, synchronize, delay):
                    self.stream, self.synchronize, self.delay = stream, synchronize, delay
                def __enter__(self):
                    self.stream.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.stream.__exit__(*args)
                def read(self, size):
                    if self.delay:
                        self.delay = False
                        time.sleep(0.005)
                    if self.synchronize:
                        self.synchronize = False
                        barrier.wait()
                    return self.stream.read(size)

            def opened(path, *args, **kwargs):
                return Reader(real_open(path, *args, **kwargs), path.parent.name == "a", path.name == "0-probe")

            with patch.object(Path, "open", opened):
                self.assertEqual(fingerprint(root), expected)
            from agent_env_man import payload_links
            identities = {(p.stat().st_dev, p.stat().st_ino) for p in (root / "a").iterdir() if p.is_file()}
            barrier = Barrier(4, timeout=5)
            seen = set()
            lock = Lock()
            real_read = payload_links.os.read
            probe = (root / "0-probe").stat()
            probe_identity = probe.st_dev, probe.st_ino

            def read(fd, size):
                info = os.fstat(fd)
                identity = info.st_dev, info.st_ino
                with lock:
                    synchronize = identity in identities and identity not in seen
                    seen.add(identity)
                if identity == probe_identity:
                    time.sleep(0.005)
                if synchronize:
                    barrier.wait()
                return real_read(fd, size)

            with patch.object(payload_links.os, "read", side_effect=read):
                self.assertEqual(fingerprint(root, preserve_symlinks=True), expected)

    def test_parallel_inspection_preserves_permission_policy_and_node_types(self):
        from agent_env_man import payload_links, permissions
        with tempfile.TemporaryDirectory(prefix="aem-parallel-permissions-") as directory:
            root = Path(directory).resolve()
            (root / "nested").mkdir()
            for index in range(12):
                (root / "nested" / f"file-{index:02}").write_bytes(str(index).encode())
            executable = root / "nested" / "file-00"
            executable.chmod(0o644)
            (root / "alias").symlink_to("nested/file-00")
            policy = {"permissions": "best-effort", "preserve_symlinks": True}
            with patch("agent_env_man.payload_io.perf_counter", new=lambda: 0):
                serial = fingerprint(root, **policy)
                strict = fingerprint(root, preserve_symlinks=True)
            expected_modes = {".": stat.S_IMODE(root.stat().st_mode),
                              "nested": stat.S_IMODE((root / "nested").stat().st_mode)}
            expected_types = {".": "d", "nested": "d"}
            for child in (root / "nested").iterdir():
                relative = child.relative_to(root).as_posix()
                expected_modes[relative] = stat.S_IMODE(child.stat().st_mode)
                expected_types[relative] = "f"
            with patch("agent_env_man.payload_io.perf_counter", new=count(step=0.003).__next__):
                self.assertEqual(fingerprint(root, **policy), serial)
                self.assertEqual(fingerprint(root, preserve_symlinks=True), strict)
                node_types = {}
                with patch.object(payload_links.os, "read", side_effect=AssertionError("Snapshot read content")):
                    self.assertEqual(permissions.snapshot(root, node_types=node_types, **policy), expected_modes)
                self.assertEqual(node_types, expected_types)
                executable.chmod(0o755)
                self.assertEqual(fingerprint(root, **policy), serial)
                self.assertNotEqual(fingerprint(root, preserve_symlinks=True), strict)
                (root / "alias").unlink()
                (root / "alias").symlink_to("nested/file-01")
                self.assertNotEqual(fingerprint(root, **policy), serial)
            # The ordinary (link-rejecting) parallel path obeys the same policy.
            (root / "alias").unlink()
            with patch("agent_env_man.payload_io.perf_counter", new=count(step=0.003).__next__):
                before = fingerprint(root, permissions="best-effort")
                executable.chmod(0o644)
                self.assertEqual(fingerprint(root, permissions="best-effort"), before)
                self.assertEqual(fingerprint(root, permissions="best-effort", preserve_symlinks=True), before)

    def test_failed_parallel_copy_keeps_parents_pinned_until_readers_finish(self):
        from agent_env_man import payload_links
        with tempfile.TemporaryDirectory(prefix="aem-parallel-failure-") as directory:
            root = Path(directory).resolve() / "source"
            root.mkdir()
            for name in ("0-probe", "a", "b"):
                (root / name).write_bytes(name.encode())
            identity = {name: (root / name).stat().st_ino for name in ("0-probe", "a", "b")}
            started, finished = Event(), Event()
            violations = []
            real_read, real_close = os.read, os.close

            def read(fd, size):
                inode = os.fstat(fd).st_ino
                if inode == identity["0-probe"]:
                    time.sleep(0.005)
                if inode == identity["a"]:
                    if not started.wait(5):
                        raise AssertionError("Sibling reader was not scheduled")
                    raise OSError("failed leaf read")
                if inode == identity["b"]:
                    started.set()
                    time.sleep(0.02)
                return real_read(fd, size)

            def close(fd):
                info = os.fstat(fd)
                if stat.S_ISDIR(info.st_mode) and started.is_set() and not finished.is_set():
                    violations.append(fd)
                if info.st_ino == identity["b"]:
                    finished.set()
                return real_close(fd)

            with patch.object(payload_links.os, "read", side_effect=read), patch.object(payload_links.os, "close", side_effect=close):
                with self.assertRaisesRegex(OSError, "failed leaf read"):
                    payload_links.scan(root, destination=root.parent / "copy")
            self.assertTrue(started.is_set())
            self.assertTrue(finished.is_set())
            self.assertEqual(violations, [])
