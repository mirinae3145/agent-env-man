"""Named source selection preserves item scope and installation boundaries."""

import json
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.git_source import Git
import test_publish as publication_tests
import test_settings as settings_tests


class SourceSelectors(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli

    def save(self):
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')

    def test_named_source_lookup_is_offline_and_does_not_require_payloads(self):
        (self.checkout / 'skill/SKILL.md').unlink()
        self.remote.rename(self.root / 'offline.git')
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        with patch.object(Git, 'fetch', side_effect=AssertionError('lookup fetched')):
            for name in ('shared', 'source:shared'):
                for option in ('--source', '--repo'):
                    with self.subTest(name=name, option=option):
                        report = self.cli('locate', name, option)
                        self.assertEqual(report['root'], str(self.checkout))
                        self.assertEqual(report['entry'], str(self.checkout))
                        self.assertEqual(report['members'], ['one', 'personal', 'two'])
        self.assertEqual(state.read_bytes(), before)
        self.assertIn('unknown', self.cli('locate', 'shared', code=1))
        self.assertIn('Unknown catalog source', self.cli('locate', 'source:missing', '--repo', code=1))

    def test_item_names_take_precedence_and_explicit_sources_disambiguate(self):
        self.document['sources']['one'] = {'type': 'git', 'repository': str(self.remote), 'branch': 'main'}
        self.document['skills']['sibling'] = {'source': 'one', 'subdir': 'skill'}
        self.save()
        other = self.checkout.parent / 'one'
        self.git(self.root, 'clone', self.remote, other)
        self.assertEqual(self.cli('locate', 'one', '--source')['root'], str(self.checkout / 'skill'))
        self.assertEqual(self.cli('locate', 'one', '--repo')['root'], str(self.checkout))
        self.assertEqual(self.cli('locate', 'source:one', '--source')['root'], str(other))
        self.assertEqual(self.cli('locate', 'source:one', '--repo')['members'], ['sibling'])
        self.assertEqual([r['source'] for r in self.cli('update', 'one')], ['one'])
        self.assertEqual([r['source'] for r in self.cli('update', 'source:one')], ['sibling'])

    def test_update_expands_source_and_deduplicates_mixed_selectors(self):
        (self.seed / 'skill/SKILL.md').write_text('# Incoming\n', encoding='utf-8')
        self.commit(self.seed)
        self.git(self.seed, 'push', 'origin', 'main')
        original = Git.fetch
        with patch.object(Git, 'fetch', autospec=True, side_effect=original) as fetch:
            reports = self.cli('update', 'shared', 'source:shared', 'one')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual([r['source'] for r in reports], ['one', 'two', 'personal'])
        self.assertTrue(all(r['status'] == 'updated' for r in reports))
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_text(), '# Incoming\n')
        state = json.loads((self.root / 'machine.toml.state/state.json').read_text())
        self.assertFalse(state['items'])

    def test_invalid_selector_stops_all_updates_before_fetch(self):
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        with patch.object(Git, 'fetch', side_effect=AssertionError('invalid selection fetched')):
            self.assertIn('Unknown catalog source', self.cli('update', 'shared', 'source:missing', code=1))
            self.cli('update', 'shared', 'missing', code=1)
            self.cli('update', 'source:', code=1)
        self.assertEqual(state.read_bytes(), before)

    def test_named_source_requires_consistent_recorded_default_branch(self):
        state = self.root / 'machine.toml.state/state.json'
        data = json.loads(state.read_text())
        for record in data['sources'].values():
            record.pop('branch', None)
        state.write_text(json.dumps(data), encoding='utf-8')
        self.assertIn('bootstrap', self.cli('locate', 'shared', '--repo', code=1))
        data['sources']['one']['branch'] = 'main'
        data['sources']['two']['branch'] = 'other'
        state.write_text(json.dumps(data), encoding='utf-8')
        self.assertIn('conflicting', self.cli('locate', 'shared', '--source', code=1))
        self.assertIn('conflicting', self.cli('update', 'shared', code=1))

    def test_unconsumed_source_is_not_implicitly_updated(self):
        self.document['sources']['unused'] = {'type': 'git', 'repository': str(self.remote), 'branch': 'main'}
        self.save()
        other = self.checkout.parent / 'unused'
        self.git(self.root, 'clone', self.remote, other)
        report = self.cli('locate', 'unused', '--repo')
        self.assertEqual(report['root'], str(other))
        self.assertEqual(report['members'], [])
        self.assertEqual([r['source'] for r in self.cli('update')], ['one', 'two', 'personal'])
        self.assertEqual(self.cli('update', 'unused'), [{'source': 'source:unused', 'status': 'updated'}])

    def test_other_commands_do_not_expand_source_names(self):
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        for args in (('publish', 'shared', '--dry-run'), ('apply', '--item', 'shared', '--dry-run'),
                     ('detach', 'shared', '--dry-run'), ('bootstrap', '--item', 'shared'),
                     ('export', 'shared', '--dry-run'), ('hooks', 'remove', 'shared', '--dry-run'),
                     ('locate', 'source:shared'), ('locate', 'shared', '--target')):
            with self.subTest(args=args):
                self.cli(*args, code=1)
                self.assertEqual(state.read_bytes(), before)


class ExternalSourceSelectors(unittest.TestCase):
    setUp = settings_tests.StagedSettings.setUp
    call = settings_tests.StagedSettings.call
    bootstrap = settings_tests.StagedSettings.bootstrap

    def test_external_source_lookup_and_update_receive_all_settings(self):
        document = tomlkit.loads(self.catalog.read_text())
        document['settings']['second'] = {'source': 'shared', 'path': 'second.toml', 'format': 'toml'}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        second = self.source / 'second.toml'
        second.write_text('color = "blue"\n', encoding='utf-8')
        machine = tomlkit.loads(self.machine.read_text())
        machine['settings']['second'] = {'target': str(self.root / 'app/second.toml')}
        self.machine.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.bootstrap()
        report = self.call('locate', 'shared', '--source')
        self.assertEqual(report['root'], str(self.source))
        self.assertEqual(report['entry'], str(self.source))
        self.assertIsNone(report['checkout'])
        self.assertEqual(report['members'], ['editor', 'second'])
        self.call('locate', 'source:shared', '--repo', code=1)
        self.payload.write_text('color = "red"\ncount = 1\n', encoding='utf-8')
        second.write_text('color = "red"\n', encoding='utf-8')
        other_stage = self.root / 'machine.toml.stages/second/config.toml'
        self.call('update', 'editor')
        self.assertEqual(tomlkit.loads(other_stage.read_text())['color'], 'blue')
        reports = self.call('update', 'source:shared')
        self.assertEqual({r['source'] for r in reports if 'source' in r}, {'editor', 'second'})
        self.assertEqual(tomlkit.loads(self.stage.read_text())['color'], 'red')
        self.assertEqual(tomlkit.loads(other_stage.read_text())['color'], 'red')
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / 'app/second.toml').exists())
