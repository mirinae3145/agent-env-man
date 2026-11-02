"""Distribution helper preserves child diagnostics and failure status."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


class DistributionCommands(unittest.TestCase):
    def setUp(self):
        self.run = runpy.run_path(str(Path(__file__).resolve().parents[1]
                                    / 'scripts/verify_distribution.py'))['run']
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_success_forwards_both_output_streams(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.run(sys.executable, '-c',
                     "import sys; print('child stdout'); print('child stderr', file=sys.stderr)",
                     cwd=self.temporary.name)
        lines = output.getvalue().splitlines()
        self.assertIn('child stdout', lines)
        self.assertIn('child stderr', lines)

    def test_failure_retains_diagnostic_and_exit_status(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(subprocess.CalledProcessError) as caught:
            self.run(sys.executable, '-c',
                     "import sys; print('child failure', file=sys.stderr); sys.exit(7)",
                     cwd=self.temporary.name)
        self.assertEqual(caught.exception.returncode, 7)
        self.assertIn('child failure', output.getvalue().splitlines())
