"""Machine integration runs entirely in temporary homes with local repositories."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import tomlkit

from agent_env_man import agents
from agent_env_man.model import Config
from agent_env_man.storage import State
from agent_env_man.setup import shell_block, shell_path
from test_instructions import InstructionFixture


class SetupFixture(InstructionFixture):
    def setUp(self):
        super().setUp()
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        self.executable = self.home / 'bin' / ('aem.exe' if os.name == 'nt' else 'aem')
        self.executable.parent.mkdir()
        self.executable.write_text('#!/bin/sh\nexit 0\n')
        self.executable.chmod(0o755)
        self.home_patch = patch('pathlib.Path.home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.env_patch = patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex'), 'ZDOTDIR': str(self.home)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def setup_cli(self, *args, **kwargs):
        return self.run_cli('setup', '--executable', self.executable, *args, **kwargs)

    def state(self):
        return State(Config(self.config).state_dir).data


class MachineSetup(SetupFixture):
    def test_startup_timeout_updates_saved_agents_and_preserves_instruction_hooks(self):
        self.configure()
        self.setup_cli('--agent', 'codex', '--agent', 'claude')
        self.run_cli('apply', '--item', 'personal:entry')
        instruction = json.loads((self.agent / 'hooks.json').read_text())['hooks']['SessionStart'][-1]
        self.run_cli('setup', '--startup-hook-timeout', '65.5', '--dry-run')
        self.assertEqual(Config(self.config).startup_hook_timeout, 10)
        self.run_cli('setup', '--startup-hook-timeout', '65.5')
        self.assertEqual(Config(self.config).startup_hook_timeout, 65.5)
        for name in ('codex', 'claude'):
            record = self.state()['items']['setup:agent-' + name]
            hook = json.loads(Path(record['target']).read_text())['hooks']['SessionStart'][0]
            self.assertEqual(hook['hooks'][0]['timeout'], 66 if name == 'codex' else 65.5)
            if name == 'codex':
                self.assertIs(type(hook['hooks'][0]['timeout']), int)
        self.assertEqual(json.loads((self.agent / 'hooks.json').read_text())['hooks']['SessionStart'][-1], instruction)
        self.setup_cli()
        self.assertEqual(Config(self.config).startup_hook_timeout, 65.5)
        self.run_cli('apply', '--item', 'personal:entry')

    def test_startup_timeout_can_be_saved_before_registering_agents(self):
        self.run_cli('setup', '--startup-hook-timeout', '45')
        self.assertEqual(Config(self.config).startup_hook_timeout, 45)
        self.assertFalse((self.home / '.codex').exists())
        self.setup_cli('--agent', 'codex')
        record = self.state()['items']['setup:agent-codex']
        self.assertEqual(record['hook_group']['hooks'][0]['timeout'], 45)
        self.assertIs(type(record['hook_group']['hooks'][0]['timeout']), int)

    def test_git_policy_aliases_preserve_saved_keys(self):
        for flag in ('--automation-git-timeout', '--automation-timeout'):
            self.run_cli('setup', flag, '12.5')
            self.assertEqual(Config(self.config).automation['timeout'], 12.5)
        for flag in ('--catalog-git-timeout', '--catalog-timeout'):
            self.run_cli('setup', flag, '3.5')
            self.assertEqual(Config(self.config).catalog_update['timeout'], 3.5)

    def test_startup_timeout_refuses_local_hook_edits_without_saving_value(self):
        self.setup_cli('--agent', 'codex')
        path = self.home / '.codex/hooks.json'
        doc = json.loads(path.read_text())
        doc['hooks']['SessionStart'][0]['hooks'][0]['timeout'] = 99
        path.write_text(json.dumps(doc))
        before = path.read_bytes()
        self.run_cli('setup', '--startup-hook-timeout', '60', code=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(Config(self.config).startup_hook_timeout, 10)

    def test_invalid_saved_startup_timeout_is_rejected(self):
        for value in (0, -1, True, '30', float('inf'), float('nan')):
            with self.subTest(value=value):
                from agent_env_man.model import Error
                with self.assertRaises(Error):
                    Config(self.config, document={'version': 1, 'setup': {'startup_hook_timeout': value}})

    def test_invalid_agent_bindings_fail_before_profile_or_machine_writes(self):
        invalid = [[], {'unknown': {}}, {'claude': 'not-a-table'},
                   {'claude': {'root': 'relative'}}, {'claude': {'skills': 42}},
                   {'claude': {'unexpected': True}}]
        for bindings in invalid:
            with self.subTest(bindings=bindings):
                self.config.write_text(tomlkit.dumps({'version': 1, 'agents': bindings}))
                before = self.config.read_bytes()
                self.setup_cli('--shell', 'bash', code=1)
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse((self.home / '.bashrc').exists())
                self.assertFalse((self.home / '.claude').exists())
                self.assertFalse((self.home / '.codex').exists())

    def test_initial_preview_is_completely_read_only(self):
        self.setup_cli('--shell', 'bash', '--agent', 'codex', '--dry-run')
        self.assertFalse(self.config.exists())
        self.assertFalse(Path(str(self.config) + '.state').exists())
        self.assertFalse((self.home / '.bashrc').exists())
        self.assertFalse((self.home / '.codex').exists())

    def test_repeat_add_remove_preserves_user_content_and_no_catalog(self):
        bash = self.home / '.bashrc'
        bash.write_bytes(b'# user settings\r\nexport EXAMPLE=yes\r\n')
        bash.chmod(0o640)
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        before = bash.read_bytes()
        self.assertNotIn(b'\n', before.replace(b'\r\n', b''))
        if os.name != "nt":
            self.assertEqual(bash.stat().st_mode & 0o777, 0o640)
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        self.assertEqual(before, bash.read_bytes())
        self.setup_cli('--shell', 'zsh')
        self.assertEqual(before, bash.read_bytes())
        self.assertTrue((self.home / '.zshrc').exists())
        self.assertIsNone(Config(self.config).catalog_path)
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertFalse(self.state()['startup']['failed'])
        bash.write_bytes(before + b'# added by user\r\n')
        self.setup_cli('--remove-shell', 'bash', '--remove-agent', 'codex')
        self.assertEqual(bash.read_bytes(), b'# user settings\r\nexport EXAMPLE=yes\r\n# added by user\r\n')
        self.assertTrue((self.home / '.zshrc').exists())
        self.setup_cli('--remove-shell', 'bash')
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        self.assertEqual(bash.read_bytes().count(b'# >>> AEM'), 1)

    def test_local_edit_and_redirect_are_rejected_before_any_write(self):
        self.require_links()
        self.setup_cli('--shell', 'bash')
        bash = self.home / '.bashrc'
        bash.write_text(bash.read_text().replace('shell-start', 'interval'))
        original = bash.read_bytes()
        self.setup_cli('--shell', 'zsh', code=1)
        self.assertEqual(original, bash.read_bytes())
        self.assertFalse((self.home / '.zshrc').exists())
        self.setup_cli('--remove-shell', 'bash', code=1)
        other = self.home / 'other'
        other.write_text('keep')
        (self.home / '.zshrc').symlink_to(other)
        self.setup_cli('--shell', 'zsh', code=1)
        self.assertEqual(other.read_text(), 'keep')

    def test_duplicate_block_is_not_adopted_or_removed(self):
        self.setup_cli('--shell', 'bash')
        path = self.home / '.bashrc'
        original = path.read_bytes() * 2
        path.write_bytes(original)
        self.setup_cli(code=1)
        self.setup_cli('--remove-shell', 'bash', code=1)
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_json_prevents_shell_registration(self):
        path = self.home / '.codex/hooks.json'
        path.parent.mkdir()
        path.write_text('{"hooks":{},"hooks":{}}')
        self.setup_cli('--shell', 'bash', '--agent', 'codex', code=1)
        self.assertFalse((self.home / '.bashrc').exists())
        self.assertFalse(self.config.exists())

    def test_failure_then_retry_and_instruction_hook_coexist(self):
        self.configure()
        original = os.replace
        def fail_machine(src, dst):
            if Path(dst) == self.config and Path(src).name.startswith('.aem-stage-'):
                raise OSError('injected configuration commit failure')
            return original(src, dst)
        with patch('agent_env_man.manager.os.replace', side_effect=fail_machine):
            self.setup_cli('--shell', 'bash', '--agent', 'codex', code=1)
        self.assertIsNone(self.state()['pending'])
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        self.run_cli('apply')
        hook_file = self.agent / 'hooks.json'
        groups = json.loads(hook_file.read_text())['hooks']['SessionStart']
        self.assertEqual(len(groups), 2)
        self.setup_cli()
        self.run_cli('apply')
        self.assertEqual(json.loads(hook_file.read_text())['hooks']['SessionStart'], groups)
        self.setup_cli('--remove-agent', 'codex', code=1)
        self.run_cli('detach', 'report', 'personal:bundle', 'personal:entry')
        self.setup_cli('--remove-agent', 'codex')
        remaining = json.loads(hook_file.read_text())['hooks']['SessionStart']
        self.assertEqual(len(remaining), 1)
        self.assertIn('instruction roots', remaining[0]['hooks'][0]['statusMessage'])

    def test_startup_fetches_local_remote_and_filters_then_throttles(self):
        self.require_links()
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'action': 'sync', 'min_interval': 3600}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        helper = self.repo / 'skills/report/helper.py'
        helper.write_text('updated locally\n')
        self.commit(self.repo)
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertEqual(self.state()['startup']['outcomes'][0]['status'], 'not-triggered')
        result = self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex')
        context = result['systemMessage']
        self.assertNotIn('hookSpecificOutput', result)
        self.assertIn('report:', context)
        self.assertIn(' -> ', context)
        self.assertEqual((self.home / '.agents/skills/report/helper.py').read_text(), 'updated locally\n')
        self.assertEqual(self.state()['startup']['outcomes'][0]['status'], 'synced')
        self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex'), {})
        self.assertEqual(self.state()['startup']['outcomes'][0]['status'], 'throttled')
        self.catalog.write_text('broken TOML [')
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertTrue(self.state()['startup']['failed'])
        self.assertIn('error', self.state()['startup'])

    def test_bash_execution_quotes_paths_and_skips_noninteractive_shell(self):
        if os.name == 'nt':
            self.skipTest('Bash execution test')
        calls = self.home / 'calls'
        self.executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> ' + shlex.quote(str(calls)) + '\nexit 1\n')
        self.setup_cli('--shell', 'bash')
        rc = self.home / '.bashrc'
        subprocess.run(['bash', '-c', 'source "$1"', '_', str(rc)], check=True)
        self.assertFalse(calls.exists())
        result = subprocess.run(['bash', '--noprofile', '--rcfile', str(rc), '-i', '-c', 'printf READY'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'READY', result.stdout)
        self.assertEqual(calls.read_text().splitlines(), ['--config', str(self.config), 'startup', '--trigger', 'shell-start'])

    def test_setup_preserves_explicit_destinations_and_detach_tombstones(self):
        self.configure()
        self.run_cli('apply')
        self.run_cli('detach', 'report')
        self.setup_cli('--agent', 'codex')
        self.run_cli('apply')
        self.assertFalse((self.destination / 'report').is_symlink())
        self.assertTrue((self.agent / 'AGENTS.md').is_symlink())
        self.assertTrue(self.state()['items']['report']['detached'])
        self.assertNotIn('personal:entry@codex', self.state()['items'])

    def test_startup_briefing_only_reports_actual_changes(self):
        self.require_links()
        self.setup_cli('--agent', 'codex')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['agent-start'], 'min_interval': 0}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        first = self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex')
        self.assertIn('report: installed/refreshed', first['systemMessage'])
        self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex'), {})
        self.assertEqual(self.state()['startup']['outcomes'][0]['status'], 'synced')
        doc['updates']['defaults']['action'] = 'check'
        self.catalog.write_text(tomlkit.dumps(doc))
        (self.repo / 'skills/report/helper.py').write_text('pending update')
        self.commit(self.repo)
        self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex'), {})
        self.assertEqual(self.state()['startup']['outcomes'][0]['remote_relation'], 'behind')
        self.catalog.write_text('broken TOML [')
        self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex'), {})

    def test_source_selected_context_briefing_and_silent_empty_result(self):
        adapter = agents.profile('codex')
        with patch.object(agents, 'STARTUP_BRIEFING_OUTPUT', 'additionalContext'):
            self.assertEqual(adapter.startup_result('AEM skill updates: report'), {
                'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                       'additionalContext': 'AEM skill updates: report'}})
            self.assertEqual(adapter.startup_result(), {})
        with patch.object(agents, 'STARTUP_BRIEFING_OUTPUT', 'systemMessage'):
            self.assertEqual(adapter.startup_result('AEM skill updates: report'),
                             {'systemMessage': 'AEM skill updates: report'})
            self.assertEqual(adapter.startup_result(), {})

    def test_shared_checkout_briefing_keeps_initial_revision_for_each_skill(self):
        self.require_links()
        self.setup_cli('--agent', 'codex')
        self.catalog.write_text(tomlkit.dumps({'version': 2, 'sources': {'shared': {'type': 'git', 'repository': str(self.repo)}}, 'skills': {name: {'subdir': 'skills/report', 'source': 'shared'} for name in ('first', 'second')}, 'updates': {'defaults': {'trigger': ['agent-start'], 'min_interval': 0}}}))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        (self.repo / 'skills/report/helper.py').write_text('new shared revision')
        self.commit(self.repo)
        result = self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex')
        context = result['systemMessage']
        self.assertNotIn('hookSpecificOutput', result)
        self.assertIn('first:', context)
        self.assertIn('second:', context)
        first, second = self.state()['startup']['outcomes']
        self.assertEqual(first['previous_revision'], second['previous_revision'])
        self.assertNotEqual(first['previous_revision'], first['revision'])
        self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex'), {})

    def test_powershell_discovery_and_literal_rendering(self):
        path = self.home / 'PowerShell/Microsoft.PowerShell_profile.ps1'
        with patch('agent_env_man.setup.shutil.which', return_value='pwsh'), patch('agent_env_man.setup.subprocess.run') as run:
            run.return_value.stdout = str(path)
            self.assertEqual(shell_path('powershell'), path)
            self.assertIn('$PROFILE.CurrentUserAllHosts', run.call_args.args[0][-1])
            if os.name == 'nt':
                self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
        _, _, text = shell_block('powershell', self.home / "a'$name.toml", self.executable, self.executable.parent)
        self.assertIn("a''$name.toml'", text)
        self.assertIn('$aemPreviousExitCode', text)


class AgentInjection(SetupFixture):
    def setUp(self):
        super().setUp()
        class Fake(agents.Codex):
            def defaults(adapter):
                return {'root': str(self.home / 'fake'), 'skills': str(self.home / 'fake/skills')}
            def context(adapter, text):
                return {'fake_context': text}
        self.fake = Fake(name='fake', entry_name='RULES.md', hook_name='events.json', notice='Fake test profile')
        registry = patch.dict(agents.PROFILES, {'fake': self.fake})
        registry.start()
        self.addCleanup(registry.stop)

    def test_multiple_agents_delivery_selection_detach_and_offline_context(self):
        self.configure()
        doc = tomlkit.parse(self.catalog.read_text())
        del doc['instructions']['personal']['install']['entry']['root']
        del doc['instructions']['personal']['install']['entry']['destination']
        self.catalog.write_text(tomlkit.dumps(doc))
        self.setup_cli('--agent', 'codex', '--agent', 'fake')
        self.run_cli('apply')
        self.assertTrue((self.agent / 'AGENTS.md').is_symlink())
        self.assertTrue((self.home / 'fake/RULES.md').is_symlink())
        self.assertTrue((self.home / 'fake/skills/report').is_symlink())
        self.assertTrue((self.destination / 'report').is_symlink())
        records = self.state()['items']
        self.assertIn('report', records)
        self.assertIn('report@fake', records)
        result = self.run_cli('agent-hook', 'personal', '--agent', 'fake')
        self.assertIn('fake_context', result)
        self.run_cli('detach', 'report', '--agent', 'fake')
        self.assertFalse((self.home / 'fake/skills/report').is_symlink())
        self.assertTrue((self.destination / 'report').is_symlink())
        self.run_cli('apply', '--item', 'report')
        self.assertFalse((self.home / 'fake/skills/report').is_symlink())
        self.catalog.unlink()
        self.run_cli('detach', 'personal:bundle@fake', 'personal:entry@fake')
        self.assertIn('fake_context', self.run_cli('agent-hook', 'personal', '--agent', 'fake'))

    def test_agent_only_injection_and_qualified_instruction_selection(self):
        self.configure()
        self.setup_cli('--agent', 'fake')
        self.run_cli('apply', '--item', 'personal:entry', '--agent', 'fake')
        self.assertTrue((self.agent / 'AGENTS.md').is_symlink())
        # Explicit entry destination is respected, but product behavior comes
        # from the selected profile rather than an implicit Codex adapter.
        self.assertTrue((self.agent / 'events.json').exists())
        self.assertFalse((self.agent / 'hooks.json').exists())
        self.assertFalse((self.destination / 'report').exists())
        self.assertIn('fake_context', self.run_cli('agent-hook', 'personal', '--agent', 'fake'))
        self.run_cli('detach', 'personal:entry', '--agent', 'fake')
        self.assertFalse((self.agent / 'AGENTS.md').is_symlink())

    def test_partial_detach_does_not_disable_other_agents_updates(self):
        self.require_links()
        self.setup_cli('--agent', 'codex', '--agent', 'fake')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['shell-start'], 'min_interval': 0}}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        self.run_cli('detach', 'report', '--agent', 'codex')
        old = (self.home / '.agents/skills/report/helper.py').read_text()
        (self.repo / 'skills/report/helper.py').write_text('new revision')
        self.commit(self.repo)
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertEqual((self.home / 'fake/skills/report/helper.py').read_text(), 'new revision')
        self.assertEqual((self.home / '.agents/skills/report/helper.py').read_text(), old)

    def test_shared_skill_target_has_one_owner(self):
        self.require_links()
        self.setup_cli('--agent', 'codex', '--agent', 'fake')
        doc = tomlkit.parse(self.config.read_text())
        doc['agents']['fake']['skills'] = doc['agents']['codex']['skills']
        self.config.write_text(tomlkit.dumps(doc))
        self.run_cli('bootstrap', self.catalog)
        self.run_cli('apply')
        records = self.state()['items']
        self.assertIn('report', records)
        self.assertNotIn('report@fake', records)
        self.assertEqual(records['report']['agents'], ['codex', 'fake'])
        self.run_cli('detach', 'report', '--agent', 'fake', code=1)
        self.run_cli('detach', 'report')


class Installer(SetupFixture):
    def test_fake_uv_install_and_preview_do_not_use_network(self):
        spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'scripts/setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=str(self.executable.parent) + '\n')
        with (patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n),
              patch.object(module.subprocess, 'run', side_effect=run),
              patch.object(module.sys.stdin, 'isatty', return_value=False),
              patch('builtins.input', side_effect=AssertionError('Unattended installation must not prompt')),
              redirect_stdout(io.StringIO())):
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config), '--dry-run']), 0)
            self.assertFalse(any('install' in call for call in calls))
            calls.clear()
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config),
                                          '--startup-hook-timeout', '60', '--automation-git-timeout', '15']), 0)
        self.assertIn('--startup-hook-timeout', calls[-1])
        self.assertEqual(calls[-1][calls[-1].index('--startup-hook-timeout') + 1], '60.0')
        self.assertIn('--automation-git-timeout', calls[-1])
        self.assertIn('install', calls[2])
        self.assertIn('--reinstall', calls[2])
        self.assertEqual(calls[-1][0], str(self.executable))
