"""JSON settings contracts using temporary files and local Git repositories."""

from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.model import Error
from agent_env_man.settings import Bundle, Settings, merge, recover_group, transaction
from agent_env_man.settings_formats import JsonFormat
from agent_env_man.storage import observation
import test_settings as fixtures


class JsonFixture:
    call = fixtures.StagedSettings.call
    manager = fixtures.StagedSettings.manager
    apply = fixtures.StagedSettings.apply
    settings_policy = fixtures.StagedSettings.settings_policy

    def temporary_root(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-json-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.machine = self.root / 'machine.toml'
        self.catalog = self.root / 'catalog.toml'
        self.target = self.root / 'app/config.json'
        self.stage = self.root / 'machine.toml.stages/editor/config.json'

    def edit(self, path, **changes):
        document = json.loads(path.read_text(encoding='utf-8'))
        document.update(changes)
        path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')


class JsonSettings(JsonFixture, unittest.TestCase):
    def setUp(self):
        self.temporary_root()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.payload = self.source / 'editor.json'
        self.payload.write_text('{"color": "blue", "count": 1}\n', encoding='utf-8')
        self.catalog.write_text(tomlkit.dumps({'version': 2,
            'sources': {'shared': {'type': 'external'}},
            'settings': {'editor': {'source': 'shared', 'path': 'editor.json', 'format': 'json'}}}),
            encoding='utf-8')
        self.call('bootstrap', str(self.catalog), '--external', f'shared={self.source}',
                  '--setting-target', f'editor={self.target}')

    def test_missing_target_and_stage_locations(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(self.stage.read_bytes(), self.payload.read_bytes())
        self.assertEqual(Path(self.call('locate', 'editor')['entry']), self.stage)
        self.assertEqual(Path(self.call('locate', 'editor', '--target')['entry']), self.target)
        self.apply()
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8')), {'color': 'blue', 'count': 1})
        self.assertTrue(self.target.read_text(encoding='utf-8').startswith('{\n  '))

    def test_noop_and_changed_apply_preserve_unmanaged_tokens_and_permissions(self):
        self.target.parent.mkdir()
        original = b'{\r\n\t"local" : { "huge":900719925474099312345, "escape":"\\u0061" },\r\n\t"color":"blue",\r\n\t"count" : 1e0\r\n}\r\n'
        self.target.write_bytes(original)
        self.target.chmod(0o640)
        mode = self.target.stat().st_mode
        self.apply()
        self.assertEqual(self.target.read_bytes(), original)
        self.edit(self.stage, count=2)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original.replace(b'1e0', b'2'))
        self.assertEqual(self.target.stat().st_mode, mode)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original.replace(b'1e0', b'2'))

    def test_null_deletion_release_and_reclaim(self):
        self.edit(self.stage, nullable=None)
        self.apply()
        self.assertIsNone(json.loads(self.target.read_text(encoding='utf-8'))['nullable'])
        self.call('settings', 'collect', 'editor')
        self.assertIsNone(json.loads(self.stage.read_text(encoding='utf-8'))['nullable'])
        self.call('settings', 'release', 'editor', '--path', '["nullable"]')
        self.apply()
        self.assertIn('nullable', json.loads(self.target.read_text(encoding='utf-8')))
        self.call('settings', 'collect', 'editor', '--path', '["nullable"]')
        self.apply()
        document = json.loads(self.stage.read_text(encoding='utf-8'))
        del document['nullable']
        self.stage.write_text(json.dumps(document), encoding='utf-8')
        self.apply()
        self.assertNotIn('nullable', json.loads(self.target.read_text(encoding='utf-8')))
        self.call('export', 'editor')
        metadata = tomlkit.parse(self.payload.with_name('editor.json.aem.toml').read_text(encoding='utf-8'))
        self.assertIn(['nullable'], metadata['deleted'])

    def test_unchanged_json_target_retains_mixed_line_endings(self):
        self.target.parent.mkdir()
        original = b'{\r\n"color":"blue",\n"count":1e0, "private":900719925474099312345\r\n}\n'
        self.target.write_bytes(original)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original)
        self.apply()
        self.assertEqual(self.target.read_bytes(), original)

    def test_exact_numbers_and_literal_keys_survive_apply_collect_export(self):
        text = '{"a.b": 900719925474099312345, "": 0.12345678901234567890123456789, "a": {"b": null}, "quote\\\"\\\\": true, "한글": "값", "array": [1, {"x": null}], "empty": {}}\n'
        self.stage.write_text(text, encoding='utf-8')
        self.apply()
        for path in (self.target, self.stage):
            parsed = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)
            self.assertEqual(parsed['a.b'], 900719925474099312345)
            self.assertEqual(parsed[''], Decimal('0.12345678901234567890123456789'))
            self.assertIsNone(parsed['a']['b'])
            self.assertTrue(parsed['quote"\\'])
            self.assertEqual(parsed['한글'], '값')
        self.call('settings', 'collect', 'editor', '--path', '["a.b"]')
        self.call('export', 'editor')
        self.assertIn(b'900719925474099312345', self.payload.read_bytes())
        self.assertIn(b'0.12345678901234567890123456789', self.payload.read_bytes())

    def test_invalid_actual_is_preserved_even_with_replace(self):
        self.target.parent.mkdir()
        invalid = ['', '[]', 'null', '{"count":1,"count":2}', '{"x":[{"a":1,"a":2}]}',
                   '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1,}',
                   '{/* comment */"x":1}', '{"x":01}', '{"x":1} trailing']
        for text in invalid:
            with self.subTest(text=text):
                self.target.write_text(text, encoding='utf-8')
                before = self.manager().state.path.read_bytes()
                stage = self.stage.read_bytes()
                self.apply('--replace', code=1)
                self.assertEqual(self.target.read_bytes(), text.encode())
                self.assertEqual(self.manager().state.path.read_bytes(), before)
                self.assertEqual(self.stage.read_bytes(), stage)

    def test_collect_requires_explicit_new_fields_and_rejects_conflicts(self):
        self.apply()
        self.edit(self.target, count=2, local=7)
        self.call('settings', 'collect', 'editor')
        self.assertEqual(json.loads(self.stage.read_text(encoding='utf-8'))['count'], 2)
        self.assertNotIn('local', json.loads(self.stage.read_text(encoding='utf-8')))
        self.call('settings', 'collect', 'editor', '--path', '["local"]')
        self.assertEqual(json.loads(self.stage.read_text(encoding='utf-8'))['local'], 7)
        self.apply()
        self.edit(self.stage, color='stage')
        self.edit(self.target, color='actual')
        before = self.stage.read_bytes()
        self.call('settings', 'collect', 'editor', code=1)
        self.assertEqual(self.stage.read_bytes(), before)

    def test_receive_nonoverlap_and_resolve_each_choice(self):
        self.edit(self.stage, color='local')
        self.edit(self.payload, count=2)
        self.call('update', 'editor')
        self.assertEqual(json.loads(self.stage.read_text(encoding='utf-8')), {'color': 'local', 'count': 2})
        for choice, expected in [('shared', 'remote-shared'), ('local', 'local'), ('edited', 'edited')]:
            with self.subTest(choice=choice):
                self.edit(self.stage, color='local')
                self.edit(self.payload, color='remote-' + choice)
                self.call('update', 'editor', code=1)
                self.apply(code=1)
                self.call('export', 'editor', code=1)
                if choice == 'edited':
                    self.edit(self.stage, color='edited')
                self.call('settings', 'resolve', 'editor', '--path', '["color"]', '--take', choice)
                self.assertEqual(json.loads(self.stage.read_text(encoding='utf-8'))['color'], expected)
                self.call('export', 'editor')
                self.apply()
                # Advance the base so the next iteration has two real changes.
                self.edit(self.payload, color='baseline')
                self.call('update', 'editor')

    def test_structural_transitions_protect_unmanaged_descendants(self):
        self.stage.write_text('{"a":{"b":1}}', encoding='utf-8')
        self.apply()
        self.edit(self.target, a={'b': 1, 'private': 5})
        self.stage.write_text('{"a":2}', encoding='utf-8')
        original = self.target.read_bytes()
        self.apply('--replace', code=1)
        self.assertEqual(self.target.read_bytes(), original)
        self.edit(self.target, a={'b': 1})
        self.apply()
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['a'], 2)
        self.stage.write_text('{"a":{"b":{"c":3}}}', encoding='utf-8')
        self.apply()
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['a']['b']['c'], 3)
        self.stage.write_text('{}', encoding='utf-8')
        self.apply()
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8')), {})
        self.assertTrue(self.target.exists())

    def test_previews_and_export_preserve_native_line_endings(self):
        self.apply()
        original = b'{\r\n  "color": "blue",\r\n  "count": 1\r\n}\r\n'
        self.stage.write_bytes(original)
        self.payload.write_bytes(original)
        self.edit(self.target, count=2, local=6)
        for args in [('apply', '--item', 'editor'), ('export', 'editor'),
                     ('settings', 'collect', 'editor', '--path', '["local"]'),
                     ('settings', 'release', 'editor', '--path', '["color"]')]:
            before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.call(*args, '--dry-run', code=1 if args[0] == 'apply' else 0)
            self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
        self.call('export', 'editor')
        self.assertEqual(self.payload.read_bytes(), original)

    def test_automation_receives_applies_and_preserves_conflicts_and_detach(self):
        from agent_env_man.updates import run_settings_updates
        self.settings_policy(trigger=['interval'], min_interval=0)
        self.apply()
        self.edit(self.target, local=5)
        self.edit(self.payload, count=2)
        report, failed = run_settings_updates(self.manager(), 'interval')
        self.assertFalse(failed)
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['count'], 2)
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['local'], 5)
        self.edit(self.target, count=3)
        self.edit(self.payload, count=4)
        original = self.target.read_bytes()
        _, failed = run_settings_updates(self.manager(), 'interval')
        self.assertTrue(failed)
        self.assertEqual(self.target.read_bytes(), original)
        self.call('detach', 'editor')
        report, failed = run_settings_updates(self.manager(), 'interval')
        self.assertFalse(failed)
        self.assertEqual(report[0]['status'], 'detached')
        self.apply('--reattach', '--replace')
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['count'], 4)

    def test_saved_locate_and_detach_without_catalog(self):
        self.catalog.unlink()
        self.assertEqual(Path(self.call('locate', 'editor')['entry']), self.stage)
        before = self.stage.read_bytes()
        self.call('detach', 'editor')
        self.assertTrue(self.call('locate', 'editor')['detached'])
        self.assertEqual(self.stage.read_bytes(), before)
        self.call('recover')

    def test_export_does_not_overwrite_a_stage_edited_after_reading(self):
        manager = self.manager()
        self.edit(self.stage, color='pending')
        writes, record, _ = Settings(manager).export_plan('editor')
        self.edit(self.stage, color='later')
        before = self.payload.read_bytes()
        with self.assertRaises(Error):
            transaction(manager.state, writes, {'editor:settings': record})
        self.assertEqual(self.payload.read_bytes(), before)
        self.assertEqual(json.loads(self.stage.read_text(encoding='utf-8'))['color'], 'later')

    test_state_commit_failure_rolls_back_files_and_comparison_bases = fixtures.SettingsSafety.test_state_commit_failure_rolls_back_files_and_comparison_bases

    def test_group_recovery_refuses_later_user_edits(self):
        self.edit(self.stage, count=2)
        manager = self.manager()
        writes, _, _ = Settings(manager).export_plan('editor')
        entries = []
        for index, (target, content, before) in enumerate(writes):
            backup = target.with_name(target.name + f'.aem-backup-json-{index}')
            if target.exists():
                os.replace(target, backup)
            target.write_bytes(content)
            entries.append({'target': str(target), 'backup': str(backup),
                            'stage': str(target.with_name(f'.aem-stage-json-{index}')),
                            'before': before, 'after': observation(target)})
        manager.state.data['pending'] = {'operation': 'settings-group', 'files': entries}
        manager.state.save()
        first = self.payload.read_bytes()
        self.stage.write_text('{"later":true}', encoding='utf-8')
        with self.assertRaises(Error):
            recover_group(manager.state)
        self.assertEqual(self.payload.read_bytes(), first)
        self.stage.write_bytes(writes[2][1])
        self.call('recover')
        self.assertEqual(json.loads(self.payload.read_text(encoding='utf-8'))['count'], 1)


