"""Profile comparison reads two roots offline and never writes."""
import base64
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from agent_env_man.cli import main


def encoded_aem_command(config, digest):
    """An AEM startup command as AEM writes it on native Windows."""
    script = (f"& 'python' '-m' 'agent_env_man' '--config' '{config}' 'startup' "
              f"'--aem-hook-id' 'AEM startup [{digest}]'; exit $LASTEXITCODE")
    return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + base64.b64encode(script.encode('utf-16le')).decode('ascii')


AEM_COMMAND = 'python -m agent_env_man --config {config} startup --aem-hook-id marker-{name}'


class Roots(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.config = self.tmp / 'aem' / 'machine.toml'
        self.source = self.tmp / 'source'
        (self.source / 'skill-a').mkdir(parents=True)
        (self.source / 'entry.md').write_text('rules')
        self.left = self.profile('left')
        self.right = self.profile('right')

    def profile(self, name, **overrides):
        root = self.tmp / name
        (root / 'skills').mkdir(parents=True)
        (root / 'skills' / 'skill-a').symlink_to(self.source / 'skill-a')
        (root / 'CLAUDE.md').symlink_to(self.source / 'entry.md')
        (root / 'output-styles').symlink_to(self.source)
        settings = {
            'model': 'sonnet',
            'effortLevel': 'medium',
            'statusLine': {'type': 'command', 'command': 'python3 status.py'},
            'hooks': {
                'SessionStart': [
                    {'matcher': '^startup$', 'hooks': [{'type': 'command',
                     'command': AEM_COMMAND.format(config=self.config, name=name)}]},
                    {'matcher': '', 'hooks': [{'type': 'command',
                     'command': f'bash {root}/hooks/herdr.sh session'}]},
                ],
            },
        }
        settings.update(overrides)
        (root / 'settings.json').write_text(json.dumps(settings))
        plugins = root / 'plugins'
        plugins.mkdir()
        (plugins / 'installed_plugins.json').write_text(json.dumps(
            {'version': 2, 'plugins': {'tool@market': [{'scope': 'user', 'version': '1.0.0'}]}}))
        return root

    def run_compare(self, *args, left=None, right=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), *(['--json'] if '--json' in args else []), 'compare',
                         str(left or self.left), str(right or self.right),
                         *[a for a in args if a != '--json']])
        return code, output.getvalue(), errors.getvalue()

    def report(self, *args, **kwargs):
        code, output, errors = self.run_compare('--json', *args, **kwargs)
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def items(self, report, section):
        return {item['item']: item for item in report['sections'][section]}

    def snapshot(self):
        return {str(p): (p.read_bytes() if p.is_file() and not p.is_symlink() else os.readlink(p) if p.is_symlink() else None)
                for root in (self.left, self.right) for p in root.rglob('*')}


