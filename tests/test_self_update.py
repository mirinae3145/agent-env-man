"""Release updates use local Git fixtures and never change real uv installations."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from types import SimpleNamespace

import tomlkit

from agent_env_man import process_lock, self_update
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, lock
from test_setup import SetupFixture


class Releases(unittest.TestCase):
    def test_worker_capture_preserves_options_and_hides_windows_children(self):
        for platform in ('nt', 'posix'):
            with self.subTest(platform=platform), patch.object(self_update, 'os', SimpleNamespace(name=platform)), patch.object(
                    self_update.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), patch.object(
                    self_update.subprocess, 'run') as run:
                self_update.run_captured(['git', '--version'], capture_output=True, text=True, timeout=30)
                self.assertEqual(run.call_args.kwargs['timeout'], 30)
                self.assertTrue(run.call_args.kwargs['capture_output'])
                if platform == 'nt':
                    self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
                else:
                    self.assertNotIn('creationflags', run.call_args.kwargs)

    def test_installation_lock_is_outside_tools_and_shared_by_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / 'tools'
            tools.mkdir()
            settings = {'tool_dir': str(tools)}
            shared = self_update.installation_lock(settings)
            self.assertEqual(shared, tools.parent / '.tools.aem-update-lock')
            self.assertEqual(shared, self_update.installation_lock(
                {'tool_dir': str(tools / '..' / 'tools')}))
            self.assertNotEqual(shared, self_update.installation_lock(
                {'tool_dir': str(tools.parent / 'other-tools')}))
            with lock(shared):
                self.assertEqual(list(tools.iterdir()), [])
                with self.assertRaises(Error):
                    with lock(self_update.installation_lock(settings)):
                        self.fail('Shared installation lock did not serialize callers')
            self.assertIsNone(self_update.installation_lock({}))

    @unittest.skipUnless(shutil.which('uv'), 'uv is required for tool discovery regression')
    def test_uv_tool_list_with_persistent_installation_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / 'tools'
            tools.mkdir()
            shared = self_update.installation_lock({'tool_dir': str(tools)})
            environment = dict(os.environ, UV_TOOL_DIR=str(tools),
                               UV_CACHE_DIR=str(Path(directory) / 'cache'))
            with lock(shared):
                result = subprocess.run([shutil.which('uv'), 'tool', 'list'],
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((shared / 'lock').is_file())
            result = subprocess.run([shutil.which('uv'), 'tool', 'list'],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_semver_boundaries_and_annotated_tags(self):
        refs = '\n'.join(f'{str(i) * 40}\trefs/tags/v{v}' for i, v in enumerate(
            ['0.2.0', '0.2.1', '0.2.10', '0.3.0', '1.0.0', '1.1.0', '1.2.0', '2.0.0', '3.0.0rc1']))
        refs += '\n' + 'a' * 40 + '\trefs/tags/v0.2.10^{}'
        self.assertEqual(self_update.select_release(refs, '0.2.0', 'compatible'),
                         {'version': '0.2.10', 'revision': 'a' * 40})
        self.assertEqual(self_update.select_release(refs, '1.0.0', 'compatible')['version'], '1.2.0')
        self.assertEqual(self_update.select_release(refs, '0.2.0', 'breaking')['version'], '3.0.0rc1')
        self.assertIsNone(self_update.select_release(refs, '2.0.0', 'compatible'))
        self.assertIsNone(self_update.select_release(refs, '0.2.0', 'off'))
        with self.assertRaises(ValueError):
            self_update.select_release(refs, '0.2.0.dev1', 'compatible')

    def test_prerelease_series_and_numeric_ordering(self):
        versions = ['1.0.0a1', '1.0.0a2', '1.0.0b1', '1.0.0rc1',
                    '1.0.0rc2', '1.0.0rc10', '1.0.0', '1.0.1rc1', '1.1.0']
        refs = '\n'.join('a' * 40 + '\trefs/tags/v' + v for v in versions)
        refs += '\n' + 'b' * 40 + '\trefs/tags/v1.0.0rc10^{}'
        for baseline, expected in [('1.0.0a1', '1.0.0a2'), ('1.0.0b0', '1.0.0b1'),
                                   ('1.0.0rc1', '1.0.0rc10'), ('1.0.0', '1.1.0')]:
            with self.subTest(baseline=baseline):
                self.assertEqual(self_update.select_release(refs, baseline, 'compatible')['version'], expected)
        self.assertEqual(self_update.select_release(refs, '1.0.0rc1', 'compatible')['revision'], 'b' * 40)
        self.assertIsNone(self_update.select_release(refs, '1.0.0rc10', 'compatible'))
        self.assertIsNone(self_update.select_release(refs, '1.0.0rc1', 'off'))
        self.assertEqual(self_update.select_release(refs, '1.0.0rc10', 'breaking')['version'], '1.1.0')
        finals = 'a' * 40 + '\trefs/tags/v1.0.0'
        self.assertEqual(self_update.select_release(finals, '1.0.0rc10', 'breaking')['version'], '1.0.0')
        for invalid in ['1.0.0rc01', '1.0.0.dev1', '1.0.0.post1',
                        '1.0.0+local', '1.0.0-preview.1', '01.0.0a1', None]:
            with self.subTest(invalid=invalid):
                self.assertIsNone(self_update.release_version(invalid))

    def test_omitted_prerelease_number_is_zero(self):
        for label in ('a', 'b', 'rc'):
            with self.subTest(label=label):
                bare = '1.0.0' + label
                zero, next_version = bare + '0', bare + '1'
                self.assertEqual(self_update.release_version(bare), self_update.release_version(zero))
                refs = 'a' * 40 + '\trefs/tags/v' + bare
                self.assertIsNone(self_update.select_release(refs, zero, 'compatible'))
                self.assertEqual(self_update.select_release(refs, '0.9.0', 'breaking')['version'], bare)
                refs += '\n' + 'b' * 40 + '\trefs/tags/v' + next_version
                self.assertEqual(self_update.select_release(refs, bare, 'compatible')['version'], next_version)

    def test_equivalent_zero_tags_keep_peeled_commit_of_selected_spelling(self):
        lines = ['a' * 40 + '\trefs/tags/v1.0.0rc',
                 'b' * 40 + '\trefs/tags/v1.0.0rc^{}',
                 'c' * 40 + '\trefs/tags/v1.0.0rc0',
                 'd' * 40 + '\trefs/tags/v1.0.0rc0^{}']
        for refs in ('\n'.join(lines), '\n'.join(reversed(lines))):
            self.assertEqual(self_update.select_release(refs, '0.9.0', 'breaking'),
                             {'version': '1.0.0rc0', 'revision': 'd' * 40})

    def test_semver_prerelease_tags_convert_to_package_versions(self):
        for label, pre in [('alpha', 'a'), ('beta', 'b'), ('rc', 'rc')]:
            with self.subTest(label=label):
                refs = 'a' * 40 + '\trefs/tags/v1.0.0-' + label
                self.assertEqual(self_update.select_release(refs, '0.5.3', 'breaking')['version'], '1.0.0' + pre + '0')
                self.assertIsNone(self_update.select_release(refs, '1.0.0' + pre + '0', 'compatible'))
                refs += '\n' + 'b' * 40 + '\trefs/tags/v1.0.0-' + label + '.10'
                refs += '\n' + 'c' * 40 + '\trefs/tags/v1.0.0-' + label + '.10^{}'
                self.assertEqual(self_update.select_release(refs, '1.0.0' + pre, 'compatible'),
                                 {'version': '1.0.0' + pre + '10', 'revision': 'c' * 40})
        for invalid in ['1.0.0-preview', '1.0.0-beta.01', '1.0.0-beta.x', '1.0.0-beta.1.2', '1.0.0-beta1']:
            with self.subTest(invalid=invalid):
                self.assertIsNone(self_update.tag_version(invalid))

    def test_equivalent_python_and_semver_tags_prefer_python_commit(self):
        lines = ['a' * 40 + '\trefs/tags/v1.0.0-beta',
                 'b' * 40 + '\trefs/tags/v1.0.0-beta^{}',
                 'c' * 40 + '\trefs/tags/v1.0.0b0',
                 'd' * 40 + '\trefs/tags/v1.0.0b0^{}']
        for refs in ('\n'.join(lines), '\n'.join(reversed(lines))):
            self.assertEqual(self_update.select_release(refs, '0.5.3', 'breaking'),
                             {'version': '1.0.0b0', 'revision': 'd' * 40})

    def test_configuration_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'machine.toml'
            for settings in ({'mode': 'stable'}, {'mode': 'compatible'}, {'other': True},
                             {'python': 'relative'}, {'repository': '-remote'}, {'repository': 'git@host'}, {'mode': []},
                             {'python': str(Path(directory) / 'tools/python'), 'tool_dir': str(Path(directory) / 'tools')}):
                with self.subTest(settings=settings), self.assertRaises(Error):
                    Config(path, document={'version': 1, 'self_update': settings})
            Config(path, document={'version': 1, 'self_update': {'mode': 'off'}})


class OriginalWorker(unittest.TestCase):
    """Exercise source worker policy under real locks, alongside copied-worker tests."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-original-worker-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'machine.toml'
        self.state_dir = self.root / 'machine.toml.state'
        self.result = self.state_dir / 'self-update.json'
        self.directory = self.state_dir / 'self-update-worker' / 'request-token'
        self.request_path = self.directory / 'request.json'
        self.settings = {'mode': 'compatible', 'tool_dir': str(self.root / 'tools'),
                         'bin_dir': str(self.root / 'bin')}
        self.document = {'version': 1, 'self_update': self.settings}
        self.request = {'token': 'request-token', 'parent_pid': 123, 'config': str(self.config),
                        'settings': self.settings, 'saved_settings': dict(self.settings)}
        self.records = {}

    def run_worker(self, *, parent_exited=True, outcome=None, run=None, perform_error=None,
                   pending=None, result_token='request-token'):
        self.config.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self_update.write_json(self.state_dir / 'state.json', {'items': self.records, 'pending': pending})
        self_update.write_json(self.request_path, self.request)
        self_update.write_json(self.result, {'token': result_token, 'status': 'queued'})
        with patch.dict(sys.modules, {'process_lock': process_lock}), \
                patch.object(self_update, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO()))), \
                patch.object(self_update, 'wait_for_parent', return_value=parent_exited), \
                patch.object(self_update, 'check_official_skills'), \
                patch.object(self_update, 'perform', return_value=outcome or {'status': 'updated'},
                             side_effect=perform_error) as perform, \
                patch.object(self_update.subprocess, 'run', side_effect=run) as subprocess_run:
            self_update.worker(self.request_path)
        self.assertFalse(self.directory.exists(), 'Worker request was not cleaned up')
        return self_update.read_result(self.result), perform, subprocess_run

    def test_superseded_request_and_pending_recovery_do_not_replace(self):
        result, perform, run = self.run_worker(result_token='new-request')
        self.assertEqual(result, {'token': 'new-request', 'status': 'queued'})
        perform.assert_not_called()
        run.assert_not_called()
        result, perform, run = self.run_worker(pending={})
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'Recovery is pending')
        perform.assert_not_called()
        run.assert_not_called()

    def test_unconfirmed_parent_and_changed_policy_block_replacement(self):
        result, perform, run = self.run_worker(parent_exited=False)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('process exit', result['error'])
        perform.assert_not_called()
        run.assert_not_called()
        self.document['self_update'] = {'mode': 'off'}
        result, perform, _ = self.run_worker()
        self.assertEqual(result['status'], 'cancelled')
        perform.assert_not_called()

    def test_changed_automation_cancels_automatic_and_full_requests(self):
        for full in (False, True):
            with self.subTest(full=full):
                self.request.update({'automatic': not full, 'full': full,
                                     'saved_automation': {'mode': 'full'}})
                self.document['automation'] = {'mode': 'off'}
                result, perform, run = self.run_worker()
                self.assertEqual(result['status'], 'cancelled')
                perform.assert_not_called()
                run.assert_not_called()

    def test_changed_full_skip_policy_cancels_worker(self):
        self.request.update({'full': True, 'saved_automation': {'mode': 'full'}})
        self.document['automation'] = {'mode': 'full', 'skip_unsupported': True}
        result, perform, run = self.run_worker()
        self.assertEqual(result['status'], 'cancelled')
        perform.assert_not_called()
        run.assert_not_called()

    def test_replacement_failures_do_not_persist_subprocess_credentials(self):
        errors = (ValueError('metadata mismatch'), OSError('secret credential'),
                  subprocess.CalledProcessError(1, ['secret credential'], stderr='secret credential'))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                result, _, run = self.run_worker(perform_error=error)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('secret credential', json.dumps(result))
                run.assert_not_called()

    def test_refresh_runs_after_unlock_and_records_success(self):
        self.records = {'official': {'official_skill': True, 'agent': 'codex'}}
        self.document['agents'] = {'codex': {}}
        def refresh(command, **kwargs):
            self.assertIn('_self-skill-refresh', command)
            # The fresh CLI needs both locks; taking them here checks the
            # handoff rather than just observing mock acquisition calls.
            with process_lock.lock(self_update.installation_lock(self.settings)), process_lock.lock(self.state_dir):
                pass
            return subprocess.CompletedProcess(command, 0, stdout='{"official_skills": {}}')
        result, perform, run = self.run_worker(run=refresh)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['stages']['official_skill']['status'], 'completed')
        perform.assert_called_once()
        run.assert_called_once()

    def full_request(self):
        self.document['automation'] = {'mode': 'full'}
        self.request.update({'full': True, 'saved_automation': {'mode': 'full'}})

    def test_refresh_failure_blocks_full_continuation(self):
        self.full_request()
        self.records = {'official': {'official_skill': True, 'agent': 'codex'}}
        self.document['agents'] = {'codex': {}}
        for response in (subprocess.CompletedProcess([], 1),
                         subprocess.CompletedProcess([], 0, stdout='invalid JSON'),
                         OSError('secret credential')):
            with self.subTest(response=type(response).__name__):
                def fail(command, **kwargs):
                    self.assertIn('_self-skill-refresh', command)
                    if isinstance(response, Exception):
                        raise response
                    return response
                result, _, run = self.run_worker(run=fail)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['stages']['official_skill']['status'], 'failed')
                self.assertNotIn('secret credential', json.dumps(result))
                run.assert_called_once()

    def test_disabled_tool_still_continues_full_automation_after_unlock(self):
        self.full_request()
        self.settings['mode'] = 'off'
        self.request['saved_settings'] = dict(self.settings)
        def continue_full(command, **kwargs):
            self.assertIn('_full-run', command)
            with process_lock.lock(self_update.installation_lock(self.settings)), process_lock.lock(self.state_dir):
                result = self_update.read_result(self.result)
                self.assertEqual(result['stages']['tool']['status'], 'disabled')
                self_update.write_json(self.result, {**result, 'status': 'completed'})
            return subprocess.CompletedProcess(command, 0)
        result, perform, run = self.run_worker(run=continue_full)
        self.assertEqual(result['status'], 'completed')
        perform.assert_not_called()
        run.assert_called_once()

    def test_failed_continuation_preserves_result_written_by_new_request(self):
        self.full_request()
        for replace_token in (False, True):
            with self.subTest(replace_token=replace_token):
                def fail(command, **kwargs):
                    if replace_token:
                        self_update.write_json(self.result, {'token': 'new-request', 'status': 'queued'})
                    return subprocess.CompletedProcess(command, 1)
                result, _, _ = self.run_worker(run=fail)
                self.assertEqual(result['status'], 'queued' if replace_token else 'failed')
                self.assertEqual(result['token'], 'new-request' if replace_token else 'request-token')

    def test_refresh_success_precedes_full_continuation(self):
        self.full_request()
        self.records = {'official': {'official_skill': True, 'agent': 'codex'}}
        self.document['agents'] = {'codex': {}}
        commands = []
        def fresh_cli(command, **kwargs):
            with process_lock.lock(self_update.installation_lock(self.settings)), process_lock.lock(self.state_dir):
                result = self_update.read_result(self.result)
                if '_self-skill-refresh' in command:
                    commands.append('refresh')
                    return subprocess.CompletedProcess(command, 0, stdout='{}')
                commands.append('continue')
                self.assertEqual(result['stages']['official_skill']['status'], 'completed')
                self_update.write_json(self.result, {**result, 'status': 'completed'})
                return subprocess.CompletedProcess(command, 0)
        result, _, _ = self.run_worker(run=fresh_cli)
        self.assertEqual(commands, ['refresh', 'continue'])
        self.assertEqual(result['status'], 'completed')

    def test_continuation_launch_failure_is_recorded_without_credentials(self):
        self.full_request()
        def fail(command, **kwargs):
            raise OSError('secret credential')
        result, _, _ = self.run_worker(run=fail)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'Fresh AEM continuation failed')
        self.assertNotIn('secret credential', json.dumps(result))


