"""Copy a personal profile to a new lab profile, register it with AEM, then compare."""
import io
import json
import shutil
from contextlib import redirect_stdout, redirect_stderr

from agent_env_man.cli import main
import test_named_profiles
from test_setup import SetupFixture


class Workflow(SetupFixture):
    prepare = test_named_profiles.NamedProfiles.prepare

    def run_main(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(['--config', str(self.config), *args])
        return code, output.getvalue(), errors.getvalue()

    def personal_profile(self):
        """The registered personal profile plus a user hook and script AEM does not own."""
        self.prepare()
        root = self.home / '.claude'
        settings = json.loads((root / 'settings.json').read_text())
        settings['model'] = 'sonnet'
        settings['hooks'].setdefault('SessionStart', []).append(
            {'matcher': '', 'hooks': [{'type': 'command', 'command': f'bash {root}/hooks/herdr.sh session'}]})
        (root / 'settings.json').write_text(json.dumps(settings))
        (root / 'hooks').mkdir()
        (root / 'hooks' / 'herdr.sh').write_text(f'exec {root}/hooks/real.sh\n')
        return root

    def test_lab_copy_differs_only_in_the_chosen_model_and_survives_the_personal_profile(self):
        personal = self.personal_profile()
        lab = self.home / '.claude-lab'

        code, output, errors = self.run_main('--json', 'copy-profile', str(personal), str(lab), '--set', 'model=opus', '--write')
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)['verification']['unexpected'], [])
        self.assertFalse((lab / 'CLAUDE.md').exists())  # AEM installs it for the lab itself

        self.setup_cli('--agent', 'claude-lab')
        self.run_cli('apply', '--agent', 'claude-lab', '--dry-run')
        self.run_cli('apply', '--agent', 'claude-lab')

        code, output, errors = self.run_main('--json', 'compare', 'claude', 'claude-lab', '--expect', 'model')
        totals = json.loads(output)['totals']
        self.assertEqual((code, totals['different'], totals['expected']), (0, 0, 1), output)
        settings = json.loads((lab / 'settings.json').read_text())
        self.assertEqual(settings['model'], 'opus')
        self.assertEqual(json.loads((personal / 'settings.json').read_text())['model'], 'sonnet')
        commands = [h['command'] for groups in settings['hooks'].values() for g in groups for h in g['hooks']]
        self.assertIn(f'bash {lab}/hooks/herdr.sh session', commands)
        self.assertTrue(all('--agent claude-lab' in c for c in commands if '--aem-hook-id' in c))

        shutil.rmtree(personal)
        code, output, errors = self.run_main('agent-hook', 'personal', '--agent', 'claude-lab')
        self.assertEqual(code, 0, errors)
        self.assertIn(str(lab / 'CLAUDE.md'), output)
        self.run_cli('apply', '--agent', 'claude-lab')
        self.assertTrue((lab / 'skills' / 'report').is_symlink())
        self.assertTrue((lab / 'skills' / 'report').resolve().exists())

    def test_links_the_user_made_are_copied_but_aem_installed_ones_are_left_to_aem(self):
        personal = self.personal_profile()
        (personal / 'skills' / 'mine').symlink_to(self.bundle)
        lab = self.home / '.claude-lab'
        code, output, errors = self.run_main('--json', 'copy-profile', str(personal), str(lab), '--write')
        self.assertEqual(code, 0, errors)
        report = json.loads(output)
        self.assertIn('skills/mine', report['links'])
        self.assertNotIn('skills/report', report['links'])
        self.assertIn({'item': 'skills/report', 'reason': 'installed by AEM; run aem apply for the target'}, report['skipped'])
        self.assertEqual(report['verification']['unexpected'], [])
