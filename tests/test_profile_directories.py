"""A catalog directory declared for a named profile installs into that profile's root and is skipped elsewhere."""
import io
from contextlib import redirect_stderr, redirect_stdout

import tomlkit

import test_named_profiles
from agent_env_man.cli import main
from test_setup import SetupFixture


class ProfileDirectories(SetupFixture):
    prepare = test_named_profiles.NamedProfiles.prepare

    def declare(self, **fields):
        self.prepare()
        (self.external / 'shared').mkdir()
        (self.external / 'shared/note.md').write_text('shared\n')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['directories'] = {
            'plain': {'source': 'personal', 'subdir': 'shared', 'install': {'root': 'home', 'destination': 'plain'}},
            'lab-agents': {'source': 'personal', 'subdir': 'shared', 'install': {'destination': 'agents'}, **fields}}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        machine.setdefault('roots', {})['home'] = str(self.home)
        self.config.write_text(tomlkit.dumps(machine))

    def refused(self, text):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), 'apply', '--dry-run'])
        self.assertEqual(code, 1, output.getvalue())
        self.assertIn(text, errors.getvalue())

    def items(self, *args):
        return {row['item'] for row in self.run_cli('status', *args)['items']}

    def test_machine_without_the_profile_skips_the_declaration(self):
        self.declare(agent='claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply')
        self.assertNotIn('lab-agents:directory', self.items())
        self.assertIn('plain:directory', self.items())
        self.assertFalse((self.home / '.claude-lab').exists())

    def test_registered_profile_installs_into_its_own_root_by_default(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertEqual((self.home / '.claude-lab/agents/note.md').read_text(), 'shared\n')
        self.assertFalse((self.home / '.claude/agents').exists())

    def test_other_profile_selection_leaves_a_bound_directory_alone(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply', '--agent', 'claude')
        self.assertFalse((self.home / '.claude-lab/agents').exists())
        self.assertNotIn('lab-agents:directory', self.items('--agent', 'claude'))
        self.assertIn('lab-agents:directory', self.items('--agent', 'claude-lab'))

    def test_an_unbound_directory_stays_independent_of_agent_selection(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertTrue((self.home / 'plain/note.md').is_file())
        self.assertIn('plain:directory', self.items('--agent', 'claude'))
        self.assertIn('plain:directory', self.items('--agent', 'claude-lab'))

    def test_an_unknown_agent_name_is_refused(self):
        self.declare(agent='nobody')
        self.refused('Unsupported agent: nobody')

    def test_a_non_string_agent_is_refused(self):
        self.declare(agent=5)
        self.refused('agent must be a destination name')

    def installed(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply')
        self.assertTrue((self.home / '.claude-lab/agents/note.md').is_file())

    def test_detach_with_the_bound_agent_releases_only_that_directory(self):
        self.installed()
        self.run_cli('detach', 'lab-agents', '--agent', 'claude-lab')
        rows = {row['item']: row['status'] for row in self.run_cli('status')['items']}
        self.assertEqual(rows['lab-agents:directory'], 'detached')
        self.assertNotEqual(rows['plain:directory'], 'detached')
        self.assertTrue((self.home / '.claude-lab/agents/note.md').is_file())

    def test_detach_with_another_agent_does_not_touch_a_bound_directory(self):
        self.installed()
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            main(['--config', str(self.config), 'detach', 'lab-agents', '--agent', 'claude'])
        rows = {row['item']: row['status'] for row in self.run_cli('status')['items']}
        self.assertNotEqual(rows['lab-agents:directory'], 'detached')
        self.assertTrue((self.home / '.claude-lab/agents/note.md').is_file())

    def test_status_for_another_agent_omits_a_bound_directory_whose_source_is_gone(self):
        self.installed()
        doc = tomlkit.parse(self.catalog.read_text())
        del doc['directories']['lab-agents']
        self.catalog.write_text(tomlkit.dumps(doc))
        self.assertNotIn('lab-agents:directory', self.items('--agent', 'claude'))
        self.assertIn('lab-agents:directory', self.items('--agent', 'claude-lab'))
        self.assertIn('lab-agents:directory', self.items())

    def test_locate_finds_a_bound_directory_without_an_agent_before_the_first_apply(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('bootstrap')
        self.assertIn('root', self.run_cli('locate', 'lab-agents', '--source'))
