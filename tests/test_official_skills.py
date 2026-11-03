"""Official integration links use isolated payloads and fake update installers."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man import agents, automation, official_skills, self_update
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.setup import official_plans
from agent_env_man.storage import State, observation
import test_self_update
from test_setup import SetupFixture


class OfficialSkillResources(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-skill-resources-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_source_checkout_fallback_requires_a_descriptor(self):
        module = self.root / "src/agent_env_man/official_skills.py"
        payload = self.root / "skills" / official_skills.NAME
        payload.mkdir(parents=True)
        descriptor = payload / "SKILL.md"
        descriptor.write_bytes(b"source skill\n")
        missing_package = ModuleNotFoundError(name="agent_env_man.builtin_skills")
        with patch.object(official_skills, "__file__", str(module)), patch.object(
                official_skills.resources, "files", side_effect=missing_package):
            self.assertEqual(official_skills.source(), payload)
            descriptor.unlink()
            with self.assertRaisesRegex(ValueError, "missing from the installation"):
                official_skills.source()

    def test_unrelated_import_failure_is_not_hidden_by_checkout_fallback(self):
        error = ModuleNotFoundError(name="unrelated_dependency")
        with patch.object(official_skills.resources, "files", side_effect=error):
            with self.assertRaises(ModuleNotFoundError) as raised:
                official_skills.source()
        self.assertIs(raised.exception, error)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO payload fixture requires POSIX")
    def test_nonregular_payload_is_rejected_without_opening_it(self):
        payload = self.root / "payload"
        payload.mkdir()
        fifo = payload / "pipe"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "not regular"):
            official_skills.signature(payload)
        self.assertTrue(fifo.exists())


class OfficialSkills(SetupFixture):
    def setUp(self):
        super().setUp()
        self.require_links()
        self.original = self.root / 'packaged-skill'
        shutil.copytree(official_skills.source(), self.original)
        self.source_patch = patch('agent_env_man.official_skills.source', return_value=self.original)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def target(self):
        return Path(Config(self.config).agents['codex']['skills']) / official_skills.NAME

    def test_setup_links_repeat_and_removes_without_touching_payload(self):
        report = self.setup_cli('--agent', 'codex')
        target = self.target()
        self.assertEqual(target.resolve(), self.original)
        self.assertIn('agent-skill:codex', [entry['integration'] for entry in report['official_skills']])
        self.setup_cli('--agent', 'codex')
        self.assertEqual(target.resolve(), self.original)
        self.run_cli('setup', '--remove-agent', 'codex')
        self.assertFalse(target.is_symlink())
        self.assertTrue((self.original / 'SKILL.md').is_file())
        self.assertFalse(list(target.parent.glob('idk-aem.aem-backup-*')))
        backups = list((Config(self.config).state_dir / 'setup-backups').iterdir())
        self.assertTrue(backups)
        self.assertTrue(all(path.is_symlink() for path in backups))

    def test_refresh_relocates_owned_link_and_keeps_detached_skill(self):
        from agent_env_man.setup import refresh_official

        self.setup_cli('--agent', 'codex')
        target = self.target()
        relocated = self.root / 'new package location'
        shutil.copytree(self.original, relocated)
        config = Config(self.config)
        manager = Manager(config, State(config.state_dir))
        with patch('agent_env_man.official_skills.source', return_value=relocated):
            result = refresh_official(manager, replaced=True)
        self.assertEqual(target.resolve(), relocated)
        self.assertEqual(result['integrations'][0]['action'], 'write')
        record = manager.state.data['items']['setup:skill-codex-idk-aem']
        official_skills.check({'skill': record})
        record['detached'] = True
        manager.state.save()
        with patch('agent_env_man.official_skills.source', side_effect=AssertionError('Detached skill')):
            self.assertEqual(refresh_official(manager, replaced=True), {'integrations': []})
        self.assertEqual(target.resolve(), relocated)

    def test_official_identity_rejects_invalid_records_and_equivalent_aliases(self):
        self.setup_cli('--agent', 'codex')
        record = self.state()['items']['setup:skill-codex-idk-aem']
        for values, message in (({'official_hash': None}, 'malformed'),
                                ({'source': 'relative-source'}, 'absolute')):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, message):
                official_skills.check({'skill': dict(record, **values)})
        target = self.target()
        parent_alias = self.root / 'redirected-parent'
        parent_alias.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'ancestry changed'):
            official_skills.check({'skill': dict(record, target=str(parent_alias / target.name))})
        source_alias = self.root / 'same-source-alias'
        source_alias.symlink_to(self.original, target_is_directory=True)
        target.unlink()
        target.symlink_to(source_alias, target_is_directory=True)
        self.assertTrue(target.samefile(self.original))
        with self.assertRaisesRegex(ValueError, 'link changed'):
            official_skills.check({'skill': record})

    def test_changed_link_and_copy_are_preserved_on_removal(self):
        for replacement in ('link', 'copy'):
            with self.subTest(replacement=replacement):
                self.setup_cli('--agent', 'codex')
                target = self.target()
                target.unlink()
                if replacement == 'link':
                    target.symlink_to(self.original.parent, target_is_directory=True)
                else:
                    target.mkdir()
                    (target / 'user.txt').write_text('keep')
                report = self.run_cli('setup', '--remove-agent', 'codex')
                self.assertIn('preserve', [entry['action'] for entry in report['official_skills']])
                self.assertTrue(target.exists())
                if target.is_symlink():
                    target.unlink()
                else:
                    shutil.rmtree(target)

    def test_local_source_edits_skip_skill_but_complete_setup_and_guard_update(self):
        self.setup_cli('--agent', 'codex')
        target = self.target()
        (self.original / 'extra.txt').write_text('local addition')
        report = self.setup_cli('--shell', 'bash')
        self.assertTrue((self.home / '.bashrc').exists())
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        with self.assertRaisesRegex(ValueError, 'changed locally'):
            official_skills.check(self.state()['items'])
        report = self.run_cli('setup', '--remove-agent', 'codex')
        self.assertTrue(target.is_symlink())
        self.assertIn('preserve', [entry['action'] for entry in report['official_skills']])

    def test_redirected_source_addition_is_preserved_on_removal(self):
        self.setup_cli('--agent', 'codex')
        target = self.target()
        (self.original / 'nested-link').symlink_to(self.home, target_is_directory=True)
        report = self.run_cli('setup', '--remove-agent', 'codex')
        self.assertTrue(target.is_symlink())
        self.assertIn('preserve', [entry['action'] for entry in report['official_skills']])

    def test_unmanaged_collision_preserves_target_and_completes_core_setup(self):
        target = self.home / '.agents/skills' / official_skills.NAME
        target.mkdir(parents=True)
        (target / 'user.txt').write_text('keep')
        report = self.setup_cli('--agent', 'codex', '--shell', 'bash')
        self.assertTrue((self.home / '.codex/hooks.json').exists())
        self.assertTrue((self.home / '.bashrc').exists())
        self.assertTrue(self.config.exists())
        self.assertEqual((target / 'user.txt').read_text(), 'keep')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertEqual(set(Config(self.config).agents), {'codex'})

    def test_skill_root_cannot_discover_manager_backup_storage(self):
        self.config.write_text('version = 1\n[roots]\nskills = ' + json.dumps(str(self.root)) + '\n')
        report = self.setup_cli('--agent', 'codex')
        self.assertTrue((self.home / '.codex/hooks.json').exists())
        self.assertEqual(report['official_skills'][0]['action'], 'failed')

    def test_link_removal_and_recovery_do_not_require_cross_filesystem_rename(self):
        self.setup_cli('--agent', 'codex')
        target = self.target()
        replace = os.replace
        def same_filesystem_only(source, destination):
            if 'setup-backups' in Path(source).parts or 'setup-backups' in Path(destination).parts:
                raise OSError('cross-filesystem rename')
            return replace(source, destination)
        with patch('agent_env_man.manager.os.replace', side_effect=same_filesystem_only):
            self.run_cli('setup', '--remove-agent', 'codex')
        self.assertFalse(target.is_symlink())

    def test_custom_path_preview_and_shell_policy_setup(self):
        custom = self.root / 'custom skills'
        self.config.write_text('version = 1\n[roots]\nskills = ' + json.dumps(str(custom)) + '\n')
        self.setup_cli('--agent', 'codex', '--dry-run')
        self.assertFalse(custom.exists())
        self.setup_cli('--shell', 'bash')
        self.assertFalse(custom.exists())
        self.setup_cli('--agent', 'codex')
        self.assertEqual(self.target().parent, custom)
        before = observation(self.target())
        self.run_cli('setup', '--automation', 'off')
        self.assertEqual(observation(self.target()), before)

    def test_link_capability_failure_does_not_copy(self):
        with patch.object(Path, 'symlink_to', side_effect=OSError('no links')):
            report = self.setup_cli('--agent', 'codex')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertTrue((self.home / '.codex/hooks.json').exists())
        self.assertTrue(self.config.exists())
        self.assertFalse((self.home / '.agents/skills' / official_skills.NAME).exists())
        self.setup_cli('--agent', 'codex')
        self.assertTrue(self.target().is_symlink())

    def test_removal_recovery_restores_link_after_state_commit_failure(self):
        self.setup_cli('--agent', 'codex')
        config = Config(self.config)
        state = State(config.state_dir)
        manager = Manager(config, state)
        plans, _ = official_plans(manager, {}, removing=['codex'])
        save = state.save
        calls = 0
        def fail_once():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('state commit failed')
            return save()
        with patch.object(state, 'save', side_effect=fail_once), self.assertRaises(OSError):
            manager.install(plans[0])
        self.assertTrue(self.target().is_symlink())
        self.assertIsNone(State(config.state_dir).data['pending'])
        self.run_cli('setup', '--remove-agent', 'codex')

    def test_catalog_collision_and_second_machine_do_not_adopt(self):
        self.configure()
        catalog = Path(Config(self.config).catalog_path)
        import tomlkit
        document = tomlkit.parse(catalog.read_text())
        document['skills'][official_skills.NAME] = document['skills']['report']
        catalog.write_text(tomlkit.dumps(document))
        report = self.setup_cli('--agent', 'codex')
        self.assertTrue((self.agent / 'hooks.json').exists())
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        document['skills'].pop(official_skills.NAME)
        catalog.write_text(tomlkit.dumps(document))
        self.setup_cli('--agent', 'codex')
        second = self.root / 'second.toml'
        second.write_text('version = 1\n[roots]\nskills = ' + json.dumps(str(self.target().parent)) + '\n')
        report = self.setup_cli('--agent', 'codex', config=second)
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertTrue(second.exists())

    def test_missing_packaged_skill_does_not_prevent_core_setup_or_preview(self):
        with patch('agent_env_man.official_skills.source', side_effect=ValueError('missing resource')):
            preview = self.setup_cli('--agent', 'codex', '--dry-run')
            self.assertEqual(preview['official_skills'][0]['action'], 'failed')
            self.assertFalse(self.config.exists())
            report = self.setup_cli('--agent', 'codex')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertTrue((self.home / '.codex/hooks.json').exists())

    def test_one_agent_skill_collision_does_not_skip_other_agent(self):
        home = self.home
        class Fake(agents.Codex):
            def defaults(self):
                return {'root': str(home / 'fake-agent'), 'skills': str(home / 'fake-skills')}
        collision = self.home / '.agents/skills/idk-aem'
        collision.mkdir(parents=True)
        (collision / 'user.txt').write_text('keep')
        with patch.dict(agents.PROFILES, {'fake': Fake(name='fake')}):
            report = self.setup_cli('--agent', 'codex', '--agent', 'fake')
            self.assertEqual(set(Config(self.config).agents), {'codex', 'fake'})
        outcomes = {entry['integration']: entry['action'] for entry in report['official_skills']}
        self.assertEqual(outcomes, {'agent-skill:codex': 'failed', 'agent-skill:fake': 'write'})
        self.assertTrue((home / 'fake-skills/idk-aem').is_symlink())
        self.assertTrue((home / 'fake-agent/hooks.json').is_file())
        self.assertTrue((home / '.codex/hooks.json').is_file())

    def test_optional_removal_failure_keeps_core_removal_and_allows_retry(self):
        self.setup_cli('--agent', 'codex')
        target = self.target()
        with patch.object(Path, 'symlink_to', side_effect=OSError('backup link denied')):
            report = self.run_cli('setup', '--remove-agent', 'codex')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertEqual(Config(self.config).agents, {})
        self.assertTrue(target.is_symlink())
        self.assertIsNone(self.state()['pending'])
        self.run_cli('setup', '--remove-agent', 'codex')
        self.assertFalse(target.is_symlink())

    def test_optional_state_commit_failure_rolls_back_and_preserves_core_success(self):
        save = State.save
        failed = False
        def fail_once(state):
            nonlocal failed
            if not failed and state.data['pending'] is None and any(record.get('official_skill') for record in state.data['items'].values()):
                failed = True
                raise OSError('optional state commit failed')
            return save(state)
        with patch.object(State, 'save', new=fail_once):
            report = self.setup_cli('--agent', 'codex', '--shell', 'bash')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        self.assertTrue((self.home / '.bashrc').exists())
        self.assertTrue((self.home / '.codex/hooks.json').exists())
        self.assertIsNone(self.state()['pending'])
        self.assertNotIn('setup:skill-codex-idk-aem', self.state()['items'])
        self.assertFalse(self.target().is_symlink())
        self.setup_cli('--agent', 'codex')
        self.assertTrue(self.target().is_symlink())

    def test_unresolved_optional_recovery_is_not_hidden_as_success(self):
        save = State.save
        failed = False
        def fail_commit_and_recovery(state):
            nonlocal failed
            if state.data['pending'] is None and any(record.get('official_skill') for record in state.data['items'].values()):
                failed = True
            if failed:
                raise OSError('state storage unavailable')
            return save(state)
        with patch.object(State, 'save', new=fail_commit_and_recovery):
            self.setup_cli('--agent', 'codex', code=1)
        self.assertTrue((self.home / '.codex/hooks.json').exists())
        self.assertTrue(self.config.exists())
        self.assertIsNotNone(self.state()['pending'])
        self.run_cli('recover')
        self.setup_cli('--agent', 'codex')

    def test_internal_refresh_requires_worker_token(self):
        self.setup_cli('--agent', 'codex')
        self.run_cli('_self-skill-refresh', '--token', 'invalid', '--result-file', 'self-update.json', code=1)

    def test_setup_relocates_package_source_after_version_change(self):
        self.setup_cli('--agent', 'codex')
        newer = self.root / 'newer-package'
        shutil.copytree(self.original, newer)
        (newer / 'SKILL.md').write_text((newer / 'SKILL.md').read_text() + '\nNew release guidance.\n')
        with patch('agent_env_man.official_skills.source', return_value=newer), \
                patch('importlib.metadata.version', return_value='0.5.0'):
            self.setup_cli('--agent', 'codex')
        self.assertEqual(self.target().resolve(), newer)


class OfficialUpdate(SetupFixture):
    register = test_self_update.SelfUpdate.register
    release = test_self_update.SelfUpdate.release
    finish_worker = test_self_update.SelfUpdate.finish_worker

    @unittest.skipIf(os.name == 'nt', 'Fake installers use POSIX shebangs')
    def test_uninstalled_skill_does_not_become_an_update_prerequisite(self):
        self.require_links()
        self.register()
        target = self.home / '.agents/skills/idk-aem'
        target.mkdir(parents=True)
        (target / 'user.txt').write_text('keep')
        report = self.setup_cli('--agent', 'codex')
        self.assertEqual(report['official_skills'][0]['action'], 'failed')
        config = Config(self.config)
        self.release('0.4.1')
        marker = self.root / 'installed'
        self.uv.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list": print("agent-env-man v0.4.0")\n'
                           'else: Path(' + repr(str(marker)) + ').write_text("installed")\n')
        self.uv.chmod(0o755)
        self.run_cli('self', 'update')
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'updated', result)
        self.assertTrue(marker.exists())
        self.assertEqual((target / 'user.txt').read_text(), 'keep')
        self.assertNotIn('stages', result)

    @unittest.skipIf(os.name == 'nt', 'Fake CLI uses POSIX shebangs')
    def test_full_without_tool_update_stops_on_edited_official_source(self):
        self.require_links()
        self.register(mode='off')
        payload = self.root / 'edited-package'
        shutil.copytree(official_skills.source(), payload)
        with patch('agent_env_man.official_skills.source', return_value=payload):
            self.setup_cli('--agent', 'codex', '--automation', 'full', '--automation-trigger', 'interval')
        (payload / 'extra.txt').write_text('preserve')
        self.bin.mkdir()
        executable = self.bin / 'aem'
        executable.write_text('#!' + sys.executable + '\nfrom agent_env_man.cli import main\nraise SystemExit(main())\n')
        executable.chmod(0o755)
        config = Config(self.config)
        automation.schedule(config, 'interval')
        attempt = self_update.read_result(automation.result_path(config))
        request_path = config.state_dir / 'self-update-worker' / attempt['token'] / 'request.json'
        request = json.loads(request_path.read_text())
        request['parent_pid'] = 0
        self_update.write_json(request_path, request)
        child = self_update._children[-1]
        self_update.close_workers()
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(automation.result_path(config))
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['stages']['tool']['status'], 'disabled')
        self.assertEqual(result['stages']['official_skill']['status'], 'failed')
        self.assertNotIn('catalog', result['stages'])
        self.assertEqual((payload / 'extra.txt').read_text(), 'preserve')

    @unittest.skipIf(os.name == 'nt', 'Fake installers use POSIX shebangs')
    def test_worker_validates_edits_and_refreshes_relocated_link(self):
        self.require_links()
        config = self.register()
        payload = self.root / 'previous-package'
        shutil.copytree(official_skills.source(), payload)
        # Match the fake uv installation rather than the test runner's package.
        with patch('agent_env_man.official_skills.source', return_value=payload), \
                patch('importlib.metadata.version', return_value='0.4.0'):
            self.setup_cli('--agent', 'codex')
        self.release('0.4.1')
        self.bin.mkdir()
        executable = self.bin / 'aem'
        progress = self.root / 'progress-status'
        executable.write_text('#!' + sys.executable + '\nimport json\nfrom pathlib import Path\n'
                              'Path(' + repr(str(progress)) + ').write_text(json.loads(Path(' +
                              repr(str(self_update.result_path(config))) + ').read_text())["status"])\n'
                              'from agent_env_man.cli import main\nraise SystemExit(main())\n')
        executable.chmod(0o755)
        marker = self.root / 'installed'
        self.uv.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list": print("agent-env-man v0.4.0")\n'
                           'else: Path(' + repr(str(marker)) + ').write_text("installed")\n')
        self.uv.chmod(0o755)
        (payload / 'extra.txt').write_text('user edit')
        self.run_cli('self', 'update')
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'failed')
        self.assertFalse(marker.exists())
        (payload / 'extra.txt').unlink()
        self.run_cli('self', 'update')
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'updated', result)
        self.assertEqual(result['stages']['official_skill']['status'], 'completed')
        self.assertEqual(progress.read_text(), 'queued')
        target = Path(Config(self.config).agents['codex']['skills']) / official_skills.NAME
        self.assertEqual(target.resolve(), official_skills.source().resolve())
