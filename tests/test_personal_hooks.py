"""Personal resources exercise real offline CLI, ownership and delivery boundaries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch

import tomlkit
from click.testing import CliRunner
from agent_env_man.cli import cli
from agent_env_man.manager import Manager
from agent_env_man.model import Config
from agent_env_man.storage import State
import test_skill_catalog


class PersonalHooks(unittest.TestCase):
    git = test_skill_catalog.SkillCatalog.git
    commit = test_skill_catalog.SkillCatalog.commit

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-personal-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source with spaces'
        self.source.mkdir()
        self.script = self.source / 'observer.py'
        self.script.write_text('raise AssertionError("AEM must never execute this script")\n', encoding='utf-8')
        self.catalog = self.root / 'catalog.toml'
        self.machine = self.root / 'machine.toml'
        self.codex = self.root / 'codex'
        self.claude = self.root / 'claude'
        self.doc = {'version': 2, 'sources': {'scripts': {'type': 'external'}}, 'hooks': {'observer': {
            'source': 'scripts', 'agents': {agent: {'event': 'SessionEnd', 'runtime': 'python',
                'script': 'observer.py', 'args': ['a b', "quote'", '한국어', '$(touch never)'], 'timeout': 3}
                for agent in ('codex', 'claude')}}}}
        self.machine.write_text(tomlkit.dumps({'version': 1, 'agents': {
            'codex': {'root': str(self.codex), 'skills': str(self.root / 'codex-skills')},
            'claude': {'root': str(self.claude), 'skills': str(self.root / 'claude-skills')}}}), encoding='utf-8')
        env = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        env.start()
        self.addCleanup(env.stop)
        self.save()

    def save(self):
        self.catalog.write_text(tomlkit.dumps(self.doc), encoding='utf-8')

    def call(self, *args, code=0):
        result = CliRunner().invoke(cli, ['--json', '--config', str(self.machine), *map(str, args)])
        self.assertEqual(result.exit_code, code, result.output + repr(result.exception))
        return json.loads(result.output) if code == 0 else result.output

    def bootstrap(self):
        return self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                         '--runtime', f'python={sys.executable}')

    def apply(self, *args, code=0):
        return self.call('apply', '--item', 'observer', *args, code=code)

    def target(self, agent='codex'):
        return (self.codex / 'hooks.json') if agent == 'codex' else (self.claude / 'settings.json')

    def document(self, agent='codex'):
        return json.loads(self.target(agent).read_text(encoding='utf-8'))

    def write(self, doc, agent='codex'):
        target = self.target(agent)
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(doc), encoding='utf-8')

    def manager(self):
        config = Config(self.machine)
        return Manager(config, State(config.state_dir))

    def test_bootstrap_preview_and_plain_apply_never_register(self):
        self.bootstrap()
        self.apply('--dry-run')
        self.call('apply')
        self.call('sync')
        self.assertFalse(self.target().exists())
        self.assertFalse(self.target('claude').exists())
        result = self.apply()
        self.assertEqual(len(result), 2)
        for agent in ('codex', 'claude'):
            self.assertEqual(len(self.document(agent)['hooks']['SessionEnd']), 1)
        self.assertFalse((self.root / 'never').exists())

    def test_preserves_groups_preferences_and_exact_numbers_idempotently(self):
        self.bootstrap()
        initial = {'hooks': {'SessionEnd': [{'hooks': [{'type': 'command', 'command': 'echo user'}]}],
                             'Stop': [{'hooks': [{'type': 'command', 'command': 'echo plugin'}]}]},
                   'awaySummaryEnabled': False}
        for agent in ('codex', 'claude'):
            self.write(initial, agent)
            p = self.target(agent)
            p.write_text(p.read_text()[:-1] + ', "precision": 1.234567890123456789}\n')
        self.apply()
        for agent in ('codex', 'claude'):
            after = self.document(agent)
            self.assertEqual(after['hooks']['Stop'], initial['hooks']['Stop'])
            self.assertEqual(after['hooks']['SessionEnd'][:-1], initial['hooks']['SessionEnd'])
            self.assertFalse(after['awaySummaryEnabled'])
            self.assertIn('1.234567890123456789', self.target(agent).read_text())
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        self.apply()
        self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])
        self.call('hooks', 'remove', 'observer')
        for agent in ('codex', 'claude'):
            self.assertEqual(self.document(agent)['hooks'], initial['hooks'])
            self.assertIn('1.234567890123456789', self.target(agent).read_text())

    def test_definition_update_event_move_and_status(self):
        self.bootstrap()
        self.apply()
        binding = self.doc['hooks']['observer']['agents']['codex']
        binding.update(event='SessionStart', args=['changed'])
        self.save()
        statuses = {i['item']: i['status'] for i in self.call('status')['items']}
        self.assertEqual(statuses['observer:hook'], 'stale')
        before_claude = self.target('claude').read_bytes()
        self.apply('--agent', 'codex')
        self.assertEqual(self.document()['hooks']['SessionEnd'], [])
        self.assertEqual(len(self.document()['hooks']['SessionStart']), 1)
        self.assertEqual(before_claude, self.target('claude').read_bytes())
        self.assertEqual(self.call('locate', 'observer', '--agent', 'codex')['entry'], str(self.script))

    def write_precise_foreign_groups(self, *, large='1e200'):
        foreign = ('{ "hooks": [{"type":"command", "command":"echo user", '
                   '"timeout":1.0000000000000001}], '
                   '"metadata":{"tiny":1e-400,"large":' + large + ',"spelling":4.20e+1} }')
        for agent in ('codex', 'claude'):
            target = self.target(agent)
            owned = self.document(agent)['hooks']['SessionEnd'] if target.exists() else []
            target.parent.mkdir(exist_ok=True)
            groups = ', '.join([foreign, *map(json.dumps, owned)])
            target.write_text('{"hooks":{"SessionEnd":[' + groups + '],"Stop":[' + foreign +
                              ']},"precision":1.234567890123456789}\n', encoding='utf-8')
        return foreign

    def assert_precise_foreign_groups(self, foreign):
        for agent in ('codex', 'claude'):
            text = self.target(agent).read_text(encoding='utf-8')
            self.assertEqual(text.count(foreign), 2, text)
            self.assertIn('1.234567890123456789', text)

    def test_registration_preserves_unowned_group_numeric_tokens(self):
        self.bootstrap()
        foreign = self.write_precise_foreign_groups()
        self.apply()
        self.assert_precise_foreign_groups(foreign)

    def test_event_move_preserves_unowned_group_numeric_tokens(self):
        self.bootstrap()
        self.apply()
        foreign = self.write_precise_foreign_groups()
        for binding in self.doc['hooks']['observer']['agents'].values():
            binding['event'] = 'SessionStart'
        self.save()
        self.apply()
        self.assert_precise_foreign_groups(foreign)
        for agent in ('codex', 'claude'):
            self.assertEqual(len(self.document(agent)['hooks']['SessionEnd']), 1)
            self.assertEqual(len(self.document(agent)['hooks']['SessionStart']), 1)

    def test_registration_accepts_unowned_numbers_beyond_float_range(self):
        self.bootstrap()
        foreign = self.write_precise_foreign_groups(large='1e400')
        self.apply()
        self.assert_precise_foreign_groups(foreign)

    def test_saved_removal_preserves_unowned_group_numeric_tokens(self):
        self.bootstrap()
        self.apply()
        foreign = self.write_precise_foreign_groups()
        self.catalog.unlink()
        self.call('hooks', 'remove', 'observer')
        self.assert_precise_foreign_groups(foreign)
        for agent in ('codex', 'claude'):
            self.assertEqual(len(self.document(agent)['hooks']['SessionEnd']), 1)

    def test_local_edits_duplicate_identity_and_missing_groups_are_protected(self):
        self.bootstrap()
        self.apply()
        pristine = self.document()
        changed = deepcopy(pristine)
        changed['hooks']['SessionEnd'][0]['hooks'][0]['timeout'] = 2
        self.write(changed)
        before = self.target().read_bytes()
        self.apply(code=1)
        self.call('hooks', 'remove', 'observer', code=1)
        self.assertEqual(self.target().read_bytes(), before)
        self.apply('--replace')
        self.assertEqual(self.document(), pristine)
        duplicate = deepcopy(pristine)
        duplicate['hooks']['SessionStart'] = deepcopy(duplicate['hooks']['SessionEnd'])
        self.write(duplicate)
        self.assertIn('Duplicate', self.apply('--replace', code=1))
        self.write({'hooks': {}})
        self.assertIn('disappeared', self.apply(code=1))
        self.apply('--replace')

    def test_marker_mentioned_as_argument_does_not_claim_foreign_group(self):
        self.bootstrap()
        self.apply()
        state = self.manager().state.data['items']['observer:hook']
        foreign = {'hooks': [{'type': 'command', 'command': 'echo ' + state['hook_marker']}]}
        doc = self.document()
        doc['hooks']['Stop'] = [foreign]
        self.write(doc)
        self.apply()
        self.call('hooks', 'remove', 'observer', '--agent', 'codex')
        self.assertEqual(self.document()['hooks']['Stop'], [foreign])

    def test_saved_removal_is_offline_and_detach_preserves_group(self):
        self.bootstrap()
        self.apply()
        before = self.target().read_bytes()
        self.call('hooks', 'remove', 'observer', '--agent', 'codex', '--dry-run')
        self.assertEqual(before, self.target().read_bytes())
        self.catalog.unlink()
        self.call('hooks', 'remove', 'observer', '--agent', 'codex')
        self.assertEqual(self.document()['hooks']['SessionEnd'], [])
        self.call('detach', 'observer')
        self.assertEqual(len(self.document('claude')['hooks']['SessionEnd']), 1)
        self.assertIn('Detached', self.call('hooks', 'remove', 'observer', '--agent', 'claude', code=1))

    def test_reapply_after_explicit_removal_requires_reattach(self):
        self.bootstrap()
        self.apply()
        self.call('hooks', 'remove', 'observer')
        self.apply()
        self.assertEqual(self.document()['hooks']['SessionEnd'], [])
        self.apply('--reattach')
        self.assertEqual(len(self.document()['hooks']['SessionEnd']), 1)

    def test_registration_preserves_native_streams_exit_and_literal_argv(self):
        if os.name == 'nt':
            self.skipTest('Native POSIX command execution')
        self.script.write_text('import sys,json\nprint(json.dumps(sys.argv[1:],ensure_ascii=False))\n'
                               'print(sys.stdin.read(),file=sys.stderr)\nsys.exit(7)\n', encoding='utf-8')
        self.bootstrap()
        self.apply()
        command = self.document()['hooks']['SessionEnd'][0]['hooks'][0]['command']
        result = subprocess.run(command, shell=True, input='event stdin', text=True, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(json.loads(result.stdout), self.doc['hooks']['observer']['agents']['codex']['args'])
        self.assertEqual(result.stderr, 'event stdin\n')

    def virtualenv_runtime(self):
        if os.name == 'nt':
            self.skipTest('Native POSIX virtualenv symlink execution')
        environment = self.root / 'hook venv'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
        executable = environment / 'bin/python'
        if not executable.is_symlink():
            self.skipTest('Virtualenv interpreter symlink capability unavailable')
        self.script.write_text('import json,sys\n'
                               'print(json.dumps({"prefix":sys.prefix,"executable":sys.executable}))\n',
                               encoding='utf-8')
        return executable

    def assert_virtualenv_execution(self, executable):
        self.apply('--agent', 'codex')
        command = self.document()['hooks']['SessionEnd'][0]['hooks'][0]['command']
        expected = subprocess.run([str(executable), str(self.script)], capture_output=True,
                                  text=True, check=True)
        actual = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))

    def test_bootstrap_preserves_virtualenv_runtime_path(self):
        executable = self.virtualenv_runtime()
        self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                  '--runtime', f'python={executable}')
        machine = tomlkit.parse(self.machine.read_text(encoding='utf-8'))
        self.assertEqual(machine['runtimes']['python'], str(executable))
        self.assert_virtualenv_execution(executable)

    def test_saved_virtualenv_runtime_uses_its_environment(self):
        executable = self.virtualenv_runtime()
        self.bootstrap()
        machine = tomlkit.parse(self.machine.read_text(encoding='utf-8'))
        machine['runtimes']['python'] = str(executable)
        self.machine.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.assert_virtualenv_execution(executable)

    def test_invalid_declarations_runtime_and_redirected_payload_refused(self):
        cases = [('event', 'Impossible'), ('timeout', 4), ('runtime', 'missing'), ('script', '../escape'),
                 ('matcher', '['), ('args', ['nul\0'])]
        original = deepcopy(self.doc)
        for field, value in cases:
            with self.subTest(field=field):
                self.doc = deepcopy(original)
                self.doc['hooks']['observer']['agents']['codex'][field] = value
                self.save()
                self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                          '--runtime', f'python={sys.executable}', code=1)
                self.assertFalse(self.target().exists())
        self.doc = original
        self.save()
        self.bootstrap()
        self.script.write_bytes(b'\xff')
        self.apply(code=1)
        self.assertFalse(self.target().exists())

    def test_invalid_hook_fields_preserve_registered_files_and_ownership(self):
        self.bootstrap()
        self.apply()
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        state_path = self.manager().state.path
        state_before = state_path.read_bytes()
        original = deepcopy(self.doc)
        cases = [('timeout', True), ('timeout', 0), ('timeout', 2**32),
                 ('args', 'literal'), ('args', [1]), ('matcher', 1),
                 ('matcher', 'nul\0'), ('script', 'observer\0.py'), ('unknown', True)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.doc = deepcopy(original)
                self.doc['hooks']['observer']['agents']['codex'][field] = value
                self.save()
                self.apply(code=1)
                self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])
                self.assertEqual(state_path.read_bytes(), state_before)

    def test_runtime_binding_errors_do_not_save_machine_or_register_hooks(self):
        before = self.machine.read_bytes()
        for bindings in (('python',), ('python=relative',),
                         (f'python={sys.executable}', f'python={sys.executable}'),
                         (f'python={self.root / "missing executable"}',)):
            with self.subTest(bindings=bindings):
                args = ['bootstrap', self.catalog, '--external', f'scripts={self.source}']
                for value in bindings:
                    args += ['--runtime', value]
                self.call(*args, code=1)
                self.assertEqual(self.machine.read_bytes(), before)
                self.assertFalse(self.target().exists())
                self.assertFalse(self.target('claude').exists())

    def test_invalid_saved_runtime_types_preserve_registered_hooks(self):
        self.bootstrap()
        self.apply()
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        original = tomlkit.parse(self.machine.read_text(encoding='utf-8'))
        for value in ('python', {'python': 1}, {'python': 'relative'}):
            with self.subTest(value=value):
                document = deepcopy(original)
                document['runtimes'] = value
                self.machine.write_text(tomlkit.dumps(document), encoding='utf-8')
                self.apply(code=1)
                self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])

    def test_foreign_noncommand_and_invalid_encoded_handlers_are_preserved(self):
        self.bootstrap()
        foreign = {'hooks': [{'type': 'prompt', 'prompt': 'User-owned prompt'},
                            {'type': 'command', 'command': 'powershell.exe -NoProfile -NonInteractive -EncodedCommand invalid!'},
                            {'type': 'command', 'command': 'powershell.exe -NoProfile -NonInteractive -EncodedCommand /w=='}]}
        for agent in ('codex', 'claude'):
            self.write({'hooks': {'SessionEnd': [foreign]}}, agent)
        self.apply()
        self.call('hooks', 'remove', 'observer')
        for agent in ('codex', 'claude'):
            self.assertEqual(self.document(agent)['hooks']['SessionEnd'], [foreign])

    def test_source_script_redirect_is_refused_without_registering(self):
        self.bootstrap()
        foreign = self.root / 'foreign.py'
        foreign.write_text('Foreign user script\n', encoding='utf-8')
        self.script.unlink()
        try:
            self.script.symlink_to(foreign)
        except OSError as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')
        before = foreign.read_bytes()
        self.assertIn('redirects', self.apply(code=1))
        self.assertFalse(self.target().exists())
        self.assertFalse(self.target('claude').exists())
        self.assertEqual(foreign.read_bytes(), before)

    def test_saved_removal_rejects_invalid_ownership_without_changing_targets(self):
        self.bootstrap()
        self.apply()
        state = self.manager().state
        state.data['items']['observer:hook']['hook_event'] = None
        state.save()
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        state_before = state.path.read_bytes()
        self.catalog.unlink()
        self.assertIn('Invalid saved personal hook ownership',
                      self.call('hooks', 'remove', 'observer', code=1))
        self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])
        self.assertEqual(state.path.read_bytes(), state_before)

    def test_saved_removal_unknown_selection_preserves_registered_groups(self):
        self.bootstrap()
        self.apply()
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        self.assertIn('No saved personal hook',
                      self.call('hooks', 'remove', 'observer', 'missing', code=1))
        self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])
        self.assertFalse(self.manager().state.data['items']['observer:hook']['detached'])

    def test_same_file_multiple_groups_preflight_together(self):
        self.doc['hooks']['second'] = deepcopy(self.doc['hooks']['observer'])
        self.save()
        self.bootstrap()
        self.call('apply', '--item', 'observer', '--item', 'second')
        self.assertEqual(len(self.document()['hooks']['SessionEnd']), 2)
        doc = self.document()
        doc['hooks']['SessionEnd'][1]['hooks'][0]['timeout'] = 2
        self.write(doc)
        binding = self.doc['hooks']['observer']['agents']['codex']
        binding['args'] = ['new']
        self.save()
        before = self.target().read_bytes()
        self.call('apply', '--item', 'observer', '--item', 'second', code=1)
        self.assertEqual(before, self.target().read_bytes())

    def test_claude_preferences_and_hook_changes_share_target_transaction(self):
        (self.source / 'prefs.json').write_text('{"awaySummaryEnabled": false}\n')
        self.doc['settings'] = {'prefs': {'source': 'scripts', 'path': 'prefs.json', 'format': 'json'}}
        self.save()
        self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                  '--runtime', f'python={sys.executable}', '--setting-target', f'prefs={self.target("claude")}')
        self.call('apply', '--item', 'prefs', '--item', 'observer', '--agent', 'claude')
        doc = self.document('claude')
        self.assertFalse(doc['awaySummaryEnabled'])
        self.assertEqual(len(doc['hooks']['SessionEnd']), 1)
        self.call('hooks', 'remove', 'observer', '--agent', 'claude')
        self.assertFalse(self.document('claude')['awaySummaryEnabled'])

    def test_failed_state_commit_rolls_back_registration(self):
        self.bootstrap()
        self.write({'keep': 1, 'hooks': {}})
        before = self.target().read_bytes()
        with patch.object(State, 'save', side_effect=OSError('injected state failure')):
            self.apply('--agent', 'codex', code=1)
        self.assertEqual(before, self.target().read_bytes())

    def test_git_shared_source_update_guards_live_script_without_reregistering(self):
        self.git(self.source, 'init', '-b', 'main')
        self.commit(self.source)
        self.doc['sources']['scripts'] = {'type': 'git', 'repository': str(self.source)}
        self.save()
        self.call('bootstrap', self.catalog, '--checkout-root', self.root / 'checkouts',
                  '--runtime', f'python={sys.executable}')
        self.apply()
        before = self.target().read_bytes()
        self.script.write_text('# Changed source, not definition\n')
        self.commit(self.source)
        self.call('update', 'observer')
        self.assertEqual(before, self.target().read_bytes())
        self.script.unlink()
        self.commit(self.source)
        result = self.call('update', 'observer', code=1)
        self.assertIn('removes or redirects', str(result))
        self.assertEqual(before, self.target().read_bytes())

    def test_full_content_excludes_personal_registrations(self):
        from agent_env_man.automation import full_content
        self.bootstrap()
        manager = self.manager()
        result = full_content(manager, timeout=10)
        self.assertIn('personal-hook-requires-explicit-apply', str(result))
        self.assertFalse(self.target().exists())

    def test_target_redirect_and_post_preflight_edits_preserved(self):
        from agent_env_man.model import Error
        self.bootstrap()
        self.apply()
        manager = self.manager()
        item = next(i for i in manager.items() if i.agent == 'codex')
        plan = manager.plan(item)
        doc = self.document()
        doc['user_edit'] = True
        self.write(doc)
        with self.assertRaises(Error):
            manager.install(plan)
        self.assertTrue(self.document()['user_edit'])
        target = self.target()
        foreign = self.root / 'foreign.json'
        foreign.write_bytes(target.read_bytes())
        target.unlink()
        try:
            target.symlink_to(foreign)
        except OSError:
            self.skipTest('Symlink capability unavailable')
        before = foreign.read_bytes()
        self.apply('--replace', code=1)
        self.call('hooks', 'remove', 'observer', code=1)
        self.assertEqual(foreign.read_bytes(), before)

    def test_hook_removal_rolls_back_both_agents_on_state_commit_failure(self):
        self.bootstrap()
        self.apply()
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        original = State.save
        def fail_commit(state):
            if state.data['items'].get('observer:hook', {}).get('removed'):
                raise OSError('injected commit failure')
            return original(state)
        with patch.object(State, 'save', fail_commit):
            self.call('hooks', 'remove', 'observer', code=1)
        self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])
        self.assertFalse(self.manager().state.data['items']['observer:hook']['detached'])
        self.call('hooks', 'remove', 'observer')

    def test_crash_recovery_does_not_overwrite_later_user_edits(self):
        self.bootstrap()
        self.apply()
        original = State.save
        def crash_commit(state):
            if state.data['items'].get('observer:hook', {}).get('removed'):
                raise KeyboardInterrupt('simulated crash')
            return original(state)
        with patch.object(State, 'save', crash_commit):
            # CliRunner converts KeyboardInterrupt to an Abort (exit 1).
            self.call('hooks', 'remove', 'observer', code=1)
        self.assertIsNotNone(self.manager().state.data['pending'])
        self.write({'hooks': {}, 'later_user_edit': True})
        before = [self.target(a).read_bytes() for a in ('codex', 'claude')]
        self.call('recover', code=1)
        self.assertEqual(before, [self.target(a).read_bytes() for a in ('codex', 'claude')])

    def test_saved_removal_without_runtime_or_profile(self):
        from agent_env_man import agents
        self.bootstrap()
        self.apply()
        self.catalog.unlink()
        machine = tomlkit.parse(self.machine.read_text())
        machine['runtimes']['python'] = str(self.root / 'missing-runtime')
        self.machine.write_text(tomlkit.dumps(machine))
        with patch.dict(agents.PROFILES, {}, clear=True):
            self.call('hooks', 'remove', 'observer')
        self.assertEqual(self.document()['hooks']['SessionEnd'], [])
        self.assertEqual(self.document('claude')['hooks']['SessionEnd'], [])

    def test_shared_skill_update_preserves_orphaned_live_hook(self):
        (self.source / 'SKILL.md').write_text('---\nname: other\ndescription: fixture\n---\nOther\n')
        self.git(self.source, 'init', '-b', 'main')
        self.commit(self.source)
        self.doc['sources']['scripts'] = {'type': 'git', 'repository': str(self.source)}
        self.doc['skills'] = {'other': {'source': 'scripts', 'subdir': '.'}}
        self.save()
        self.call('bootstrap', self.catalog, '--checkout-root', self.root / 'checkouts',
                  '--runtime', f'python={sys.executable}')
        self.apply()
        self.doc.pop('hooks')
        self.save()
        self.script.unlink()
        self.commit(self.source)
        self.assertIn('removes or redirects', self.call('update', 'other', code=1))
        self.assertEqual(len(self.document()['hooks']['SessionEnd']), 1)

    def test_all_agent_scripts_validated_before_git_checkout_publication(self):
        self.doc['hooks']['observer']['agents']['claude']['script'] = 'missing.py'
        self.git(self.source, 'init', '-b', 'main')
        self.commit(self.source)
        self.doc['sources']['scripts'] = {'type': 'git', 'repository': str(self.source)}
        self.save()
        self.call('bootstrap', self.catalog, '--checkout-root', self.root / 'checkouts',
                  '--runtime', f'python={sys.executable}', code=1)
        self.assertFalse((self.root / 'checkouts/.aem-repositories/scripts').exists())
        self.assertFalse(self.target().exists())

    def test_external_update_validates_script_without_registration(self):
        self.bootstrap()
        self.script.unlink()
        self.call('update', 'observer', code=1)
        self.assertFalse(self.target().exists())

    def test_setup_instruction_personal_and_preferences_coexist(self):
        bundle = self.source / 'rules'
        bundle.mkdir()
        (bundle / 'start.md').write_text('Personal guidance\n')
        (self.source / 'prefs.json').write_text('{"awaySummaryEnabled": false}\n')
        self.doc['instructions'] = {'guidance': {'source': 'scripts', 'subdir': 'rules', 'entry': 'start.md'}}
        self.doc['settings'] = {'prefs': {'source': 'scripts', 'path': 'prefs.json', 'format': 'json'}}
        self.save()
        self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                  '--runtime', f'python={sys.executable}', '--setting-target', f'prefs={self.target("claude")}')
        executable = self.root / 'aem'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        self.call('setup', '--agent', 'claude', '--executable', executable)
        before = deepcopy(self.document('claude')['hooks']['SessionStart'])
        self.call('apply', '--item', 'guidance:entry@claude', '--item', 'prefs', '--item', 'observer:hook@claude')
        doc = self.document('claude')
        self.assertEqual(doc['hooks']['SessionStart'][:len(before)], before)
        self.assertEqual(len(doc['hooks']['SessionStart']), len(before) + 1)
        self.assertFalse(doc['awaySummaryEnabled'])
        self.call('hooks', 'remove', 'observer', '--agent', 'claude')
        self.assertEqual(self.document('claude')['hooks']['SessionStart'], doc['hooks']['SessionStart'])

    def test_windows_command_encoding_preserves_literal_arguments(self):
        import base64
        from agent_env_man.personal_hooks import direct_command
        argv = [r'C:\Program Files\python.exe', r'C:\한글\script.py', "quote'", '$env:HOME', 'a b']
        with patch('agent_env_man.personal_hooks.os.name', 'nt'):
            command = direct_command('AEM test marker', argv)
        encoded = command.split()[-1]
        decoded = base64.b64decode(encoded).decode('utf-16le')
        self.assertIn("'quote'''", decoded)
        self.assertIn("'$env:HOME'", decoded)
        self.assertIn("'C:\\한글\\script.py'", decoded)
        self.assertTrue(decoded.endswith('; exit $LASTEXITCODE'))

    def test_publication_reports_shared_consumers_and_never_registers(self):
        (self.source / 'SKILL.md').write_text('---\nname: other\ndescription: fixture\n---\nOther\n')
        self.git(self.source, 'init', '-b', 'main')
        self.git(self.source, 'config', 'receive.denyCurrentBranch', 'updateInstead')
        self.commit(self.source)
        self.doc['sources']['scripts'] = {'type': 'git', 'repository': str(self.source)}
        self.doc['skills'] = {'other': {'source': 'scripts', 'subdir': '.'}}
        self.save()
        self.call('bootstrap', self.catalog, '--checkout-root', self.root / 'checkouts',
                  '--runtime', f'python={sys.executable}')
        checkout = self.root / 'checkouts/.aem-repositories/scripts'
        (checkout / 'observer.py').write_text('# Published script\n')
        state = (self.root / 'machine.toml.state/state.json').read_bytes()
        with patch('agent_env_man.git_source.Git.fetch', side_effect=AssertionError('preview fetched')):
            report = self.call('publish', 'observer', '--dry-run')
        self.assertEqual(report[0]['members'], ['observer', 'other'])
        self.assertEqual(state, (self.root / 'machine.toml.state/state.json').read_bytes())
        self.git(checkout, 'config', 'user.name', 'Fixture')
        self.git(checkout, 'config', 'user.email', 'fixture@example.invalid')
        self.call('publish', 'observer', '-m', 'Publish fixture')
        self.assertEqual(self.script.read_text(), '# Published script\n')
        self.assertFalse(self.target().exists())

    def test_multiple_groups_write_one_target_image(self):
        self.doc['hooks']['second'] = deepcopy(self.doc['hooks']['observer'])
        self.save()
        self.bootstrap()
        original = os.replace
        writes = []
        def observe(source, destination):
            if Path(destination) == self.target():
                writes.append((source, destination))
            return original(source, destination)
        with patch('os.replace', observe):
            self.call('apply', '--item', 'observer', '--item', 'second', '--agent', 'codex')
        self.assertEqual(len(writes), 1)
        self.assertEqual(len(self.document()['hooks']['SessionEnd']), 2)

    def test_native_field_limits_and_match_all_are_validated(self):
        self.doc['hooks']['observer']['agents']['codex'].update(matcher='*')
        self.save()
        self.bootstrap()
        self.apply()
        self.assertEqual(self.document()['hooks']['SessionEnd'][0]['matcher'], '*')
        self.doc['hooks']['observer']['agents']['codex'].update(event='Interrupt')
        self.save()
        self.assertIn('matchers are not supported', self.apply(code=1))
        self.doc['hooks']['observer']['agents']['codex'].pop('matcher')
        self.doc['hooks']['observer']['agents']['claude']['timeout'] = 61
        self.save()
        self.assertIn('60 seconds', self.apply(code=1))

    def test_target_lookup_is_only_for_settings(self):
        self.bootstrap()
        self.apply()
        self.call('locate', 'observer', '--target', code=1)

    def test_shared_preference_owner_removal_survives_missing_profiles(self):
        from agent_env_man import agents
        (self.source / 'prefs.json').write_text('{"awaySummaryEnabled": false}\n')
        self.doc['settings'] = {'prefs': {'source': 'scripts', 'path': 'prefs.json', 'format': 'json'}}
        self.save()
        self.call('bootstrap', self.catalog, '--external', f'scripts={self.source}',
                  '--runtime', f'python={sys.executable}', '--setting-target', f'prefs={self.target("claude")}')
        self.call('apply', '--item', 'prefs', '--item', 'observer')
        self.catalog.unlink()
        with patch.dict(agents.PROFILES, {}, clear=True):
            self.call('hooks', 'remove', 'observer')
        self.assertFalse(self.document('claude')['awaySummaryEnabled'])
        self.assertEqual(self.document('claude')['hooks']['SessionEnd'], [])