class ParentExit(unittest.TestCase):
    def test_posix_parent_waits_until_reparenting_or_timeout(self):
        with patch.object(self_update, 'os', SimpleNamespace(name='posix', getppid=Mock(side_effect=[123, 1]))), \
                patch.object(self_update.time, 'sleep') as sleep:
            self.assertTrue(self_update.wait_for_parent(123))
            sleep.assert_called_once()
        with patch.object(self_update, 'os', SimpleNamespace(name='posix', getppid=lambda: 123)), \
                patch.object(self_update.time, 'monotonic', side_effect=[0, self_update.TIMEOUT]):
            self.assertFalse(self_update.wait_for_parent(123))
        self.assertTrue(self_update.wait_for_parent(0))

    def test_mocked_windows_parent_exit_closes_handle_on_all_wait_outcomes(self):
        import ctypes
        for wait_result in (0, 258, 0xFFFFFFFF, OSError('wait failed')):
            with self.subTest(wait_result=wait_result):
                kernel = SimpleNamespace(OpenProcess=Mock(return_value=42),
                                         WaitForSingleObject=Mock(), CloseHandle=Mock())
                if isinstance(wait_result, Exception):
                    kernel.WaitForSingleObject.side_effect = wait_result
                else:
                    kernel.WaitForSingleObject.return_value = wait_result
                with patch.object(self_update, 'os', SimpleNamespace(name='nt')), \
                        patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
                    if isinstance(wait_result, Exception):
                        with self.assertRaises(OSError):
                            self_update.wait_for_parent(123)
                    else:
                        self.assertEqual(self_update.wait_for_parent(123), wait_result == 0)
                kernel.OpenProcess.assert_called_once_with(0x00100000, False, 123)
                kernel.WaitForSingleObject.assert_called_once_with(42, self_update.TIMEOUT * 1000)
                kernel.CloseHandle.assert_called_once_with(42)

    def test_mocked_windows_missing_parent_distinguishes_invalid_pid_from_denial(self):
        import ctypes
        for error in (87, 5):
            with self.subTest(error=error):
                kernel = SimpleNamespace(OpenProcess=Mock(return_value=0),
                                         WaitForSingleObject=Mock(), CloseHandle=Mock())
                with patch.object(self_update, 'os', SimpleNamespace(name='nt')), \
                        patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                        patch.object(ctypes, 'get_last_error', return_value=error, create=True):
                    self.assertEqual(self_update.wait_for_parent(123), error == 87)
                kernel.WaitForSingleObject.assert_not_called()
                kernel.CloseHandle.assert_not_called()