class Compare(Roots):
    def test_profile_specific_paths_are_not_drift(self):
        report = self.report()
        self.assertEqual(report['totals']['different'], 0, report)
        self.assertEqual(report['totals']['expected'], 0)
        self.assertGreater(report['totals']['same'], 8)

    def test_value_difference_is_digest_unless_values_requested(self):
        (self.right / 'settings.json').write_text(json.dumps({**json.loads((self.right / 'settings.json').read_text()),
                                                              'model': 'opus-secret'}))
        report = self.report()
        item = self.items(report, 'settings')['model']
        self.assertEqual(item['status'], 'different')
        self.assertNotIn('opus-secret', json.dumps(report))
        self.assertEqual(len(item['left']), 8)
        shown = self.items(self.report('--values'), 'settings')['model']
        self.assertEqual((shown['left'], shown['right']), ('sonnet', 'opus-secret'))

    def test_expect_marks_a_difference_as_intended_and_reports_unmatched_names(self):
        (self.right / 'settings.json').write_text(json.dumps({**json.loads((self.right / 'settings.json').read_text()),
                                                              'model': 'opus'}))
        report = self.report('--expect', 'model', '--expect', 'no.such.item')
        self.assertEqual(self.items(report, 'settings')['model']['status'], 'expected')
        self.assertEqual(report['totals']['different'], 0)
        self.assertEqual(report['unmatched_expect'], ['no.such.item'])

    def test_booleans_and_numbers_are_distinct_and_absence_is_not_null(self):
        base = json.loads((self.left / 'settings.json').read_text())
        (self.left / 'settings.json').write_text(json.dumps({**base, 'flag': True, 'nothing': None}))
        (self.right / 'settings.json').write_text(json.dumps({**base, 'flag': 1}))
        items = self.items(self.report(), 'settings')
        self.assertEqual(items['flag']['status'], 'different')
        self.assertNotIn('only', items['flag'])
        self.assertEqual(items['nothing'].get('only'), 'left')

    def test_numbers_compare_by_value_not_spelling(self):
        base = json.loads((self.left / 'settings.json').read_text())
        (self.left / 'settings.json').write_text(json.dumps({**base, 'interval': 10, 'ratio': 0.5}))
        # The same values spelled differently: 1e1 is 10 and 5e-1 is 0.5.
        (self.right / 'settings.json').write_text(json.dumps(base)[:-1] + ', "interval": 1e1, "ratio": 5e-1}')
        items = self.items(self.report(), 'settings')
        self.assertEqual((items['interval']['status'], items['ratio']['status']), ('same', 'same'))

    def test_hook_groups_are_compared_by_owner(self):
        data = json.loads((self.right / 'settings.json').read_text())
        data['hooks']['SessionStart'] = [data['hooks']['SessionStart'][0],
                                         {'matcher': '', 'hooks': [{'type': 'command', 'command': 'bash other.sh'}]}]
        (self.right / 'settings.json').write_text(json.dumps(data))
        hooks = self.items(self.report(), 'hooks')
        self.assertEqual(hooks['SessionStart[^startup$] aem']['status'], 'same')
        self.assertEqual(sum(1 for item in hooks.values() if item['status'] == 'same'), 1)
        external = [item for name, item in hooks.items() if ' external#' in name]
        self.assertEqual(len(external), 2)
        self.assertEqual(sorted(item['only'] for item in external if 'only' in item), ['left', 'right'])
        self.assertEqual(len({item['item'] for item in external}), 2)

    def test_personal_hooks_compare_without_their_per_agent_marker(self):
        def personal(marker, script):
            return {'matcher': '', 'hooks': [{'type': 'command', 'command': f": 'AEM personal hook [{marker}]'; exec /usr/bin/python3 {script}"}]}
        for root, marker in ((self.left, '0' * 20), (self.right, '1' * 20)):
            data = json.loads((root / 'settings.json').read_text())
            data['hooks']['Stop'] = [personal(marker, '/tools/logger')]
            (root / 'settings.json').write_text(json.dumps(data))
        stops = [item for name, item in self.items(self.report(), 'hooks').items() if name.startswith('Stop')]
        self.assertEqual([item['status'] for item in stops], ['same'])
        # Personal hooks are AEM-owned, as copy-profile treats them, yet still compare by command.
        self.assertTrue(all(' aem#' in name for name in self.items(self.report(), 'hooks') if name.startswith('Stop')))
        data = json.loads((self.right / 'settings.json').read_text())
        data['hooks']['Stop'] = [personal('1' * 20, '/tools/other')]
        (self.right / 'settings.json').write_text(json.dumps(data))
        self.assertEqual(sorted(item['status'] for name, item in self.items(self.report(), 'hooks').items() if name.startswith('Stop')),
                         ['different', 'different'])

    def test_skill_link_plugin_and_entry_differences(self):
        other = self.tmp / 'other'
        other.mkdir()
        (self.right / 'skills' / 'skill-a').unlink()
        (self.right / 'skills' / 'skill-a').symlink_to(other)
        (self.right / 'skills' / 'extra').symlink_to(other)
        (self.right / 'CLAUDE.md').unlink()
        (self.right / 'CLAUDE.md').write_text('own rules')
        (self.right / 'plugins' / 'installed_plugins.json').write_text(json.dumps(
            {'version': 2, 'plugins': {'tool@market': [{'version': '1.1.0'}], 'new@market': [{'version': '0.1'}]}}))
        report = self.report()
        self.assertEqual(self.items(report, 'skills')['skills/skill-a']['status'], 'different')
        self.assertEqual(self.items(report, 'skills')['skills/extra']['only'], 'right')
        self.assertEqual(self.items(report, 'entry')['CLAUDE.md']['status'], 'different')
        plugins = self.items(report, 'plugins')
        self.assertEqual((plugins['plugins/tool@market']['left'], plugins['plugins/tool@market']['right']), ('1.0.0', '1.1.0'))
        self.assertEqual(plugins['plugins/new@market']['only'], 'right')

    def test_missing_settings_file_lists_fields_as_one_sided(self):
        (self.right / 'settings.json').unlink()
        items = self.items(self.report(), 'settings')
        self.assertTrue(items and all(item.get('only') == 'left' for item in items.values()))

    def test_secret_values_stay_out_of_text_output_without_values_flag(self):
        base = json.loads((self.left / 'settings.json').read_text())
        (self.left / 'settings.json').write_text(json.dumps({**base, 'env': {'TOKEN': 'left-secret'}}))
        (self.right / 'settings.json').write_text(json.dumps({**base, 'env': {'TOKEN': 'right-secret'}}))
        code, output, _ = self.run_compare()
        self.assertEqual(code, 0)
        self.assertIn('env.TOKEN', output)
        self.assertNotIn('secret', output)
        self.assertIn('left-secret', self.run_compare('--values')[1])

    def test_compare_changes_nothing_and_needs_no_machine_state(self):
        before = self.snapshot()
        self.run_compare()
        self.run_compare('--values', '--json')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.config.parent.exists())

    def test_registered_agent_names_resolve_from_the_machine_file(self):
        self.config.parent.mkdir()
        self.config.write_text(f'version = 1\n[agents.claude]\nroot = "{self.left}"\nskills = "{self.left}/skills"\n'
                               f'[agents.claude-lab]\nroot = "{self.right}"\nskills = "{self.right}/skills"\n')
        code, output, errors = self.run_compare('--json', left='claude', right='claude-lab')
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)['totals']['different'], 0)

    def test_unknown_name_is_refused(self):
        for name in ('nobody', 'relative/root'):
            code, _, errors = self.run_compare(left=name)
            self.assertEqual(code, 1)
            self.assertIn(f'Unknown profile {name}; use a registered agent name or an absolute root path', errors)

    def test_numbers_beyond_default_decimal_precision_stay_distinct(self):
        base = (self.left / 'settings.json').read_text()[:-1]
        (self.left / 'settings.json').write_text(base + ', "big": 12345678901234567890123456789012}')
        (self.right / 'settings.json').write_text(base.replace('left', 'right') + ', "big": 12345678901234567890123456789013}')
        self.assertEqual(self.items(self.report(), 'settings')['big']['status'], 'different')

    def test_a_sibling_root_sharing_the_prefix_is_not_normalized(self):
        sibling = str(self.left) + '-lab/settings.json'
        for root, value in ((self.left, sibling), (self.right, str(self.right) + '-lab/settings.json')):
            data = json.loads((root / 'settings.json').read_text())
            data['env'] = {'OTHER': value}
            (root / 'settings.json').write_text(json.dumps(data))
        self.assertEqual(self.items(self.report(), 'settings')['env.OTHER']['status'], 'different')

    def test_codex_profiles_are_refused(self):
        code, _, errors = self.run_compare(left='codex')
        self.assertEqual(code, 1)
        self.assertIn('not a Claude Code profile', errors)

    def test_invalid_settings_json_is_reported(self):
        (self.right / 'settings.json').write_text('{broken')
        code, _, errors = self.run_compare()
        self.assertEqual(code, 1)
        self.assertIn('settings.json', errors)

    def edit(self, root, change):
        data = json.loads((root / 'settings.json').read_text())
        change(data)
        (root / 'settings.json').write_text(json.dumps(data))

    def test_aem_hooks_encoded_for_windows_are_aem_owned(self):
        for root, digest in ((self.left, '0' * 20), (self.right, '1' * 20)):
            self.edit(root, lambda data: data['hooks']['SessionStart'][0]['hooks'][0].update(
                command=encoded_aem_command(f'C:\\aem\\{root.name}.toml', digest)))
        report = self.report()
        self.assertEqual(report['totals']['different'], 0, report)
        self.assertEqual(self.items(report, 'hooks')['SessionStart[^startup$] aem']['status'], 'same')

    def test_home_relative_spellings_of_the_root_are_normalized(self):
        self.edit(self.left, lambda data: data['statusLine'].update(command=f'bash ~/{self.left.name}/status.sh'))
        self.edit(self.right, lambda data: data['statusLine'].update(command=f'bash $HOME/{self.right.name}/status.sh'))
        with mock.patch('pathlib.Path.home', return_value=self.tmp):
            report = self.report()
        self.assertEqual(self.items(report, 'settings')['statusLine.command']['status'], 'same')

    def test_expect_marks_an_intended_hook_difference(self):
        self.edit(self.right, lambda data: data['hooks'].update(
            Stop=[{'hooks': [{'type': 'command', 'command': 'bash notify.sh'}]}]))
        label = next(name for name in self.items(self.report(), 'hooks') if name.startswith('Stop'))
        report = self.report('--expect', label)
        self.assertEqual(self.items(report, 'hooks')[label]['status'], 'expected')
        self.assertEqual((report['totals']['different'], report['unmatched_expect']), (0, []))

    def test_expect_on_a_settings_object_covers_its_fields(self):
        self.edit(self.right, lambda data: data.update(permissions={'allow': ['Bash'], 'deny': []}))
        report = self.report('--expect', 'permissions')
        self.assertEqual({item['status'] for name, item in self.items(report, 'settings').items()
                          if name.startswith('permissions.')}, {'expected'})
        self.assertEqual((report['totals']['different'], report['unmatched_expect']), (0, []))

    def test_a_repeated_hook_group_is_a_difference(self):
        self.edit(self.left, lambda data: data['hooks']['SessionStart'].append(data['hooks']['SessionStart'][0]))
        item = self.items(self.report(), 'hooks')['SessionStart[^startup$] aem']
        self.assertEqual(item['status'], 'different')
        self.assertEqual((item['left'], item['right']), (2, 1))

    def test_a_settings_file_holding_only_hooks_has_no_unnamed_field(self):
        self.edit(self.left, lambda data: [data.pop(key) for key in list(data) if key != 'hooks'])
        (self.right / 'settings.json').unlink()
        self.assertNotIn('', self.items(self.report(), 'settings'))


if __name__ == '__main__':
    unittest.main()
