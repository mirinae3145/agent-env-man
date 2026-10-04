"""Click command boundaries: parsing, effects, exit codes, and callbacks."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from agent_env_man.cli import cli, main
from agent_env_man.cli_runtime import Runtime


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-cli-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "missing machine.toml"
        self.runner = CliRunner()

    def invoke(self, *args):
        return self.runner.invoke(cli, ["--config", str(self.config), *args])

    def test_help_at_every_command_level_has_no_runtime_effects(self):
        commands = [[], ["catalog"], ["self"]]
        for name, command in cli.commands.items():
            commands.append([name])
            if hasattr(command, "commands"):
                commands.extend([name, child] for child in command.commands)
        with patch.object(Runtime, "run", side_effect=AssertionError("Help reached execution")):
            for command in commands:
                for flag in ("-h", "--help"):
                    with self.subTest(command=command, flag=flag):
                        result = self.invoke(*command, flag)
                        self.assertEqual(result.exit_code, 0, result.output)
                        self.assertIn("Usage:", result.output)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertNotIn("_full-run", self.invoke("--help").output)

    def test_usage_errors_do_not_read_or_write_configuration(self):
        cases = (["publish"], ["detach"], ["catalog"], ["self"],
                 ["apply", "--adopt", "--replace"], ["status", "--ref"],
                 ["status", "--config", str(self.config)],
                 ["setup", "--remove-agent", "../bad"],
                 ["auto", "--trigger", "unknown"])
        with patch.object(Runtime, "run", side_effect=AssertionError("Usage error reached execution")):
            for args in cases:
                with self.subTest(args=args):
                    result = self.invoke(*args)
                    self.assertEqual(result.exit_code, 2, result.output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_nonfinite_and_out_of_range_durations_are_usage_errors(self):
        cases = (("setup", "--startup-hook-timeout"), ("status", "--git-timeout"),
                 ("setup", "--catalog-git-timeout"), ("setup", "--automation-git-timeout"),
                 ("status", "--timeout"), ("bootstrap", "--timeout"),
                 ("catalog", "update", "--timeout"), ("setup", "--catalog-timeout"),
                 ("setup", "--automation-timeout"), ("setup", "--catalog-interval"),
                 ("setup", "--automation-interval"))
        with patch.object(Runtime, "run", side_effect=AssertionError("Invalid duration reached execution")):
            for args in cases:
                for value in ("nan", "inf", "-1"):
                    with self.subTest(args=args, value=value):
                        result = self.invoke(*args, value)
                        self.assertEqual(result.exit_code, 2, result.output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_git_timeout_aliases_pass_the_same_value_to_delivery(self):
        self.config.write_text('version = 1\n', encoding='utf-8')
        for flag in ('--git-timeout', '--timeout'):
            with self.subTest(flag=flag), patch('agent_env_man.manager.Manager.update', return_value=([], False)) as update:
                result = self.invoke('update', flag, '7.5')
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(update.call_args.kwargs['timeout'], 7.5)

    def test_operation_errors_use_stderr_and_exit_one(self):
        result = self.invoke("locate", "missing")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("aem:", result.stderr)

    def test_main_returns_usage_codes(self):
        with self.runner.isolation():
            self.assertEqual(main(["unknown-command"]), 2)
            self.assertEqual(main(["--help"]), 0)

    def test_failed_operation_reports_are_printed_before_exit_one(self):
        self.config.write_text("version = 1\n", encoding="utf-8")
        with patch("agent_env_man.manager.Manager.update", return_value=([{"status": "failed", "error": "remote failed"}], True)):
            result = self.invoke("--json", "update")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(json.loads(result.stdout)[0]["error"], "remote failed")

    def test_callback_failure_is_structured_and_fail_open(self):
        result = self.invoke("agent-hook", "missing", "--agent", "codex")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("AEM instruction root lookup failed", result.stdout)
        self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertEqual(result.stderr, "")
