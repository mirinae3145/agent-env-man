"""A catalog setting declared for a named profile is skipped on machines without that profile."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout

import tomlkit

from agent_env_man.model import Config
import test_named_profiles
from agent_env_man.cli import main
from test_setup import SetupFixture


class ProfileSettings(SetupFixture):
    prepare = test_named_profiles.NamedProfiles.prepare

    def declare(self, **fields):
        self.prepare()
        (self.external / 'preferences.json').write_text('{"model":"sonnet"}')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {'personal-preferences': {'source': 'personal', 'path': 'preferences.json', 'format': 'json'},
                           'lab-preferences': {'source': 'personal', 'path': 'preferences.json', 'format': 'json', **fields}}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {'personal-preferences': {'target': str(self.home / '.claude/settings.json')}}
        self.config.write_text(tomlkit.dumps(machine))

    def bind(self, target='.claude-lab/settings.json', **binding):
        machine = tomlkit.parse(self.config.read_text())
        machine['settings']['lab-preferences'] = {'target': str(self.home / target), **binding}
        self.config.write_text(tomlkit.dumps(machine))

    def refused(self, text):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), 'apply', '--dry-run'])
        self.assertEqual(code, 1, output.getvalue())
        self.assertIn(text, errors.getvalue())

    def items(self):
        return {row['item'] for row in self.run_cli('status')['items']}

    def test_machine_without_the_profile_skips_the_declaration(self):
        self.declare(agent='claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply', '--dry-run')
        self.assertNotIn('lab-preferences:settings', self.items())
        self.assertFalse((self.home / '.claude-lab').exists())

    def test_machine_with_the_profile_must_bind_it_with_the_same_agent(self):
        self.declare(agent='claude-lab')
        self.setup_cli('--agent', 'claude-lab')
        self.refused('missing machine settings.lab-preferences.target')
        self.bind()
        self.refused('machine binding must name agent claude-lab')
        self.bind('.claude/lab.json', agent='claude')
        self.refused('machine binding must name agent claude-lab')
        self.bind(agent='claude-lab')
        self.run_cli('bootstrap')
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertEqual(json.loads((self.home / '.claude-lab/settings.json').read_text())['model'], 'sonnet')
        self.assertIn('lab-preferences:settings', self.items())

    def test_a_binding_for_an_unregistered_profile_is_refused(self):
        self.declare(agent='claude-lab')
        self.bind(agent='claude-lab')
        self.refused('its agent claude-lab is not registered on this machine; register it with '
                     'aem setup --agent claude-lab or remove machine settings.lab-preferences')

    def test_a_legacy_machine_counts_its_implicit_codex_agent(self):
        self.configure()
        (self.external / 'preferences.json').write_text('{"model":"sonnet"}')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings'] = {'codex-preferences': {'source': 'personal', 'path': 'preferences.json',
                                                 'format': 'json', 'agent': 'codex'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        self.assertNotIn('agents', machine)
        machine['settings'] = {'codex-preferences': {'target': str(self.agent / 'preferences.json'), 'agent': 'codex'}}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('bootstrap')
        self.run_cli('apply', '--dry-run')
        self.assertIn('codex-preferences:settings', self.items())

    def test_a_setting_without_agent_still_requires_every_machine_to_bind_it(self):
        self.declare()
        self.refused('missing machine settings.lab-preferences.target')

    def test_an_unknown_agent_name_is_refused(self):
        self.declare(agent='nobody')
        self.refused('Unsupported agent: nobody')

    def test_a_non_string_agent_is_refused(self):
        self.declare(agent=5)
        self.refused('agent must be a destination name')
