"""Full automation uses temporary homes, local repositories, and fake uv installs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import automation, self_update
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, lock
from test_setup import SetupFixture


class FullAutomation(SetupFixture):
    def register(self, tool='off'):
        self.configure()
        self.uv = self.root / 'fake-uv'
        self.uv.write_text('fake')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.tools = self.root / 'tools'
        self.setup_cli('--shell', 'bash', '--automation', 'full', '--self-update', tool,
                       '--update-python', sys.executable, '--update-uv', self.uv,
                       '--update-tool-dir', self.tools, '--update-bin-dir', self.bin,
                       '--automation-trigger', 'interval', '--automation-interval', '3600')
        self.configuration = Config(self.config)
        return Manager(self.configuration, State(self.configuration.state_dir))

    def continue_in_process(self, manager):
        value = {'token': 'test', 'time': time.time(), 'status': 'continuing',
                 'binding': self_update.full_binding(manager.config.doc), 'stages': {'tool': {'status': 'disabled'}}}
        self_update.write_json(automation.result_path(manager.config), value)
        return automation.complete(manager, 'test')

    def finish_worker(self, config):
        value = self_update.read_result(automation.result_path(config))
        path = config.state_dir / 'self-update-worker' / value['token'] / 'request.json'
        request = json.loads(path.read_text())
        request['parent_pid'] = 0
        self_update.write_json(path, request)
        child = self_update._children[-1]
        self_update.close_workers()
        self.assertEqual(child.wait(timeout=15), 0)
        return self_update.read_result(automation.result_path(config))

    def test_full_prepares_updates_and_applies_default_skills_and_instructions(self):
        manager = self.register()
        report, failed = self.continue_in_process(manager)
        self.assertFalse(failed, report)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['stages']['catalog']['status'], 'skipped')
        self.assertEqual(report['stages']['content']['sources'], ['report', 'personal'])
        self.assertTrue((self.destination / 'report/SKILL.md').exists())
        self.assertTrue((self.agent / 'AGENTS.md').exists())
        with self.assertRaises(Error):
            automation.complete(manager, 'test')  # Continuations are consumed once.

    def test_full_preserves_explicit_manual_and_detached_consumers(self):
        manager = self.register()
        self.run_cli('apply')
        self.run_cli('detach', 'personal:bundle', 'personal:entry')
        document = tomlkit.parse(self.catalog.read_text())
        document['skills']['report']['update'] = {'trigger': []}
        self.catalog.write_text(tomlkit.dumps(document))
        manager = Manager(Config(self.config), State(self.configuration.state_dir))
        with patch.object(Manager, 'prepare_skills', side_effect=AssertionError('Excluded sources prepared')):
            report, failed = self.continue_in_process(manager)
        self.assertFalse(failed)
        self.assertEqual(report['stages']['content']['status'], 'skipped')
        self.assertEqual(report['stages']['content']['excluded'],
                         [{'source': 'report', 'reason': 'manual'}, {'source': 'personal', 'reason': 'detached'}])
        self.assertFalse((self.agent / 'AGENTS.md').is_symlink())

    def test_global_explicit_manual_precedence_is_preserved(self):
        self.register()
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': []}, 'policies': {'enabled': {'trigger': ['agent-start']}}}
        doc['skills']['report']['update'] = {'policy': 'enabled'}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.assertEqual(Config(self.config).full_update_policies()['report']['trigger'], ['agent-start'])
        del doc['skills']['report']['update']
        self.catalog.write_text(tomlkit.dumps(doc))
        self.assertEqual(Config(self.config).full_update_policies()['report']['trigger'], ['manual'])

    def test_off_gates_all_events_but_explicit_operations_work(self):
        self.configure()
        self.run_cli('setup', '--automation', 'off')
        with patch.object(Manager, 'update', side_effect=AssertionError('Automatic update ran')):
            self.assertEqual(self.run_cli('automation', '--trigger', 'interval')['status'], 'disabled')
            self.assertEqual(self.run_cli('auto', '--trigger', 'agent-start'), [])
            self.assertEqual(self.run_cli('catalog', 'auto', '--trigger', 'agent-start')['status'], 'not-triggered')
            self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start'), {})
        self.run_cli('update')
        self.run_cli('apply')
        self.assertTrue((self.destination / 'report/SKILL.md').exists())

    def test_full_event_clock_preview_and_individual_event_rejection(self):
        manager = self.register()
        before = self.config.read_bytes()
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.assertEqual(self.run_cli('automation', '--trigger', 'interval', '--dry-run')['status'], 'planned')
            spawn.assert_not_called()
            self.assertFalse(automation.result_path(manager.config).exists())
            self.assertEqual(before, self.config.read_bytes())
            self.assertEqual(self.run_cli('automation', '--trigger', 'interval')['status'], 'queued')
            self.assertEqual(self.run_cli('automation', '--trigger', 'interval')['status'], 'throttled')
            self.assertEqual(spawn.call_count, 1)
            self.run_cli('auto', '--trigger', 'interval', code=1)
            self.run_cli('catalog', 'auto', '--trigger', 'interval', code=1)
        self_update.close_workers()

    def test_full_skip_setting_reaches_worker_and_invalidates_continuation(self):
        self.register()
        self.run_cli('setup', '--automation-skip-unsupported')
        manager = Manager(Config(self.config), State(self.configuration.state_dir))
        with patch.object(self_update, 'launch', return_value={'status': 'queued'}) as launch:
            automation.schedule(manager.config, 'interval')
        self.assertTrue(launch.call_args.kwargs['extra']['saved_automation']['skip_unsupported'])
        saved = {'token': 'test', 'status': 'continuing',
                 'binding': self_update.full_binding(manager.config.doc)}
        self_update.write_json(automation.result_path(manager.config), saved)
        self.run_cli('setup', '--no-automation-skip-unsupported')
        self.assertIn('No matching', str(self.run_cli('_full-run', '--token', 'test', code=1)))

    def test_policy_only_setup_preserves_fields_and_invalid_settings_fail(self):
        self.configure()
        self.run_cli('setup', '--automation', 'off', '--automation-interval', '60')
        self.run_cli('setup', '--automation-trigger', 'interval')
        saved = tomlkit.parse(self.config.read_text())
        self.assertEqual(saved['automation'], {'mode': 'off', 'min_interval': 60, 'trigger': ['interval']})
        before = self.config.read_bytes()
        self.run_cli('setup', '--automation', 'full', code=1)  # Requires registered external runtime.
        self.assertEqual(before, self.config.read_bytes())
        for options in (('--automation-timeout', '0'), ('--automation-interval', '-1'),
                        ('--automation-trigger', 'manual', '--automation-trigger', 'interval')):
            self.run_cli('setup', *options, code=1 if options[0] == '--automation-trigger' else 2)
            self.assertEqual(before, self.config.read_bytes())

    def test_prepare_or_update_failure_blocks_apply_and_conflicts_are_preserved(self):
        manager = self.register()
        with patch.object(Manager, 'prepare_skills', return_value=([{'status': 'failed'}], True)), \
                patch.object(Manager, 'update', side_effect=AssertionError('Update after preparation failure')):
            result, failed = self.continue_in_process(manager)
            self.assertTrue(failed)
        with patch.object(Manager, 'update', return_value=([{'status': 'failed'}], True)), \
                patch.object(Manager, 'apply', side_effect=AssertionError('Apply after delivery failure')):
            _, failed = self.continue_in_process(manager)
            self.assertTrue(failed)
        target = self.destination / 'report'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('user file')
        _, failed = self.continue_in_process(manager)
        self.assertTrue(failed)
        self.assertEqual((target / 'SKILL.md').read_text(), 'user file')

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration uses a POSIX shebang')
    def test_worker_restarts_fresh_cli_after_tool_install_before_catalog_and_content(self):
        manager = self.register(tool='compatible')
        self.setup_cli('--agent', 'codex')
        release = self.root / 'release'
        release.mkdir()
        self.git(release, 'init', '-b', 'main')
        (release / 'pyproject.toml').write_text('[project]\nname="agent-env-man"\nversion="0.2.1"\n')
        self.commit(release)
        self.git(release, 'tag', 'v0.2.1')
        doc = tomlkit.parse(self.config.read_text())
        doc['self_update']['repository'] = str(release)
        self.config.write_text(tomlkit.dumps(doc))
        config = Config(self.config)
        marker = self.root / 'order'
        executable = self.bin / 'aem'
        executable.write_text('#!' + sys.executable + '\nraise SystemExit(99)\n')
        executable.chmod(0o755)
        fresh = ('#!' + sys.executable + '\nfrom pathlib import Path\n'
                 'Path(' + repr(str(marker)) + ').open("a").write("fresh-cli\\n")\n'
                 'from agent_env_man.cli import main\nraise SystemExit(main())\n')
        self.uv.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v0.2.0")\n'
                           'else:\n Path(' + repr(str(marker)) + ').write_text("tool\\n")\n'
                           ' Path(' + repr(str(executable)) + ').write_text(' + repr(fresh) + ')\n')
        self.uv.chmod(0o755)
        with lock(config.state_dir):
            automation.schedule(config, 'interval')
        result = self.finish_worker(config)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(marker.read_text().splitlines(), ['tool', 'fresh-cli', 'fresh-cli'])
        self.assertEqual(result['stages']['tool']['version'], '0.2.1')
        self.assertEqual(result['stages']['official_skill']['status'], 'completed')
        self.assertTrue((self.destination / 'report/SKILL.md').exists())
        self.assertTrue((self.agent / 'AGENTS.md').exists())

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration uses a POSIX shebang')
    def test_worker_tool_failure_blocks_continuation_and_failure_is_throttled(self):
        manager = self.register(tool='compatible')
        self.uv.write_text('#!' + sys.executable + '\nraise SystemExit(1)\n')
        self.uv.chmod(0o755)
        with lock(manager.config.state_dir):
            automation.schedule(manager.config, 'interval')
        result = self.finish_worker(manager.config)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse((self.destination / 'report').exists())
        self.assertEqual(self.run_cli('automation', '--trigger', 'interval')['status'], 'throttled')

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration uses a POSIX shebang')
    def test_queued_full_run_cancelled_when_mode_changes(self):
        manager = self.register()
        with lock(manager.config.state_dir):
            automation.schedule(manager.config, 'interval')
        self.setup_cli('--automation', 'off')
        self.assertEqual(self.finish_worker(manager.config)['status'], 'cancelled')


from test_git_catalog import GitCatalog


class FullGitCatalog(unittest.TestCase):
    setUp = GitCatalog.setUp
    git = GitCatalog.git
    commit = GitCatalog.commit
    save_remote = GitCatalog.save_remote
    cli = GitCatalog.cli
    boot = GitCatalog.boot
    state = GitCatalog.state

    def register(self):
        self.boot()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.uv = self.root / 'uv'
        self.uv.write_text('not used')
        doc = tomlkit.parse(self.config.read_text())
        doc['self_update'] = {'mode': 'off', 'python': sys.executable, 'uv': str(self.uv),
                              'tool_dir': str(self.root / 'tools'), 'bin_dir': str(self.bin)}
        doc['automation'] = {'mode': 'full', 'trigger': ['interval'], 'min_interval': 3600}
        self.config.write_text(tomlkit.dumps(doc))
        return Config(self.config)

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration uses a POSIX shebang')
    def test_real_cli_worker_refreshes_catalog_then_prepares_new_declarations(self):
        config = self.register()
        self.document['skills']['new'] = dict(self.document['skills']['tool'])
        self.document['skills']['new']['subdir'] = 'new-skill'
        (self.seed / 'new-skill').mkdir()
        (self.seed / 'new-skill/SKILL.md').write_text('# New skill\n', encoding='utf-8')
        (self.seed / 'editor.toml').write_text('color = "blue"\n', encoding='utf-8')
        self.document['settings'] = {'editor': {'source': 'tool', 'path': 'editor.toml', 'format': 'toml'}}
        setting_target = self.root / 'app.toml'
        machine = tomlkit.parse(self.config.read_text())
        machine['settings'] = {'editor': {'target': str(setting_target)}}
        self.config.write_text(tomlkit.dumps(machine))
        self.save_remote()
        executable = self.bin / 'aem'
        executable.write_text('#!' + sys.executable + '\nfrom agent_env_man.cli import main\nraise SystemExit(main())\n')
        executable.chmod(0o755)
        response = subprocess.run([sys.executable, '-m', 'agent_env_man', '--json', '--config', str(self.config),
                                   'automation', '--trigger', 'interval'], capture_output=True, text=True, timeout=5)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['status'], 'queued')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self_update.read_result(automation.result_path(config))
            if result.get('status') not in ('queued', 'continuing'):
                break
            time.sleep(0.02)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['stages']['tool']['status'], 'disabled')
        self.assertEqual(result['stages']['catalog']['status'], 'updated')
        self.assertTrue((self.root / 'installed/new/SKILL.md').is_file())
        self.assertTrue(self.target.is_dir())
        self.assertEqual(result['stages']['content']['sources'], ['tool', 'new', 'editor'])
        self.assertEqual(tomlkit.parse(setting_target.read_text())['color'], 'blue')
        self.assertNotIn('settings_automation', json.loads(self.state())['sources']['editor'])
        self.assertNotIn('catalog_automation', json.loads(self.state()))
        self.assertNotIn('automation', json.loads(self.state())['sources']['tool'])

    def add_shared_skill(self, *, present=True):
        self.document['skills']['new'] = {
            'source': 'tool', 'subdir': 'new-skill', 'install': {'mode': 'copy'}}
        if present:
            (self.seed / 'new-skill').mkdir()
            (self.seed / 'new-skill/SKILL.md').write_text('# New skill\n', encoding='utf-8')
        self.save_remote()

    def continue_full(self, config, *, code=0):
        self_update.write_json(automation.result_path(config), {
            'status': 'continuing', 'time': time.time(), 'token': 'test',
            'binding': self_update.full_binding(config.doc), 'stages': {'tool': {'status': 'disabled'}}})
        return self.cli('_full-run', '--token', 'test', code=code)

    def test_new_shared_skill_with_eligible_detached_and_manual_consumers(self):
        cases = ((policy, mode) for policy in ('eligible', 'detached', 'manual')
                 for mode in ('copy', 'link'))
        for policy, mode in cases:
            with self.subTest(policy=policy, mode=mode):
                self.setUp()
                if mode == 'link':
                    probe = self.root / 'link-probe'
                    try:
                        probe.symlink_to(self.seed, target_is_directory=True)
                    except OSError:
                        self.skipTest('Symbolic link capability unavailable')
                    probe.unlink()
                    self.document['skills']['tool']['install']['mode'] = 'link'
                    self.save_remote()
                config = self.register()
                self.cli('apply', '--item', 'tool')
                if policy == 'detached':
                    self.cli('detach', 'tool')
                if policy == 'manual':
                    self.document['skills']['tool']['update'] = {'trigger': []}
                self.add_shared_skill()
                (self.seed / 'skill/SKILL.md').write_text('# Updated existing\n', encoding='utf-8')
                self.save_remote()
                result = self.continue_full(config)
                content = result['stages']['content']
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['stages']['catalog']['status'], 'updated')
                self.assertEqual(content['sources'], ['tool', 'new'] if policy == 'eligible' else ['new'])
                self.assertEqual(self.git(self.content, 'rev-parse', 'HEAD'), self.git(self.seed, 'rev-parse', 'HEAD'))
                self.assertEqual((self.root / 'installed/new/SKILL.md').read_text(), '# New skill\n')
                preserved = policy == 'detached' or (policy == 'manual' and mode == 'copy')
                expected = '# Initial\n' if preserved else '# Updated existing\n'
                self.assertEqual((self.target / 'SKILL.md').read_text(), expected)
                if policy == 'detached':
                    self.assertTrue(json.loads(self.state())['items']['tool']['detached'])
                    self.assertFalse(self.target.is_symlink())
                else:
                    self.assertEqual(self.target.is_symlink(), mode == 'link')

    def test_full_refuses_dirty_diverged_and_invalid_incoming_shared_skills(self):
        for invalid in ('dirty', 'diverged', 'absent', 'symlink'):
            with self.subTest(invalid=invalid):
                self.setUp()
                config = self.register()
                self.cli('apply', '--item', 'tool')
                installed = (self.target / 'SKILL.md').read_bytes()
                self.add_shared_skill(present=invalid != 'absent')
                if invalid == 'dirty':
                    (self.content / 'skill/SKILL.md').write_text('local edits', encoding='utf-8')
                elif invalid == 'diverged':
                    (self.content / 'local.txt').write_text('local commit', encoding='utf-8')
                    self.commit(self.content)
                elif invalid == 'symlink':
                    # Git mode validation also works where checkout symlinks are unavailable.
                    blob = self.git(self.seed, 'hash-object', '-w', 'skill/SKILL.md')
                    self.git(self.seed, 'update-index', '--add', '--cacheinfo', f'120000,{blob},new-skill/redirect')
                    self.git(self.seed, 'commit', '-m', 'Invalid skill tree')
                    self.git(self.seed, 'push', 'origin', 'main')
                head = self.git(self.content, 'rev-parse', 'HEAD')
                result = self.continue_full(config, code=1)
                content = result['stages']['content']
                self.assertEqual(result['stages']['catalog']['status'], 'updated')
                self.assertEqual(content['status'], 'failed')
                stage_name = 'prepare' if invalid == 'dirty' else 'update'
                self.assertIn(stage_name, content, content)
                stage = content[stage_name]
                errors = ' '.join(entry.get('error', '') for entry in stage)
                expected = {'dirty': 'dirty checkout', 'diverged': 'diverged',
                            'absent': 'new: skill needs a tracked regular', 'symlink': 'new: skill contains a Git symlink'}
                self.assertIn(expected[invalid], errors)
                self.assertNotIn('apply', content)
                self.assertEqual(self.git(self.content, 'rev-parse', 'HEAD'), head)
                self.assertEqual((self.target / 'SKILL.md').read_bytes(), installed)
                self.assertFalse((self.root / 'installed/new').exists())
                if invalid == 'dirty':
                    self.assertEqual((self.content / 'skill/SKILL.md').read_text(), 'local edits')

    def test_bootstrap_stale_skill_diagnostic_and_supported_recovery(self):
        self.register()
        self.cli('apply', '--item', 'tool')
        self.cli('detach', 'tool')
        self.add_shared_skill()
        self.cli('catalog', 'update')
        head = self.git(self.content, 'rev-parse', 'HEAD')
        result = self.cli('bootstrap', '--item', 'new', code=1)
        error = result['skills'][0]['error']
        self.assertIn('new: skill needs a tracked regular new-skill/SKILL.md at HEAD', error)
        self.assertIn('aem update new', error)
        self.assertIn('aem bootstrap --item new', error)
        self.assertEqual(self.git(self.content, 'rev-parse', 'HEAD'), head)
        self.cli('update', 'new')
        self.cli('bootstrap', '--item', 'new')
        self.cli('apply', '--item', 'new', '--dry-run')
        self.assertFalse((self.root / 'installed/new').exists())
        self.cli('apply', '--item', 'new')
        self.assertEqual((self.root / 'installed/new/SKILL.md').read_text(), '# New skill\n')
        self.assertEqual((self.target / 'SKILL.md').read_text(), '# Initial\n')
        self.assertTrue(json.loads(self.state())['items']['tool']['detached'])

    def test_explicit_update_refuses_missing_incoming_new_skill(self):
        self.register()
        self.add_shared_skill(present=False)
        self.cli('catalog', 'update')
        head = self.git(self.content, 'rev-parse', 'HEAD')
        result = self.cli('update', 'new', code=1)
        self.assertIn('new: skill needs a tracked regular', result[0]['error'])
        self.assertEqual(self.git(self.content, 'rev-parse', 'HEAD'), head)

    def test_invalid_catalog_blocks_full_content_and_retains_old_revision(self):
        config = self.register()
        original = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.save_remote('broken TOML [')
        self_update.write_json(automation.result_path(config), {'status': 'continuing', 'time': time.time(),
            'token': 'test', 'binding': self_update.full_binding(config.doc), 'stages': {'tool': {'status': 'disabled'}}})
        with patch.object(Manager, 'prepare_skills', side_effect=AssertionError('Content ran after catalog failure')):
            result = self.cli('_full-run', '--token', 'test', code=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['stages']['catalog']['status'], 'failed')
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), original)
        self.assertFalse(self.target.exists())


# The imported fixture class itself must not be rediscovered in this module.
del GitCatalog