class JsonMerges(unittest.TestCase):
    @staticmethod
    def bundle(text):
        return Bundle.from_snapshot({'config': text, 'management': ''}, format='json')

    def test_nested_write_refuses_nonobject_parent_without_changing_document(self):
        value = JsonFormat.fields(JsonFormat.parse('{"value": 900719925474099312345}'))[('value',)]
        for parent in ('null', 'false', '1e0', '"private"', '[1, {"child": 2}]'):
            for path in (('parent', 'child'), ('parent', 'nested', 'child')):
                with self.subTest(parent=parent, path=path):
                    original = '{\r\n\t"local" : "\\u0061",\r\n\t"parent" : ' + parent + '\r\n}\n'
                    document = JsonFormat.parse(original)
                    with self.assertRaisesRegex(Error, 'Field structure conflict'):
                        JsonFormat.put(document, path, value)
                    self.assertEqual(JsonFormat.dump(document), original)

    def test_nested_delete_beneath_nonobject_parent_preserves_exact_document(self):
        for parent in ('null', 'false', '1e0', '"private"', '[1, {"child": 2}]'):
            with self.subTest(parent=parent):
                original = '{\r\n "parent":' + parent + ', "local":"\\u0061"\n}\r\n'
                document = JsonFormat.parse(original)
                JsonFormat.put(document, ('parent', 'nested', 'child'), delete=True)
                self.assertEqual(JsonFormat.dump(document), original)

    def test_delete_missing_nested_path_preserves_existing_siblings_and_tokens(self):
        original = '{\r\n\t"parent": { "local":1e0 },\n\t"escaped":"\\u0061"\r\n}\n'
        for path in (('absent', 'child'), ('parent', 'absent', 'child'), ('parent', 'absent')):
            with self.subTest(path=path):
                document = JsonFormat.parse(original)
                JsonFormat.put(document, path, delete=True)
                self.assertEqual(JsonFormat.dump(document), original)

    def test_number_spelling_is_equal_and_boolean_is_distinct(self):
        base = self.bundle('{"n":1,"zero":-0.0,"array":[1,{"x":2}]}')
        local = self.bundle('{"n":1.0,"zero":0,"array":[1.0,{"x":2e0}]}')
        incoming = self.bundle('{"n":1e0,"zero":0e5,"array":[1e0,{"x":2.0}]}')
        result, conflicts = merge(base, local, incoming)
        self.assertFalse(conflicts)
        self.assertEqual(result.snapshot()['config'], local.snapshot()['config'])
        changed = self.bundle('{"n":true,"zero":0,"array":[1,{"x":2}]}')
        result, conflicts = merge(base, local, changed)
        self.assertFalse(conflicts)
        self.assertTrue(json.loads(result.snapshot()['config'])['n'])

    def test_identical_concurrent_edits_and_atomic_arrays(self):
        base = self.bundle('{"array":[1,2],"empty":{},"object":{"x":1,"y":2}}')
        local = self.bundle('{"array":[3,2],"empty":{},"object":{"x":3,"y":2}}')
        same = self.bundle('{"array":[3.0,2],"empty":{},"object":{"y":4,"x":3e0}}')
        result, conflicts = merge(base, local, same)
        self.assertFalse(conflicts)
        self.assertEqual(json.loads(result.snapshot()['config'])['object'], {'x': 3, 'y': 4})
        incoming = self.bundle('{"array":[1,4],"empty":{},"object":{"x":1,"y":2}}')
        _, conflicts = merge(base, local, incoming)
        self.assertEqual(conflicts, [('array',)])

    def test_deletion_and_structural_changes_conflict(self):
        base = self.bundle('{"a":{"b":1}}')
        local = self.bundle('{"a":{"b":2}}')
        incoming = self.bundle('{"a":null}')
        _, conflicts = merge(base, local, incoming)
        self.assertEqual(set(conflicts), {('a',), ('a', 'b')})
        incoming = self.bundle('{}')
        incoming.deleted.add(('a', 'b'))
        _, conflicts = merge(base, local, incoming)
        self.assertEqual(conflicts, [('a', 'b')])

    def test_insertions_and_removals_preserve_other_values(self):
        for text in ['{"a":1,"b":2,"c":3}', '{\n\t"a":1,\n\t"b":2,\n\t"c":3\n}',
                     '{\r\n  "a":1,\r\n  "b":2,\r\n  "c":3\r\n}']:
            for key in ['a', 'b', 'c']:
                with self.subTest(text=text, key=key):
                    bundle = self.bundle(text)
                    bundle.set_operation((key,), ('deleted', None))
                    parsed = json.loads(bundle.snapshot()['config'])
                    self.assertEqual(parsed, {k: v for k, v in {'a': 1, 'b': 2, 'c': 3}.items() if k != key})
                    self.assertEqual(bundle.adapter.dump(bundle.document).count('\r\n'),
                                     bundle.adapter.dump(bundle.document).count('\n') if '\r\n' in text else 0)
        bundle = self.bundle('{\n\t"local" : "\\u0061"\n}\n')
        value = self.bundle('{"v":900719925474099312345}').operations()[('v',)]
        bundle.set_operation(('new', 'nested', ''), value)
        self.assertIn('\n\t"new":', bundle.snapshot()['config'])
        self.assertIn('"local" : "\\u0061"', bundle.snapshot()['config'])
        self.assertEqual(json.loads(bundle.snapshot()['config'])['new']['nested'][''], 900719925474099312345)


