"""Instruction and catalog copies remain independent through offline use and publication."""
from pathlib import Path
import unittest

import tomlkit

from agent_env_man.automation import full_content
from agent_env_man.manager import Manager
from agent_env_man.model import Config
from agent_env_man.storage import State
import test_local_catalog_copies as catalog_tests


class ManagedCopies(unittest.TestCase):
    setUp = catalog_tests.LocalCatalogCopies.setUp
    cli = catalog_tests.LocalCatalogCopies.cli
    state = catalog_tests.LocalCatalogCopies.state

    def configure(self):
        probe = self.root / 'probe'
        try:
            probe.symlink_to(self.source)
        except OSError:
            self.skipTest('Symbolic link capability unavailable')
        probe.unlink()
        self.rules = self.root / 'synced/rules'
        (self.rules / 'guides').mkdir(parents=True)
        (self.rules / 'entry.md').write_text('Read guides/development.md')
        (self.rules / 'guides/development.md').write_text('Initial guidance')
        doc = {'version': 2, 'sources': {'docs': {'type': 'external'}},
               'instructions': {'personal': {'source': 'docs', 'entry': 'entry.md',
                                             'install': {'bundle': {'mode': 'copy'},
                                                         'entry': {'root': 'agent'}}}}}
        self.source.write_text(tomlkit.dumps(doc))
        self.cli('bootstrap', self.source, '--catalog-copy', '--external', f'docs={self.rules}',
                 '--root', f'agent={self.root / "agent"}', '--root', f'skills={self.root / "skills"}',
                 '--root', f'home={self.root / "home"}')
        self.cli('apply')
        self.installed = self.root / 'machine.toml.bundles/personal'
        self.entry = self.root / 'agent/AGENTS.md'

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def test_both_sources_offline_then_independent_round_trips(self):
        self.configure()
        offline = self.root / 'offline'
        (self.root / 'synced').rename(offline)
        self.assertEqual(self.cli('catalog', 'status')['status'], 'ready')
        self.assertEqual(self.cli('locate', 'personal')['root'], str(self.installed))
        self.assertEqual(self.entry.read_text(), 'Read guides/development.md')
        self.assertIn(str(self.installed), str(self.manager().hook_context('personal')))
        self.assertEqual((self.installed / 'guides/development.md').read_text(), 'Initial guidance')
        offline.rename(self.root / 'synced')
        self.copy.write_text(self.copy.read_text() + '\n# edited catalog\n')
        (self.installed / 'guides/development.md').write_text('Edited instruction')
        catalog_before = self.copy.read_bytes(), self.source.read_bytes(), self.state()['catalog_copy']
        self.cli('publish', 'personal', '--from-copy')
        self.assertEqual((self.rules / 'guides/development.md').read_text(), 'Edited instruction')
        self.assertEqual((self.copy.read_bytes(), self.source.read_bytes(), self.state()['catalog_copy']), catalog_before)
        instruction_before = self.state()['items']
        self.cli('catalog', 'publish', '--from-copy')
        self.assertEqual(self.copy.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.state()['items'], instruction_before)
        self.source.write_text(self.source.read_text() + '# incoming catalog\n')
        self.cli('catalog', 'update')
        self.assertEqual(self.state()['items'], instruction_before)
        (self.rules / 'guides/development.md').write_text('Incoming instruction')
        baseline = self.state()['catalog_copy']
        self.cli('apply')
        self.assertEqual((self.installed / 'guides/development.md').read_text(), 'Incoming instruction')
        self.assertEqual(self.state()['catalog_copy'], baseline)

    def test_catalog_update_rejects_instruction_reconfiguration(self):
        self.configure()
        doc = tomlkit.parse(self.source.read_text())
        doc['instructions']['personal']['install']['bundle']['mode'] = 'link'
        self.source.write_text(tomlkit.dumps(doc))
        before = self.copy.read_bytes(), self.state()
        self.cli('catalog', 'update', code=1)
        self.assertEqual((self.copy.read_bytes(), self.state()), before)
        self.assertFalse(self.installed.is_symlink())
        self.assertEqual(self.entry.resolve(), self.installed / 'entry.md')

    def test_full_content_applies_instruction_copy_without_refreshing_catalog(self):
        self.configure()
        self.source.write_text('invalid external catalog = [')
        (self.rules / 'guides/development.md').write_text('Full apply input')
        copied_catalog, baseline = self.copy.read_bytes(), self.state()['catalog_copy']
        report, failed = full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual((self.installed / 'guides/development.md').read_text(), 'Full apply input')
        self.assertEqual((self.copy.read_bytes(), self.state()['catalog_copy']), (copied_catalog, baseline))
