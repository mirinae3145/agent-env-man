"""A profile copy is independent of its source and compares clean except for intended changes."""
import io
import json
import os
import shutil
import stat
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agent_env_man.cli import main
from agent_env_man.profile_compare import compare as compare_profiles
from test_profile_compare import Roots, encoded_aem_command


class Copy(Roots):
    def setUp(self):
        super().setUp()
        (self.left / 'hooks').mkdir()
        script = self.left / 'hooks' / 'herdr.sh'
        script.write_text(f'#!/bin/bash\nexec {self.left}/hooks/real.sh\n')
        script.chmod(0o755)
        self.target = self.tmp / 'copy'

    def copy(self, *args, source=None, target=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), '--json', 'copy-profile',
                         str(source or self.left), str(target or self.target), *args])
        return code, output.getvalue(), errors.getvalue()

    def report(self, *args, **kwargs):
        code, output, errors = self.copy(*args, **kwargs)
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def settings(self, root):
        return json.loads((root / 'settings.json').read_text())


class Write(Copy):
    def test_copy_with_one_change_compares_clean_except_that_change(self):
        report = self.report('--set', 'model=opus', '--write')
        check = report['verification']
        self.assertEqual((check['expected'], check['unexpected']), (1, []))
        self.assertEqual(self.settings(self.target)['model'], 'opus')
        self.assertEqual(self.settings(self.left)['model'], 'sonnet')

    def test_paths_are_rebased_and_aem_hook_groups_are_left_out(self):
        self.report('--write')
        text = (self.target / 'settings.json').read_text()
        self.assertNotIn(str(self.left), text)
        self.assertNotIn('--aem-hook-id', text)
        commands = [h['command'] for g in self.settings(self.target)['hooks']['SessionStart'] for h in g['hooks']]
        self.assertEqual(commands, [f'bash {self.target}/hooks/herdr.sh session'])
        script = self.target / 'hooks' / 'herdr.sh'
        self.assertEqual(script.read_text(), f'#!/bin/bash\nexec {self.target}/hooks/real.sh\n')
        self.assertTrue(stat.S_IMODE(script.stat().st_mode) & 0o111)

    def test_personal_hook_markers_are_also_left_out(self):
        data = self.settings(self.left)
        data['hooks']['Stop'] = [{'hooks': [{'type': 'command',
                                             'command': ": 'AEM personal hook [0123456789abcdef0123]'; exec /usr/bin/true"}]}]
        (self.left / 'settings.json').write_text(json.dumps(data))
        self.report('--write')
        self.assertNotIn('Stop', self.settings(self.target)['hooks'])

    def test_copy_survives_removing_the_source_profile(self):
        self.report('--write')
        shutil.rmtree(self.left)
        for path in self.target.rglob('*'):
            if path.is_symlink():
                self.assertTrue(path.exists(), f'{path} -> {os.readlink(path)}')
                self.assertNotIn(str(self.left), os.readlink(path))
            elif path.is_file():
                self.assertNotIn(str(self.left), path.read_text())

    def test_credentials_sessions_and_plugin_data_are_not_copied(self):
        (self.left / '.credentials.json').write_text('secret')
        (self.left / 'projects').mkdir()
        (self.left / 'history.jsonl').write_text('{}')
        (self.left / 'plugins' / 'data').mkdir()
        self.report('--write')
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ['CLAUDE.md', 'hooks', 'output-styles', 'settings.json', 'skills'])

    def test_relative_links_are_resolved_before_copying(self):
        (self.left / 'skills' / 'rel').symlink_to(os.path.relpath(self.source / 'skill-a', self.left / 'skills'))
        self.report('--write')
        self.assertEqual(os.readlink(self.target / 'skills' / 'rel'), str(self.source / 'skill-a'))

    def test_real_skill_directories_are_reported_not_copied(self):
        (self.left / 'skills' / 'local').mkdir()
        report = self.report('--write')
        self.assertIn({'item': 'skills/local', 'reason': 'not a link'}, report['skipped'])
        self.assertFalse((self.target / 'skills' / 'local').exists())

    def test_plugins_become_product_cli_steps_that_are_never_run(self):
        plugins = self.left / 'plugins'
        (plugins / 'known_marketplaces.json').write_text(json.dumps({
            'market': {'source': {'source': 'github', 'repo': 'owner/repo'}},
            'other': {'source': {'source': 'directory', 'path': str(plugins / 'local')}}}))
        (plugins / 'installed_plugins.json').write_text(json.dumps({'version': 2, 'plugins': {
            'tool@market': [{'scope': 'user', 'version': '1.0.0'}],
            'dir@other': [{'scope': 'user', 'version': '0.1'}],
            'proj@market': [{'scope': 'project', 'version': '2'}],
            'lost@ghost': [{'scope': 'user', 'version': '3'}]}}))
        with mock.patch('subprocess.Popen', side_effect=AssertionError('plugins are installed by the product CLI')):
            report = self.report('--write')
        env = {'CLAUDE_CONFIG_DIR': str(self.target)}
        self.assertEqual(report['plugin_steps'], [
            {'env': env, 'args': ['claude', 'plugin', 'marketplace', 'add', 'owner/repo']},
            {'env': env, 'args': ['claude', 'plugin', 'marketplace', 'add', str(self.target / 'plugins' / 'local')]},
            {'env': env, 'args': ['claude', 'plugin', 'install', 'tool@market', '--scope', 'user']},
            {'env': env, 'args': ['claude', 'plugin', 'install', 'dir@other', '--scope', 'user']}])
        skipped = {item['item'] for item in report['skipped']}
        self.assertIn('plugins/lost@ghost', skipped)
        self.assertNotIn('plugins/proj@market', skipped)
        self.assertFalse((self.target / 'plugins').exists())

    def test_failure_leaves_no_target_or_staging_folder(self):
        with mock.patch('os.symlink', side_effect=OSError('denied')):
            code, _, errors = self.copy('--write')
        self.assertEqual(code, 1)
        self.assertIn('denied', errors)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(('copy', '.aem-copy'))), [])

    def test_sibling_paths_numbers_and_permissions_survive_the_copy(self):
        data = self.settings(self.left)
        sibling = str(self.left) + '-lab/hooks/run.sh'
        data['env'] = {'LAB': sibling, 'OWN': str(self.left / 'hooks')}
        settings = self.left / 'settings.json'
        settings.write_text(json.dumps(data)[:-1] + ', "ratio": 0.1234567890123456789012, "scale": 1.50}')
        settings.chmod(0o600)
        (self.left / 'CLAUDE.md').unlink()
        (self.left / 'CLAUDE.md').write_text(f'Rules live in {self.left}/rules and {sibling}.\n')
        (self.left / 'skills' / 'rel').symlink_to(os.path.relpath(self.source / 'skill-a', self.left / 'skills'))
        report = self.report('--write')
        self.assertEqual(report['verification']['unexpected'], [])
        copied = (self.target / 'settings.json').read_text()
        self.assertIn('"ratio": 0.1234567890123456789012', copied)
        self.assertIn('"scale": 1.50', copied)
        self.assertEqual(self.settings(self.target)['env'], {'LAB': sibling, 'OWN': str(self.target / 'hooks')})
        self.assertIn(sibling, (self.target / 'CLAUDE.md').read_text())
        self.assertEqual(stat.S_IMODE((self.target / 'settings.json').stat().st_mode), 0o600)

    def test_malformed_hooks_are_refused_without_writing(self):
        for hooks in ([], {'Stop': {}}, {'Stop': ['not a group']}):
            (self.left / 'settings.json').write_text(json.dumps({'hooks': hooks}))
            code, _, errors = self.copy('--write')
            self.assertEqual(code, 1)
            self.assertIn('hooks must map each event to a list of hook groups', errors)
            self.assertFalse(self.target.exists())

    def test_set_creates_settings_and_parses_json_values(self):
        (self.left / 'settings.json').unlink()
        self.report('--set', 'a.b=5', '--set', 'name=plain', '--set', 'flag=true', '--write')
        self.assertEqual(self.settings(self.target), {'a': {'b': 5}, 'name': 'plain', 'flag': True})

    def test_a_missing_setting_is_unexpected_but_a_left_out_plugin_is_not(self):
        real = compare_profiles

        def lossy(*args, **kwargs):
            report = real(*args, **kwargs)
            report['sections']['settings'].append({'item': 'lost', 'status': 'different', 'only': 'left'})
            report['sections']['hooks'].append({'item': 'added', 'status': 'different', 'only': 'right'})
            return report
        with mock.patch('agent_env_man.profile_copy.compare', lossy):
            check = self.report('--write')['verification']
        self.assertEqual([item['item'] for item in check['unexpected']], ['lost', 'added'])
        self.assertEqual(check['not_copied'], 2)

    def test_codex_source_is_refused(self):
        code, _, errors = self.copy('--write', source='codex')
        self.assertEqual(code, 1)
        self.assertIn('not a Claude Code profile', errors)
        self.assertFalse(self.target.exists())

    def test_write_never_creates_or_changes_the_machine_configuration(self):
        self.report('--write')
        self.assertFalse(self.config.exists())
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text('version = 1\n')
        self.report('--write', target=self.tmp / 'second')
        self.assertEqual(self.config.read_text(), 'version = 1\n')

    def test_copy_into_an_existing_empty_folder_is_allowed(self):
        self.target.mkdir()
        self.report('--write')
        self.assertTrue((self.target / 'settings.json').is_file())

    def edit_source(self, change):
        data = self.settings(self.left)
        change(data)
        (self.left / 'settings.json').write_text(json.dumps(data))

    def test_an_own_command_beside_an_aem_command_is_kept(self):
        self.edit_source(lambda data: data['hooks']['SessionStart'][0]['hooks'].append(
            {'type': 'command', 'command': 'bash mine.sh'}))
        check = self.report('--write')['verification']
        groups = self.settings(self.target)['hooks']['SessionStart']
        self.assertIn({'matcher': '^startup$', 'hooks': [{'type': 'command', 'command': 'bash mine.sh'}]}, groups)
        self.assertNotIn('--aem-hook-id', (self.target / 'settings.json').read_text())
        self.assertEqual(check['unexpected'], [])

    def test_aem_hooks_encoded_for_windows_are_left_out(self):
        self.edit_source(lambda data: data['hooks']['SessionStart'][0]['hooks'][0].update(
            command=encoded_aem_command('C:\\aem\\machine.toml', '0' * 20)))
        self.report('--write')
        self.assertNotIn('EncodedCommand', (self.target / 'settings.json').read_text())

    def test_setting_an_object_value_is_expected(self):
        check = self.report('--set', 'permissions={"allow":["Bash"],"deny":["Read"]}', '--write')['verification']
        self.assertEqual((check['expected'], check['unexpected']), (2, []))

    def test_home_relative_source_paths_are_rewritten(self):
        self.edit_source(lambda data: data['statusLine'].update(command=f'bash ~/{self.left.name}/status.sh'))
        with mock.patch('pathlib.Path.home', return_value=self.tmp):
            self.report('--write')
        self.assertEqual(self.settings(self.target)['statusLine']['command'], f'bash {self.target}/status.sh')

    def test_an_own_hook_missing_from_the_copy_is_unexpected(self):
        real = compare_profiles

        def lossy(*args, **kwargs):
            report = real(*args, **kwargs)
            report['sections']['hooks'].append({'item': 'Stop[] external#abcdef', 'owner': 'external',
                                                'status': 'different', 'only': 'left'})
            return report
        with mock.patch('agent_env_man.profile_copy.compare', lossy):
            check = self.report('--write')['verification']
        self.assertEqual([item['item'] for item in check['unexpected']], ['Stop[] external#abcdef'])


