"""Staged settings tests use isolated homes and local sources/remotes only."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner
import tomlkit

from agent_env_man.cli import cli
from agent_env_man.model import Config, Error
from agent_env_man.manager import Manager
from agent_env_man.settings import Bundle, Settings, merge, transaction, recover_group
from agent_env_man.settings_formats import TomlFormat
from agent_env_man.storage import State, observation


class StagedSettings(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='aem-settings-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.payload = self.source / 'editor.toml'
        self.payload.write_text('# Shared\ncolor = "blue"\ncount = 1\n', encoding='utf-8')
        self.catalog = self.root / 'catalog.toml'
        self.catalog.write_text(tomlkit.dumps({'version': 2, 'sources': {'shared': {'type': 'external'}},
            'settings': {'editor': {'source': 'shared', 'path': 'editor.toml', 'format': 'toml'}}}), encoding='utf-8')
        self.machine = self.root / 'machine.toml'
        self.target = self.root / 'app/config.toml'
        self.stage = self.root / 'machine.toml.stages/editor/config.toml'
        self.bootstrap()

    def call(self, *args, code=0):
        result = CliRunner().invoke(cli, ['--config', str(self.machine), '--json', *args])
        self.assertEqual(result.exit_code, code, result.output + (repr(result.exception) if result.exception else ''))
        return json.loads(result.output) if code == 0 else result.output

    def bootstrap(self):
        return self.call('bootstrap', str(self.catalog), '--external', f'shared={self.source}',
                         '--setting-target', f'editor={self.target}')

    def manager(self):
        config = Config(self.machine)
        return Manager(config, State(config.state_dir))

    def edit(self, path, **changes):
        doc = tomlkit.parse(path.read_text(encoding='utf-8'))
        for key, value in changes.items():
            if value is None:
                del doc[key]
            else:
                doc[key] = value
        path.write_text(tomlkit.dumps(doc), encoding='utf-8')

    def apply(self, *args, code=0):
        return self.call('apply', '--item', 'editor', *args, code=code)

    def settings_policy(self, **values):
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings']['editor']['update'] = values
        self.catalog.write_text(tomlkit.dumps(doc))

    def test_settings_policy_is_independent_and_preview_is_offline(self):
        from agent_env_man.updates import run_settings_updates
        doc = tomlkit.parse(self.catalog.read_text())
        doc['updates'] = {'defaults': {'trigger': ['interval'], 'action': 'check'}}
        self.catalog.write_text(tomlkit.dumps(doc))
        manager = self.manager()
        self.assertEqual(run_settings_updates(manager, 'interval')[0][0]['status'], 'not-triggered')
        self.settings_policy(trigger=['interval'])
        manager = self.manager()
        before = manager.state.path.read_bytes()
        with patch.object(manager, 'update', side_effect=AssertionError('Preview must not deliver')):
            report, failed = run_settings_updates(manager, 'interval', dry_run=True)
        self.assertFalse(failed)
        self.assertEqual(report[0]['status'], 'planned')
        self.assertEqual(manager.state.path.read_bytes(), before)
        self.assertFalse(self.target.exists())

    def test_settings_automation_external_sync_preserves_unmanaged_fields(self):
        from agent_env_man.automation import run
        self.apply()
        self.edit(self.target, other=9)
        self.edit(self.payload, color='remote')
        self.settings_policy(trigger=['interval'])
        report = run(self.manager(), 'interval')
        self.assertFalse(report['failed'])
        self.assertEqual(report['settings_updates'][0]['status'], 'synced')
        actual = tomlkit.parse(self.target.read_text())
        self.assertEqual(actual['color'], 'remote')
        self.assertEqual(actual['other'], 9)
        self.assertEqual(run(self.manager(), 'interval')['settings_updates'][0]['status'], 'throttled')

    def test_settings_automation_conflicts_preserve_actual_and_throttle_failure(self):
        from agent_env_man.updates import run_settings_updates
        self.apply()
        self.edit(self.target, color='actual')
        self.edit(self.payload, color='remote')
        self.settings_policy(trigger=['interval'])
        before = self.target.read_bytes()
        manager = self.manager()
        report, failed = run_settings_updates(manager, 'interval')
        self.assertTrue(failed)
        self.assertEqual(report[0]['status'], 'failed')
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(run_settings_updates(manager, 'interval')[0][0]['status'], 'throttled')

    def test_settings_automation_excludes_detached_and_off_mode(self):
        from agent_env_man.updates import run_settings_updates
        self.settings_policy(trigger=['interval'])
        self.call('detach', 'editor')
        self.assertEqual(run_settings_updates(self.manager(), 'interval')[0][0]['status'], 'detached')
        self.call('setup', '--automation', 'off')
        self.assertEqual(run_settings_updates(self.manager(), 'interval'), ([], False))

    def test_full_settings_prepare_new_declaration_and_preserve_detach(self):
        from agent_env_man.automation import full_content
        self.call('detach', 'editor')
        second = self.source / 'second.toml'
        second.write_text('value = 2\n')
        second_target = self.root / 'second-app.toml'
        doc = tomlkit.parse(self.catalog.read_text())
        doc['settings']['second'] = {'source': 'shared', 'path': 'second.toml', 'format': 'toml'}
        self.catalog.write_text(tomlkit.dumps(doc))
        machine = tomlkit.parse(self.machine.read_text())
        machine['settings']['second'] = {'target': str(second_target)}
        self.machine.write_text(tomlkit.dumps(machine))
        manager = self.manager()
        report, failed = full_content(manager, 30)
        self.assertFalse(failed)
        self.assertEqual(report['sources'], ['second'])
        self.assertEqual(report['excluded'], [{'source': 'editor', 'reason': 'detached'}])
        self.assertEqual(tomlkit.parse(second_target.read_text())['value'], 2)
        self.assertNotIn('settings_automation', manager.state.data['sources']['second'])
        self.assertFalse(self.target.exists())

    def test_settings_policy_does_not_prepare_new_stage(self):
        from agent_env_man.updates import run_settings_updates
        self.settings_policy(trigger=['interval'])
        manager = self.manager()
        del manager.state.data['items']['editor:settings']
        report, failed = run_settings_updates(manager, 'interval')
        self.assertFalse(failed)
        self.assertEqual(report[0]['status'], 'not-prepared')
        self.assertFalse(self.target.exists())

    def test_settings_update_rejects_unsupported_fields_and_values(self):
        for fields in ({'action': 'check'}, {'policy': 'skill-policy'}, {'trigger': 'interval'},
                       {'trigger': ['manual']}, {'timeout': 0}, {'min_interval': -1}):
            with self.subTest(fields=fields):
                self.settings_policy(**fields)
                with self.assertRaises(Error):
                    self.manager().config.catalog()

    def test_prepare_locate_and_repeat_preserve_edits(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(self.call('locate', 'editor')['entry'], str(self.stage))
        self.assertEqual(self.call('locate', 'editor', '--source')['entry'], str(self.payload))
        self.assertEqual(self.call('locate', 'editor', '--target')['entry'], str(self.target))
        self.edit(self.stage, color='green')
        self.bootstrap()
        self.assertEqual(tomlkit.parse(self.stage.read_text())['color'], 'green')
        self.call('locate', 'editor', '--source', '--target', code=2)

    def test_multiline_crlf_target_adoption_preserves_bytes(self):
        text = 'policy = """\nfirst\nsecond\n"""\n'
        self.stage.write_bytes(text.encode('utf-8'))
        self.target.parent.mkdir()
        before = ('# Local\nother = 8 # keep\n' + text).replace('\n', '\r\n').encode('utf-8')
        self.target.write_bytes(before)
        self.apply()
        self.apply()
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse(self.call('status')['items'][0]['modified_locally'])
        self.assertEqual(self.call('settings', 'collect', 'editor')['paths'], [])

    def test_multiline_crlf_output_matches_applied_snapshot(self):
        text = 'policy = """\nfirst\nsecond\n"""\n'
        self.stage.write_bytes(text.encode('utf-8'))
        self.target.parent.mkdir()
        self.target.write_bytes(b'# Local\r\nother = 8 # keep\r\n')
        self.apply()
        first = self.target.read_bytes()
        self.assertIn(b'first\r\nsecond\r\n', first)
        self.assertIn(b'other = 8 # keep\r\n', first)
        self.apply()
        self.assertEqual(self.target.read_bytes(), first)
        self.assertFalse(self.call('status')['items'][0]['modified_locally'])
        self.assertEqual(self.call('settings', 'collect', 'editor')['paths'], [])
        self.stage.write_bytes(text.replace('second', 'updated').encode('utf-8'))
        self.apply()
        self.assertIn(b'first\r\nupdated\r\n', self.target.read_bytes())
        self.target.write_bytes(self.target.read_bytes().replace(b'updated', b'local edit'))
        self.stage.write_bytes(text.replace('second', 'stage edit').encode('utf-8'))
        before = self.target.read_bytes()
        self.apply(code=1)
        self.assertEqual(self.target.read_bytes(), before)

    def test_apply_preserves_nonmanaged_values_comments_and_mode(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b'# Application\r\nother = 8 # keep\r\ncolor = "blue"\r\n')
        self.target.chmod(0o640)
        self.apply()
        text = self.target.read_bytes()
        self.assertIn(b'other = 8 # keep\r\n', text)
        self.assertIn(b'count = 1\r\n', text)
        if os.name != 'nt':
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)
        before = self.target.read_bytes()
        self.apply()
        self.assertEqual(self.target.read_bytes(), before)

    def test_initial_different_value_requires_explicit_replace(self):
        self.target.parent.mkdir()
        self.target.write_text('color = "red"\nother = 9\n')
        self.apply(code=1)
        self.apply('--replace')
        doc = tomlkit.parse(self.target.read_text())
        self.assertEqual(doc['color'], 'blue')
        self.assertEqual(doc['other'], 9)

    def test_delete_propagates_and_release_preserves_local_value(self):
        self.apply()
        self.edit(self.stage, count=None)
        self.call('export', 'editor')
        metadata = tomlkit.parse(self.payload.with_name('editor.toml.aem.toml').read_text())
        self.assertIn(['count'], metadata['deleted'])
        self.apply()
        self.assertNotIn('count', tomlkit.parse(self.target.read_text()))
        self.edit(self.target, color='local')
        self.call('settings', 'release', 'editor', '--path', '["color"]')
        self.apply()
        self.assertEqual(tomlkit.parse(self.target.read_text())['color'], 'local')
        self.call('export', 'editor')
        self.assertNotIn('color', tomlkit.parse(self.payload.read_text()))

    def test_new_device_honors_deleted_metadata(self):
        self.edit(self.stage, count=None)
        self.call('export', 'editor')
        self.machine = self.root / 'second.toml'
        self.target = self.root / 'second-app.toml'
        self.target.write_text('count = 44\nother = true\n')
        self.bootstrap()
        self.apply(code=1)
        self.apply('--replace')
        doc = tomlkit.parse(self.target.read_text())
        self.assertNotIn('count', doc)
        self.assertTrue(doc['other'])

    def test_stage_and_target_conflicts_collect_and_explicit_new_field(self):
        self.apply()
        self.edit(self.target, color='red', other=9)
        self.apply(code=1)
        self.call('settings', 'collect', 'editor')
        self.assertNotIn('other', tomlkit.parse(self.stage.read_text()))
        self.call('settings', 'collect', 'editor', '--path', '["other"]')
        self.assertEqual(tomlkit.parse(self.stage.read_text())['other'], 9)
        self.apply()
        self.edit(self.stage, color='yellow')
        self.edit(self.target, color='purple')
        before = self.stage.read_bytes()
        self.call('settings', 'collect', 'editor', code=1)
        self.assertEqual(self.stage.read_bytes(), before)

    def test_receive_nonoverlap_and_persist_conflict_resolution(self):
        self.edit(self.stage, color='local')
        self.edit(self.payload, count=2)
        self.call('update', 'editor')
        doc = tomlkit.parse(self.stage.read_text())
        self.assertEqual((doc['color'], doc['count']), ('local', 2))
        self.edit(self.payload, color='shared')
        self.call('update', 'editor', code=1)
        self.apply(code=1)
        self.call('export', 'editor', code=1)
        self.call('settings', 'resolve', 'editor', '--path', '["color"]', '--take', 'shared')
        self.assertEqual(tomlkit.parse(self.stage.read_text())['color'], 'shared')
        self.apply()

    def test_direct_edit_resolution(self):
        self.edit(self.stage, color='local')
        self.edit(self.payload, color='shared')
        self.call('update', 'editor', code=1)
        self.edit(self.stage, color='chosen')
        self.call('settings', 'resolve', 'editor', '--path', '["color"]', '--take', 'edited')
        self.call('export', 'editor')
        self.assertEqual(tomlkit.parse(self.payload.read_text())['color'], 'chosen')

    def test_export_detects_unreceived_shared_conflict(self):
        self.edit(self.stage, color='local')
        self.edit(self.payload, color='shared')
        before = self.payload.read_bytes()
        self.call('export', 'editor', code=1)
        self.assertEqual(self.payload.read_bytes(), before)

    def test_previews_leave_files_and_state_unchanged(self):
        self.apply()
        self.edit(self.target, other=6)
        self.edit(self.stage, count=None)
        def snapshot():
            return {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for args in [('apply', '--item', 'editor'), ('export', 'editor'),
                     ('settings', 'collect', 'editor', '--path', '["other"]'),
                     ('settings', 'release', 'editor', '--path', '["color"]')]:
            before = snapshot()
            self.call(*args, '--dry-run')
            self.assertEqual(snapshot(), before)

    def test_detach_and_saved_locate_without_catalog(self):
        self.edit(self.stage, color='pending')
        before = self.stage.read_bytes()
        self.call('detach', 'editor')
        self.catalog.unlink()
        self.assertTrue(self.call('locate', 'editor')['detached'])
        self.assertEqual(self.stage.read_bytes(), before)
        self.call('recover')
        self.call('status')

    def test_reattach_after_target_rebinding(self):
        self.apply()
        self.call('detach', 'editor')
        new = self.root / 'new-app.toml'
        self.call('bootstrap', '--setting-target', f'editor={new}')
        self.apply('--reattach')
        self.assertTrue(new.exists())

    def test_source_and_target_redirect_rejected(self):
        other = self.root / 'other.toml'
        other.write_text('count=9\n')
        try:
            self.payload.unlink()
            self.payload.symlink_to(other)
        except OSError:
            self.skipTest('Symlinks unavailable')
        self.call('update', 'editor', code=1)
        self.target.parent.mkdir()
        self.target.symlink_to(other)
        self.apply('--replace', code=1)

    def test_structural_change_cannot_remove_nonmanaged_children(self):
        self.stage.write_text('a = 3\n')
        self.target.parent.mkdir()
        self.target.write_text('[a]\nprivate = 5\n')
        self.apply('--replace', code=1)
        self.assertEqual(tomlkit.parse(self.target.read_text())['a']['private'], 5)

    def test_toml_values_and_literal_dotted_keys(self):
        text = '"a.b" = 4\nvalues = [1, 2]\nf = nan\nd = 2024-02-01\nt = 12:34:56\n[empty]\n[[rows]]\nx = 3\n'
        self.stage.write_text(text)
        self.apply()
        first = self.target.read_bytes()
        self.apply()
        self.assertEqual(first, self.target.read_bytes())
        self.assertEqual(tomlkit.parse(first.decode())['a.b'], 4)

    def test_unchanged_toml_target_retains_mixed_line_endings(self):
        self.target.parent.mkdir()
        original = b'# user comment\r\ncolor = "blue"\ncount = 1\r\nprivate = 4\n'
        self.target.write_bytes(original)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original)

    def test_metadata_validation_and_format_validation(self):
        meta = self.stage.with_name('management.toml')
        meta.write_text('version=1\ndeleted=[["color"]]\n')
        self.apply(code=1)
        document = tomlkit.parse(self.catalog.read_text())
        document['settings']['editor']['format'] = 'jsonc'
        self.catalog.write_text(tomlkit.dumps(document))
        self.call('bootstrap', code=1)

    def test_external_publish_remains_unsupported(self):
        self.call('publish', 'editor', '-m', 'test', code=1)

    def test_group_write_failure_restores_every_file(self):
        manager = self.manager()
        settings = Settings(manager)
        self.edit(self.stage, color='updated')
        writes, record, _ = settings.export_plan('editor')
        before = {path: observation(path) for path, _, _ in writes}
        original = os.replace
        count = 0
        def fail(source, target):
            nonlocal count
            if Path(source).name.startswith('.aem-stage-'):
                count += 1
                if count == 2:
                    raise OSError('Simulated interruption')
            return original(source, target)
        with patch('agent_env_man.settings.os.replace', side_effect=fail):
            with self.assertRaises(OSError):
                transaction(manager.state, writes, {'editor:settings': record})
        self.assertEqual({p: observation(p) for p in before}, before)
        self.assertIsNone(manager.state.data['pending'])

    def test_recovery_preflights_whole_group_before_rollback(self):
        state = self.manager().state
        files = []
        for index in range(2):
            target = self.root / f'file{index}'
            target.write_text('old')
            before = observation(target)
            backup = target.with_name(target.name + '.aem-backup-test')
            target.rename(backup)
            target.write_text('new')
            files.append({'target': str(target), 'backup': str(backup),
                          'stage': str(target.with_name(f'.aem-stage-test-{index}')),
                          'before': before, 'after': observation(target)})
        Path(files[1]['target']).write_text('user edit')
        state.data['pending'] = {'operation': 'settings-group', 'files': files}
        state.save()
        with self.assertRaises(Error):
            recover_group(state)
        self.assertEqual(Path(files[0]['target']).read_text(), 'new')
        Path(files[1]['target']).write_text('new')
        self.call('recover')
        self.assertEqual(Path(files[0]['target']).read_text(), 'old')


class SemanticMerge(unittest.TestCase):
    def bundle(self, text):
        return Bundle.from_snapshot({'config': text, 'management': ''})

    def test_multiline_physical_newlines_compare_equal_in_containers(self):
        for text in ('value = """\nfirst\nsecond\n"""\n',
                     'value = ' + chr(39) * 3 + '\nfirst\nsecond\n' + chr(39) * 3 + '\n',
                     'value = ["""first\nsecond"""]\n',
                     'value = [{nested = """first\nsecond"""}]\n',
                     '[[value]]\nnested = """first\nsecond"""\n'):
            with self.subTest(text=text):
                lf = self.bundle(text)
                crlf = self.bundle(text.replace('\n', '\r\n'))
                _, conflicts = merge(lf, crlf, lf)
                self.assertFalse(conflicts)
                for path, value in lf.adapter.fields(lf.document).items():
                    self.assertEqual(TomlFormat.identity(value),
                                     TomlFormat.identity(crlf.adapter.fields(crlf.document)[path]))
                self.assertEqual(crlf.snapshot()['config'], text.replace('\n', '\r\n'))

    def test_explicit_carriage_return_remains_a_distinct_value(self):
        for text in ('value = "first\\r\\nsecond"\n',
                     'value = """first\\r\nsecond"""\n',
                     'value = ["first\\u000D\\nsecond"]\n',
                     '[[value]]\nnested = "first\\r\\nsecond"\n'):
            with self.subTest(text=text):
                escaped = self.bundle(text)
                plain = self.bundle(text.replace('\\r', '').replace('\\u000D', ''))
                for path, value in escaped.adapter.fields(escaped.document).items():
                    self.assertNotEqual(TomlFormat.identity(value),
                                        TomlFormat.identity(plain.adapter.fields(plain.document)[path]))

    def test_scalar_table_transition(self):
        base = self.bundle('[a]\nb=1\n')
        local = deepcopy(base)
        incoming = self.bundle('a=2\n')
        result, conflicts = merge(base, local, incoming)
        self.assertFalse(conflicts)
        self.assertEqual(result.document['a'], 2)

    def test_structural_overlap_is_conflict(self):
        base = self.bundle('[a]\nb=1\n')
        local = self.bundle('[a]\nb=2\n')
        incoming = self.bundle('a=2\n')
        _, conflicts = merge(base, local, incoming)
        self.assertEqual(set(conflicts), {('a',), ('a', 'b')})

    def test_types_are_distinct_and_nan_is_stable(self):
        self.assertNotEqual(TomlFormat.identity(1), TomlFormat.identity(True))
        self.assertNotEqual(TomlFormat.identity(1), TomlFormat.identity(1.0))
        self.assertEqual(TomlFormat.identity(float('nan')), TomlFormat.identity(float('nan')))


class GitSettings(unittest.TestCase):
    call = StagedSettings.call
    edit = StagedSettings.edit
    apply = StagedSettings.apply
    manager = StagedSettings.manager

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='aem-settings-git-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.git(self.work, 'init', '-b', 'main')
        self.git(self.work, 'config', 'user.name', 'Test User')
        self.git(self.work, 'config', 'user.email', 'test@example.invalid')
        (self.work / 'editor.toml').write_text('color="blue"\ncount=1\n')
        (self.work / 'second.toml').write_text('count=1\n')
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'Initial')
        self.remote = self.root / 'remote.git'
        self.git(self.root, 'clone', '--bare', str(self.work), str(self.remote))
        self.git(self.work, 'remote', 'add', 'origin', str(self.remote))
        self.catalog = self.root / 'catalog.toml'
        self.catalog.write_text(tomlkit.dumps({'version': 2,
            'sources': {'shared': {'type': 'git', 'repository': str(self.remote)}},
            'settings': {'editor': {'source': 'shared', 'path': 'editor.toml', 'format': 'toml'}}}))
        self.machine = self.root / 'machine.toml'
        self.target = self.root / 'app.toml'
        self.call('bootstrap', str(self.catalog), '--setting-target', f'editor={self.target}',
                  '--root', f'skills={self.root / "skills"}')
        self.checkout = self.root / 'machine.toml.checkouts/.aem-repositories/shared'
        self.payload = self.checkout / 'editor.toml'
        self.stage = self.root / 'machine.toml.stages/editor/config.toml'
        self.git(self.checkout, 'config', 'user.name', 'Test User')
        self.git(self.checkout, 'config', 'user.email', 'test@example.invalid')

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-C', str(cwd), *args], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def upstream(self, text):
        (self.work / 'editor.toml').write_text(text)
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'Upstream change')
        self.git(self.work, 'push', 'origin', 'main')

    def test_publish_exports_to_verified_empty_remote(self):
        self.git(self.remote, 'update-ref', '-d', 'refs/heads/main')
        self.edit(self.stage, color='green')
        report = self.call('publish', 'editor', '-m', 'Initial settings publication')[0]
        self.assertTrue(report['initial_publish'])
        self.assertEqual(report['status'], 'published')
        self.assertEqual(tomlkit.parse(self.git(self.remote, 'show', 'main:editor.toml'))['color'], 'green')

    def test_publish_exports_commits_and_pushes(self):
        self.edit(self.stage, color='green')
        report = self.call('publish', 'editor', '-m', 'Update setting')
        self.assertEqual(report[0]['status'], 'published')
        remote = self.git(self.remote, 'show', 'main:editor.toml')
        self.assertEqual(tomlkit.parse(remote)['color'], 'green')
        self.assertIn('version = 1', self.git(self.remote, 'show', 'main:editor.toml.aem.toml'))
        self.assertIsNone(self.manager().state.data['items']['editor:settings']['applied'])

    def test_no_message_and_offline_preview_do_not_export(self):
        self.edit(self.stage, count=None)
        before = self.payload.read_bytes()
        self.call('publish', 'editor', code=1)
        self.assertEqual(self.payload.read_bytes(), before)
        from agent_env_man.git_source import Git
        with patch.object(Git, 'fetch', side_effect=AssertionError('Preview fetched')):
            report = self.call('publish', 'editor', '-m', 'Delete count', '--dry-run')
        self.assertTrue(report[0]['export'][0]['changed'])
        self.assertEqual(self.payload.read_bytes(), before)

    def test_invalid_incoming_toml_does_not_advance_checkout(self):
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.upstream('color = [\n')
        self.call('update', 'editor', code=1)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), head)

    def test_checkout_newlines_do_not_conflict_with_staged_edits(self):
        text = 'policy = """\nfirst\nsecond\n"""\n'
        self.upstream(text)
        self.call('update', 'editor')
        self.git(self.checkout, 'config', 'core.autocrlf', 'true')
        self.payload.unlink()
        self.git(self.checkout, 'checkout', '--', 'editor.toml')
        self.assertIn(b'\r\n', self.payload.read_bytes())
        edited = text.replace('second', 'staged')
        self.stage.write_bytes(edited.encode('utf-8'))
        self.call('update', 'editor')
        self.assertIn('staged', Bundle.load(self.stage).document['policy'])
        self.call('export', 'editor')
        self.assertIn('staged', Bundle.load(self.payload).document['policy'])
        self.apply()
        self.apply()
        self.assertFalse(self.call('status')['items'][0]['modified_locally'])

    def test_export_merges_stage_edit_after_checkout_conversion(self):
        text = 'policy = """\nfirst\nsecond\n"""\n'
        self.upstream(text)
        self.call('update', 'editor')
        self.git(self.checkout, 'config', 'core.autocrlf', 'true')
        self.payload.unlink()
        self.git(self.checkout, 'checkout', '--', 'editor.toml')
        self.assertIn(b'\r\n', self.payload.read_bytes())
        self.stage.write_bytes(text.replace('second', 'staged').encode('utf-8'))
        self.call('export', 'editor')
        self.assertIn('staged', Bundle.load(self.payload).document['policy'])

    def test_receive_and_apply_are_separate(self):
        self.apply()
        self.upstream('color="blue"\ncount=2\n')
        self.call('update', 'editor')
        self.assertEqual(tomlkit.parse(self.stage.read_text())['count'], 2)
        self.assertEqual(tomlkit.parse(self.target.read_text())['count'], 1)
        self.apply()
        self.assertEqual(tomlkit.parse(self.target.read_text())['count'], 2)

    def test_push_failure_retains_commit_for_retry(self):
        from agent_env_man.git_source import Git
        original = Git.run
        def fail(git, path, *args, **kwargs):
            if 'push' in args:
                raise Error('Simulated push failure')
            return original(git, path, *args, **kwargs)
        self.edit(self.stage, color='green')
        with patch.object(Git, 'run', new=fail):
            self.call('publish', 'editor', '-m', 'Change color', code=1)
        self.assertEqual(self.git(self.checkout, 'status', '--porcelain'), '')
        self.assertEqual(tomlkit.parse(self.payload.read_text())['color'], 'green')
        self.assertTrue(Settings(self.manager()).status(self.manager().state.data['items']['editor:settings'])['unpublished'])
        self.call('publish', 'editor')
        self.assertEqual(tomlkit.parse(self.git(self.remote, 'show', 'main:editor.toml'))['color'], 'green')

    def test_behind_publication_does_not_export(self):
        self.edit(self.stage, color='local')
        before = self.payload.read_bytes()
        self.upstream('color="remote"\ncount=1\n')
        self.call('publish', 'editor', '-m', 'Change color', code=1)
        self.assertEqual(self.payload.read_bytes(), before)

    def test_full_content_receives_and_applies_settings(self):
        from agent_env_man.automation import full_content
        self.upstream('color="remote"\ncount=1\n')
        report, failed = full_content(self.manager(), 30)
        self.assertFalse(failed)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['sources'], ['editor'])
        self.assertEqual(tomlkit.parse(self.stage.read_text())['color'], 'remote')
        self.assertEqual(tomlkit.parse(self.target.read_text())['color'], 'remote')

    def test_full_settings_exclusions_and_conflict_stop_application(self):
        from agent_env_man.automation import full_content
        self.apply()
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['settings']['editor']['update'] = {'trigger': []}
        self.catalog.write_text(tomlkit.dumps(catalog))
        report, failed = full_content(self.manager(), 30)
        self.assertFalse(failed)
        self.assertEqual(report['excluded'], [{'source': 'editor', 'reason': 'manual'}])
        del catalog['settings']['editor']['update']
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.edit(self.stage, color='local')
        self.upstream('color="remote"\ncount=1\n')
        before = self.target.read_bytes()
        report, failed = full_content(self.manager(), 30)
        self.assertTrue(failed)
        self.assertNotIn('apply', report)
        self.assertEqual(self.target.read_bytes(), before)

    def test_setting_policy_git_reception_and_apply(self):
        from agent_env_man.updates import run_settings_updates
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['settings']['editor']['update'] = {'trigger': ['interval']}
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.upstream('color="remote"\ncount=1\n')
        manager = self.manager()
        report, failed = run_settings_updates(manager, 'interval')
        self.assertFalse(failed)
        self.assertEqual(report[0]['status'], 'synced')
        self.assertEqual(tomlkit.parse(self.target.read_text())['color'], 'remote')
        self.assertEqual(run_settings_updates(manager, 'interval')[0][0]['status'], 'throttled')

    def test_settings_sync_shared_checkout_requests_skill_reload(self):
        from agent_env_man.updates import run_settings_updates, startup_skills_changed
        skill = self.work / 'helper'
        skill.mkdir()
        (skill / 'SKILL.md').write_text('# Helper\n')
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'Add shared skill')
        self.git(self.work, 'push', 'origin', 'main')
        self.call('update', 'editor')
        doc = tomlkit.parse(self.catalog.read_text())
        doc['skills'] = {'helper': {'source': 'shared', 'subdir': 'helper'}}
        doc['settings']['editor']['update'] = {'trigger': ['interval']}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.call('bootstrap', str(self.catalog))
        self.call('apply', '--item', 'helper')
        (skill / 'SKILL.md').write_text('# Updated helper\n')
        self.upstream('color="remote"\ncount=1\n')
        manager = self.manager()
        report, failed = run_settings_updates(manager, 'interval')
        self.assertFalse(failed)
        self.assertTrue(startup_skills_changed(report, manager.state.data['items'], 'codex', manager.config.sources))
        self.assertIn('Updated helper', (self.root / 'skills/helper/SKILL.md').read_text())

    def test_publish_reports_unselected_pending_stage(self):
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['settings']['second'] = {'source': 'shared', 'path': 'second.toml', 'format': 'toml'}
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.call('bootstrap', '--setting-target', f'second={self.root / "second-app.toml"}')
        second_stage = self.root / 'machine.toml.stages/second/config.toml'
        self.edit(second_stage, count=9)
        self.edit(self.stage, color='green')
        report = self.call('publish', 'editor', '-m', 'Change editor')
        self.assertEqual(report[0]['unpublished_settings'], ['second'])
        self.assertEqual(tomlkit.parse(self.git(self.remote, 'show', 'main:second.toml'))['count'], 1)


class SettingsSafety(unittest.TestCase):
    setUp = StagedSettings.setUp
    call = StagedSettings.call
    bootstrap = StagedSettings.bootstrap
    manager = StagedSettings.manager
    edit = StagedSettings.edit
    apply = StagedSettings.apply

    def test_export_does_not_overwrite_a_stage_edited_after_reading(self):
        manager = self.manager()
        self.edit(self.stage, color='pending')
        writes, record, _ = Settings(manager).export_plan('editor')
        self.edit(self.stage, color='later')
        source_before = self.payload.read_bytes()
        with self.assertRaises(Error):
            transaction(manager.state, writes, {'editor:settings': record})
        self.assertEqual(self.payload.read_bytes(), source_before)
        self.assertEqual(tomlkit.parse(self.stage.read_text())['color'], 'later')

    def test_state_commit_failure_rolls_back_files_and_comparison_bases(self):
        manager = self.manager()
        self.edit(self.stage, color='pending')
        writes, record, _ = Settings(manager).export_plan('editor')
        before_records = deepcopy(manager.state.data['items'])
        source_before = self.payload.read_bytes()
        original = manager.state.save
        calls = 0
        def save():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('Simulated state commit failure')
            original()
        with patch.object(manager.state, 'save', side_effect=save):
            with self.assertRaises(OSError):
                transaction(manager.state, writes, {'editor:settings': record})
        self.assertEqual(self.payload.read_bytes(), source_before)
        self.assertEqual(manager.state.data['items'], before_records)
        self.assertIsNone(manager.state.data['pending'])

    def test_repeated_metadata_only_publish_preview_stays_semantic(self):
        self.call('export', 'editor')
        before = self.payload.read_bytes()
        report = self.call('export', 'editor', '--dry-run')
        self.assertFalse(report[0]['changed'])
        self.assertEqual(report[0]['paths'], [])
        self.assertEqual(self.payload.read_bytes(), before)

    def test_invalid_cli_paths_fail_before_loading_configuration(self):
        self.machine.unlink()
        for path in ('invalid', '[]', '[1]'):
            self.call('settings', 'release', 'editor', '--path', path, code=2)

    def test_overlapping_target_declarations_are_rejected(self):
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['settings']['second'] = dict(catalog['settings']['editor'])
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.call('bootstrap', '--setting-target', f'second={self.target}', code=1)

    def test_management_state_does_not_capture_application_private_fields(self):
        self.apply()
        self.edit(self.target, private='private-value')
        self.call('settings', 'collect', 'editor')
        text = self.manager().state.path.read_text()
        self.assertNotIn('private-value', text)
        self.assertNotIn('private', self.stage.read_text())

    def test_collect_structural_change_preserves_unmanaged_sibling(self):
        self.stage.write_text('a=1\n')
        self.apply()
        self.target.write_text('[a]\nb=2\nprivate=3\n')
        self.call('settings', 'collect', 'editor', '--path', '["a","b"]')
        self.apply()
        doc = tomlkit.parse(self.target.read_text())
        self.assertEqual(doc['a']['b'], 2)
        self.assertEqual(doc['a']['private'], 3)

    def test_scalar_to_table_detects_local_scalar_edit(self):
        self.stage.write_text('a=1\n')
        self.apply()
        self.stage.write_text('[a]\nb=2\n')
        self.target.write_text('a=3\n')
        before = self.target.read_bytes()
        self.apply(code=1)
        self.assertEqual(self.target.read_bytes(), before)
        self.apply('--replace')
        self.assertEqual(tomlkit.parse(self.target.read_text())['a']['b'], 2)

    def test_preparing_stage_preview_does_not_create_files(self):
        manager = self.manager()
        record = manager.state.data['items'].pop('editor:settings')
        manager.state.save()
        for path in (self.stage, self.stage.with_name('management.toml')):
            path.unlink()
        before = manager.state.path.read_bytes()
        self.call('settings', 'prepare', 'editor', '--dry-run')
        self.assertEqual(manager.state.path.read_bytes(), before)
        self.assertFalse(self.stage.exists())
        self.call('settings', 'prepare', 'editor')
        self.assertTrue(self.stage.exists())

    def test_owned_target_cannot_overlap_stage_storage(self):
        catalog = tomlkit.parse(self.catalog.read_text())
        catalog['instructions'] = {'docs': {'source': 'shared', 'entry': 'AGENTS.md',
            'install': {'entry': {'root': 'agent'}}}}
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.call('bootstrap', '--root', f'agent={self.stage.parent}', code=1)


class FormatIndependentMerge(unittest.TestCase):
    def test_merge_uses_format_adapter_value_identity(self):
        class Adapter:
            def fields(self, document):
                return {(key,): value for key, value in document.items()}

            def identity(self, value):
                return value.casefold()

            def put(self, document, path, value=None, *, delete=False):
                if delete:
                    document.pop(path[0], None)
                else:
                    document[path[0]] = value

        adapter = Adapter()
        base = Bundle({'key': 'a'}, set(), set(), adapter)
        local = Bundle({'key': 'b'}, set(), set(), adapter)
        incoming = Bundle({'key': 'B'}, set(), set(), adapter)
        result, conflicts = merge(base, local, incoming)
        self.assertEqual(conflicts, [])
        self.assertEqual(result.document['key'].casefold(), 'b')
