"""Local catalog copies round-trip without depending on external availability."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.model import Config
from agent_env_man.storage import State


class LocalCatalogCopies(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-local-catalog-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'machine.toml'
        self.source = self.root / 'synced/catalog.toml'
        self.source.parent.mkdir()
        self.source.write_text('version = 2\n# initial\n', encoding='utf-8')
        self.copy = self.root / 'machine.toml.catalog-copy/catalog.toml'
        self.state_path = self.root / 'machine.toml.state'

    def cli(self, *args, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(['--json', '--config', str(self.config), *map(str, args)])
        self.assertEqual(result, code, f'{args}\n{output.getvalue()}\n{errors.getvalue()}')
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def bootstrap(self):
        return self.cli('bootstrap', self.source, '--catalog-copy', '--root', f'agent={self.root / "agent"}',
                        '--root', f'skills={self.root / "skills"}', '--root', f'home={self.root / "home"}')

    def state(self):
        return State(self.state_path).data

    def test_registration_reuse_offline_and_locate(self):
        self.bootstrap()
        self.assertEqual(self.source.read_bytes(), self.copy.read_bytes())
        binding = tomlkit.parse(self.config.read_text())['catalog']
        self.assertEqual(dict(binding), {'type': 'local', 'path': str(self.source), 'mode': 'copy'})
        self.assertEqual(self.cli('catalog', 'locate')['entry'], str(self.copy))
        self.source.unlink()
        self.assertEqual(self.cli('catalog', 'locate', '--source')['entry'], str(self.source))
        self.cli('bootstrap')
        self.cli('apply', '--dry-run')
        status = self.cli('catalog', 'status')
        self.assertEqual(status['status'], 'ready')
        self.assertFalse(status['source_available'])
        before = self.copy.read_bytes(), self.state()
        self.cli('catalog', 'update', code=1)
        self.cli('catalog', 'publish', '--from-copy', code=1)
        self.assertEqual((self.copy.read_bytes(), self.state()), before)
        self.assertFalse(self.source.exists())

    def test_round_trip_conflict_matrix(self):
        self.bootstrap()
        initial_state = self.state()
        self.cli('catalog', 'update')
        self.cli('catalog', 'publish', '--from-copy')
        self.assertEqual(self.state(), initial_state)
        self.source.write_text('version = 2\n# source edit\n')
        original_copy = self.copy.read_bytes()
        report = self.cli('catalog', 'publish', '--from-copy')
        self.assertTrue(report['stale'])
        self.assertEqual(self.copy.read_bytes(), original_copy)
        self.assertEqual(self.state(), initial_state)
        self.cli('catalog', 'update')
        self.assertEqual(self.copy.read_bytes(), self.source.read_bytes())
        self.copy.write_text('version = 2\n# copy edit\n')
        before_source = self.source.read_bytes()
        state = self.state()
        self.cli('catalog', 'update')
        self.assertEqual(self.state(), state)
        self.assertIn('copy edit', self.copy.read_text())
        self.cli('catalog', 'publish', '--from-copy', '--dry-run')
        self.assertEqual(self.source.read_bytes(), before_source)
        self.assertEqual(self.state(), state)
        self.cli('catalog', 'publish', '--from-copy')
        self.assertEqual(self.copy.read_bytes(), self.source.read_bytes())
        self.source.write_text('version = 2\n# competing source\n')
        self.copy.write_text('version = 2\n# competing copy\n')
        before = self.source.read_bytes(), self.copy.read_bytes(), self.state()
        self.assertTrue(self.cli('catalog', 'update', code=1)['conflict'])
        self.assertTrue(self.cli('catalog', 'publish', '--from-copy', code=1)['conflict'])
        self.assertEqual((self.source.read_bytes(), self.copy.read_bytes(), self.state()), before)
        self.source.write_bytes(self.copy.read_bytes())
        self.cli('catalog', 'publish', '--from-copy')
        self.assertFalse(self.cli('catalog', 'status')['copy_modified'])

    def test_invalid_candidate_preserves_files_and_baseline(self):
        self.bootstrap()
        for text in ('not valid TOML', 'version = 2\n[skills.bad]\nsource = "absent"\n'):
            with self.subTest(text=text):
                self.source.write_text(text)
                before = self.copy.read_bytes(), self.state()
                self.cli('catalog', 'update', code=1)
                self.assertEqual((self.copy.read_bytes(), self.state()), before)
        self.source.write_bytes(self.copy.read_bytes())
        self.copy.write_text('broken = [')
        original = self.source.read_bytes()
        self.cli('catalog', 'publish', '--from-copy', code=1)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.cli('catalog', 'locate')['entry'], str(self.copy))
        self.assertEqual(self.cli('catalog', 'status')['status'], 'unavailable')
        self.cli('recover')

    def test_initial_invalid_and_option_combinations_do_not_bind(self):
        self.cli('bootstrap', '--catalog-copy', code=1)
        self.cli('bootstrap', self.source, '--catalog-copy', '--catalog-repository', 'https://invalid.test/x', code=1)
        self.source.write_text('bad = [')
        self.bootstrap_error()
        self.assertFalse(self.config.exists())
        self.assertFalse(self.copy.exists())

    def bootstrap_error(self):
        return self.cli('bootstrap', self.source, '--catalog-copy', code=1)

    def test_publication_is_explicit_and_direct_binding_stays_direct(self):
        self.bootstrap()
        self.cli('catalog', 'publish', code=1)
        self.cli('catalog', 'publish', '--from-copy', '-m', 'Not Git', code=1)
        other = self.root / 'direct.toml'
        other.write_text('version = 1\ncatalog = ' + json.dumps(str(self.source)) + '\n')
        self.config = other
        self.assertEqual(self.cli('catalog', 'locate')['entry'], str(self.source))
        self.assertEqual(self.cli('catalog', 'locate', '--source')['entry'], str(self.source))
        self.cli('catalog', 'publish', '--from-copy', code=1)

    def test_rebind_protects_modified_and_unowned_copies(self):
        self.bootstrap()
        other = self.root / 'another.toml'
        other.write_text('version = 2\n# another\n')
        self.copy.write_text('version = 2\n# local\n')
        before = self.config.read_bytes(), self.copy.read_bytes(), self.state()
        self.cli('bootstrap', other, '--catalog-copy', code=1)
        self.assertEqual((self.config.read_bytes(), self.copy.read_bytes(), self.state()), before)
        self.copy.write_bytes(self.source.read_bytes())
        self.cli('bootstrap', other, '--catalog-copy')
        self.assertEqual(self.copy.read_bytes(), other.read_bytes())
        state = State(self.state_path)
        del state.data['catalog_copy']
        state.save()
        self.cli('bootstrap', other, '--catalog-copy', code=1)
        self.cli('catalog', 'update', code=1)

    def test_symlinks_and_storage_overlap_rejected(self):
        probe = self.root / 'link'
        try:
            probe.symlink_to(self.source)
        except OSError:
            self.skipTest('Symbolic link capability unavailable')
        self.cli('bootstrap', probe, '--catalog-copy', code=1)
        self.bootstrap()
        self.copy.unlink()
        self.copy.symlink_to(self.source)
        self.cli('catalog', 'locate', code=1)
        self.cli('catalog', 'update', code=1)
        self.cli('catalog', 'publish', '--from-copy', code=1)
        self.assertEqual(self.cli('catalog', 'status')['status'], 'unavailable')

    def test_bootstrap_commit_failure_restores_binding_and_copy(self):
        replace = os.replace
        def fail_machine(src, dst):
            if Path(dst) == self.config and Path(src).name.startswith('.aem-stage-'):
                raise OSError('injected machine replacement failure')
            return replace(src, dst)
        with patch('agent_env_man.settings.os.replace', side_effect=fail_machine):
            self.bootstrap_error()
        self.assertFalse(self.copy.exists())
        self.assertFalse(self.config.exists())
        self.assertIsNone(self.state()['pending'])
        self.assertNotIn('catalog_copy', self.state())
        self.bootstrap()

    def test_state_commit_failure_rolls_back_update_and_publication(self):
        self.bootstrap()
        save = State.save
        for publish in (False, True):
            with self.subTest(publish=publish):
                self.source.write_bytes(self.copy.read_bytes())
                self.cli('catalog', 'update')
                changed = self.copy if publish else self.source
                changed.write_text('version = 2\n# ' + str(publish))
                before = self.source.read_bytes(), self.copy.read_bytes(), self.state()
                attempted = False
                def fail_once(state):
                    nonlocal attempted
                    if state.data['pending'] is None and not attempted:
                        attempted = True
                        raise OSError('injected state commit failure')
                    return save(state)
                with patch.object(State, 'save', fail_once):
                    self.cli('catalog', *(['publish', '--from-copy'] if publish else ['update']), code=1)
                self.assertEqual((self.source.read_bytes(), self.copy.read_bytes(), self.state()), before)

    def test_interrupted_update_recovery_preserves_unrelated_edit(self):
        self.bootstrap()
        self.source.write_text('version = 2\n# newer\n')
        before = self.copy.read_bytes()
        replace = os.replace
        def interrupt(src, dst):
            if Path(dst) == self.copy and Path(src).name.startswith('.aem-stage-'):
                raise KeyboardInterrupt()
            return replace(src, dst)
        with patch('agent_env_man.settings.os.replace', side_effect=interrupt):
            self.cli('catalog', 'update', code=1)
        self.assertIsNotNone(self.state()['pending'])
        self.copy.write_text('unrelated user edit')
        self.cli('recover', code=1)
        self.assertEqual(self.copy.read_text(), 'unrelated user edit')
        self.copy.unlink()
        self.source.unlink()
        self.cli('recover')
        self.assertEqual(self.copy.read_bytes(), before)
        self.assertIsNone(self.state()['pending'])

    def test_input_race_rolls_back_and_automatic_policy_stays_git_only(self):
        self.bootstrap()
        self.copy.write_text('version = 2\n# edited\n')
        original = self.source.read_bytes()
        replace = os.replace
        def race(src, dst):
            result = replace(src, dst)
            if Path(dst) == self.source and Path(src).name.startswith('.aem-stage-'):
                self.copy.write_text('version = 2\n# concurrent edit\n')
            return result
        with patch('agent_env_man.settings.os.replace', side_effect=race):
            self.cli('catalog', 'publish', '--from-copy', code=1)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIn('concurrent edit', self.copy.read_text())
        self.cli('bootstrap', '--catalog-trigger', 'shell-start', code=1)

    def test_new_declarations_are_validated_without_preparing_sources(self):
        self.bootstrap()
        before = self.copy.read_bytes(), self.state()
        self.source.write_text('version = 2\n[sources.docs]\ntype = "external"\n'
                               '[instructions.personal]\nsource = "docs"\nentry = "start.md"\n'
                               '[instructions.personal.install.entry]\nroot = "agent"\n')
        self.cli('catalog', 'update', code=1)
        self.assertEqual((self.copy.read_bytes(), self.state()), before)
        external = self.root / 'documents'
        external.mkdir()
        (external / 'start.md').write_text('Instructions')
        doc = tomlkit.parse(self.config.read_text())
        doc['external_paths'] = {'docs': str(external)}
        self.config.write_text(tomlkit.dumps(doc))
        self.cli('catalog', 'update')
        self.assertFalse((self.root / 'agent/AGENTS.md').exists())
        self.assertFalse((self.root / 'machine.toml.bundles').exists())

    def test_saved_target_and_external_root_overlap_preserve_existing_state(self):
        self.bootstrap()
        self.source.write_text('version = 2\n# update\n')
        state = State(self.state_path)
        state.data['items']['orphan'] = {'target': str(self.source), 'mode': 'copy', 'kind': 'directory',
                                        'source': str(self.root / 'other'), 'hash': 'old'}
        state.save()
        before = self.copy.read_bytes(), self.state()
        self.cli('catalog', 'update', code=1)
        self.assertEqual((self.copy.read_bytes(), self.state()), before)
        state.data['items'] = {}
        state.save()
        doc = tomlkit.parse(self.config.read_text())
        doc['external_paths'] = {'overlap': str(self.copy.parent)}
        self.config.write_text(tomlkit.dumps(doc))
        self.cli('catalog', 'update', code=1)
        self.assertEqual(self.copy.read_bytes(), before[0])

    def test_copy_schema_rejects_unknown_fields_and_managed_sources(self):
        self.bootstrap()
        original = tomlkit.parse(self.config.read_text())
        for field, value in (('extra', True), ('mode', 'link'), ('path', 'relative.toml'),
                             ('path', str(self.state_path / 'input.toml')),
                             ('path', str(self.copy)), ('path', True)):
            with self.subTest(field=field, value=value):
                doc = tomlkit.parse(tomlkit.dumps(original))
                doc['catalog'][field] = value
                self.config.write_text(tomlkit.dumps(doc))
                self.cli('catalog', 'locate', code=1)
        self.config.write_text(tomlkit.dumps(original))
        self.cli('catalog', 'locate')

    def test_initial_utf8_failure_and_executable_original(self):
        self.source.write_bytes(b'\xff')
        self.bootstrap_error()
        self.assertFalse(self.copy.exists())
        self.assertFalse(self.config.exists())
        self.source.write_text('version = 2\n# 한글\r\n', encoding='utf-8')
        self.source.chmod(0o700)
        self.bootstrap()
        self.assertEqual(self.source.read_bytes(), self.copy.read_bytes())
        self.assertFalse(self.cli('catalog', 'status')['copy_modified'])
        self.cli('catalog', 'update')
        self.cli('catalog', 'publish', '--from-copy')

    def test_interrupt_initial_binding_recovers_without_catalog(self):
        replace = os.replace
        def interrupt(src, dst):
            if Path(dst) == self.config and Path(src).name.startswith('.aem-stage-'):
                raise KeyboardInterrupt()
            return replace(src, dst)
        with patch('agent_env_man.settings.os.replace', side_effect=interrupt):
            self.bootstrap_error()
        self.assertIsNotNone(self.state()['pending'])
        self.assertTrue(self.copy.exists())
        self.source.unlink()
        self.cli('recover')
        self.assertFalse(self.copy.exists())
        self.assertFalse(self.config.exists())
        self.assertNotIn('catalog_copy', self.state())
