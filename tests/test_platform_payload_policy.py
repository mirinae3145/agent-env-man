"""Native Windows refusal and migration of the obsolete skip setting."""
import importlib.util
import io
from contextlib import redirect_stderr
from pathlib import Path
import unittest
from unittest.mock import patch

from click.testing import CliRunner
import tomlkit

from agent_env_man import automation
from agent_env_man.cli import cli
from agent_env_man.model import Config, Error
import test_directories


class PlatformSupport(unittest.TestCase):
    def test_windows_cli_refuses_before_configuration_access(self):
        with patch('agent_env_man.cli.sys.platform', 'win32'), patch(
                'agent_env_man.cli_runtime.MachineFile', side_effect=AssertionError('config access')):
            result = CliRunner().invoke(cli, ['bootstrap', '/unused/catalog.toml'])
            self.assertEqual(result.exit_code, 1)
            self.assertIn('WSL or Linux', result.output)
            self.assertEqual(CliRunner().invoke(cli, ['--help']).exit_code, 0)

    def test_windows_installer_refuses_before_discovery_or_subprocesses(self):
        spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'scripts/setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.sys, 'platform', 'win32'), patch.object(module.shutil, 'which') as which, \
                patch.object(module.subprocess, 'run') as run, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(module.main(['--shell', 'bash']), 1)
        which.assert_not_called()
        run.assert_not_called()
        self.assertIn('WSL or Linux', error.getvalue())

    def test_legacy_boolean_is_validated_but_has_no_effective_skip_policy(self):
        for value in (True, False):
            self.assertEqual(automation.policy({'skip_unsupported': value}), automation.policy({}))
        for value in ('true', 1, None):
            with self.assertRaises(Error):
                automation.policy({'skip_unsupported': value})
        for option in ('--automation-skip-unsupported', '--no-automation-skip-unsupported'):
            self.assertEqual(CliRunner().invoke(cli, ['setup', option]).exit_code, 2)

    def test_legacy_skip_cannot_hide_missing_sources_in_full_automation(self):
        case = test_directories.Directories()
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.external()
        document = tomlkit.parse(case.config.read_text())
        document['automation'] = {'skip_unsupported': True}
        case.config.write_text(tomlkit.dumps(document))
        case.external_root.rename(case.root / 'offline-source')
        report, failed = automation.full_content(case.manager(), 30)
        self.assertTrue(failed)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('cases', report['sources'])
        self.assertFalse(case.target.exists())
        self.assertNotIn('skip_unsupported', Config(case.config).automation)
