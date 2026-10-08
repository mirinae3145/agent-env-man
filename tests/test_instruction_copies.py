"""Managed instruction copies retain an offline reading tree and explicit publication."""
from pathlib import Path
import os
import shutil
from unittest.mock import patch

import tomlkit

from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State
from test_instructions import InstructionFixture


class InstructionCopies(InstructionFixture):
    def configure_copy(self, **kwargs):
        self.configure(**kwargs)
        doc = tomlkit.parse(self.catalog.read_text())
        doc['instructions']['personal']['install']['bundle']['mode'] = 'copy'
        self.catalog.write_text(tomlkit.dumps(doc))
        return self.rules / 'personal'

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def test_copy_offline_entry_hook_and_detach(self):
        installed = self.configure_copy(subdir='nested/rules')
        self.run_cli('apply', '--dry-run')
        self.assertFalse(installed.exists())
        self.run_cli('apply')
        self.run_cli('apply')
        self.assertFalse(installed.is_symlink())
        self.assertEqual((self.agent / 'AGENTS.md').resolve(), installed / 'start.md')
        self.assertEqual(self.run_cli('locate', 'personal', '--source')['root'], str(self.bundle))
        shutil.rmtree(self.external)
        self.catalog.unlink()
        self.assertEqual(self.run_cli('locate', 'personal')['root'], str(installed))
        context = str(self.manager().hook_context('personal'))
        self.assertIn(str(installed), context)
        self.assertNotIn(str(self.external), context)
        self.run_cli('detach', 'personal:bundle')
        self.assertIn(str(installed), str(self.manager().hook_context('personal')))
        self.run_cli('detach', 'personal:entry')
        self.assertTrue((self.agent / 'AGENTS.md').is_file())

    def test_copy_refresh_and_conflict_preservation(self):
        installed = self.configure_copy()
        self.run_cli('apply')
        incoming = self.bundle / 'start.md'
        incoming.write_text('source revision')
        self.assertNotEqual((installed / 'start.md').read_text(), 'source revision')
        self.run_cli('apply')
        (installed / 'start.md').write_text('local edit')
        self.run_cli('apply', code=1)
        self.assertEqual((installed / 'start.md').read_text(), 'local edit')
        self.run_cli('apply', '--item', 'personal:entry', '--replace', code=1)
        self.run_cli('apply', '--item', 'personal:bundle', '--replace')
        self.assertEqual((installed / 'start.md').read_text(), 'source revision')

    def test_machine_override_and_link_to_copy_transition(self):
        self.configure()
        self.run_cli('apply')
        doc = tomlkit.parse(self.config.read_text())
        doc['modes'] = {'personal': 'copy'}
        self.config.write_text(tomlkit.dumps(doc))
        self.run_cli('apply', code=1)
        self.run_cli('detach', 'personal:bundle', 'personal:entry')
        self.run_cli('apply', '--item', 'personal:bundle', '--reattach', '--adopt')
        self.run_cli('apply', '--item', 'personal:entry', '--reattach', '--replace')
        self.assertFalse((self.rules / 'personal').is_symlink())
        self.assertEqual((self.agent / 'AGENTS.md').resolve(), self.rules / 'personal/start.md')

    def test_external_publish_preview_conflict_and_resolve(self):
        installed = self.configure_copy()
        self.run_cli('apply')
        copied, source = installed / 'start.md', self.bundle / 'start.md'
        baseline = source.read_bytes()
        copied.write_text('copy edit')
        self.run_cli('publish', 'personal', '--from-copy', '--dry-run')
        self.assertEqual(source.read_bytes(), baseline)
        self.run_cli('publish', 'personal', '--from-copy')
        self.assertEqual(source.read_text(), 'copy edit')
        source.write_text('source edit')
        self.run_cli('publish', 'personal', '--from-copy')
        self.assertEqual(source.read_text(), 'source edit')
        copied.write_text('competing edit')
        self.run_cli('publish', 'personal', '--from-copy', code=1)
        self.assertEqual(source.read_text(), 'source edit')
        source.write_text('competing edit')
        self.run_cli('publish', 'personal', '--from-copy')
        self.run_cli('apply')
        self.run_cli('detach', 'personal:bundle')
        self.run_cli('publish', 'personal', '--from-copy', code=1)

    def test_missing_or_redirected_entry_and_bundle_are_rejected(self):
        installed = self.configure_copy()
        self.run_cli('apply')
        (installed / 'start.md').unlink()
        self.run_cli('publish', 'personal', '--from-copy', code=1)
        self.run_cli('locate', 'personal', code=1)
        (installed / 'start.md').symlink_to(self.bundle / 'start.md')
        self.run_cli('locate', 'personal', code=1)
        self.run_cli('publish', 'personal', '--from-copy', code=1)
        shutil.rmtree(installed)
        installed.symlink_to(self.bundle, target_is_directory=True)
        self.run_cli('locate', 'personal', code=1)

    def test_git_copy_updates_only_on_apply_and_publishes(self):
        installed = self.configure_copy(git=True)
        self.git(self.external, 'config', 'receive.denyCurrentBranch', 'updateInstead')
        self.run_cli('apply')
        original = (installed / 'start.md').read_text()
        (self.bundle / 'start.md').write_text('remote change')
        self.commit(self.external)
        self.run_cli('update', 'personal')
        self.assertEqual((installed / 'start.md').read_text(), original)
        self.run_cli('apply')
        (installed / 'start.md').write_text('collected')
        checkout = Path(self.run_cli('locate', 'personal', '--source')['root'])
        self.git(checkout, 'config', 'user.name', 'Test')
        self.git(checkout, 'config', 'user.email', 'test@example.invalid')
        self.run_cli('publish', 'personal', '--from-copy', '-m', 'Collect instruction edits')
        self.assertEqual((self.bundle / 'start.md').read_text(), 'collected')
        self.assertFalse((installed / '.git').exists())

    def test_two_agents_offline_and_competing_publication(self):
        self.configure_copy()
        doc = tomlkit.parse(self.catalog.read_text())
        del doc['instructions']['personal']['install']['entry']
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.config.read_text())
        machine['agents'] = {name: {'root': str(self.root / name), 'skills': str(self.root / name / 'skills')}
                             for name in ('codex', 'claude')}
        self.config.write_text(tomlkit.dumps(machine))
        self.run_cli('apply')
        for name in ('codex', 'claude'):
            manager = self.manager()
            found = manager.locate_instruction('personal', name)
            self.assertIn(found['root'], str(manager.hook_context('personal', name)))
            (Path(found['root']) / 'start.md').write_text(name)
        self.run_cli('publish', 'personal', '--from-copy', code=1)
        self.assertNotIn((self.bundle / 'start.md').read_text(), ('codex', 'claude'))
        shutil.rmtree(self.external)
        for name in ('codex', 'claude'):
            self.manager().hook_context('personal', name)

    def test_failed_entry_install_preserves_completed_bundle_and_retry(self):
        installed = self.configure_copy()
        real = os.replace
        def fail_entry(src, dst):
            if Path(dst) == self.agent / 'AGENTS.md' and Path(src).name.startswith('.aem-stage-'):
                raise OSError('injected entry replacement failure')
            return real(src, dst)
        with patch('agent_env_man.manager.os.replace', side_effect=fail_entry):
            self.run_cli('apply', code=1)
        self.assertTrue((installed / 'start.md').is_file())
        self.assertIsNone(self.manager().state.data['pending'])
        self.run_cli('apply')
        self.assertEqual((self.agent / 'AGENTS.md').resolve(), installed / 'start.md')

    def test_unavailable_link_capability_does_not_copy_entry(self):
        with patch.object(self, 'require_links'):
            installed = self.configure_copy()
        with patch.object(Path, 'symlink_to', side_effect=OSError('no link privilege')):
            self.run_cli('apply', '--item', 'personal:entry', code=1)
        self.assertFalse((self.agent / 'AGENTS.md').exists())
        self.assertTrue(installed.is_dir())
