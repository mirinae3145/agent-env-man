"""Live diagnostics preserve command results and machine callback boundaries."""

import io
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from agent_env_man.cli import cli, main
from agent_env_man.manager import Manager
from agent_env_man.model import Error
from agent_env_man.progress import Progress, phase


class ProgressCommands(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-progress-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / "machine.toml"
        self.config.write_text("version = 1\n", encoding="utf-8")
        self.runner = CliRunner()
        self.enterContext(patch("agent_env_man.progress.MIN_INTERVAL", 0.005))

    def invoke(self, *args):
        return self.runner.invoke(cli, ["--config", str(self.config), *args])

    def waiting_update(self, *, failed=False):
        visible = Event()
        original = Progress._write

        def write(reporter, line):
            original(reporter, line)
            if "Waiting on source: fixture" in line:
                visible.set()

        def update(*args, **kwargs):
            with phase("Waiting on source", "fixture"):
                self.assertTrue(visible.wait(3), "Progress was not visible during blocked work")
                if failed:
                    raise Error("fixture failed")
            return [], False
        return update, write

    def test_explicit_progress_is_visible_before_blocked_operation_returns(self):
        update, write = self.waiting_update()
        with patch.object(Manager, "update", side_effect=update), patch.object(Progress, "_write", write), \
                patch("agent_env_man.progress.DELAY", 0.005), patch("agent_env_man.progress.POLL_INTERVAL", 0.01):
            result = self.invoke("--json", "--progress", "update")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertIn("Waiting on source: fixture", result.stderr)
        self.assertIn("Finished", result.stderr)

    def test_failure_stops_reporter_without_reporting_completion(self):
        update, write = self.waiting_update(failed=True)
        with patch.object(Manager, "update", side_effect=update), patch.object(Progress, "_write", write), \
                patch("agent_env_man.progress.DELAY", 0.005), patch("agent_env_man.progress.POLL_INTERVAL", 0.01):
            result = self.invoke("--progress", "update")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(result.stdout, "")
        self.assertIn("fixture failed", result.stderr)
        self.assertIn("Failed", result.stderr)
        self.assertNotIn("Finished", result.stderr)

    def test_default_redirected_output_is_quiet(self):
        with patch.object(Manager, "update", return_value=([], False)):
            result = self.invoke("--json", "update")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertEqual(result.stderr, "")

    def test_terminal_auto_mode_and_explicit_disable(self):
        for options, expected in (([], True), (["--no-progress"], False), (["--json"], False)):
            with self.subTest(options=options), self.runner.isolation() as streams:
                with patch.object(sys.stderr, "isatty", return_value=True), \
                        patch.object(Manager, "update", return_value=([], False)), \
                        patch("agent_env_man.progress.DELAY", 0):
                    # Force one heartbeat while the operation is still active.
                    def update(*args, **kwargs):
                        import agent_env_man.progress as progress
                        observer = progress._observer.get()
                        if observer is not None:
                            observer.tick()
                        return [], False
                    with patch.object(Manager, "update", side_effect=update):
                        code = main(["--config", str(self.config), *options, "update"])
                stderr = streams[1].getvalue().decode()
            self.assertEqual(code, 0)
            self.assertEqual("Running operation" in stderr, expected)

    def test_callbacks_remain_silent_even_when_progress_is_forced(self):
        with patch("agent_env_man.progress.Thread.start", side_effect=AssertionError("Callback started reporter")):
            result = self.invoke("--progress", "agent-hook", "missing", "--agent", "codex")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertEqual(result.stderr, "")

    def test_help_does_not_start_progress_or_read_configuration(self):
        missing = self.root / "absent.toml"
        with patch("agent_env_man.cli_runtime.Runtime.run", side_effect=AssertionError("Help reached runtime")):
            result = self.runner.invoke(cli, ["--config", str(missing), "--progress", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stderr, "")
        self.assertFalse(missing.exists())

    def test_closed_progress_stream_does_not_fail_core_operation(self):
        sink = io.StringIO()
        sink.close()
        with Progress("fixture", sink, enabled=True, immediate=True):
            with phase("Still working"):
                pass

    def test_nested_phases_restore_parent_and_throttle_repeated_lines(self):
        sink = io.StringIO()
        with patch("agent_env_man.progress.Thread.start"), patch("agent_env_man.progress.Thread.join"), \
                patch("agent_env_man.progress.time.monotonic", return_value=10):
            with Progress("fixture", sink, enabled=True) as reporter:
                with phase("Parent", "source"):
                    with phase("Child", "item"):
                        reporter.started = 0
                        reporter.tick()
                        reporter.tick()
                    reporter.tick(force=True)
        lines = sink.getvalue().splitlines()
        self.assertEqual(sum("Child: item" in line for line in lines), 1)
        self.assertIn("Parent: source", lines[-2])
        self.assertNotIn("Child", lines[-2])

    def test_real_payload_inspection_identifies_the_current_item(self):
        from test_directories import Directories
        fixture = Directories()
        fixture.setUp()
        try:
            fixture.external(mode="link")
            visible = Event()
            original_write = Progress._write
            original_open = Path.open
            def write(reporter, line):
                original_write(reporter, line)
                if "Inspecting source content: cases:directory" in line:
                    visible.set()
            class Reader:
                def __init__(self, stream):
                    self.stream = stream
                def __enter__(self):
                    self.stream.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.stream.__exit__(*args)
                def read(self, size):
                    self_test.assertTrue(visible.wait(3), "Actual payload scan had no current-item progress")
                    return self.stream.read(size)
            self_test = self
            def opened(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return Reader(stream) if path == fixture.external_root / "first.md" else stream
            with patch.object(Path, "open", opened), patch.object(Progress, "_write", write), \
                    patch("agent_env_man.progress.DELAY", 0.005), patch("agent_env_man.progress.POLL_INTERVAL", 0.01):
                result = self.runner.invoke(cli, ["--config", str(fixture.config), "--json", "--progress", "status"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)["items"][0]["status"], "not-installed")
            self.assertIn("Inspecting source 1/1", result.stderr)
        finally:
            fixture.doCleanups()

    def external_copy(self, *, best_effort=False):
        from test_directories import Directories
        fixture = Directories()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if best_effort:
            fixture.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        fixture.external(mode="copy")
        return fixture

    def test_progress_bootstrap_reuses_saved_external_binding(self):
        fixture = self.external_copy()
        result = self.runner.invoke(cli, ["--config", str(fixture.config),
                                         "--json", "--progress", "bootstrap"])
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        self.assertEqual(json.loads(result.stdout)["items"][0]["status"], "external-ready")
        self.assertIn("Finished", result.stderr)
        self.assertFalse(fixture.target.exists())

    def test_progress_applies_best_effort_copy_and_records_current_contents(self):
        fixture = self.external_copy(best_effort=True)
        result = self.runner.invoke(cli, ["--config", str(fixture.config),
                                         "--json", "--progress", "apply", "--item", "cases"])
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        self.assertEqual(json.loads(result.stdout)[0]["action"], "install")
        self.assertIn("Finished", result.stderr)
        self.assertEqual((fixture.target / "first.md").read_bytes(),
                         (fixture.external_root / "first.md").read_bytes())
        self.assertEqual(fixture.run_cli("status")["items"][0]["status"], "current")

    def test_progress_status_observes_installed_copy(self):
        fixture = self.external_copy()
        fixture.run_cli("apply", "--item", "cases")
        expected = fixture.run_cli("status")
        for option in ("--no-progress", "--progress"):
            with self.subTest(option=option):
                result = self.runner.invoke(cli, ["--config", str(fixture.config),
                                                 "--json", option, "status"])
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                self.assertEqual(json.loads(result.stdout), expected)
                self.assertEqual("Finished" in result.stderr, option == "--progress")

    def test_terminal_default_status_observes_installed_copy(self):
        fixture = self.external_copy()
        fixture.run_cli("apply", "--item", "cases")
        with self.runner.isolation() as streams:
            with patch.object(sys.stderr, "isatty", return_value=True), \
                    patch("agent_env_man.progress.DELAY", 0):
                code = main(["--config", str(fixture.config), "status"])
            stdout = streams[0].getvalue().decode()
        self.assertEqual(code, 0)
        self.assertIn("current", stdout)

    def test_repository_fetch_is_visible_while_subprocess_is_blocked(self):
        import subprocess
        from test_skill_catalog import SkillCatalog
        fixture = SkillCatalog()
        fixture.setUp()
        try:
            fixture.bootstrap()
            visible = Event()
            original_write, original_communicate = Progress._write, subprocess.Popen.communicate
            def write(reporter, line):
                original_write(reporter, line)
                if "Fetching repository" in line:
                    visible.set()
            def communicate(process, *args, **kwargs):
                if "fetch" in process.args:
                    self.assertTrue(visible.wait(3), "Fetch had no live phase before completion")
                return original_communicate(process, *args, **kwargs)
            with patch.object(subprocess.Popen, "communicate", communicate), \
                    patch.object(Progress, "_write", write), patch("agent_env_man.progress.DELAY", 0.005), \
                    patch("agent_env_man.progress.POLL_INTERVAL", 0.01):
                result = self.runner.invoke(cli, ["--config", str(fixture.config), "--json", "--progress", "update"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIsInstance(json.loads(result.stdout), list)
            self.assertIn("Fetching repository", result.stderr)
            self.assertNotIn(str(fixture.root), result.stderr)
        finally:
            fixture.doCleanups()

    def test_preview_is_identified_without_claiming_installation(self):
        result = self.invoke("--progress", "apply", "--dry-run")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("[apply preview", result.stderr)
        self.assertNotIn("Installing target", result.stderr)
        self.assertIn("no items to install", result.stdout)

    def test_publication_reports_push_before_subprocess_returns(self):
        import subprocess
        from test_skill_catalog import SkillCatalog
        from test_git_catalog import GitCatalog
        from test_self_publish import SelfPublication

        for fixture_class in (SkillCatalog, GitCatalog, SelfPublication):
            with self.subTest(workflow=fixture_class.__name__):
                fixture = fixture_class()
                fixture.setUp()
                try:
                    if fixture_class is SkillCatalog:
                        fixture.bootstrap()
                        command = ["publish", "report"]
                    elif fixture_class is GitCatalog:
                        fixture.boot()
                        command = ["catalog", "publish"]
                    else:
                        command = ["self", "publish", "--checkout", str(fixture.checkout)]
                    visible = Event()
                    original_write = Progress._write
                    original_communicate = subprocess.Popen.communicate

                    def write(reporter, line):
                        original_write(reporter, line)
                        if "Publishing repository" in line:
                            visible.set()

                    def communicate(process, *args, **kwargs):
                        if "push" in process.args:
                            self.assertTrue(visible.wait(3), "Push had no publication phase before completion")
                        return original_communicate(process, *args, **kwargs)

                    config = getattr(fixture, "config", fixture.root / "unused-machine.toml")
                    with patch.object(subprocess.Popen, "communicate", communicate), \
                            patch.object(Progress, "_write", write), \
                            patch("agent_env_man.progress.DELAY", 0.005), \
                            patch("agent_env_man.progress.POLL_INTERVAL", 0.01):
                        result = self.runner.invoke(cli, ["--config", str(config), "--json", "--progress", *command])
                    self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                    report = json.loads(result.stdout)
                    self.assertEqual((report[0] if isinstance(report, list) else report)["status"], "published")
                    self.assertTrue(visible.is_set(), "Publication did not run a push")
                finally:
                    fixture.doCleanups()