class SelfUpdate(SetupFixture):
    def register(self, mode='compatible'):
        self.tools = self.root / 'uv tools'
        self.bin = self.root / 'uv bin'
        self.uv = self.root / 'fake-uv'
        self.uv.write_text('fake')
        self.settings = {'mode': mode, 'repository': str(self.repo), 'python': sys.executable,
                         'uv': str(self.uv), 'tool_dir': str(self.tools), 'bin_dir': str(self.bin)}
        options = ['--self-update', mode]
        for field, value in self.settings.items():
            if field != 'mode':
                options += ['--update-' + field.replace('_', '-'), value]
        self.setup_cli('--shell', 'bash', *options)
        return Config(self.config)

    def executable_fake_uv(self):
        """Run the fake installer through Python on Windows, without a shebang."""
        if os.name == 'nt':
            script = self.uv.with_suffix('.py')
            self.uv.rename(script)
            self.uv = self.uv.with_suffix('.cmd')
            self.uv.write_text('@echo off\n"' + sys.executable + '" "' + str(script) + '" %*\n')
            self.settings['uv'] = str(self.uv)
            self.setup_cli('--update-uv', str(self.uv))
        else:
            self.uv.chmod(0o755)
        self.uv_script = script if os.name == 'nt' else self.uv
        return Config(self.config)

    def finish_worker(self, config):
        # In-process tests close the lifetime pipe while their test runner
        # remains alive; model a terminated requester before releasing EOF.
        attempt = self_update.read_result(self_update.result_path(config))
        request_path = config.state_dir / 'self-update-worker' / attempt['token'] / 'request.json'
        request = json.loads(request_path.read_text())
        request['parent_pid'] = 0
        self_update.write_json(request_path, request)
        self_update.close_workers()

    def release(self, value, *, tag=None, name='agent-env-man'):
        (self.repo / 'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "{value}"\n')
        self.commit(self.repo)
        self.git(self.repo, 'tag', tag or 'v' + value)

    def test_settings_preserved_changed_and_preview_read_only(self):
        config = self.register()
        self.setup_cli('--shell', 'zsh')
        self.assertEqual(Config(self.config).doc['self_update'], self.settings)
        before = self.config.read_bytes()
        self.setup_cli('--self-update', 'breaking', '--dry-run')
        self.assertEqual(self.config.read_bytes(), before)
        self.setup_cli('--self-update', 'off')
        self.assertEqual(self.run_cli('self', 'status')['mode'], 'off')
        self.assertFalse(self_update.result_path(config).exists())
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('self', 'update', '--dry-run')
            spawn.assert_not_called()
        self.assertFalse(self_update.result_path(config).exists())

    def test_startup_queue_throttle_and_explicit_retry(self):
        config = self.register()
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            self.assertEqual(spawn.call_count, 1)
            self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'queued')
            self.run_cli('startup', '--trigger', 'agent-start')
            self.assertEqual(spawn.call_count, 1)
            self.run_cli('self', 'update')
            self.assertEqual(spawn.call_count, 2)
        self_update.close_workers()
        self.catalog.write_text('broken TOML [')
        # Self commands remain independent of content declaration validity.
        self.assertEqual(self.run_cli('self', 'status')['mode'], 'compatible')

    def test_spawn_failure_is_recorded_and_throttled(self):
        config = self.register()
        with patch('agent_env_man.self_update.subprocess.Popen', side_effect=OSError('cannot launch')):
            self.run_cli('startup', '--trigger', 'agent-start')
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'failed')
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            spawn.assert_not_called()

    def test_missing_external_runtime_failure_is_throttled(self):
        config = self.register()
        self.uv.unlink()
        self.run_cli('startup', '--trigger', 'agent-start')
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'failed')
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertEqual(State(config.state_dir).data['startup']['self_update']['status'], 'throttled')

    def test_release_metadata_verified_and_commit_pinned(self):
        self.register()
        self.release('0.2.1')
        self.release('0.3.0')
        calls = []
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == str(self.uv):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, stdout='agent-env-man v0.2.0\n - aem\n')
            return real_run(command, **kwargs)
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run):
            outcome = self_update.perform({'settings': self.settings})
        self.assertEqual(outcome['version'], '0.2.1')
        install, options = calls[-1]
        self.assertIn('@' + outcome['revision'], install[-2])
        self.assertEqual(options['env']['UV_TOOL_DIR'], str(self.tools))
        self.assertEqual(options['env']['UV_TOOL_BIN_DIR'], str(self.bin))
        self.release('0.2.2', tag='v0.2.3')
        calls.clear()
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run), self.assertRaises(ValueError):
            self_update.perform({'settings': self.settings})
        self.assertEqual(len(calls), 1)  # Metadata failure never reaches install.

    def test_copied_worker_updates_only_same_prerelease_series(self):
        config = self.register()
        for value in ['1.0.0rc2', '1.0.0rc10', '1.0.0', '1.1.0rc1']:
            self.release(value)
        calls = self.root / 'pre-uv-calls.json'
        self.uv.write_text('#!' + sys.executable + '\nimport json, sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v1.0.0rc1\\n - aem")\n'
                           'else:\n Path(' + repr(str(calls)) + ').write_text(json.dumps(sys.argv[1:]))\n')
        config = self.executable_fake_uv()
        attempt = self_update.schedule(config)
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['token'], attempt['token'])
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['version'], '1.0.0rc10')
        command = json.loads(calls.read_text())
        self.assertIn('install', command)
        self.assertIn('@' + result['revision'], command[-2])

    def test_implicit_zero_tag_and_metadata_equivalence(self):
        self.register('breaking')
        calls = []
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == str(self.uv):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout='agent-env-man v0.2.0\n - aem\n')
            return real_run(command, **kwargs)
        for package, tag in [('1.0.0b0', 'v1.0.0b'), ('1.0.0rc', 'v1.0.0rc0')]:
            with self.subTest(package=package, tag=tag):
                self.release(package, tag=tag)
                calls.clear()
                with patch('agent_env_man.self_update.subprocess.run', side_effect=run):
                    outcome = self_update.perform({'settings': self.settings})
                self.assertEqual(outcome['version'], tag[1:])
                self.assertIn('@' + outcome['revision'], calls[-1][-2])
        self.release('1.1.0rc1', tag='v1.1.0rc')
        calls.clear()
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run), self.assertRaises(ValueError):
            self_update.perform({'settings': self.settings})
        self.assertEqual(len(calls), 1)

    def test_copied_worker_converts_semver_beta_tag(self):
        config = self.register()
        self.release('1.0.0b1', tag='v1.0.0-beta.1')
        self.release('1.0.0rc1', tag='v1.0.0-rc.1')
        calls = self.root / 'semver-uv-calls.json'
        self.uv.write_text('#!' + sys.executable + '\nimport json, sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v1.0.0b0\\n - aem")\n'
                           'else:\n Path(' + repr(str(calls)) + ').write_text(json.dumps(sys.argv[1:]))\n')
        config = self.executable_fake_uv()
        self_update.schedule(config)
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['version'], '1.0.0b1')
        self.assertIn('@' + result['revision'], json.loads(calls.read_text())[-2])

    def test_actual_installed_version_prevents_cross_config_downgrade(self):
        self.register()
        self.release('0.2.1')
        self.release('0.3.0')
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == str(self.uv):
                self.assertEqual(command[-1], 'list')
                return subprocess.CompletedProcess(command, 0, stdout='agent-env-man v0.3.0\n')
            return real_run(command, **kwargs)
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run):
            self.assertEqual(self_update.perform({'settings': self.settings, 'current': '0.2.0'}),
                             {'status': 'up-to-date'})

    def test_worker_waits_for_parent_then_updates_with_local_git(self):
        config = self.register()
        self.release('0.2.1')
        calls = self.root / 'uv-calls.json'
        self.uv.write_text('#!' + sys.executable + '\nimport json, sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v0.2.0\\n - aem")\n'
                           'else:\n Path(' + repr(str(calls)) + ').write_text(json.dumps(sys.argv[1:]))\n')
        config = self.executable_fake_uv()
        # Real lifetime pipe: worker must do no update until it receives EOF.
        with lock(config.state_dir):
            attempt = self_update.schedule(config)
        child = self_update._children[-1]
        time.sleep(0.15)
        self.assertFalse(calls.exists())
        self.assertIsNone(child.poll())
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['token'], attempt['token'])
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['version'], '0.2.1')
        self.assertIn('install', json.loads(calls.read_text()))

    def test_installation_lock_serializes_configs_and_startup_is_fail_open(self):
        config = self.register()
        with lock(self_update.installation_lock(self.settings)):
            self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start'), {})
            self.run_cli('self', 'update', code=1)
        self.assertFalse(self_update.result_path(config).exists())

    def test_corrupt_attempt_clock_fails_open_without_launching(self):
        config = self.register()
        self_update.write_json(self_update.result_path(config), {'time': 'invalid'})
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            spawn.assert_not_called()
        self.assertEqual(State(config.state_dir).data['startup']['self_update']['status'], 'failed')

    def test_worker_failure_recorded_and_explicit_retry_succeeds(self):
        config = self.register()
        self.release('0.2.1')
        self.uv.write_text('#!' + sys.executable + '\nimport sys\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v0.2.0")\n'
                           'else:\n sys.exit(1)\n')
        config = self.executable_fake_uv()
        self_update.schedule(config)
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'failed')
        self.uv_script.write_text(self.uv_script.read_text().replace('sys.exit(1)', 'sys.exit(0)'))
        # Exercise the real entrypoint: stdout must finish without waiting on
        # worker-owned handles, and the external child outlives the callback.
        response = subprocess.run([sys.executable, '-m', 'agent_env_man', '--json', '--config', str(self.config),
                                   'self', 'update'], capture_output=True, text=True, timeout=5)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['status'], 'queued')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self_update.read_result(self_update.result_path(config))
            if result.get('status') != 'queued':
                break
            time.sleep(0.02)
        self.assertEqual(result['status'], 'updated')

    def test_queued_worker_cancels_for_pending_recovery(self):
        config = self.register()
        self_update.schedule(config)
        child = self_update._children[-1]
        state = State(config.state_dir)
        state.data['pending'] = {}  # Even an empty journal blocks replacement.
        state.save()
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'Recovery is pending')

    def test_queued_worker_cancels_when_policy_changes(self):
        config = self.register()
        with lock(config.state_dir):
            self_update.schedule(config)
        child = self_update._children[-1]
        self.setup_cli('--self-update', 'off')
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'cancelled')


