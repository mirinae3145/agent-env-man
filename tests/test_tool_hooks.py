"""Tool hooks are checked, never installed, and only for tools that are present."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agent_env_man.cli import main
from agent_env_man.model import Config

HERDR = 'bash {root}/hooks/herdr-agent-state.sh session'


class ToolHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.roots = {name: self.tmp / name for name in ('claude', 'claude-lab')}
        for name, root in self.roots.items():
            root.mkdir()
            self.hook(name)
        self.config = self.tmp / 'machine.toml'
        self.write_config()

    def hook(self, name, event='SessionStart', command=None):
        root = self.roots[name]
        (root / 'settings.json').write_text(json.dumps({'hooks': {event: [
            {'matcher': '', 'hooks': [{'type': 'command', 'command': command or HERDR.format(root=root)}]}]}}))

    def write_config(self, tool='herdr', command=sys.executable, extra=''):
        agents = ''.join(f'[agents.{name}]\nroot = "{root}"\nskills = "{root}/skills"\n'
                         for name, root in self.roots.items())
        self.config.write_text(f'version = 1\n{agents}[tool_hooks.{tool}]\ncommand = "{command}"\n'
                               f'event = "SessionStart"\ncontains = "herdr-agent-state.sh"\n{extra}')

    def check(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), '--json', 'check-tool-hooks', *args])
        return code, output.getvalue(), errors.getvalue()

    def report(self, *args, expect=0):
        code, output, errors = self.check(*args)
        self.assertEqual(code, expect, errors)
        return json.loads(output)

    def statuses(self, report):
        return {item['agent']: item['status'] for tool in report['tools'] for item in tool['agents']}


class Check(ToolHooks):
    def test_present_in_every_profile_passes(self):
        report = self.report()
        self.assertEqual(self.statuses(report), {'claude': 'present', 'claude-lab': 'present'})
        self.assertEqual(report['missing'], 0)

    def test_missing_hook_fails_with_advice_naming_the_profile_root(self):
        self.hook('claude-lab', command='bash other.sh')
        report = self.report(expect=1)
        self.assertEqual(self.statuses(report), {'claude': 'present', 'claude-lab': 'missing'})
        advice = report['tools'][0]['agents'][1]['advice']
        self.assertIn(f"CLAUDE_CONFIG_DIR={self.roots['claude-lab']}", advice)
        self.assertIn('does not install', advice)

    def test_hook_under_another_event_does_not_count(self):
        self.hook('claude', event='Stop')
        self.assertEqual(self.statuses(self.report(expect=1))['claude'], 'missing')

    def test_malformed_hooks_are_reported_as_an_error(self):
        for hooks in ([], {'SessionStart': ['not a group']}):
            (self.roots['claude'] / 'settings.json').write_text(json.dumps({'hooks': hooks}))
            code, _, errors = self.check()
            self.assertEqual(code, 1)
            self.assertIn('hooks must map each event to a list of hook groups', errors)

    def test_absent_tool_is_skipped_without_reading_profiles(self):
        self.write_config(command='definitely-not-installed-tool')
        (self.roots['claude'] / 'settings.json').write_text('{broken')
        report = self.report()
        self.assertEqual((report['tools'][0]['installed'], report['tools'][0]['agents'], report['missing']), (False, [], 0))
        code, _, _ = self.check('--agent', 'claude')
        self.assertEqual(code, 0)

    def test_agents_field_and_agent_option_narrow_the_check(self):
        self.hook('claude-lab', command='bash other.sh')
        self.write_config(extra='agents = ["claude"]\n')
        self.assertEqual(self.statuses(self.report()), {'claude': 'present'})
        self.write_config()
        self.assertEqual(self.statuses(self.report('--agent', 'claude')), {'claude': 'present'})
        code, _, errors = self.check('--agent', 'nobody')
        self.assertEqual(code, 1)
        self.assertIn('nobody', errors)

    def test_check_changes_nothing_and_text_output_is_plain(self):
        before = {p: p.read_bytes() for p in self.tmp.rglob('*') if p.is_file()}
        self.hook('claude-lab', command='bash other.sh')
        before[self.roots['claude-lab'] / 'settings.json'] = (self.roots['claude-lab'] / 'settings.json').read_bytes()
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            main(['--config', str(self.config), 'check-tool-hooks'])
        self.assertIn('herdr: claude present, claude-lab missing', output.getvalue())
        self.assertEqual({p: p.read_bytes() for p in self.tmp.rglob('*') if p.is_file()}, before)

    def test_no_declarations_is_not_an_error(self):
        self.config.write_text('version = 1\n')
        self.assertEqual(self.report()['tools'], [])


class Validation(ToolHooks):
    def refused(self, extra='', tool='herdr'):
        self.write_config(tool=tool, extra=extra)
        code, _, errors = self.check()
        self.assertEqual(code, 1)
        return errors

    def test_bad_declarations_are_refused(self):
        self.assertIn('requires command', self.refused('colour = "red"\n'))
        self.assertIn('agents', self.refused('agents = ["claude-gone"]\n'))
        self.assertIn('agents must be a nonempty list', self.refused('agents = "claude"\n'))
        self.assertIn('agents must be a nonempty list', self.refused('agents = []\n'))
        self.assertIn('requires command', self.refused(tool='x.y'))

    def test_unknown_event_is_refused(self):
        self.config.write_text(self.config.read_text().replace('"SessionStart"', '"Nope"'))
        code, _, errors = self.check()
        self.assertEqual(code, 1)
        self.assertIn('event must be one of', errors)

    def test_machine_configuration_accepts_the_section(self):
        self.assertIn('claude-lab', Config(self.config).agents)
        self.write_config(extra='agents = ["claude-gone"]\n')
        with self.assertRaises(Exception):
            Config(self.config)


if __name__ == '__main__':
    unittest.main()
