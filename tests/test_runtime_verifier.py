"""Runtime verifier diagnostics and target-interpreter isolation contracts."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import agent_env_man


_spec = importlib.util.spec_from_file_location(
    "aem_runtime_verifier", Path(__file__).parents[1] / "scripts/verify_runtime.py")
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)


class RuntimeVerifier(unittest.TestCase):

    def test_missing_interpreter_reports_failure_without_launch(self):
        with tempfile.TemporaryDirectory(prefix="aem-runtime-verifier-") as directory:
            missing = Path(directory) / "missing-python"
            output = io.StringIO()
            with redirect_stderr(output), patch.object(verifier.subprocess, "run") as run:
                self.assertEqual(verifier.main(["--python", str(missing)]), 1)
            run.assert_not_called()
            self.assertIn("Runtime Python is missing", output.getvalue())

    def test_target_failure_forwards_output_and_preserves_exit_status(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess([], 7, "target output\n", "target error\n")
        with patch.object(verifier.subprocess, "run", return_value=result) as run, redirect_stdout(
                stdout), redirect_stderr(stderr):
            self.assertEqual(verifier.main(["--python", sys.executable]), 7)
        self.assertEqual(stdout.getvalue(), "target output\n")
        self.assertEqual(stderr.getvalue(), "target error\n")
        command = run.call_args.args[0]
        self.assertEqual(command[0], str(Path(sys.executable).absolute()))
        self.assertEqual(command[1:3], ["-I", "-c"])
        self.assertEqual(Path(command[-1]), Path(verifier.__file__).resolve())

    def test_launch_failure_and_timeout_report_a_failed_check(self):
        for failure in (OSError("cannot launch"), subprocess.TimeoutExpired("python", 180)):
            with self.subTest(failure=failure):
                output = io.StringIO()
                with patch.object(verifier.subprocess, "run", side_effect=failure), redirect_stderr(output):
                    self.assertEqual(verifier.main(["--python", sys.executable]), 1)
                self.assertIn("Runtime verification:", output.getvalue())

    def test_success_without_output_is_silent(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(verifier.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), redirect_stdout(
                stdout), redirect_stderr(stderr):
            self.assertEqual(verifier.main(["--python", sys.executable]), 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_each_development_dependency_is_rejected(self):
        for dependency in ("coverage", "setuptools"):
            with self.subTest(dependency=dependency), patch.object(
                    verifier.util, "find_spec", side_effect=lambda name: object() if name == dependency else None):
                with self.assertRaisesRegex(RuntimeError, "development dependency: " + dependency):
                    verifier.verify()

    def test_package_outside_target_environment_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aem-runtime-prefix-") as directory:
            with patch.object(verifier.util, "find_spec", return_value=None), patch.object(
                    verifier.sys, "prefix", directory):
                with self.assertRaisesRegex(RuntimeError, "installed inside the target"):
                    verifier.verify()

    def test_editable_installation_is_rejected_before_any_operations(self):
        with tempfile.TemporaryDirectory(prefix="aem-runtime-editable-") as directory:
            package = Path(directory) / "lib/agent_env_man/__init__.py"
            distribution = SimpleNamespace(read_text=lambda name: '{"dir_info": {"editable": true}}')
            with patch.object(verifier.util, "find_spec", return_value=None), patch.object(
                    verifier.sys, "prefix", directory), patch.object(agent_env_man, "__file__", str(package)), patch.object(
                    verifier.metadata, "distribution", return_value=distribution), patch.object(
                    verifier.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "installed wheel"):
                    verifier.verify()
            run.assert_not_called()
