"""Opted-in instruction bundles share storage without sharing agent hooks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

import tomlkit

from agent_env_man import automation
from agent_env_man.catalog_schema import validate
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State
from test_instructions import InstructionFixture


class SharedInstructions(InstructionFixture):
    def configure_shared(self, *, agents=('codex', 'claude'), mode='copy', shared=True, git=False):
        self.configure(git=git)
        document = tomlkit.parse(self.catalog.read_text())
        instruction = document['instructions']['personal']
        del instruction['install']['entry']
        instruction['install']['bundle'].update(mode=mode, shared=shared)
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        machine = tomlkit.parse(self.config.read_text())
        machine['agents'] = {name: {'root': str(self.root / name), 'skills': str(self.root / name / 'skills')}
                             for name in agents}
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        return self.rules / 'personal'

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def locations(self, agent):
        output = self.manager().hook_context('personal', agent)
        if isinstance(output, dict):
            output = output['hookSpecificOutput']['additionalContext']
        return json.loads(output.splitlines()[1])

    def test_filtered_install_one_copy_and_one_collection(self):
        installed = self.configure_shared()
        report = self.run_cli('apply', '--item', 'personal:entry', '--agent', 'claude', '--dry-run')
        self.assertEqual({r['item'] for r in report},
                         {'personal:bundle', 'personal:entry@claude', 'personal:hook@claude'})
        self.assertFalse(installed.exists())
        self.run_cli('apply', '--item', 'personal:entry', '--agent', 'claude')
        self.assertFalse((self.root / 'codex/AGENTS.md').exists())
        self.run_cli('apply')
        self.assertFalse((self.rules / 'personal@claude').exists())
        for agent, filename in (('codex', 'AGENTS.md'), ('claude', 'CLAUDE.md')):
            self.assertEqual((self.root / agent / filename).resolve(), installed / 'start.md')
            self.assertEqual(self.locations(agent)['root'], str(installed))
            found = self.run_cli('locate', 'personal', '--agent', agent)
            self.assertEqual(found['root'], str(installed))
        (installed / 'start.md').write_text('shared edit', encoding='utf-8')
        report = self.run_cli('publish', 'personal', '--from-copy')[0]
        self.assertEqual(len(report['collection']), 1)
        self.assertEqual((self.bundle / 'start.md').read_text(), 'shared edit')
        self.run_cli('apply')
        shutil.rmtree(self.external)
        self.catalog.unlink()
        for agent in ('codex', 'claude'):
            self.assertEqual(self.run_cli('locate', 'personal', '--agent', agent)['root'], str(installed))
            self.assertEqual(self.locations(agent)['root'], str(installed))

    def test_named_agents_without_codex_and_bundle_only_install(self):
        installed = self.configure_shared(agents=('claude-lab', 'codex-work'))
        report = self.run_cli('apply', '--item', 'personal:bundle', '--agent', 'claude-lab')
        self.assertEqual([r['item'] for r in report], ['personal:bundle'])
        self.assertEqual(self.run_cli('locate', 'personal', '--agent', 'claude-lab')['root'], str(installed))
        self.run_cli('apply', '--item', 'personal:entry@codex-work')
        self.assertEqual(self.locations('codex-work')['root'], str(installed))
        self.run_cli('apply', '--item', 'personal:hook@claude-lab')
        self.assertEqual(self.locations('claude-lab')['root'], str(installed))
        self.run_cli('locate', 'personal', '--agent', 'claude', code=1)

    def test_shared_links_keep_reading_tree_after_bundle_detach(self):
        installed = self.configure_shared(mode='link')
        self.run_cli('apply')
        self.assertTrue(installed.is_symlink())
        self.assertEqual(self.locations('claude')['root'], str(self.bundle))
        self.run_cli('detach', 'personal:bundle')
        shutil.rmtree(self.external)
        self.catalog.unlink()
        for agent in ('codex', 'claude'):
            self.assertEqual(self.locations(agent)['root'], str(installed))

    def test_shared_detach_is_all_consumers_and_entries_stay_independent(self):
        installed = self.configure_shared()
        self.run_cli('apply')
        before = (installed / 'start.md').read_bytes()
        error = self.run_cli('detach', 'personal:bundle', '--agent', 'claude', code=1)
        self.assertIn('shared target', str(error))
        self.run_cli('detach', 'personal:entry', '--agent', 'claude')
        self.assertFalse((self.root / 'claude/CLAUDE.md').is_symlink())
        self.assertTrue((self.root / 'codex/AGENTS.md').is_symlink())
        self.assertFalse(self.manager().state.data['items']['personal:bundle']['detached'])
        self.run_cli('detach', 'personal:bundle')
        self.assertEqual((installed / 'start.md').read_bytes(), before)
        self.assertEqual(self.locations('codex')['root'], str(installed))
        self.run_cli('publish', 'personal', '--from-copy', code=1)

    def test_existing_and_implicit_replace_do_not_overwrite_shared_edits(self):
        installed = self.configure_shared()
        self.run_cli('apply')
        (installed / 'start.md').write_text('local edit', encoding='utf-8')
        (self.bundle / 'start.md').write_text('source edit', encoding='utf-8')
        self.run_cli('apply', '--item', 'personal:entry@claude', '--replace', code=1)
        self.assertEqual((installed / 'start.md').read_text(), 'local edit')
        self.run_cli('apply', '--item', 'personal:bundle', '--replace')
        self.assertEqual((installed / 'start.md').read_text(), 'source edit')

    def test_shared_requires_boolean_and_false_preserves_separate_copies(self):
        self.configure_shared(shared=False)
        document = tomlkit.parse(self.catalog.read_text()).unwrap()
        for value in (1, 'true', [], {}):
            candidate = deepcopy(document)
            candidate['instructions']['personal']['install']['bundle']['shared'] = value
            with self.subTest(value=value), self.assertRaisesRegex(Error, 'Boolean'):
                validate(candidate)
        self.run_cli('apply')
        roots = [self.locations(agent)['root'] for agent in ('codex', 'claude')]
        self.assertNotEqual(*roots)
        del document['instructions']['personal']['install']['bundle']['shared']
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.run_cli('apply')
        self.assertEqual(roots, [self.locations(agent)['root'] for agent in ('codex', 'claude')])

    def test_transition_requires_detach_and_preserves_separate_copy_edits(self):
        installed = self.configure_shared(shared=False)
        self.run_cli('apply')
        other = self.rules / 'personal@claude'
        (other / 'start.md').write_text('preserved claude edit', encoding='utf-8')
        document = tomlkit.parse(self.catalog.read_text())
        document['instructions']['personal']['install']['bundle']['shared'] = True
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        error = self.run_cli('apply', code=1)
        self.assertIn('detach', str(error))
        self.run_cli('publish', 'personal', '--from-copy', code=1)
        self.run_cli('detach', 'personal:bundle', 'personal:entry')
        self.run_cli('apply', '--item', 'personal:bundle', '--reattach', '--adopt')
        self.run_cli('apply', '--item', 'personal:entry', '--reattach', '--replace')
        self.assertEqual((other / 'start.md').read_text(), 'preserved claude edit')
        self.assertEqual(self.locations('claude')['root'], str(installed))
        document['instructions']['personal']['install']['bundle']['shared'] = False
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.run_cli('apply', code=1)
        self.run_cli('publish', 'personal', '--from-copy', code=1)

    def test_full_automation_skips_shared_group_after_partial_detach(self):
        installed = self.configure_shared()
        self.run_cli('apply')
        self.run_cli('detach', 'personal:entry', '--agent', 'claude')
        before = (installed / 'start.md').read_bytes()
        (self.bundle / 'start.md').write_text('incoming', encoding='utf-8')
        document = tomlkit.parse(self.catalog.read_text())
        document['skills']['report']['update'] = {'trigger': []}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        with patch.object(Manager, 'prepare_skills', side_effect=AssertionError('Detached group prepared')):
            report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['status'], 'skipped')
        self.assertEqual((installed / 'start.md').read_bytes(), before)

    def check_transition_with_orphaned_consumer(self, shared):
        installed = self.configure_shared(shared=shared)
        self.run_cli('apply')
        orphan, remaining = ('claude', 'codex') if shared else ('codex', 'claude')
        machine = tomlkit.parse(self.config.read_text())
        del machine['agents'][orphan]
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.run_cli('detach', 'personal:bundle')
        self.run_cli('detach', 'personal:entry', '--agent', remaining)
        document = tomlkit.parse(self.catalog.read_text())
        document['instructions']['personal']['install']['bundle']['shared'] = not shared
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        before = deepcopy(self.manager().state.data)
        locations = self.locations(orphan)
        contents = (installed / 'start.md').read_bytes()
        for preview in (('--dry-run',), ()):
            with self.subTest(preview=preview):
                error = self.run_cli('apply', '--item', 'personal:bundle', '--reattach', '--adopt',
                                     *preview, code=1)
                self.assertIn('detach', str(error))
                self.assertEqual(self.manager().state.data, before)
                self.assertEqual(self.locations(orphan), locations)
                self.assertEqual((installed / 'start.md').read_bytes(), contents)
        self.run_cli('detach', 'personal:entry', '--agent', orphan)
        self.run_cli('apply', '--item', 'personal:bundle', '--reattach', '--adopt')
        self.assertEqual(bool(self.manager().state.data['items']['personal:bundle'].get('shared_bundle')),
                         not shared)
        self.assertEqual(Path(locations['global_entry']).read_bytes(), contents)

    def test_shared_to_separate_requires_detaching_orphaned_consumer(self):
        self.check_transition_with_orphaned_consumer(True)

    def test_separate_to_shared_requires_detaching_orphaned_consumer(self):
        self.check_transition_with_orphaned_consumer(False)

    def test_saved_consumer_survives_machine_agent_removal(self):
        installed = self.configure_shared()
        self.run_cli('apply')
        machine = tomlkit.parse(self.config.read_text())
        del machine['agents']['claude']
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.run_cli('apply')
        self.catalog.unlink()
        self.assertEqual(self.locations('claude')['root'], str(installed))

    def test_broken_shared_bundle_never_falls_back_to_source(self):
        installed = self.configure_shared()
        self.run_cli('apply')
        (installed / 'start.md').unlink()
        self.run_cli('locate', 'personal', '--agent', 'claude', code=1)
        self.assertEqual(self.run_cli('locate', 'personal', '--source', '--agent', 'claude')['root'], str(self.bundle))
        (installed / 'start.md').symlink_to(self.bundle / 'start.md')
        self.run_cli('locate', 'personal', '--agent', 'claude', code=1)
        shutil.rmtree(installed)
        installed.symlink_to(self.bundle, target_is_directory=True)
        self.run_cli('locate', 'personal', '--agent', 'claude', code=1)
        manager = self.manager()
        del manager.state.data['items']['personal:bundle']
        manager.state.save()
        self.assertIn('shared bundle', str(self.run_cli('locate', 'personal', '--agent', 'claude', code=1)))

    def test_failed_second_entry_preserves_bundle_and_first_consumer(self):
        installed = self.configure_shared()
        real = os.replace
        def fail_entry(source, destination):
            if Path(destination) == self.root / 'claude/CLAUDE.md' and Path(source).name.startswith('.aem-stage-'):
                raise OSError('injected second consumer failure')
            return real(source, destination)
        with patch('agent_env_man.manager.os.replace', side_effect=fail_entry):
            self.run_cli('apply', '--item', 'personal:entry', code=1)
        self.assertEqual(self.locations('codex')['root'], str(installed))
        self.assertFalse((self.root / 'claude/CLAUDE.md').exists())
        self.assertIsNone(self.manager().state.data['pending'])
        self.run_cli('recover')
        self.run_cli('apply', '--item', 'personal:entry@claude')
        self.assertEqual(self.locations('claude')['root'], str(installed))

    def test_shared_git_copy_update_and_publication(self):
        installed = self.configure_shared(git=True)
        self.git(self.external, 'config', 'receive.denyCurrentBranch', 'updateInstead')
        self.run_cli('apply')
        original = (installed / 'start.md').read_text()
        (self.bundle / 'start.md').write_text('remote change', encoding='utf-8')
        self.commit(self.external)
        self.run_cli('update', 'personal')
        self.assertEqual((installed / 'start.md').read_text(), original)
        self.run_cli('apply', '--item', 'personal:entry@claude')
        self.assertEqual((self.root / 'codex/AGENTS.md').read_text(), 'remote change')
        (installed / 'start.md').write_text('collected once', encoding='utf-8')
        checkout = Path(self.run_cli('locate', 'personal', '--source')['root'])
        self.git(checkout, 'config', 'user.name', 'Test')
        self.git(checkout, 'config', 'user.email', 'test@example.invalid')
        report = self.run_cli('publish', 'personal', '--from-copy', '-m', 'Shared instruction edit')[0]
        self.assertEqual(len(report['collection']), 1)
        self.assertEqual((self.bundle / 'start.md').read_text(), 'collected once')
        self.assertFalse((installed / '.git').exists())

    def test_explicit_entry_root_remains_single_destination(self):
        installed = self.configure_shared()
        document = tomlkit.parse(self.catalog.read_text())
        document['instructions']['personal']['install']['entry'] = {'root': 'aem-agent-claude'}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        report = self.run_cli('apply', '--item', 'personal:entry')
        self.assertEqual({r['item'] for r in report},
                         {'personal:bundle', 'personal:entry@claude', 'personal:hook@claude'})
        self.assertEqual(self.locations('claude')['root'], str(installed))
        self.assertFalse((self.root / 'codex/AGENTS.md').exists())