class JsonGitSettings(JsonFixture, unittest.TestCase):
    git = fixtures.GitSettings.git

    def setUp(self):
        self.temporary_root()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.git(self.work, 'init', '-b', 'main')
        self.git(self.work, 'config', 'user.name', 'Test User')
        self.git(self.work, 'config', 'user.email', 'test@example.invalid')
        (self.work / 'editor.json').write_text('{"color":"blue","count":1}\n', encoding='utf-8')
        (self.work / 'second.toml').write_text('count=1\n', encoding='utf-8')
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'Initial')
        self.remote = self.root / 'remote.git'
        self.git(self.root, 'clone', '--bare', str(self.work), str(self.remote))
        self.git(self.work, 'remote', 'add', 'origin', str(self.remote))
        self.catalog.write_text(tomlkit.dumps({'version': 2,
            'sources': {'shared': {'type': 'git', 'repository': str(self.remote), 'branch': 'main'}},
            'settings': {'editor': {'source': 'shared', 'path': 'editor.json', 'format': 'json'},
                         'second': {'source': 'shared', 'path': 'second.toml', 'format': 'toml'}}}), encoding='utf-8')
        self.call('bootstrap', str(self.catalog), '--setting-target', f'editor={self.target}',
                  '--setting-target', f'second={self.root / "second-app.toml"}')
        self.checkout = self.root / 'machine.toml.checkouts/.aem-repositories/shared'
        self.payload = self.checkout / 'editor.json'
        self.git(self.checkout, 'config', 'user.name', 'Test User')
        self.git(self.checkout, 'config', 'user.email', 'test@example.invalid')

    def upstream(self, text):
        (self.work / 'editor.json').write_text(text, encoding='utf-8')
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'Upstream change')
        self.git(self.work, 'push', 'origin', 'main')

    def test_publish_mixed_checkout_reports_unselected_json_and_exports_selected(self):
        self.edit(self.stage, count=9)
        report = self.call('publish', 'second', '-m', 'Publish TOML')[0]
        self.assertEqual(report['unpublished_settings'], ['editor'])
        self.assertEqual(json.loads(self.git(self.remote, 'show', 'main:editor.json'))['count'], 1)
        self.call('publish', 'editor', '-m', 'Publish JSON')
        self.assertEqual(json.loads(self.git(self.remote, 'show', 'main:editor.json'))['count'], 9)
        self.assertIn('version = 1', self.git(self.remote, 'show', 'main:editor.json.aem.toml'))
        self.assertFalse(self.target.exists())

    def test_invalid_candidate_refuses_checkout_advance_and_preserves_stage(self):
        before = self.git(self.checkout, 'rev-parse', 'HEAD')
        stage = self.stage.read_bytes()
        self.upstream('{"count":1,"count":2}')
        self.call('update', 'editor', code=1)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.stage.read_bytes(), stage)

    def test_full_automation_prepares_receives_and_applies_json(self):
        from agent_env_man.automation import full_content
        self.upstream('{"color":"remote","count":2}')
        manager = self.manager()
        self.assertFalse(full_content(manager, 30)[1])
        self.assertEqual(json.loads(self.target.read_text(encoding='utf-8'))['color'], 'remote')
        self.call('detach', 'editor')
        before = self.target.read_bytes()
        self.upstream('{"color":"later","count":3}')
        self.assertFalse(full_content(self.manager(), 30)[1])
        self.assertEqual(self.target.read_bytes(), before)