class Refuse(Copy):
    def test_text_output_lists_plugin_steps_with_the_target_config_dir(self):
        (self.left / 'plugins' / 'known_marketplaces.json').write_text(json.dumps(
            {'market': {'source': {'source': 'github', 'repo': 'owner/repo'}}}))
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            main(['--config', str(self.config), 'copy-profile', str(self.left), str(self.target)])
        self.assertIn(f'CLAUDE_CONFIG_DIR={self.target} claude plugin install tool@market --scope user', output.getvalue())

    def test_text_output_says_settings_are_independent(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            main(['--config', str(self.config), 'copy-profile', str(self.left), str(self.target)])
        self.assertIn('independent copy', output.getvalue())

    def test_preview_writes_nothing(self):
        report = self.report('--set', 'model=opus')
        self.assertFalse(report['applied'])
        self.assertFalse(self.target.exists())
        self.assertNotIn('verification', report)

    def test_nonempty_or_overlapping_targets_are_refused(self):
        self.target.mkdir()
        (self.target / 'keep').write_text('x')
        code, _, errors = self.copy('--write')
        self.assertEqual(code, 1)
        self.assertIn('already exists', errors)
        self.assertEqual((self.target / 'keep').read_text(), 'x')
        for target in (self.left, self.left / 'inner', self.tmp):
            code, _, errors = self.copy('--write', target=target)
            self.assertEqual(code, 1)
            self.assertIn('overlaps', errors)

    def test_bad_set_arguments_are_refused(self):
        for spec in ('model', '=x', 'hooks.SessionStart=1', 'model.deep=1'):
            code, _, errors = self.copy('--set', spec, '--write')
            self.assertEqual(code, 1, spec)
            self.assertFalse(self.target.exists(), spec)

    def test_source_settings_stay_untouched(self):
        before = self.snapshot()
        self.report('--set', 'model=opus', '--write')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
