"""The standalone filesystem verifier executes safely inside its own fixtures."""

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    'aem_payload_mount_verifier', Path(__file__).parents[1] / 'scripts/verify_payload_mount.py')
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)


class PayloadMountVerifier(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-verifier-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.marker = self.root / 'outside-fixture'
        self.marker.write_bytes(b'preserve existing file')
        patcher = patch.object(sys, 'argv', ['verify_payload_mount.py', '--root', str(self.root)])
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipIf(os.name == 'nt', 'POSIX filesystem verification')
    def test_full_local_workflow_and_cleanup_preserve_preexisting_root_files(self):
        output = io.StringIO()
        with redirect_stdout(output):
            verifier.main()
        self.assertIn('PASS: apply, status, collection', output.getvalue())
        self.assertEqual(list(self.root.iterdir()), [self.marker])
        self.assertEqual(self.marker.read_bytes(), b'preserve existing file')

    @unittest.skipIf(os.name == 'nt', 'POSIX filesystem verification')
    def test_failed_child_reports_diagnostics_and_removes_only_its_fixture(self):
        result = subprocess.CompletedProcess([], 7, 'child failure output', 'child failure error')
        with patch.object(verifier.subprocess, 'run', return_value=result), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'child failure output') as failure:
                verifier.main()
            self.assertIn('child failure error', str(failure.exception))
        self.assertEqual(list(self.root.iterdir()), [self.marker])
        self.assertEqual(self.marker.read_bytes(), b'preserve existing file')

    def test_windows_refusal_happens_before_creating_a_fixture(self):
        with patch.object(verifier, 'os', SimpleNamespace(name='nt')):
            with self.assertRaisesRegex(RuntimeError, 'POSIX descriptor scans'):
                verifier.main()
        self.assertEqual(list(self.root.iterdir()), [self.marker])
        self.assertEqual(self.marker.read_bytes(), b'preserve existing file')


if __name__ == '__main__':
    unittest.main()