class InstallerChoices(SetupFixture):
    def module(self):
        spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'scripts/setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_initial_prompt_and_repeat_preserves_selection(self):
        module = self.module()
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            output = str(self.root / 'tools') if command[-1] == 'dir' else str(self.executable.parent)
            return subprocess.CompletedProcess(command, 0, stdout=output)
        with patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n), \
                patch.object(module.subprocess, 'run', side_effect=run), \
                patch.object(module.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', side_effect=['policies', 'invalid', 'compatible']) as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config)]), 0)
            self.assertEqual(prompt.call_count, 3)
        self.assertIn('compatible', calls[-1])
        self.config.write_text('version = 1\n[self_update]\nmode = "breaking"\nrepository = "https://example.test/aem.git"\n')
        with patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n), \
                patch.object(module.subprocess, 'run', side_effect=run), patch('builtins.input') as prompt:
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config)]), 0)
            prompt.assert_not_called()
        self.assertNotIn('--self-update', calls[-1])
        self.assertNotIn('--update-repository', calls[-1])

    def test_installer_forwards_full_mode_and_shared_clock_options(self):
        module = self.module()
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=str(self.root / 'tools'))
        with patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n), \
                patch.object(module.subprocess, 'run', side_effect=run), patch('builtins.input') as prompt:
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config), '--automation', 'full',
                                         '--self-update', 'off', '--automation-trigger', 'interval',
                                         '--automation-interval', '600']), 0)
            prompt.assert_not_called()
        command = calls[-1]
        self.assertEqual(command[command.index('--automation') + 1], 'full')
        self.assertEqual(command[command.index('--automation-trigger') + 1], 'interval')
        self.assertEqual(command[command.index('--automation-interval') + 1], '600.0')

    def test_invalid_installer_flow_options_fail_before_install(self):
        module = self.module()
        with patch.object(module.subprocess, 'run') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(['--automation-timeout', '0']), 1)
            self.assertEqual(module.main(['--automation-trigger', 'manual', '--automation-trigger', 'interval']), 1)
            run.assert_not_called()
